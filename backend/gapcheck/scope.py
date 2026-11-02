"""Scope Engine: AR의 applicability.when 사실이 모두 확인됐는지 본다. 기본값은 UNKNOWN."""
from __future__ import annotations

from .compiler.schema import AR


def evaluate_scope(ar: AR, facts: dict[str, dict]) -> tuple[str, str]:
    missing, false = [], []
    for f in ar.applicability.when:
        v = facts.get(f)
        if v is None or v.get("value") is None:
            missing.append(f)
        elif v.get("value") is False:
            false.append(f)
    if false:
        return "NOT_APPLICABLE_PENDING", f"적용 조건이 거짓: {false} — 적용제외 승인 필요"
    if missing:
        return "UNKNOWN", f"확인되지 않은 범위 사실: {missing}"
    return "APPLICABLE", "적용 조건 확인: " + ", ".join(
        f"{f}({facts[f].get('basis', '근거 미기재')})" for f in ar.applicability.when)


def test_enabled(when: str | None, facts: dict[str, dict]) -> bool | None:
    """테스트 단위 조건. None = 사실 미확인."""
    if not when:
        return True
    v = facts.get(when, {}).get("value")
    return None if v is None else bool(v)
