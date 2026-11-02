"""귀속: 위반 1건 = 결함 사실 1건. 대표 기준(primary_criterion)은 정확히 1개 (결정 D06).

related_criteria 는 같은 사실이 다른 기준에도 영향을 줄 때의 참고 연결이다. 보고서의 '심사 관행 보기'는
primary_criterion 기준으로만 결함을 센다.
"""
from __future__ import annotations

from .model import Decision, Evaluation, FindingFact

# 같은 사실이 다른 기준과 맞닿는 경우 (검토자 참고용, 자동 결함 아님)
RELATED = {
    "AR-2.5.4-03": ["2.5.1"],   # 임시 비밀번호 발급은 계정 발급 절차와 연결
}


def attribute(decision: Decision, ev: Evaluation) -> list[FindingFact]:
    if decision.verdict != "CANDIDATE_NONCONFORMITY":
        return []
    facts = []
    for i, v in enumerate(ev.violations, 1):
        facts.append(FindingFact(
            finding_id=f"F-{v.ar_id}-{i:02d}", ar_id=v.ar_id, primary_criterion=ev.criterion,
            related_criteria=RELATED.get(v.ar_id, []), relation="direct_violation",
            subject=v.subject, summary=v.message, obs_ids=v.obs_ids))
    return facts
