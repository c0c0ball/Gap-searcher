"""관통 테스트 (2.5.4 파일럿 + 2단계 IAM). 개발용 정답지 일치 + 판정 순서·범위·품질 규칙을 변형 시나리오로 확인한다."""
import csv
import io
import json

from conftest import REPO, SCENARIO, edit_json, edit_yaml, fix_iam

from gapcheck.cli import compare_expected
from gapcheck.pipeline import run_scenario


def verdicts(r):
    return {d["ar_id"]: d["verdict"] for d in r["decisions"]}


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


# ── 정답지 ──────────────────────────────────────────────────────────────────

def test_dev_answer_key_matches():
    r = run_scenario(SCENARIO, REPO)
    lines = compare_expected(r, SCENARIO / "expected" / "dev_expected.yaml")
    assert all(l.startswith("✓") for l in lines), lines


def test_deterministic_ten_runs():
    hashes = {run_scenario(SCENARIO, REPO)["result_hash"] for _ in range(10)}
    assert len(hashes) == 1


def test_every_finding_traces_to_hashed_artifacts():
    r = run_scenario(SCENARIO, REPO)
    shas = {a["sha256"] for a in r["artifacts"]}
    obs = {o["obs_id"]: o for o in r["observations"]}
    assert r["findings"]
    for f in r["findings"]:
        assert f["obs_ids"], f
        for oid in f["obs_ids"]:
            o = obs[oid]
            src = [c["artifact_sha256"] for c in o["citations"]]
            s = o["source"].get("sha256")
            src += s if isinstance(s, list) else ([s] if s else [])
            assert src and all(x in shas for x in src if x), (oid, src)


def test_document_citations_are_verbatim():
    r = run_scenario(SCENARIO, REPO)
    for o in r["observations"]:
        for c in o["citations"]:
            assert c["verified"], c


# ── 결함이 고쳐진 시나리오 ──────────────────────────────────────────────────────

def _fix_all(sc):
    def fix_policy(d):
        d["PasswordPolicy"]["MinimumPasswordLength"] = 10
    edit_json(sc / "aws-snapshot/111111111111/iam_password_policy.json", fix_policy)
    (sc / "aws-snapshot/222222222222/iam_password_policy.json").write_text(json.dumps({"PasswordPolicy": {
        "MinimumPasswordLength": 10, "RequireSymbols": True, "RequireNumbers": True,
        "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True, "ExpirePasswords": True,
        "MaxPasswordAge": 90, "PasswordReusePrevention": 3}}))
    p = sc / "aws-snapshot/111111111111/credential_report.csv"
    rows = list(csv.DictReader(io.StringIO(p.read_text())))
    for row in rows:
        if row["user"] == "ops-kim":
            row["password_last_changed"] = "2026-10-01T03:00:00+00:00"
        if row["user"] == "dev-lee":
            row["password_last_changed"] = "2026-09-01T03:00:00+00:00"
    buf = io.StringIO()
    w = csv.DictWriter(buf, rows[0].keys())
    w.writeheader()
    w.writerows(rows)
    p.write_text(buf.getvalue())
    edit_json(sc / "aws-snapshot/111111111111/cognito_user_pools.json",
              lambda d: d[0]["Policies"]["PasswordPolicy"].update(MinimumLength=8))
    fix_iam(sc)


def test_fixed_scenario_is_conforming(scenario):
    _fix_all(scenario)
    v = verdicts(run_scenario(scenario, REPO))
    assert set(v.values()) == {"CANDIDATE_CONFORMING"}, v


def test_ops_kim_who_changed_password_is_not_flagged(scenario):
    _fix_all(scenario)
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.5.4-03") == []


# ── 판정 순서 (D05) ──────────────────────────────────────────────────────────

def _drop_account(sc, aid):
    def f(m):
        for a in m["accounts"]:
            if a["account_id"] == aid:
                a["status"] = "failed"
                a["errors"] = ["AccessDenied"]
    edit_json(sc / "aws-snapshot/manifest.json", f)


def test_violation_beats_partial_coverage(scenario):
    """stg 수집이 실패해도 prod에서 확인된 위반은 결함 후보로 나와야 한다."""
    _drop_account(scenario, "222222222222")
    r = run_scenario(scenario, REPO)
    d = decision(r, "AR-2.5.4-02")
    assert d["verdict"] == "CANDIDATE_NONCONFORMITY"
    assert "범위 일부 미수집" in d["reason"]
    assert subjects(r, "AR-2.5.4-02") == ["111111111111"]


def test_partial_coverage_without_violation_is_insufficient(scenario):
    """위반이 없는데 한 계정을 못 봤다면 '적합'이 아니라 '미확인'."""
    _fix_all(scenario)
    _drop_account(scenario, "222222222222")
    d = decision(run_scenario(scenario, REPO), "AR-2.5.4-02")
    assert d["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert d["reason_code"] == "PARTIAL_COLLECTION"


def test_missing_scope_fact_is_scope_incomplete(scenario):
    edit_yaml(scenario / "scope.yaml", lambda s: s["facts"].pop("scope.has_aws_accounts"))
    d = decision(run_scenario(scenario, REPO), "AR-2.5.4-02")
    assert (d["verdict"], d["reason_code"]) == ("INSUFFICIENT_EVIDENCE", "SCOPE_INCOMPLETE")


def test_false_scope_fact_needs_exclusion_approval(scenario):
    edit_yaml(scenario / "scope.yaml",
              lambda s: s["facts"]["scope.service_has_customer_login"].update(value=False))
    assert decision(run_scenario(scenario, REPO), "AR-2.5.4-05")["verdict"] == "NOT_APPLICABLE_PENDING"


# ── 문서 범위·부재 ───────────────────────────────────────────────────────────

def test_missing_policy_document_blocks_absence_claim(scenario):
    """선언된 문서 하나가 없으면 '규칙 없음'을 결함으로 단정하지 않는다."""
    (scenario / "docs/A사_접근통제지침_v2.1.docx").unlink()
    r = run_scenario(scenario, REPO)
    d = decision(r, "AR-2.5.4-01")
    assert d["verdict"] == "INSUFFICIENT_EVIDENCE"
    assert r["document_coverage"]["status"] == "PARTIAL_COLLECTION"


def test_rule_absent_with_full_coverage_is_violation(scenario):
    """문서가 다 있는데 비밀번호 규칙이 어디에도 없으면 AR-01 결함 후보."""
    (scenario / "docs/A사_접근통제지침_v2.1.docx").unlink()
    edit_yaml(scenario / "scope.yaml", lambda s: s.update(policy_documents=[
        d for d in s["policy_documents"] if "접근통제" not in d["file"]]))
    r = run_scenario(scenario, REPO)
    assert decision(r, "AR-2.5.4-01")["verdict"] == "CANDIDATE_NONCONFORMITY"
    # 정책값이 없으니 비교 자체를 못 한다 → 02는 결함도 적합도 아니고 외부엔 '미확인'
    d2 = decision(r, "AR-2.5.4-02")
    assert d2["verdict"] in ("INSUFFICIENT_EVIDENCE", "CANDIDATE_PARTIAL")
    assert d2["external_label_pending"] == "미확인"


def test_undeclared_documents_mean_unknown_denominator(scenario):
    edit_yaml(scenario / "scope.yaml", lambda s: s.pop("policy_documents"))
    r = run_scenario(scenario, REPO)
    assert r["document_coverage"]["status"] == "DENOMINATOR_UNKNOWN"
    assert decision(r, "AR-2.5.4-01")["verdict"] == "INSUFFICIENT_EVIDENCE"


# ── 품질 ───────────────────────────────────────────────────────────────────

def test_stale_snapshot_is_not_used(scenario):
    edit_json(scenario / "aws-snapshot/manifest.json",
              lambda m: m.update(collected_at="2026-09-01T00:00:00+00:00"))
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.5.4-02", "AR-2.5.4-03", "AR-2.5.4-04", "AR-2.5.4-05"):
        assert decision(r, ar)["verdict"] == "INSUFFICIENT_EVIDENCE", ar


def test_cognito_off_leaves_screen_review_for_human(scenario):
    edit_yaml(scenario / "scope.yaml", lambda s: s["facts"]["scope.uses_cognito"].update(value=False))
    d = decision(run_scenario(scenario, REPO), "AR-2.5.4-05")
    assert d["verdict"] == "CANDIDATE_PARTIAL"
    assert "사람 검토" in d["reason"]


def test_service_account_and_root_excluded(scenario):
    r = run_scenario(scenario, REPO)
    users = [o["subject"] for o in r["observations"] if o["kind"] == "aws_user"]
    assert not any(u.endswith("<root_account>") for u in users)
    assert not any("svc-batch" in s for f in r["findings"] for s in [f["subject"]])
