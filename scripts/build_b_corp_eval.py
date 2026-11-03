"""b-corp-eval 시나리오(B사, 가상 온라인 교육 플랫폼)를 처음부터 만든다. 다시 실행해도 같은 내용이 나온다.

    python scripts/build_b_corp_eval.py

만드는 것
- scope.yaml, README.md
- docs/      B사 규정 문서 4종 (docx)
- evidence/  B사가 보관하는 관리대장·기록 (xlsx)
- aws-snapshot/  manifest.json + 계정별 수집 결과 (live 수집기와 같은 형식)

모든 회사·인물·계정·IP 정보는 가상이다 (계정 ID 444444444444 등, 문서용 IP 대역, 도메인 .example).
사람 이름은 마스킹(황○○)해서만 쓴다.
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import docx
import yaml
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "b-corp-eval"
SNAP = SC / "aws-snapshot"
DOCS = SC / "docs"
EV = SC / "evidence"

AS_OF = "2026-11-02"
COLLECTED_AT = "2026-11-01T23:10:00+00:00"
FIXED_TS = datetime(2026, 11, 1, 9, 0, 0, tzinfo=timezone.utc)
REGION = "ap-northeast-2"

PROD, DEV, SECLOG, SANDBOX = "444444444444", "555555555555", "666666666666", "777777777777"
ALIAS = {PROD: "b-prod", DEV: "b-dev", SECLOG: "b-seclog", SANDBOX: "b-sandbox"}
LABEL = {PROD: "운영", DEV: "개발", SECLOG: "보안로그", SANDBOX: "샌드박스(사내 교육 실습용)"}
IN_SCOPE = {PROD: True, DEV: True, SECLOG: True, SANDBOX: False}
ACCOUNTS = (PROD, DEV, SECLOG, SANDBOX)

HQ_ADMIN_NET = "192.0.2.32/28"
VPN_NET = "10.250.0.0/24"


def jdump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# IAM
# ══════════════════════════════════════════════════════════════════════════

CR_HEADER = ["user", "arn", "user_creation_time", "password_enabled", "password_last_used", "password_last_changed",
             "password_next_rotation", "mfa_active", "access_key_1_active", "access_key_1_last_rotated",
             "access_key_1_last_used_date", "access_key_1_last_used_region", "access_key_1_last_used_service",
             "access_key_2_active", "access_key_2_last_rotated", "access_key_2_last_used_date",
             "access_key_2_last_used_region", "access_key_2_last_used_service", "cert_1_active",
             "cert_1_last_rotated", "cert_2_active", "cert_2_last_rotated"]

AWS_ADMIN = "arn:aws:iam::aws:policy/AdministratorAccess"
AWS_POWER = "arn:aws:iam::aws:policy/PowerUserAccess"
AWS_READ = "arn:aws:iam::aws:policy/ReadOnlyAccess"
AWS_ATHENA = "arn:aws:iam::aws:policy/AmazonAthenaFullAccess"
AWS_AUDIT = "arn:aws:iam::aws:policy/SecurityAudit"


def U(name, created, console, *, used=None, changed=None, mfa=False, groups=(), key=False, key_used=None,
      key_rotated=None, lp=None, reset=False, direct=(), inline=None):
    return dict(name=name, created=created, console=console, used=used, changed=changed, mfa=mfa,
                groups=list(groups), key=key, key_used=key_used, key_rotated=key_rotated or created,
                lp=lp, reset=reset, direct=list(direct), inline=inline)


USERS: dict[str, list[dict]] = {
    PROD: [
        U("sec-hwang", "2025-03-03T00:30:00+00:00", True, used="2026-10-31T02:14:00+00:00",
          changed="2026-07-10T05:20:00+00:00", mfa=True, groups=["Admins"], lp="2025-03-03T00:30:04+00:00"),
        U("ops-yang", "2025-04-14T01:00:00+00:00", True, used="2026-10-30T07:41:00+00:00",
          changed="2026-09-15T01:05:00+00:00", mfa=True, groups=["Operators"], lp="2025-04-14T01:00:03+00:00"),
        U("dev-kang", "2025-05-06T02:00:00+00:00", True, used="2026-10-29T09:12:00+00:00",
          changed="2026-05-20T03:30:00+00:00", mfa=True, groups=["Developers"], lp="2025-05-06T02:00:05+00:00"),
        U("dev-moon", "2026-08-03T00:40:00+00:00", True, used="2026-10-27T06:02:00+00:00",
          changed="2026-08-20T04:11:00+00:00", mfa=False, groups=["Developers"], lp="2026-08-03T00:40:02+00:00"),
        U("data-oh", "2025-09-01T01:00:00+00:00", True, used="2026-10-22T08:30:00+00:00",
          changed="2026-08-01T02:45:00+00:00", mfa=True, groups=["DataAnalysts"], lp="2025-09-01T01:00:04+00:00",
          inline={"PolicyName": "athena-adhoc-results",
                  "PolicyDocument": {"Version": "2012-10-17", "Statement": [{
                      "Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                      "Resource": ["arn:aws:s3:::b-prod-athena-results", "arn:aws:s3:::b-prod-athena-results/*"]}]}}),
        U("ops-shin", "2025-07-21T00:20:00+00:00", True, used="2026-10-23T10:05:00+00:00",
          changed="2026-08-11T01:15:00+00:00", mfa=True, groups=["Operators"], key=True,
          key_used="2026-10-24T13:40:00+00:00", key_rotated="2026-02-02T00:00:00+00:00",
          lp="2025-07-21T00:20:03+00:00"),
        U("cs-lim", "2026-01-12T00:10:00+00:00", True, used="2026-10-28T05:50:00+00:00",
          changed="2026-09-02T00:35:00+00:00", mfa=True, groups=["CSOps"], lp="2026-01-12T00:10:02+00:00"),
        U("ops-yoo", "2026-10-12T00:00:00+00:00", True, used="2026-10-30T01:22:00+00:00",
          changed="2026-10-12T00:00:04+00:00", mfa=True, groups=["Operators"], lp="2026-10-12T00:00:04+00:00"),
        U("svc-deploy", "2025-06-02T00:00:00+00:00", False, groups=["CICD"], key=True,
          key_used="2026-11-01T11:20:00+00:00", key_rotated="2026-06-01T00:00:00+00:00"),
        U("vendor-lms", "2026-09-01T00:00:00+00:00", True, used="2026-10-20T08:10:00+00:00",
          changed="2026-10-01T02:00:00+00:00", mfa=True, groups=["Maintenance"], lp="2026-09-01T00:00:03+00:00"),
        U("vendor-old", "2026-01-05T00:00:00+00:00", False, groups=["Maintenance"]),
    ],
    DEV: [
        U("dev-kang", "2025-05-06T02:10:00+00:00", True, used="2026-10-30T04:12:00+00:00",
          changed="2026-09-01T00:50:00+00:00", mfa=True, groups=["Developers"], lp="2025-05-06T02:10:04+00:00"),
        U("test", "2026-03-02T00:00:00+00:00", True, used="2026-10-31T03:33:00+00:00",
          changed="2026-10-05T06:00:00+00:00", mfa=True, groups=["Developers"], lp="2026-03-02T00:00:03+00:00"),
        U("svc-ci", "2025-10-13T00:00:00+00:00", False, groups=["CICD-Dev"], key=True,
          key_used="2026-08-15T02:00:00+00:00", key_rotated="2025-10-13T00:00:00+00:00"),
    ],
    SECLOG: [
        U("sec-hwang", "2025-03-03T00:40:00+00:00", True, used="2026-10-28T01:00:00+00:00",
          changed="2026-08-20T02:10:00+00:00", mfa=True, groups=["Admins"], lp="2025-03-03T00:40:03+00:00"),
        U("log-auditor", "2026-02-02T00:00:00+00:00", True, used="2026-09-10T06:30:00+00:00",
          changed="2026-09-10T06:25:00+00:00", mfa=True, groups=["Auditors"], lp="2026-02-02T00:00:04+00:00"),
    ],
    SANDBOX: [
        U("admin", "2026-04-01T00:00:00+00:00", True, used="2026-10-15T05:00:00+00:00",
          changed="2026-04-01T00:00:03+00:00", mfa=False, direct=[AWS_ADMIN], lp="2026-04-01T00:00:03+00:00"),
        U("trainee01", "2026-04-01T00:05:00+00:00", True, used="2026-06-10T05:00:00+00:00",
          changed="2026-04-01T00:05:02+00:00", mfa=False, groups=["Trainees"], lp="2026-04-01T00:05:02+00:00"),
    ],
}

ROOT_MFA = {PROD: True, DEV: True, SECLOG: True, SANDBOX: False}
ROOT_USED = {PROD: "2026-02-11T01:00:00+00:00", DEV: "N/A", SECLOG: "N/A", SANDBOX: "2026-04-01T00:00:00+00:00"}
ROOT_CREATED = {PROD: "2025-02-17T00:00:00+00:00", DEV: "2025-02-17T00:05:00+00:00",
                SECLOG: "2025-02-17T00:10:00+00:00", SANDBOX: "2026-03-30T00:00:00+00:00"}

PASSWORD_POLICY = {
    PROD: {"MinimumPasswordLength": 9, "RequireSymbols": False, "RequireNumbers": True,
           "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True,
           "AllowUsersToChangePassword": True, "ExpirePasswords": True, "MaxPasswordAge": 120,
           "PasswordReusePrevention": 5, "HardExpiry": False},
    DEV: {"MinimumPasswordLength": 8, "RequireSymbols": True, "RequireNumbers": True,
          "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True,
          "AllowUsersToChangePassword": True, "ExpirePasswords": True, "MaxPasswordAge": 120,
          "PasswordReusePrevention": 5, "HardExpiry": False},
    SECLOG: {"MinimumPasswordLength": 12, "RequireSymbols": True, "RequireNumbers": True,
             "RequireUppercaseCharacters": True, "RequireLowercaseCharacters": True,
             "AllowUsersToChangePassword": True, "ExpirePasswords": True, "MaxPasswordAge": 90,
             "PasswordReusePrevention": 24, "HardExpiry": False},
    SANDBOX: None,
}

GROUP_POLICIES = {
    "Admins": [AWS_ADMIN],
    "Operators": [AWS_READ, "arn:aws:iam::{acct}:policy/OpsSupport"],
    "Developers": [AWS_POWER],
    "DataAnalysts": [AWS_ATHENA],
    "CSOps": [AWS_READ],
    "CICD": ["arn:aws:iam::{acct}:policy/DeployPipeline"],
    "CICD-Dev": [AWS_POWER],
    "Maintenance": [AWS_READ],
    "Auditors": [AWS_AUDIT],
    "Trainees": [AWS_READ],
}

CUSTOM_POLICIES = {
    "OpsSupport": {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["ec2:*", "rds:Describe*", "cloudwatch:*", "logs:*"], "Resource": "*"}]},
    "DeployPipeline": {"Version": "2012-10-17", "Statement": [
        {"Sid": "PipelineAll", "Effect": "Allow", "Action": "*", "Resource": "*"}]},
}


def credential_report(acct: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CR_HEADER)
    na = "N/A"
    w.writerow(["<root_account>", f"arn:aws:iam::{acct}:root", ROOT_CREATED[acct], "not_supported",
                ROOT_USED[acct], "not_supported", na, str(ROOT_MFA[acct]).lower(), "false", na, na, na, na,
                "false", na, na, na, na, "false", na, "false", na])
    for u in sorted(USERS[acct], key=lambda x: x["name"]):
        key = u["key"]
        w.writerow([u["name"], f"arn:aws:iam::{acct}:user/{u['name']}", u["created"],
                    str(u["console"]).lower(),
                    (u["used"] or "no_information") if u["console"] else na,
                    u["changed"] if u["console"] else na, na, str(u["mfa"]).lower(),
                    str(key).lower(), u["key_rotated"] if key else na, u["key_used"] if key else na,
                    REGION if key else na, ("s3" if key else na),
                    "false", na, na, na, na, "false", na, "false", na])
    return buf.getvalue()


def login_profiles(acct: str) -> dict:
    return {u["name"]: {"CreateDate": u["lp"], "PasswordResetRequired": u["reset"]}
            for u in sorted(USERS[acct], key=lambda x: x["name"]) if u["console"]}


def authorization(acct: str) -> dict:
    used = sorted({g for u in USERS[acct] for g in u["groups"]})

    def pol(arn: str) -> dict:
        arn = arn.format(acct=acct)
        return {"PolicyName": arn.rsplit("/", 1)[1], "PolicyArn": arn}

    users = []
    for u in sorted(USERS[acct], key=lambda x: x["name"]):
        users.append({
            "UserName": u["name"],
            "UserId": "AIDA" + (acct[:3] + u["name"].upper().replace("-", "")).ljust(17, "X")[:17],
            "Arn": f"arn:aws:iam::{acct}:user/{u['name']}", "Path": "/", "CreateDate": u["created"],
            "GroupList": u["groups"], "AttachedManagedPolicies": [pol(p) for p in u["direct"]],
            "UserPolicyList": [u["inline"]] if u["inline"] else [], "Tags": [],
        })
    groups = [{"GroupName": g, "GroupId": "AGPA" + (acct[:3] + g.upper().replace("-", "")).ljust(17, "X")[:17],
               "Arn": f"arn:aws:iam::{acct}:group/{g}", "Path": "/",
               "AttachedManagedPolicies": [pol(p) for p in GROUP_POLICIES[g]], "GroupPolicyList": []}
              for g in used]
    custom_names = sorted({p.rsplit("/", 1)[1] for g in used for p in GROUP_POLICIES[g] if "{acct}" in p})
    custom = [{"PolicyName": n, "PolicyId": "ANPA" + (acct[:3] + n.upper()).ljust(17, "X")[:17],
               "Arn": f"arn:aws:iam::{acct}:policy/{n}", "Path": "/", "DefaultVersionId": "v2",
               "AttachmentCount": 1, "IsAttachable": True,
               "PolicyVersionList": [{"VersionId": "v2", "IsDefaultVersion": True, "Document": CUSTOM_POLICIES[n],
                                      "CreateDate": "2026-03-10T00:00:00+00:00"}]}
              for n in custom_names]
    return {"UserDetailList": users, "GroupDetailList": groups, "RoleDetailList": [], "Policies": custom}


# ══════════════════════════════════════════════════════════════════════════
# 네트워크
# ══════════════════════════════════════════════════════════════════════════

def perm(proto, lo=None, hi=None, cidrs=(), groups=(), desc=""):
    p: dict = {"IpProtocol": proto}
    if proto != "-1":
        p["FromPort"], p["ToPort"] = lo, (hi if hi is not None else lo)
    p["IpRanges"] = [{"CidrIp": c, **({"Description": desc} if desc else {})} for c in cidrs if ":" not in c]
    p["Ipv6Ranges"] = [{"CidrIpv6": c, **({"Description": desc} if desc else {})} for c in cidrs if ":" in c]
    p["UserIdGroupPairs"] = [{"GroupId": g, **({"Description": desc} if desc else {})} for g in groups]
    p["PrefixListIds"] = []
    return p


EGRESS_ALL = [perm("-1", cidrs=["0.0.0.0/0"])]


def sg(gid, name, vpc, acct, ingress, egress=None, desc=""):
    return {"GroupId": gid, "GroupName": name, "VpcId": vpc, "OwnerId": acct, "Description": desc or name,
            "IpPermissions": ingress, "IpPermissionsEgress": EGRESS_ALL if egress is None else egress,
            "Tags": [] if name == "default" else [{"Key": "Name", "Value": name}]}


def subnet(sid, vpc, cidr, name, az, public=False):
    return {"SubnetId": sid, "VpcId": vpc, "CidrBlock": cidr, "AvailabilityZone": az, "State": "available",
            "MapPublicIpOnLaunch": public, "Tags": [{"Key": "Name", "Value": name}]}


def rt(rid, vpc, vpc_cidr, subnets, default=None, main=False, name=""):
    routes = [{"DestinationCidrBlock": vpc_cidr, "GatewayId": "local", "State": "active", "Origin": "CreateRouteTable"}]
    if default:
        key = "NatGatewayId" if default.startswith("nat-") else "GatewayId"
        routes.append({"DestinationCidrBlock": "0.0.0.0/0", key: default, "State": "active", "Origin": "CreateRoute"})
    assoc = [{"RouteTableAssociationId": f"rtbassoc-{rid[4:]}{i}", "RouteTableId": rid, "SubnetId": s, "Main": False}
             for i, s in enumerate(subnets)]
    if main:
        assoc.append({"RouteTableAssociationId": f"rtbassoc-{rid[4:]}m", "RouteTableId": rid, "Main": True})
    return {"RouteTableId": rid, "VpcId": vpc, "Routes": routes, "Associations": assoc,
            "Tags": [{"Key": "Name", "Value": name}] if name else []}


def karn(acct, kid):
    return f"arn:aws:kms:{REGION}:{acct}:key/{kid}"


K_LMS = "4d4d4d4d-1111-4a00-9000-00000000a001"
K_PAY = "4d4d4d4d-1111-4a00-9000-00000000a002"
K_LEGACY = "4d4d4d4d-1111-4a00-9000-00000000a003"
K_PROD_EBS = "4d4d4d4d-1111-4a00-9000-0000000000e1"
K_PROD_RDS = "4d4d4d4d-1111-4a00-9000-0000000000e2"
K_DEV_APP = "5e5e5e5e-2222-4b00-9000-00000000b001"
K_DEV_EBS = "5e5e5e5e-2222-4b00-9000-0000000000e1"
K_SEC = "6f6f6f6f-3333-4c00-9000-00000000c001"


def rds(name, engine, public, sgs, subnets, enc, key, retention, cls="db.r6g.large"):
    d = {"DBInstanceIdentifier": name, "DBInstanceClass": cls, "Engine": engine, "DBInstanceStatus": "available",
         "PubliclyAccessible": public, "StorageEncrypted": enc, "BackupRetentionPeriod": retention,
         "MultiAZ": not name.startswith("lms-dev"),
         "VpcSecurityGroups": [{"VpcSecurityGroupId": g, "Status": "active"} for g in sgs],
         "DBSubnetGroup": {"DBSubnetGroupName": f"{name}-subnets", "SubnetGroupStatus": "Complete",
                           "Subnets": [{"SubnetIdentifier": s, "SubnetStatus": "Active"} for s in subnets]}}
    if enc:
        d["KmsKeyId"] = key
    return d


def network(acct: str) -> dict:
    if acct == PROD:
        vpc, cidr = "vpc-0d4lms000000001", "10.40.0.0/16"
        alb, app, bastion = "sg-0d4alb000000001", "sg-0d4app000000001", "sg-0d4bastion00001"
        db, report, enc = "sg-0d4db0000000001", "sg-0d4report000001", "sg-0d4encoder00001"
        return {
            "sg": [
                sg("sg-0d4default00001", "default", vpc, acct, [], [], "default VPC security group"),
                sg(alb, "lms-prod-alb", vpc, acct, [perm("tcp", 443, cidrs=["0.0.0.0/0", "::/0"]),
                                                     perm("tcp", 80, cidrs=["0.0.0.0/0", "::/0"])]),
                sg(app, "lms-prod-app", vpc, acct, [perm("tcp", 8080, groups=[alb]),
                                                     perm("tcp", 22, groups=[bastion])]),
                sg(bastion, "lms-prod-bastion", vpc, acct, [
                    perm("tcp", 22, cidrs=[HQ_ADMIN_NET], desc="HQ IT"),
                    perm("tcp", 22, cidrs=[VPN_NET], desc="SSL-VPN"),
                    perm("tcp", 3389, cidrs=["192.0.2.0/24"], desc="HQ office")]),
                sg(db, "lms-prod-db", vpc, acct, [
                    perm("tcp", 3306, groups=[app], desc="app"),
                    perm("tcp", 3306, cidrs=[VPN_NET], desc="DBA via VPN")]),
                sg(report, "lms-prod-report-db", vpc, acct, [
                    perm("tcp", 5432, groups=[app], desc="app"),
                    perm("tcp", 5432, cidrs=["203.0.113.77/32"], desc="BI SaaS")]),
                sg(enc, "lms-prod-encoder", vpc, acct, [perm("tcp", 8000, groups=[app])]),
            ],
            "subnet": [
                subnet("subnet-0d4pub00000a", vpc, "10.40.0.0/24", "lms-prod-public-a", "ap-northeast-2a", True),
                subnet("subnet-0d4pub00000c", vpc, "10.40.1.0/24", "lms-prod-public-c", "ap-northeast-2c", True),
                subnet("subnet-0d4app00000a", vpc, "10.40.10.0/24", "lms-prod-app-a", "ap-northeast-2a"),
                subnet("subnet-0d4app00000c", vpc, "10.40.11.0/24", "lms-prod-app-c", "ap-northeast-2c"),
                subnet("subnet-0d4data0000a", vpc, "10.40.20.0/24", "lms-prod-data-a", "ap-northeast-2a"),
                subnet("subnet-0d4data0000c", vpc, "10.40.21.0/24", "lms-prod-data-c", "ap-northeast-2c"),
            ],
            "rt": [
                rt("rtb-0d4main0000001", vpc, cidr, [], "nat-0d4lms00000000001", main=True, name="lms-prod-main"),
                rt("rtb-0d4public00001", vpc, cidr, ["subnet-0d4pub00000a", "subnet-0d4pub00000c"],
                   "igw-0d4lms0000000001", name="lms-prod-public"),
                rt("rtb-0d4data000001", vpc, cidr, ["subnet-0d4data0000a", "subnet-0d4data0000c"],
                   None, name="lms-prod-data"),
            ],
            "rds": [
                rds("lms-prod-db", "mysql", False, [db], ["subnet-0d4data0000a", "subnet-0d4data0000c"],
                    True, karn(PROD, K_LMS), 7),
                rds("pay-prod-db", "mysql", False, [db], ["subnet-0d4data0000a", "subnet-0d4data0000c"],
                    True, karn(PROD, K_PAY), 35),
                rds("lms-prod-report", "postgres", True, [report], ["subnet-0d4data0000a", "subnet-0d4data0000c"],
                    True, karn(PROD, K_LMS), 1, cls="db.t4g.large"),
            ],
        }
    if acct == DEV:
        vpc, cidr = "vpc-0e5dev000000001", "10.50.0.0/16"
        alb, app, db = "sg-0e5alb000000001", "sg-0e5app000000001", "sg-0e5db0000000001"
        return {
            "sg": [
                sg("sg-0e5default00001", "default", vpc, acct, [], [], "default VPC security group"),
                sg(alb, "lms-dev-alb", vpc, acct, [perm("tcp", 443, cidrs=["0.0.0.0/0"]),
                                                    perm("tcp", 80, cidrs=["0.0.0.0/0"])]),
                sg(app, "lms-dev-app", vpc, acct, [
                    perm("tcp", 8080, groups=[alb]),
                    perm("tcp", 22, cidrs=["0.0.0.0/0"], desc="temp - outsourcing dev")]),
                sg("sg-0e5encleg00001", "dev-encoder-legacy", vpc, acct, [
                    perm("tcp", 23, cidrs=[cidr], desc="encoder appliance mgmt"),
                    perm("tcp", 8000, groups=[app])]),
                sg(db, "lms-dev-db", vpc, acct, [perm("tcp", 3306, groups=[app])]),
            ],
            "subnet": [
                subnet("subnet-0e5pub00000a", vpc, "10.50.0.0/24", "lms-dev-public-a", "ap-northeast-2a", True),
                subnet("subnet-0e5app00000a", vpc, "10.50.10.0/24", "lms-dev-app-a", "ap-northeast-2a"),
                subnet("subnet-0e5data0000a", vpc, "10.50.20.0/24", "lms-dev-data-a", "ap-northeast-2a"),
                subnet("subnet-0e5data0000c", vpc, "10.50.21.0/24", "lms-dev-data-c", "ap-northeast-2c"),
            ],
            "rt": [
                rt("rtb-0e5main0000001", vpc, cidr, [], None, main=True, name="lms-dev-main"),
                rt("rtb-0e5public00001", vpc, cidr, ["subnet-0e5pub00000a"], "igw-0e5dev00000000001",
                   name="lms-dev-public"),
                rt("rtb-0e5app0000001", vpc, cidr, ["subnet-0e5app00000a"], "nat-0e5dev00000000001",
                   name="lms-dev-app"),
            ],
            "rds": [
                rds("lms-dev-db", "mysql", False, [db], ["subnet-0e5data0000a", "subnet-0e5data0000c"],
                    False, None, 1, cls="db.t4g.medium"),
            ],
        }
    if acct == SECLOG:
        vpc, cidr = "vpc-0f6sec000000001", "10.60.0.0/16"
        return {
            "sg": [
                sg("sg-0f6default00001", "default", vpc, acct, [], [], "default VPC security group"),
                sg("sg-0f6tools000001", "seclog-tools", vpc, acct, [
                    perm("tcp", 22, cidrs=[VPN_NET], desc="SSL-VPN"),
                    perm("tcp", 443, cidrs=["10.0.0.0/8"], desc="internal dashboards")]),
            ],
            "subnet": [subnet("subnet-0f6priv0000a", vpc, "10.60.10.0/24", "seclog-private-a", "ap-northeast-2a")],
            "rt": [rt("rtb-0f6main0000001", vpc, cidr, [], None, main=True, name="seclog-main")],
            "rds": [],
        }
    vpc, cidr = "vpc-0a7sbx000000001", "10.70.0.0/16"
    return {
        "sg": [
            sg("sg-0a7default00001", "default", vpc, acct, [perm("-1", groups=["sg-0a7default00001"])],
               desc="default VPC security group"),
            sg("sg-0a7lab00000001", "sandbox-lab", vpc, acct, [perm("tcp", 22, cidrs=["0.0.0.0/0"]),
                                                               perm("tcp", 21, cidrs=["0.0.0.0/0"])]),
        ],
        "subnet": [subnet("subnet-0a7pub00000a", vpc, "10.70.0.0/24", "sandbox-public-a", "ap-northeast-2a", True)],
        "rt": [rt("rtb-0a7main0000001", vpc, cidr, [], "igw-0a7sbx0000000001", main=True, name="sandbox-main")],
        "rds": [],
    }


# ══════════════════════════════════════════════════════════════════════════
# 암호화
# ══════════════════════════════════════════════════════════════════════════

def kms(acct: str) -> list[dict]:
    def k(kid, alias, manager, state, rotation, desc, created):
        return {"KeyId": kid, "Arn": karn(acct, kid), "KeyManager": manager, "KeyState": state,
                "Enabled": state == "Enabled", "KeySpec": "SYMMETRIC_DEFAULT", "KeyUsage": "ENCRYPT_DECRYPT",
                "CreationDate": created, "Aliases": [alias], "Description": desc, "KeyRotationEnabled": rotation}
    return {
        PROD: [
            k(K_LMS, "alias/lms-prod", "CUSTOMER", "Enabled", True, "LMS 운영 데이터 암호화", "2025-03-10T00:00:00+00:00"),
            k(K_PAY, "alias/pay-prod", "CUSTOMER", "Enabled", False, "결제 DB 암호화", "2025-08-18T00:00:00+00:00"),
            k(K_LEGACY, "alias/legacy-2024", "CUSTOMER", "Disabled", False, "구 LMS 이관 데이터 (사용 중지)",
              "2024-11-04T00:00:00+00:00"),
            k(K_PROD_EBS, "alias/aws/ebs", "AWS", "Enabled", True, "Default key that protects my EBS volumes when no other key is defined",
              "2025-03-10T00:00:00+00:00"),
            k(K_PROD_RDS, "alias/aws/rds", "AWS", "Enabled", True, "Default key that protects my RDS database volumes when no other key is defined",
              "2025-03-10T00:00:00+00:00"),
        ],
        DEV: [
            k(K_DEV_APP, "alias/dev-app", "CUSTOMER", "Enabled", True, "개발 환경 애플리케이션 데이터", "2026-06-22T00:00:00+00:00"),
            k(K_DEV_EBS, "alias/aws/ebs", "AWS", "Enabled", True, "Default key that protects my EBS volumes when no other key is defined",
              "2025-03-11T00:00:00+00:00"),
        ],
        SECLOG: [
            k(K_SEC, "alias/seclog-archive", "CUSTOMER", "Enabled", True, "감사 로그 보관 암호화", "2025-03-12T00:00:00+00:00"),
        ],
        SANDBOX: [],
    }[acct]


def volumes(acct: str) -> list[dict]:
    def v(vid, name, enc, key, inst, size, dev="/dev/xvda", state="in-use"):
        d = {"VolumeId": vid, "Size": size, "VolumeType": "gp3", "State": state, "Encrypted": enc,
             "AvailabilityZone": "ap-northeast-2a", "CreateTime": "2026-01-05T00:00:00+00:00",
             "Attachments": [{"InstanceId": inst, "Device": dev, "State": "attached"}] if inst else [],
             "Tags": [{"Key": "Name", "Value": name}]}
        if key:
            d["KmsKeyId"] = key
        return d
    return {
        PROD: [
            v("vol-0d4appa00000001", "lms-prod-app-a-root", True, karn(PROD, K_LMS), "i-0d4appa00000001", 40),
            v("vol-0d4appc00000001", "lms-prod-app-c-root", True, karn(PROD, K_LMS), "i-0d4appc00000001", 40),
            v("vol-0d4encode000001", "lms-prod-encoder-root", True, karn(PROD, K_LMS), "i-0d4encode000001", 30),
            v("vol-0d4encode000002", "lms-prod-encoder-scratch", True, karn(PROD, K_LMS), "i-0d4encode000001",
              500, "/dev/xvdb"),
            v("vol-0d4bastion00001", "lms-prod-bastion-root", True, karn(PROD, K_PROD_EBS), "i-0d4bastion00001", 8),
        ],
        DEV: [
            v("vol-0e5app00000001", "lms-dev-app-root", True, karn(PROD, K_LMS), "i-0e5app00000001", 40),
            v("vol-0e5app00000002", "lms-dev-app-data", True, karn(DEV, K_DEV_APP), "i-0e5app00000001", 100,
              "/dev/xvdb"),
            v("vol-0e5encleg00001", "dev-encoder-legacy-root", True, karn(DEV, K_DEV_EBS), "i-0e5encleg00001", 20),
        ],
        SECLOG: [
            v("vol-0f6tools000001", "seclog-tools-root", True, karn(SECLOG, K_SEC), "i-0f6tools000001", 30),
        ],
        SANDBOX: [
            v("vol-0a7lab00000001", "sandbox-lab-root", False, None, "i-0a7lab00000001", 8),
        ],
    }[acct]


def buckets(acct: str) -> list[dict]:
    def b(name, algo, key=None, lifecycle=None):
        d = {"SSEAlgorithm": algo, **({"KMSMasterKeyID": key} if key else {})}
        out = {"Name": name, "Region": REGION, "CreationDate": "2025-03-15T00:00:00+00:00",
               "Encryption": [{"ApplyServerSideEncryptionByDefault": d, "BucketKeyEnabled": algo == "aws:kms"}]}
        if lifecycle is not None:
            out["Lifecycle"] = lifecycle
        return out
    return {
        PROD: [
            b("b-prod-learner-uploads", "aws:kms", karn(PROD, K_LMS)),
            b("b-prod-certificates", "AES256"),
            b("b-prod-course-media", "AES256"),
            b("b-prod-athena-results", "aws:kms", karn(PROD, K_LMS),
              [{"ID": "expire-30d", "Status": "Enabled", "Filter": {"Prefix": ""}, "Expiration": {"Days": 30}}]),
            b("b-prod-ct-old", "AES256", lifecycle=[{"ID": "expire-90d", "Status": "Enabled",
                                                     "Filter": {"Prefix": ""}, "Expiration": {"Days": 90}}]),
        ],
        DEV: [
            b("b-dev-sample-data", "AES256"),
            b("b-dev-build-artifacts", "aws:kms", karn(DEV, K_DEV_APP)),
        ],
        SECLOG: [],   # 수집 실패 (manifest 참고) — 파일을 쓰지 않는다
        SANDBOX: [b("b-sandbox-lab-files", "AES256")],
    }[acct]


TLS13_12 = "ELBSecurityPolicy-TLS13-1-2-2021-06"
TLS11 = "ELBSecurityPolicy-TLS-1-1-2017-01"
SSL = {TLS13_12: ["TLSv1.2", "TLSv1.3"], TLS11: ["TLSv1.1", "TLSv1.2"]}


def listeners(acct: str) -> list[dict]:
    def lb(name, scheme, ls, suffix):
        arn = f"arn:aws:elasticloadbalancing:{REGION}:{acct}:loadbalancer/app/{name}/{suffix}"
        return {"LoadBalancerName": name, "Scheme": scheme, "Type": "application", "LoadBalancerArn": arn,
                "Listeners": [dict(x, LoadBalancerArn=arn,
                                   ListenerArn=arn.replace(":loadbalancer/", ":listener/") + f"/{x['Port']:016x}")
                              for x in ls]}

    def li(port, proto, action, policy=None):
        acts = [{"Type": "forward", "TargetGroupArn": f"arn:aws:elasticloadbalancing:{REGION}:{acct}:targetgroup/tg/1"}] \
            if action == "forward" else \
            [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "Host": "#{host}",
                                                     "Path": "/#{path}", "Query": "#{query}",
                                                     "StatusCode": "HTTP_301"}}]
        d = {"Port": port, "Protocol": proto, "DefaultActions": acts}
        if policy:
            d["SslPolicy"] = policy
            d["Certificates"] = [{"CertificateArn": f"arn:aws:acm:{REGION}:{acct}:certificate/cert-{port}"}]
        return d
    return {
        PROD: [
            lb("lms-web", "internet-facing", [li(443, "HTTPS", "forward", TLS13_12), li(80, "HTTP", "redirect")],
               "4a0000000000a001"),
            lb("lms-api", "internet-facing", [li(443, "HTTPS", "forward", TLS11)], "4a0000000000a002"),
            lb("lms-admin-internal", "internal", [li(80, "HTTP", "forward")], "4a0000000000a003"),
        ],
        DEV: [
            lb("dev-web", "internet-facing", [li(443, "HTTPS", "forward", TLS13_12), li(80, "HTTP", "redirect")],
               "5b0000000000b001"),
        ],
        SECLOG: [],
        SANDBOX: [],
    }[acct]


# ══════════════════════════════════════════════════════════════════════════
# 로그·백업
# ══════════════════════════════════════════════════════════════════════════

CENTRAL_LOG_BUCKET = "b-seclog-ct-archive"


def trail(acct, name, logging, multi, global_events, validation, bucket, selectors=None):
    return {"Name": name, "TrailARN": f"arn:aws:cloudtrail:{REGION}:{acct}:trail/{name}", "HomeRegion": REGION,
            "IsMultiRegionTrail": multi, "IncludeGlobalServiceEvents": global_events, "IsOrganizationTrail": False,
            "LogFileValidationEnabled": validation, "S3BucketName": bucket, "S3KeyPrefix": f"AWSLogs-{acct}",
            "Status": {"IsLogging": logging},
            "EventSelectors": selectors if selectors is not None else
            [{"ReadWriteType": "All", "IncludeManagementEvents": True, "DataResources": []}]}


def trails(acct: str) -> list[dict]:
    return {
        PROD: [
            trail(PROD, "b-prod-trail", True, True, True, True, CENTRAL_LOG_BUCKET),
            trail(PROD, "b-prod-trail-old", False, False, False, False, "b-prod-ct-old"),
        ],
        DEV: [
            trail(DEV, "b-dev-trail", True, True, True, False, CENTRAL_LOG_BUCKET, selectors=[{
                "ReadWriteType": "All", "IncludeManagementEvents": False,
                "DataResources": [{"Type": "AWS::S3::Object", "Values": ["arn:aws:s3:::b-dev-build-artifacts/"]}]}]),
        ],
        SECLOG: [trail(SECLOG, "b-seclog-trail", True, True, True, True, CENTRAL_LOG_BUCKET)],
        SANDBOX: [],
    }[acct]


GUARDDUTY = {
    PROD: [{"DetectorId": "4c8d0000000000000000000000000001", "Status": "ENABLED",
            "FindingPublishingFrequency": "FIFTEEN_MINUTES"}],
    DEV: [{"DetectorId": "5c8d0000000000000000000000000001", "Status": "DISABLED",
           "FindingPublishingFrequency": "SIX_HOURS"}],
    SECLOG: [{"DetectorId": "6c8d0000000000000000000000000001", "Status": "ENABLED",
              "FindingPublishingFrequency": "FIFTEEN_MINUTES"}],
    SANDBOX: [],
}


def backup_plan(acct, name, keep, schedule, copy_region=None):
    rule = {"RuleName": name.split("-")[-1], "TargetBackupVaultName": f"{ALIAS[acct]}-vault",
            "ScheduleExpression": schedule, "StartWindowMinutes": 60,
            "Lifecycle": {"DeleteAfterDays": keep}, "CopyActions": []}
    if copy_region:
        rule["CopyActions"] = [{"DestinationBackupVaultArn":
                                f"arn:aws:backup:{copy_region}:{acct}:backup-vault:{ALIAS[acct]}-dr-vault",
                                "Lifecycle": {"DeleteAfterDays": keep}}]
    return {"BackupPlanName": name, "BackupPlanId": f"bp-{acct[:3]}-{name}", "Rules": [rule]}


BACKUP = {
    PROD: [backup_plan(PROD, "lms-prod-daily", 14, "cron(0 17 * * ? *)"),
           backup_plan(PROD, "lms-prod-monthly", 365, "cron(0 18 1 * ? *)", copy_region="ap-northeast-3")],
    DEV: [],
    SECLOG: [backup_plan(SECLOG, "seclog-weekly", 90, "cron(0 19 ? * SUN *)", copy_region="ap-northeast-1")],
    SANDBOX: [],
}

COGNITO: dict[str, list] = {PROD: [], DEV: [], SECLOG: [], SANDBOX: []}


# ══════════════════════════════════════════════════════════════════════════
# 스냅샷 쓰기
# ══════════════════════════════════════════════════════════════════════════

def write_snapshot() -> None:
    if SNAP.exists():
        shutil.rmtree(SNAP)
    accounts = []
    for acct in ACCOUNTS:
        d = SNAP / acct
        d.mkdir(parents=True)
        (d / "credential_report.csv").write_text(credential_report(acct), encoding="utf-8")
        pp = PASSWORD_POLICY[acct]
        jdump(d / "iam_password_policy.json",
              {"PasswordPolicy": pp} if pp else
              {"Error": {"Code": "NoSuchEntity",
                         "Message": f"The Password Policy with domain name {acct} cannot be found."}})
        jdump(d / "login_profiles.json", login_profiles(acct))
        jdump(d / "iam_authorization.json", authorization(acct))
        jdump(d / "cognito_user_pools.json", COGNITO[acct])
        net = network(acct)
        jdump(d / "ec2_security_groups.json", net["sg"])
        jdump(d / "ec2_subnets.json", net["subnet"])
        jdump(d / "ec2_route_tables.json", net["rt"])
        jdump(d / "rds_db_instances.json", net["rds"])
        jdump(d / "ec2_volumes.json", volumes(acct))
        if acct != SECLOG:
            jdump(d / "s3_buckets.json", buckets(acct))
        jdump(d / "kms_keys.json", kms(acct))
        ls = listeners(acct)
        jdump(d / "elbv2_listeners.json", ls)
        used = sorted({x["SslPolicy"] for b in ls for x in b["Listeners"] if "SslPolicy" in x})
        jdump(d / "elbv2_ssl_policies.json", [{"Name": n, "SslProtocols": SSL[n]} for n in used])
        jdump(d / "cloudtrail_trails.json", trails(acct))
        jdump(d / "guardduty.json", GUARDDUTY[acct])
        jdump(d / "backup_plans.json", BACKUP[acct])
        entry = {"account_id": acct, "alias": ALIAS[acct], "status": "ok",
                 "files": sorted(p.name for p in d.iterdir())}
        if acct == SECLOG:
            entry["status"] = "partial"
            entry["errors"] = [{"file": "s3_buckets.json", "api": "s3:ListBuckets",
                                "error": "AccessDenied: 버킷 정책이 수집 역할(gapcheck-collector)의 접근을 거부함"}]
        accounts.append(entry)
    jdump(SNAP / "manifest.json", {
        "snapshot_id": "b-corp-eval-2026-11-02",
        "source": "fixture",
        "collected_at": COLLECTED_AT,
        "collector": "gapcheck-collector/fixture",
        "region": REGION,
        "note": "평가용 가상 스냅샷. live 수집기와 같은 파일 형식을 쓴다.",
        "accounts": accounts,
    })


# ══════════════════════════════════════════════════════════════════════════
# 증적 (xlsx)
# ══════════════════════════════════════════════════════════════════════════

def sheet(name: str, title: str, head: list[str], rows: list[list], fill="E2EFDA") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor=fill)
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(10, max(len(str(c.value or "")) for c in col) * 1.7)
    ws.freeze_panes = "A2"
    wb.properties.creator = "B사 정보보안팀 (가상)"
    wb.properties.created = FIXED_TS.replace(tzinfo=None)
    wb.properties.modified = FIXED_TS.replace(tzinfo=None)
    wb.save(EV / name)


def write_evidence() -> None:
    if EV.exists():
        shutil.rmtree(EV)
    EV.mkdir(parents=True)

    sheet("AWS계정관리대장_2026-11.xlsx", "AWS 계정관리대장",
          ["No", "계정ID", "계정 별칭", "IAM 사용자", "사번", "소속", "용도", "콘솔 비밀번호", "승인자", "승인일",
           "사용기한", "비고"], [
              [1, PROD, "b-prod", "sec-hwang", "B1003", "정보보안팀", "보안 관리", "사용", "CISO", "2025-03-03", None, None],
              [2, PROD, "b-prod", "ops-yang", "B1011", "인프라운영팀", "운영", "사용", "인프라운영팀장", "2025-04-14", None, None],
              [3, PROD, "b-prod", "dev-kang", "B1020", "플랫폼개발팀", "개발", "사용", "플랫폼개발팀장", "2025-05-06", None, None],
              [4, PROD, "b-prod", "dev-moon", "B1052", "플랫폼개발팀", "개발", "사용", "플랫폼개발팀장", "2026-08-03", None, None],
              [5, PROD, "b-prod", "data-oh", "B1037", "데이터팀", "데이터 분석", "사용", "데이터팀장", "2025-09-01", None, None],
              [6, PROD, "b-prod", "ops-shin", "B2041", "인프라운영팀", "운영", "사용", "인프라운영팀장", "2025-07-21", None, None],
              [7, PROD, "b-prod", "cs-lim", "B2058", "고객지원팀", "고객 문의 조회", "사용", "고객지원팀장", "2026-01-12", None, None],
              [8, PROD, "b-prod", "ops-yoo", "B2063", "인프라운영팀", "운영", "사용", "인프라운영팀장", "2026-10-12", None, "신규 입사"],
              [9, PROD, "b-prod", "svc-deploy", "-", "플랫폼개발팀", "배포 자동화(CI/CD)", "미사용", "플랫폼개발팀장",
               "2025-06-02", None, "액세스 키 전용"],
              [10, PROD, "b-prod", "vendor-lms", "EXT-021", "(주)러닝솔루션", "외부 유지보수", "사용", "인프라운영팀장",
               "2026-09-01", "2026-12-31", "LMS 유지보수 계약 2026-09~12"],
              [11, PROD, "b-prod", "vendor-old", "EXT-009", "(주)에듀시스템", "외부 유지보수", "미사용", "인프라운영팀장",
               "2026-01-05", "2026-06-30", "2026-07-01 비밀번호 삭제(비활성)"],
              [12, PROD, "b-prod", "demo-shared", "-", "영업팀", "영업 데모 공용", "사용", None, None, None,
               "2026-09-24 삭제 처리"],
              [13, DEV, "b-dev", "dev-kang", "B1020", "플랫폼개발팀", "개발", "사용", "플랫폼개발팀장", "2025-05-06", None, None],
              [14, DEV, "b-dev", "test", "-", "플랫폼개발팀", "개발 공용(통합 테스트)", "사용", "정보보안팀장", "2026-03-02",
               None, "공용 사용자: 강○○, 문○○, 외주 개발자 2명"],
              [15, DEV, "b-dev", "svc-ci", "-", "플랫폼개발팀", "CI 빌드", "미사용", "플랫폼개발팀장", "2025-10-13", None,
               "액세스 키 전용"],
              [16, SECLOG, "b-seclog", "sec-hwang", "B1003", "정보보안팀", "보안 관리", "사용", "CISO", "2025-03-03", None, None],
              [17, SECLOG, "b-seclog", "log-auditor", "B1044", "정보보안팀", "로그 감사", "사용", "정보보안팀장", "2026-02-02",
               None, None],
          ])

    sheet("인사명부_재직퇴직_2026-11-01.xlsx", "인사명부",
          ["사번", "성명", "부서", "직급", "고용형태", "상태", "입사일", "퇴직일"], [
              ["B1003", "황○○", "정보보안팀", "팀장", "정규직", "재직", "2025-03-01", None],
              ["B1011", "양○○", "인프라운영팀", "책임", "정규직", "재직", "2025-04-14", None],
              ["B1020", "강○○", "플랫폼개발팀", "선임", "정규직", "재직", "2025-05-06", None],
              ["B1029", "노○○", "플랫폼개발팀", "선임", "정규직", "퇴직", "2025-06-02", "2026-08-31"],
              ["B1037", "오○○", "데이터팀", "선임", "정규직", "재직", "2025-09-01", None],
              ["B1044", "배○○", "정보보안팀", "선임", "정규직", "재직", "2026-02-02", None],
              ["B1052", "문○○", "플랫폼개발팀", "사원", "정규직", "재직", "2026-08-03", None],
              ["B2041", "신○○", "인프라운영팀", "선임", "계약직", "퇴직", "2025-07-21", "2026-10-26"],
              ["B2058", "임○○", "고객지원팀", "사원", "계약직", "퇴직", "2026-01-12", "2026-10-29"],
              ["B2063", "유○○", "인프라운영팀", "사원", "정규직", "재직", "2026-10-12", None],
          ])

    sheet("특수권한자현황_2026-하반기.xlsx", "특수권한자 현황",
          ["AWS 계정", "IAM 사용자", "권한", "부여 사유", "승인자", "승인일", "최근 검토일"], [
              ["b-prod", "sec-hwang", "AdministratorAccess", "보안 관리자", "CISO", "2025-03-03", "2026-05-15"],
              ["b-seclog", "sec-hwang", "AdministratorAccess", "보안 관리자", "CISO", "2025-03-03", "2026-05-15"],
          ])

    sheet("접근권한검토결과_2025-2026.xlsx", "접근권한 검토",
          ["검토일", "검토자", "검토 대상", "결과", "조치 내용", "조치 완료일"], [
              ["2025-05-16", "정보보안팀 황○○", "AWS 3개 계정, LMS 관리자", "과다 권한 2건", "그룹 재지정", "2025-05-23"],
              ["2025-11-14", "정보보안팀 황○○", "AWS 3개 계정, LMS 관리자", "장기 미사용 1건", "비활성화", "2025-11-17"],
              ["2026-05-15", "정보보안팀 배○○", "AWS 3개 계정, LMS 관리자", "이상 없음", None, None],
          ])

    sheet("정보자산목록_클라우드_2026-10.xlsx", "정보자산",
          ["자산ID", "자산명", "유형", "AWS 계정", "리소스ID", "개인정보", "중요도", "자산관리자", "비고"], [
              ["B-DB-001", "LMS 운영 DB", "RDS", "b-prod", "lms-prod-db", "Y", "상", "인프라운영팀", "수강생 회원정보"],
              ["B-DB-002", "결제 DB", "RDS", "b-prod", "pay-prod-db", "Y", "상", "인프라운영팀", "결제·환불 내역"],
              ["B-DB-003", "학습 리포트 DB", "RDS", "b-prod", "lms-prod-report", "Y", "중", "데이터팀", "BI 연동"],
              ["B-DB-004", "개발 DB", "RDS", "b-dev", "lms-dev-db", "Y", "중", "플랫폼개발팀", "운영 데이터 일부 복제"],
              ["B-ST-001", "수강생 업로드 파일", "S3", "b-prod", "b-prod-learner-uploads", "Y", "상", "인프라운영팀", None],
              ["B-ST-002", "수료증 발급본", "S3", "b-prod", "b-prod-certificates", "Y", "중", "인프라운영팀",
               "성명·생년월일 포함 PDF"],
              ["B-ST-003", "강의 영상", "S3", "b-prod", "b-prod-course-media", "N", "중", "콘텐츠팀", None],
              ["B-ST-004", "분석 쿼리 결과", "S3", "b-prod", "b-prod-athena-results", "N", "하", "데이터팀", "가명처리 집계"],
              ["B-ST-005", "개발 샘플 데이터", "S3", "b-dev", "b-dev-sample-data", "N", "하", "플랫폼개발팀", "합성 데이터"],
              ["B-ST-006", "감사 로그 보관", "S3", "b-seclog", "b-seclog-ct-archive", "N", "상", "정보보안팀", None],
              ["B-SV-001", "LMS 애플리케이션 서버", "EC2", "b-prod", "i-0d4appa00000001", "Y", "상", "인프라운영팀", None],
              ["B-SV-002", "영상 인코딩 서버", "EC2", "b-prod", "i-0d4encode000001", "N", "중", "콘텐츠팀", None],
          ])

    sheet("암호키관리대장_2026.xlsx", "암호키 관리대장",
          ["키 별칭", "AWS 계정", "키 ID", "용도", "승인자", "생성일", "교체 방식", "상태"], [
              ["alias/lms-prod", "b-prod", K_LMS, "LMS 운영 DB·S3·EBS 암호화", "정보보안팀장", "2025-03-10", "KMS 자동(연 1회)", "사용"],
              ["alias/pay-prod", "b-prod", K_PAY, "결제 DB 암호화", "정보보안팀장", "2025-08-18", "KMS 자동(연 1회)", "사용"],
              ["alias/legacy-2024", "b-prod", K_LEGACY, "구 LMS 이관 데이터", "정보보안팀장", "2024-11-04", "-",
               "사용 중지(2026-12 삭제 예정)"],
              ["alias/seclog-archive", "b-seclog", K_SEC, "감사 로그 보관 암호화", "정보보안팀장", "2025-03-12",
               "KMS 자동(연 1회)", "사용"],
          ])

    sheet("개인정보처리시스템_접속기록점검_2026.xlsx", "접속기록 점검",
          ["점검일", "점검자", "점검 대상", "결과", "조치"], [
              ["2026-06-08", "정보보안팀 배○○", "LMS 관리자 콘솔, 결제 관리자", "이상 없음", None],
              ["2026-07-06", "정보보안팀 배○○", "LMS 관리자 콘솔, 결제 관리자", "대량 다운로드 1건", "업무 목적 확인"],
              ["2026-08-10", "정보보안팀 배○○", "LMS 관리자 콘솔, 결제 관리자", "이상 없음", None],
              ["2026-09-07", "정보보안팀 배○○", "LMS 관리자 콘솔, 결제 관리자", "야간 접속 2건", "소명 완료"],
              ["2026-10-12", "정보보안팀 배○○", "LMS 관리자 콘솔, 결제 관리자", "이상 없음", None],
          ])

    sheet("백업복구테스트_결과_2025-2026.xlsx", "복구 테스트",
          ["시험일", "대상", "결과", "확인자", "복구 소요시간"], [
              ["2025-10-17", "LMS 운영 DB 스냅샷 복원", "성공", "인프라운영팀장", "35분"],
              ["2026-01-20", "결제 DB 스냅샷 복원", "성공", "인프라운영팀장", "28분"],
              ["2026-04-22", "LMS 운영 DB 시점 복원(PITR)", "성공", "인프라운영팀장", "41분"],
              ["2026-07-15", "수강생 업로드 버킷 객체 복원", "성공", "인프라운영팀장", "12분"],
          ])

    sheet("재해복구_모의훈련_결과.xlsx", "DR 훈련",
          ["훈련일", "시나리오", "결과", "참여 부서", "보고일"], [
              ["2024-11-28", "서울 리전 장애 시 오사카 리전 백업 복원", "목표 시간 내 복구", "정보보안팀, 인프라운영팀", "2024-12-03"],
              ["2025-12-04", "랜섬웨어 감염 가정 DB 복구", "목표 시간 초과(보완 완료)", "정보보안팀, 인프라운영팀, 플랫폼개발팀",
               "2025-12-10"],
          ])


# ══════════════════════════════════════════════════════════════════════════
# 규정 문서 (docx)
# ══════════════════════════════════════════════════════════════════════════

def _korean_font(d) -> None:
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        st = d.styles[name]
        st.font.name = "맑은 고딕"
        rpr = st.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = rpr.makeelement(qn("w:rFonts"), {})
            rpr.append(rfonts)
        rfonts.set(qn("w:eastAsia"), "맑은 고딕")
    d.styles["Normal"].font.size = Pt(10)


def _table(d, rows, header=False):
    t = d.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = t.cell(r, c)
            cell.text = ""
            run = cell.paragraphs[0].add_run(val)
            if (header and r == 0) or (not header and c == 0):
                run.bold = True
    return t


def make_doc(filename, *, company_line, title, meta, history, body, article_style="Heading 2",
             cover_order="company-first", closing=None):
    d = docx.Document()
    _korean_font(d)
    cp = d.core_properties
    cp.author = "B사 정보보안팀"
    cp.title = title
    cp.created = FIXED_TS.replace(tzinfo=None)
    cp.modified = FIXED_TS.replace(tzinfo=None)
    cp.last_modified_by = "B사 정보보안팀"
    cp.revision = 1
    if cover_order == "company-first":
        d.add_paragraph(company_line)
        d.add_paragraph(title, style="Title")
    else:
        d.add_paragraph(title, style="Title")
        p = d.add_paragraph(company_line)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _table(d, meta)
    d.add_paragraph("")
    d.add_paragraph("제·개정 이력")
    _table(d, history, header=True)
    d.add_paragraph("")
    for kind, text in body:
        if kind == "H1":
            p = d.add_paragraph(text, style="Heading 1")
        elif kind == "ART":
            if article_style == "Heading 2":
                p = d.add_paragraph(text, style="Heading 2")
            else:
                p = d.add_paragraph()
                r = p.add_run(text)
                r.bold = True
        else:
            p = d.add_paragraph(text)
            if kind == "SUB":
                p.paragraph_format.left_indent = Pt(18)
            elif kind == "SUB2":
                p.paragraph_format.left_indent = Pt(36)
    if closing:
        for text in closing:
            d.add_paragraph(text)
    d.save(DOCS / filename)


def _meta(no, ver, eff, approver, dept="정보보안팀", grade="사내한정"):
    return [["문서번호", no], ["버전", ver], ["시행일", eff], ["승인자", approver], ["주관부서", dept], ["보안등급", grade]]


DOC_SEC = "B사_정보보안지침_v3.0.docx"
DOC_ACCT = "B사_계정및권한관리절차_v1.1.docx"
DOC_CRYPTO = "B사_암호화관리지침_v1.2.docx"
DOC_LOG = "B사_로그및백업관리지침_v2.0.docx"


def write_docs() -> None:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    DOCS.mkdir(parents=True)

    # ── 정보보안지침 (통합 지침: 사용자 인증·계정·권한·네트워크) ─────────────
    make_doc(
        DOC_SEC, company_line="B사 (주식회사 비러닝)", title="정보보안지침",
        meta=_meta("BS-GL-001", "3.0", "2026-04-01", "대표이사"),
        history=[["버전", "개정일", "개정 내용", "작성/검토"],
                 ["1.0", "2025-03-01", "제정", "정보보안팀 / CISO"],
                 ["2.0", "2025-09-15", "클라우드(AWS) 운영 기준 반영, 외부인력 계정 조항 신설", "정보보안팀 / CISO"],
                 ["3.0", "2026-03-20", "패스워드 최소 길이 8자리→9자리 상향, 재사용 제한 3회→5회, "
                                       "원격접속 관리망에 SSL-VPN 대역 추가, 접근권한 검토 주기 조정", "정보보안팀 / CISO"]],
        body=[
            ("H1", "제1장 총칙"),
            ("ART", "제1조(목적)"),
            ("P", "이 지침은 「정보보호 및 개인정보보호 정책」에 따라 B사가 운영하는 온라인 교육 서비스와 이를 지원하는 "
                  "정보시스템을 안전하게 관리하기 위하여 임직원과 외부인력이 지켜야 할 보안 기준을 정한다."),
            ("ART", "제2조(적용 범위)"),
            ("P", "이 지침은 B사의 임직원, 협력업체 인력 및 B사가 운영하는 정보시스템(클라우드 관리 콘솔, 서버, DB, "
                  "LMS 관리자 화면 포함)에 적용한다. 다만, 사내 교육 실습용 샌드박스 계정은 별도 운영 기준에 따른다."),
            ("ART", "제3조(용어 정의)"),
            ("P", "이 지침에서 사용하는 용어의 뜻은 다음과 같다."),
            ("SUB", "1. \"사용자\"란 업무 수행을 위하여 정보시스템 계정을 부여받은 임직원 및 외부인력을 말한다."),
            ("SUB", "2. \"회원\"이란 B사의 온라인 교육 서비스에 가입하여 강의를 수강하는 자를 말한다."),
            ("SUB", "3. \"초기 패스워드\"란 계정 생성 또는 패스워드 초기화 시 관리자가 임의로 부여한 패스워드를 말한다."),
            ("SUB", "4. \"특수권한\"이란 정보시스템 전체 또는 보안 설정을 변경할 수 있는 관리자급 권한을 말한다."),
            ("H1", "제2장 사용자 인증 및 패스워드"),
            ("ART", "제4조(패스워드 작성 기준)"),
            ("P", "① 사용자는 정보시스템 패스워드를 다음 각 호의 기준에 따라 설정하여야 한다."),
            ("SUB", "1. 영문 대문자, 영문 소문자, 숫자, 특수문자 중 3종류 이상을 조합하여 최소 9자리 이상으로 구성한다."),
            ("SUB", "2. 사용자 ID, 생년월일, 전화번호, 연속되거나 반복되는 문자·숫자 등 추측 가능한 값은 사용하지 않는다."),
            ("SUB", "3. 최근 5회 이내에 사용한 패스워드는 다시 사용할 수 없다."),
            ("P", "② 시스템 관리자는 각 정보시스템(클라우드 계정 포함)의 패스워드 정책이 제1항의 기준 이상이 되도록 설정하여야 한다."),
            ("ART", "제5조(패스워드 변경)"),
            ("P", "① 패스워드의 최대 사용기간은 120일로 하며, 사용자는 그 기간이 지나기 전에 패스워드를 변경하여야 한다."),
            ("P", "② 계정 발급 또는 초기화 시 부여된 초기 패스워드는 최초 로그인 시 사용자가 즉시 변경하여야 하며, "
                  "시스템은 변경하기 전에는 다른 기능을 이용할 수 없도록 설정한다."),
            ("P", "③ 패스워드가 노출되었거나 노출이 의심되는 경우 사용자는 즉시 변경하고 정보보안팀에 신고한다."),
            ("ART", "제6조(회원 패스워드)"),
            ("P", "① 서비스 회원의 패스워드는 영문, 숫자, 특수문자 중 2종류 이상을 조합하는 경우 최소 10자리 이상, "
                  "3종류 이상을 조합하는 경우 최소 8자리 이상으로 설정하도록 한다."),
            ("P", "② 회원가입 및 패스워드 변경 화면에는 제1항의 기준을 안내하고, 기준에 미달하는 패스워드는 등록되지 않도록 한다."),
            ("ART", "제7조(2차 인증)"),
            ("P", "클라우드(AWS) 관리 콘솔에 로그인하는 모든 계정(루트 계정 포함)은 패스워드와 함께 OTP 등 "
                  "2차 인증수단(MFA)을 적용하여야 한다."),
            ("H1", "제3장 계정 및 권한 관리"),
            ("ART", "제8조(계정 관리)"),
            ("P", "① 정보시스템 계정은 「계정 및 권한 관리 절차」에 따라 신청하고 승인을 받은 후 발급한다."),
            ("P", "② 계정 ID는 사용자 개인을 식별할 수 있도록 부여하며, administrator, root, test, guest 등 "
                  "유추하기 쉬운 ID는 사용하지 않는다."),
            ("P", "③ 여러 사람이 함께 사용하는 공용 계정은 원칙적으로 허용하지 않는다. 다만, 업무상 불가피한 경우에는 "
                  "정보보안팀장의 사전 승인을 받고 계정관리대장에 승인자와 실제 사용자를 기재한 후 사용할 수 있다."),
            ("P", "④ 최종 접속일로부터 60일 이상 사용하지 않은 계정은 잠금(비활성화) 처리한다."),
            ("ART", "제9조(접근권한 부여)"),
            ("P", "① 접근권한은 직무별로 정의한 역할 그룹(IAM 그룹)에 부여하고, 사용자는 해당 그룹에 소속시키는 방식으로 "
                  "권한을 받는다. 사용자 계정에 정책을 직접 연결하지 않는다."),
            ("P", "② 관리자 권한(AdministratorAccess 등 모든 서비스·자원에 대한 권한)은 특수권한으로 분류하여 "
                  "정보보안팀장의 승인을 받아 부여하며, 정보보안팀은 특수권한자 현황을 별도로 작성·관리한다."),
            ("P", "③ 외부 협력업체의 유지보수용 계정은 계약 기간 범위 안에서 사용기한을 정하여 발급하고, "
                  "사용기한이 지나면 지체 없이 비활성화한다."),
            ("ART", "제10조(접근권한 검토)"),
            ("P", "정보보안팀은 반기마다 1회 이상 정보시스템 계정 및 접근권한 부여 현황의 적정성을 검토하고, "
                  "그 결과와 조치 내역을 기록하여 보관한다."),
            ("H1", "제4장 네트워크 보안"),
            ("ART", "제11조(네트워크 영역 구분)"),
            ("P", "① 서비스 네트워크는 외부 공개 영역(DMZ), 애플리케이션 영역, DB 영역으로 구분하여 구성한다."),
            ("P", "② DB 서버(RDS 포함)에는 공인 IP를 할당하지 않으며, 인터넷에서 직접 접근할 수 있도록 퍼블릭 액세스를 허용하지 않는다."),
            ("P", "③ DB 영역 보안그룹의 인바운드 규칙은 애플리케이션 영역 보안그룹을 출발지로 하는 규칙만 허용하며, "
                  "IP 주소 대역을 출발지로 하는 규칙은 등록하지 않는다."),
            ("P", "④ DB 영역 서브넷의 라우팅 테이블에는 인터넷 게이트웨이 또는 NAT 게이트웨이로 향하는 경로를 두지 않는다."),
            ("P", "⑤ VPC 기본 보안그룹(default)은 모든 인바운드·아웃바운드 규칙을 삭제한 상태로 유지하며 자원에 연결하지 않는다."),
            ("ART", "제12조(서버 접근 통제)"),
            ("P", "① 서버 원격 접속(SSH, RDP)은 다음 각 호의 관리망에서만 허용한다."),
            ("SUB", f"1. 본사 IT 관리망: {HQ_ADMIN_NET}"),
            ("SUB", f"2. 원격근무용 SSL-VPN 대역: {VPN_NET}"),
            ("P", "② Telnet, FTP, rlogin 등 평문으로 인증정보를 전송하는 프로토콜은 사용하지 않으며, "
                  "SSH, SFTP 등 암호화된 프로토콜로 대체한다."),
            ("H1", "부칙"),
            ("P", "① (시행일) 이 지침은 2026년 4월 1일부터 시행한다."),
            ("P", "② (경과조치) 이 지침 시행 전에 종전 기준(8자리 이상)으로 설정한 사용자 패스워드는 "
                  "다음 변경 시까지 유효한 것으로 본다."),
        ],
    )

    # ── 계정 및 권한 관리 절차 (본문 조문을 일반 문단으로 작성) ────────────────
    make_doc(
        DOC_ACCT, company_line="주식회사 비러닝 정보보안팀", title="계정 및 권한 관리 절차",
        meta=_meta("BS-PR-003", "1.1", "2026-04-01", "정보보안팀장"),
        history=[["버전", "개정일", "개정 내용", "작성/검토"],
                 ["1.0", "2025-03-01", "제정", "정보보안팀"],
                 ["1.1", "2026-03-20", "퇴직자 계정 회수 기한 명확화(즉시 → 3영업일 이내), 액세스 키 회수 포함", "정보보안팀"]],
        cover_order="title-first", article_style="plain",
        body=[
            ("H1", "제1장 일반사항"),
            ("ART", "제1조(목적)"),
            ("P", "이 절차는 「정보보안지침」 제8조 및 제9조에 따라 정보시스템 계정과 접근권한의 신청, 승인, 발급, "
                  "변경, 회수 업무를 수행하는 방법을 정한다."),
            ("ART", "제2조(역할)"),
            ("P", "① 신청자의 소속 팀장은 계정 및 권한 신청의 업무상 필요성을 검토하여 승인한다."),
            ("P", "② 정보보안팀은 승인된 신청에 따라 계정을 생성·변경·회수하고 계정관리대장을 최신 상태로 유지한다."),
            ("P", "③ 인사팀은 입사, 부서 이동, 퇴직 등 인사 변동 사항을 정보보안팀에 통보한다."),
            ("H1", "제2장 계정 발급 및 변경"),
            ("ART", "제3조(계정 신청 및 승인)"),
            ("P", "① 계정이 필요한 사용자는 그룹웨어 전자결재로 「정보시스템 계정 신청서」를 작성하여 소속 팀장의 승인을 받는다."),
            ("P", "② 특수권한 또는 공용 계정을 신청하는 경우에는 소속 팀장 승인 후 정보보안팀장의 승인을 추가로 받는다."),
            ("P", "③ 정보보안팀은 승인이 완료되지 않은 신청에 대하여 계정을 발급하지 않는다."),
            ("ART", "제4조(계정 발급)"),
            ("P", "① 정보보안팀은 승인된 신청서에 따라 직무에 해당하는 역할 그룹에 사용자를 등록한다."),
            ("P", "② 초기 패스워드는 신청자에게 메신저와 분리된 별도 경로(문자 메시지 등)로 전달한다."),
            ("P", "③ 클라우드 콘솔 계정을 생성하는 경우 \"다음 로그인 시 패스워드 재설정 필요\" 옵션을 반드시 선택한다."),
            ("P", "④ 발급 결과는 계정관리대장에 사번, 용도, 승인자, 승인일을 포함하여 기록한다."),
            ("ART", "제5조(권한 변경)"),
            ("P", "부서 이동 또는 직무 변경이 있는 경우 정보보안팀은 기존 역할 그룹에서 사용자를 제외한 후 "
                  "새 직무의 역할 그룹에 등록한다."),
            ("H1", "제3장 계정 회수"),
            ("ART", "제6조(퇴직자 계정 회수)"),
            ("P", "① 인사팀은 퇴직이 확정되면 퇴직자 성명, 사번, 퇴직일을 정보보안팀에 통보한다."),
            ("P", "② 정보보안팀은 퇴직일로부터 3영업일 이내에 퇴직자의 모든 정보시스템 계정을 삭제하거나 비활성화한다. "
                  "클라우드 계정의 경우 콘솔 패스워드 삭제와 액세스 키 비활성화를 모두 포함한다."),
            ("P", "③ 회수 결과는 계정관리대장의 비고란에 처리일과 처리자를 기재한다."),
            ("ART", "제7조(외부인력 계정)"),
            ("P", "① 외부 협력업체 인력의 계정은 계약서상 업무 기간을 확인하여 사용기한을 계정관리대장에 기재한다."),
            ("P", "② 사용기한이 도래한 계정은 별도 연장 승인이 없으면 만료일 다음 영업일에 비활성화한다."),
            ("ART", "제8조(장기 미사용 계정)"),
            ("P", "정보보안팀은 매월 첫 주에 계정별 최종 사용일을 확인하여 「정보보안지침」 제8조제4항에 해당하는 계정을 "
                  "비활성화하고, 재사용이 필요한 경우 제3조의 신청 절차를 다시 거치도록 한다."),
            ("H1", "부칙"),
            ("P", "이 절차는 2026년 4월 1일부터 시행한다."),
        ],
    )

    # ── 암호화 관리 지침 ────────────────────────────────────────────────────
    make_doc(
        DOC_CRYPTO, company_line="B사 (주식회사 비러닝)", title="암호화 관리 지침",
        meta=_meta("BS-GL-004", "1.2", "2026-01-02", "CISO"),
        history=[["버전", "개정일", "개정 내용", "작성/검토"],
                 ["1.0", "2025-03-01", "제정", "정보보안팀 / CISO"],
                 ["1.1", "2025-08-01", "S3 서버 측 암호화 기준 추가", "정보보안팀 / CISO"],
                 ["1.2", "2025-12-15", "TLS 1.0/1.1 사용 금지 명시, 암호키 자동 교체 의무화", "정보보안팀 / CISO"]],
        body=[
            ("H1", "제1장 총칙"),
            ("ART", "제1조(목적)"),
            ("P", "이 지침은 개인정보와 중요정보를 저장하거나 전송할 때 적용할 암호화 기준과 암호키 관리 방법을 정한다."),
            ("ART", "제2조(적용 범위)"),
            ("P", "이 지침은 B사가 AWS에서 운영하는 서비스와 개인정보처리시스템에 적용한다."),
            ("ART", "제3조(암호 알고리즘)"),
            ("P", "암호화에는 국내외 표준으로 인정된 안전한 알고리즘(AES-256, SHA-256 이상 등)을 사용하며, "
                  "회원 패스워드는 솔트를 적용한 일방향 해시로 저장한다."),
            ("H1", "제2장 저장 및 전송 시 암호화"),
            ("ART", "제4조(저장 시 암호화)"),
            ("P", "① 개인정보를 저장하는 데이터베이스(RDS 등)는 스토리지 암호화를 적용하여 운영한다."),
            ("P", "② 서버(EC2)에 연결하는 블록 스토리지(EBS)는 용도와 관계없이 모두 암호화한다."),
            ("P", "③ 개인정보가 포함된 파일을 저장하는 S3 버킷은 KMS 키를 이용한 서버 측 암호화(SSE-KMS)를 "
                  "기본 암호화로 설정한다. S3 관리형 키(SSE-S3)만 적용하는 것은 허용하지 않는다."),
            ("ART", "제5조(전송 시 암호화)"),
            ("P", "① 인터넷을 통해 개인정보 및 인증정보를 송수신하는 구간은 TLS 1.2 이상으로 암호화하며, "
                  "SSL 3.0, TLS 1.0, TLS 1.1은 허용하지 않는다."),
            ("P", "② 인터넷에 공개되는 웹 서비스와 API는 HTTPS로만 제공하고, HTTP로 들어온 요청은 HTTPS로 리다이렉트한다."),
            ("H1", "제3장 암호키 관리"),
            ("ART", "제6조(암호키 생성 및 등록)"),
            ("P", "① 암호키는 AWS KMS에서 생성하며, 생성 전에 정보보안팀장의 승인을 받는다."),
            ("P", "② 생성한 고객 관리형 키는 암호키 관리대장에 키 별칭, 계정, 키 ID, 용도, 승인자를 기록한다."),
            ("ART", "제7조(암호키 교체)"),
            ("P", "고객 관리형 키는 KMS 자동 키 교체를 활성화하여 연 1회 이상 교체되도록 한다."),
            ("ART", "제8조(암호키 폐기)"),
            ("P", "더 이상 사용하지 않는 키는 비활성화하고, 해당 키로 암호화한 데이터가 없음을 확인한 후 "
                  "30일의 대기기간을 두어 삭제한다. 폐기 내역은 암호키 관리대장에 기록한다."),
            ("H1", "부칙"),
            ("P", "이 지침은 2026년 1월 2일부터 시행한다."),
        ],
    )

    # ── 로그 및 백업 관리 지침 (조문을 일반 문단으로 작성) ──────────────────────
    make_doc(
        DOC_LOG, company_line="B사 (주식회사 비러닝)", title="로그 및 백업 관리 지침",
        meta=_meta("BS-GL-005", "2.0", "2026-02-01", "CISO"),
        history=[["버전", "개정일", "개정 내용", "작성/검토"],
                 ["1.0", "2025-03-01", "제정", "정보보안팀 / CISO"],
                 ["2.0", "2026-01-20", "보안로그 전용 계정으로 로그 집중, 보관 기간 2년 → 3년, 복구 테스트 분기화",
                  "정보보안팀 / CISO"]],
        article_style="plain",
        body=[
            ("H1", "제1장 총칙"),
            ("ART", "제1조(목적)"),
            ("P", "이 지침은 정보시스템의 로그 수집·보관·점검과 데이터 백업·복구, 재해복구 훈련에 관한 기준을 정한다."),
            ("ART", "제2조(적용 범위)"),
            ("P", "이 지침은 B사가 운영하는 모든 AWS 계정과 개인정보처리시스템에 적용한다."),
            ("H1", "제2장 로그 관리"),
            ("ART", "제3조(감사 로그 수집)"),
            ("P", "① 모든 AWS 계정은 CloudTrail을 전체 리전(멀티 리전)으로 설정하여 관리 이벤트(읽기·쓰기)를 기록한다."),
            ("P", "② CloudTrail 로그는 보안로그 전용 계정의 S3 버킷으로 모아서 저장하며, 로그 파일 무결성 검증을 활성화한다."),
            ("ART", "제4조(로그 보관)"),
            ("P", "감사 로그와 개인정보처리시스템 접속기록은 3년간 보관한다. 다만, 관계 법령에서 이보다 긴 기간을 정한 경우에는 그에 따른다."),
            ("ART", "제5조(로그 점검 및 이상행위 탐지)"),
            ("P", "① 정보보안팀은 개인정보처리시스템 접속기록을 매월 1회 이상 점검하고 점검 결과를 기록한다."),
            ("P", "② 모든 AWS 계정에서 Amazon GuardDuty를 활성화하여 이상행위를 탐지하며, 심각도 높음 이상의 탐지 결과는 "
                  "24시간 이내에 확인한다."),
            ("H1", "제3장 백업 및 복구"),
            ("ART", "제6조(백업)"),
            ("P", "① 정보자산 중요도가 '상'인 데이터베이스는 매일 자동 백업하고, 백업본은 14일 이상 보관한다."),
            ("P", "② 중요도 '상' 자원의 백업본은 재해에 대비하여 주 리전(서울)과 다른 리전에 복제하여 보관한다."),
            ("P", "③ 중요도 '중' 이하 자원의 백업 주기와 보관 기간은 자산관리자가 정한다."),
            ("ART", "제7조(복구 테스트)"),
            ("P", "백업 담당 부서는 분기별 1회 이상 백업 데이터의 복구 테스트를 실시하고 그 결과를 기록한다."),
            ("ART", "제8조(재해복구 훈련)"),
            ("P", "정보보안팀은 매년 1회 이상 재해복구(DR) 모의훈련을 실시하고, 그 결과를 정보보호최고책임자(CISO)에게 보고한다."),
            ("H1", "부칙"),
            ("P", "이 지침은 2026년 2월 1일부터 시행한다."),
        ],
    )


# ══════════════════════════════════════════════════════════════════════════
# scope.yaml, README.md
# ══════════════════════════════════════════════════════════════════════════

SCOPE = f"""# B사 진단 범위 사실 (Scope facts). 사람이 확인해 입력한 값이며, 근거(basis)를 함께 적는다.
# 여기 없는 사실은 Scope Engine이 UNKNOWN 으로 본다.
organization: B사 (가상 온라인 교육 플랫폼, 임직원 약 120명)
as_of: "{AS_OF}"
facts:
  scope.has_information_systems: {{value: true, basis: "정보보안지침 제2조 — LMS, 결제, 관리자 화면"}}
  scope.has_aws_accounts: {{value: true, basis: "정보자산목록 — AWS 운영·개발·보안로그 계정"}}
  scope.aws_iam_users_with_console_password: {{value: true, basis: "AWS 계정관리대장 — 콘솔 사용자 존재"}}
  scope.service_has_customer_login: {{value: true, basis: "수강생 회원가입·로그인 (LMS)"}}
  scope.uses_cognito: {{value: false, basis: "회원 인증은 LMS 자체 인증 서버에서 처리 (Cognito 미사용)"}}
aws_accounts:
  - {{account_id: "{PROD}", alias: {ALIAS[PROD]}, label: {LABEL[PROD]}, in_scope: true}}
  - {{account_id: "{DEV}", alias: {ALIAS[DEV]}, label: {LABEL[DEV]}, in_scope: true}}
  - {{account_id: "{SECLOG}", alias: {ALIAS[SECLOG]}, label: {LABEL[SECLOG]}, in_scope: true}}
  - {{account_id: "{SANDBOX}", alias: {ALIAS[SANDBOX]}, label: "{LABEL[SANDBOX]}", in_scope: false}}
policy_documents:
  # 이 목록이 문서 Coverage의 분모다.
  - {{file: docs/{DOC_SEC}, doc_id: BS-GL-001}}
  - {{file: docs/{DOC_ACCT}, doc_id: BS-PR-003}}
  - {{file: docs/{DOC_CRYPTO}, doc_id: BS-GL-004}}
  - {{file: docs/{DOC_LOG}, doc_id: BS-GL-005}}
evidence:
  # 표 증적은 파일 이름이 아니라 첫 줄(머리글)로 종류를 알아낸다
  - {{file: evidence/AWS계정관리대장_2026-11.xlsx, kind: account_list}}
  - {{file: evidence/인사명부_재직퇴직_2026-11-01.xlsx, kind: hr_roster}}
  - {{file: evidence/특수권한자현황_2026-하반기.xlsx, kind: privileged_list}}
  - {{file: evidence/접근권한검토결과_2025-2026.xlsx, kind: access_review_log}}
  - {{file: evidence/정보자산목록_클라우드_2026-10.xlsx, kind: asset_list}}
  - {{file: evidence/암호키관리대장_2026.xlsx, kind: key_ledger}}
  - {{file: evidence/개인정보처리시스템_접속기록점검_2026.xlsx, kind: access_log_review}}
  - {{file: evidence/백업복구테스트_결과_2025-2026.xlsx, kind: restore_test_log}}
  - {{file: evidence/재해복구_모의훈련_결과.xlsx, kind: dr_drill_log}}
"""

README = f"""# 시나리오: b-corp-eval (B사, 가상 온라인 교육 플랫폼)

ISMS-P 갭분석 도구의 **평가용 시나리오**입니다. 개발용 시나리오(a-corp-dev)와 다른 회사·다른 규정 문체·다른 기준값으로 구성되어,
도구가 회사 자체 규정에서 기준을 읽어 판정하는지 확인하는 데 씁니다. 정답지는 이 저장소에 없고, 해시(`ANSWER_KEY.sha256`)만 둡니다.

`python scripts/build_b_corp_eval.py` 로 이 폴더의 내용(문서·증적·스냅샷·scope.yaml·README)을 다시 만들 수 있습니다.
모든 회사·인물·계정 정보는 가상입니다 (AWS 계정 ID {PROD} 등, 문서용 IP 대역, 사람 이름은 마스킹).

## B사 개요

- 주식회사 비러닝(B사): 성인 직무교육 온라인 강의(LMS)를 운영하는 가상 회사, 임직원 약 120명
- 수강생 회원가입·로그인과 수강료 결제 서비스를 운영 (회원 인증은 자체 인증 서버)
- AWS 서울 리전에서 운영. 계정은 용도별로 나뉨

| 계정 ID | 별칭 | 용도 | 진단 범위 |
|---|---|---|---|
| {PROD} | b-prod | 운영 (LMS, 결제, 리포트) | 포함 |
| {DEV} | b-dev | 개발 | 포함 |
| {SECLOG} | b-seclog | 보안로그 (감사 로그 집중 보관) | 포함 |
| {SANDBOX} | b-sandbox | 사내 교육 실습용 샌드박스 | 제외 |

## 폴더

| 폴더 | 내용 |
|---|---|
| docs/ | 정보보안지침(v3.0, 인증·계정·권한·네트워크 통합), 계정 및 권한 관리 절차(v1.1), 암호화 관리 지침(v1.2), 로그 및 백업 관리 지침(v2.0) |
| evidence/ | AWS 계정관리대장, 인사명부, 특수권한자 현황, 접근권한 검토 결과, 정보자산목록, 암호키 관리대장, 접속기록 점검, 백업 복구 테스트 결과, 재해복구 모의훈련 결과 |
| aws-snapshot/ | 4개 AWS 계정의 수집 결과 (live 수집기와 같은 형식, manifest.json 에 계정별 수집 상태) |
| scope.yaml | 진단 범위 사실과 근거, 진단 기준일({AS_OF}) |
| ANSWER_KEY.sha256 | 숨김 정답지의 해시 (정답지 원본은 저장소 밖에 보관) |
"""


def write_meta_files() -> None:
    (SC / "scope.yaml").write_text(SCOPE, encoding="utf-8")
    yaml.safe_load((SC / "scope.yaml").read_text(encoding="utf-8"))
    (SC / "README.md").write_text(README, encoding="utf-8")


if __name__ == "__main__":
    SC.mkdir(parents=True, exist_ok=True)
    write_docs()
    write_evidence()
    write_snapshot()
    write_meta_files()
    print("b-corp-eval 시나리오 생성 완료", file=sys.stderr)
