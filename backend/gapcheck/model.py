"""파이프라인 전 단계가 주고받는 자료형. 모두 JSON으로 직렬화 가능해야 한다 (결정성·계보)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ScanStatus = Literal["clean", "infected", "error", "not_scanned"]
QStatus = Literal["pass", "warn", "fail"]
CoverageStatus = Literal["COVERAGE_PASS", "PARTIAL_COLLECTION", "DENOMINATOR_UNKNOWN", "NOT_REQUIRED"]
Verdict = Literal[
    "CANDIDATE_CONFORMING",
    "CANDIDATE_PARTIAL",
    "CANDIDATE_NONCONFORMITY",
    "INSUFFICIENT_EVIDENCE",
    "NOT_APPLICABLE_PENDING",
]


@dataclass
class Artifact:
    """업로드·수집된 원본 1개. sha256이 계보의 뿌리다."""
    artifact_id: str
    path: str                 # 시나리오 기준 상대 경로 또는 저장소 키
    sha256: str
    size: int
    kind: str                 # policy_document | screen_capture | aws_snapshot_file | list
    scan_status: ScanStatus = "not_scanned"
    scan_detail: str = ""


@dataclass
class Clause:
    """정규화된 문서 조각. locator는 사람이 원문을 다시 찾을 수 있는 위치다."""
    clause_id: str            # 예: A-ISG-004#제5조-①-1
    doc_id: str
    artifact_sha256: str
    article: str              # 예: 제5조(비밀번호 작성규칙)
    label: str                # 예: ①-1
    text: str
    parent_text: str = ""     # 호(1.)의 경우 상위 항 문장
    order: int = 0

    @property
    def locator(self) -> str:
        return f"{self.doc_id} {self.article} {self.label}".strip()


@dataclass
class Citation:
    artifact_sha256: str
    locator: str
    quote: str
    clause_id: str = ""
    verified: bool = False


@dataclass
class Observation:
    obs_id: str
    axis: Literal["document", "evidence", "technical", "inquiry"]
    kind: str                 # doc_param | aws_password_policy | aws_user | cognito_pool | evidence_gap
    subject: str              # 문서 param 이름 / 계정 ID / 사용자 / 풀 ID
    values: dict[str, Any]
    extractor: str = "rule"   # rule | llm | collector | fixture | human
    citations: list[Citation] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)
    quality: QStatus = "pass"
    quality_reasons: list[str] = field(default_factory=list)


@dataclass
class TestResult:
    test_id: str
    status: Literal["pass", "fail", "gap", "skip"]
    detail: str = ""
    obs_ids: list[str] = field(default_factory=list)


@dataclass
class Violation:
    ar_id: str
    test_id: str
    subject: str
    expected: Any
    observed: Any
    op: str
    message: str
    obs_ids: list[str] = field(default_factory=list)


@dataclass
class Evaluation:
    ar_id: str
    criterion: str
    scope: Literal["APPLICABLE", "UNKNOWN", "NOT_APPLICABLE_PENDING"]
    scope_detail: str
    coverage: CoverageStatus
    coverage_detail: str
    tests: dict[str, TestResult]
    violations: list[Violation] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


@dataclass
class Decision:
    ar_id: str
    criterion: str
    verdict: Verdict
    reason_code: str
    reason: str
    external_label_pending: str   # 검토 전 외부 표기
    satisfied_path: list[str] | None = None


@dataclass
class FindingFact:
    finding_id: str
    ar_id: str
    primary_criterion: str
    related_criteria: list[str]
    relation: Literal["direct_violation", "contributing_condition", "scope_gap", "informational"]
    subject: str
    summary: str
    obs_ids: list[str]


def to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    return obj
