"""2단계(IAM 수집기) 테스트: 2.2.5, 2.5.1~2.5.6.

정답지 일치는 test_pipeline 이 본다. 여기서는 규칙의 경계(영업일, 빈 칸, 누락 자료)와
'판단 불가를 적합으로 착각하지 않는가'를 변형 시나리오로 확인한다.
"""
import json
from datetime import date
from pathlib import Path

import boto3
from botocore.stub import Stubber
from conftest import REPO, edit_csv, edit_json, edit_xlsx, edit_yaml, fix_iam

from gapcheck.observe.aws import authorization_index
from gapcheck.observe.aws_collect import collect_authorization
from gapcheck.pipeline import RunOptions, run_scenario


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


def test_all_iam_rules_conforming_after_fix(scenario):
    fix_iam(scenario)
    r = run_scenario(scenario, REPO)
    iam = [d for d in r["decisions"] if d["ar_id"].startswith(("AR-2.2.5", "AR-2.5.")) and
           not d["ar_id"].startswith("AR-2.5.4")]
    assert len(iam) == 11
    assert {d["ar_id"]: d["verdict"] for d in iam if d["verdict"] != "CANDIDATE_CONFORMING"} == {}


# ── 2.2.5 퇴직자: 영업일 계산과 연결 ─────────────────────────────────────────

def test_retiree_grace_is_counted_in_business_days(scenario):
    """qa-seo 는 10/30(금) 퇴직. 11/2(월)은 1영업일이라 아직 아님, 11/3(화)은 2영업일이라 결함."""
    r = run_scenario(scenario, REPO)
    assert "222222222222/qa-seo" not in subjects(r, "AR-2.2.5-01")
    r = run_scenario(scenario, REPO, RunOptions(as_of=date(2026, 11, 3)))
    assert "222222222222/qa-seo" in subjects(r, "AR-2.2.5-01")


def test_retiree_without_ledger_is_not_reported_conforming(scenario):
    """계정 관리대장이 없으면 퇴직자와 계정을 이을 수 없다 → 적합이 아니라 미확인."""
    fix_iam(scenario)
    edit_yaml(scenario / "scope.yaml",
              lambda s: s.update(evidence=[e for e in s["evidence"] if e["kind"] != "account_list"]))
    d = decision(run_scenario(scenario, REPO), "AR-2.2.5-01")
    assert d["verdict"] != "CANDIDATE_CONFORMING"
    assert d["verdict"] in ("CANDIDATE_PARTIAL", "INSUFFICIENT_EVIDENCE")


def test_retiree_disabled_by_key_and_password(scenario):
    """비밀번호만 끄고 액세스 키가 살아 있으면 여전히 결함."""
    def rows(rs):
        for r in rs:
            if r["user"] == "intern-jung":
                r["password_enabled"] = "false"
                r["access_key_1_active"] = "true"
                r["access_key_1_last_used_date"] = "2026-10-20T00:00:00+00:00"
    edit_csv(scenario / "aws-snapshot/111111111111/credential_report.csv", rows)
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.2.5-01") == ["111111111111/intern-jung"]


# ── 2.5.1 / 2.5.5 권한 상세 ──────────────────────────────────────────────────

def test_missing_authorization_snapshot_is_partial_collection(scenario):
    """권한 상세 파일이 없는 계정이 있으면 위반이 없어도 '적합'이 아니다."""
    fix_iam(scenario)
    (scenario / "aws-snapshot/333333333333/iam_authorization.json").unlink()
    edit_json(scenario / "aws-snapshot/manifest.json", lambda m: [
        a.update(files=[f for f in a["files"] if f != "iam_authorization.json"])
        for a in m["accounts"] if a["account_id"] == "333333333333"])
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.5.1-02", "AR-2.5.5-01"):
        d = decision(r, ar)
        assert d["verdict"] == "INSUFFICIENT_EVIDENCE", (ar, d)
        assert d["reason_code"] == "PARTIAL_COLLECTION"
    ev = next(e for e in r["evaluations"] if e["ar_id"] == "AR-2.5.1-02")
    assert "iam_authorization.json 없음" in ev["coverage_detail"]


def test_inline_star_policy_counts_as_admin():
    raw = json.dumps({"UserDetailList": [{
        "UserName": "u1", "GroupList": [], "AttachedManagedPolicies": [], "Tags": [],
        "UserPolicyList": [{"PolicyName": "all", "PolicyDocument": {
            "Version": "2012-10-17", "Statement": {"Effect": "Allow", "Action": "*", "Resource": "*"}}}]},
        {"UserName": "u2", "GroupList": ["G"], "AttachedManagedPolicies": [], "UserPolicyList": [], "Tags": []}],
        "GroupDetailList": [{"GroupName": "G", "GroupPolicyList": [], "AttachedManagedPolicies": [
            {"PolicyName": "IAMFullAccess", "PolicyArn": "arn:aws:iam::aws:policy/IAMFullAccess"}]}],
        "Policies": []}).encode()
    idx = authorization_index(raw)
    assert idx["u1"]["admin"] and idx["u1"]["direct_policies"] == ["all(인라인)"]
    assert idx["u2"]["admin"] and idx["u2"]["admin_via"] == ["그룹 G: IAMFullAccess"]


def test_deny_or_scoped_policy_is_not_admin():
    raw = json.dumps({"UserDetailList": [{
        "UserName": "u", "GroupList": [], "AttachedManagedPolicies": [], "Tags": [],
        "UserPolicyList": [
            {"PolicyName": "deny", "PolicyDocument": {"Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}},
            {"PolicyName": "s3", "PolicyDocument": {"Statement": [{"Effect": "Allow", "Action": "s3:*", "Resource": "*"}]}},
        ]}], "GroupDetailList": [], "Policies": []}).encode()
    assert authorization_index(raw)["u"]["admin"] is False


def test_privileged_list_accepts_alias_or_account_id(scenario):
    """특수권한자 목록에 별칭 대신 계정 ID로 적어도 같은 사람으로 본다."""
    edit_xlsx(scenario / "evidence/특수권한자목록_2026-10.xlsx", lambda recs: recs.append(
        {"AWS 계정": "111111111111", "IAM 사용자": "dev-choi", "권한": "AdministratorAccess",
         "승인자": "정보보호팀장", "승인일": "2026-10-31"}))
    assert subjects(run_scenario(scenario, REPO), "AR-2.5.5-01") == []


# ── 2.5.3 규정 근거 ───────────────────────────────────────────────────────────

def test_no_mfa_clause_means_no_mfa_finding_but_not_conforming(scenario):
    """규정에 MFA 조항이 없으면 MFA가 없어도 '규정 위반'으로 단정하지 않는다. 대신 적합도 아니다."""
    import docx
    p = scenario / "docs/A사_접근통제지침_v2.1.docx"
    d = docx.Document(p)
    for para in d.paragraphs:
        if "다중 인증" in para.text and not para.text.startswith("제8조"):
            para.text = "클라우드 관리 콘솔 접속 방법은 운영팀이 따로 안내한다."
    d.save(p)
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.5.3-01", "AR-2.5.3-02"):
        assert subjects(r, ar) == []
        assert decision(r, ar)["verdict"] != "CANDIDATE_CONFORMING"


# ── 2.5.6 검토 주기·장기 미사용 ────────────────────────────────────────────────

def test_review_cadence_uses_latest_record(scenario):
    edit_xlsx(scenario / "evidence/접근권한검토기록_2026.xlsx", lambda recs: recs.insert(0,
              {"검토일": "2026-09-30", "검토자": "정보보호팀 박○○", "범위": "AWS 3개 계정", "결과": "이상 없음"}))
    assert decision(run_scenario(scenario, REPO), "AR-2.5.6-01")["verdict"] == "CANDIDATE_CONFORMING"


def test_never_used_user_counts_from_creation(scenario):
    """한 번도 안 쓴 계정은 만든 날부터 센다. 최근에 만든 계정은 결함이 아니다."""
    def rows(rs):
        new = dict(rs[-1])
        new.update(user="new-hire", password_enabled="true", password_last_used="N/A",
                   user_creation_time="2026-10-30T00:00:00+00:00", password_last_changed="2026-10-30T00:00:00+00:00",
                   mfa_active="true", access_key_1_active="false")
        old = dict(new, user="ghost", user_creation_time="2026-01-05T00:00:00+00:00",
                   password_last_changed="2026-10-01T00:00:00+00:00")
        rs += [new, old]
    edit_csv(scenario / "aws-snapshot/333333333333/credential_report.csv", rows)
    s = subjects(run_scenario(scenario, REPO), "AR-2.5.6-02")
    assert "333333333333/ghost" in s and "333333333333/new-hire" not in s


# ── 증적 인식 ────────────────────────────────────────────────────────────────

def test_evidence_kind_is_detected_by_header_not_filename(scenario):
    ev = scenario / "evidence"
    (ev / "특수권한자목록_2026-10.xlsx").rename(ev / "scan_0001.xlsx")
    edit_yaml(scenario / "scope.yaml", lambda s: [
        e.update(file="evidence/scan_0001.xlsx", kind="evidence") for e in s["evidence"]
        if e["file"].endswith("특수권한자목록_2026-10.xlsx")])
    r = run_scenario(scenario, REPO)
    assert {"file": "evidence/scan_0001.xlsx", "kind": "privileged_list", "sheet": "특수권한자 목록",
            "rows": 2} in r["evidence_tables"]
    assert subjects(r, "AR-2.5.5-01") == ["111111111111/dev-choi"]


def test_violation_messages_have_no_raw_values():
    r = run_scenario(REPO / "scenarios/a-corp-dev", REPO)
    for e in r["evaluations"]:
        for v in e["violations"]:
            assert "None" not in v["message"] and "True" not in v["message"], v["message"]
    plain = " ".join(" ".join(i["found"]) for i in r["plain"]["items"])
    for w in ("{", "None", "111111111111", "True"):
        assert w not in plain, w


# ── 수집기 ───────────────────────────────────────────────────────────────────

def test_collect_authorization_pages():
    iam = boto3.client("iam", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(iam) as st:
        filt = {"Filter": ["User", "Group", "LocalManagedPolicy"]}
        st.add_response("get_account_authorization_details", {
            "UserDetailList": [{"UserName": "a", "UserId": "AIDAAAAAAAAAAAAAAAAAA", "Arn": "arn:aws:iam::1:user/a",
                                "Path": "/", "CreateDate": "2026-01-01T00:00:00Z", "GroupList": ["G"]}],
            "IsTruncated": True, "Marker": "m1"}, filt)
        st.add_response("get_account_authorization_details", {
            "GroupDetailList": [{"GroupName": "G", "GroupId": "AGPAAAAAAAAAAAAAAAAAA", "Arn": "arn:aws:iam::1:group/G",
                                 "Path": "/", "CreateDate": "2026-01-01T00:00:00Z"}],
            "IsTruncated": False}, {**filt, "Marker": "m1"})
        out = collect_authorization(iam)
    assert [u["UserName"] for u in out["UserDetailList"]] == ["a"]
    assert [g["GroupName"] for g in out["GroupDetailList"]] == ["G"]


def test_collect_authorization_denied_is_recorded():
    iam = boto3.client("iam", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(iam) as st:
        st.add_client_error("get_account_authorization_details", "AccessDenied")
        out = collect_authorization(iam)
    assert out["Error"]["Code"] == "AccessDenied"


# ── lint ─────────────────────────────────────────────────────────────────────

def _lint_with(tmp_path: Path, mutate):
    import shutil

    import yaml

    from gapcheck.compiler.lint import lint_paths
    req = tmp_path / "requirements"
    shutil.copytree(REPO / "requirements", req)
    p = req / "2.5/2.5.3.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    mutate(d["requirements"][0])
    p.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    return lint_paths(req, REPO / "sources")


def test_lint_check_population_must_be_observation(tmp_path):
    def m(ar):
        ar["tests"][2]["check"]["population"] = "T1"
    rep = _lint_with(tmp_path, m)
    assert any("check.population" in f.message for f in rep.errors)


def test_lint_check_needs_op_or_join(tmp_path):
    def m(ar):
        c = ar["tests"][2]["check"]
        c.pop("op")
        c.pop("field")
    rep = _lint_with(tmp_path, m)
    assert any("op 또는 join" in f.message for f in rep.errors)


def test_lint_check_requires_population_definition(tmp_path):
    rep = _lint_with(tmp_path, lambda ar: ar.pop("population"))
    assert any(f.rule == "RC-006" for f in rep.errors)
