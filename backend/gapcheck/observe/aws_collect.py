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
