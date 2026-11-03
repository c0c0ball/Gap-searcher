"""요구사항 lint. 사용법: gapcheck-lint <requirements_dir> <sources_dir>"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import (
    AR, DERIVED, NATIVE_AXIS, CriterionFile, Overlay, Registry, Test,
)

# 쉬운 설명에서 금지하는 표현 (보고서 문구 정책 v1.2 13.3)
FORBIDDEN_PLAIN = ["인증 적합", "인증 불가", "결함 확정", "취득 보장", "인증 결함"]
JARGON = ["AR-", "Coverage", "관측", "모집단", "결함 후보", "NoSuchEntity", "직접 위반"]

AR_ID = re.compile(r"^AR-(\d\.\d+\.\d+)-(\d{2})$")
CASE_REF = re.compile(r"^(KISA|CELA|ITWIKI):[\w.\-]+$")


@dataclass
class Finding:
    rule: str
    severity: str  # error | warning
    where: str
    message: str


@dataclass
class Report:
    files: int = 0
    requirements: int = 0
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, sev: str, where: str, msg: str) -> None:
        self.findings.append(Finding(rule, sev, where, msg))

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def as_dict(self) -> dict:
        return {
            "ok": not self.errors,
            "files": self.files,
            "requirements": self.requirements,
            "errors": [f.__dict__ for f in self.errors],
            "warnings": [f.__dict__ for f in self.warnings],
        }


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sources(src_dir: Path) -> tuple[Registry, Overlay]:
    reg = Registry.model_validate(_load_yaml(src_dir / "registry.yaml"))
    ov_path = src_dir / "legal_overlay.yaml"
    ov = Overlay.model_validate(_load_yaml(ov_path) or {}) if ov_path.exists() else Overlay()
    return reg, ov


class _Ctx:
    """한 AR 안에서 'T1.password.min_length' 같은 참조를 해석한다."""

    def __init__(self, ar: AR, overlay: Overlay):
        self.tests: dict[str, Test] = {t.id: t for t in ar.tests}
        self.overlay = {p.id: p for p in overlay.params}

    def outputs(self, t: Test) -> set[str]:
        out = set(t.params)
        if t.collect:
            out |= set(t.collect.fields) | set(t.collect.derive)
        return out

    def resolve(self, ref: str) -> tuple[bool, str]:
        if ref.startswith("const:"):
            return True, ""
        if ref.startswith("overlay:"):
            p = self.overlay.get(ref[8:])
            if p is None:
                return False, f"overlay 파라미터 '{ref[8:]}' 없음"
            if not p.active:
                return False, f"overlay '{p.id}'는 비활성(S1 원문 대조 전) — 기준값으로 쓸 수 없음"
            return True, ""
        tid, _, name = ref.partition(".")
        t = self.tests.get(tid)
        if t is None:
            return False, f"테스트 '{tid}' 없음"
        if name and name not in self.outputs(t):
            return False, f"'{tid}'에 산출값 '{name}' 없음 (있는 값: {sorted(self.outputs(t))})"
        return True, ""

    def axes_of(self, tid: str, seen: frozenset[str] = frozenset()) -> set[str]:
        t = self.tests.get(tid)
        if t is None or tid in seen:
            return set()
        if t.type in NATIVE_AXIS:
            return {NATIVE_AXIS[t.type]}
        refs: list[str] = []
        for c in t.compare:
            refs += [c.expected, c.observed]
        if t.cadence:
            refs += [t.cadence.last_event, t.cadence.max_interval_days]
        refs += _check_refs(t)
        axes: set[str] = set()
        for r in refs:
            if r.startswith(("const:", "overlay:")):
                continue
            axes |= self.axes_of(r.split(".")[0], seen | {tid})
        return axes


def _check_refs(t: Test) -> list[str]:
    c = t.check
    if c is None:
        return []
    refs = [c.population]
    for r in (c.gate, c.value):
        if r:
            refs.append(r)
    if c.join:
        refs.append(c.join.test)
    if c.grace:
        refs.append(c.grace.days)
    return refs


def lint_ar(ar: AR, criterion: str, reg_ids: dict, overlay: Overlay, rep: Report) -> None:
    w = ar.id
    ctx = _Ctx(ar, overlay)

    # RC-001 ID 형식·기준 일치
    m = AR_ID.match(ar.id)
    if not m:
        rep.add("RC-001", "error", w, "AR id는 'AR-<기준번호>-NN' 형식이어야 함")
    elif m.group(1) != criterion:
        rep.add("RC-001", "error", w, f"AR id의 기준번호({m.group(1)})가 파일 기준({criterion})과 다름")
    dup = [t.id for t in ar.tests]
    if len(dup) != len(set(dup)):
        rep.add("RC-001", "error", w, "테스트 id 중복")

    # RC-002 원천 등록·검증 상태
    src = reg_ids.get(ar.source.ref)
    if src is None:
        rep.add("RC-002", "error", w, f"원천 '{ar.source.ref}'가 Source Registry에 없음")
    elif src.status != "verified":
        sev = "error" if ar.status == "active" else "warning"
        rep.add("RC-002", sev, w, f"원천 '{src.id}' 미검증 — active 전환 전 S1 원문 대조·해시 등록 필요")
    if ar.source.via and ar.source.via not in reg_ids:
        rep.add("RC-002", "error", w, f"via 원천 '{ar.source.via}'가 Registry에 없음")

    # RC-005 참조 해석
    for path in ar.conforming_paths:
        for tid in path:
            if tid not in ctx.tests:
                rep.add("RC-005", "error", w, f"conforming_paths의 '{tid}' 없음")
    for v in ar.violation_when:
        if v.test not in ctx.tests:
            rep.add("RC-005", "error", w, f"violation_when의 '{v.test}' 없음")
    for t in ar.tests:
        refs: list[tuple[str, str]] = []
        for c in t.compare:
            refs += [("expected", c.expected), ("observed", c.observed)]
            # RC-004 법정 수치는 활성 overlay만 / 관측값은 직접 관측이어야 함
            if c.observed.startswith(("const:", "overlay:")):
                rep.add("RC-004", "error", f"{w}/{t.id}", "observed는 실제 관측 테스트를 참조해야 함")
        if t.cadence:
            refs += [("last_event", t.cadence.last_event), ("max_interval_days", t.cadence.max_interval_days)]
        if t.check:
            c = t.check
            refs += [("population", c.population)]
            refs += [(k, r) for k, r in (("gate", c.gate), ("value", c.value)) if r]
            if c.join:
                refs += [("join.test", c.join.test)]
            if c.grace:
                refs += [("grace.days", c.grace.days)]
            if (c.op is None) != (c.field is None) and not c.join:
                rep.add("RC-005", "error", f"{w}/{t.id}", "check의 field와 op는 함께 써야 함")
            if c.op in ("==", "!=", "age_days_le") and not c.value:
                rep.add("RC-005", "error", f"{w}/{t.id}", f"op '{c.op}'에는 value가 필요")
            if c.op is None and not (c.join and c.join.missing == "violation"):
                rep.add("RC-005", "error", f"{w}/{t.id}", "check는 op 또는 join.missing=violation 중 하나가 필요")
        for role, r in refs:
            ok, why = ctx.resolve(r)
            if not ok:
                rule = "RC-004" if r.startswith("overlay:") else "RC-005"
                rep.add(rule, "error", f"{w}/{t.id}", f"{role} '{r}': {why}")
        # 테스트 유형별 필수 필드
        if t.type == "CONFIG_COLLECT" and not t.collect:
            rep.add("RC-005", "error", f"{w}/{t.id}", "CONFIG_COLLECT에는 collect가 필요")
        if t.type in ("DOCUMENT_EXTRACT", "EVIDENCE_REVIEW") and not t.params:
            rep.add("RC-005", "error", f"{w}/{t.id}", f"{t.type}에는 params가 필요")
        if t.type == "PARAMETER_COMPARE" and not t.compare:
            rep.add("RC-005", "error", f"{w}/{t.id}", "PARAMETER_COMPARE에는 compare가 필요")
        if t.type == "CADENCE_CHECK" and not t.cadence:
            rep.add("RC-005", "error", f"{w}/{t.id}", "CADENCE_CHECK에는 cadence가 필요")
        if t.type == "SUBJECT_CHECK" and not t.check:
            rep.add("RC-005", "error", f"{w}/{t.id}", "SUBJECT_CHECK에는 check가 필요")
        if t.check and t.check.population in ctx.tests and \
                ctx.tests[t.check.population].type not in ("CONFIG_COLLECT", "EVIDENCE_REVIEW"):
            rep.add("RC-005", "error", f"{w}/{t.id}", "check.population은 수집(CONFIG_COLLECT)이나 증적(EVIDENCE_REVIEW) 테스트여야 함")

    # RC-003 적합 경로는 독립 관측 축 2개 이상
    for path in ar.conforming_paths:
        axes: set[str] = set()
        for tid in path:
            axes |= ctx.axes_of(tid)
        if len(axes) < 2 and not ar.single_axis_justification:
            rep.add("RC-003", "error", w,
                    f"적합 경로 {path}의 관측 축이 {sorted(axes)}뿐 — 2개 이상 또는 single_axis_justification 필요")
        # RC-007 진술(inquiry)만으로 적합 불가
        if axes and axes <= {"inquiry"}:
            rep.add("RC-007", "error", w, f"적합 경로 {path}가 질의 답변만으로 구성됨")

    # RC-006 주기·범위 테스트는 모집단 필요
    if any(t.type in ("CADENCE_CHECK", "POPULATION_COVERAGE", "SUBJECT_CHECK") for t in ar.tests) and not ar.population:
        rep.add("RC-006", "error", w, "CADENCE_CHECK/POPULATION_COVERAGE/SUBJECT_CHECK가 있으면 population을 정의해야 함")

    # RC-008 결함 근거는 질의 답변이 아니어야 함
    for v in ar.violation_when:
        t = ctx.tests.get(v.test)
        if t and t.type == "HUMAN_CONFIRMATION":
            rep.add("RC-008", "error", w, f"'{v.test}'(질의)는 결함 근거가 될 수 없음")
        if t and t.type in DERIVED and ctx.axes_of(t.id) <= {"inquiry"}:
            rep.add("RC-008", "error", w, f"'{v.test}'가 질의 답변에만 의존함")

    # RC-010 적용 여부 기본값은 UNKNOWN
    if ar.applicability.default != "UNKNOWN":
        rep.add("RC-010", "error", w, "applicability.default는 UNKNOWN이어야 함 (근거 없는 적용/제외 금지)")

    # RC-011 쉬운 설명: active AR은 필수, 확정·인증 표현 금지, 전문용어 최소화
    if ar.plain is None:
        rep.add("RC-011", "error" if ar.status == "active" else "warning", w, "쉬운 설명(plain)이 없음")
    else:
        text = " ".join([ar.plain.question, ar.plain.why, *ar.plain.fix, ar.plain.owner])
        for bad in FORBIDDEN_PLAIN:
            if bad in text:
                rep.add("RC-011", "error", w, f"쉬운 설명에 쓰면 안 되는 표현: '{bad}'")
        q = ar.plain.question.strip()
        if not q.endswith("가?"):
            rep.add("RC-011", "error", w, f"question은 ISMS-P 확인사항 어투(~하고 있는가?)로 끝나야 함: '{q}'")
        for jargon in JARGON:
            if jargon in text:
                rep.add("RC-011", "warning", w, f"쉬운 설명에 전문용어 '{jargon}' — 풀어 쓰기 권장")

    for c in ar.case_refs:
        if not CASE_REF.match(c):
            rep.add("RC-009", "warning", w, f"case_ref '{c}' 형식은 'KISA:2.5.4-1'처럼 써야 함")


def lint_file(path: Path, reg_ids: dict, overlay: Overlay, seen_ids: set[str], rep: Report) -> None:
    rep.files += 1
    try:
        cf = CriterionFile.model_validate(_load_yaml(path))
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            rep.add("RC-000", "error", f"{path.name}:{loc}", err["msg"])
        return
    if cf.source.ref not in reg_ids:
        rep.add("RC-002", "error", path.name, f"원천 '{cf.source.ref}'가 Registry에 없음")
    ar_ids = {ar.id for ar in cf.requirements}
    for ar in cf.requirements:
        rep.requirements += 1
        if ar.id in seen_ids:
            rep.add("RC-001", "error", ar.id, "AR id가 다른 파일과 중복")
        seen_ids.add(ar.id)
        lint_ar(ar, cf.criterion, reg_ids, overlay, rep)
        cp_nos = {c.index for c in cf.checkpoints}
        for n in ar.checkpoints:
            if n not in cp_nos:
                rep.add("RC-009", "error", ar.id, f"확인사항 {n}이 기준 파일에 없음")
    # RC-009 확인사항 커버리지
    for cp in cf.checkpoints:
        for a in cp.covered_by:
            if a not in ar_ids:
                rep.add("RC-009", "error", f"{cf.criterion}#{cp.index}", f"covered_by '{a}' 없음")
        if not cp.covered_by:
            sev = "warning" if cp.note else "error"
            rep.add("RC-009", sev, f"{cf.criterion}#{cp.index}",
                    "확인사항을 다루는 AR이 없음" + (f" — {cp.note}" if cp.note else " (note로 사유를 적어야 함)"))


def lint_paths(req_dir: Path, src_dir: Path) -> Report:
    rep = Report()
    reg, overlay = load_sources(src_dir)
    reg_ids = {s.id: s for s in reg.sources}
    seen: set[str] = set()
    for p in sorted(req_dir.rglob("*.yaml")):
        lint_file(p, reg_ids, overlay, seen, rep)
    return rep


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    root = Path.cwd()
    req = Path(argv[0]) if argv else root / "requirements"
    src = Path(argv[1]) if len(argv) > 1 else root / "sources"
    rep = lint_paths(req, src)
    for f in rep.findings:
        mark = "✗" if f.severity == "error" else "!"
        print(f"{mark} [{f.rule}] {f.where}: {f.message}")
    print(f"\n파일 {rep.files}개, AR {rep.requirements}개 — 오류 {len(rep.errors)}건, 경고 {len(rep.warnings)}건")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
