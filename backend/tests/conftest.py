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


def fix_crypto(sc: Path):
    """암호화(2.7) 결함 D22~D29를 모두 고친 상태로 만든다."""
    prod, stg = sc / "aws-snapshot/111111111111", sc / "aws-snapshot/222222222222"
    stg_key = "arn:aws:kms:ap-northeast-2:222222222222:key/2b2b2b2b-0000-4000-8000-000000000001"
    edit_json(stg / "rds_db_instances.json", lambda d: d[0].update(StorageEncrypted=True, KmsKeyId=stg_key))  # D22
    edit_json(prod / "ec2_volumes.json", lambda vs: [v.update(                                                  # D23
        Encrypted=True, KmsKeyId="arn:aws:kms:ap-northeast-2:111111111111:key/1a1a1a1a-0000-4000-8000-000000000001")
        for v in vs if v["VolumeId"] == "vol-0a1batch0000001"])
    edit_json(prod / "s3_buckets.json", lambda bs: [b.update(Encryption=[{"ApplyServerSideEncryptionByDefault": {  # D24
        "SSEAlgorithm": "aws:kms", "KMSMasterKeyID": "alias/prod-data"}}]) for b in bs if b["Name"] == "a-prod-member-exports"])
    edit_json(prod / "kms_keys.json", lambda ks: [k.update(KeyRotationEnabled=True)                               # D25
                                                  for k in ks if k["KeyManager"] == "CUSTOMER"])
    edit_json(stg / "kms_keys.json", lambda ks: ks.pop(1))                                                       # D26 (임시 키 삭제)
    edit_json(stg / "ec2_volumes.json", lambda vs: vs[0].update(KmsKeyId=stg_key))                                # D27

    def prod_lb(lbs):                                                                                           # D28
        for li in lbs[0]["Listeners"]:
            if li["Port"] == 80:
                li["DefaultActions"] = [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443"}}]
    edit_json(prod / "elbv2_listeners.json", prod_lb)
    edit_json(stg / "elbv2_listeners.json", lambda lbs: lbs[0]["Listeners"][0].update(                         # D29
        SslPolicy="ELBSecurityPolicy-TLS13-1-2-2021-06"))
    edit_json(stg / "elbv2_ssl_policies.json", lambda ps: ps.append(
        {"Name": "ELBSecurityPolicy-TLS13-1-2-2021-06", "SslProtocols": ["TLSv1.2", "TLSv1.3"]}))


def fix_logging(sc: Path):
    """로그·백업 결함 D30~D38을 고치고 재해 복구 훈련 기록(G1)을 제출한 상태로 만든다."""
    prod, stg, shared = (sc / f"aws-snapshot/{a}" for a in ("111111111111", "222222222222", "333333333333"))
    edit_json(stg / "cloudtrail_trails.json", lambda ts: ts[0]["Status"].update(IsLogging=True))          # D30
    edit_json(shared / "cloudtrail_trails.json", lambda ts: ts[0].update(                                 # D31, D32
        IsMultiRegionTrail=True, IncludeGlobalServiceEvents=True, LogFileValidationEnabled=True))
    edit_json(prod / "s3_buckets.json", lambda bs: [b.update(Lifecycle=[{"ID": "expire", "Status": "Enabled",  # D33
        "Expiration": {"Days": 1825}}]) for b in bs if b["Name"] == "a-prod-cloudtrail-logs"])
    (shared / "guardduty.json").write_text('[{"DetectorId": "d0c3", "Status": "ENABLED"}]')               # D34
    edit_json(prod / "backup_plans.json", lambda ps: ps[0]["Rules"][0].update(CopyActions=[{             # D35
        "DestinationBackupVaultArn": "arn:aws:backup:ap-northeast-1:111111111111:backup-vault:dr"}]))
    edit_json(prod / "rds_db_instances.json", lambda d: d[0].update(BackupRetentionPeriod=14))            # D36
    ev = sc / "evidence"
    edit_xlsx(ev / "접속기록점검기록_2026.xlsx", lambda rs: rs.append(                                       # D37
        {"점검일": "2026-10-30", "점검자": "정보보호팀 박○○", "대상 시스템": "쇼핑몰 관리자 페이지", "결과": "이상 없음"}))
    edit_xlsx(ev / "백업복구테스트기록_2025-2026.xlsx", lambda rs: rs.append(                                 # D38
        {"시험일": "2026-06-15", "대상": "운영 주문 DB 스냅샷 복원", "결과": "성공", "확인자": "운영팀장"}))
    from openpyxl import Workbook                                                                        # G1
    wb = Workbook()
    ws = wb.active
    ws.title = "재해 복구 훈련"
    ws.append(["훈련일", "시나리오", "결과", "보고"])
    ws.append(["2026-04-22", "서울 리전 장애 — 도쿄 리전 복구", "목표 시간 내 복구", "정보보호최고책임자 보고"])
    wb.save(ev / "재해복구훈련기록_2026.xlsx")
    edit_yaml(sc / "scope.yaml", lambda s: s["evidence"].append(
        {"file": "evidence/재해복구훈련기록_2026.xlsx", "kind": "dr_drill_log"}))


def _docx_edit(path: Path, fn):
    import docx
    d = docx.Document(path)
    fn(d)
    d.save(path)


def fix_mgmt(sc: Path):
    """관리체계 결함 D39~D45를 모두 고친 상태로 만든다."""
    docs, ev = sc / "docs", sc / "evidence"

    def approver(d):                                                                                     # D39
        for row in d.tables[0].rows:
            if row.cells[0].text == "승인자":
                row.cells[1].paragraphs[0].runs[0].text = "정보보호최고책임자"
    _docx_edit(docs / "A사_계정관리절차서_v1.3.docx", approver)

    def reviewed(d):                                                                                     # D41
        t = d.tables[1]
        row = t.add_row()
        for cell, text in zip(row.cells, ["v1.0", "2026-02-20", "정기 검토 — 하위 지침 목록 반영", "정보보호팀장"]):
            cell.text = text
    _docx_edit(docs / "A사_정보보호정책서_v1.0.docx", reviewed)

    def cite(d):                                                                                         # D44
        for p in d.paragraphs:
            if "제2023-6호" in p.text:
                p.runs[0].text = p.text.replace("제2023-6호", "제2026-9호")
                for r in p.runs[1:]:
                    r.text = ""
    _docx_edit(docs / "A사_암호통제지침_v1.0.docx", cite)
    edit_xlsx(ev / "정보보호위원회_회의록목록.xlsx", lambda rs: rs.append(                                # D40
        {"개최일": "2026-09-15", "안건": "2027년 정보보호 계획·예산", "참석자": "대표이사, CISO", "의결": "원안 의결"}))
    edit_xlsx(ev / "위험평가기록.xlsx", lambda rs: rs.append(                                              # D43
        {"평가일": "2026-08-25", "평가 범위": "AWS 3개 계정", "결과": "위험 17건", "보고": "CISO 보고"}))
    edit_xlsx(ev / "정보자산목록_2026-10.xlsx", lambda rs: rs.append(                                      # D42
        {"자산ID": "A-ST-009", "자산명": "임시 내보내기", "유형": "S3", "AWS 계정": "a-prod",
         "리소스ID": "a-prod-export-tmp-0915", "개인정보": "N", "중요도": "중", "관리자": "운영팀"}))
    edit_xlsx(ev / "개선조치관리대장_2026.xlsx", lambda rs: [                                              # D45
        r.update({"상태": "완료"}) for r in rs if r["조치번호"] in ("IA-2026-03", "IA-2026-04")])
