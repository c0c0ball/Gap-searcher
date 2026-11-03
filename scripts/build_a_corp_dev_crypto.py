"""a-corp-dev 시나리오의 암호화 단계(2.7) 데이터를 만든다. 다시 실행해도 같은 결과 (멱등).

    python scripts/build_a_corp_dev_crypto.py

만드는 것
- docs/A사_암호통제지침_v1.0.docx (A-ISG-006) — 접근통제 지침과 같은 양식
- 스냅샷: ec2_volumes, s3_buckets, kms_keys, elbv2_listeners, elbv2_ssl_policies, rds 저장 암호화 필드
- 증적: 정보자산목록(개인정보 포함 여부), 암호키 관리대장

심는 결함 D22~D29 (자세한 내용은 expected/dev_expected.yaml)
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import docx
import yaml
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = Path(__file__).resolve().parents[1]
SC = ROOT / "scenarios" / "a-corp-dev"
SNAP = SC / "aws-snapshot"
PROD, STG, SHARED = "111111111111", "222222222222", "333333333333"
REGION = "ap-northeast-2"


def karn(acct: str, kid: str) -> str:
    return f"arn:aws:kms:{REGION}:{acct}:key/{kid}"


K_PROD = "1a1a1a1a-0000-4000-8000-000000000001"        # alias/prod-data (D25 자동 교체 꺼짐)
K_PROD_AWS_EBS = "1a1a1a1a-0000-4000-8000-0000000000e5"  # alias/aws/ebs (AWS 관리형 — 함정)
K_STG = "2b2b2b2b-0000-4000-8000-000000000001"         # alias/stg-data
K_STG_TEMP = "2b2b2b2b-0000-4000-8000-000000000002"    # alias/stg-temp (D26 관리대장 누락)
K_SHARED = "3c3c3c3c-0000-4000-8000-000000000001"      # alias/shared-tools


def kms(acct: str) -> list[dict]:
    def k(kid, alias, manager, rotation, desc):
        return {"KeyId": kid, "Arn": karn(acct, kid), "KeyManager": manager, "KeyState": "Enabled",
                "KeySpec": "SYMMETRIC_DEFAULT", "Aliases": [alias], "Description": desc,
                "KeyRotationEnabled": rotation}
    return {
        PROD: [k(K_PROD, "alias/prod-data", "CUSTOMER", False, "운영 데이터 암호화"),
               k(K_PROD_AWS_EBS, "alias/aws/ebs", "AWS", True, "Default key for EBS")],
        STG: [k(K_STG, "alias/stg-data", "CUSTOMER", True, "스테이징 데이터 암호화"),
              k(K_STG_TEMP, "alias/stg-temp", "CUSTOMER", True, "성능 시험용 임시 키")],
        SHARED: [k(K_SHARED, "alias/shared-tools", "CUSTOMER", True, "공용 도구 암호화")],
    }[acct]


def volumes(acct: str) -> list[dict]:
    def v(vid, name, enc, key, inst, size):
        return {"VolumeId": vid, "Size": size, "VolumeType": "gp3", "State": "in-use", "Encrypted": enc,
                **({"KmsKeyId": key} if key else {}),
                "Attachments": [{"InstanceId": inst, "Device": "/dev/xvda", "State": "attached"}],
                "Tags": [{"Key": "Name", "Value": name}]}
    return {
        PROD: [v("vol-0a1app000000001", "prod-app-root", True, karn(PROD, K_PROD), "i-0a1app000000001", 30),
               # D23: 고객 내보내기 파일을 만드는 배치 서버의 데이터 디스크가 암호화되지 않음
               v("vol-0a1batch0000001", "prod-batch-export", False, None, "i-0a1batch00000001", 200),
               # 함정: AWS 관리형 기본 키(aws/ebs)로 암호화 — 저장 암호화는 충족
               v("vol-0a1bastion00001", "prod-bastion-root", True, karn(PROD, K_PROD_AWS_EBS), "i-0a1bastion000001", 8)],
        # D27: 스테이징 서버 디스크가 운영 계정의 키(prod-data)로 암호화됨 — 운영 데이터를 스테이징에서 복호화 가능
        STG: [v("vol-0b2app000000001", "stg-app-root", True, karn(PROD, K_PROD), "i-0b2app000000001", 30)],
        SHARED: [v("vol-0c3tools0000001", "shared-tools-root", True, karn(SHARED, K_SHARED), "i-0c3tools00000001", 30)],
    }[acct]


def buckets(acct: str) -> list[dict]:
    def b(name, algo, key=None):
        d = {"SSEAlgorithm": algo, **({"KMSMasterKeyID": key} if key else {})}
        return {"Name": name, "Region": REGION,
                "Encryption": [{"ApplyServerSideEncryptionByDefault": d, "BucketKeyEnabled": algo == "aws:kms"}]}
    return {
        # D24: 회원 정보 내보내기 버킷이 S3 기본 키(SSE-S3)로만 암호화 — 지침은 회사 관리 키(KMS)
        PROD: [b("a-prod-member-exports", "AES256"),
               b("a-prod-orders-archive", "aws:kms", karn(PROD, K_PROD)),
               # 함정: 개인정보가 없는 정적 파일 버킷은 SSE-S3 로 충분
               b("a-prod-static-assets", "AES256")],
        STG: [b("a-stg-test-data", "aws:kms", karn(STG, K_STG))],
        SHARED: [b("a-shared-tool-logs", "AES256")],
    }[acct]


TLS13_12 = "ELBSecurityPolicy-TLS13-1-2-2021-06"
LEGACY = "ELBSecurityPolicy-2016-08"
SSL = {TLS13_12: ["TLSv1.2", "TLSv1.3"], LEGACY: ["TLSv1", "TLSv1.1", "TLSv1.2"]}


def listeners(acct: str) -> list[dict]:
    def lb(name, scheme, ls):
        return {"LoadBalancerName": name, "Scheme": scheme, "Type": "application",
                "LoadBalancerArn": f"arn:aws:elasticloadbalancing:{REGION}:{acct}:loadbalancer/app/{name}/0123456789abcdef",
                "Listeners": ls}

    def li(port, proto, action, policy=None):
        acts = [{"Type": "forward", "TargetGroupArn": "arn:aws:elasticloadbalancing:tg"}] if action == "forward" else \
               [{"Type": "redirect", "RedirectConfig": {"Protocol": "HTTPS", "Port": "443", "StatusCode": "HTTP_301"}}]
        return {"Port": port, "Protocol": proto, "DefaultActions": acts, **({"SslPolicy": policy} if policy else {})}
    return {
        PROD: [lb("prod-web", "internet-facing", [
                   li(443, "HTTPS", "forward", TLS13_12),
                   # D28: 쇼핑몰 회원 페이지가 HTTP 그대로 서비스됨 (HTTPS 전환 없음)
                   li(80, "HTTP", "forward")]),
               # 함정: 내부 전용 관리 ALB의 HTTP 리스너 — 인터넷 구간이 아님
               lb("prod-internal-admin", "internal", [li(8080, "HTTP", "forward")])],
        STG: [lb("stg-web", "internet-facing", [
                  # D29: TLS 1.0·1.1 을 허용하는 오래된 보안 정책
                  li(443, "HTTPS", "forward", LEGACY),
                  # 함정: 80은 HTTPS 로 넘기기만 함
                  li(80, "HTTP", "redirect")])],
        SHARED: [],
    }[acct]


def write_snapshot() -> None:
    for acct in (PROD, STG, SHARED):
        d = SNAP / acct
        (d / "kms_keys.json").write_text(json.dumps(kms(acct), indent=2) + "\n")
        (d / "ec2_volumes.json").write_text(json.dumps(volumes(acct), indent=2) + "\n")
        (d / "s3_buckets.json").write_text(json.dumps(buckets(acct), indent=2) + "\n")
        ls = listeners(acct)
        (d / "elbv2_listeners.json").write_text(json.dumps(ls, indent=2) + "\n")
        used = sorted({x["SslPolicy"] for lb in ls for x in lb["Listeners"] if "SslPolicy" in x})
        (d / "elbv2_ssl_policies.json").write_text(json.dumps(
            [{"Name": n, "SslProtocols": SSL[n]} for n in used], indent=2) + "\n")
        # RDS 저장 암호화 필드 (D22: 스테이징 DB 저장 암호화 꺼짐)
        p = d / "rds_db_instances.json"
        dbs = json.loads(p.read_text())
        for db in dbs:
            if acct == PROD:
                db.update(StorageEncrypted=True, KmsKeyId=karn(PROD, K_PROD))
            else:
                db["StorageEncrypted"] = False
                db.pop("KmsKeyId", None)
        p.write_text(json.dumps(dbs, indent=2) + "\n")
    m = json.loads((SNAP / "manifest.json").read_text(encoding="utf-8"))
    for a in m["accounts"]:
        a["files"] = sorted(x.name for x in (SNAP / a["account_id"]).iterdir())
    (SNAP / "manifest.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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
    _sheet(ev / "정보자산목록_2026-10.xlsx", "정보자산 목록",
           ["자산ID", "자산명", "유형", "AWS 계정", "리소스ID", "개인정보", "중요도", "관리자"], [
               ["A-DB-001", "운영 주문 DB", "RDS", "a-prod", "prod-orders", "Y", "상", "운영팀"],
               ["A-DB-002", "스테이징 주문 DB", "RDS", "a-stg", "stg-orders", "Y", "중", "개발팀"],
               ["A-ST-001", "회원 정보 내보내기", "S3", "a-prod", "a-prod-member-exports", "Y", "상", "운영팀"],
               ["A-ST-002", "주문 보관", "S3", "a-prod", "a-prod-orders-archive", "Y", "상", "운영팀"],
               ["A-ST-003", "정적 파일", "S3", "a-prod", "a-prod-static-assets", "N", "하", "개발팀"],
               ["A-ST-004", "시험 데이터", "S3", "a-stg", "a-stg-test-data", "Y", "중", "QA팀"],
               ["A-ST-005", "도구 로그", "S3", "a-shared", "a-shared-tool-logs", "N", "하", "정보보호팀"],
               ["A-SV-001", "배치 서버", "EC2", "a-prod", "i-0a1batch00000001", "Y", "상", "운영팀"],
           ])
    _sheet(ev / "암호키관리대장_2026.xlsx", "암호키 관리대장",
           ["키 별칭", "AWS 계정", "키 ID", "용도", "생성 승인자", "생성일", "담당자"], [
               ["alias/prod-data", "a-prod", K_PROD, "운영 DB·S3·EBS 암호화", "정보보호팀장", "2025-06-15", "운영팀 김○○"],
               ["alias/stg-data", "a-stg", K_STG, "스테이징 데이터 암호화", "정보보호팀장", "2026-04-01", "개발팀 이○○"],
               ["alias/shared-tools", "a-shared", K_SHARED, "공용 도구 암호화", "정보보호팀장", "2025-06-20", "정보보호팀 박○○"],
           ])


CLAUSES = [
    ("Heading 1", "제1장 총칙"),
    ("Heading 2", "제1조(목적)"),
    ("Normal", "이 지침은 정보보호 정책서 제4조에 따라 개인정보와 중요정보의 암호화 대상, 방법, 암호키 관리 기준을 정함을 목적으로 한다."),
    ("Heading 2", "제2조(적용범위)"),
    ("Normal", "이 지침은 회사가 운영하는 클라우드(AWS) 자원과 개인정보처리시스템에 적용한다."),
    ("Heading 1", "제2장 암호화 대상과 방법"),
    ("Heading 2", "제3조(저장 시 암호화)"),
    ("Normal", "① 개인정보를 저장하는 데이터베이스는 저장 시 암호화를 적용한다."),
    ("Normal", "② 서버의 디스크(EBS 볼륨)는 모두 암호화하여 사용한다."),
    ("Normal", "③ 개인정보를 저장하는 객체 저장소(S3)는 회사가 관리하는 암호키(KMS)로 암호화한다."),
    ("Normal", "④ 고유식별정보, 계좌번호, 신용카드번호는 안전한 암호 알고리즘(AES-256 이상)으로 항목 단위 암호화하고, 비밀번호는 일방향 암호화(SHA-256 이상)하여 저장한다."),
    ("Heading 2", "제4조(전송 시 암호화)"),
    ("Normal", "인터넷으로 개인정보를 주고받는 구간은 TLS 1.2 이상으로 암호화하며, 암호화되지 않은 HTTP 접속은 HTTPS로 전환한다."),
    ("Heading 1", "제3장 암호키 관리"),
    ("Heading 2", "제5조(암호키 생성·등록)"),
    ("Normal", "암호키는 정보보호팀장의 승인을 받아 생성하고 암호키 관리대장에 등록한다."),
    ("Heading 2", "제6조(암호키 교체)"),
    ("Normal", "암호키는 1년마다 교체하며, 클라우드 키 관리 서비스(KMS)의 자동 교체 기능을 사용한다."),
    ("Heading 2", "제7조(환경 분리)"),
    ("Normal", "운영 환경의 암호키를 개발·테스트 환경에서 사용하지 않는다."),
    ("Heading 1", "부칙"),
    ("Normal", "1. 이 지침은 2026년 10월 1일부터 시행한다."),
]


def write_docs() -> None:
    src = SC / "docs" / "A사_접근통제지침_v2.1.docx"
    dst = SC / "docs" / "A사_암호통제지침_v1.0.docx"
    d = docx.Document(src)
    styles = {n: next(p.style for p in d.paragraphs if p.style.name == n) for n in ("Normal", "Heading 1", "Heading 2")}
    body = d.element.body
    kids = list(body)
    # A사 / 제목 / 문서정보 표 / '개정 이력' / 개정 이력 표 만 남기고 지운다
    for el in kids[5:]:
        if not el.tag.endswith("sectPr"):
            body.remove(el)
    d.paragraphs[1].runs[0].text = "암호통제 지침"
    for r in d.paragraphs[1].runs[1:]:
        r.text = ""
    meta = {"문서번호": "A-ISG-006", "버전": "v1.0", "시행일": "2026-10-01"}
    for row in d.tables[0].rows:
        if row.cells[0].text in meta:
            row.cells[1].paragraphs[0].runs[0].text = meta[row.cells[0].text]
    hist = d.tables[1]
    for row in list(hist.rows)[2:]:
        hist._tbl.remove(row._tr)
    for cell, text in zip(hist.rows[1].cells, ["v1.0", "2026-09-20", "최초 제정", "정보보호팀장"]):
        cell.paragraphs[0].runs[0].text = text
    for style, text in CLAUSES:
        p = d.add_paragraph(text, style=styles[style])
        if style.startswith("Heading"):
            for r in p.runs:
                r.bold = True
    sect = next((el for el in body if el.tag.endswith("sectPr")), None)
    if sect is not None:   # 구역 설정은 본문 맨 끝에 있어야 한다
        body.remove(sect)
        body.append(sect)
    d.save(dst)

    pol = SC / "docs" / "A사_정보보호정책서_v1.0.docx"
    pd = docx.Document(pol)
    if not any("A-ISG-006" in p.text for p in pd.paragraphs):
        last = next(p for p in pd.paragraphs if p.text.startswith("3. 개인정보 보호 지침"))
        new = copy.deepcopy(last._p)
        last._p.addnext(new)
        from docx.text.paragraph import Paragraph
        np = Paragraph(new, last._parent)
        np.runs[0].text = "4. 암호통제 지침 (A-ISG-006)"
        for r in np.runs[1:]:
            r.text = ""
        pd.save(pol)


def write_scope() -> None:
    p = SC / "scope.yaml"
    text = p.read_text(encoding="utf-8")
    if "A사_암호통제지침" not in text:
        text = text.replace(
            "  - {file: docs/A사_계정관리절차서_v1.3.docx, doc_id: A-ISP-004-01}",
            "  - {file: docs/A사_계정관리절차서_v1.3.docx, doc_id: A-ISP-004-01}\n"
            "  - {file: docs/A사_암호통제지침_v1.0.docx, doc_id: A-ISG-006}")
        text = text.replace(
            "  - {file: evidence/접근권한검토기록_2026.xlsx, kind: access_review_log}",
            "  - {file: evidence/접근권한검토기록_2026.xlsx, kind: access_review_log}\n"
            "  - {file: evidence/정보자산목록_2026-10.xlsx, kind: asset_list}\n"
            "  - {file: evidence/암호키관리대장_2026.xlsx, kind: key_ledger}")
        p.write_text(text, encoding="utf-8")
    yaml.safe_load(p.read_text(encoding="utf-8"))   # 형식 확인


if __name__ == "__main__":
    write_snapshot()
    write_evidence()
    write_docs()
    write_scope()
    print("a-corp-dev 암호화 단계 데이터 생성 완료", file=sys.stderr)
