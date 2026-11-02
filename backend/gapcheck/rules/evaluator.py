"""규칙 실행기. AR YAML의 테스트 정의를 그대로 해석해 Evaluation을 만든다.

AR마다 파이썬 함수를 따로 쓰지 않고, 테스트 유형별 의미를 여기 한 곳에 둔다.
그래서 '규칙 = AR YAML + 이 해석기 버전'이고, 둘 다 결과에 버전으로 남는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..compiler.schema import AR, Comparison, Test
from ..model import Evaluation, Observation, TestResult, Violation
from ..observe.aws import parse_ts
from ..scope import evaluate_scope, test_enabled

EVALUATOR_VERSION = "0.1.0"

API_KIND = {
    "iam:GetAccountPasswordPolicy": "aws_password_policy",
    "iam:GetCredentialReport": "aws_user",
    "cognito-idp:DescribeUserPool": "cognito_pool",
}


@dataclass
class Context:
    facts: dict[str, dict]
    accounts_in_scope: list[str]
    doc_obs: dict[str, Observation]           # param → 관측
    tech_obs: list[Observation]
    doc_coverage: tuple[str, str]
    manifest_accounts: dict[str, dict]        # account_id → manifest 항목
    as_of: date
    doc_conflicts: list[str] = field(default_factory=list)


def _kind_for(t: Test) -> str | None:
    for api in (t.collect.apis if t.collect else []):
        if api in API_KIND:
            return API_KIND[api]
    return None


def _usable(o: Observation) -> bool:
    return o.quality != "fail"


class _Run:
    def __init__(self, ar: AR, ctx: Context):
        self.ar, self.ctx = ar, ctx
        self.tests = {t.id: t for t in ar.tests}
        self.results: dict[str, TestResult] = {}
        self.violations: list[Violation] = []
        self.coverage_issues: list[str] = []
        self.collected: dict[str, list[Observation]] = {}

    # ── 참조 해석 ──
    def doc_value(self, ref: str) -> tuple[Any, list[str]]:
        tid, _, param = ref.partition(".")
        o = self.ctx.doc_obs.get(param)
        if o is None or not _usable(o):
            return None, []
        return o.values.get("value"), [o.obs_id]

    def population(self, kind: str, obs: list[Observation]) -> list[Observation]:
        if kind == "aws_user":
            return [o for o in obs if o.values.get("password_enabled")]
        return obs

    # ── 테스트 유형별 ──
    def run_document(self, t: Test) -> TestResult:
        found = {p: self.ctx.doc_obs[p] for p in t.params if p in self.ctx.doc_obs}
        usable = {p: o for p, o in found.items() if _usable(o)}
        cov, _ = self.ctx.doc_coverage
        if usable:
            return TestResult(t.id, "pass", f"추출: {sorted(usable)}", sorted(o.obs_id for o in usable.values()))
        if found:
            return TestResult(t.id, "gap", "추출값이 품질 검사를 통과하지 못함", sorted(o.obs_id for o in found.values()))
        if cov == "COVERAGE_PASS":
            return TestResult(t.id, "fail", f"제출된 정책 문서 전체에서 {t.params} 를 찾지 못함")
        return TestResult(t.id, "gap", "정책 문서 범위가 확정되지 않아 부재를 단정할 수 없음")

    def run_collect(self, t: Test) -> TestResult:
        kind = _kind_for(t)
        obs = [o for o in self.ctx.tech_obs if o.kind == kind]
        usable = [o for o in obs if _usable(o)]
        self.collected[t.id] = usable
        per = t.collect.per if t.collect else "account"
        # 범위: 범위 내 계정마다 수집 성공했는가
        if per in ("account", "user"):
            gaps = []
            for a in self.ctx.accounts_in_scope:
                m = self.ctx.manifest_accounts.get(a, {})
                mine = [o for o in obs if o.values.get("account_id", o.subject) == a or o.subject == a]
                bad = [o for o in mine if not _usable(o)]
                if m.get("status") != "ok":
                    gaps.append(f"{a}(수집 {m.get('status', '없음')})")
                elif bad:
                    gaps.append(f"{a}(품질 미달: {bad[0].quality_reasons[0] if bad[0].quality_reasons else 'fail'})")
                elif not mine and not (kind == "aws_user" and self._report_present(a)):
                    gaps.append(f"{a}(결과 없음)")
            if gaps:
                self.coverage_issues.append(f"{t.id}: 범위 내 계정 미충족 {gaps}")
        if not usable and per != "resource":
            return TestResult(t.id, "gap", "사용 가능한 수집 결과 없음", [o.obs_id for o in obs])
        if per == "resource" and obs and not usable:
            self.coverage_issues.append(f"{t.id}: 리소스 관측 품질 미달 ({obs[0].quality_reasons[0] if obs[0].quality_reasons else 'fail'})")
            return TestResult(t.id, "gap", "리소스 관측이 품질 검사를 통과하지 못함", [o.obs_id for o in obs])
        if per == "resource" and not usable:
            return TestResult(t.id, "gap", "대상 리소스를 찾지 못함")
        return TestResult(t.id, "pass", f"{len(usable)}건 수집", sorted(o.obs_id for o in usable))

    def _report_present(self, account: str) -> bool:
        # 사용자 0명인 계정도 credential report가 있으면 수집 성공으로 본다
        files = self.ctx.manifest_accounts.get(account, {}).get("files", [])
        return "credential_report.csv" in files and self.ctx.manifest_accounts[account].get("status") == "ok"

    @staticmethod
    def _cmp(op: str, expected: Any, observed: Any) -> bool:
        if op == "forbids":
            return not (expected is True and observed is True)
        if observed is None:
            return False
        if op == ">=":
            return observed >= expected
        if op == "<=":
            return observed <= expected
        return observed == expected

    def run_compare(self, t: Test) -> TestResult:
        evaluated, skipped, obs_ids = 0, [], []
        before = len(self.violations)
        no_policy_reported: set[str] = set()   # 정책 자체가 없는 계정은 비교 항목 수와 관계없이 1건
        for c in t.compare:
            expected, e_ids = self.doc_value(c.expected) if not c.expected.startswith("const:") else (
                _const(c.expected), [])
            if expected is None:
                skipped.append(f"{c.expected} 없음")
                continue
            otid, _, field_ = c.observed.partition(".")
            subjects = self.population(_kind_for(self.tests[otid]) or "", self.collected.get(otid, []))
            for o in subjects:
                observed = o.values.get(field_)
                if c.op == "forbids" and observed is None:
                    continue  # 판단 불가 사용자 (발급 시각 없음 등)
                evaluated += 1
                obs_ids.append(o.obs_id)
                if not self._cmp(c.op, expected, observed):
                    if o.kind == "aws_password_policy" and o.values.get("policy_exists") is False:
                        if o.subject in no_policy_reported:
                            continue
                        no_policy_reported.add(o.subject)
                    self.violations.append(Violation(
                        ar_id=self.ar.id, test_id=t.id, subject=o.subject, expected=expected,
                        observed=observed, op=c.op, message=_msg(c, expected, observed, o),
                        obs_ids=sorted(set(e_ids + [o.obs_id]))))
        if len(self.violations) > before:
            return TestResult(t.id, "fail", f"{len(self.violations) - before}건 불일치", sorted(set(obs_ids)))
        if evaluated == 0:
            return TestResult(t.id, "gap", "비교할 값이 없음: " + "; ".join(skipped) if skipped else "비교 대상 없음")
        return TestResult(t.id, "pass", f"{evaluated}건 비교 일치" + (f" (건너뜀: {skipped})" if skipped else ""),
                          sorted(set(obs_ids)))

    def run_cadence(self, t: Test) -> TestResult:
        cad = t.cadence
        max_days, e_ids = self.doc_value(cad.max_interval_days)
        if max_days is None:
            return TestResult(t.id, "gap", f"주기 기준값({cad.max_interval_days}) 없음")
        otid, _, field_ = cad.last_event.partition(".")
        users = self.population("aws_user", self.collected.get(otid, []))
        before, checked = len(self.violations), 0
        for o in users:
            last = parse_ts(o.values.get(field_))
            if last is None:
                continue
            checked += 1
            days = (self.ctx.as_of - last.date()).days
            if days > max_days:
                self.violations.append(Violation(
                    ar_id=self.ar.id, test_id=t.id, subject=o.subject, expected=f"≤ {max_days}일",
                    observed=f"{days}일", op="<=",
                    message=f"{o.subject}: 마지막 변경 {last.date()} → 기준일까지 {days}일 (정책 {max_days}일)",
                    obs_ids=sorted(set(e_ids + [o.obs_id]))))
        if len(self.violations) > before:
            return TestResult(t.id, "fail", f"{len(self.violations) - before}명 주기 초과")
        if checked == 0:
            return TestResult(t.id, "gap", "확인할 사용자 없음")
        return TestResult(t.id, "pass", f"{checked}명 모두 {max_days}일 이내")

    def run(self) -> Evaluation:
        scope, scope_detail = evaluate_scope(self.ar, self.ctx.facts)
        for t in self.ar.tests:
            enabled = test_enabled(t.when, self.ctx.facts)
            if enabled is False:
                self.results[t.id] = TestResult(t.id, "skip", f"조건 거짓: {t.when}")
                continue
            if enabled is None:
                self.results[t.id] = TestResult(t.id, "gap", f"조건 미확인: {t.when}")
                continue
            if any(self.results.get(r, TestResult(r, "pass")).status in ("gap", "skip") for r in _deps(t)):
                self.results[t.id] = TestResult(t.id, "gap", f"선행 테스트 미충족: {_deps(t)}")
                continue
            fn = {"DOCUMENT_EXTRACT": self.run_document, "CONFIG_COLLECT": self.run_collect,
                  "PARAMETER_COMPARE": self.run_compare, "CADENCE_CHECK": self.run_cadence}.get(t.type)
            if fn is None:  # EVIDENCE_REVIEW, HUMAN_CONFIRMATION, POPULATION_COVERAGE
                self.results[t.id] = TestResult(t.id, "gap", f"{t.type}: 자동화되지 않음 — 사람 검토 필요")
                continue
            self.results[t.id] = fn(t)

        # violation_when에 걸린 '부재' 결과(문서 추출 fail)는 위반으로 기록
        vtests = {v.test for v in self.ar.violation_when}
        for tid in sorted(vtests):
            r = self.results.get(tid)
            t = self.tests.get(tid)
            if r and t and r.status == "fail" and t.type == "DOCUMENT_EXTRACT":
                self.violations.append(Violation(self.ar.id, tid, "정책 문서", t.params, None, "exists", r.detail))
        # violation_when에 없는 테스트의 실패는 결함 근거가 아니다 (규칙이 승인하지 않음)
        self.violations = [v for v in self.violations if v.test_id in vtests]

        # 범위
        uses_docs = any(t.type == "DOCUMENT_EXTRACT" and self.results[t.id].status != "skip" for t in self.ar.tests)
        cov, cov_detail = "COVERAGE_PASS", "범위 충족"
        issues = list(self.coverage_issues)
        if uses_docs and self.ctx.doc_coverage[0] != "COVERAGE_PASS":
            issues.append(self.ctx.doc_coverage[1])
            cov = self.ctx.doc_coverage[0]
        if self.coverage_issues and cov == "COVERAGE_PASS":
            cov = "PARTIAL_COLLECTION"
        if issues:
            cov_detail = "; ".join(issues)

        params = {p for t in self.ar.tests for p in t.params}
        conflicts = [c for c in self.ctx.doc_conflicts if c.split(":")[0] in params]
        return Evaluation(self.ar.id, self.ar.id.split("-")[1], scope, scope_detail, cov, cov_detail,
                          self.results, sorted(self.violations, key=lambda v: (v.test_id, v.subject, str(v.expected))),
                          conflicts)


def _deps(t: Test) -> list[str]:
    refs = []
    for c in t.compare:
        refs += [c.expected, c.observed]
    if t.cadence:
        refs += [t.cadence.last_event, t.cadence.max_interval_days]
    return sorted({r.split(".")[0] for r in refs if not r.startswith(("const:", "overlay:"))})


def _const(ref: str) -> Any:
    v = ref[6:]
    return {"true": True, "false": False}.get(v.lower(), int(v) if v.isdigit() else v)


def _msg(c: Comparison, expected: Any, observed: Any, o: Observation) -> str:
    field_ = c.observed.split(".", 1)[1]
    if o.kind == "aws_password_policy" and o.values.get("policy_exists") is False:
        return f"{o.subject}: IAM 계정 비밀번호 정책이 설정되어 있지 않음 (NoSuchEntity) — 정책 문서의 작성규칙이 전혀 반영되지 않음"
    if c.op == "forbids":
        return f"{o.subject}: 발급받은 임시 비밀번호를 변경하지 않고 로그인함 (정책은 최초 로그인 시 변경 요구)"
    shown = "미설정" if observed is None else observed
    return f"{o.subject}: {field_} = {shown}, 정책 기준 {c.op} {expected}"


def evaluate(ar: AR, ctx: Context) -> Evaluation:
    return _Run(ar, ctx).run()
