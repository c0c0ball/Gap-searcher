"""판정 함수 — 순수함수. 같은 Evaluation이면 언제나 같은 Decision.

순서 (결정 D05)
 1. Scope 확정?        아니면 미확인 / 적용제외 검토
 2. 직접 위반 확인?     있으면 결함 후보 — 범위가 부분이어도
 3. Coverage 충족?     아니면 미확인
 4. 고품질 근거 상충?    있으면 미확인
 5. 적합 경로 충족?     있으면 적합 후보, 일부만이면 부분(외부 미확인)
"""
from __future__ import annotations

from .compiler.schema import AR
from .model import Decision, Evaluation

EXTERNAL_PENDING = {
    "CANDIDATE_NONCONFORMITY": "결함 후보 (검토 대기)",
    "CANDIDATE_CONFORMING": "검토 대기",
    "CANDIDATE_PARTIAL": "미확인",
    "INSUFFICIENT_EVIDENCE": "미확인",
    "NOT_APPLICABLE_PENDING": "미확인 (적용제외 검토 중)",
}


def adjudicate(ar: AR, ev: Evaluation) -> Decision:
    def d(verdict, code, reason, path=None):
        return Decision(ar.id, ev.criterion, verdict, code, reason, EXTERNAL_PENDING[verdict], path)

    if ev.scope == "NOT_APPLICABLE_PENDING":
        return d("NOT_APPLICABLE_PENDING", "SCOPE_NOT_APPLICABLE", ev.scope_detail)
    if ev.scope != "APPLICABLE":
        return d("INSUFFICIENT_EVIDENCE", "SCOPE_INCOMPLETE", ev.scope_detail)
    if ev.violations:
        extra = "" if ev.coverage == "COVERAGE_PASS" else f" (범위 일부 미수집: {ev.coverage_detail})"
        return d("CANDIDATE_NONCONFORMITY", "DIRECT_VIOLATION", f"직접 위반 {len(ev.violations)}건{extra}")
    if ev.coverage != "COVERAGE_PASS":
        return d("INSUFFICIENT_EVIDENCE", ev.coverage, ev.coverage_detail)
    if ev.conflicts:
        return d("INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "; ".join(ev.conflicts))
    for path in ar.conforming_paths:
        if all(ev.tests[t].status == "pass" for t in path):
            return d("CANDIDATE_CONFORMING", "PATH_SATISFIED", f"적합 경로 {path} 모두 통과", path)
    gaps = sorted({f"{t}: {ev.tests[t].detail}" for p in ar.conforming_paths for t in p
                   if ev.tests[t].status in ("gap", "skip")})
    if any(ev.tests[t].status == "pass" for p in ar.conforming_paths for t in p):
        return d("CANDIDATE_PARTIAL", "REQUIRED_EVIDENCE_GAP", "; ".join(gaps))
    return d("INSUFFICIENT_EVIDENCE", "REQUIRED_EVIDENCE_GAP", "; ".join(gaps))
