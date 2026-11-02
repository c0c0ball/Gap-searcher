"""Q/C/P — 증적 품질(Quality), 범위(Coverage), 출처(Provenance) 점검.

품질 fail 관측은 판정 근거로 쓰지 않는다. warn은 쓰되 보고서에 표시한다.
"""
from __future__ import annotations

from datetime import date, datetime

from .model import Artifact, Observation

FRESH_WARN_DAYS = 7
FRESH_FAIL_DAYS = 30


def apply_quality(obs: list[Observation], artifacts: dict[str, Artifact], as_of: date) -> None:
    for o in obs:
        if o.axis == "document":
            for c in o.citations:
                a = artifacts.get(c.artifact_sha256)
                if a is None:
                    o.quality = "fail"
                    o.quality_reasons.append(f"인용 원본({c.artifact_sha256[:12]})이 등록되지 않음")
                elif a.scan_status != "clean" and o.quality == "pass":
                    o.quality = "warn"
                    o.quality_reasons.append(f"원본 검역 상태: {a.scan_status}")
        if o.axis == "technical":
            ts = o.source.get("collected_at")
            if not ts:
                o.quality, o.quality_reasons = "fail", o.quality_reasons + ["수집 시각 없음"]
                continue
            age = (as_of - datetime.fromisoformat(ts).date()).days
            if age > FRESH_FAIL_DAYS:
                o.quality = "fail"
                o.quality_reasons.append(f"수집 후 {age}일 경과 (>{FRESH_FAIL_DAYS}일)")
            elif age > FRESH_WARN_DAYS and o.quality == "pass":
                o.quality = "warn"
                o.quality_reasons.append(f"수집 후 {age}일 경과")
            if age < 0:
                o.quality = "fail"
                o.quality_reasons.append("수집 시각이 기준일보다 미래")
            if o.source.get("source") == "fixture":
                o.quality_reasons.append("가상 스냅샷(fixture) — 개발용")


def document_coverage(declared: list[dict] | None, parsed: dict[str, int], failed: list[str]) -> tuple[str, str]:
    """declared: scope.yaml의 policy_documents / parsed: file → clause 수"""
    if not declared:
        return "DENOMINATOR_UNKNOWN", "검토 대상 정책 문서 목록(분모)이 없음"
    missing = [d["file"] for d in declared if parsed.get(d["file"], 0) == 0]
    if missing or failed:
        return "PARTIAL_COLLECTION", f"미수용·파싱 실패 문서: {sorted(set(missing + failed))}"
    return "COVERAGE_PASS", f"정책 문서 {len(declared)}건 모두 정규화"
