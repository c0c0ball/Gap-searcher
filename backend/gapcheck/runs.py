"""실행 결과 저장과 검토 기록.

- runs/<run_id>/result.json   실행 결과 (불변)
- runs/<run_id>/reviews.jsonl 검토 이벤트 (추가만 가능). AR별 마지막 이벤트가 현재 상태다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .paths import runs_dir

DECISIONS = {"approve", "reject", "request_evidence"}
APPROVED_LABEL = {
    "CANDIDATE_NONCONFORMITY": ("APPROVED_NONCONFORMITY", "결함"),
    "CANDIDATE_CONFORMING": ("APPROVED_CONFORMING", "결함 없음(확인)"),
    "CANDIDATE_PARTIAL": ("APPROVED_INSUFFICIENT", "미확인"),
    "INSUFFICIENT_EVIDENCE": ("APPROVED_INSUFFICIENT", "미확인"),
    "NOT_APPLICABLE_PENDING": ("APPROVED_NOT_APPLICABLE", "해당 없음"),
}


def run_id_of(result: dict) -> str:
    return f"{result['scenario']}-{result['as_of']}-{result['result_hash'][:8]}"


def save_run(result: dict, target: str | None = None) -> str:
    rid = run_id_of(result)
    d = runs_dir() / rid
    d.mkdir(parents=True, exist_ok=True)
    meta = d / "meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({"target": target or result["scenario"]}, ensure_ascii=False), encoding="utf-8")
    p = d / "result.json"
    if not p.exists():  # 같은 해시면 같은 결과 — 덮어쓰지 않는다
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return rid


def _dir(rid: str) -> Path:
    d = (runs_dir() / rid).resolve()
    if d.parent != runs_dir().resolve() or not (d / "result.json").exists():
        raise FileNotFoundError(rid)
    return d


def load_run(rid: str) -> dict:
    return json.loads((_dir(rid) / "result.json").read_text(encoding="utf-8"))


def list_runs() -> list[dict]:
    out = []
    for d in sorted(runs_dir().iterdir(), reverse=True):
        p = d / "result.json"
        if p.exists():
            r = json.loads(p.read_text(encoding="utf-8"))
            m = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
            pl = r.get("plain") or {}
            out.append({"run_id": d.name, "scenario": r["scenario"], "target": m.get("target", r["scenario"]),
                        "organization": r.get("organization"), "as_of": r["as_of"],
                        "generated_at": r["generated_at"], "result_hash": r["result_hash"],
                        "counts": _counts(r), "headline": pl.get("headline", "")})
    return sorted(out, key=lambda x: x["generated_at"], reverse=True)


def _counts(r: dict) -> dict:
    c: dict[str, int] = {}
    for d in r["decisions"]:
        c[d["verdict"]] = c.get(d["verdict"], 0) + 1
    return c


def add_review(rid: str, ar_id: str, decision: str, reviewer: str, comment: str) -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision은 {sorted(DECISIONS)} 중 하나")
    r = load_run(rid)
    dec = next((d for d in r["decisions"] if d["ar_id"] == ar_id), None)
    if dec is None:
        raise KeyError(ar_id)
    if not reviewer.strip():
        raise ValueError("검토자 이름이 필요함")
    if decision != "approve" and not comment.strip():
        raise ValueError("반려·추가자료 요청에는 사유가 필요함")
    if decision == "approve":
        state, label = APPROVED_LABEL[dec["verdict"]]
    elif decision == "reject":
        state, label = "REJECTED", "미확인 (검토 반려)"
    else:
        state, label = "EVIDENCE_REQUESTED", "미확인 (추가 자료 요청)"
    ev = {"ar_id": ar_id, "decision": decision, "state": state, "external_label": label,
          "candidate_verdict": dec["verdict"], "result_hash": r["result_hash"], "reviewer": reviewer,
          "comment": comment, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (_dir(rid) / "reviews.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return ev


def reviews(rid: str) -> tuple[dict[str, dict], list[dict]]:
    p = _dir(rid) / "reviews.jsonl"
    events = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    latest: dict[str, dict] = {}
    for e in events:
        latest[e["ar_id"]] = e
    return latest, events
