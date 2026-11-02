"""AR(Atomic Requirement) YAML 스키마.

원칙
- AR 파일에는 KISA 원문을 그대로 싣지 않는다. 원문 위치(locator)와 자체 요약(summary)만 둔다.
  원문은 비공개 data/ 의 Source Registry 사본에서 런타임에 읽는다 (공공누리 4유형 변경금지 조건).
- 비교 기준값(expected)은 조직 자체 정책 문서에서 추출한 값이 기본이다.
  법정 수치는 overlay 에서 active=true 인 것만 참조할 수 있다.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Axis = Literal["document", "evidence", "technical", "inquiry"]
TestType = Literal[
    "DOCUMENT_EXTRACT",     # 정책·지침 문서에서 값/조항 추출 (axis=document)
    "CONFIG_COLLECT",       # 시스템 설정값 직접 수집 (axis=technical)
    "EVIDENCE_REVIEW",      # 제출 증적(캡처·기록) 검토 (axis=evidence)
    "PARAMETER_COMPARE",    # 다른 테스트 결과끼리 비교 (파생)
    "CADENCE_CHECK",        # 주기 이행 여부 (파생)
    "POPULATION_COVERAGE",  # 모집단 대비 범위 (파생)
    "HUMAN_CONFIRMATION",   # 질의·인터뷰 (axis=inquiry)
]
DERIVED: set[str] = {"PARAMETER_COMPARE", "CADENCE_CHECK", "POPULATION_COVERAGE"}
NATIVE_AXIS: dict[str, Axis] = {
    "DOCUMENT_EXTRACT": "document",
    "CONFIG_COLLECT": "technical",
    "EVIDENCE_REVIEW": "evidence",
    "HUMAN_CONFIRMATION": "inquiry",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(_Strict):
    ref: str                      # sources/registry.yaml 의 id
    locator: str                  # 원문 위치 (항목·쪽·확인사항 번호)
    via: str | None = None        # 실제로 텍스트를 얻은 경로 (예: S3 사본)


class Collect(_Strict):
    apis: list[str]               # 예: iam:GetAccountPasswordPolicy
    fields: list[str]
    per: Literal["account", "user", "resource"] = "account"
    derive: dict[str, str] = Field(default_factory=dict)   # 파생 필드 이름 → 설명식


class Comparison(_Strict):
    expected: str                 # "T1.password.min_length" | "overlay:<id>" | "const:<값>"
    observed: str                 # "T2.MinimumPasswordLength"
    op: Literal[">=", "<=", "==", "forbids"]   # forbids: expected가 true면 observed는 false여야 함
    when_expected_missing: Literal["skip", "insufficient"] = "skip"
    note: str | None = None


class Cadence(_Strict):
    last_event: str               # 마지막 수행 시각 참조 (예: T2.password_last_changed)
    max_interval_days: str        # 허용 주기 참조 (예: T1.password.max_age_days)


class Test(_Strict):
    id: str = Field(pattern=r"^T\d+$")
    type: TestType
    description: str
    params: list[str] = Field(default_factory=list)       # DOCUMENT_EXTRACT/EVIDENCE_REVIEW 산출값
    collect: Collect | None = None                        # CONFIG_COLLECT
    compare: list[Comparison] = Field(default_factory=list)
    cadence: Cadence | None = None
    when: str | None = None                               # 이 테스트를 실행할 Scope 조건


class Violation(_Strict):
    test: str
    condition: str                # 사람이 읽는 조건 설명. 실행 로직은 rule bundle 이 가진다.


class Applicability(_Strict):
    when: list[str] = Field(default_factory=list)         # 필요한 Scope 사실
    default: Literal["UNKNOWN", "APPLICABLE", "NOT_APPLICABLE"] = "UNKNOWN"


class Population(_Strict):
    name: str
    source: str


class Plain(_Strict):
    """일반 직원도 이해할 수 있는 설명.

    question 은 ISMS-P 확인사항 어투(~을 수립·이행하고 있는가?)로, 나머지는 전문용어 없이 해요체로 쓴다.
    question 도 KISA 원문을 복제하지 않고 자체 문장으로 쓴다.
    """
    question: str                 # 이 항목이 확인하는 통제를 ISMS-P 확인사항 어투의 질문 한 문장으로
    why: str                      # 왜 중요한지
    fix: list[str]                # 무엇을 하면 되는지 (순서대로)
    owner: str                    # 누가 하면 되는지


class AR(_Strict):
    id: str
    title: str
    summary: str                  # 자체 문장으로 쓴 요구 요약 (원문 복제 금지)
    plain: Plain | None = None
    status: Literal["draft", "active"] = "draft"
    source: SourceRef
    checkpoints: list[int]
    case_refs: list[str] = Field(default_factory=list)
    applicability: Applicability = Field(default_factory=Applicability)
    population: Population | None = None
    tests: list[Test]
    conforming_paths: list[list[str]]                     # 적합 후보가 되려면 모두 통과해야 하는 테스트 묶음 (OR)
    violation_when: list[Violation] = Field(default_factory=list)
    single_axis_justification: str | None = None


class Checkpoint(_Strict):
    index: int                    # 확인사항 번호 (YAML에서 no는 불리언으로 읽혀서 쓰지 않음)
    covered_by: list[str] = Field(default_factory=list)
    note: str | None = None


class CriterionFile(_Strict):
    criterion: str = Field(pattern=r"^\d\.\d+\.\d+$")
    name: str
    source: SourceRef
    checkpoints: list[Checkpoint]
    requirements: list[AR]


class RegistrySource(_Strict):
    id: str
    tier: Literal["S1", "S2", "S3", "S4", "S5"]
    title: str
    publisher: str
    url: str | None = None
    license: str
    sha256: str | None = None
    status: Literal["verified", "unverified"] = "unverified"
    allowed_use: list[str]
    note: str | None = None


class Registry(_Strict):
    sources: list[RegistrySource]


class OverlayParam(_Strict):
    id: str
    description: str
    value: str | int | float | bool | None = None
    unit: str | None = None
    source_ref: str
    locator: str | None = None
    active: bool = False


class Overlay(_Strict):
    params: list[OverlayParam] = Field(default_factory=list)
