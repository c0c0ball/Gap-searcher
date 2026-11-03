"""2단계(암호화) 테스트: 2.7.1, 2.7.2.

정답지 일치는 test_pipeline 이 본다. 여기서는 판단 경계(AWS 관리형 키, 전환 리스너, 개인정보 여부),
자료가 빠졌을 때의 처리, 수집기를 확인한다.
"""
import boto3
from botocore.stub import Stubber
from conftest import REPO, edit_json, edit_xlsx, fix_crypto

from gapcheck.observe.aws_collect import collect_kms, collect_s3
from gapcheck.observe.crypto import key_account
from gapcheck.pipeline import run_scenario

PROD, STG = "aws-snapshot/111111111111", "aws-snapshot/222222222222"
CRYPTO = ("AR-2.7.1-01", "AR-2.7.1-02", "AR-2.7.1-03", "AR-2.7.1-04", "AR-2.7.1-05",
          "AR-2.7.2-01", "AR-2.7.2-02", "AR-2.7.2-03")


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


def test_all_crypto_rules_conforming_after_fix(scenario):
    fix_crypto(scenario)
    r = run_scenario(scenario, REPO)
    assert {a: decision(r, a)["verdict"] for a in CRYPTO if decision(r, a)["verdict"] != "CANDIDATE_CONFORMING"} == {}


def test_key_account_from_arn_or_alias():
    assert key_account("arn:aws:kms:ap-northeast-2:111111111111:key/abc", "222222222222") == "111111111111"
    assert key_account("alias/prod-data", "222222222222") == "222222222222"
    assert key_account(None, "222222222222") is None


def test_bucket_becomes_personal_by_asset_list(scenario):
    """정적 파일 버킷도 정보자산 목록에서 개인정보 포함으로 바뀌면 KMS가 필요하다."""
    fix_crypto(scenario)
    edit_xlsx(scenario / "evidence/정보자산목록_2026-10.xlsx", lambda recs: [
        r.update({"개인정보": "Y"}) for r in recs if r["자산ID"] == "A-ST-003"])
    assert subjects(run_scenario(scenario, REPO), "AR-2.7.1-03") == ["111111111111/a-prod-static-assets"]


def test_no_asset_list_is_not_conforming(scenario):
    """정보자산 목록이 없으면 어떤 버킷에 개인정보가 있는지 몰라 '적합'으로 보지 않는다."""
    import yaml
    fix_crypto(scenario)
    p = scenario / "scope.yaml"
    s = yaml.safe_load(p.read_text(encoding="utf-8"))
    s["evidence"] = [e for e in s["evidence"] if e.get("kind") != "asset_list"]
    p.write_text(yaml.safe_dump(s, allow_unicode=True), encoding="utf-8")
    assert decision(run_scenario(scenario, REPO), "AR-2.7.1-03")["verdict"] != "CANDIDATE_CONFORMING"


def test_internal_or_redirect_http_is_not_plaintext_but_https_to_http_redirect_is(scenario):
    fix_crypto(scenario)

    def lb(lbs):   # 리디렉션이 HTTP 로 가면 평문 서비스
        for li in lbs[0]["Listeners"]:
            if li["Port"] == 80:
                li["DefaultActions"][0]["RedirectConfig"]["Protocol"] = "HTTP"
    edit_json(scenario / PROD / "elbv2_listeners.json", lb)
    assert subjects(run_scenario(scenario, REPO), "AR-2.7.1-04") == ["111111111111/prod-web:80"]


def test_unknown_ssl_policy_is_not_counted_as_safe(scenario):
    """보안 정책 상세(허용 TLS)를 수집하지 못하면 판단 불가 — 통과로 보지 않는다."""
    fix_crypto(scenario)
    (scenario / STG / "elbv2_ssl_policies.json").write_text("[]")
    d = decision(run_scenario(scenario, REPO), "AR-2.7.1-05")
    assert d["verdict"] != "CANDIDATE_CONFORMING"


def test_disabled_or_aws_managed_keys_are_not_rotation_targets(scenario):
    fix_crypto(scenario)

    def ks(keys):
        keys.append({"KeyId": "dead", "Arn": "arn:aws:kms:ap-northeast-2:111111111111:key/dead", "KeyManager": "CUSTOMER",
                     "KeyState": "PendingDeletion", "Aliases": ["alias/old"], "KeyRotationEnabled": False})
    edit_json(scenario / PROD / "kms_keys.json", ks)
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.7.2-01") == []
    # 삭제 대기 중인 키도 고객 관리형이면 관리대장에는 있어야 한다
    assert subjects(r, "AR-2.7.2-03") == ["111111111111/dead"]


def test_cross_account_key_on_s3_and_rds(scenario):
    fix_crypto(scenario)
    prod_key = "arn:aws:kms:ap-northeast-2:111111111111:key/1a1a1a1a-0000-4000-8000-000000000001"
    edit_json(scenario / STG / "s3_buckets.json", lambda bs: bs[0]["Encryption"][0][
        "ApplyServerSideEncryptionByDefault"].update(KMSMasterKeyID=prod_key))
    edit_json(scenario / STG / "rds_db_instances.json", lambda d: d[0].update(KmsKeyId=prod_key))
    assert subjects(run_scenario(scenario, REPO), "AR-2.7.2-02") == ["222222222222/a-stg-test-data",
                                                                     "222222222222/stg-orders"]


def test_missing_kms_snapshot_is_partial(scenario):
    fix_crypto(scenario)
    (scenario / "aws-snapshot/333333333333/kms_keys.json").unlink()
    edit_json(scenario / "aws-snapshot/manifest.json", lambda m: [
        a.update(files=[f for f in a["files"] if f != "kms_keys.json"])
        for a in m["accounts"] if a["account_id"] == "333333333333"])
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.7.2-01", "AR-2.7.2-03"):
        d = decision(r, ar)
        assert d["verdict"] == "INSUFFICIENT_EVIDENCE" and d["reason_code"] == "PARTIAL_COLLECTION", (ar, d)


# ── 수집기 ───────────────────────────────────────────────────────────────────

def _c(svc):
    return boto3.client(svc, region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="x")


def test_collect_s3_without_default_encryption():
    s3 = _c("s3")
    with Stubber(s3) as st:
        st.add_response("list_buckets", {"Buckets": [{"Name": "b1"}]})
        st.add_response("get_bucket_location", {"LocationConstraint": "ap-northeast-2"}, {"Bucket": "b1"})
        st.add_client_error("get_bucket_encryption", "ServerSideEncryptionConfigurationNotFoundError",
                            expected_params={"Bucket": "b1"})
        out = collect_s3(s3)
    assert out == [{"Name": "b1", "Region": "ap-northeast-2", "Encryption": []}]


def test_collect_kms_rotation_only_for_enabled_customer_keys():
    kms = _c("kms")
    with Stubber(kms) as st:
        st.add_response("list_keys", {"Keys": [{"KeyId": "k1"}, {"KeyId": "k2"}]})
        st.add_response("list_aliases", {"Aliases": [{"AliasName": "alias/a", "TargetKeyId": "k1"}]})
        st.add_response("describe_key", {"KeyMetadata": {"KeyId": "k1", "Arn": "arn:aws:kms:ap-northeast-2:1:key/k1",
                                                         "KeyManager": "CUSTOMER", "KeyState": "Enabled",
                                                         "KeySpec": "SYMMETRIC_DEFAULT"}}, {"KeyId": "k1"})
        st.add_response("get_key_rotation_status", {"KeyRotationEnabled": False}, {"KeyId": "k1"})
        st.add_response("describe_key", {"KeyMetadata": {"KeyId": "k2", "Arn": "arn:aws:kms:ap-northeast-2:1:key/k2",
                                                         "KeyManager": "AWS", "KeyState": "Enabled",
                                                         "KeySpec": "SYMMETRIC_DEFAULT"}}, {"KeyId": "k2"})
        out = collect_kms(kms)
    assert out[0]["Aliases"] == ["alias/a"] and out[0]["KeyRotationEnabled"] is False
    assert "KeyRotationEnabled" not in out[1]
