"""a-corp-dev 시나리오의 네트워크 단계(2.6) 데이터를 만든다. 다시 실행해도 같은 결과 (멱등).

    python scripts/build_a_corp_dev_network.py

심는 결함 (D16~D21) — 자세한 내용은 expected/dev_expected.yaml
  a-prod   DB 보안그룹이 VPC 전체 대역(10.10.0.0/16)에서 3306 허용, 배스천 SSH 0.0.0.0/0,
           DB 서브넷 라우팅에 NAT 경로
  a-stg    RDS 공인 접근 허용, 기본 보안그룹 규칙 그대로, FTP(21) 허용
함정
  a-prod   ALB의 443 0.0.0.0/0 (웹 서비스라 정상), 앱 서브넷의 NAT 경로 (DB 영역이 아님)
  a-stg    앱 보안그룹 SSH가 관리망(203.0.113.0/28)에서만
  a-shared RDS가 없음 (DB 규칙은 대상 0건이라 통과), RDP·SSH가 관리망 안의 /32에서만
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import docx

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "a-corp-dev"
SNAP = SC / "aws-snapshot"
PROD, STG, SHARED = "111111111111", "222222222222", "333333333333"
OFFICE_ADMIN = "203.0.113.0/28"


def perm(proto: str, lo: int | None = None, hi: int | None = None, cidrs=(), groups=(), desc: str = "") -> dict:
    p: dict = {"IpProtocol": proto}
    if proto != "-1":
        p["FromPort"], p["ToPort"] = lo, (hi if hi is not None else lo)
    p["IpRanges"] = [{"CidrIp": c, **({"Description": desc} if desc else {})} for c in cidrs if ":" not in c]
    p["Ipv6Ranges"] = [{"CidrIpv6": c} for c in cidrs if ":" in c]
    p["UserIdGroupPairs"] = [{"GroupId": g} for g in groups]
    p["PrefixListIds"] = []
    return p


EGRESS_ALL = [perm("-1", cidrs=["0.0.0.0/0"])]


def sg(gid: str, name: str, vpc: str, ingress: list, egress: list | None = None, desc: str = "") -> dict:
    return {"GroupId": gid, "GroupName": name, "VpcId": vpc, "Description": desc or name,
            "IpPermissions": ingress, "IpPermissionsEgress": EGRESS_ALL if egress is None else egress, "Tags": []}


def subnet(sid: str, vpc: str, cidr: str, name: str, az: str) -> dict:
    return {"SubnetId": sid, "VpcId": vpc, "CidrBlock": cidr, "AvailabilityZone": az,
            "MapPublicIpOnLaunch": name.endswith("public-a"), "Tags": [{"Key": "Name", "Value": name}]}


def rt(rid: str, vpc: str, vpc_cidr: str, subnets: list[str], default: str | None, main: bool = False) -> dict:
    routes = [{"DestinationCidrBlock": vpc_cidr, "GatewayId": "local", "State": "active"}]
    if default:
        key = "NatGatewayId" if default.startswith("nat-") else "GatewayId"
        routes.append({"DestinationCidrBlock": "0.0.0.0/0", key: default, "State": "active"})
    assoc = [{"RouteTableAssociationId": f"rtbassoc-{rid[4:]}{i}", "RouteTableId": rid, "SubnetId": s, "Main": False}
             for i, s in enumerate(subnets)]
    if main:
        assoc.append({"RouteTableAssociationId": f"rtbassoc-{rid[4:]}m", "RouteTableId": rid, "Main": True})
    return {"RouteTableId": rid, "VpcId": vpc, "Routes": routes, "Associations": assoc}


def rds(name: str, engine: str, public: bool, sgs: list[str], subnets: list[str]) -> dict:
    return {"DBInstanceIdentifier": name, "Engine": engine, "DBInstanceStatus": "available",
            "PubliclyAccessible": public, "StorageEncrypted": True,
            "VpcSecurityGroups": [{"VpcSecurityGroupId": g, "Status": "active"} for g in sgs],
            "DBSubnetGroup": {"DBSubnetGroupName": f"{name}-subnets",
                              "Subnets": [{"SubnetIdentifier": s} for s in subnets]}}


def prod() -> dict:
    vpc, cidr = "vpc-0a1prod0000000001", "10.10.0.0/16"
    return {
        "sg": [
            sg("sg-0a1default000001", "default", vpc, [], []),
            sg("sg-0a1alb0000000001", "prod-alb", vpc, [perm("tcp", 443, cidrs=["0.0.0.0/0", "::/0"])]),
            sg("sg-0a1app0000000001", "prod-app", vpc, [
                perm("tcp", 8080, groups=["sg-0a1alb0000000001"]),
                perm("tcp", 22, groups=["sg-0a1bastion000001"])]),
            # D20: 배스천 SSH가 인터넷 전체에서 열림
            sg("sg-0a1bastion000001", "prod-bastion", vpc, [perm("tcp", 22, cidrs=["0.0.0.0/0"], desc="temp")]),
            # D19: DB 보안그룹이 앱 보안그룹이 아니라 VPC 전체 대역에서 3306 허용
            sg("sg-0a1db00000000001", "prod-db", vpc, [
                perm("tcp", 3306, groups=["sg-0a1app0000000001"]),
                perm("tcp", 3306, cidrs=[cidr], desc="ops query")]),
        ],
        "subnet": [
            subnet("subnet-0a1pub000000a", vpc, "10.10.0.0/24", "prod-public-a", "ap-northeast-2a"),
            subnet("subnet-0a1app000000a", vpc, "10.10.10.0/24", "prod-app-a", "ap-northeast-2a"),
            subnet("subnet-0a1db0000000a", vpc, "10.10.20.0/24", "prod-db-a", "ap-northeast-2a"),
            subnet("subnet-0a1db0000000c", vpc, "10.10.21.0/24", "prod-db-c", "ap-northeast-2c"),
        ],
        "rt": [
            rt("rtb-0a1main00000001", vpc, cidr, [], None, main=True),
            rt("rtb-0a1public000001", vpc, cidr, ["subnet-0a1pub000000a"], "igw-0a1prod00000001"),
            rt("rtb-0a1app00000001", vpc, cidr, ["subnet-0a1app000000a"], "nat-0a1prod0000000001"),
            # D21: DB 서브넷 라우팅 테이블에 NAT로 나가는 기본 경로
            rt("rtb-0a1db000000001", vpc, cidr, ["subnet-0a1db0000000a", "subnet-0a1db0000000c"],
               "nat-0a1prod0000000001"),
        ],
        "rds": [rds("prod-orders", "mysql", False, ["sg-0a1db00000000001"],
                    ["subnet-0a1db0000000a", "subnet-0a1db0000000c"])],
    }


def stg() -> dict:
    vpc, cidr = "vpc-0b2stg00000000001", "10.20.0.0/16"
    return {
        "sg": [
            # D17: 기본 보안그룹에 AWS 기본 규칙(같은 그룹 전체 허용, 나가는 전체 허용)이 그대로
            sg("sg-0b2default000001", "default", vpc, [perm("-1", groups=["sg-0b2default000001"])]),
            sg("sg-0b2app0000000001", "stg-app", vpc, [
                perm("tcp", 8080, cidrs=[cidr]),
                perm("tcp", 22, cidrs=[OFFICE_ADMIN])]),
            # D18: 암호화되지 않은 FTP 허용 (외부 정산 업체 연동용으로 남은 규칙)
            sg("sg-0b2legacy000001", "stg-legacy-ftp", vpc, [perm("tcp", 21, cidrs=["198.51.100.10/32"])]),
            sg("sg-0b2db00000000001", "stg-db", vpc, [perm("tcp", 5432, groups=["sg-0b2app0000000001"])]),
        ],
        "subnet": [
            subnet("subnet-0b2pub000000a", vpc, "10.20.0.0/24", "stg-public-a", "ap-northeast-2a"),
            subnet("subnet-0b2app000000a", vpc, "10.20.10.0/24", "stg-app-a", "ap-northeast-2a"),
            subnet("subnet-0b2db0000000a", vpc, "10.20.20.0/24", "stg-db-a", "ap-northeast-2a"),
        ],
        "rt": [
            rt("rtb-0b2main00000001", vpc, cidr, [], None, main=True),
            rt("rtb-0b2public000001", vpc, cidr, ["subnet-0b2pub000000a"], "igw-0b2stg000000001"),
            rt("rtb-0b2app00000001", vpc, cidr, ["subnet-0b2app000000a"], "nat-0b2stg00000000001"),
            rt("rtb-0b2db000000001", vpc, cidr, ["subnet-0b2db0000000a"], None),
        ],
        # D16: 스테이징 DB에 공인 접근 허용 (운영 데이터 일부를 복제해 시험 중)
        "rds": [rds("stg-orders", "postgres", True, ["sg-0b2db00000000001"], ["subnet-0b2db0000000a"])],
    }


def shared() -> dict:
    vpc, cidr = "vpc-0c3shared0000001", "10.30.0.0/16"
    return {
        "sg": [
            sg("sg-0c3default000001", "default", vpc, [], []),
            sg("sg-0c3tools00000001", "shared-tools", vpc, [
                perm("tcp", 22, cidrs=[OFFICE_ADMIN]),
                perm("tcp", 3389, cidrs=["203.0.113.5/32"])]),
        ],
        "subnet": [
            subnet("subnet-0c3pub000000a", vpc, "10.30.0.0/24", "shared-public-a", "ap-northeast-2a"),
            subnet("subnet-0c3tools0000a", vpc, "10.30.10.0/24", "shared-tools-a", "ap-northeast-2a"),
        ],
        "rt": [
            rt("rtb-0c3main00000001", vpc, cidr, ["subnet-0c3tools0000a"], "nat-0c3shared0000000001", main=True),
            rt("rtb-0c3public000001", vpc, cidr, ["subnet-0c3pub000000a"], "igw-0c3shared000001"),
        ],
        "rds": [],
    }


FILE = {"sg": ("ec2_security_groups.json", "SecurityGroups"), "subnet": ("ec2_subnets.json", "Subnets"),
        "rt": ("ec2_route_tables.json", "RouteTables"), "rds": ("rds_db_instances.json", "DBInstances")}


def write_snapshot() -> None:
    for acct, data in ((PROD, prod()), (STG, stg()), (SHARED, shared())):
        for k, (name, _) in FILE.items():
            (SNAP / acct / name).write_text(json.dumps(data[k], indent=2) + "\n", encoding="utf-8")
    p = SNAP / "manifest.json"
    m = json.loads(p.read_text(encoding="utf-8"))
    for a in m["accounts"]:
        a["files"] = sorted(x.name for x in (SNAP / a["account_id"]).iterdir())
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _style(doc, name: str):
    return next(p.style for p in doc.paragraphs if p.style.name == name)


def write_docs() -> None:
    path = SC / "docs" / "A사_접근통제지침_v2.1.docx"
    d = docx.Document(path)
    if any(p.text.startswith("제13조") for p in d.paragraphs):
        return
    anchor = next(p for p in d.paragraphs if p.text.strip().startswith("부칙"))
    items = [
        ("Heading 1", "제4장 네트워크 접근통제"),
        ("Heading 2", "제13조(네트워크 영역 분리)"),
        ("Normal", "① 정보시스템은 인터넷 영역(DMZ), 애플리케이션 영역, 데이터베이스 영역으로 나누어 구성한다."),
        ("Normal", "② 데이터베이스는 공인 IP를 부여하지 않고 외부에서 직접 접근할 수 없는 데이터베이스 영역에 둔다."),
        ("Normal", "③ 데이터베이스 영역에는 애플리케이션 영역의 보안그룹만 접근할 수 있도록 허용하며, IP 대역 단위로 허용하지 않는다."),
        ("Normal", "④ 데이터베이스 영역의 서버는 인터넷으로 직접 접속하지 않으며, 외부로 나가는 경로를 두지 않는다."),
        ("Normal", "⑤ 클라우드의 기본 보안그룹은 사용하지 않으며 허용 규칙을 두지 않는다."),
        ("Heading 2", "제14조(정보시스템 접근)"),
        ("Normal", f"① 서버의 원격 관리(SSH, 원격 데스크톱)는 회사가 지정한 관리망({OFFICE_ADMIN})에서만 허용한다."),
        ("Normal", "② telnet, FTP 등 암호화되지 않은 접속 프로토콜은 사용하지 않는다."),
    ]
    for style, text in items:
        new = anchor.insert_paragraph_before(text, style=_style(d, style))
        if style.startswith("Heading"):
            for r in new.runs:
                r.bold = True
    d.save(path)


if __name__ == "__main__":
    write_snapshot()
    write_docs()
    print("a-corp-dev 네트워크 단계 데이터 생성 완료", file=sys.stderr)
