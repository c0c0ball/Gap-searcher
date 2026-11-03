"""2단계(로그·백업) 테스트: 2.5.6-03, 2.9.3, 2.9.4, 2.9.5, 2.12.2.

정답지 일치는 test_pipeline 이 본다. 여기서는 IAM 변경 기록 판정, 보관기간·백업 대상의 경계,
증적이 없을 때 '판단 못함'으로 남는지, 수집기를 확인한다.
"""
import boto3
from botocore.stub import Stubber
from conftest import REPO, edit_json, edit_xlsx, edit_yaml, fix_logging

from gapcheck.observe.aws_collect import add_bucket_lifecycle, collect_guardduty, collect_trails
from gapcheck.observe.logging import _records_iam, bucket_retention
from gapcheck.pipeline import run_scenario

PROD, STG, SHARED = (f"aws-snapshot/{a}" for a in ("111111111111", "222222222222", "333333333333"))
LOG = ("AR-2.5.6-03", "AR-2.9.3-01", "AR-2.9.3-02", "AR-2.9.3-03", "AR-2.9.4-01", "AR-2.9.4-02", "AR-2.9.4-03",
       "AR-2.9.5-01", "AR-2.9.5-02", "AR-2.12.2-01")


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


def test_all_logging_rules_conforming_after_fix(scenario):
    fix_logging(scenario)
    r = run_scenario(scenario, REPO)
    assert {a: decision(r, a)["verdict"] for a in LOG if decision(r, a)["verdict"] != "CANDIDATE_CONFORMING"} == {}


# ── IAM 변경 기록 ────────────────────────────────────────────────────────────

def _t(**kw):
    base = {"Status": {"IsLogging": True}, "IsMultiRegionTrail": True, "IncludeGlobalServiceEvents": True}
    return {**base, **kw}


def test_records_iam_changes_rules():
    assert _records_iam(_t())                                                    # 선택기 없음 = 관리 이벤트 전체
    assert not _records_iam(_t(Status={"IsLogging": False}))
    assert not _records_iam(_t(IsMultiRegionTrail=False, IncludeGlobalServiceEvents=False))
    assert _records_iam(_t(IsMultiRegionTrail=False))                            # 단일 리전이어도 전역 이벤트 포함이면 남음
    assert not _records_iam(_t(EventSelectors=[{"ReadWriteType": "ReadOnly", "IncludeManagementEvents": True}]))
    assert not _records_iam(_t(EventSelectors=[{"ReadWriteType": "All", "IncludeManagementEvents": False}]))
    mgmt = {"Field": "eventCategory", "Equals": ["Management"]}
    assert _records_iam(_t(AdvancedEventSelectors=[{"FieldSelectors": [mgmt]}]))
    assert not _records_iam(_t(AdvancedEventSelectors=[{"FieldSelectors": [
        mgmt, {"Field": "readOnly", "Equals": ["true"]}]}]))
    assert not _records_iam(_t(AdvancedEventSelectors=[{"FieldSelectors": [
        {"Field": "eventCategory", "Equals": ["Data"]}]}]))


def test_account_without_any_trail(scenario):
    fix_logging(scenario)
    (scenario / SHARED / "cloudtrail_trails.json").write_text("[]")
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.9.4-01") == ["333333333333/cloudtrail"]
    assert subjects(r, "AR-2.5.6-03") == ["333333333333/cloudtrail"]


# ── 보관기간 ─────────────────────────────────────────────────────────────────

def test_bucket_retention_uses_shortest_enabled_rule():
    assert bucket_retention(None)[0] == 36500
    assert bucket_retention([{"Status": "Disabled", "Expiration": {"Days": 30}}])[0] == 36500
    assert bucket_retention([{"Status": "Enabled", "Expiration": {"Days": 900}},
                             {"Status": "Enabled", "Expiration": {"Days": 400}}]) == (400, "400일 후 삭제")


def test_trail_bucket_not_collected_is_unknown_not_pass(scenario):
    """감사 로그를 다른 계정 버킷에 저장하는데 그 버킷을 수집하지 못하면 판단 불가."""
    fix_logging(scenario)
    edit_json(scenario / PROD / "cloudtrail_trails.json", lambda ts: ts[0].update(S3BucketName="org-central-logs"))
    d = decision(run_scenario(scenario, REPO), "AR-2.9.4-03")
    assert d["verdict"] != "CANDIDATE_CONFORMING"


# ── 백업 ─────────────────────────────────────────────────────────────────────

def test_copy_to_same_region_is_not_offsite(scenario):
    fix_logging(scenario)
    edit_json(scenario / PROD / "backup_plans.json", lambda ps: ps[0]["Rules"][0].update(CopyActions=[{
        "DestinationBackupVaultArn": "arn:aws:backup:ap-northeast-2:111111111111:backup-vault:other"}]))
    assert subjects(run_scenario(scenario, REPO), "AR-2.9.3-02") == ["111111111111/backup"]


def test_offsite_required_only_where_critical_assets_exist(scenario):
    """중요도 '상' 자원이 하나도 없으면 다른 리전 복사가 없어도 결함이 아니다."""
    edit_xlsx(scenario / "evidence/정보자산목록_2026-10.xlsx", lambda rs: [r.update({"중요도": "중"}) for r in rs])
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.9.3-02") == [] and subjects(r, "AR-2.9.3-01") == []


def test_automated_backup_off_is_violation(scenario):
    fix_logging(scenario)
    edit_json(scenario / PROD / "rds_db_instances.json", lambda d: d[0].update(BackupRetentionPeriod=0))
    assert subjects(run_scenario(scenario, REPO), "AR-2.9.3-01") == ["111111111111/prod-orders"]


# ── 증적 주기 ────────────────────────────────────────────────────────────────

def test_dr_drill_submitted_but_old_is_violation(scenario):
    fix_logging(scenario)
    edit_xlsx(scenario / "evidence/재해복구훈련기록_2026.xlsx", lambda rs: rs[0].update({"훈련일": "2025-09-01"}))
    r = run_scenario(scenario, REPO)
    assert decision(r, "AR-2.12.2-01")["verdict"] == "CANDIDATE_NONCONFORMITY"


def test_cycle_comes_from_policy(scenario):
    """지침의 점검 주기를 분기로 바꾸면 63일 지난 점검도 결함이 아니다 (법정 주기를 따로 쓰지 않음, D08)."""
    import docx
    p = scenario / "docs/A사_운영보안지침_v1.0.docx"
    d = docx.Document(p)
    for para in d.paragraphs:
        if para.text.startswith("① 개인정보처리시스템 접속기록은 월 1회"):
            para.text = para.text.replace("월 1회", "분기 1회")
    d.save(p)
    assert decision(run_scenario(scenario, REPO), "AR-2.9.5-02")["verdict"] == "CANDIDATE_CONFORMING"


# ── 수집기 ───────────────────────────────────────────────────────────────────

def _c(svc):
    return boto3.client(svc, region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="x")


def test_collect_trails_with_status_and_selectors():
    ct = _c("cloudtrail")
    arn = "arn:aws:cloudtrail:ap-northeast-2:1:trail/t"
    with Stubber(ct) as st:
        st.add_response("describe_trails", {"trailList": [{"Name": "t", "TrailARN": arn}]}, {"includeShadowTrails": False})
        st.add_response("get_trail_status", {"IsLogging": False}, {"Name": arn})
        st.add_response("get_event_selectors", {"TrailARN": arn, "AdvancedEventSelectors": [
            {"FieldSelectors": [{"Field": "eventCategory", "Equals": ["Management"]}]}]}, {"TrailName": arn})
        out = collect_trails(ct)
    assert out[0]["Status"] == {"IsLogging": False} and "AdvancedEventSelectors" in out[0]


def test_collect_guardduty_none():
    gd = _c("guardduty")
    with Stubber(gd) as st:
        st.add_response("list_detectors", {"DetectorIds": []})
        assert collect_guardduty(gd) == []


def test_bucket_lifecycle_missing_means_keep():
    s3 = _c("s3")
    bs = [{"Name": "logs"}]
    with Stubber(s3) as st:
        st.add_client_error("get_bucket_lifecycle_configuration", "NoSuchLifecycleConfiguration",
                            expected_params={"Bucket": "logs"})
        add_bucket_lifecycle(s3, bs)
    assert bs[0]["Lifecycle"] == []
