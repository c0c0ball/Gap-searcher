"""a-corp-dev 시나리오의 관리체계 단계(1.1.2, 1.1.3, 1.1.5, 1.2.1, 1.2.3, 1.4.1~1.4.3) 데이터를 만든다. 멱등.

    python scripts/build_a_corp_dev_mgmt.py

실행 순서: build_a_corp_dev_crypto.py → build_a_corp_dev_logging.py → 이 파일
(앞 스크립트들이 같은 문서·버킷 파일을 다시 쓰기 때문)

심는 결함 D39~D45 (자세한 내용은 expected/dev_expected.yaml)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import docx

sys.path.insert(0, str(Path(__file__).parent))
from build_a_corp_dev_crypto import _sheet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "a-corp-dev"
DOCS = SC / "docs"
PROD = "111111111111"
TMP_BUCKET = "a-prod-export-tmp-0915"


def _style(d, name):
    return next(p.style for p in d.paragraphs if p.style.name == name)


def _set_cell(cell, text):
    p = cell.paragraphs[0]
    if p.runs:
        p.runs[0].text = text
        for r in p.runs[1:]:
            r.text = ""
    else:
        p.add_run(text)


def _set_para(p, text):
    p.runs[0].text = text
    for r in p.runs[1:]:
        r.text = ""


def policy() -> None:
    """정보보호 정책서: 관리체계 조항 추가, 개정 이력은 2025-02-20 제정 뒤 손대지 않은 상태 (D41)"""
    path = DOCS / "A사_정보보호정책서_v1.0.docx"
    d = docx.Document(path)
    for row in d.tables[0].rows:
        if row.cells[0].text == "시행일":
            _set_cell(row.cells[1], "2025-03-01")
    for row in d.tables[1].rows[1:]:
        if row.cells[0].text == "v1.0":
            _set_cell(row.cells[1], "2025-02-20")
    for p in d.paragraphs:
        if p.text.startswith("1. 이 정책은"):
            _set_para(p, "1. 이 정책은 2025년 3월 1일부터 시행한다.")
    if any(p.text.startswith("제6조(정책 승인)") for p in d.paragraphs):
        d.save(path)
        return
    anchor = next(p for p in d.paragraphs if p.text.strip().startswith("부칙"))
    items = [
        ("Heading 2", "제6조(정책 승인)"),
        ("Normal", "이 정책과 하위 지침은 정보보호최고책임자 또는 대표이사의 승인을 받아 시행한다."),
        ("Heading 2", "제7조(정보보호위원회)"),
        ("Normal", "회사는 대표이사를 위원장으로 하는 정보보호위원회를 두며, 위원회는 연 1회 이상 개최하여 정보보호 계획과 예산 등 주요 사항을 심의·의결한다."),
        ("Heading 2", "제8조(정보자산 관리)"),
        ("Normal", "회사는 클라우드 자원을 포함한 모든 정보자산을 식별하여 정보자산 목록으로 관리하고, 자산이 생기거나 바뀌면 지체 없이 목록을 갱신한다."),
        ("Heading 2", "제9조(위험 관리)"),
        ("Normal", "정보보호팀은 연 1회 이상 위험평가를 수행하고 그 결과를 정보보호최고책임자에게 보고한다."),
        ("Heading 2", "제10조(관리체계 점검과 개선)"),
        ("Normal", "① 회사는 점검 대상 업무와 독립된 인력으로 연 1회 이상 관리체계 점검(내부 감사)을 실시한다."),
        ("Normal", "② 점검에서 발견된 문제는 기한을 정하여 조치하고 개선조치 관리대장으로 이행 여부를 관리한다."),
    ]
    for style, text in items:
        new = anchor.insert_paragraph_before(text, style=_style(d, style))
        if style.startswith("Heading"):
            for r in new.runs:
                r.bold = True
    d.save(path)


def citations() -> None:
    """지침 제1조의 법령 인용: 암호통제 지침은 폐지된 고시 번호(D44), 운영보안 지침은 현행 번호(함정)"""
    for name, notice in (("A사_암호통제지침_v1.0.docx", "제2023-6호"), ("A사_운영보안지침_v1.0.docx", "제2026-9호")):
        path = DOCS / name
        d = docx.Document(path)
        p = next(p for p in d.paragraphs if p.text.startswith("이 지침은 정보보호 정책서 제4조"))
        if "안전성 확보조치 기준" not in p.text:
            _set_para(p, p.text.replace(
                "이 지침은 정보보호 정책서 제4조에 따라",
                f"이 지침은 정보보호 정책서 제4조와 「개인정보의 안전성 확보조치 기준」(개인정보보호위원회 고시 {notice})에 따라"))
            d.save(path)


def evidence() -> None:
    ev = SC / "evidence"
    # D40: 정보보호위원회가 2025-09-10 뒤로 열리지 않음 — 정책은 연 1회
    _sheet(ev / "정보보호위원회_회의록목록.xlsx", "정보보호위원회",
           ["개최일", "안건", "참석자", "의결"], [
               ["2024-09-12", "2025년 정보보호 계획·예산", "대표이사, CISO, 개발·운영·QA팀장", "원안 의결"],
               ["2025-09-10", "2026년 정보보호 계획·예산, ISMS-P 준비", "대표이사, CISO, 개발·운영·QA팀장", "원안 의결"],
           ])
    # D43: 위험평가가 2025-08-20 뒤로 없음 — 정책은 연 1회
    _sheet(ev / "위험평가기록.xlsx", "위험평가",
           ["평가일", "평가 범위", "결과", "보고"], [
               ["2024-08-20", "AWS 3개 계정, 쇼핑몰 서비스", "위험 23건 (수용 불가 5)", "CISO 보고"],
               ["2025-08-20", "AWS 3개 계정, 쇼핑몰 서비스", "위험 19건 (수용 불가 4)", "CISO 보고"],
           ])
    # 함정: 내부 감사는 2026-05-15 — 연 1회 충족
    _sheet(ev / "내부감사기록.xlsx", "내부 감사",
           ["감사일", "감사인", "범위", "결과"], [
               ["2025-05-14", "외부 감사인 (가상 컨설팅)", "관리체계 전 영역", "지적 6건"],
               ["2026-05-15", "외부 감사인 (가상 컨설팅)", "관리체계 전 영역", "지적 4건"],
           ])
    # D45: 기한이 지났는데 끝나지 않은 개선조치 2건. 함정: 기한 지났지만 완료, 진행 중이지만 기한 전
    _sheet(ev / "개선조치관리대장_2026.xlsx", "개선조치",
           ["조치번호", "발견사항", "담당", "완료예정일", "상태", "출처"], [
               ["IA-2026-01", "정보보호 정책서 정기 검토 미이행", "정보보호팀", "2026-12-31", "진행중", "2026 내부 감사"],
               ["IA-2026-02", "퇴직자 계정 회수 지연", "운영팀", "2026-07-31", "완료", "2026 내부 감사"],
               ["IA-2026-03", "접근권한 분기 검토 누락", "정보보호팀", "2026-09-30", "진행중", "2026 내부 감사"],
               ["IA-2026-04", "백업 복구 테스트 미실시", "운영팀", "2026-08-31", "미착수", "2026 내부 감사"],
           ])
    # 정보자산 목록: 감사 로그 버킷 3개를 추가 등록 (임시 내보내기 버킷은 빠져 있음 — D42)
    from openpyxl import load_workbook
    p = ev / "정보자산목록_2026-10.xlsx"
    wb = load_workbook(p)
    ws = wb.active
    have = {r[0] for r in ws.iter_rows(min_row=2, values_only=True)}
    for row in (["A-ST-006", "감사 로그(운영)", "S3", "a-prod", "a-prod-cloudtrail-logs", "N", "중", "정보보호팀"],
                ["A-ST-007", "감사 로그(스테이징)", "S3", "a-stg", "a-stg-cloudtrail-logs", "N", "중", "정보보호팀"],
                ["A-ST-008", "감사 로그(공용)", "S3", "a-shared", "a-shared-cloudtrail-logs", "N", "중", "정보보호팀"]):
        if row[0] not in have:
            ws.append(row)
    wb.save(p)


def snapshot() -> None:
    """D42: 9월에 회원 데이터를 임시로 내보낸 버킷이 남아 있고 정보자산 목록에 없음"""
    p = SC / "aws-snapshot" / PROD / "s3_buckets.json"
    bs = [b for b in json.loads(p.read_text()) if b["Name"] != TMP_BUCKET]
    bs.append({"Name": TMP_BUCKET, "Region": "ap-northeast-2", "Lifecycle": [], "Encryption": [
        {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}, "BucketKeyEnabled": False}]})
    p.write_text(json.dumps(bs, indent=2) + "\n")


def scope() -> None:
    p = SC / "scope.yaml"
    text = p.read_text(encoding="utf-8")
    if "정보보호위원회_회의록목록" not in text:
        text = text.replace(
            "  # 재해 복구 훈련 기록은 제출되지 않음 (2.12.2 는 '판단 못함'이 정상)",
            "  # 재해 복구 훈련 기록은 제출되지 않음 (2.12.2 는 '판단 못함'이 정상)\n"
            "  - {file: evidence/정보보호위원회_회의록목록.xlsx, kind: committee_log}\n"
            "  - {file: evidence/위험평가기록.xlsx, kind: risk_assessment_log}\n"
            "  - {file: evidence/내부감사기록.xlsx, kind: internal_audit_log}\n"
            "  - {file: evidence/개선조치관리대장_2026.xlsx, kind: improvement_tracker}")
        p.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    policy()
    citations()
    evidence()
    snapshot()
    scope()
    print("a-corp-dev 관리체계 단계 데이터 생성 완료", file=sys.stderr)
