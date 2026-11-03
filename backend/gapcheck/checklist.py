"""전체 점검표: 101개 인증기준 × 주요 확인사항마다 상태를 하나로 모은다.

상태 출처 우선순위
  1) 사람 판단 (담당자가 점검표에서 기록) — 가장 최근 기록
  2) 자동 결과 (그 대상의 최근 진단에서 이 확인사항을 다루는 AR들) — 검토 승인이 있으면 승인된 상태
  3) 없으면 '미확인'

상태 값: fix(고칠 것) / ok(규칙대로) / na(해당 없음) / unknown(미확인)
기록은 대상별 assessments/<대상>/events.jsonl 에 추가만 한다. 증적 파일은 같은 폴더 files/ 에 sha256 이름으로 둔다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import catalog, runs
from .ingest.ingest import ingest_bytes
from .paths import repo_root

STATES = {"fix", "ok", "na", "unknown"}
LABEL = {"fix": "고칠 것", "ok": "규칙대로", "na": "해당 없음", "unknown": "미확인"}
VERDICT_TONE = {"CANDIDATE_NONCONFORMITY": "fix", "CANDIDATE_CONFORMING": "ok"}
REVIEW_TONE = {"APPROVED_NONCONFORMITY": "fix", "APPROVED_CONFORMING": "ok", "APPROVED_NOT_APPLICABLE": "na"}
SEVERITY = {"fix": 3, "unknown": 2, "ok": 1, "na": 0}


def _assess_root() -> Path:
    d = Path(os.environ.get("GAPCHECK_ASSESS", repo_root() / "assessments"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tdir(target: str) -> Path:
    key = re.sub(r"[^\w가-힣\-]", "_", target)
    d = _assess_root() / key
    (d / "files").mkdir(parents=True, exist_ok=True)
    return d


def _events(target: str) -> list[dict]:
    p = _tdir(target) / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _ar_checkpoints() -> dict[str, list[tuple[str, list[int]]]]:
    """기준번호 → [(AR id, 다루는 확인사항 번호들)]"""
    out: dict[str, list[tuple[str, list[int]]]] = {}
    for p in sorted((repo_root() / "requirements").rglob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        for ar in doc.get("requirements", []):
            out.setdefault(doc["criterion"], []).append((ar["id"], ar.get("checkpoints", [])))
    return out


def _auto(target: str) -> tuple[str | None, dict[str, dict]]:
    """최근 진단의 AR별 상태. 검토가 있으면 검토 결과를 쓴다."""
    rs = [r for r in runs.list_runs() if r["target"] == target]
    if not rs:
        return None, {}
    rid = rs[0]["run_id"]
    r = runs.load_run(rid)
    latest, _ = runs.reviews(rid)
    plain = {i["ar_id"]: i for i in (r.get("plain") or {}).get("items", [])}
    out = {}
    for d in r["decisions"]:
        rv = latest.get(d["ar_id"])
        if rv and rv["state"] in REVIEW_TONE:
            tone, reviewed = REVIEW_TONE[rv["state"]], True
        else:
            tone, reviewed = VERDICT_TONE.get(d["verdict"], "unknown"), bool(rv)
        out[d["ar_id"]] = {"ar_id": d["ar_id"], "tone": tone, "reviewed": reviewed, "verdict": d["verdict"],
                           "reason": d["reason"], "found": plain.get(d["ar_id"], {}).get("found", [])}
    return rid, out


def _worst(tones: list[str]) -> str:
    if not tones:
        return "unknown"
    if all(t == "na" for t in tones):
        return "na"
    return max(tones, key=lambda t: SEVERITY[t])


def build(target: str) -> dict:
    cat = catalog.load()
    rid, auto = _auto(target)
    ar_map = _ar_checkpoints()
    manual: dict[tuple[str, int], dict] = {}
    files: dict[tuple[str, int], list[dict]] = {}
    for e in _events(target):
        k = (e["criterion"], e["checkpoint"])
        if e["type"] == "judgement":
            manual[k] = e
        elif e["type"] == "evidence":
            files.setdefault(k, []).append(e)
    criteria = []
    for cid in cat["order"]:
        c = cat["items"][cid]
        n = catalog.checkpoint_count(cid)
        cps = []
        for idx in range(1, n + 1):
            ars = [auto[a] for a, cpn in ar_map.get(cid, []) if idx in cpn and a in auto]
            auto_tone = _worst([a["tone"] for a in ars]) if ars else None
            m = manual.get((cid, idx))
            if m:
                state, source = m["state"], "manual"
            elif auto_tone:
                state, source = auto_tone, "auto"
            else:
                state, source = "unknown", "none"
            cps.append({"index": idx, "state": state, "source": source,
                        "auto": {"tone": auto_tone, "ars": ars, "run_id": rid} if ars else None,
                        "manual": m, "files": files.get((cid, idx), []),
                        "covered_by_ar": [a for a, cpn in ar_map.get(cid, []) if idx in cpn]})
        criteria.append({"id": cid, "name": c["name"], "field_id": c["field_id"], "field": c["field"],
                         "area": c["area"], "scope": c["scope"], "print_page": c["print_page"],
                         "state": _worst([x["state"] for x in cps]),
                         "counts": {s: sum(1 for x in cps if x["state"] == s) for s in STATES},
                         "automated": any(x["covered_by_ar"] for x in cps), "checkpoints": cps})
    total = {s: sum(c["counts"][s] for c in criteria) for s in STATES}
    return {"target": target, "run_id": rid, "has_text": cat["has_text"], "criteria": criteria,
            "totals": {"checkpoints": sum(total.values()), **total,
                       "criteria": len(criteria),
                       "criteria_decided": sum(1 for c in criteria if c["counts"]["unknown"] == 0),
                       "criteria_fix": sum(1 for c in criteria if c["state"] == "fix"),
                       "automated_criteria": sum(1 for c in criteria if c["automated"])}}


def record(target: str, cid: str, idx: int, state: str, by: str, comment: str = "") -> dict:
    if state not in STATES:
        raise ValueError(f"state는 {sorted(STATES)} 중 하나")
    if catalog.criterion(cid) is None or not 1 <= idx <= catalog.checkpoint_count(cid):
        raise KeyError(f"{cid} 확인사항 {idx}")
    if not by.strip():
        raise ValueError("판단한 사람 이름이 필요함")
    if state in ("fix", "na") and not comment.strip():
        raise ValueError("'고칠 것'과 '해당 없음'에는 근거나 사유를 적어야 함")
    e = {"type": "judgement", "criterion": cid, "checkpoint": idx, "state": state, "by": by, "comment": comment,
         "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (_tdir(target) / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def attach(target: str, cid: str, idx: int, filename: str, data: bytes, by: str, scanner=None) -> dict:
    if catalog.criterion(cid) is None or not 1 <= idx <= catalog.checkpoint_count(cid):
        raise KeyError(f"{cid} 확인사항 {idx}")
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("20MB를 넘는 파일은 받지 않음")
    name = Path(filename).name
    art = ingest_bytes(name, data, "evidence", scanner)
    d = _tdir(target) / "files"
    (d / f"{art.sha256}{Path(name).suffix.lower()}").write_bytes(data)
    e = {"type": "evidence", "criterion": cid, "checkpoint": idx, "file": name, "sha256": art.sha256,
         "size": art.size, "scan_status": art.scan_status, "by": by,
         "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (_tdir(target) / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def history(target: str, cid: str) -> list[dict]:
    return [e for e in _events(target) if e["criterion"] == cid]


def write_xlsx(target: str, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    data = build(target)
    cat = catalog.load()
    fill = {"fix": "FCECEE", "ok": "E5F4EA", "na": "EEF0F3", "unknown": "FFFFFF"}
    wb = Workbook()
    ws = wb.active
    ws.title = "요약"
    t = data["totals"]
    for row in [("대상", target), ("인증기준", f"{t['criteria']}개 중 판단 완료 {t['criteria_decided']}개, 고칠 것이 있는 기준 {t['criteria_fix']}개"),
                ("주요 확인사항", f"{t['checkpoints']}개: 고칠 것 {t['fix']}, 규칙대로 {t['ok']}, 해당 없음 {t['na']}, 미확인 {t['unknown']}"),
                ("자동 점검", f"자동 규칙이 있는 기준 {t['automated_criteria']}개 (나머지는 담당자 판단)"),
                ("주의", "자동 결과는 후보이며, 담당자 판단과 검토 승인을 거친 내용만 확정으로 본다. 인증 심사 결과를 대신하지 않는다.")]:
        ws.append(row)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 14, 110
    ws2 = wb.create_sheet("점검표")
    head = ["항목", "항목명", "분야", "확인사항", "내용", "상태", "판단 출처", "판단자", "근거·의견", "자동 결과", "증적 파일", "안내서 쪽"]
    ws2.append(head)
    for c in ws2[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="13233A")
    for c in data["criteria"]:
        full = cat["items"][c["id"]]
        texts = full["checkpoints"] if isinstance(full["checkpoints"], list) else []
        for cp in c["checkpoints"]:
            m = cp["manual"] or {}
            auto = cp["auto"]
            ws2.append([c["id"], c["name"], f"{c['field_id']} {c['field']}", cp["index"],
                        texts[cp["index"] - 1] if len(texts) >= cp["index"] else "",
                        LABEL[cp["state"]], {"manual": "담당자", "auto": "자동", "none": "-"}[cp["source"]],
                        m.get("by", ""), m.get("comment", ""),
                        "; ".join(f"{a['ar_id']} {LABEL[a['tone']]}" for a in auto["ars"]) if auto else "",
                        ", ".join(f["file"] for f in cp["files"]), c["print_page"]])
            ws2.cell(ws2.max_row, 6).fill = PatternFill("solid", fgColor=fill[cp["state"]])
    for col, w in zip("ABCDEFGHIJKL", (8, 22, 22, 7, 70, 10, 9, 10, 40, 30, 24, 8)):
        ws2.column_dimensions[col].width = w
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws2.freeze_panes = "E2"
    ws2.auto_filter.ref = ws2.dimensions
    wb.save(path)
