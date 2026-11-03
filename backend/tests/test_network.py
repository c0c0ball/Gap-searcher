"""2단계(네트워크) 테스트: 2.6.1, 2.6.2, 2.6.4, 2.6.6, 2.6.7.

정답지 일치는 test_pipeline 이 본다. 여기서는 포트·대역 계산의 경계, 대상이 0건인 경우,
자료가 빠졌을 때 '적합'으로 착각하지 않는지를 확인한다.
"""
import boto3
from botocore.stub import Stubber
from conftest import REPO, edit_json, fix_network

from gapcheck.observe.aws_collect import collect_network
from gapcheck.pipeline import run_scenario

PROD = "aws-snapshot/111111111111"
NET = ("AR-2.6.1-01", "AR-2.6.1-02", "AR-2.6.2-01", "AR-2.6.4-01", "AR-2.6.6-01", "AR-2.6.7-01")


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


def _add_rule(sc, group, perm):
    def f(gs):
        next(g for g in gs if g["GroupName"] == group)["IpPermissions"].append(perm)
    edit_json(sc / PROD / "ec2_security_groups.json", f)


def _perm(proto, lo=None, hi=None, cidr=None, v6=None):
    p = {"IpProtocol": proto, "IpRanges": [{"CidrIp": cidr}] if cidr else [],
         "Ipv6Ranges": [{"CidrIpv6": v6}] if v6 else [], "UserIdGroupPairs": [], "PrefixListIds": []}
    if proto != "-1":
        p["FromPort"], p["ToPort"] = lo, hi if hi is not None else lo
    return p


def test_all_network_rules_conforming_after_fix(scenario):
    fix_network(scenario)
    r = run_scenario(scenario, REPO)
    assert {a: decision(r, a)["verdict"] for a in NET if decision(r, a)["verdict"] != "CANDIDATE_CONFORMING"} == {}


# ── 원격 관리 포트 ────────────────────────────────────────────────────────────

def test_ipv6_world_and_all_ports_count_as_remote_admin(scenario):
    fix_network(scenario)
    _add_rule(scenario, "prod-app", _perm("tcp", 3389, v6="::/0"))
    _add_rule(scenario, "prod-alb", _perm("-1", cidr="198.51.100.0/24"))
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.6.6-01") == ["111111111111/sg-0a1alb0000000001", "111111111111/sg-0a1app0000000001"]


def test_port_range_covering_ssh_is_caught(scenario):
    fix_network(scenario)
    _add_rule(scenario, "prod-app", _perm("tcp", 20, 25, cidr="0.0.0.0/0"))
    r = run_scenario(scenario, REPO)
    assert subjects(r, "AR-2.6.6-01") == ["111111111111/sg-0a1app0000000001"]
    assert subjects(r, "AR-2.6.2-01") == ["111111111111/sg-0a1app0000000001"]   # 20~25에는 FTP·Telnet도 있음


def test_cidr_must_be_inside_admin_network(scenario):
    """관리망 /28 안의 /32는 통과, 관리망을 포함하는 더 큰 /24는 결함."""
    fix_network(scenario)
    _add_rule(scenario, "prod-app", _perm("tcp", 22, cidr="203.0.113.7/32"))
    assert subjects(run_scenario(scenario, REPO), "AR-2.6.6-01") == []
    _add_rule(scenario, "prod-app", _perm("tcp", 22, cidr="203.0.113.0/24"))
    assert subjects(run_scenario(scenario, REPO), "AR-2.6.6-01") == ["111111111111/sg-0a1app0000000001"]


def test_no_admin_network_in_policy_is_not_conforming(scenario):
    import docx
    fix_network(scenario)
    p = scenario / "docs/A사_접근통제지침_v2.1.docx"
    d = docx.Document(p)
    for para in d.paragraphs:
        if para.text.startswith("① 서버의 원격 관리"):
            para.text = "① 서버의 원격 관리는 정보보호팀이 정한 방법을 따른다."
    d.save(p)
    dec = decision(run_scenario(scenario, REPO), "AR-2.6.6-01")
    assert dec["verdict"] != "CANDIDATE_CONFORMING"


# ── DB ───────────────────────────────────────────────────────────────────────

def test_no_rds_anywhere_is_conforming(scenario):
    """DB가 하나도 없으면 DB 규칙은 대상 0건으로 통과 (판단 불가가 아님)."""
    fix_network(scenario)
    for a in ("111111111111", "222222222222", "333333333333"):
        (scenario / f"aws-snapshot/{a}/rds_db_instances.json").write_text("[]")
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.6.1-01", "AR-2.6.4-01", "AR-2.6.7-01"):
        assert decision(r, ar)["verdict"] == "CANDIDATE_CONFORMING", ar


def test_missing_network_file_is_partial_collection(scenario):
    fix_network(scenario)
    (scenario / "aws-snapshot/333333333333/ec2_security_groups.json").unlink()
    edit_json(scenario / "aws-snapshot/manifest.json", lambda m: [
        a.update(files=[f for f in a["files"] if f != "ec2_security_groups.json"])
        for a in m["accounts"] if a["account_id"] == "333333333333"])
    r = run_scenario(scenario, REPO)
    for ar in ("AR-2.6.1-02", "AR-2.6.2-01", "AR-2.6.6-01"):
        d = decision(r, ar)
        assert d["verdict"] == "INSUFFICIENT_EVIDENCE", (ar, d)
        assert d["reason_code"] == "PARTIAL_COLLECTION"


def test_db_subnet_without_association_uses_main_route_table(scenario):
    """DB 서브넷이 명시적으로 연결된 라우팅 테이블이 없으면 VPC 기본(main) 테이블을 따른다."""
    fix_network(scenario)

    def f(tables):
        for t in tables:
            if t["RouteTableId"] == "rtb-0a1db000000001":
                t["Associations"] = []
            if t["RouteTableId"] == "rtb-0a1main00000001":
                t["Routes"].append({"DestinationCidrBlock": "0.0.0.0/0", "GatewayId": "igw-0a1prod00000001"})
    edit_json(scenario / PROD / "ec2_route_tables.json", f)
    assert subjects(run_scenario(scenario, REPO), "AR-2.6.7-01") == [
        "111111111111/subnet-0a1db0000000a", "111111111111/subnet-0a1db0000000c"]


def test_db_rule_from_prefix_list_or_cidr_is_flagged_but_sg_is_not(scenario):
    fix_network(scenario)

    def f(gs):
        g = next(g for g in gs if g["GroupName"] == "prod-db")
        g["IpPermissions"].append({"IpProtocol": "tcp", "FromPort": 3306, "ToPort": 3306, "IpRanges": [],
                                   "Ipv6Ranges": [], "UserIdGroupPairs": [], "PrefixListIds": [{"PrefixListId": "pl-0abc"}]})
    edit_json(scenario / PROD / "ec2_security_groups.json", f)
    assert subjects(run_scenario(scenario, REPO), "AR-2.6.4-01") == ["111111111111/sg-0a1db00000000001"]


# ── 수집기 ───────────────────────────────────────────────────────────────────

def test_collect_network_records_errors_without_files():
    ec2 = boto3.client("ec2", region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="x")
    rds = boto3.client("rds", region_name="ap-northeast-2", aws_access_key_id="x", aws_secret_access_key="x")
    with Stubber(ec2) as se, Stubber(rds) as sr:
        se.add_response("describe_security_groups", {"SecurityGroups": [{"GroupId": "sg-1", "GroupName": "default"}]})
        se.add_response("describe_subnets", {"Subnets": []})
        se.add_client_error("describe_route_tables", "UnauthorizedOperation")
        sr.add_response("describe_db_instances", {"DBInstances": []})
        out = collect_network(ec2, rds)
    assert out["ec2_security_groups.json"][0]["GroupId"] == "sg-1"
    assert out["ec2_route_tables.json"]["Error"]["Code"] == "UnauthorizedOperation"
    assert out["rds_db_instances.json"] == []
