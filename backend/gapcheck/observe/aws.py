"""기술 관측: AWS 수집 스냅샷을 읽어 Observation으로 바꾼다. live 수집기도 같은 형식으로 쓴다.

스냅샷 형식 (계정별 폴더)
  manifest.json                       수집 시각·출처·계정 목록·상태
  <account>/iam_password_policy.json  GetAccountPasswordPolicy 응답 또는 {"Error": {"Code": "NoSuchEntity"}}
  <account>/credential_report.csv     GetCredentialReport 원문 CSV
  <account>/login_profiles.json       {user: {CreateDate, PasswordResetRequired}}
  <account>/cognito_user_pools.json   [DescribeUserPool.UserPool …]
  <account>/iam_authorization.json    GetAccountAuthorizationDetails 응답 (UserDetailList, GroupDetailList, Policies)
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..model import Observation

ISSUE_TOLERANCE = timedelta(minutes=1)

# 관리자(특수) 권한으로 보는 AWS 관리형 정책. IAMFullAccess는 스스로 권한을 올릴 수 있어 관리자와 같다.
ADMIN_MANAGED = {"arn:aws:iam::aws:policy/AdministratorAccess", "arn:aws:iam::aws:policy/IAMFullAccess"}
# 추측하기 쉬운 계정 이름 (사람을 특정할 수 없는 이름)
GENERIC_NAMES = {"admin", "administrator", "root", "test", "tester", "guest", "user", "dev", "developer",
                 "manager", "operator", "master", "shared", "temp", "sysadmin"}


def _statements(doc: Any) -> list[dict]:
    if isinstance(doc, str):
        from urllib.parse import unquote
        doc = json.loads(unquote(doc))
    st = (doc or {}).get("Statement", [])
    return st if isinstance(st, list) else [st]


def _grants_all(doc: Any) -> bool:
    """Allow, Action '*', Resource '*' 문장이 있으면 전체 권한"""
    for st in _statements(doc):
        if st.get("Effect") != "Allow":
            continue
        acts = st.get("Action", [])
        res = st.get("Resource", [])
        acts = [acts] if isinstance(acts, str) else acts
        res = [res] if isinstance(res, str) else res
        if any(a in ("*", "iam:*") for a in acts) and "*" in res:
            return True
    return False


def authorization_index(raw: bytes) -> dict[str, dict]:
    """사용자 이름 → {groups, direct_policies, admin, admin_via}"""
    body = json.loads(raw)
    if "Error" in body:
        return {}
    custom_admin = set()
    for p in body.get("Policies", []):
        ver = next((v for v in p.get("PolicyVersionList", []) if v.get("IsDefaultVersion")), None)
        if ver and _grants_all(ver.get("Document")):
            custom_admin.add(p["Arn"])

    def admin_reason(attached: list[dict], inline: list[dict], label: str) -> list[str]:
        out = [f"{label}: {a['PolicyName']}" for a in attached
               if a["PolicyArn"] in ADMIN_MANAGED or a["PolicyArn"] in custom_admin]
        out += [f"{label}: {i['PolicyName']}(인라인)" for i in inline if _grants_all(i.get("PolicyDocument"))]
        return out

    groups = {}
    for g in body.get("GroupDetailList", []):
        groups[g["GroupName"]] = admin_reason(g.get("AttachedManagedPolicies", []),
                                              g.get("GroupPolicyList", []), f"그룹 {g['GroupName']}")
    idx = {}
    for u in body.get("UserDetailList", []):
        direct = [a["PolicyName"] for a in u.get("AttachedManagedPolicies", [])] + \
                 [f"{i['PolicyName']}(인라인)" for i in u.get("UserPolicyList", [])]
        via = admin_reason(u.get("AttachedManagedPolicies", []), u.get("UserPolicyList", []), "직접")
        for g in u.get("GroupList", []):
            via += groups.get(g, [])
        idx[u["UserName"]] = {"groups": sorted(u.get("GroupList", [])), "direct_policies": sorted(direct),
                              "admin": bool(via), "admin_via": via,
                              "tags": {t["Key"]: t["Value"] for t in u.get("Tags", [])}}
    return idx


def parse_ts(v: str | None) -> datetime | None:
    if not v or v in ("N/A", "not_supported", "no_information"):
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def load_snapshot(snap_dir: Path) -> tuple[dict, dict[str, dict[str, bytes]]]:
    manifest = json.loads((snap_dir / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, dict[str, bytes]] = {}
    for acct in manifest["accounts"]:
        aid = acct["account_id"]
        d = snap_dir / aid
        files[aid] = {f.name: f.read_bytes() for f in sorted(d.iterdir())} if d.is_dir() else {}
    return manifest, files


def password_policy_obs(aid: str, raw: bytes, sha: str, src: dict) -> Observation:
    body = json.loads(raw)
    if "Error" in body:
        exists = body["Error"].get("Code") != "NoSuchEntity"
        values: dict[str, Any] = {"policy_exists": False if not exists else None}
        if exists:  # 다른 오류 (AccessDenied 등)
            return Observation(
                obs_id=f"aws:{aid}:password_policy", axis="technical", kind="aws_password_policy",
                subject=aid, values={}, extractor=src["source"], source={**src, "sha256": sha},
                quality="fail", quality_reasons=[f"수집 오류: {body['Error']}"])
    else:
        p = body["PasswordPolicy"]
        values = {
            "policy_exists": True,
            "MinimumPasswordLength": p.get("MinimumPasswordLength"),
            "RequireUppercaseCharacters": p.get("RequireUppercaseCharacters", False),
            "RequireLowercaseCharacters": p.get("RequireLowercaseCharacters", False),
            "RequireNumbers": p.get("RequireNumbers", False),
            "RequireSymbols": p.get("RequireSymbols", False),
            # 만료 미설정은 '만료 없음' — 비교 시 None은 실패로 다룬다
            "MaxPasswordAge": p.get("MaxPasswordAge") if p.get("ExpirePasswords", "MaxPasswordAge" in p) else None,
            "PasswordReusePrevention": p.get("PasswordReusePrevention"),
        }
    if values.get("policy_exists") is False:
        values.update({k: None for k in ("MinimumPasswordLength", "RequireUppercaseCharacters",
                                         "RequireLowercaseCharacters", "RequireNumbers", "RequireSymbols",
                                         "MaxPasswordAge", "PasswordReusePrevention")})
    return Observation(
        obs_id=f"aws:{aid}:password_policy", axis="technical", kind="aws_password_policy",
        subject=aid, values=values, extractor=src["source"], source={**src, "sha256": sha,
                                                                     "api": "iam:GetAccountPasswordPolicy"})


def _latest(*vals: str | None) -> str | None:
    ts = [t for t in (parse_ts(v) for v in vals) if t is not None]
    return max(ts).isoformat() if ts else None


def user_obs(aid: str, report: bytes, logins: dict, sha_r: str, sha_l: str, src: dict,
             authz: dict[str, dict] | None = None, sha_a: str = "") -> list[Observation]:
    out = []
    for row in csv.DictReader(io.StringIO(report.decode("utf-8"))):
        user = row["user"]
        if user == "<root_account>":
            # 루트는 IAM 사용자 모집단이 아니다. 별도 관측(aws_root)으로 남긴다
            keys = [row.get(f"access_key_{i}_active") == "true" for i in (1, 2)]
            out.append(Observation(
                obs_id=f"aws:{aid}:root", axis="technical", kind="aws_root", subject=f"{aid}/root",
                values={"account_id": aid, "mfa_active": row.get("mfa_active") == "true",
                        "access_key_active": any(keys), "password_last_used": row.get("password_last_used")},
                extractor=src["source"], source={**src, "sha256": sha_r, "api": "iam:GetCredentialReport"}))
            continue
        enabled = row["password_enabled"] == "true"
        lp = logins.get(user) or {}
        changed, used = parse_ts(row["password_last_changed"]), parse_ts(row["password_last_used"])
        issued = parse_ts(lp.get("CreateDate"))
        used_issued = None
        if enabled and issued and changed:
            used_issued = (abs(changed - issued) <= ISSUE_TOLERANCE and used is not None and used > changed
                           and lp.get("PasswordResetRequired") is False)
        keys_on = [row.get(f"access_key_{i}_active") == "true" for i in (1, 2)]
        last_activity = _latest(row["password_last_used"] if enabled else None,
                                *(row.get(f"access_key_{i}_last_used_date") for i in (1, 2) if keys_on[i - 1]))
        az = (authz or {}).get(user) if authz else None
        values_authz: dict[str, Any] = {k: None for k in ("groups", "direct_policies", "admin", "admin_via", "tags")}
        if authz:   # 권한 상세를 수집한 계정만. 수집하지 않았으면 None(판단 불가)
            az = az or {"groups": [], "direct_policies": [], "admin": False, "admin_via": [], "tags": {}}
            values_authz = dict(az)
        out.append(Observation(
            obs_id=f"aws:{aid}:user:{user}", axis="technical", kind="aws_user", subject=f"{aid}/{user}",
            values={
                "account_id": aid, "user": user, "key": f"{aid}/{user}", "password_enabled": enabled,
                "mfa_active": row.get("mfa_active") == "true",
                "access_key_active": any(keys_on),
                "active": enabled or any(keys_on),
                "user_creation_time": row.get("user_creation_time"),
                # 마지막 사용: 비밀번호·키 중 가장 최근. 한 번도 안 썼으면 만든 시각부터 센다
                "last_activity": last_activity or row.get("user_creation_time"),
                "never_used": last_activity is None,
                "generic_identifier": user.lower() in GENERIC_NAMES,
                **values_authz,
                "password_last_changed": row["password_last_changed"],
                "password_last_used": row["password_last_used"],
                "LoginProfileCreateDate": lp.get("CreateDate"),
                "PasswordResetRequired": lp.get("PasswordResetRequired"),
                "used_issued_password": used_issued,
            },
            extractor=src["source"],
            source={**src, "sha256": [x for x in (sha_r, sha_l, sha_a) if x],
                    "api": "iam:GetCredentialReport+iam:GetLoginProfile"
                           + ("+iam:GetAccountAuthorizationDetails" if authz else "")},
        ))
    return out


def cognito_obs(aid: str, raw: bytes, sha: str, src: dict) -> list[Observation]:
    out = []
    for pool in json.loads(raw):
        pp = pool.get("Policies", {}).get("PasswordPolicy", {})
        out.append(Observation(
            obs_id=f"aws:{aid}:cognito:{pool['Id']}", axis="technical", kind="cognito_pool",
            subject=f"{aid}/{pool['Id']}",
            values={"account_id": aid, "pool_name": pool.get("Name"), "MinimumLength": pp.get("MinimumLength"),
                    "RequireUppercase": pp.get("RequireUppercase"), "RequireLowercase": pp.get("RequireLowercase"),
                    "RequireNumbers": pp.get("RequireNumbers"), "RequireSymbols": pp.get("RequireSymbols")},
            extractor=src["source"], source={**src, "sha256": sha, "api": "cognito-idp:DescribeUserPool"},
        ))
    return out


def snapshot_observations(manifest: dict, files: dict[str, dict[str, bytes]], sha: dict[str, str]) -> list[Observation]:
    """sha: '<account>/<file>' → sha256 (원본 등록 단계에서 계산된 값)"""
    obs: list[Observation] = []
    for acct in manifest["accounts"]:
        aid = acct["account_id"]
        if acct.get("status") != "ok":
            continue
        f = files.get(aid, {})
        src = {"source": manifest.get("source", "unknown"), "snapshot_id": manifest.get("snapshot_id"),
               "collected_at": manifest.get("collected_at"), "account_id": aid}
        if "iam_password_policy.json" in f:
            obs.append(password_policy_obs(aid, f["iam_password_policy.json"],
                                           sha[f"{aid}/iam_password_policy.json"], src))
        if "credential_report.csv" in f:
            logins = json.loads(f.get("login_profiles.json", b"{}"))
            authz = authorization_index(f["iam_authorization.json"]) if "iam_authorization.json" in f else None
            obs += user_obs(aid, f["credential_report.csv"], logins, sha[f"{aid}/credential_report.csv"],
                            sha.get(f"{aid}/login_profiles.json", ""), src,
                            authz, sha.get(f"{aid}/iam_authorization.json", ""))
        if "cognito_user_pools.json" in f:
            obs += cognito_obs(aid, f["cognito_user_pools.json"], sha[f"{aid}/cognito_user_pools.json"], src)
        from .network import FILES as NET_FILES, network_observations
        if any(n in f for n in NET_FILES.values()):
            obs += network_observations(aid, f, sha, src)
        from .crypto import FILES as CRYPTO_FILES, crypto_observations
        if any(n in f for n in CRYPTO_FILES.values()) or "rds_db_instances.json" in f:
            obs += crypto_observations(aid, f, sha, src)
    return obs
