"""기술 관측: AWS 수집 스냅샷을 읽어 Observation으로 바꾼다. live 수집기도 같은 형식으로 쓴다.

스냅샷 형식 (계정별 폴더)
  manifest.json                       수집 시각·출처·계정 목록·상태
  <account>/iam_password_policy.json  GetAccountPasswordPolicy 응답 또는 {"Error": {"Code": "NoSuchEntity"}}
  <account>/credential_report.csv     GetCredentialReport 원문 CSV
  <account>/login_profiles.json       {user: {CreateDate, PasswordResetRequired}}
  <account>/cognito_user_pools.json   [DescribeUserPool.UserPool …]
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


def user_obs(aid: str, report: bytes, logins: dict, sha_r: str, sha_l: str, src: dict) -> list[Observation]:
    out = []
    for row in csv.DictReader(io.StringIO(report.decode("utf-8"))):
        user = row["user"]
        if user == "<root_account>":
            continue  # 루트는 IAM 사용자 모집단이 아니다 (별도 항목에서 다룸)
        enabled = row["password_enabled"] == "true"
        lp = logins.get(user) or {}
        changed, used = parse_ts(row["password_last_changed"]), parse_ts(row["password_last_used"])
        issued = parse_ts(lp.get("CreateDate"))
        used_issued = None
        if enabled and issued and changed:
            used_issued = (abs(changed - issued) <= ISSUE_TOLERANCE and used is not None and used > changed
                           and lp.get("PasswordResetRequired") is False)
        out.append(Observation(
            obs_id=f"aws:{aid}:user:{user}", axis="technical", kind="aws_user", subject=f"{aid}/{user}",
            values={
                "account_id": aid, "user": user, "password_enabled": enabled,
                "password_last_changed": row["password_last_changed"],
                "password_last_used": row["password_last_used"],
                "LoginProfileCreateDate": lp.get("CreateDate"),
                "PasswordResetRequired": lp.get("PasswordResetRequired"),
                "used_issued_password": used_issued,
            },
            extractor=src["source"],
            source={**src, "sha256": [sha_r, sha_l], "api": "iam:GetCredentialReport+iam:GetLoginProfile"},
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
            obs += user_obs(aid, f["credential_report.csv"], logins, sha[f"{aid}/credential_report.csv"],
                            sha.get(f"{aid}/login_profiles.json", ""), src)
        if "cognito_user_pools.json" in f:
            obs += cognito_obs(aid, f["cognito_user_pools.json"], sha[f"{aid}/cognito_user_pools.json"], src)
    return obs
