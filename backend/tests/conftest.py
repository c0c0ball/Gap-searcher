import json
import shutil
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCENARIO = REPO / "scenarios" / "a-corp-dev"


@pytest.fixture
def scenario(tmp_path) -> Path:
    """개발 시나리오 사본. 테스트마다 한 곳씩 바꿔서 쓴다."""
    dst = tmp_path / "a-corp-dev"
    shutil.copytree(SCENARIO, dst, ignore=shutil.ignore_patterns("terraform"))
    return dst


def edit_json(path: Path, fn):
    data = json.loads(path.read_text())
    fn(data)  # 제자리 수정. 반환값은 무시한다 (pop 등의 반환값으로 덮어쓰지 않도록)
    path.write_text(json.dumps(data, indent=2))


def edit_yaml(path: Path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def edit_csv(path: Path, fn):
    """credential report 같은 CSV를 행 단위로 고친다. fn(rows)는 행 목록을 제자리에서 바꾸거나 지운다."""
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    head = list(rows[0].keys())
    fn(rows)
    buf = io.StringIO()
    w = csv.DictWriter(buf, head, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue())


def edit_xlsx(path: Path, fn):
    """증적 엑셀의 첫 시트를 행(dict) 목록으로 고친다."""
    from openpyxl import Workbook, load_workbook
    ws = load_workbook(path).active
    rows = list(ws.iter_rows(values_only=True))
    head = list(rows[0])
    recs = [dict(zip(head, r)) for r in rows[1:]]
    fn(recs)
    wb = Workbook()
    out = wb.active
    out.title = ws.title
    out.append(head)
    for r in recs:
        out.append([r.get(h) for h in head])
    wb.save(path)


def fix_iam(sc: Path):
    """2단계(IAM) 결함 D6~D15를 모두 고친 상태로 만든다."""
    prod, stg = sc / "aws-snapshot/111111111111", sc / "aws-snapshot/222222222222"

    def no_direct(d):            # D6
        for u in d["UserDetailList"]:
            if u["UserName"] == "ops-kim":
                u["AttachedManagedPolicies"] = []
    edit_json(prod / "iam_authorization.json", no_direct)

    def prod_rows(rows):         # D11 MFA, D13 퇴직자 회수
        for r in rows:
            if r["user"] == "dev-park":
                r["mfa_active"] = "true"
            if r["user"] == "intern-jung":
                r["password_enabled"] = "false"
    edit_csv(prod / "credential_report.csv", prod_rows)

    def stg_rows(rows):          # D7·D8 공용 admin 삭제, D12 루트 MFA, D14 장기 미사용 키 비활성
        rows[:] = [r for r in rows if r["user"] != "admin"]
        for r in rows:
            if r["user"] == "<root_account>":
                r["mfa_active"] = "true"
            if r["user"] == "svc-legacy-etl":
                r["access_key_1_active"] = "false"
    edit_csv(stg / "credential_report.csv", stg_rows)
    edit_json(stg / "login_profiles.json", lambda d: d.pop("admin"))

    ev = sc / "evidence"

    def ledger(recs):            # D8 공용 계정 행 정리, D10 유지보수 기한
        recs[:] = [r for r in recs if r["IAM 사용자"] != "admin"]
        for r in recs:
            if r["IAM 사용자"] == "vendor-maint":
                r["사용기한"] = "2026-12-31"
    edit_xlsx(ev / "계정목록_AWS_2026-11-01.xlsx", ledger)
    edit_xlsx(ev / "특수권한자목록_2026-10.xlsx", lambda recs: recs.append(   # D9 승인 후 목록 등재
        {"AWS 계정": "a-prod", "IAM 사용자": "dev-choi", "권한": "AdministratorAccess",
         "승인자": "정보보호팀장", "승인일": "2026-10-31", "비고": "배포 담당"}))
    edit_xlsx(ev / "접근권한검토기록_2026.xlsx", lambda recs: recs.append(    # D15 3분기 검토
        {"검토일": "2026-09-30", "검토자": "정보보호팀 박○○", "범위": "AWS 3개 계정", "결과": "이상 없음"}))


def fix_network(sc: Path):
    """네트워크(2.6) 결함 D16~D21을 모두 고친 상태로 만든다."""
    prod, stg = sc / "aws-snapshot/111111111111", sc / "aws-snapshot/222222222222"
    edit_json(stg / "rds_db_instances.json", lambda d: d[0].update(PubliclyAccessible=False))   # D16

    def stg_sg(groups):
        groups[:] = [g for g in groups if g["GroupName"] != "stg-legacy-ftp"]                    # D18
        for g in groups:
            if g["GroupName"] == "default":                                                      # D17
                g["IpPermissions"], g["IpPermissionsEgress"] = [], []
    edit_json(stg / "ec2_security_groups.json", stg_sg)

    def prod_sg(groups):
        for g in groups:
            if g["GroupName"] == "prod-db":                                                      # D19
                g["IpPermissions"] = [p for p in g["IpPermissions"] if not p["IpRanges"]]
            if g["GroupName"] == "prod-bastion":                                                 # D20
                g["IpPermissions"][0]["IpRanges"] = [{"CidrIp": "203.0.113.0/28"}]
    edit_json(prod / "ec2_security_groups.json", prod_sg)

    def prod_rt(tables):                                                                         # D21
        for t in tables:
            if t["RouteTableId"] == "rtb-0a1db000000001":
                t["Routes"] = [r for r in t["Routes"] if r.get("DestinationCidrBlock") != "0.0.0.0/0"]
    edit_json(prod / "ec2_route_tables.json", prod_rt)
