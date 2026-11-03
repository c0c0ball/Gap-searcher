"""네트워크 관측: 보안그룹·서브넷·라우팅·RDS 스냅샷을 Observation으로 바꾼다 (2.6 접근통제).

스냅샷 파일 (계정 폴더마다, live 수집기와 같은 형식)
  ec2_security_groups.json   DescribeSecurityGroups 응답의 SecurityGroups 목록
  ec2_subnets.json           DescribeSubnets 응답의 Subnets 목록
  ec2_route_tables.json      DescribeRouteTables 응답의 RouteTables 목록
  rds_db_instances.json      DescribeDBInstances 응답의 DBInstances 목록

관측 kind
  aws_sg_rule  보안그룹 인바운드 규칙 1개 × 출발지 1개 (포트·출발지·DB 보안그룹 여부)
  aws_sg       보안그룹 1개 (기본 보안그룹 여부, 규칙 수)
  aws_subnet   서브넷 1개 (DB 서브넷 여부, 인터넷으로 나가는 경로)
  aws_db       RDS 인스턴스 1개 (공인 접근 허용 여부)

DB 서브넷·DB 보안그룹은 태그가 아니라 RDS 인스턴스가 실제로 쓰는 것으로 정한다 (태그는 틀릴 수 있음).
"""
from __future__ import annotations

import json
from typing import Any

from ..model import Observation
from .crypto import db_crypto_fields
from .logging import db_backup_fields

REMOTE_ADMIN = {22: "SSH", 3389: "원격 데스크톱(RDP)"}
INSECURE = {20: "FTP 데이터", 21: "FTP", 23: "Telnet", 69: "TFTP", 512: "rexec", 513: "rlogin", 514: "rsh"}
WORLD = {"0.0.0.0/0", "::/0"}

FILES = {"sg": "ec2_security_groups.json", "subnet": "ec2_subnets.json",
         "rt": "ec2_route_tables.json", "rds": "rds_db_instances.json"}


def _load(f: dict[str, bytes], name: str) -> list | None:
    if name not in f:
        return None
    body = json.loads(f[name])
    return None if isinstance(body, dict) and "Error" in body else body


def _ports(p: dict) -> tuple[str, int | None, int | None]:
    proto = str(p.get("IpProtocol", "-1"))
    if proto in ("-1", "all"):
        return "all", 0, 65535
    return proto, p.get("FromPort"), p.get("ToPort")


def _covers(lo: int | None, hi: int | None, port: int) -> bool:
    return lo is not None and hi is not None and lo <= port <= hi


def network_observations(aid: str, f: dict[str, bytes], sha: dict[str, str], src: dict) -> list[Observation]:
    sgs, subnets, rts, dbs = (_load(f, FILES[k]) for k in ("sg", "subnet", "rt", "rds"))
    obs: list[Observation] = []

    def o(kind: str, oid: str, subject: str, values: dict, files: list[str], api: str) -> Observation:
        return Observation(obs_id=f"aws:{aid}:{oid}", axis="technical", kind=kind, subject=subject,
                           values={"account_id": aid, **values}, extractor=src["source"],
                           source={**src, "sha256": [sha[f"{aid}/{x}"] for x in files if f"{aid}/{x}" in sha],
                                   "api": api})

    db_sgs: dict[str, list[str]] = {}
    db_subnets: dict[str, list[str]] = {}
    for d in dbs or []:
        name = d["DBInstanceIdentifier"]
        for g in d.get("VpcSecurityGroups", []):
            db_sgs.setdefault(g["VpcSecurityGroupId"], []).append(name)
        for s in (d.get("DBSubnetGroup") or {}).get("Subnets", []):
            db_subnets.setdefault(s["SubnetIdentifier"], []).append(name)
        obs.append(o("aws_db", f"rds:{name}", f"{aid}/{name}", {
            "key": f"{aid}/{name}", "db": name, "engine": d.get("Engine"),
            "publicly_accessible": bool(d.get("PubliclyAccessible")),
            "security_groups": sorted(g["VpcSecurityGroupId"] for g in d.get("VpcSecurityGroups", [])),
            **db_crypto_fields(d, aid),
            **db_backup_fields(d),
        }, [FILES["rds"]], "rds:DescribeDBInstances"))

    names = {g["GroupId"]: g.get("GroupName", g["GroupId"]) for g in sgs or []}
    for g in sgs or []:
        gid, gname = g["GroupId"], g.get("GroupName", g["GroupId"])
        ingress, egress = g.get("IpPermissions", []), g.get("IpPermissionsEgress", [])
        obs.append(o("aws_sg", f"sg:{gid}", f"{aid}/{gid}", {
            "key": f"{aid}/{gid}", "group_id": gid, "group_name": gname, "vpc_id": g.get("VpcId"),
            "is_default": gname == "default", "rule_count": len(ingress) + len(egress),
            "ingress_count": len(ingress), "egress_count": len(egress),
        }, [FILES["sg"]], "ec2:DescribeSecurityGroups"))
        for i, p in enumerate(ingress):
            proto, lo, hi = _ports(p)
            sources: list[tuple[str, str]] = [(r["CidrIp"], "cidr") for r in p.get("IpRanges", [])]
            sources += [(r["CidrIpv6"], "cidr") for r in p.get("Ipv6Ranges", [])]
            sources += [(r["GroupId"], "sg") for r in p.get("UserIdGroupPairs", [])]
            sources += [(r["PrefixListId"], "prefix_list") for r in p.get("PrefixListIds", [])]
            port_text = "전체 포트" if proto == "all" else (f"{proto}/{lo}" if lo == hi else f"{proto}/{lo}-{hi}")
            tcp = proto in ("tcp", "all", "6")
            admin = [n for port, n in REMOTE_ADMIN.items() if tcp and _covers(lo, hi, port)]
            # 평문 프로토콜은 그 포트를 지정해 연 규칙만 본다 (전체 포트 허용은 기본 보안그룹·영역 분리 규칙에서 다룸)
            insecure = [n for port, n in INSECURE.items()
                        if proto != "all" and (tcp or proto in ("udp", "17")) and _covers(lo, hi, port)]
            for s, stype in sources:
                shown = names.get(s, s) if stype == "sg" else s
                obs.append(o("aws_sg_rule", f"sg:{gid}:in{i}:{s}", f"{aid}/{gid}({gname}) ← {shown} {port_text}", {
                    "key": f"{aid}/{gid}", "group_id": gid, "group_name": gname, "protocol": proto,
                    "from_port": lo, "to_port": hi, "ports": port_text,
                    "source": s, "source_name": shown, "source_type": stype, "world": s in WORLD,
                    "source_label": f"인터넷 전체({s})" if s in WORLD else shown,
                    "remote_admin": bool(admin), "remote_admin_service": "·".join(admin),
                    "insecure": bool(insecure), "insecure_service": "·".join(insecure),
                    "db_target": gid in db_sgs, "db_instances": sorted(db_sgs.get(gid, [])),
                }, [FILES["sg"]], "ec2:DescribeSecurityGroups"))

    if subnets is not None and rts is not None:
        main = {r["VpcId"]: r for r in rts if any(a.get("Main") for a in r.get("Associations", []))}
        by_subnet = {a["SubnetId"]: r for r in rts for a in r.get("Associations", []) if a.get("SubnetId")}
        for s in subnets:
            sid = s["SubnetId"]
            rt = by_subnet.get(sid) or main.get(s.get("VpcId"))
            out = [r for r in (rt or {}).get("Routes", [])
                   if r.get("DestinationCidrBlock") == "0.0.0.0/0" or r.get("DestinationIpv6CidrBlock") == "::/0"]
            target = next((r.get("GatewayId") or r.get("NatGatewayId") or r.get("TransitGatewayId") or "")
                          for r in out) if out else ""
            internet = target.startswith(("igw-", "nat-", "eigw-"))
            tags = {t["Key"]: t["Value"] for t in s.get("Tags", [])}
            obs.append(o("aws_subnet", f"subnet:{sid}", f"{aid}/{sid}", {
                "key": f"{aid}/{sid}", "subnet_id": sid, "name": tags.get("Name", sid), "vpc_id": s.get("VpcId"),
                "cidr": s.get("CidrBlock"), "db_subnet": sid in db_subnets, "db_instances": sorted(db_subnets.get(sid, [])),
                "route_table": (rt or {}).get("RouteTableId"), "internet_route": internet,
                "internet_target": target or "",
            }, [FILES["subnet"], FILES["rt"]], "ec2:DescribeSubnets+ec2:DescribeRouteTables"))
    return obs
