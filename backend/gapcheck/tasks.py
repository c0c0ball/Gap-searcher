"""담당자별 할 일: 실행 결과의 쉬운 설명에서 '고칠 부분'을 담당자 단위로 펼친다.

- 할 일 ID = <AR>:<담당자>. 담당자 문자열 'A · B'는 두 사람 몫으로 나눈다.
- 완료 체크는 실행 폴더의 tasks.jsonl 에 이벤트로 쌓는다 (마지막 이벤트가 현재 상태).
- 완료 체크는 '조치했다'는 자기 신고일 뿐이다. 실제로 고쳐졌는지는 다음 실행이 확인한다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .runs import _dir, load_run, reviews


def _owners(s: str) -> list[str]:
    return [o.strip() for o in re.split(r"\s*·\s*|\s*,\s*", s) if o.strip()]


def task_list(rid: str) -> list[dict]:
    r = load_run(rid)
    pl = r.get("plain") or {"items": []}
    latest, _ = reviews(rid)
    state = _state(rid)
    out = []
    for it in pl["items"]:
        if not it["fix"]:
            continue
        rv = latest.get(it["ar_id"])
        if rv and rv["state"] in ("REJECTED",):
            continue  # 검토에서 반려된 결과는 할 일로 내보내지 않는다
        for owner in _owners(it["owner"]):
            tid = f"{it['ar_id']}:{owner}"
            st = state.get(tid, {})
            out.append({"task_id": tid, "run_id": rid, "ar_id": it["ar_id"], "owner": owner,
                        "question": it["question"], "found": it["found"], "fix": it["fix"], "why": it["why"],
                        "confirmed": bool(rv and rv["state"] == "APPROVED_NONCONFORMITY"),
                        "done": st.get("done", False), "done_by": st.get("by"), "done_at": st.get("at"),
                        "memo": st.get("memo", "")})
    return out


def _state(rid: str) -> dict[str, dict]:
    p = _dir(rid) / "tasks.jsonl"
    st: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                st[e["task_id"]] = e
    return st


def set_done(rid: str, task_id: str, done: bool, by: str, memo: str = "") -> dict:
    if task_id not in {t["task_id"] for t in task_list(rid)}:
        raise KeyError(task_id)
    if not by.strip():
        raise ValueError("처리한 사람 이름이 필요함")
    e = {"task_id": task_id, "done": done, "by": by, "memo": memo,
         "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    with (_dir(rid) / "tasks.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def by_owner(tasks: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in tasks:
        groups.setdefault(t["owner"], []).append(t)
    return [{"owner": o, "total": len(ts), "done": sum(t["done"] for t in ts), "tasks": ts}
            for o, ts in sorted(groups.items(), key=lambda kv: (-sum(not t["done"] for t in kv[1]), kv[0]))]
