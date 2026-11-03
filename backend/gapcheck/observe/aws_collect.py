"""live AWS 수집기. 읽기 전용 역할을 AssumeRole 해서 스냅샷 형식으로 저장한다.

- 장기 액세스 키를 받지 않는다. 호출자 자격으로 대상 계정의 역할을 ExternalId와 함께 맡는다.
- 맡은 뒤 sts:GetCallerIdentity 로 계정 ID를 확인하고, 기대한 계정이 아니면 중단한다.
- 권한 거부·오류는 결함이 아니라 수집 상태(status)로 기록한다.
"""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def assume(role_arn: str, external_id: str, session_name: str = "gapcheck-collector",
           base: boto3.Session | None = None) -> boto3.Session:
    sts = (base or boto3.Session()).client("sts")
    c = sts.assume_role(RoleArn=role_arn, RoleSessionName=session_name, ExternalId=external_id,
                        DurationSeconds=900)["Credentials"]
    return boto3.Session(aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                         aws_session_token=c["SessionToken"])


def _err(e: ClientError) -> dict:
    return {"Error": {"Code": e.response["Error"]["Code"], "Message": e.response["Error"].get("Message", "")}}


def collect_password_policy(iam) -> dict:
    try:
        return {"PasswordPolicy": iam.get_account_password_policy()["PasswordPolicy"]}
    except ClientError as e:
        return _err(e)


def collect_credential_report(iam, wait: float = 2.0, attempts: int = 15) -> bytes | dict:
    try:
        for _ in range(attempts):
            if iam.generate_credential_report()["State"] == "COMPLETE":
                break
            time.sleep(wait)
        return iam.get_credential_report()["Content"]
    except ClientError as e:
        return _err(e)


def collect_login_profiles(iam) -> dict:
    out: dict[str, dict] = {}
    for page in iam.get_paginator("list_users").paginate():
        for u in page["Users"]:
            name = u["UserName"]
            try:
                lp = iam.get_login_profile(UserName=name)["LoginProfile"]
                out[name] = {"CreateDate": lp["CreateDate"].isoformat(),
                             "PasswordResetRequired": lp.get("PasswordResetRequired", False)}
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchEntity":
                    out[name] = _err(e)
    return out


def collect_authorization(iam) -> dict:
    """GetAccountAuthorizationDetails: 사용자·그룹의 정책 연결과 고객 관리형 정책 문서 (권한 판정용)"""
    try:
        out: dict[str, list] = {"UserDetailList": [], "GroupDetailList": [], "RoleDetailList": [], "Policies": []}
        pages = iam.get_paginator("get_account_authorization_details").paginate(
            Filter=["User", "Group", "LocalManagedPolicy"])
        for page in pages:
            for k in out:
                out[k] += page.get(k, [])
        return out
    except ClientError as e:
        return _err(e)


def _pages(client, op: str, key: str, **kw) -> list | dict:
    try:
        out: list = []
        for page in client.get_paginator(op).paginate(**kw):
            out += page.get(key, [])
        return out
    except ClientError as e:
        return _err(e)


def collect_network(ec2, rds) -> dict[str, list | dict]:
    """2.6 네트워크: 보안그룹·서브넷·라우팅 테이블·RDS. 파일 이름 → 내용"""
    return {
        "ec2_security_groups.json": _pages(ec2, "describe_security_groups", "SecurityGroups"),
        "ec2_subnets.json": _pages(ec2, "describe_subnets", "Subnets"),
        "ec2_route_tables.json": _pages(ec2, "describe_route_tables", "RouteTables"),
        "rds_db_instances.json": _pages(rds, "describe_db_instances", "DBInstances"),
    }


def collect_s3(s3) -> list | dict:
    """버킷마다 기본 암호화. 기본 암호화가 없으면 Encryption = [] (2023년 이후 버킷은 SSE-S3가 기본)"""
    try:
        names = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    except ClientError as e:
        return _err(e)
    out = []
    for n in names:
        item: dict = {"Name": n}
        try:
            item["Region"] = s3.get_bucket_location(Bucket=n).get("LocationConstraint") or "us-east-1"
        except ClientError as e:
            item["Region"] = None
            item["LocationError"] = e.response["Error"]["Code"]
        try:
            item["Encryption"] = s3.get_bucket_encryption(Bucket=n)["ServerSideEncryptionConfiguration"]["Rules"]
        except ClientError as e:
            code = e.response["Error"]["Code"]
            item["Encryption"] = [] if code == "ServerSideEncryptionConfigurationNotFoundError" else _err(e)
        out.append(item)
    return out


def collect_kms(kms) -> list | dict:
    keys = _pages(kms, "list_keys", "Keys")
    if isinstance(keys, dict):
        return keys
    aliases = _pages(kms, "list_aliases", "Aliases")
    by_key: dict[str, list[str]] = {}
    for a in aliases if isinstance(aliases, list) else []:
        if a.get("TargetKeyId"):
            by_key.setdefault(a["TargetKeyId"], []).append(a["AliasName"])
    out = []
    for k in keys:
        try:
            meta = kms.describe_key(KeyId=k["KeyId"])["KeyMetadata"]
        except ClientError as e:
            out.append({"KeyId": k["KeyId"], **_err(e)})
            continue
        item = {"KeyId": meta["KeyId"], "Arn": meta["Arn"], "KeyManager": meta.get("KeyManager"),
                "KeyState": meta.get("KeyState"), "KeySpec": meta.get("KeySpec"),
                "Description": meta.get("Description", ""), "Aliases": sorted(by_key.get(meta["KeyId"], []))}
        if meta.get("KeyManager") == "CUSTOMER" and meta.get("KeySpec") == "SYMMETRIC_DEFAULT" \
                and meta.get("KeyState") == "Enabled":
            try:
                item["KeyRotationEnabled"] = kms.get_key_rotation_status(KeyId=meta["KeyId"])["KeyRotationEnabled"]
            except ClientError as e:
                item["RotationError"] = e.response["Error"]["Code"]
        out.append(item)
    return out


def collect_listeners(elb) -> tuple[list | dict, list | dict]:
    lbs = _pages(elb, "describe_load_balancers", "LoadBalancers")
    if isinstance(lbs, dict):
        return lbs, lbs
    out, used = [], set()
    for lb in lbs:
        ls = _pages(elb, "describe_listeners", "Listeners", LoadBalancerArn=lb["LoadBalancerArn"])
        if isinstance(ls, dict):
            return ls, ls
        used |= {x["SslPolicy"] for x in ls if x.get("SslPolicy")}
        out.append({"LoadBalancerName": lb["LoadBalancerName"], "LoadBalancerArn": lb["LoadBalancerArn"],
                    "Scheme": lb.get("Scheme"), "Type": lb.get("Type"), "Listeners": ls})
    try:
        pol = elb.describe_ssl_policies(Names=sorted(used))["SslPolicies"] if used else []
    except ClientError as e:
        pol = _err(e)
    return out, pol


def collect_crypto(ec2, s3, kms, elb) -> dict[str, list | dict]:
    """2.7 암호화: EBS·S3·KMS·로드밸런서 리스너. 파일 이름 → 내용"""
    listeners, policies = collect_listeners(elb)
    return {
        "ec2_volumes.json": _pages(ec2, "describe_volumes", "Volumes"),
        "s3_buckets.json": collect_s3(s3),
        "kms_keys.json": collect_kms(kms),
        "elbv2_listeners.json": listeners,
        "elbv2_ssl_policies.json": policies,
    }


def collect_trails(ct) -> list | dict:
    """trail마다 상태와 이벤트 선택기를 붙인다. 고급 이벤트 선택기만 쓰면 AdvancedEventSelectors 로 남긴다."""
    try:
        trails = ct.describe_trails(includeShadowTrails=False)["trailList"]
    except ClientError as e:
        return _err(e)
    for t in trails:
        arn = t["TrailARN"]
        try:
            t["Status"] = {"IsLogging": ct.get_trail_status(Name=arn)["IsLogging"]}
        except ClientError as e:
            t["Status"] = _err(e)
        try:
            sel = ct.get_event_selectors(TrailName=arn)
            if "EventSelectors" in sel:
                t["EventSelectors"] = sel["EventSelectors"]
            if "AdvancedEventSelectors" in sel:
                t["AdvancedEventSelectors"] = sel["AdvancedEventSelectors"]
        except ClientError as e:
            t["EventSelectorsError"] = e.response["Error"]["Code"]
    return trails


def collect_guardduty(gd) -> list | dict:
    ids = _pages(gd, "list_detectors", "DetectorIds")
    if isinstance(ids, dict):
        return ids
    out = []
    for i in ids:
        try:
            out.append({"DetectorId": i, "Status": gd.get_detector(DetectorId=i)["Status"]})
        except ClientError as e:
            out.append({"DetectorId": i, **_err(e)})
    return out


def collect_backup(bk) -> list | dict:
    plans = _pages(bk, "list_backup_plans", "BackupPlansList")
    if isinstance(plans, dict):
        return plans
    out = []
    for p in plans:
        try:
            out.append(bk.get_backup_plan(BackupPlanId=p["BackupPlanId"])["BackupPlan"])
        except ClientError as e:
            out.append({"BackupPlanName": p.get("BackupPlanName"), **_err(e)})
    return out


def add_bucket_lifecycle(s3, buckets: list) -> None:
    """s3_buckets.json 항목에 수명주기 규칙을 붙인다 (로그 보관기간용)"""
    for b in buckets:
        try:
            b["Lifecycle"] = s3.get_bucket_lifecycle_configuration(Bucket=b["Name"])["Rules"]
        except ClientError as e:
            b["Lifecycle"] = [] if e.response["Error"]["Code"] == "NoSuchLifecycleConfiguration" else None


def collect_cognito(cog) -> list | dict:
    try:
        pools = []
        for page in cog.get_paginator("list_user_pools").paginate(MaxResults=60):
            for p in page["UserPools"]:
                pools.append(cog.describe_user_pool(UserPoolId=p["Id"])["UserPool"])
        return [{"Id": p["Id"], "Name": p.get("Name"), "Policies": p.get("Policies", {})} for p in pools]
    except ClientError as e:
        return _err(e)


def collect_account(session: boto3.Session, expected_account: str, out_dir: Path, region: str) -> dict:
    actual = session.client("sts").get_caller_identity()["Account"]
    if actual != expected_account:
        raise RuntimeError(f"대상 계정 불일치: 기대 {expected_account}, 실제 {actual} — 수집 중단")
    d = out_dir / expected_account
    d.mkdir(parents=True, exist_ok=True)
    iam = session.client("iam")
    status, errors = "ok", []

    pol = collect_password_policy(iam)
    (d / "iam_password_policy.json").write_text(json.dumps(pol, indent=2, default=str))
    if "Error" in pol and pol["Error"]["Code"] != "NoSuchEntity":
        errors.append(f"password_policy: {pol['Error']['Code']}")

    rep = collect_credential_report(iam)
    if isinstance(rep, dict):
        errors.append(f"credential_report: {rep['Error']['Code']}")
    else:
        (d / "credential_report.csv").write_bytes(rep)

    lps = collect_login_profiles(iam)
    (d / "login_profiles.json").write_text(json.dumps(lps, indent=2, default=str))

    az = collect_authorization(iam)
    if "Error" in az:
        errors.append(f"authorization: {az['Error']['Code']}")
    else:
        (d / "iam_authorization.json").write_text(json.dumps(az, indent=2, default=str))

    net = collect_network(session.client("ec2", region_name=region), session.client("rds", region_name=region))
    for name, body in net.items():
        if isinstance(body, dict):   # 오류는 파일을 만들지 않는다 (없는 파일 = 범위 미충족)
            errors.append(f"{name.split('.')[0]}: {body['Error']['Code']}")
        else:
            (d / name).write_text(json.dumps(body, indent=2, default=str))

    s3c = session.client("s3", region_name=region)
    cr = collect_crypto(session.client("ec2", region_name=region), s3c,
                        session.client("kms", region_name=region), session.client("elbv2", region_name=region))
    if isinstance(cr["s3_buckets.json"], list):
        add_bucket_lifecycle(s3c, cr["s3_buckets.json"])
    cr["cloudtrail_trails.json"] = collect_trails(session.client("cloudtrail", region_name=region))
    cr["guardduty.json"] = collect_guardduty(session.client("guardduty", region_name=region))
    cr["backup_plans.json"] = collect_backup(session.client("backup", region_name=region))
    for name, body in cr.items():
        if isinstance(body, dict):
            errors.append(f"{name.split('.')[0]}: {body['Error']['Code']}")
        else:
            (d / name).write_text(json.dumps(body, indent=2, default=str))

    cog = collect_cognito(session.client("cognito-idp", region_name=region))
    (d / "cognito_user_pools.json").write_text(json.dumps(cog, indent=2, default=str))
    if isinstance(cog, dict):
        errors.append(f"cognito: {cog['Error']['Code']}")

    if errors:
        status = "partial"
    return {"account_id": expected_account, "status": status, "errors": errors,
            "files": sorted(f.name for f in d.iterdir())}


def collect(targets: list[dict], out_dir: Path, region: str = "ap-northeast-2") -> dict:
    """targets: [{account_id, alias, role_arn, external_id}]"""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"snapshot_id": f"live-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", "source": "live",
                "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "collector": "gapcheck-collector/0.1", "region": region, "accounts": []}
    for t in targets:
        try:
            s = assume(t["role_arn"], t["external_id"])
            res = collect_account(s, t["account_id"], out_dir, region)
        except Exception as e:  # 연결 실패는 결함이 아니라 수집 실패
            res = {"account_id": t["account_id"], "status": "failed", "errors": [f"{type(e).__name__}: {e}"]}
        res["alias"] = t.get("alias")
        manifest["accounts"].append(res)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest
