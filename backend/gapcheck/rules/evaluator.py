"""규칙 실행기. AR YAML의 테스트 정의를 그대로 해석해 Evaluation을 만든다.

AR마다 파이썬 함수를 따로 쓰지 않고, 테스트 유형별 의미를 여기 한 곳에 둔다.
그래서 '규칙 = AR YAML + 이 해석기 버전'이고, 둘 다 결과에 버전으로 남는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..compiler.schema import AR, Check, Comparison, Test
from ..model import Evaluation, Observation, TestResult, Violation
from ..observe.aws import parse_ts
from ..observe.evidence import KIND_OBS
from ..scope import evaluate_scope, test_enabled

EVALUATOR_VERSION = "0.3.0"

API_KIND = {
    "iam:GetAccountPasswordPolicy": "aws_password_policy",
    "iam:GetCredentialReport": "aws_user",
    "iam:GetAccountAuthorizationDetails": "aws_user",
    "cognito-idp:DescribeUserPool": "cognito_pool",
}
# 계정 단위 수집에서 범위 충족으로 보려면 있어야 하는 스냅샷 파일
API_FILE = {
    "iam:GetAccountPasswordPolicy": "iam_password_policy.json",
    "iam:GetCredentialReport": "credential_report.csv",
    "iam:GetLoginProfile": "login_profiles.json",
    "iam:GetAccountAuthorizationDetails": "iam_authorization.json",
    "ec2:DescribeSecurityGroups": "ec2_security_groups.json",
    "ec2:DescribeSubnets": "ec2_subnets.json",
    "ec2:DescribeRouteTables": "ec2_route_tables.json",
    "rds:DescribeDBInstances": "rds_db_instances.json",
    "ec2:DescribeVolumes": "ec2_volumes.json",
    "s3:GetBucketEncryption": "s3_buckets.json",
    "kms:ListKeys": "kms_keys.json",
    "elasticloadbalancing:DescribeListeners": "elbv2_listeners.json",
    "elasticloadbalancing:DescribeSSLPolicies": "elbv2_ssl_policies.json",
    "cloudtrail:DescribeTrails": "cloudtrail_trails.json",
    "guardduty:ListDetectors": "guardduty.json",
    "backup:ListBackupPlans": "backup_plans.json",
    "s3:GetBucketLifecycleConfiguration": "s3_buckets.json",
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
    evidence_obs: list[Observation] = field(default_factory=list)
    overlay: dict[str, Any] = field(default_factory=dict)   # 원문 대조를 마친(active) 법정 파라미터만


def _kind_for(t: Test) -> str | None:
    if t.type == "EVIDENCE_REVIEW":
        return KIND_OBS.get(t.evidence_kind or "")
    if t.collect and t.collect.kind:
        return t.collect.kind
    if t.collect and t.collect.per == "root":
        return "aws_root"
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
        if ref.startswith("const:"):
            return _const(ref), []
        if ref.startswith("overlay:"):
            return self.ctx.overlay.get(ref[8:]), []
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
        need = sorted({API_FILE[a] for a in (t.collect.apis if t.collect else []) if a in API_FILE})
        # 범위: 범위 내 계정마다 수집 성공했는가
        # 계정 단위로 받는 자료(필수 파일이 정해진 API)는 리소스 단위 관측이어도 계정마다 수집됐는지 본다
        if per in ("account", "user", "root") or (per == "resource" and need):
            gaps = []
            for a in self.ctx.accounts_in_scope:
                m = self.ctx.manifest_accounts.get(a, {})
                lacking = [f for f in need if f not in m.get("files", [])]
                status = m.get("status")
                if status in ("ok", "partial") and lacking:
                    gaps.append(f"{a}({', '.join(lacking)} 없음)")
                    continue
                # 일부 파일만 못 받은 계정(partial)이라도 이 테스트에 필요한 파일이 다 있으면 수집 성공으로 본다
                if status == "partial" and need:
                    status = "ok"
                mine = [o for o in obs if o.values.get("account_id", o.subject) == a or o.subject == a]
                bad = [o for o in mine if not _usable(o)]
                if status != "ok":
                    gaps.append(f"{a}(수집 {m.get('status', '없음')})")
                elif bad:
                    gaps.append(f"{a}(품질 미달: {bad[0].quality_reasons[0] if bad[0].quality_reasons else 'fail'})")
                elif not mine and per != "resource" and not (kind in ("aws_user", "aws_root") and self._report_present(a)):
                    gaps.append(f"{a}(결과 없음)")
            if gaps:
                self.coverage_issues.append(f"{t.id}: 범위 내 계정 미충족 {gaps}")
        if not usable and per != "resource":
            return TestResult(t.id, "gap", "사용 가능한 수집 결과 없음", [o.obs_id for o in obs])
        if per == "resource" and obs and not usable:
            self.coverage_issues.append(f"{t.id}: 리소스 관측 품질 미달 ({obs[0].quality_reasons[0] if obs[0].quality_reasons else 'fail'})")
            return TestResult(t.id, "gap", "리소스 관측이 품질 검사를 통과하지 못함", [o.obs_id for o in obs])
        if per == "resource" and not usable:
            if need and not self.coverage_issues:
                return TestResult(t.id, "pass", "범위 내 계정을 모두 수집했고 해당 리소스는 0건")
            return TestResult(t.id, "gap", "대상 리소스를 찾지 못함")
        return TestResult(t.id, "pass", f"{len(usable)}건 수집", sorted(o.obs_id for o in usable))

    def _report_present(self, account: str) -> bool:
        # 사용자 0명인 계정도 credential report가 있으면 수집 성공으로 본다
        files = self.ctx.manifest_accounts.get(account, {}).get("files", [])
        return "credential_report.csv" in files and self.ctx.manifest_accounts[account].get("status") in ("ok", "partial")

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
        kind = _kind_for(self.tests[otid]) or ""
        users = self.population(kind, self.collected.get(otid, []))
        if cad.aggregate == "latest":
            dated = [(parse_ts(o.values.get(field_)), o) for o in users]
            dated = [(d, o) for d, o in dated if d is not None]
            if not dated:
                return TestResult(t.id, "gap", "기록에서 날짜를 찾지 못함")
            last, o = max(dated, key=lambda x: x[0])
            days = (self.ctx.as_of - last.date()).days
            ids = sorted(set(e_ids + [x.obs_id for _, x in dated]))
            if days > max_days:
                self.violations.append(Violation(
                    ar_id=self.ar.id, test_id=t.id, subject=self.ar.population.name if self.ar.population else o.subject,
                    expected=f"≤ {max_days}일", observed=f"{days}일", op="<=",
                    message=f"가장 최근 기록이 {last.date()} → 기준일까지 {days}일 지남 (정책 주기 {max_days}일). "
                            f"그 뒤 기록 없음 (전체 {len(dated)}건)",
                    obs_ids=ids,
                    plain=cad.plain.format_map(_Safe({"last": last.date().isoformat(), "days": days,
                                                       "max_days": max_days})) if cad.plain else None))
                return TestResult(t.id, "fail", f"마지막 기록 {last.date()}, {days}일 경과", ids)
            return TestResult(t.id, "pass", f"마지막 기록 {last.date()}, {days}일 경과 (주기 {max_days}일 이내)", ids)
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

    def run_evidence(self, t: Test) -> TestResult:
        kind = _kind_for(t)
        if kind is None:
            return TestResult(t.id, "gap", f"{t.type}: 자동화되지 않음 — 사람 검토 필요")
        obs = [o for o in self.ctx.evidence_obs if o.kind == kind]
        usable = [o for o in obs if _usable(o)]
        self.collected[t.id] = usable
        if not obs:
            self.coverage_issues.append(f"{t.id}: 증적 '{t.evidence_kind}'이(가) 제출되지 않음")
            return TestResult(t.id, "gap", f"증적 '{t.evidence_kind}' 없음")
        if not usable:
            return TestResult(t.id, "gap", "증적이 품질 검사를 통과하지 못함", [o.obs_id for o in obs])
        files = sorted({o.source.get("file", "") for o in usable})
        return TestResult(t.id, "pass", f"{len(usable)}행 판독 ({', '.join(files)})", sorted(o.obs_id for o in usable))

    def run_subject_check(self, t: Test) -> TestResult:
        c: Check = t.check
        if c.gate:
            g, _ = self.doc_value(c.gate)
            if g is None:
                return TestResult(t.id, "gap", f"정책 근거({c.gate})를 찾지 못해 검사하지 않음")
            if not g:
                return TestResult(t.id, "skip", f"정책이 이 통제를 요구하지 않음 ({c.gate} = {g})")
        value, e_ids = (None, [])
        if c.value:
            value, e_ids = self.doc_value(c.value)
            if value is None:
                return TestResult(t.id, "gap", f"기준값({c.value})을 찾지 못함")
        grace_days = None
        if c.grace:
            grace_days, g_ids = self.doc_value(c.grace.days)
            if grace_days is None:
                return TestResult(t.id, "gap", f"허용 기간({c.grace.days})을 찾지 못함")
            e_ids = e_ids + g_ids
        self._limit = value if value is not None else grace_days
        pop = [o for o in self.collected.get(c.population, [])
               if all(o.values.get(k) == v for k, v in c.where.items())]
        others = self.collected.get(c.join.test, []) if c.join else []
        before = len(self.violations)
        checked, unknown, waiting, ids = 0, 0, 0, []
        for o in pop:
            vals = dict(o.values)
            target_ids = [o.obs_id]
            if c.grace:
                start = parse_ts(o.values.get(c.grace.date_field))
                if start is None:
                    unknown += 1
                    continue
                elapsed = _business_days(start.date(), self.ctx.as_of) if c.grace.business_days \
                    else (self.ctx.as_of - start.date()).days
                if elapsed <= grace_days:
                    waiting += 1
                    continue
                vals["elapsed"] = elapsed
            if c.join:
                key = o.values.get(c.join.match[0])
                if key is None:
                    unknown += 1
                    continue
                match = [x for x in others if x.values.get(c.join.match[1]) == key
                         and all(x.values.get(k) == v for k, v in c.join.where.items())]
                if not match:
                    if c.join.missing == "unknown":
                        unknown += 1
                        continue
                    checked += 1
                    ids.append(o.obs_id)
                    if c.join.missing == "violation":
                        self._violate(t, c, o, vals, None, e_ids + target_ids)
                    continue
                m = match[0]
                target_ids.append(m.obs_id)
                vals = {**m.values, **vals}
            if c.field is None:
                checked += 1
                ids += target_ids
                continue
            observed = vals.get(c.field)
            ok = self._check_op(c.op, observed, value)
            if ok is None:
                unknown += 1
                continue
            checked += 1
            ids += target_ids
            if not ok:
                self._violate(t, c, o, vals, observed, e_ids + target_ids)
        n = len(self.violations) - before
        tail = (f", 기간 안이라 아직 보지 않음 {waiting}건" if waiting else "") + (f", 판단 불가 {unknown}건" if unknown else "")
        if n:
            return TestResult(t.id, "fail", f"{checked}건 중 {n}건 위반{tail}", sorted(set(ids)))
        if unknown and checked == 0:
            return TestResult(t.id, "gap", f"판단할 수 있는 대상 없음{tail}")
        if unknown:
            return TestResult(t.id, "gap", f"{checked}건 이상 없음, 그러나 판단 불가 대상 있음{tail}", sorted(set(ids)))
        return TestResult(t.id, "pass", f"{checked}건 모두 이상 없음{tail}", sorted(set(ids)))

    def _check_op(self, op: str | None, observed: Any, value: Any) -> bool | None:
        if op == "truthy":
            return None if observed is None else bool(observed)
        if op == "falsy":
            return None if observed is None else not observed
        if op == "empty":
            return None if observed is None else len(observed) == 0
        if op == "==":
            return None if observed is None else observed == value
        if op == "in":
            return None if observed is None else observed in (value or [])
        if op in (">=", "<="):
            if observed is None or value is None:
                return None
            return observed >= value if op == ">=" else observed <= value
        if op == "!=":
            return None if observed is None else observed != value
        if op == "age_days_le":
            ts = parse_ts(observed) if isinstance(observed, str) else None
            return None if ts is None else (self.ctx.as_of - ts.date()).days <= value
        if op == "cidr_within":
            import ipaddress
            if observed is None:
                return None
            try:
                net = ipaddress.ip_network(str(observed), strict=False)
                allowed = [ipaddress.ip_network(str(a), strict=False) for a in (value or [])]
            except ValueError:
                return None
            return any(net.version == a.version and net.subnet_of(a) for a in allowed)
        if op == "date_after_asof":
            if observed is None:
                return False   # 기한이 정해져 있지 않음
            ts = parse_ts(str(observed))
            return None if ts is None else ts.date() > self.ctx.as_of
        return None

    def _violate(self, t: Test, c: Check, o: Observation, vals: dict, observed: Any, ids: list[str]) -> None:
        fmt = {k: _show(v) for k, v in vals.items()}
        fmt["subject"] = o.subject
        fmt["limit"] = _show(getattr(self, "_limit", None))
        if c.op == "age_days_le" and isinstance(observed, str) and (ts := parse_ts(observed)):
            fmt["days"] = (self.ctx.as_of - ts.date()).days
        self.violations.append(Violation(
            ar_id=self.ar.id, test_id=t.id, subject=vals.get("key") or o.subject,
            expected=c.value or c.op or "대조 대상 있음", observed=observed, op=c.op or "join",
            message=c.message.format_map(_Safe(fmt)), obs_ids=sorted(set(ids)),
            plain=c.plain.format_map(_Safe(fmt)) if c.plain else None))

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
                  "PARAMETER_COMPARE": self.run_compare, "CADENCE_CHECK": self.run_cadence,
                  "SUBJECT_CHECK": self.run_subject_check,
                  "EVIDENCE_REVIEW": self.run_evidence if t.evidence_kind else None}.get(t.type)
            if fn is None:  # EVIDENCE_REVIEW(사람 검토), HUMAN_CONFIRMATION, POPULATION_COVERAGE
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
    if t.check:
        c = t.check
        refs += [c.population] + [r for r in (c.gate, c.value) if r]
        refs += [c.join.test] if c.join else []
        refs += [c.grace.days] if c.grace else []
    return sorted({r.split(".")[0] for r in refs if not r.startswith(("const:", "overlay:"))})


def _business_days(start: date, end: date) -> int:
    """start 다음 날부터 end까지 평일 수 (공휴일은 반영하지 않음)"""
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _show(v: Any) -> Any:
    if v is None or v == "":
        return "없음"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, list):
        return ", ".join(map(str, v)) or "없음"
    if isinstance(v, str) and len(v) >= 19 and v[4] == "-" and v[10] == "T":
        return v[:10]   # 시각은 날짜만
    return v


class _Safe(dict):
    def __missing__(self, k: str) -> str:
        return "{" + k + "}"


def _const(ref: str) -> Any:
    v = ref[6:]
    if "|" in v:   # const:a|b|c → 목록
        return v.split("|")
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
