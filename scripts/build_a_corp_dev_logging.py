"""a-corp-dev 시나리오의 로그·백업 단계(2.5.6 확인사항 1, 2.9.3~2.9.5, 2.12.2) 데이터를 만든다. 멱등.

    python scripts/build_a_corp_dev_logging.py

만드는 것
- docs/A사_운영보안지침_v1.0.docx (A-ISG-008) — 다른 지침과 같은 양식
- 스냅샷: cloudtrail_trails, guardduty, backup_plans, 로그 버킷(수명주기), RDS 백업 보관일
- 증적: 접속기록 점검 기록, 백업 복구 테스트 기록. 재해 복구 훈련 기록은 일부러 내지 않는다 (판단 못함 확인용)

심는 결함 D30~D38 (자세한 내용은 expected/dev_expected.yaml)
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import docx
from docx.text.paragraph import Paragraph

sys.path.insert(0, str(Path(__file__).parent))
from build_a_corp_dev_crypto import _sheet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "a-corp-dev"
SNAP = SC / "aws-snapshot"
PROD, STG, SHARED = "111111111111", "222222222222", "333333333333"
REGION, DR_REGION = "ap-northeast-2", "ap-northeast-1"


def trail(acct, name, logging, multi, global_events, validation, bucket):
    return {"Name": name, "TrailARN": f"arn:aws:cloudtrail:{REGION}:{acct}:trail/{name}", "HomeRegion": REGION,
            "IsMultiRegionTrail": multi, "IncludeGlobalServiceEvents": global_events,
            "LogFileValidationEnabled": validation, "S3BucketName": bucket,
            "Status": {"IsLogging": logging},
            "EventSelectors": [{"ReadWriteType": "All", "IncludeManagementEvents": True, "DataResources": []}]}


TRAILS = {
    PROD: [trail(PROD, "a-prod-audit", True, True, True, True, "a-prod-cloudtrail-logs")],
    # D30: 스테이징 감사 로그 기록이 멈춰 있음 (비용 절감 중 중지 후 재개 안 함) → 2.9.4-01, 2.5.6-03
    STG: [trail(STG, "a-stg-audit", False, True, True, True, "a-stg-cloudtrail-logs")],
    # D31: 단일 리전, 전역 서비스 이벤트 제외 → IAM 변경이 남지 않음 (2.5.6-03)
    # D32: 로그 파일 무결성 검증 꺼짐 (2.9.4-02)
    SHARED: [trail(SHARED, "a-shared-audit", True, False, False, False, "a-shared-cloudtrail-logs")],
}
LOG_BUCKETS = {
    # D33: 감사 로그 버킷이 1년 뒤 삭제 — 지침은 2년 이상 보관 (2.9.4-03)
    PROD: ("a-prod-cloudtrail-logs", [{"ID": "expire", "Status": "Enabled", "Filter": {"Prefix": ""},
                                       "Expiration": {"Days": 365}}]),
    STG: ("a-stg-cloudtrail-logs", [{"ID": "expire", "Status": "Enabled", "Filter": {"Prefix": ""},
                                     "Expiration": {"Days": 800}}]),
    # 함정: 수명주기 규칙이 없으면 계속 보관 — 보관기간 충족
    SHARED: ("a-shared-cloudtrail-logs", []),
}
# D34: a-shared 계정에 이상 행위 탐지(GuardDuty)가 없음 (2.9.5-01)
GUARDDUTY = {PROD: [{"DetectorId": "d0a1", "Status": "ENABLED"}],
             STG: [{"DetectorId": "d0b2", "Status": "ENABLED"}], SHARED: []}


def plan(name, copy_to=None, keep=35):
    rule = {"RuleName": "daily", "TargetBackupVaultName": "Default", "ScheduleExpression": "cron(0 18 * * ? *)",
            "Lifecycle": {"DeleteAfterDays": keep}, "CopyActions": []}
    if copy_to:
        rule["CopyActions"] = [{"DestinationBackupVaultArn": f"arn:aws:backup:{copy_to}:111111111111:backup-vault:dr",
                                "Lifecycle": {"DeleteAfterDays": keep}}]
    return {"BackupPlanName": name, "Rules": [rule]}


# D35: 운영 계정 백업 계획에 다른 리전 복사가 없음 (2.9.3-02)
BACKUP = {PROD: [plan("prod-daily")], STG: [plan("stg-weekly", keep=14)], SHARED: []}
# D36: 운영 주문 DB(중요도 상) 자동 백업 보관 3일 — 지침은 7일 이상 (2.9.3-01)
# 함정: 스테이징 DB(중요도 중)는 1일이지만 지침 대상(중요도 상)이 아님
RDS_RETENTION = {PROD: 3, STG: 1}


def write_snapshot() -> None:
    for acct in (PROD, STG, SHARED):
        d = SNAP / acct
        (d / "cloudtrail_trails.json").write_text(json.dumps(TRAILS[acct], indent=2) + "\n")
        (d / "guardduty.json").write_text(json.dumps(GUARDDUTY[acct], indent=2) + "\n")
        (d / "backup_plans.json").write_text(json.dumps(BACKUP[acct], indent=2) + "\n")
        p = d / "s3_buckets.json"
        bs = [b for b in json.loads(p.read_text()) if b["Name"] != LOG_BUCKETS[acct][0]]
        name, lc = LOG_BUCKETS[acct]
        bs.append({"Name": name, "Region": REGION, "Lifecycle": lc, "Encryption": [
            {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}, "BucketKeyEnabled": False}]})
        p.write_text(json.dumps(bs, indent=2) + "\n")
        if acct in RDS_RETENTION:
            p = d / "rds_db_instances.json"
            dbs = json.loads(p.read_text())
            for db in dbs:
                db["BackupRetentionPeriod"] = RDS_RETENTION[acct]
            p.write_text(json.dumps(dbs, indent=2) + "\n")
    m = json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))
    for a in m["accounts"]:
        a["files"] = sorted(x.name for x in (SNAP / a["account_id"]).iterdir())
    (SNAP / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_evidence() -> None:
    ev = SC / "evidence"
    # D37: 접속기록 점검이 8월 31일 뒤로 없음 — 지침은 월 1회 (2.9.5-02)
    _sheet(ev / "접속기록점검기록_2026.xlsx", "접속기록 점검",
           ["점검일", "점검자", "대상 시스템", "결과", "조치"], [
               ["2026-06-30", "정보보호팀 박○○", "쇼핑몰 관리자 페이지", "이상 없음", None],
               ["2026-07-31", "정보보호팀 박○○", "쇼핑몰 관리자 페이지", "새벽 대량 조회 1건", "사유 확인 완료"],
               ["2026-08-31", "정보보호팀 박○○", "쇼핑몰 관리자 페이지", "이상 없음", None],
           ])
    # D38: 복구 테스트를 2025년 12월 뒤로 하지 않음 — 지침은 반기 1회 (2.9.3-03)
    _sheet(ev / "백업복구테스트기록_2025-2026.xlsx", "복구 테스트",
           ["시험일", "대상", "결과", "확인자", "소요 시간"], [
               ["2025-06-12", "운영 주문 DB 스냅샷 복원", "성공", "운영팀장", "42분"],
               ["2025-12-10", "운영 주문 DB 스냅샷 복원", "성공", "운영팀장", "38분"],
           ])


CLAUSES = [
    ("Heading 1", "제1장 총칙"),
    ("Heading 2", "제1조(목적)"),
    ("Normal", "이 지침은 정보보호 정책서 제4조에 따라 로그 관리, 이상 행위 점검, 백업과 재해 복구 기준을 정함을 목적으로 한다."),
    ("Heading 2", "제2조(적용범위)"),
    ("Normal", "이 지침은 회사가 운영하는 클라우드(AWS) 계정과 개인정보처리시스템에 적용한다."),
    ("Heading 1", "제2장 로그 관리와 점검"),
    ("Heading 2", "제3조(로그 기록과 보관)"),
    ("Normal", "① 모든 클라우드 계정은 감사 로그(CloudTrail)를 모든 리전에서 기록한다."),
    ("Normal", "② 감사 로그는 무결성 검증 기능을 켜서 위·변조 여부를 확인할 수 있게 한다."),
    ("Normal", "③ 개인정보처리시스템 접속기록과 감사 로그는 2년 이상 보관한다."),
    ("Heading 2", "제4조(로그 점검)"),
    ("Normal", "① 개인정보처리시스템 접속기록은 월 1회 이상 점검하고 그 결과를 정보보호최고책임자에게 보고한다."),
    ("Normal", "② 클라우드 이상 행위 탐지 서비스(GuardDuty)를 모든 계정에서 사용하고, 탐지 결과는 정보보호팀이 확인한다."),
    ("Heading 1", "제3장 백업과 재해 복구"),
    ("Heading 2", "제5조(백업)"),
    ("Normal", "① 중요도 '상' 데이터베이스는 매일 자동 백업하고 백업은 7일 이상 보관한다."),
    ("Normal", "② 중요도 '상' 자원의 백업은 재해에 대비하여 다른 리전에 복사본을 둔다."),
    ("Normal", "③ 백업 복구 테스트는 반기 1회 이상 실시하고 결과를 기록한다."),
    ("Heading 2", "제6조(재해 복구)"),
    ("Normal", "재해 복구 훈련은 연 1회 이상 실시하고 결과를 정보보호최고책임자에게 보고한다."),
    ("Heading 1", "부칙"),
    ("Normal", "1. 이 지침은 2026년 6월 1일부터 시행한다."),
]


def write_docs() -> None:
    src = SC / "docs" / "A사_접근통제지침_v2.1.docx"
    dst = SC / "docs" / "A사_운영보안지침_v1.0.docx"
    d = docx.Document(src)
    styles = {n: next(p.style for p in d.paragraphs if p.style.name == n) for n in ("Normal", "Heading 1", "Heading 2")}
    body = d.element.body
    for el in list(body)[5:]:
        if not el.tag.endswith("sectPr"):
            body.remove(el)
    d.paragraphs[1].runs[0].text = "운영보안 지침"
    for r in d.paragraphs[1].runs[1:]:
        r.text = ""
    meta = {"문서번호": "A-ISG-008", "버전": "v1.0", "시행일": "2026-06-01"}
    for row in d.tables[0].rows:
        if row.cells[0].text in meta:
            row.cells[1].paragraphs[0].runs[0].text = meta[row.cells[0].text]
    hist = d.tables[1]
    for row in list(hist.rows)[2:]:
        hist._tbl.remove(row._tr)
    for cell, text in zip(hist.rows[1].cells, ["v1.0", "2026-05-20", "최초 제정", "정보보호팀장"]):
        cell.paragraphs[0].runs[0].text = text
    for style, text in CLAUSES:
        p = d.add_paragraph(text, style=styles[style])
        if style.startswith("Heading"):
            for r in p.runs:
                r.bold = True
    sect = next((el for el in body if el.tag.endswith("sectPr")), None)
    if sect is not None:
        body.remove(sect)
        body.append(sect)
    d.save(dst)

    pol = SC / "docs" / "A사_정보보호정책서_v1.0.docx"
    pd = docx.Document(pol)
    if not any("A-ISG-008" in p.text for p in pd.paragraphs):
        last = next(p for p in pd.paragraphs if p.text.startswith("4. 암호통제 지침"))
        new = copy.deepcopy(last._p)
        last._p.addnext(new)
        np = Paragraph(new, last._parent)
        np.runs[0].text = "5. 운영보안 지침 (A-ISG-008)"
        for r in np.runs[1:]:
            r.text = ""
        pd.save(pol)


def write_scope() -> None:
    p = SC / "scope.yaml"
    text = p.read_text(encoding="utf-8")
    if "A사_운영보안지침" not in text:
        text = text.replace(
            "  - {file: docs/A사_암호통제지침_v1.0.docx, doc_id: A-ISG-006}",
            "  - {file: docs/A사_암호통제지침_v1.0.docx, doc_id: A-ISG-006}\n"
            "  - {file: docs/A사_운영보안지침_v1.0.docx, doc_id: A-ISG-008}")
        text = text.replace(
            "  - {file: evidence/암호키관리대장_2026.xlsx, kind: key_ledger}",
            "  - {file: evidence/암호키관리대장_2026.xlsx, kind: key_ledger}\n"
            "  - {file: evidence/접속기록점검기록_2026.xlsx, kind: access_log_review}\n"
            "  - {file: evidence/백업복구테스트기록_2025-2026.xlsx, kind: restore_test_log}\n"
            "  # 재해 복구 훈련 기록은 제출되지 않음 (2.12.2 는 '판단 못함'이 정상)")
        p.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    write_snapshot()
    write_evidence()
    write_docs()
    write_scope()
    print("a-corp-dev 로그·백업 단계 데이터 생성 완료", file=sys.stderr)
