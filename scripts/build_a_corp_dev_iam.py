"""a-corp-dev 시나리오의 IAM 단계(2.2.5, 2.5.1~2.5.6) 데이터를 만든다.

다시 실행해도 같은 결과가 나온다 (멱등). 2.5.4 파일럿의 결함(D1~D5)은 그대로 두고 D6~D16을 더한다.

    python scripts/build_a_corp_dev_iam.py

모든 회사·인물·계정은 가상이다. 사람 이름은 마스킹(박○○)해서만 쓴다.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import docx
from docx.oxml.ns import qn  # noqa: F401  (python-docx 존재 확인)
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "a-corp-dev"
SNAP = SC / "aws-snapshot"

PROD, STG, SHARED = "111111111111", "222222222222", "333333333333"
ALIAS = {PROD: "a-prod", STG: "a-stg", SHARED: "a-shared"}

HEADER = ["user", "arn", "user_creation_time", "password_enabled", "password_last_used", "password_last_changed",
          "password_next_rotation", "mfa_active", "access_key_1_active", "access_key_1_last_rotated",
          "access_key_1_last_used_date", "access_key_1_last_used_region", "access_key_1_last_used_service",
          "access_key_2_active", "access_key_2_last_rotated", "access_key_2_last_used_date",
          "access_key_2_last_used_region", "access_key_2_last_used_service", "cert_1_active",
          "cert_1_last_rotated", "cert_2_active", "cert_2_last_rotated"]

ADMIN = "arn:aws:iam::aws:policy/AdministratorAccess"
POWER = "arn:aws:iam::aws:policy/PowerUserAccess"
READ = "arn:aws:iam::aws:policy/ReadOnlyAccess"

# 사용자 정의: (이름, 만든 시각, 콘솔, 비밀번호 마지막 사용, 마지막 변경, MFA, 키 활성, 키 마지막 사용, 그룹, 직접 정책, 로그인 프로필 발급 시각)
# 2.5.4 결함과 겹치지 않도록 새 사용자는 비밀번호를 90일 안에 바꾼 것으로 둔다.
USERS: dict[str, list[dict]] = {
    PROD: [
        dict(name="admin-park", created="2025-06-12T01:00:00+00:00", console=True, used="2026-10-30T08:12:00+00:00",
             changed="2026-09-15T00:30:00+00:00", mfa=True, groups=["Admins"], lp="2025-06-12T01:00:03+00:00"),
        # D9: 특수권한자 목록에 없는 관리자 (Admins 그룹)
        dict(name="dev-choi", created="2026-02-03T05:00:00+00:00", console=True, used="2026-11-01T09:00:00+00:00",
             changed="2026-08-20T02:00:00+00:00", mfa=True, groups=["Admins"], lp="2026-02-03T05:00:04+00:00"),
        dict(name="dev-lee", created="2025-11-20T05:00:00+00:00", console=True, used="2026-10-29T10:00:00+00:00",
             changed="2026-05-01T04:00:00+00:00", mfa=True, groups=["Developers"], lp="2025-11-20T05:00:02+00:00"),
        # D6: 그룹이 아니라 사용자에게 정책을 직접 붙임
        dict(name="ops-kim", created="2026-10-01T02:00:00+00:00", console=True, used="2026-10-28T00:40:00+00:00",
             changed="2026-10-01T02:00:05+00:00", mfa=True, groups=["Operators"], direct=[READ],
             lp="2026-10-01T02:00:05+00:00"),
        # 함정: 콘솔 비밀번호가 없는 서비스 계정 — MFA 검사 대상 아님
        dict(name="svc-batch", created="2025-07-01T00:00:00+00:00", console=False, mfa=False, key=True,
             key_used="2026-11-01T18:00:00+00:00", groups=["BatchJobs"]),
        # D11: 콘솔 사용자인데 MFA 없음
        dict(name="dev-park", created="2026-09-01T01:00:00+00:00", console=True, used="2026-10-30T02:00:00+00:00",
             changed="2026-09-20T03:00:00+00:00", mfa=False, groups=["Developers"], lp="2026-09-01T01:00:04+00:00"),
        # D13: 10월 15일 퇴직했는데 계정이 살아 있음
        dict(name="intern-jung", created="2026-07-01T01:00:00+00:00", console=True, used="2026-10-14T08:00:00+00:00",
             changed="2026-08-10T01:00:00+00:00", mfa=True, groups=["Developers"], lp="2026-07-01T01:00:02+00:00"),
        # D10: 외부 유지보수 계정에 사용 기한이 없음
        dict(name="vendor-maint", created="2026-03-02T01:00:00+00:00", console=True, used="2026-08-26T05:00:00+00:00",
             changed="2026-08-25T05:00:00+00:00", mfa=True, groups=["Maintenance"], lp="2026-03-02T01:00:03+00:00"),
    ],
    STG: [
        dict(name="qa-yoon", created="2026-04-02T01:00:00+00:00", console=True, used="2026-10-31T06:00:00+00:00",
             changed="2026-10-10T01:00:00+00:00", mfa=True, groups=["QA"], lp="2026-04-02T01:00:02+00:00"),
        # D7, D8: 추측하기 쉬운 이름의 공용 계정, 공용 사용 승인 기록 없음
        dict(name="admin", created="2026-05-11T01:00:00+00:00", console=True, used="2026-10-31T09:00:00+00:00",
             changed="2026-10-05T01:00:00+00:00", mfa=True, groups=["Developers"], lp="2026-05-11T01:00:03+00:00"),
        # 함정: 10월 30일(금) 퇴직, 기준일 11월 2일(월) — 1영업일 이내라 아직 결함 아님
        dict(name="qa-seo", created="2026-03-03T01:00:00+00:00", console=True, used="2026-10-29T07:00:00+00:00",
             changed="2026-10-01T01:00:00+00:00", mfa=True, groups=["QA"], lp="2026-03-03T01:00:02+00:00"),
        # D14: 액세스 키가 206일째 쓰이지 않았는데 활성
        dict(name="svc-legacy-etl", created="2025-09-01T00:00:00+00:00", console=False, mfa=False, key=True,
             key_used="2026-04-10T03:00:00+00:00", groups=["BatchJobs"]),
    ],
    SHARED: [
        dict(name="admin-park", created="2025-06-15T01:00:00+00:00", console=True, used="2026-10-20T01:00:00+00:00",
             changed="2026-10-01T01:00:00+00:00", mfa=True, groups=["Admins"], lp="2025-06-15T01:00:02+00:00"),
        # 함정: 유지보수 계정이지만 사용 기한(2026-12-31)이 정해져 있음
        dict(name="vendor-net", created="2026-10-01T01:00:00+00:00", console=True, used="2026-10-20T04:00:00+00:00",
             changed="2026-10-15T04:00:00+00:00", mfa=True, groups=["Maintenance"], lp="2026-10-01T01:00:02+00:00"),
    ],
}
# D12: a-stg 루트 사용자에 MFA 없음
ROOT_MFA = {PROD: True, STG: False, SHARED: True}
ROOT_USED = {PROD: "2026-01-10T03:00:00+00:00", STG: "N/A", SHARED: "N/A"}

GROUPS = {
    "Admins": [ADMIN], "Developers": [POWER], "Operators": [READ], "QA": [READ],
    "BatchJobs": ["arn:aws:iam::{acct}:policy/BatchJobRunner"], "Maintenance": [READ],
}


def credential_report(acct: str) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    na = "N/A"
    w.writerow(["<root_account>", f"arn:aws:iam::{acct}:root", "2025-06-01T00:00:00+00:00", "not_supported",
                ROOT_USED[acct], "not_supported", na, str(ROOT_MFA[acct]).lower(), "false", na, na, na, na,
                "false", na, na, na, na, "false", na, "false", na])
    for u in sorted(USERS[acct], key=lambda u: u["name"]):
        key = u.get("key", False)
        w.writerow([u["name"], f"arn:aws:iam::{acct}:user/{u['name']}", u["created"],
                    str(u["console"]).lower(), u.get("used", na) if u["console"] else na,
                    u.get("changed", na) if u["console"] else na, na, str(u["mfa"]).lower(),
                    str(key).lower(), u["created"] if key else na, u.get("key_used", na) if key else na,
                    "ap-northeast-2" if key else na, "s3" if key else na,
                    "false", na, na, na, na, "false", na, "false", na])
    return buf.getvalue()


def login_profiles(acct: str) -> dict:
    return {u["name"]: {"CreateDate": u["lp"], "PasswordResetRequired": False}
            for u in sorted(USERS[acct], key=lambda u: u["name"]) if u["console"]}


def authorization(acct: str) -> dict:
    used = sorted({g for u in USERS[acct] for g in u.get("groups", [])})

    def pol(arn: str) -> dict:
        arn = arn.format(acct=acct)
        return {"PolicyName": arn.rsplit("/", 1)[1], "PolicyArn": arn}

    users = []
    for u in sorted(USERS[acct], key=lambda u: u["name"]):
        users.append({
            "UserName": u["name"], "UserId": f"AIDA{acct[:4]}{u['name'].upper().replace('-', '')[:12]}",
            "Arn": f"arn:aws:iam::{acct}:user/{u['name']}", "Path": "/", "CreateDate": u["created"],
            "GroupList": u.get("groups", []), "AttachedManagedPolicies": [pol(p) for p in u.get("direct", [])],
            "UserPolicyList": [], "Tags": [],
        })
    groups = [{"GroupName": g, "Arn": f"arn:aws:iam::{acct}:group/{g}", "Path": "/",
               "AttachedManagedPolicies": [pol(p) for p in GROUPS[g]], "GroupPolicyList": []} for g in used]
    custom = [{
        "PolicyName": "BatchJobRunner", "Arn": f"arn:aws:iam::{acct}:policy/BatchJobRunner",
        "DefaultVersionId": "v1",
        "PolicyVersionList": [{"VersionId": "v1", "IsDefaultVersion": True, "Document": {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": ["s3:GetObject", "s3:PutObject"],
                           "Resource": "arn:aws:s3:::a-batch-*/*"}]}}],
    }] if "BatchJobs" in used else []
    return {"UserDetailList": users, "GroupDetailList": groups, "RoleDetailList": [], "Policies": custom}


def write_snapshot() -> None:
    manifest = json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))
    for acct in (PROD, STG, SHARED):
        d = SNAP / acct
        (d / "credential_report.csv").write_text(credential_report(acct), encoding="utf-8")
        (d / "login_profiles.json").write_text(json.dumps(login_profiles(acct), indent=2) + "\n", encoding="utf-8")
        (d / "iam_authorization.json").write_text(json.dumps(authorization(acct), indent=2) + "\n", encoding="utf-8")
    for a in manifest["accounts"]:
        a["files"] = sorted(p.name for p in (SNAP / a["account_id"]).iterdir())
    (SNAP / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ── 증적 ──────────────────────────────────────────────────────────────────

def _sheet(path: Path, title: str, head: list[str], rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = title
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDE6F5")
    for r in rows:
        ws.append(r)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(10, max(len(str(c.value or "")) for c in col) * 1.6)
    wb.properties.creator = "A사 정보보호팀 (가상)"
    wb.save(path)


def write_evidence() -> None:
    ev = SC / "evidence"
    # 계정 관리대장: 사번으로 사람과 계정을 잇는다. 외주 인력은 P로 시작하는 협력사 번호
    _sheet(ev / "계정목록_AWS_2026-11-01.xlsx", "AWS 계정목록",
           ["계정ID", "별칭", "IAM 사용자", "사번", "용도", "콘솔 비밀번호", "승인자", "사용기한"], [
               [PROD, "a-prod", "admin-park", "A1001", "관리", "사용", "정보보호팀장", None],
               [PROD, "a-prod", "dev-choi", "A1015", "개발", "사용", "개발팀장", None],
               [PROD, "a-prod", "dev-lee", "A1012", "개발", "사용", "개발팀장", None],
               [PROD, "a-prod", "dev-park", "A1024", "개발", "사용", "개발팀장", None],
               [PROD, "a-prod", "intern-jung", "A1031", "개발(인턴)", "사용", "개발팀장", None],
               [PROD, "a-prod", "ops-kim", "A1007", "운영", "사용", "운영팀장", None],
               [PROD, "a-prod", "svc-batch", "-", "배치 서비스", "미사용", "운영팀장", None],
               [PROD, "a-prod", "vendor-maint", "P0103", "외부 유지보수", "사용", "운영팀장", None],
               [STG, "a-stg", "admin", "-", "개발 공용", "사용", None, None],
               [STG, "a-stg", "qa-seo", "A1022", "QA", "사용", "QA팀장", None],
               [STG, "a-stg", "qa-yoon", "A1020", "QA", "사용", "QA팀장", None],
               [STG, "a-stg", "svc-legacy-etl", "-", "배치 서비스(구)", "미사용", "운영팀장", None],
               [SHARED, "a-shared", "admin-park", "A1001", "관리", "사용", "정보보호팀장", None],
               [SHARED, "a-shared", "vendor-net", "P0110", "외부 유지보수", "사용", "정보보호팀장", "2026-12-31"],
           ])
    _sheet(ev / "인사목록_2026-11-01.xlsx", "인사목록",
           ["사번", "성명", "부서", "직무", "상태", "입사일", "퇴직일"], [
               ["A1001", "박○○", "정보보호팀", "보안관리자", "재직", "2025-06-01", None],
               ["A1007", "김○○", "운영팀", "운영", "재직", "2026-09-28", None],
               ["A1012", "이○○", "개발팀", "백엔드 개발", "재직", "2025-11-17", None],
               ["A1015", "최○○", "개발팀", "프론트엔드 개발", "재직", "2026-02-02", None],
               ["A1020", "윤○○", "QA팀", "QA", "재직", "2026-03-30", None],
               ["A1022", "서○○", "QA팀", "QA", "퇴직", "2026-03-02", "2026-10-30"],
               ["A1024", "박○○", "개발팀", "백엔드 개발", "재직", "2026-08-31", None],
               # 함정: 계정이 이미 회수되어 관리대장에서도 빠진 퇴직자
               ["A1009", "한○○", "운영팀", "운영", "퇴직", "2025-08-01", "2026-09-30"],
               ["A1031", "정○○", "개발팀", "인턴", "퇴직", "2026-06-30", "2026-10-15"],
           ])
    _sheet(ev / "특수권한자목록_2026-10.xlsx", "특수권한자 목록",
           ["AWS 계정", "IAM 사용자", "권한", "승인자", "승인일", "비고"], [
               ["a-prod", "admin-park", "AdministratorAccess", "정보보호팀장", "2026-03-02", "보안관리자"],
               ["a-shared", "admin-park", "AdministratorAccess", "정보보호팀장", "2026-03-02", "보안관리자"],
           ])
    _sheet(ev / "접근권한검토기록_2026.xlsx", "접근권한 검토",
           ["검토일", "검토자", "범위", "결과", "조치"], [
               ["2025-12-29", "정보보호팀 박○○", "AWS 3개 계정", "과다 권한 1건", "회수 완료"],
               ["2026-03-31", "정보보호팀 박○○", "AWS 3개 계정", "이상 없음", None],
               ["2026-06-30", "정보보호팀 박○○", "AWS 3개 계정", "장기 미사용 1건", "비활성화 완료"],
           ])


# ── 규정 문서: 조항 추가 (이미 있으면 건너뜀) ─────────────────────────────────

def _style(doc, name: str):
    """문서에 실제로 쓰인 같은 이름의 스타일 객체 (이름 조회가 안 되는 템플릿 대비)"""
    return next(p.style for p in doc.paragraphs if p.style.name == name)


def _insert_before(doc, anchor_text: str, items: list[tuple[str, str]]) -> None:
    anchor = next(p for p in doc.paragraphs if p.text.strip().startswith(anchor_text))
    for style, text in items:
        new = anchor.insert_paragraph_before(text, style=_style(doc, style))
        if style.startswith("Heading"):
            for r in new.runs:
                r.bold = True


def _after(doc, after_text: str, items: list[tuple[str, str]]) -> None:
    """after_text 문단 다음(같은 조의 다음 조 앞)에 넣는다"""
    ps = doc.paragraphs
    i = next(i for i, p in enumerate(ps) if p.text.strip().startswith(after_text))
    _insert_before(doc, ps[i + 1].text.strip(), items)


def write_docs() -> None:
    path = SC / "docs" / "A사_접근통제지침_v2.1.docx"
    d = docx.Document(path)
    text = "\n".join(p.text for p in d.paragraphs)
    if "제11조(특수권한 관리)" in text:
        return
    _after(d, "② 계정의 발급·변경·삭제는", [
        ("Normal", "③ 계정 이름은 사용자를 식별할 수 있게 정하며, admin·test처럼 추측하기 쉬운 이름을 계정 이름으로 쓰지 않는다."),
        ("Normal", "④ 업무상 불가피하게 공용 계정을 써야 하는 경우 정보보호팀장의 승인을 받고, 계정 관리대장에 승인자를 기록한다."),
    ])
    p9 = next(p for p in d.paragraphs if p.text.startswith("접근 권한은 업무 수행에 필요한"))
    p9.text = "① 접근 권한은 업무 수행에 필요한 최소한의 범위로 부여한다."
    _after(d, "① 접근 권한은 업무 수행에", [
        ("Normal", "② 접근 권한은 직무별로 정한 권한 그룹을 통하여 부여하며, 개별 사용자에게 직접 부여하지 않는다."),
    ])
    p10 = next(p for p in d.paragraphs if p.text.startswith("정보보호팀은 분기 1회 이상"))
    p10.text = "① " + p10.text
    _insert_before(d, "부칙", [
        ("Normal", "② 검토 결과 과다 부여, 장기 미사용 등 문제가 발견되면 지체 없이 권한을 회수·조정하고 그 결과를 기록한다."),
        ("Heading 2", "제11조(특수권한 관리)"),
        ("Normal", "① 관리자 권한 등 특수권한은 정보보호팀장의 승인을 받아 부여하며, 정보보호팀은 특수권한자 목록을 작성·관리한다."),
        ("Normal", "② 외부 업체의 유지보수 계정은 사용 기간을 정하여 발급하고, 기간이 끝나면 즉시 비활성화한다."),
        ("Heading 2", "제12조(장기 미사용 계정)"),
        ("Normal", "90일 이상 사용하지 않은 계정은 비활성화하고, 다시 사용하려면 계정 신청 절차를 거친다."),
    ])
    d.save(path)


if __name__ == "__main__":
    write_snapshot()
    write_evidence()
    write_docs()
    print("a-corp-dev IAM 단계 데이터 생성 완료", file=sys.stderr)
