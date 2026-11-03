"""로그·백업 관측: CloudTrail·GuardDuty·AWS Backup·S3 수명주기·RDS 백업을 Observation으로 바꾼다 (2.5.6, 2.9, 2.12).

스냅샷 파일 (계정 폴더마다)
  cloudtrail_trails.json   [DescribeTrails 항목 + Status(GetTrailStatus) + EventSelectors(GetEventSelectors)]
  guardduty.json           [{DetectorId, Status}]  (ListDetectors → GetDetector). 없으면 []
  backup_plans.json        [{BackupPlanName, Rules: [{RuleName, Lifecycle, CopyActions}]}]
  s3_buckets.json          crypto.py 와 같은 파일. 항목의 Lifecycle 규칙을 여기서 읽는다
  rds_db_instances.json    BackupRetentionPeriod 를 aws_db 관측에 붙인다 (network.py)

관측 kind
  aws_trail_status   계정 1개: 기록 중인 감사 로그가 있는지, IAM 변경이 남는지
  aws_trail          감사 로그(trail) 1개: 기록 여부, 무결성 검증, 저장 버킷
  aws_guardduty      계정 1개: 이상 행위 탐지 사용 여부
  aws_backup_account 계정 1개: 다른 리전 복사가 있는 백업 계획이 있는지
"""
from __future__ import annotations

import json
from typing import Any

from ..model import Observation

FILES = {"trail": "cloudtrail_trails.json", "guardduty": "guardduty.json", "backup": "backup_plans.json"}
NO_EXPIRY = 36500   # 수명주기 만료가 없으면 사실상 무기한 보관


def _load(f: dict[str, bytes], name: str) -> list | None:
    if name not in f:
        return None
    body = json.loads(f[name])
    return None if isinstance(body, dict) and "Error" in body else body


def bucket_retention(lifecycle: list | None) -> tuple[int, str]:
    """켜진 수명주기 규칙 중 가장 짧은 만료(일). 규칙이 없으면 무기한."""
    days = [r["Expiration"]["Days"] for r in (lifecycle or [])
            if r.get("Status") == "Enabled" and (r.get("Expiration") or {}).get("Days")]
    if not days:
        return NO_EXPIRY, "만료 없음(계속 보관)"
    d = min(days)
    return d, f"{d}일 후 삭제"


def _records_iam(t: dict) -> bool:
    """IAM 변경(전역 서비스 이벤트, 쓰기 관리 이벤트)이 이 trail에 남는가"""
    if not (t.get("Status") or {}).get("IsLogging"):
        return False
    if not (t.get("IsMultiRegionTrail") or t.get("IncludeGlobalServiceEvents")):
        return False
    adv = t.get("AdvancedEventSelectors")
    if adv is not None:       # 고급 이벤트 선택기: 관리 이벤트를 고르고 읽기 전용만으로 좁히지 않은 선택기가 있어야 함
        for a in adv:
            fs = {f["Field"]: f for f in a.get("FieldSelectors", [])}
            cat = fs.get("eventCategory", {}).get("Equals", [])
            ro = fs.get("readOnly", {}).get("Equals", [])
            if "Management" in cat and ro != ["true"]:
                return True
        return False
    sels = t.get("EventSelectors")
    if sels is None:          # 이벤트 선택기를 따로 두지 않으면 관리 이벤트 전체(읽기·쓰기)가 기본
        return True
    return any(s.get("IncludeManagementEvents", True) and s.get("ReadWriteType", "All") in ("All", "WriteOnly")
               for s in sels)


def logging_observations(aid: str, f: dict[str, bytes], sha: dict[str, str], src: dict, region: str) -> list[Observation]:
    trails, gd, plans = (_load(f, FILES[k]) for k in ("trail", "guardduty", "backup"))
    obs: list[Observation] = []

    def o(kind: str, oid: str, subject: str, values: dict, files: list[str], api: str) -> Observation:
        return Observation(obs_id=f"aws:{aid}:{oid}", axis="technical", kind=kind, subject=subject,
                           values={"account_id": aid, **values}, extractor=src["source"],
                           source={**src, "sha256": [sha[f"{aid}/{x}"] for x in files if f"{aid}/{x}" in sha],
                                   "api": api})

    if trails is not None:
        active = [t for t in trails if (t.get("Status") or {}).get("IsLogging")]
        iam = [t for t in trails if _records_iam(t)]
        obs.append(o("aws_trail_status", "trail_status", f"{aid}/cloudtrail", {
            "key": f"{aid}/cloudtrail", "trail_count": len(trails),
            "trails": ", ".join(t["Name"] for t in trails) or "없음",
            "has_active_trail": bool(active), "records_iam_changes": bool(iam),
            "stopped": ", ".join(t["Name"] for t in trails if t not in active) or "없음",
        }, [FILES["trail"]], "cloudtrail:DescribeTrails+GetTrailStatus+GetEventSelectors"))
        for t in trails:
            bucket = t.get("S3BucketName")
            obs.append(o("aws_trail", f"trail:{t['Name']}", f"{aid}/{t['Name']}", {
                "key": f"{aid}/{t['Name']}", "trail": t["Name"],
                "is_logging": bool((t.get("Status") or {}).get("IsLogging")),
                "multi_region": bool(t.get("IsMultiRegionTrail")),
                "global_events": bool(t.get("IncludeGlobalServiceEvents")),
                "validation": bool(t.get("LogFileValidationEnabled")),
                "bucket": bucket, "bucket_key": f"{aid}/{bucket}" if bucket else None,
            }, [FILES["trail"]], "cloudtrail:DescribeTrails+GetTrailStatus"))

    if gd is not None:
        on = [d for d in gd if d.get("Status") == "ENABLED"]
        obs.append(o("aws_guardduty", "guardduty", f"{aid}/guardduty", {
            "key": f"{aid}/guardduty", "enabled": bool(on), "detectors": len(gd),
        }, [FILES["guardduty"]], "guardduty:ListDetectors+GetDetector"))

    if plans is not None:
        copies = []
        for p in plans:
            for r in p.get("Rules", []):
                for c in r.get("CopyActions", []):
                    arn = c.get("DestinationBackupVaultArn", "")
                    dest = arn.split(":")[3] if arn.count(":") >= 5 else ""
                    if dest and dest != region:
                        copies.append(f"{p['BackupPlanName']}/{r['RuleName']} → {dest}")
        obs.append(o("aws_backup_account", "backup", f"{aid}/backup", {
            "key": f"{aid}/backup", "plans": ", ".join(p["BackupPlanName"] for p in plans) or "없음",
            "has_cross_region_copy": bool(copies), "copies": ", ".join(copies) or "없음",
        }, [FILES["backup"]], "backup:ListBackupPlans+GetBackupPlan"))
    return obs


def db_backup_fields(d: dict) -> dict[str, Any]:
    return {"backup_retention_days": d.get("BackupRetentionPeriod")}
