"""c-corp-eval 시나리오(C사, 가상 HR·급여 SaaS)를 처음부터 만든다. 다시 실행해도 같은 내용이 나온다.

    python scripts/build_c_corp_eval.py

모든 회사·인물·계정 정보는 가상이다 (계정 ID 8010000000xx, 도메인 .example). 사람 이름은 마스킹해서만 쓴다.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import shutil
import sys
from pathlib import Path

import docx
import yaml
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "c-corp-eval"
SNAP = SC / "aws-snapshot"
DOCS = SC / "docs"
EV = SC / "evidence"

PROD, DEV, SEC, SBX = "801000000001", "801000000002", "801000000003", "801000000009"
ALIAS = {PROD: "c-prod", DEV: "c-dev", SEC: "c-sec", SBX: "c-sandbox"}
REGION = "ap-northeast-2"
FIXED = dt.datetime(2026, 11, 2, 9, 0, 0)
NA = "N/A"

# ───────────────────────────── IAM ─────────────────────────────

HEADER = ["user", "arn", "user_creation_time", "password_enabled", "password_last_used", "password_last_changed",
          "password_next_rotation", "mfa_active", "access_key_1_active", "access_key_1_last_rotated",
          "access_key_1_last_used_date", "access_key_1_last_used_region", "access_key_1_last_used_service",
          "access_key_2_active", "access_key_2_last_rotated", "access_key_2_last_used_date",
          "access_key_2_last_used_region", "access_key_2_last_used_service", "cert_1_active",
          "cert_1_last_rotated", "cert_2_active", "cert_2_last_rotated"]

AWSP = "arn:aws:iam::aws:policy/"
ADMIN, IAMFULL, POWER, READ, AUDIT = (AWSP + "AdministratorAccess", AWSP + "IAMFullAccess",
                                      AWSP + "PowerUserAccess", AWSP + "ReadOnlyAccess", AWSP + "SecurityAudit")


def U(name, created, console=True, used=None, changed=None, mfa=True, groups=(), lp=None, reset=False,
      key=False, key_used=None, key_rotated=None, key2=False, inline=None, direct=()):
    return dict(name=name, created=created, console=console, used=used, changed=changed, mfa=mfa,
                groups=list(groups), lp=lp, reset=reset, key=key, key_used=key_used,
                key_rotated=key_rotated or created, inline=inline, direct=list(direct))


T = "T{}+00:00".format
USERS: dict[str, list[dict]] = {
    PROD: [
        U("park.sj", "2024-03-04" + T("01:10:00"), used="2026-11-01" + T("08:40:00"),
          changed="2026-08-20" + T("02:15:00"), groups=["SecurityAdmins"], lp="2024-03-04" + T("01:10:04")),
        U("kim.dh", "2025-01-13" + T("00:30:00"), used="2026-10-31" + T("11:02:00"),
          changed="2026-07-01" + T("05:20:00"), groups=["PlatformAdmins"], lp="2025-01-13" + T("00:30:03")),
        U("choi.mr", "2026-03-09" + T("02:00:00"), used="2026-10-29" + T("06:44:00"),
          changed="2026-09-01" + T("07:12:00"), mfa=False, groups=["HROps"], lp="2026-03-09" + T("02:00:02")),
        U("yoon.hj", "2026-10-20" + T("01:00:00"), used="2026-10-30" + T("04:31:00"),
          changed="2026-10-20" + T("01:00:02"), groups=["Developers"], lp="2026-10-20" + T("01:00:02")),
        U("lee.jw", "2026-09-01" + T("00:50:00"), used="2026-10-30" + T("09:10:00"),
          changed="2026-09-01" + T("03:05:00"), groups=["Developers"], lp="2026-09-01" + T("00:50:04")),
        U("jhkim", "2025-05-19" + T("01:00:00"), used="2026-10-07" + T("09:55:00"),
          changed="2026-06-10" + T("01:40:00"), groups=["HROps"], lp="2025-05-19" + T("01:00:03")),
        U("lim.ga", "2025-08-04" + T("01:00:00"), used="2026-09-20" + T("02:30:00"),
          changed="2026-06-30" + T("06:00:00"), groups=["HROps"], lp="2025-08-04" + T("01:00:02")),
        U("ops-shared", "2025-02-03" + T("03:00:00"), used="2026-11-02" + T("00:10:00"),
          changed="2026-09-15" + T("04:00:00"), groups=["Operators"], lp="2025-02-03" + T("03:00:05")),
        U("svc-report-export", "2025-04-01" + T("00:00:00"), console=False, mfa=False, key=True,
          key_used="2026-07-01" + T("15:00:00"), groups=["ReportJobs"]),
        U("svc-payroll-batch", "2024-11-01" + T("00:00:00"), console=False, mfa=False, key=True,
          key_used="2026-11-01" + T("18:20:00"), key_rotated="2026-05-02" + T("00:00:00"), groups=["PayrollJobs"]),
        U("vendor-hrcore", "2026-06-01" + T("01:00:00"), used="2026-09-28" + T("07:45:00"),
          changed="2026-07-15" + T("02:00:00"), groups=["VendorSupport"], lp="2026-06-01" + T("01:00:03")),
        U("sysadmin-hong", "2025-09-22" + T("01:00:00"), used="2026-10-30" + T("23:05:00"),
          changed="2026-05-10" + T("08:00:00"), groups=["Operators"], lp="2025-09-22" + T("01:00:02")),
    ],
    DEV: [
        U("dev-cho", "2025-03-17" + T("01:00:00"), used="2026-11-01" + T("10:20:00"),
          changed="2026-08-01" + T("03:00:00"), groups=["Developers"], lp="2025-03-17" + T("01:00:04"),
          inline={"PolicyName": "EmergencyFullAccess", "PolicyDocument": {
              "Version": "2012-10-17",
              "Statement": [{"Sid": "Hotfix", "Effect": "Allow", "Action": "*", "Resource": "*"}]}}),
        U("sypark", "2024-09-02" + T("01:00:00"), console=False, mfa=True, key=True,
          key_used="2026-09-17" + T("08:10:00"), groups=["Developers"]),
        U("qa-shared", "2025-11-03" + T("01:00:00"), used="2026-10-31" + T("05:00:00"),
          changed="2026-10-01" + T("02:00:00"), groups=["QA"], lp="2025-11-03" + T("01:00:03")),
        U("batch-shared", "2025-06-02" + T("00:00:00"), console=False, mfa=False, key=True,
          key_used="2026-10-30" + T("17:00:00"), groups=["BatchJobs"]),
        U("vendor-qa", "2026-07-01" + T("01:00:00"), console=False, mfa=False, groups=["VendorSupport"]),
        U("jung.ws", "2026-02-02" + T("01:00:00"), used="2026-10-30" + T("08:00:00"),
          changed="2026-09-20" + T("01:30:00"), groups=["Developers"], lp="2026-02-02" + T("01:00:02")),
        U("hwang.yr", "2025-12-01" + T("01:00:00"), used="2026-10-29" + T("07:50:00"),
          changed="2026-07-10" + T("04:00:00"), groups=["QA"], lp="2025-12-01" + T("01:00:03")),
        U("oh.ks", "2024-10-07" + T("01:00:00"), console=False, mfa=False, groups=["Developers"]),
    ],
    SEC: [
        U("park.sj", "2024-03-05" + T("01:00:00"), used="2026-10-28" + T("02:00:00"),
          changed="2026-09-01" + T("01:00:00"), groups=["SecurityAdmins"], lp="2024-03-05" + T("01:00:02")),
        U("sec.kang", "2025-07-07" + T("01:00:00"), used="2026-11-02" + T("01:30:00"),
          changed="2026-03-15" + T("02:00:00"), groups=["SecOps"], lp="2025-07-07" + T("01:00:03")),
        U("vendor-soc", "2026-10-01" + T("01:00:00"), used="2026-10-27" + T("06:00:00"),
          changed="2026-10-01" + T("05:00:00"), groups=["VendorSupport"], lp="2026-10-01" + T("01:00:03")),
        U("svc-siem-ingest", "2025-07-08" + T("00:00:00"), console=False, mfa=False, key=True,
          key_used="2026-11-02" + T("00:00:00"), key_rotated="2026-07-01" + T("00:00:00"), groups=["SiemIngest"]),
    ],
    SBX: [
        U("test", "2026-08-11" + T("01:00:00"), used="2026-10-12" + T("03:00:00"),
          changed="2026-08-11" + T("01:00:01"), mfa=False, lp="2026-08-11" + T("01:00:01"), direct=[ADMIN]),
    ],
}
ROOT_MFA = {PROD: True, DEV: True, SEC: True, SBX: False}
ROOT_USED = {PROD: "2025-12-02" + T("04:00:00"), DEV: NA, SEC: NA, SBX: "2026-08-11" + T("00:40:00")}

GROUPS = {
    "SecurityAdmins": [ADMIN], "PlatformAdmins": [ADMIN], "HROps": ["custom:HrOpsConsole"],
    "Developers": [POWER], "Operators": [READ], "ReportJobs": ["custom:ReportExport"],
    "PayrollJobs": ["custom:PayrollBatch"], "VendorSupport": [READ], "QA": [READ],
    "BatchJobs": ["custom:DevBatch"], "SecOps": [IAMFULL, AUDIT], "SiemIngest": ["custom:SiemIngest"],
}
CUSTOM = {
    "HrOpsConsole": [{"Effect": "Allow", "Action": ["rds:Describe*", "s3:GetObject", "s3:ListBucket"],
                      "Resource": "*"}],
    "ReportExport": [{"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"],
                      "Resource": "arn:aws:s3:::c-prod-payslip-pdf/*"}],
    "PayrollBatch": [{"Effect": "Allow", "Action": "s3:*",
                      "Resource": ["arn:aws:s3:::c-prod-tenant-uploads", "arn:aws:s3:::c-prod-tenant-uploads/*"]},
                     {"Effect": "Allow", "Action": ["kms:Decrypt", "kms:GenerateDataKey"], "Resource": "*"}],
    "DevBatch": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                  "Resource": "arn:aws:s3:::c-dev-test-fixtures/*"}],
    "SiemIngest": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket", "sqs:ReceiveMessage",
                                                  "sqs:DeleteMessage"], "Resource": "*"}],
}

PW_POLICY = {
    PROD: {"MinimumPasswordLength": 12, "RequireSymbols": True, "RequireNumbers": True,
           "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True,
           "AllowUsersToChangePassword": True, "ExpirePasswords": True, "MaxPasswordAge": 180,
           "PasswordReusePrevention": 5, "HardExpiry": False},
    DEV: {"MinimumPasswordLength": 10, "RequireSymbols": False, "RequireNumbers": True,
          "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True,
          "AllowUsersToChangePassword": True, "ExpirePasswords": True, "MaxPasswordAge": 180,
          "PasswordReusePrevention": 5, "HardExpiry": False},
    SEC: {"MinimumPasswordLength": 12, "RequireSymbols": False, "RequireNumbers": True,
          "RequireUppercaseCharacters": False, "RequireLowercaseCharacters": True,
          "AllowUsersToChangePassword": True, "ExpirePasswords": False, "PasswordReusePrevention": 5},
    SBX: None,
}


def credential_report(acct: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerow(["<root_account>", f"arn:aws:iam::{acct}:root", "2024-02-26T00:00:00+00:00", "not_supported",
                ROOT_USED[acct], "not_supported", NA, str(ROOT_MFA[acct]).lower(), "false", NA, NA, NA, NA,
                "false", NA, NA, NA, NA, "false", NA, "false", NA])
    for u in sorted(USERS[acct], key=lambda x: x["name"]):
        c, k = u["console"], u["key"]
        nxt = NA
        if c and PW_POLICY.get(acct) and PW_POLICY[acct].get("ExpirePasswords"):
            nxt = (dt.datetime.fromisoformat(u["changed"]) + dt.timedelta(days=PW_POLICY[acct]["MaxPasswordAge"])
                   ).isoformat()
        w.writerow([u["name"], f"arn:aws:iam::{acct}:user/{u['name']}", u["created"],
                    str(c).lower(), (u["used"] or "no_information") if c else NA,
                    u["changed"] if c else NA, nxt, str(u["mfa"]).lower(),
                    str(k).lower(), u["key_rotated"] if k else NA, u["key_used"] if k else NA,
                    REGION if k else NA, ("s3" if k else NA),
                    "false", NA, NA, NA, NA, "false", NA, "false", NA])
    return buf.getvalue()


def login_profiles(acct: str) -> dict:
    return {u["name"]: {"UserName": u["name"], "CreateDate": u["lp"], "PasswordResetRequired": u["reset"]}
            for u in sorted(USERS[acct], key=lambda x: x["name"]) if u["console"]}


def authorization(acct: str) -> dict:
    used = sorted({g for u in USERS[acct] for g in u["groups"]})

    def pol(ref: str) -> dict:
        if ref.startswith("custom:"):
            n = ref.split(":", 1)[1]
            return {"PolicyName": n, "PolicyArn": f"arn:aws:iam::{acct}:policy/{n}"}
        return {"PolicyName": ref.rsplit("/", 1)[1], "PolicyArn": ref}

    users = []
    for i, u in enumerate(sorted(USERS[acct], key=lambda x: x["name"])):
        users.append({
            "UserName": u["name"], "UserId": f"AIDA{acct[-4:]}{i:02d}{u['name'].upper().replace('-', '').replace('.', '')[:10]}",
            "Arn": f"arn:aws:iam::{acct}:user/{u['name']}", "Path": "/", "CreateDate": u["created"],
            "GroupList": u["groups"], "AttachedManagedPolicies": [pol(p) for p in u["direct"]],
            "UserPolicyList": [u["inline"]] if u["inline"] else [], "Tags": [],
        })
    groups = [{"GroupName": g, "GroupId": f"AGPA{acct[-4:]}{g.upper()[:12]}",
               "Arn": f"arn:aws:iam::{acct}:group/{g}", "Path": "/",
               "AttachedManagedPolicies": [pol(p) for p in GROUPS[g]], "GroupPolicyList": []} for g in used]
    names = sorted({p.split(":", 1)[1] for g in used for p in GROUPS[g] if p.startswith("custom:")})
    custom = [{"PolicyName": n, "PolicyId": f"ANPA{acct[-4:]}{n.upper()[:12]}",
               "Arn": f"arn:aws:iam::{acct}:policy/{n}", "Path": "/", "DefaultVersionId": "v2",
               "AttachmentCount": 1, "IsAttachable": True,
               "PolicyVersionList": [{"VersionId": "v2", "IsDefaultVersion": True,
                                      "Document": {"Version": "2012-10-17", "Statement": CUSTOM[n]}}]}
              for n in names]
    return {"UserDetailList": users, "GroupDetailList": groups, "RoleDetailList": [], "Policies": custom}


COGNITO = {
    PROD: [
        {"Id": "ap-northeast-2_CpEmp0001", "Name": "peoplecloud-employee-login", "Status": "Enabled",
         "Policies": {"PasswordPolicy": {"MinimumLength": 8, "RequireUppercase": False, "RequireLowercase": True,
                                         "RequireNumbers": True, "RequireSymbols": True,
                                         "TemporaryPasswordValidityDays": 3}},
         "MfaConfiguration": "OPTIONAL", "EstimatedNumberOfUsers": 41230},
        {"Id": "ap-northeast-2_CpAdm0001", "Name": "peoplecloud-tenant-admin", "Status": "Enabled",
         "Policies": {"PasswordPolicy": {"MinimumLength": 12, "RequireUppercase": True, "RequireLowercase": True,
                                         "RequireNumbers": True, "RequireSymbols": True,
                                         "TemporaryPasswordValidityDays": 1}},
         "MfaConfiguration": "ON", "EstimatedNumberOfUsers": 1184},
    ],
    DEV: [], SEC: [], SBX: [],
}

# ───────────────────────────── 네트워크 ─────────────────────────────


def perm(proto, lo=None, hi=None, cidrs=(), groups=(), desc=""):
    p = {"IpProtocol": proto}
    if proto != "-1":
        p["FromPort"], p["ToPort"] = lo, (hi if hi is not None else lo)
    p["IpRanges"] = [{"CidrIp": c, **({"Description": desc} if desc else {})} for c in cidrs if ":" not in c]
    p["Ipv6Ranges"] = [{"CidrIpv6": c} for c in cidrs if ":" in c]
    p["UserIdGroupPairs"] = [{"GroupId": g, **({"Description": desc} if desc else {})} for g in groups]
    p["PrefixListIds"] = []
    return p


EG_ALL = [perm("-1", cidrs=["0.0.0.0/0"])]


def sg(gid, name, vpc, ingress, egress=None, desc="", tags=None):
    return {"GroupId": gid, "GroupName": name, "VpcId": vpc, "Description": desc or name, "OwnerId": "",
            "IpPermissions": ingress, "IpPermissionsEgress": EG_ALL if egress is None else egress,
            "Tags": [{"Key": k, "Value": v} for k, v in (tags or {}).items()]}


def subnet(sid, vpc, cidr, name, az, public=False):
    return {"SubnetId": sid, "VpcId": vpc, "CidrBlock": cidr, "AvailabilityZone": az,
            "MapPublicIpOnLaunch": public, "State": "available", "Tags": [{"Key": "Name", "Value": name}]}


def rt(rid, vpc, vpc_cidr, subnets, extra=(), main=False, name=""):
    routes = [{"DestinationCidrBlock": vpc_cidr, "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"}]
    for dest, target in extra:
        key = ("NatGatewayId" if target.startswith("nat-") else
               "VpcPeeringConnectionId" if target.startswith("pcx-") else
               "TransitGatewayId" if target.startswith("tgw-") else "GatewayId")
        routes.append({"DestinationCidrBlock": dest, key: target, "State": "active", "Origin": "CreateRoute"})
    assoc = [{"RouteTableAssociationId": f"rtbassoc-{rid[4:]}{i}", "RouteTableId": rid, "SubnetId": s, "Main": False}
             for i, s in enumerate(subnets)]
    if main:
        assoc.append({"RouteTableAssociationId": f"rtbassoc-{rid[4:]}m", "RouteTableId": rid, "Main": True})
    return {"RouteTableId": rid, "VpcId": vpc, "Routes": routes, "Associations": assoc,
            "Tags": [{"Key": "Name", "Value": name}] if name else []}


def karn(acct, kid):
    return f"arn:aws:kms:{REGION}:{acct}:key/{kid}"


K = {
    "prod-payroll": (PROD, "5d0f3a1c-7b2e-4c19-9e61-0c1000000a01"),
    "prod-tenant": (PROD, "5d0f3a1c-7b2e-4c19-9e61-0c1000000a02"),
    "prod-legacy-2024": (PROD, "5d0f3a1c-7b2e-4c19-9e61-0c1000000a03"),
    "aws/ebs@prod": (PROD, "5d0f3a1c-7b2e-4c19-9e61-0c10000000e5"),
    "aws/rds@prod": (PROD, "5d0f3a1c-7b2e-4c19-9e61-0c10000000d5"),
    "dev-app": (DEV, "8a41c2be-1f0d-4e7a-b3c5-0c2000000b01"),
    "aws/ebs@dev": (DEV, "8a41c2be-1f0d-4e7a-b3c5-0c20000000e5"),
    "sec-siem": (SEC, "e27b9d04-3c6a-4f18-8d2e-0c3000000c01"),
    "central-audit-logs": (SEC, "e27b9d04-3c6a-4f18-8d2e-0c3000000c02"),
    "soc-forensics": (SEC, "e27b9d04-3c6a-4f18-8d2e-0c3000000c03"),
    "aws/ebs@sec": (SEC, "e27b9d04-3c6a-4f18-8d2e-0c30000000e5"),
}


def kid(alias):
    return K[alias][1]


def karn_of(alias):
    a, k = K[alias]
    return karn(a, k)


def rds(name, engine, public, sgs, subnets, enc_key, retention, cls="db.r6g.large"):
    d = {"DBInstanceIdentifier": name, "DBInstanceClass": cls, "Engine": engine, "DBInstanceStatus": "available",
         "PubliclyAccessible": public, "StorageEncrypted": enc_key is not None,
         "VpcSecurityGroups": [{"VpcSecurityGroupId": g, "Status": "active"} for g in sgs],
         "DBSubnetGroup": {"DBSubnetGroupName": f"{name}-subnets", "SubnetGroupStatus": "Complete",
                           "Subnets": [{"SubnetIdentifier": s, "SubnetStatus": "Active"} for s in subnets]},
         "BackupRetentionPeriod": retention, "MultiAZ": retention >= 7}
    if enc_key:
        d["KmsKeyId"] = enc_key
    return d


def net_prod():
    vpc, cidr = "vpc-0c1prod000000001", "10.10.0.0/16"
    s = {"pub_a": "subnet-0c1pub00000000a", "pub_c": "subnet-0c1pub00000000c", "app_a": "subnet-0c1app00000000a",
         "app_c": "subnet-0c1app00000000c", "db_a": "subnet-0c1db000000000a", "db_c": "subnet-0c1db000000000c"}
    return {
        "sg": [
            sg("sg-0c1default000001", "default", vpc, [], [], desc="default VPC security group"),
            sg("sg-0c1hralb00000001", "prod-hr-alb", vpc, [
                perm("tcp", 443, cidrs=["0.0.0.0/0", "::/0"]), perm("tcp", 80, cidrs=["0.0.0.0/0", "::/0"])]),
            sg("sg-0c1apialb0000001", "prod-api-alb", vpc, [perm("tcp", 443, cidrs=["0.0.0.0/0", "::/0"])]),
            sg("sg-0c1intalb0000001", "prod-internal-admin-alb", vpc, [
                perm("tcp", 8080, cidrs=["10.250.0.0/24"], desc="admin vpn"),
                perm("tcp", 443, cidrs=["10.250.0.0/24"], desc="admin vpn")]),
            sg("sg-0c1app000000001", "prod-app", vpc, [
                perm("tcp", 8080, groups=["sg-0c1hralb00000001", "sg-0c1apialb0000001", "sg-0c1intalb0000001"]),
                perm("tcp", 22, groups=["sg-0c1bastion000001"], desc="bastion")]),
            sg("sg-0c1bastion000001", "prod-bastion", vpc, [
                perm("tcp", 22, cidrs=["192.0.2.40/32"], desc="IT ops desk")]),
            sg("sg-0c1db0000000001", "prod-db", vpc, [
                perm("tcp", 5432, groups=["sg-0c1app000000001"], desc="app tier"),
                perm("tcp", 5432, cidrs=["10.250.0.0/24"], desc="DBA VPN")]),
            sg("sg-0c1cache00000001", "prod-cache", vpc, [perm("tcp", 6379, cidrs=[cidr])],
               tags={"Tier": "data", "Role": "database"}),
        ],
        "subnet": [
            subnet(s["pub_a"], vpc, "10.10.0.0/24", "prod-public-a", "ap-northeast-2a", True),
            subnet(s["pub_c"], vpc, "10.10.1.0/24", "prod-public-c", "ap-northeast-2c", True),
            subnet(s["app_a"], vpc, "10.10.10.0/24", "prod-app-a", "ap-northeast-2a"),
            subnet(s["app_c"], vpc, "10.10.11.0/24", "prod-app-c", "ap-northeast-2c"),
            subnet(s["db_a"], vpc, "10.10.20.0/24", "prod-data-a", "ap-northeast-2a"),
            subnet(s["db_c"], vpc, "10.10.21.0/24", "prod-data-c", "ap-northeast-2c"),
        ],
        "rt": [
            rt("rtb-0c1main0000001", vpc, cidr, [], main=True, name="prod-main"),
            rt("rtb-0c1public00001", vpc, cidr, [s["pub_a"], s["pub_c"]], [("0.0.0.0/0", "igw-0c1prod00000001")],
               name="prod-public"),
            rt("rtb-0c1app0000001", vpc, cidr, [s["app_a"], s["app_c"]], [("0.0.0.0/0", "nat-0c1prod000000001a")],
               name="prod-app"),
            rt("rtb-0c1data000001", vpc, cidr, [s["db_a"], s["db_c"]], [("10.250.0.0/24", "pcx-0c1toc3sec000001")],
               name="prod-data"),
        ],
        "rds": [
            rds("prod-payroll", "postgres", False, ["sg-0c1db0000000001"], [s["db_a"], s["db_c"]],
                karn_of("prod-payroll"), 7),
            rds("prod-tenant-core", "postgres", False, ["sg-0c1db0000000001"], [s["db_a"], s["db_c"]],
                karn_of("prod-tenant"), 35),
        ],
    }


def net_dev():
    vpc, cidr = "vpc-0c2dev0000000001", "10.20.0.0/16"
    s = {"pub_a": "subnet-0c2pub00000000a", "pub_c": "subnet-0c2pub00000000c", "app_a": "subnet-0c2app00000000a",
         "db_a": "subnet-0c2db000000000a", "db_c": "subnet-0c2db000000000c"}
    return {
        "sg": [
            sg("sg-0c2default000001", "default", vpc, [], [], desc="default VPC security group"),
            sg("sg-0c2alb000000001", "dev-alb", vpc, [
                perm("tcp", 443, cidrs=["0.0.0.0/0"]), perm("tcp", 80, cidrs=["0.0.0.0/0"])]),
            sg("sg-0c2app000000001", "dev-default-app", vpc, [
                perm("tcp", 8080, groups=["sg-0c2alb000000001"]),
                perm("tcp", 22, cidrs=["10.250.0.0/24"], desc="admin vpn")]),
            sg("sg-0c2legacy000001", "dev-legacy-batch", vpc, [
                perm("tcp", 23, cidrs=[cidr], desc="legacy payroll converter console")]),
            sg("sg-0c2stgdb0000001", "stg-db", vpc, [perm("tcp", 5432, groups=["sg-0c2app000000001"])]),
            sg("sg-0c2clonedb00001", "dev-clone-db", vpc, [perm("tcp", 5432, groups=["sg-0c2app000000001"])]),
        ],
        "subnet": [
            subnet(s["pub_a"], vpc, "10.20.0.0/24", "dev-public-a", "ap-northeast-2a", True),
            subnet(s["pub_c"], vpc, "10.20.1.0/24", "dev-public-c", "ap-northeast-2c", True),
            subnet(s["app_a"], vpc, "10.20.10.0/24", "dev-app-a", "ap-northeast-2a"),
            subnet(s["db_a"], vpc, "10.20.20.0/24", "dev-data-a", "ap-northeast-2a"),
            subnet(s["db_c"], vpc, "10.20.21.0/24", "dev-data-c", "ap-northeast-2c"),
        ],
        "rt": [
            rt("rtb-0c2main0000001", vpc, cidr, [s["db_a"], s["db_c"]], main=True, name="dev-main"),
            rt("rtb-0c2public00001", vpc, cidr, [s["pub_a"], s["pub_c"]], [("0.0.0.0/0", "igw-0c2dev000000001")],
               name="dev-public"),
            rt("rtb-0c2app0000001", vpc, cidr, [s["app_a"]], [("0.0.0.0/0", "nat-0c2dev0000000001a")], name="dev-app"),
        ],
        "rds": [
            rds("stg-payroll", "postgres", True, ["sg-0c2stgdb0000001"], [s["pub_a"], s["pub_c"]],
                karn_of("prod-payroll"), 1, cls="db.t4g.medium"),
            rds("dev-payroll-clone", "postgres", False, ["sg-0c2clonedb00001"], [s["db_a"], s["db_c"]],
                None, 0, cls="db.t4g.medium"),
        ],
    }


def net_sec():
    vpc, cidr = "vpc-0c3sec0000000001", "10.30.0.0/16"
    s = {"pub_a": "subnet-0c3pub00000000a", "tools_a": "subnet-0c3tools000000a"}
    return {
        "sg": [
            sg("sg-0c3default000001", "default", vpc, [], [], desc="default VPC security group"),
            sg("sg-0c3soctools00001", "soc-tools", vpc, [
                perm("tcp", 22, cidrs=["192.0.2.32/27"], desc="IT mgmt net"),
                perm("tcp", 3389, cidrs=["192.0.2.0/24"], desc="HQ")]),
            sg("sg-0c3siem00000001", "soc-siem", vpc, [perm("tcp", 443, cidrs=["10.0.0.0/8"])]),
        ],
        "subnet": [
            subnet(s["pub_a"], vpc, "10.30.0.0/24", "sec-public-a", "ap-northeast-2a", True),
            subnet(s["tools_a"], vpc, "10.30.10.0/24", "sec-tools-a", "ap-northeast-2a"),
        ],
        "rt": [
            rt("rtb-0c3main0000001", vpc, cidr, [s["tools_a"]], [("0.0.0.0/0", "nat-0c3sec0000000001a"),
                                                                 ("10.10.0.0/16", "pcx-0c1toc3sec000001")],
               main=True, name="sec-main"),
            rt("rtb-0c3public00001", vpc, cidr, [s["pub_a"]], [("0.0.0.0/0", "igw-0c3sec000000001")], name="sec-public"),
        ],
        "rds": [],
    }


def net_sbx():
    vpc, cidr = "vpc-0c9sbx0000000001", "10.90.0.0/16"
    return {
        "sg": [
            sg("sg-0c9default000001", "default", vpc, [perm("-1", groups=["sg-0c9default000001"])]),
            sg("sg-0c9open00000001", "poc-open", vpc, [perm("-1", cidrs=["0.0.0.0/0"]),
                                                     perm("tcp", 21, cidrs=["0.0.0.0/0"])]),
        ],
        "subnet": [subnet("subnet-0c9pub00000000a", vpc, "10.90.0.0/24", "sbx-public-a", "ap-northeast-2a", True)],
        "rt": [rt("rtb-0c9main0000001", vpc, cidr, ["subnet-0c9pub00000000a"], [("0.0.0.0/0", "igw-0c9sbx000000001")],
                  main=True)],
        "rds": [rds("poc-ai-resume", "mysql", True, ["sg-0c9open00000001"], ["subnet-0c9pub00000000a"], None, 0,
                    cls="db.t4g.micro")],
    }


NET = {PROD: net_prod, DEV: net_dev, SEC: net_sec, SBX: net_sbx}

# ───────────────────────────── 암호화 ─────────────────────────────


def kms(acct):
    def k(alias, manager, rotation, desc, state="Enabled"):
        a, i = K[alias]
        name = "alias/" + alias.split("@")[0]
        return {"KeyId": i, "Arn": karn(a, i), "KeyManager": manager, "KeyState": state,
                "Enabled": state == "Enabled", "KeySpec": "SYMMETRIC_DEFAULT", "KeyUsage": "ENCRYPT_DECRYPT",
                "Aliases": [name], "Description": desc, "KeyRotationEnabled": rotation}
    return {
        PROD: [k("prod-payroll", "CUSTOMER", True, "급여 DB·명세서 암호화"),
               k("prod-tenant", "CUSTOMER", True, "고객사 테넌트 데이터 암호화"),
               k("prod-legacy-2024", "CUSTOMER", False, "구 급여 시스템 이관용 (사용 중지)", state="Disabled"),
               k("aws/ebs@prod", "AWS", True, "Default key that protects my EBS volumes when no other key is defined"),
               k("aws/rds@prod", "AWS", True, "Default key that protects my RDS database volumes when no other key is defined")],
        DEV: [k("dev-app", "CUSTOMER", False, "개발 환경 애플리케이션 데이터"),
              k("aws/ebs@dev", "AWS", True, "Default key that protects my EBS volumes when no other key is defined")],
        SEC: [k("sec-siem", "CUSTOMER", True, "SIEM 저장소 암호화"),
              k("central-audit-logs", "CUSTOMER", True, "통합 감사 로그 버킷 암호화"),
              k("soc-forensics", "CUSTOMER", True, "침해사고 포렌식 이미지 보관"),
              k("aws/ebs@sec", "AWS", True, "Default key that protects my EBS volumes when no other key is defined")],
        SBX: [],
    }[acct]


def volumes(acct):
    def v(vid, name, key, inst, size, state="in-use"):
        d = {"VolumeId": vid, "Size": size, "VolumeType": "gp3", "State": state, "Encrypted": key is not None,
             "AvailabilityZone": "ap-northeast-2a", "Tags": [{"Key": "Name", "Value": name}],
             "Attachments": [{"InstanceId": inst, "Device": "/dev/xvda", "State": "attached"}] if inst else []}
        if key:
            d["KmsKeyId"] = key
        return d
    return {
        PROD: [v("vol-0c1app0000000a1", "prod-app-a-root", karn_of("prod-tenant"), "i-0c1app00000000a1", 40),
               v("vol-0c1app0000000c1", "prod-app-c-root", karn_of("prod-tenant"), "i-0c1app00000000c1", 40),
               v("vol-0c1bastion00001", "prod-bastion-root", karn_of("aws/ebs@prod"), "i-0c1bastion000001", 8),
               v("vol-0c1batch0000001", "prod-payroll-batch-data", karn_of("prod-payroll"), "i-0c1batch00000001", 300),
               v("vol-0c1oldpay000001", "payroll-v1-data-backup", karn_of("prod-legacy-2024"), None, 500,
                 state="available")],
        DEV: [v("vol-0c2app0000000a1", "dev-app-a-root", karn_of("dev-app"), "i-0c2app00000000a1", 30),
              v("vol-0c2batch0000001", "dev-legacy-batch-root", karn_of("aws/ebs@dev"), "i-0c2batch00000001", 30)],
        SEC: [v("vol-0c3siem00000001", "soc-siem-data", karn_of("sec-siem"), "i-0c3siem000000001", 2000),
              v("vol-0c3tools0000001", "soc-tools-root", karn_of("aws/ebs@sec"), "i-0c3tools00000001", 60)],
        SBX: [v("vol-0c9poc00000001", "poc-root", None, "i-0c9poc0000000001", 20)],
    }[acct]


def bucket(name, algo, key=None, lifecycle=None):
    d = {"SSEAlgorithm": algo, **({"KMSMasterKeyID": key} if key else {})}
    b = {"Name": name, "Region": REGION, "CreationDate": "2025-01-01T00:00:00+00:00",
         "Encryption": [{"ApplyServerSideEncryptionByDefault": d, "BucketKeyEnabled": algo == "aws:kms"}]}
    if lifecycle is not None:
        b["Lifecycle"] = lifecycle
    return b


def expire(days, transition=None):
    r = {"ID": "retention", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": days}}
    if transition:
        r["Transitions"] = [{"Days": transition, "StorageClass": "GLACIER"}]
    return [r]


BUCKETS = {
    PROD: [bucket("c-prod-tenant-uploads", "aws:kms", karn_of("prod-tenant")),
           bucket("c-prod-payslip-pdf", "AES256"),
           bucket("c-prod-web-assets", "AES256"),
           bucket("c-prod-alb-logs", "AES256", lifecycle=expire(180)),
           bucket("c-prod-legacy-trail-logs", "AES256", lifecycle=expire(400)),
           bucket("c-prod-payroll-migration-0817", "AES256", lifecycle=[])],
    DEV: [bucket("c-dev-test-fixtures", "aws:kms", karn_of("dev-app")),
          bucket("c-dev-cloudtrail-logs", "AES256", lifecycle=expire(1500, transition=90))],
    SEC: None,
    SBX: [bucket("c-sbx-poc-uploads", "AES256", lifecycle=[])],
}

TLS13 = "ELBSecurityPolicy-TLS13-1-2-2021-06"
TLS11 = "ELBSecurityPolicy-TLS-1-1-2017-01"
LEG = "ELBSecurityPolicy-2016-08"
SSL = {TLS13: ["TLSv1.2", "TLSv1.3"], TLS11: ["TLSv1.1", "TLSv1.2"], LEG: ["TLSv1", "TLSv1.1", "TLSv1.2"]}


def listeners(acct):
    def lb(name, scheme, ls):
        return {"LoadBalancerName": name, "Scheme": scheme, "Type": "application", "State": {"Code": "active"},
                "DNSName": f"{name}-1234567890.{REGION}.elb.amazonaws.com",
                "LoadBalancerArn": f"arn:aws:elasticloadbalancing:{REGION}:{acct}:loadbalancer/app/{name}/0c{acct[-1]}5f2e9a7d1b3c",
                "Listeners": ls}

    def li(port, proto, action, policy=None):
        acts = ([{"Type": "forward", "TargetGroupArn": f"arn:aws:elasticloadbalancing:{REGION}:{acct}:targetgroup/tg-{port}/1"}]
                if action == "forward" else
                [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "Host": "#{host}",
                                                          "Path": "/#{path}", "Query": "#{query}", "StatusCode": "HTTP_301"}}])
        d = {"Port": port, "Protocol": proto, "DefaultActions": acts}
        if policy:
            d["SslPolicy"] = policy
            d["Certificates"] = [{"CertificateArn": f"arn:aws:acm:{REGION}:{acct}:certificate/peoplecloud"}]
        return d
    return {
        PROD: [lb("prod-hr-web", "internet-facing", [li(443, "HTTPS", "forward", TLS13), li(80, "HTTP", "redirect")]),
               lb("prod-api", "internet-facing", [li(443, "HTTPS", "forward", TLS11)]),
               lb("prod-internal-admin", "internal", [li(8080, "HTTP", "forward"), li(443, "HTTPS", "forward", LEG)])],
        DEV: [lb("dev-web", "internet-facing", [li(443, "HTTPS", "forward", TLS13), li(80, "HTTP", "redirect")])],
        SEC: [],
        SBX: [lb("poc-web", "internet-facing", [li(80, "HTTP", "forward")])],
    }[acct]

# ───────────────────────────── 로그·백업 ─────────────────────────────


def trail(acct, name, logging, multi, glob, validation, bucket_name, rw="All"):
    return {"Name": name, "TrailARN": f"arn:aws:cloudtrail:{REGION}:{acct}:trail/{name}", "HomeRegion": REGION,
            "IsMultiRegionTrail": multi, "IncludeGlobalServiceEvents": glob, "IsOrganizationTrail": False,
            "LogFileValidationEnabled": validation, "S3BucketName": bucket_name,
            "Status": {"IsLogging": logging, **({"StopLoggingTime": "2025-11-20T02:00:00+00:00"} if not logging else
                                                {"LatestDeliveryTime": "2026-11-02T02:55:00+00:00"})},
            "EventSelectors": [{"ReadWriteType": rw, "IncludeManagementEvents": True, "DataResources": []}]}


CENTRAL = "c-sec-central-audit-logs"
TRAILS = {
    PROD: [trail(PROD, "c-prod-audit", True, True, True, True, CENTRAL),
           trail(PROD, "c-prod-legacy-trail", False, False, True, False, "c-prod-legacy-trail-logs")],
    DEV: [trail(DEV, "c-dev-audit", True, True, True, True, "c-dev-cloudtrail-logs", rw="ReadOnly")],
    SEC: [trail(SEC, "c-sec-audit", True, True, True, False, CENTRAL)],
    SBX: [],
}
GUARDDUTY = {PROD: [{"DetectorId": "6ec1prod0000000000000000000000a1", "Status": "ENABLED"}],
             DEV: None,
             SEC: [{"DetectorId": "6ec3sec00000000000000000000000c1", "Status": "ENABLED"}],
             SBX: []}


def plan(acct, name, sched, keep, copy_region=None):
    rule = {"RuleName": name.split("-")[-1], "TargetBackupVaultName": f"{ALIAS[acct]}-vault",
            "ScheduleExpression": sched, "Lifecycle": {"DeleteAfterDays": keep}, "CopyActions": []}
    if copy_region:
        rule["CopyActions"] = [{"DestinationBackupVaultArn": f"arn:aws:backup:{copy_region}:{acct}:backup-vault:{ALIAS[acct]}-dr",
                                "Lifecycle": {"DeleteAfterDays": keep}}]
    return {"BackupPlanName": name, "BackupPlanId": f"bp-{name}", "Rules": [rule]}


BACKUP = {PROD: [plan(PROD, "prod-daily", "cron(0 17 * * ? *)", 14),
                 plan(PROD, "prod-weekly-dr", "cron(0 18 ? * SUN *)", 35, copy_region="ap-northeast-3")],
          DEV: [plan(DEV, "dev-weekly", "cron(0 19 ? * SAT *)", 7)],
          SEC: [], SBX: []}

ALL_FILES = ["backup_plans.json", "cloudtrail_trails.json", "cognito_user_pools.json", "credential_report.csv",
             "ec2_route_tables.json", "ec2_security_groups.json", "ec2_subnets.json", "ec2_volumes.json",
             "elbv2_listeners.json", "elbv2_ssl_policies.json", "guardduty.json", "iam_authorization.json",
             "iam_password_policy.json", "kms_keys.json", "login_profiles.json", "rds_db_instances.json",
             "s3_buckets.json"]


def _j(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_snapshot() -> None:
    for acct in (PROD, DEV, SEC, SBX):
        d = SNAP / acct
        d.mkdir(parents=True, exist_ok=True)
        (d / "credential_report.csv").write_text(credential_report(acct), encoding="utf-8")
        _j(d / "login_profiles.json", login_profiles(acct))
        _j(d / "iam_authorization.json", authorization(acct))
        pp = PW_POLICY[acct]
        _j(d / "iam_password_policy.json", {"PasswordPolicy": pp} if pp else {"Error": {
            "Code": "NoSuchEntity", "Message": f"The Password Policy with domain name {acct} cannot be found."}})
        _j(d / "cognito_user_pools.json", COGNITO[acct])
        n = NET[acct]()
        _j(d / "ec2_security_groups.json", [dict(g, OwnerId=acct) for g in n["sg"]])
        _j(d / "ec2_subnets.json", [dict(s, OwnerId=acct) for s in n["subnet"]])
        _j(d / "ec2_route_tables.json", [dict(r, OwnerId=acct) for r in n["rt"]])
        _j(d / "rds_db_instances.json", n["rds"])
        _j(d / "kms_keys.json", kms(acct))
        _j(d / "ec2_volumes.json", volumes(acct))
        if BUCKETS[acct] is not None:
            _j(d / "s3_buckets.json", BUCKETS[acct])
        ls = listeners(acct)
        _j(d / "elbv2_listeners.json", ls)
        used = sorted({x["SslPolicy"] for lb in ls for x in lb["Listeners"] if "SslPolicy" in x})
        _j(d / "elbv2_ssl_policies.json", [{"Name": p, "SslProtocols": SSL[p],
                                            "SupportedLoadBalancerTypes": ["application", "network"]} for p in used])
        _j(d / "cloudtrail_trails.json", TRAILS[acct])
        if GUARDDUTY[acct] is not None:
            _j(d / "guardduty.json", GUARDDUTY[acct])
        _j(d / "backup_plans.json", BACKUP[acct])

    def entry(acct, status, errors=()):
        files = sorted(p.name for p in (SNAP / acct).iterdir())
        e = {"account_id": acct, "alias": ALIAS[acct], "status": status, "files": files}
        if errors:
            e["missing"] = sorted({x["file"] for x in errors})
            e["errors"] = list(errors)
        return e

    manifest = {
        "snapshot_id": "c-corp-eval-2026-11-02",
        "source": "fixture",
        "collected_at": "2026-11-02T03:00:00+00:00",
        "collector": "gapcheck-collector/fixture",
        "region": REGION,
        "note": "C사 진단용 가상 스냅샷. live 수집기와 같은 파일 형식을 쓴다.",
        "accounts": [
            entry(PROD, "ok"),
            entry(DEV, "partial", [{"file": "guardduty.json", "api": "guardduty:ListDetectors",
                                    "error": "AccessDeniedException",
                                    "message": "User: arn:aws:sts::801000000002:assumed-role/GapcheckCollector/run is not "
                                               "authorized to perform: guardduty:ListDetectors (SCP deny)"}]),
            entry(SEC, "partial", [{"file": "s3_buckets.json", "api": "s3:ListAllMyBuckets",
                                    "error": "AccessDenied",
                                    "message": "Access Denied (bucket policy / SCP on log-archive account)"}]),
            entry(SBX, "ok"),
        ],
    }
    _j(SNAP / "manifest.json", manifest)

# ───────────────────────────── 증적 (xlsx) ─────────────────────────────


def sheet(path: Path, title: str, head: list[str], rows: list[list], *, note: str | None = None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2F5597")
        c.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(10, max(len(str(c.value or "")) for c in col) * 1.7)
    ws.freeze_panes = "A2"
    if note:
        ws2 = wb.create_sheet("작성 기준")
        for line in note.split("\n"):
            ws2.append([line])
    wb.properties.creator = "C사 정보보호파트 (가상)"
    wb.properties.created = FIXED
    wb.properties.modified = FIXED
    wb.save(path)


def write_evidence() -> None:
    EV.mkdir(parents=True, exist_ok=True)
    P, D, S = PROD, DEV, SEC
    sheet(EV / "AWS_계정관리대장_2026-10-31.xlsx", "계정관리대장",
          ["No", "계정ID", "계정 별칭", "IAM 사용자", "사번", "소속", "용도", "콘솔 비밀번호", "발급일", "승인자",
           "사용기한", "회수일", "비고"], [
              [1, P, "c-prod", "park.sj", "E1007", "정보보호파트", "보안 관리", "사용", "2024-03-04", "CISO", None, None, None],
              [2, P, "c-prod", "kim.dh", "E1102", "플랫폼파트", "인프라 운영", "사용", "2025-01-13", "플랫폼파트장", None, None, None],
              [3, P, "c-prod", "choi.mr", "E2033", "급여운영팀", "급여 운영", "사용", "2026-03-09", "급여운영팀장", None, None, None],
              [4, P, "c-prod", "yoon.hj", "E2088", "개발1팀", "개발", "사용", "2026-10-20", "개발1팀장", None, None, None],
              [5, P, "c-prod", "lee.jw", "E2084", "개발1팀", "개발", "사용", "2026-09-01", "개발1팀장", None, None, None],
              [6, P, "c-prod", "jhkim", "E2041", "급여운영팀", "급여 운영", "사용", "2025-05-19", "급여운영팀장", None, None, None],
              [7, P, "c-prod", "lim.ga", "E2055", "급여운영팀", "급여 운영", "사용", "2025-08-04", "급여운영팀장", None, None, "육아휴직 중"],
              [8, P, "c-prod", "ops-shared", "-", "플랫폼파트", "야간 운영 공용", "사용", "2025-02-03", "정보보호파트장", None, None, "교대 근무자 3명 사용"],
              [9, P, "c-prod", "svc-report-export", "-", "플랫폼파트", "급여명세서 내보내기 서비스", "미사용", "2025-04-01", "플랫폼파트장", None, None, None],
              [10, P, "c-prod", "svc-payroll-batch", "-", "플랫폼파트", "급여 배치 서비스", "미사용", "2024-11-01", "플랫폼파트장", None, None, None],
              [11, P, "c-prod", "vendor-hrcore", "V-0311", "(협력사) 에이치알코어", "외부 유지보수", "사용", "2026-06-01", "플랫폼파트장", "2026-09-30", None, "급여엔진 유지보수"],
              [12, P, "c-prod", "sysadmin-hong", "E1150", "플랫폼파트", "인프라 운영", "사용", "2025-09-22", "플랫폼파트장", None, None, None],
              [13, D, "c-dev", "dev-cho", "E1120", "개발2팀", "개발", "사용", "2025-03-17", "개발2팀장", None, None, None],
              [14, D, "c-dev", "sypark", "E2019", "개발2팀", "개발", "사용", "2024-09-02", "개발2팀장", None, "2026-09-18", "콘솔 비밀번호 삭제"],
              [15, D, "c-dev", "qa-shared", "-", "QA팀", "QA 공용 테스트", "사용", "2025-11-03", None, None, None, None],
              [16, D, "c-dev", "batch-shared", "-", "개발2팀", "배치 테스트 공용", "미사용", "2025-06-02", None, None, None, None],
              [17, D, "c-dev", "vendor-qa", "V-0402", "(협력사) 큐에이랩", "외부 유지보수", "미사용", "2026-07-01", "QA팀장", "2026-10-15", "2026-10-16", None],
              [18, D, "c-dev", "jung.ws", "E2070", "개발2팀", "개발", "사용", "2026-02-02", "개발2팀장", None, None, None],
              [19, D, "c-dev", "hwang.yr", "E2077", "QA팀", "QA", "사용", "2025-12-01", "QA팀장", None, None, None],
              [20, D, "c-dev", "oh.ks", "E1988", "개발2팀", "개발", "미사용", "2024-10-07", "개발2팀장", None, "2026-08-14", None],
              [21, S, "c-sec", "park.sj", "E1007", "정보보호파트", "보안 관리", "사용", "2024-03-05", "CISO", None, None, None],
              [22, S, "c-sec", "sec.kang", "E1131", "정보보호파트", "보안 관제", "사용", "2025-07-07", "CISO", None, None, None],
              [23, S, "c-sec", "vendor-soc", "V-0420", "(협력사) 시큐어워치", "외부 유지보수", "사용", "2026-10-01", "정보보호파트장", "2027-03-31", None, "관제 솔루션 유지보수"],
              [24, S, "c-sec", "svc-siem-ingest", "-", "정보보호파트", "SIEM 수집 서비스", "미사용", "2025-07-08", "정보보호파트장", None, None, None],
          ])
    sheet(EV / "인사명부_2026-11-01.xlsx", "인사명부",
          ["사번", "성명", "소속", "직급", "입사일", "상태", "퇴직일", "비고"], [
              ["E1007", "박○○", "정보보호파트", "파트장", "2019-04-01", "재직", None, None],
              ["E1102", "김○○", "플랫폼파트", "책임", "2021-01-04", "재직", None, None],
              ["E1120", "조○○", "개발2팀", "책임", "2021-03-02", "재직", None, None],
              ["E1131", "강○○", "정보보호파트", "선임", "2021-07-01", "재직", None, None],
              ["E1150", "홍○○", "플랫폼파트", "선임", "2021-09-13", "재직", None, None],
              ["E1988", "오○○", "개발2팀", "선임", "2020-10-05", "퇴직", "2026-08-14", None],
              ["E2019", "박○○", "개발2팀", "선임", "2022-08-29", "퇴직", "2026-09-18", None],
              ["E2033", "최○○", "급여운영팀", "선임", "2023-03-06", "재직", None, None],
              ["E2041", "김○○", "급여운영팀", "사원", "2023-05-15", "퇴직", "2026-10-08", None],
              ["E2055", "임○○", "급여운영팀", "사원", "2023-08-01", "휴직", None, "육아휴직 2026-10-01 ~ 2027-09-30"],
              ["E2070", "정○○", "개발2팀", "사원", "2026-02-02", "재직", None, None],
              ["E2077", "황○○", "QA팀", "사원", "2025-11-24", "퇴직", "2026-10-29", None],
              ["E2084", "이○○", "개발1팀", "사원", "2026-08-31", "재직", None, None],
              ["E2088", "윤○○", "개발1팀", "사원", "2026-10-19", "재직", None, None],
          ])
    sheet(EV / "특수권한자현황_2026-10.xlsx", "특수권한자 현황",
          ["No", "AWS 계정", "IAM 사용자", "권한", "부여 사유", "승인자", "승인일", "차기 검토"], [
              [1, "c-prod", "park.sj", "AdministratorAccess (SecurityAdmins)", "보안 관리 총괄", "CISO", "2026-01-05", "2026-12"],
              [2, "c-sec", "park.sj", "AdministratorAccess (SecurityAdmins)", "보안 관리 총괄", "CISO", "2026-01-05", "2026-12"],
              [3, "c-sec", "sec.kang", "IAMFullAccess (SecOps)", "관제 계정·역할 관리", "CISO", "2025-07-07", "2026-12"],
          ])
    sheet(EV / "접근권한검토_결과.xlsx", "접근권한 검토",
          ["회차", "검토일", "검토자", "대상", "결과", "조치", "조치 완료일"], [
              ["2025-하반기", "2025-11-14", "정보보호파트 강○○", "AWS 3개 계정 IAM, 피플클라우드 관리자", "과다 권한 2건", "그룹 조정", "2025-11-28"],
              ["2026-상반기", "2026-05-20", "정보보호파트 강○○", "AWS 3개 계정 IAM, 피플클라우드 관리자", "장기 미사용 1건", "비활성화", "2026-05-22"],
          ])
    sheet(EV / "정보자산목록_2026-10-15.xlsx", "정보자산",
          ["자산ID", "자산명", "유형", "AWS 계정", "리소스ID", "개인정보", "중요도", "소유부서", "등록일"], [
              ["C-DB-001", "급여 DB (운영)", "RDS", "c-prod", "prod-payroll", "Y", "상", "급여운영팀", "2024-03-15"],
              ["C-DB-002", "테넌트 코어 DB (운영)", "RDS", "c-prod", "prod-tenant-core", "Y", "상", "플랫폼파트", "2024-03-15"],
              ["C-DB-101", "급여 DB (스테이징)", "RDS", "c-dev", "stg-payroll", "Y", "중", "개발2팀", "2025-09-01"],
              ["C-ST-001", "고객사 업로드 파일", "S3", "c-prod", "c-prod-tenant-uploads", "Y", "상", "플랫폼파트", "2024-03-15"],
              ["C-ST-002", "급여명세서 PDF", "S3", "c-prod", "c-prod-payslip-pdf", "Y", "상", "급여운영팀", "2024-06-03"],
              ["C-ST-003", "웹 정적 파일", "S3", "c-prod", "c-prod-web-assets", "N", "하", "개발1팀", "2024-03-15"],
              ["C-ST-004", "ALB 접근 로그", "S3", "c-prod", "c-prod-alb-logs", "N", "하", "플랫폼파트", "2024-03-15"],
              ["C-ST-005", "구 감사 로그", "S3", "c-prod", "c-prod-legacy-trail-logs", "N", "하", "정보보호파트", "2024-03-15"],
              ["C-ST-101", "테스트 픽스처", "S3", "c-dev", "c-dev-test-fixtures", "N", "하", "개발2팀", "2025-03-20"],
              ["C-ST-102", "감사 로그 (개발)", "S3", "c-dev", "c-dev-cloudtrail-logs", "N", "중", "정보보호파트", "2025-03-20"],
              ["C-ST-201", "통합 감사 로그", "S3", "c-sec", "c-sec-central-audit-logs", "N", "중", "정보보호파트", "2024-03-15"],
              ["C-SV-001", "급여 배치 서버", "EC2", "c-prod", "i-0c1batch00000001", "Y", "상", "플랫폼파트", "2024-03-15"],
              ["C-SV-201", "SIEM 서버", "EC2", "c-sec", "i-0c3siem000000001", "N", "상", "정보보호파트", "2025-07-10"],
              ["C-SV-202", "관제 도구 서버", "EC2", "c-sec", "i-0c3tools00000001", "N", "중", "정보보호파트", "2025-07-10"],
          ])
    sheet(EV / "암호키관리대장.xlsx", "암호키 관리대장",
          ["관리번호", "키 별칭", "AWS 계정", "키 ID", "용도", "승인자", "생성일", "자동 교체", "상태"], [
              ["KEY-01", "alias/prod-payroll", "c-prod", kid("prod-payroll"), "급여 DB·명세서·배치 디스크", "CISO", "2024-03-10", "사용", "사용"],
              ["KEY-02", "alias/prod-tenant", "c-prod", kid("prod-tenant"), "테넌트 데이터·앱 서버 디스크", "CISO", "2024-03-10", "사용", "사용"],
              ["KEY-03", "alias/prod-legacy-2024", "c-prod", kid("prod-legacy-2024"), "구 급여 시스템 이관 (2025-12 사용 중지)", "CISO", "2024-01-22", "-", "비활성 (2026-12 폐기 예정)"],
              ["KEY-11", "alias/dev-app", "c-dev", kid("dev-app"), "개발 환경 데이터", "CISO", "2025-03-15", "사용", "사용"],
              ["KEY-21", "alias/sec-siem", "c-sec", kid("sec-siem"), "SIEM 저장소", "CISO", "2025-07-08", "사용", "사용"],
              ["KEY-22", "alias/central-audit-logs", "c-sec", kid("central-audit-logs"), "통합 감사 로그", "CISO", "2024-03-12", "사용", "사용"],
          ])
    sheet(EV / "접속기록점검_2026.xlsx", "접속기록 점검",
          ["분기", "점검일", "점검자", "대상 시스템", "결과", "조치"], [
              ["2025-4Q", "2025-12-22", "정보보호파트 강○○", "피플클라우드 관리자콘솔, 급여 DB", "이상 없음", None],
              ["2026-1Q", "2026-03-30", "정보보호파트 강○○", "피플클라우드 관리자콘솔, 급여 DB", "업무시간 외 대량 조회 1건", "소명 확인"],
              ["2026-2Q", "2026-06-29", "정보보호파트 강○○", "피플클라우드 관리자콘솔, 급여 DB", "이상 없음", None],
              ["2026-3Q", "2026-09-29", "정보보호파트 강○○", "피플클라우드 관리자콘솔, 급여 DB", "퇴직 예정자 다운로드 2건", "사유 확인, 회수 요청"],
          ])
    sheet(EV / "백업복구시험_2026.xlsx", "복구 시험",
          ["시험일", "대상", "방법", "결과", "확인자", "RTO 실측"], [
              ["2026-03-18", "prod-tenant-core", "스냅샷 → 격리 VPC 복원", "성공", "플랫폼파트장", "47분"],
              ["2026-06-11", "prod-payroll", "PITR 복원", "성공", "플랫폼파트장", "1시간 12분"],
              ["2026-09-10", "c-prod-tenant-uploads", "AWS Backup 복원 (서울 → 오사카 사본)", "성공", "플랫폼파트장", "2시간 5분"],
          ])
    sheet(EV / "재해복구훈련_결과.xlsx", "DR 훈련",
          ["훈련일", "시나리오", "참여", "결과", "개선사항"], [
              ["2025-04-17", "급여 DB 장애 시 스냅샷 복구 (도상훈련)", "플랫폼파트, 급여운영팀", "목표 RTO 달성", "연락망 갱신"],
              ["2026-04-23", "서울 리전 장애 → 오사카 리전 전환 (모의훈련)", "플랫폼파트, 정보보호파트, 개발1팀", "부분 달성 (DNS 전환 지연)", "Route 53 헬스체크 보완"],
          ])
    sheet(EV / "정보보호위원회_회의록목록.xlsx", "회의 목록",
          ["개최일", "구분", "안건", "참석자", "결과"], [
              ["2025-06-20", "정보보호위원회(정기)", "2025 상반기 보안 점검 결과, 하반기 계획", "대표이사, CISO, 본부장 3인", "원안 의결"],
              ["2025-12-18", "정보보호위원회(정기)", "2026 정보보호 계획·예산, 위험평가 결과", "대표이사, CISO, 본부장 3인", "원안 의결"],
              ["2026-03-27", "정보보호위원회(임시)", "ISMS-P 인증 추진 및 범위", "대표이사, CISO, 본부장 2인", "수정 의결"],
              ["2026-06-25", "정보보호 실무협의회", "상반기 취약점 점검 결과 공유", "정보보호파트장, 플랫폼파트장, 개발팀장", "공유"],
              ["2026-09-24", "정보보호 실무협의회", "인증 심사 준비 현황", "정보보호파트장, 플랫폼파트장, 개발팀장", "공유"],
          ])
    sheet(EV / "내부감사_이력.xlsx", "내부 감사",
          ["감사일", "감사인", "범위", "결과", "보고"], [
              ["2025-06-19", "내부감사팀", "정보보호 관리체계 전 영역", "지적 7건", "대표이사 보고"],
              ["2026-06-17", "외부 전문기관 (가상 보안컨설팅)", "정보보호 관리체계 전 영역 (ISMS-P 예비 점검)", "지적 8건", "대표이사 보고"],
          ])
    sheet(EV / "개선조치관리대장_2026.xlsx", "개선조치",
          ["조치번호", "출처", "발견사항", "담당", "완료예정일", "상태", "완료일"], [
              ["CA-26-01", "2026 내부감사", "정책 문서 검토 이력 미기록", "정보보호파트", "2026-04-30", "완료", "2026-04-22"],
              ["CA-26-02", "2026 내부감사", "퇴직자 계정 회수 지연", "플랫폼파트", "2026-09-30", "완료", "2026-09-25"],
              ["CA-26-03", "2026 내부감사", "백업 복구 시험 결과 미보고", "플랫폼파트", "2026-08-31", "조치완료", "2026-09-10"],
              ["CA-26-04", "2026 내부감사", "특수권한자 현황 최신화", "정보보호파트", "2026-12-15", "조치중", None],
              ["CA-26-05", "2026 내부감사", "DB 보안그룹의 IP 대역 허용 규칙 제거", "플랫폼파트", "2026-10-15", "조치중", None],
              ["CA-26-06", "2026 내부감사", "로그·백업 관리지침 개정", "정보보호파트", "2026-11-30", "미착수", None],
              ["CA-26-07", "2026 내부감사", "개발 계정의 공용 계정 정리", "개발2팀", None, "검토중", None],
          ])
    screen()


def screen() -> None:
    from PIL import Image, ImageDraw, ImageFont
    font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    try:
        f = ImageFont.truetype(font_path, 22, index=1)
        fs = ImageFont.truetype(font_path, 17, index=1)
        fb = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 28, index=1)
    except OSError:
        f = fs = fb = ImageFont.load_default()
    img = Image.new("RGB", (900, 620), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 900, 70], fill=(31, 78, 121))
    d.text((30, 18), "피플클라우드  |  직원 계정 등록", font=fb, fill="white")
    d.text((60, 110), "회사 코드", font=f, fill="black")
    d.rectangle([60, 145, 840, 190], outline=(160, 160, 160), width=2)
    d.text((75, 155), "acme-hr", font=f, fill=(60, 60, 60))
    d.text((60, 215), "아이디 (사내 이메일)", font=f, fill="black")
    d.rectangle([60, 250, 840, 295], outline=(160, 160, 160), width=2)
    d.text((75, 260), "j.doe@acme.example", font=f, fill=(60, 60, 60))
    d.text((60, 320), "비밀번호", font=f, fill="black")
    d.rectangle([60, 355, 840, 400], outline=(200, 60, 60), width=2)
    d.text((75, 365), "●●●●●●●●", font=f, fill=(60, 60, 60))
    d.text((60, 410), "영문, 숫자, 특수문자를 조합하여 10자 이상 입력해 주세요.", font=fs, fill=(90, 90, 90))
    d.text((60, 440), "비밀번호가 보안 기준에 맞지 않습니다.", font=fs, fill=(200, 60, 60))
    d.rectangle([60, 500, 840, 555], fill=(31, 78, 121))
    d.text((400, 512), "가입하기", font=f, fill="white")
    d.text((640, 585), "캡처 2026-10-28 (모바일 웹)", font=fs, fill=(150, 150, 150))
    img.save(EV / "직원가입_비밀번호_화면_2026-10-28.png", optimize=True)

# ───────────────────────────── 규정 문서 (docx) ─────────────────────────────


def _cell(cell, text, bold=False, shade=None):
    cell.text = ""
    run = cell.paragraphs[0].add_run(text)
    run.bold = bold
    run.font.size = Pt(9.5)
    if shade:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), shade)
        tcPr.append(shd)


def new_doc(title: str, meta: list[tuple[str, str]], hist_head: list[str], hist: list[list[str]],
            *, company_line: str = "C사", subtitle: str | None = None):
    d = docx.Document()
    d.core_properties.author = "C사 정보보호파트"
    d.core_properties.created = FIXED
    d.core_properties.modified = FIXED
    d.core_properties.title = title
    p = d.add_paragraph(company_line)
    p.runs[0].bold = True
    d.add_paragraph(title, style="Title")
    if subtitle:
        sp = d.add_paragraph(subtitle)
        sp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        sp.runs[0].font.size = Pt(9)
        sp.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)
    t = d.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for k, v in meta:
        r = t.add_row().cells
        _cell(r[0], k, bold=True, shade="E7EEF7")
        _cell(r[1], v)
    d.add_paragraph("개정 이력")
    h = d.add_table(rows=1, cols=len(hist_head))
    h.style = "Table Grid"
    for c, txt in zip(h.rows[0].cells, hist_head):
        _cell(c, txt, bold=True, shade="E7EEF7")
    for row in hist:
        cells = h.add_row().cells
        for c, txt in zip(cells, row):
            _cell(c, txt)
    return d


def body(d, items):
    for style, text in items:
        if style == "B":       # 조 제목을 본문 문단에 굵게 (Heading 스타일을 쓰지 않는 문서)
            p = d.add_paragraph()
            r = p.add_run(text)
            r.bold = True
        elif style == "BT":    # 조 제목 + 본문을 한 문단에
            cut = text.index(")") + 1
            title, rest = text[:cut], text[cut:].strip()
            p = d.add_paragraph()
            r = p.add_run(title)
            r.bold = True
            if rest:
                p.add_run(" " + rest)
        elif style == "I":     # 들여쓴 본문
            p = d.add_paragraph(text)
            p.paragraph_format.left_indent = Pt(14)
        else:
            p = d.add_paragraph(text, style=style)
            if style.startswith("Heading"):
                for r in p.runs:
                    r.bold = True


def doc_policy():
    d = new_doc("정보보호 정책", [
        ("문서번호", "C-POL-01"), ("버전", "v1.2"), ("시행일", "2026-03-01"), ("승인자", "대표이사"),
        ("소관부서", "정보보호파트"), ("보안등급", "사내한정")],
        ["버전", "일자", "내용", "작성"], [
            ["v1.0", "2024-03-01", "제정", "정보보호파트"],
            ["v1.1", "2025-03-10", "정보보호위원회 운영 주기 변경(연 1회 → 반기 1회), 실무협의회 신설", "정보보호파트"],
            ["v1.2", "2026-02-16", "ISMS-P 인증 범위 반영, 하위 문서 목록 갱신", "정보보호파트"],
        ])
    body(d, [
        ("Heading 1", "제1장 총칙"),
        ("Heading 2", "제1조(목적)"),
        ("Normal", "이 정책은 C사(이하 \"회사\")가 제공하는 HR·급여 클라우드 서비스 \"피플클라우드\"와 이를 운영하는 정보자산 및 "
                   "고객사 임직원의 개인정보를 보호하기 위한 회사의 기본 방향과 책임을 정한다."),
        ("Heading 2", "제2조(적용 범위)"),
        ("Normal", "① 이 정책은 회사의 임직원, 파견·협력사 인력 및 회사 정보시스템에 접근하는 모든 자에게 적용한다."),
        ("Normal", "② 회사가 운영하는 AWS 계정(운영·개발·보안), 피플클라우드 서비스 및 사내 업무시스템을 포함한다."),
        ("Heading 1", "제2장 조직과 책임"),
        ("Heading 2", "제3조(정보보호 최고책임자)"),
        ("Normal", "① 대표이사는 정보보호 업무를 총괄할 임원을 정보보호 최고책임자(이하 \"CISO\")로 임명한다."),
        ("Normal", "② CISO는 개인정보 보호책임자를 겸할 수 있으며, 정보보호 계획 수립, 예산 집행, 사고 대응을 총괄한다."),
        ("Heading 2", "제4조(정보보호위원회)"),
        ("Normal", "① 정보보호에 관한 중요 사항을 심의·의결하기 위하여 대표이사를 위원장으로, CISO와 각 본부장을 위원으로 하는 "
                   "정보보호위원회를 둔다."),
        ("Normal", "② 위원회는 반기마다 정기회의를 개최하며, 위원장이 필요하다고 인정하는 경우 임시회의를 소집할 수 있다."),
        ("Heading 2", "제5조(정보보호 실무협의회)"),
        ("Normal", "정보보호파트장을 의장으로 하고 각 파트·팀장으로 구성된 실무협의회를 두어 위원회 상정 안건을 사전 검토하고 "
                   "실무 이행 사항을 공유한다. 실무협의회는 위원회를 대신하지 않는다."),
        ("Heading 1", "제3장 정책 체계"),
        ("Heading 2", "제6조(문서 체계와 승인)"),
        ("Normal", "① 정보보호 문서는 정책, 규정·지침, 절차 및 계획으로 구분한다."),
        ("Normal", "② 정책은 대표이사가 승인하고, 규정·지침·절차 및 계획은 CISO가 승인하여 시행한다."),
        ("Heading 2", "제7조(문서의 검토)"),
        ("Normal", "정보보호파트는 정책과 하위 문서를 매년 1회 이상 검토하여 법령·조직·시스템 변화를 반영하며, 개정할 사항이 "
                   "없는 경우에도 검토 일자와 결과를 개정 이력에 기록한다."),
        ("Heading 2", "제8조(하위 문서)"),
        ("Normal", "이 정책의 시행을 위하여 다음 각 호의 문서를 둔다."),
        ("Normal", "1. 통합 보안관리 규정 (C-REG-02)"),
        ("Normal", "2. 계정관리 절차 (C-PRC-03)"),
        ("Normal", "3. 로그 및 백업 관리지침 (C-GDL-07)"),
        ("Normal", "4. 개인정보 내부 관리계획 (C-PIP-01)"),
        ("Heading 1", "제4장 관리체계 운영"),
        ("Heading 2", "제9조(정보자산 관리)"),
        ("Normal", "① 각 부서는 클라우드 자원을 포함하여 소관 정보자산을 빠짐없이 식별하고, 정보보호파트는 이를 정보자산 목록으로 "
                   "통합 관리한다."),
        ("Normal", "② 자산에는 개인정보 포함 여부와 중요도(상·중·하)를 부여하며, 새로 만든 자원은 생성 후 지체 없이 목록에 등록한다."),
        ("Heading 2", "제10조(위험 관리)"),
        ("Normal", "정보보호파트는 매년 위험평가를 실시하고, 그 결과와 위험 처리 계획을 정보보호위원회에 보고한다."),
        ("Heading 2", "제11조(관리체계 점검)"),
        ("Normal", "회사는 정보보호파트로부터 독립된 내부감사팀 또는 외부 전문기관으로 하여금 연 1회 이상 관리체계 운영 현황을 "
                   "점검하게 하고, 그 결과를 대표이사에게 보고한다."),
        ("Heading 2", "제12조(개선 조치)"),
        ("Normal", "점검·인증심사·침해사고 등에서 발견된 문제점은 조치 담당자와 완료 기한을 정하여 개선조치 관리대장에 기록하고, "
                   "정보보호파트는 매월 이행 여부를 확인한다."),
        ("Heading 1", "부칙"),
        ("Normal", "1. 이 정책은 2026년 3월 1일부터 시행한다."),
    ])
    return d


def doc_regulation():
    d = new_doc("통합 보안관리 규정", [
        ("문서번호", "C-REG-02"), ("문서명", "통합 보안관리 규정"), ("버전", "v3.0"), ("제정일", "2023-09-01"),
        ("최종개정일", "2025-07-01"), ("시행일", "2025-07-15"), ("승인자", "정보보호 최고책임자"),
        ("관리부서", "정보보호파트")],
        ["버전", "일자", "내용", "작성자", "검토·승인"], [
            ["v1.0", "2023-09-01", "제정 (계정·접근통제 지침, 네트워크 보안 지침 통합)", "정보보호파트", "CISO"],
            ["v2.0", "2024-08-20", "AWS 멀티 계정 구조 반영, 암호화 장 신설", "정보보호파트", "CISO"],
            ["v3.0", "2025-07-01", "비밀번호 기준 상향(10자 → 12자), 미사용 계정 기준 90일 → 60일", "정보보호파트", "CISO"],
            ["v3.0", "2026-07-14", "연간 정기 검토 — 개정 사항 없음", "정보보호파트", "CISO"],
        ], subtitle="이 규정은 종전 「계정·접근통제 지침」과 「네트워크 보안 지침」을 대체한다.")
    body(d, [
        ("Heading 1", "제1장 총칙"),
        ("BT", "제1조(목적) 이 규정은 정보보호 정책(C-POL-01)과 「개인정보 보호법」 제29조에 따라 회사 정보시스템의 계정·인증, "
               "권한, 네트워크, 암호화에 관한 보안 기준을 정한다."),
        ("BT", "제2조(적용 범위) 이 규정은 회사의 AWS 계정과 그 안의 모든 자원, 피플클라우드 서비스 및 관리 도구에 적용한다."),
        ("B", "제3조(정의)"),
        ("I", "이 규정에서 사용하는 용어의 뜻은 다음과 같다."),
        ("I", "1. \"사용자\"란 회사 정보시스템을 운영·개발하기 위하여 계정을 부여받은 임직원과 협력사 인력을 말한다."),
        ("I", "2. \"이용자\"란 피플클라우드에 로그인하는 고객사의 관리자와 직원을 말한다."),
        ("I", "3. \"관리 콘솔\"이란 AWS Management Console 등 클라우드 자원을 관리하는 웹 화면을 말한다."),
        ("Heading 1", "제2장 계정과 인증"),
        ("B", "제4조(계정 원칙)"),
        ("I", "① 계정은 1인 1계정으로 발급하며, 계정 ID는 사용자를 알아볼 수 있는 이름 기반으로 정한다. admin, root, test, "
              "guest 등 누구나 짐작할 수 있는 일반 명칭은 계정 ID로 쓰지 않는다."),
        ("I", "② 업무 특성상 공용 계정이 불가피한 경우 정보보호파트장의 승인을 받아야 하며, 계정관리대장에 승인자와 실제 "
              "사용자를 기록한다."),
        ("BT", "제5조(계정의 생성·변경·삭제) 계정의 생성, 변경, 삭제는 계정관리 절차(C-PRC-03)에 따른다."),
        ("B", "제6조(사용자 비밀번호)"),
        ("I", "① 사용자 비밀번호는 12자 이상으로 하고, 영문 대문자·영문 소문자·숫자·특수문자 중 3종류 이상을 섞어 만든다."),
        ("I", "② 비밀번호는 180일을 넘기지 않고 변경한다."),
        ("I", "③ 최근 사용한 5개의 비밀번호는 다시 쓸 수 없다."),
        ("I", "④ 관리자가 발급하거나 초기화한 임시 비밀번호는 최초 로그인 즉시 변경하여야 하며, 시스템에서 변경을 강제한다."),
        ("I", "⑤ 시스템 관리자는 제1항부터 제4항까지의 기준을 각 시스템의 비밀번호 정책 설정에 반영한다."),
        ("BT", "제7조(추가 인증) 관리 콘솔에 로그인하는 모든 사용자는 비밀번호와 함께 OTP 등 추가 인증 수단(2단계 인증)을 "
               "사용하여야 하며, AWS 계정의 루트 사용자도 같다."),
        ("B", "제8조(이용자 비밀번호)"),
        ("I", "① 이용자 비밀번호는 영문·숫자·특수문자를 조합하여 10자 이상으로 설정하게 한다."),
        ("I", "② 가입 및 비밀번호 변경 화면과 인증 서비스 설정에 제1항의 기준을 적용하여 기준에 미달하는 비밀번호는 등록되지 "
              "않도록 한다."),
        ("Heading 1", "제3장 권한 관리"),
        ("BT", "제9조(권한 부여) 접근 권한은 직무별로 정의한 권한 그룹(IAM 그룹)에 사용자를 배정하는 방식으로만 부여하며, "
               "사용자 개인에게 정책을 직접 연결하지 않는다."),
        ("B", "제10조(특수권한)"),
        ("I", "① 관리자 권한 등 특수권한은 CISO의 승인을 받아 부여하며, 정보보호파트는 특수권한자 현황을 작성하여 관리한다."),
        ("I", "② 외부 유지보수 인력의 계정은 작업 기간에 맞추어 사용기한을 정하여 발급하고, 기한이 지나면 즉시 비활성화한다."),
        ("BT", "제11조(접근권한 검토) 정보보호파트는 반기 1회 이상 사용자 계정과 접근 권한의 적정성을 검토하고 결과를 기록한다."),
        ("BT", "제12조(미사용 계정) 60일 이상 사용 기록이 없는 계정(액세스 키 포함)은 잠금 처리한다."),
        ("Heading 1", "제4장 네트워크 보안"),
        ("B", "제13조(영역 구분)"),
        ("I", "① 서비스망은 인터넷 접점(DMZ) 영역, 애플리케이션 영역, 데이터 영역으로 구분한다."),
        ("I", "② 데이터베이스에는 공인 IP를 부여하지 않으며, 퍼블릭 액세스 설정을 사용하지 않는다."),
        ("I", "③ 데이터 영역의 접근 허용 규칙은 애플리케이션 영역 보안그룹을 출발지로 지정하는 방식으로만 두며, IP 대역을 "
              "출발지로 지정하지 않는다."),
        ("I", "④ 데이터 영역 서브넷의 라우팅 테이블에는 인터넷 게이트웨이나 NAT 게이트웨이로 향하는 경로를 두지 않는다."),
        ("I", "⑤ VPC의 기본 보안그룹은 모든 인바운드·아웃바운드 규칙을 삭제한 상태로 두고 자원에 연결하지 않는다."),
        ("BT", "제14조(원격 관리) 서버의 원격 접속(SSH, RDP)은 본사 IT 관리망(192.0.2.32/27)과 관리자 VPN 대역"
               "(10.250.0.0/24)에서만 허용한다."),
        ("BT", "제15조(취약한 프로토콜) Telnet, FTP, TFTP, rlogin·rsh·rexec 등 평문으로 인증 정보를 전송하는 프로토콜은 "
               "사용하지 않는다."),
        ("Heading 1", "제5장 암호화"),
        ("B", "제16조(저장 데이터 암호화)"),
        ("I", "① 데이터베이스는 저장 시 암호화를 적용한다."),
        ("I", "② 서버에 연결하는 디스크(EBS 볼륨)는 모두 암호화한다."),
        ("I", "③ 개인정보를 저장하는 S3 버킷의 기본 암호화는 회사가 관리하는 KMS 키를 사용하는 방식(SSE-KMS)으로 설정한다."),
        ("BT", "제17조(전송 구간 암호화) 인터넷에 공개하는 서비스는 HTTPS로만 제공하고 HTTP 요청은 HTTPS로 전환하며, "
               "TLS 1.2 미만의 프로토콜은 허용하지 않는다."),
        ("B", "제18조(암호키 관리)"),
        ("I", "① 암호키는 AWS KMS에서 CISO의 승인을 받아 생성하고, 생성한 고객 관리형 키는 암호키 관리대장에 등록한다."),
        ("I", "② 고객 관리형 키는 자동 교체 기능을 켜서 연 1회 이상 교체되도록 한다."),
        ("I", "③ 사용을 마친 키는 비활성화한 뒤 관리대장에 상태를 기록하고, 대기 기간을 거쳐 삭제한다."),
        ("Heading 1", "부칙"),
        ("Normal", "1. 이 규정은 2025년 7월 15일부터 시행한다."),
        ("Normal", "2. 이 규정 시행 전에 설정한 비밀번호는 다음 변경 시까지 종전 기준을 적용한다."),
    ])
    return d


def doc_procedure():
    d = new_doc("계정관리 절차", [
        ("문서번호", "C-PRC-03"), ("버전", "v1.1"), ("시행일", "2026-05-20"), ("승인자", "정보보호파트장"),
        ("작성부서", "정보보호파트"), ("보안등급", "사내한정")],
        ["버전", "일자", "내용", "작성"], [
            ["v1.0", "2025-04-01", "제정", "정보보호파트 강○○"],
            ["v1.1", "2026-05-12", "퇴직자 계정 회수 기한 명시, 외부 유지보수 계정 절차 추가", "정보보호파트 강○○"],
        ])
    body(d, [
        ("Heading 1", "1. 목적"),
        ("Normal", "통합 보안관리 규정 제5조에 따라 AWS 계정(IAM 사용자)과 피플클라우드 관리자 계정을 생성·변경·회수하는 "
                   "실무 절차를 정한다."),
        ("Heading 1", "2. 역할"),
        ("Normal", "가. 정보보호파트: 계정 생성·변경·회수 수행, 계정관리대장 관리"),
        ("Normal", "나. 인사팀: 입사·부서 이동·휴직·퇴직 정보 통보"),
        ("Normal", "다. 각 부서장: 소속 인원의 필요 권한 확인"),
        ("Heading 1", "3. 계정 생성"),
        ("Normal", "가. 계정이 필요한 경우 요청자는 사내 메신저 또는 이메일로 정보보호파트에 계정 생성을 요청한다."),
        ("Normal", "나. 정보보호파트 담당자는 요청자의 소속과 필요한 권한 그룹을 확인한 후 계정을 생성하고 임시 비밀번호를 "
                   "전달한다."),
        ("Normal", "다. 관리 콘솔 계정은 '다음 로그인 시 비밀번호 재설정 필요' 옵션을 선택하여 생성한다."),
        ("Normal", "라. 생성한 계정은 계정관리대장에 사번, 용도, 발급일을 기록한다."),
        ("Heading 1", "4. 직무 변경·휴직"),
        ("Normal", "가. 부서 이동 시 기존 권한 그룹에서 제외한 뒤 새 직무의 권한 그룹에 배정한다."),
        ("Normal", "나. 3개월 이상 휴직하는 경우 휴직 시작일에 콘솔 비밀번호를 잠그고 복직 시 해제한다."),
        ("Heading 1", "5. 퇴직자 계정 회수"),
        ("Normal", "가. 인사팀은 퇴직이 확정되면 퇴직일을 정보보호파트에 통보한다."),
        ("Normal", "나. 정보보호파트는 퇴직일로부터 3영업일 이내에 해당 인원의 콘솔 비밀번호와 액세스 키를 모두 삭제하거나 "
                   "비활성화한다."),
        ("Normal", "다. 회수 결과는 계정관리대장의 회수일 칸에 기록한다."),
        ("Heading 1", "6. 외부 유지보수 계정"),
        ("Normal", "가. 협력사 인력의 계정은 계약서상 작업 기간을 사용기한으로 정하여 계정관리대장에 기록한다."),
        ("Normal", "나. 사용기한 다음 날 콘솔 비밀번호와 액세스 키를 비활성화한다."),
        ("Heading 1", "부칙"),
        ("Normal", "1. 이 절차는 2026년 5월 20일부터 시행한다."),
    ])
    return d


def doc_logging():
    d = new_doc("로그 및 백업 관리지침", [
        ("문서번호", "C-GDL-07"), ("버전", "v1.1"), ("시행일", "2025-07-15"), ("승인자", "정보보호 최고책임자"),
        ("소관부서", "정보보호파트"), ("보안등급", "사내한정")],
        ["버전", "일자", "내용", "작성"], [
            ["v1.0", "2024-11-20", "제정", "정보보호파트"],
            ["v1.1", "2025-06-30", "로그 보관기간 2년 → 3년, 복구 시험 주기 반기 → 분기", "정보보호파트"],
        ])
    body(d, [
        ("Heading 1", "제1장 총칙"),
        ("Heading 2", "제1조(목적)"),
        ("Normal", "이 지침은 정보보호 정책(C-POL-01)과 「개인정보의 안전성 확보조치 기준」(개인정보보호위원회 고시 제2023-6호)에 "
                   "따라 감사 로그의 기록·보관, 이상 행위 탐지, 백업과 재해 복구에 관한 기준을 정한다."),
        ("Heading 2", "제2조(적용 범위)"),
        ("Normal", "이 지침은 회사의 모든 AWS 계정과 피플클라우드 운영 환경에 적용한다."),
        ("Heading 1", "제2장 로그 관리"),
        ("Heading 2", "제3조(감사 로그)"),
        ("Normal", "① 모든 AWS 계정은 CloudTrail을 전 리전 대상으로 활성화하여 관리 이벤트(읽기·쓰기)를 빠짐없이 기록한다."),
        ("Normal", "② 감사 로그는 로그 파일 무결성 검증을 켜서 위·변조 여부를 확인할 수 있도록 한다."),
        ("Normal", "③ 감사 로그는 3년 이상 보관한다."),
        ("Heading 2", "제4조(이상 행위 탐지)"),
        ("Normal", "모든 AWS 계정에서 GuardDuty를 활성화하고, 정보보호파트는 탐지 결과를 매일 확인한다."),
        ("Heading 1", "제3장 백업과 재해 복구"),
        ("Heading 2", "제5조(백업)"),
        ("Normal", "① 중요도 '상' 데이터베이스는 자동 백업을 사용하고 백업 보관기간을 14일 이상으로 설정한다."),
        ("Normal", "② 중요도 '상' 자원이 있는 계정은 백업 사본을 다른 리전에 복사하여 보관한다."),
        ("Normal", "③ 백업 복구 시험은 분기 1회 이상 실시하고 결과를 기록한다."),
        ("Heading 2", "제6조(재해 복구 훈련)"),
        ("Normal", "재해 복구 훈련은 연 1회 이상 실시하고 결과와 개선사항을 CISO에게 보고한다."),
        ("Heading 1", "부칙"),
        ("Normal", "1. 이 지침은 2025년 7월 15일부터 시행한다."),
    ])
    return d


def doc_pip():
    d = new_doc("개인정보 내부 관리계획", [
        ("문서번호", "C-PIP-01"), ("버전", "v2.1"), ("시행일", "2026-10-01"), ("승인자", "CISO"),
        ("소관부서", "정보보호파트(개인정보보호)"), ("보안등급", "사내한정")],
        ["버전", "일자", "내용", "작성"], [
            ["v1.0", "2024-12-01", "수립", "정보보호파트"],
            ["v2.0", "2025-11-10", "개인정보 처리 위탁 현황 갱신, 교육 계획 반영", "정보보호파트"],
            ["v2.1", "2026-09-22", "개정 고시(제2026-9호) 반영 — 접속기록 점검 주기·방법 명시", "정보보호파트"],
        ], company_line="C사 · 개인정보 보호책임자")
    body(d, [
        ("Heading 1", "제1장 총칙"),
        ("Heading 2", "제1조(목적)"),
        ("Normal", "이 계획은 「개인정보 보호법」 제29조와 「개인정보의 안전성 확보조치 기준」(개인정보보호위원회 고시 제2026-9호)에 "
                   "따라 회사가 처리하는 고객사 임직원 개인정보의 안전성 확보에 필요한 사항을 정한다."),
        ("Heading 2", "제2조(개인정보 처리 현황)"),
        ("Normal", "회사는 고객사로부터 급여 계산과 인사 관리를 위탁받아 고객사 임직원의 성명, 사번, 연락처, 계좌번호, 급여 정보를 "
                   "처리한다."),
        ("Heading 1", "제2장 접근 통제와 접속기록"),
        ("Heading 2", "제3조(접근 권한)"),
        ("Normal", "개인정보처리시스템의 접근 권한은 통합 보안관리 규정 제3장에 따라 부여·변경·말소하고 그 기록을 3년간 보관한다."),
        ("Heading 2", "제4조(접속기록 보관과 점검)"),
        ("Normal", "① 개인정보처리시스템의 접속기록은 2년 이상 보관한다."),
        ("Normal", "② 개인정보보호 담당자는 분기마다 1회 이상 접속기록을 점검하여 비정상 조회·대량 다운로드 여부를 확인하고, "
                   "그 결과를 개인정보 보호책임자에게 보고한다."),
        ("Heading 1", "제3장 암호화와 기타 조치"),
        ("Heading 2", "제5조(암호화)"),
        ("Normal", "계좌번호 등 고유식별정보에 준하는 정보는 항목 단위로 암호화하며, 저장소 암호화는 통합 보안관리 규정 제5장에 따른다."),
        ("Heading 2", "제6조(교육)"),
        ("Normal", "개인정보취급자에게 연 1회 이상 개인정보 보호 교육을 실시한다."),
        ("Heading 1", "부칙"),
        ("Normal", "1. 이 계획은 2026년 10월 1일부터 시행한다."),
    ])
    return d


DOC_FILES = [
    ("C사_정보보호정책_v1.2.docx", "C-POL-01", doc_policy),
    ("C사_통합보안관리규정_v3.0.docx", "C-REG-02", doc_regulation),
    ("C사_계정관리절차_v1.1.docx", "C-PRC-03", doc_procedure),
    ("C사_로그및백업관리지침_v1.1.docx", "C-GDL-07", doc_logging),
    ("C사_개인정보내부관리계획_v2.1.docx", "C-PIP-01", doc_pip),
]


def write_docs() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for name, _, fn in DOC_FILES:
        fn().save(DOCS / name)

# ───────────────────────────── scope / README ─────────────────────────────


def write_scope() -> None:
    scope = {
        "organization": "C사 (가상 B2B SaaS — HR·급여 클라우드 '피플클라우드', 임직원 약 300명)",
        "as_of": "2026-11-02",
        "facts": {
            "scope.has_information_systems": {"value": True, "basis": "정보보호 정책 제2조"},
            "scope.has_aws_accounts": {"value": True, "basis": "AWS 계정 3개 (운영·개발·보안), 샌드박스 1개는 범위 제외"},
            "scope.aws_iam_users_with_console_password": {"value": True, "basis": "계정관리대장 — 콘솔 사용 계정 존재"},
            "scope.service_has_customer_login": {"value": True, "basis": "고객사 관리자·직원이 피플클라우드에 로그인"},
            "scope.uses_cognito": {"value": True, "basis": "피플클라우드 로그인에 Amazon Cognito 사용 (c-prod)"},
        },
        "aws_accounts": [
            {"account_id": PROD, "alias": "c-prod", "label": "운영", "in_scope": True},
            {"account_id": DEV, "alias": "c-dev", "label": "개발·스테이징", "in_scope": True},
            {"account_id": SEC, "alias": "c-sec", "label": "보안·로그 보관", "in_scope": True},
            {"account_id": SBX, "alias": "c-sandbox", "label": "R&D 샌드박스 (개인정보 처리 없음, 인증 범위 제외)",
             "in_scope": False},
        ],
        "policy_documents": [{"file": f"docs/{n}", "doc_id": i} for n, i, _ in DOC_FILES],
        "evidence": [
            {"file": "evidence/직원가입_비밀번호_화면_2026-10-28.png", "kind": "screen_capture",
             "relates_to": "AR-2.5.4-05", "captured_at": "2026-10-28"},
            {"file": "evidence/AWS_계정관리대장_2026-10-31.xlsx", "kind": "account_list"},
            {"file": "evidence/인사명부_2026-11-01.xlsx", "kind": "hr_roster"},
            {"file": "evidence/특수권한자현황_2026-10.xlsx", "kind": "privileged_list"},
            {"file": "evidence/접근권한검토_결과.xlsx", "kind": "access_review_log"},
            {"file": "evidence/정보자산목록_2026-10-15.xlsx", "kind": "asset_list"},
            {"file": "evidence/암호키관리대장.xlsx", "kind": "key_ledger"},
            {"file": "evidence/접속기록점검_2026.xlsx", "kind": "access_log_review"},
            {"file": "evidence/백업복구시험_2026.xlsx", "kind": "restore_test_log"},
            {"file": "evidence/재해복구훈련_결과.xlsx", "kind": "dr_drill_log"},
            {"file": "evidence/정보보호위원회_회의록목록.xlsx", "kind": "committee_log"},
            {"file": "evidence/내부감사_이력.xlsx", "kind": "internal_audit_log"},
            {"file": "evidence/개선조치관리대장_2026.xlsx", "kind": "improvement_tracker"},
        ],
    }
    head = ("# C사 진단 범위 사실 (Scope facts). 사람이 확인해 입력하는 값이며, 근거(basis)를 함께 적는다.\n"
            "# 여기 없는 사실은 Scope Engine이 UNKNOWN 으로 본다.\n")
    text = yaml.safe_dump(scope, allow_unicode=True, sort_keys=False, width=200)
    (SC / "scope.yaml").write_text(head + text, encoding="utf-8")
    yaml.safe_load((SC / "scope.yaml").read_text(encoding="utf-8"))


README = """# 시나리오: c-corp-eval (C사, 가상 HR·급여 SaaS)

C사는 고객사 인사·급여 업무를 대행하는 B2B SaaS **피플클라우드**를 운영하는 가상 기업입니다 (임직원 약 300명).
고객사 관리자와 고객사 직원이 피플클라우드에 로그인하며, 인증은 Amazon Cognito 사용자 풀로 처리합니다.
서비스는 AWS 서울 리전(ap-northeast-2)에서 운영하고, 재해 대비 사본은 오사카 리전(ap-northeast-3)에 둡니다.

**평가용 시나리오**입니다. 데이터는 `python scripts/build_c_corp_eval.py`로 다시 만들 수 있습니다.
모든 회사·인물·계정 정보는 가상입니다 (계정 ID 8010000000xx, 도메인 .example, 이름은 마스킹).

| 폴더 | 내용 |
|---|---|
| docs/ | 정보보호 정책(C-POL-01), 통합 보안관리 규정(C-REG-02), 계정관리 절차(C-PRC-03), 로그 및 백업 관리지침(C-GDL-07), 개인정보 내부 관리계획(C-PIP-01) |
| evidence/ | 직원 가입 화면 캡처, AWS 계정관리대장, 인사명부, 특수권한자 현황, 접근권한 검토 결과, 정보자산 목록, 암호키 관리대장, 접속기록 점검, 백업 복구 시험, 재해 복구 훈련 결과, 정보보호위원회 회의 목록, 내부감사 이력, 개선조치 관리대장 |
| aws-snapshot/ | AWS 계정 4개의 수집 결과 (live 수집기와 같은 형식). 수집 상태는 manifest.json 참고 |
| scope.yaml | 진단 범위 사실과 근거, 제출 문서·증적 목록 |

AWS 계정

| 계정 ID | 별칭 | 용도 | 인증 범위 |
|---|---|---|---|
| 801000000001 | c-prod | 피플클라우드 운영 | 포함 |
| 801000000002 | c-dev | 개발·스테이징 | 포함 |
| 801000000003 | c-sec | 보안 관제·통합 감사 로그 보관 | 포함 |
| 801000000009 | c-sandbox | R&D 샌드박스 (개인정보 처리 없음) | 제외 |
"""


def main() -> None:
    if SC.exists():
        for sub in ("docs", "evidence", "aws-snapshot"):
            shutil.rmtree(SC / sub, ignore_errors=True)
    SC.mkdir(parents=True, exist_ok=True)
    write_docs()
    write_evidence()
    write_snapshot()
    write_scope()
    (SC / "README.md").write_text(README, encoding="utf-8")
    print("c-corp-eval 시나리오 생성 완료", file=sys.stderr)


if __name__ == "__main__":
    main()
