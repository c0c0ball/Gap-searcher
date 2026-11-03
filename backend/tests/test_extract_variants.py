"""문체가 다른 규정도 읽는지 — 회사마다 다른 흔한 표현으로 기준값 추출을 확인한다.

A사 문장에만 맞춘 정규식이 숨김 평가(B사)에서 드러나 고친 부분의 회귀 테스트다.
문장은 B사 문서를 베끼지 않고 국내 규정에서 흔한 표현으로 새로 썼다.
"""
import io

import docx
import pytest

from gapcheck.model import Clause
from gapcheck.normalize.docx_parser import parse_docx
from gapcheck.observe.document import RuleExtractor, cycle_days, to_observations


def values(*texts, article="제5조(규칙)", parent=""):
    cs = [Clause(clause_id=f"X#{i}", doc_id="X", artifact_sha256="s", article=article, label="", text=t,
                 parent_text=parent, order=i) for i, t in enumerate(texts)]
    obs, conflicts = to_observations(RuleExtractor().extract(cs))
    assert not conflicts, conflicts
    return {o.subject: o.values["value"] for o in obs}


@pytest.mark.parametrize("text,param,value", [
    ("패스워드는 9자리 이상으로 설정한다.", "password.min_length", 9),
    ("비밀번호 길이는 12자 이상이어야 한다.", "password.min_length", 12),
    ("패스워드의 최대 사용기간은 120일로 한다.", "password.max_age_days", 120),
    ("비밀번호는 3개월마다 변경한다.", "password.max_age_days", 90),
    ("최근 5회 이내에 사용한 패스워드는 재사용할 수 없다.", "password.reuse_prevention", 5),
    ("초기 패스워드는 처음 로그인할 때 즉시 변경하도록 한다.", "password.temp_force_change", True),
    ("영문 대문자, 소문자, 숫자, 특수문자 4종 중 3종 이상을 조합한다.", "password.complexity_classes", 3),
    ("대문자·소문자·숫자·특수문자 네 가지 중 세 가지 이상을 섞어 쓴다.", "password.complexity_classes", 3),
    ("영문 대문자, 영문 소문자, 숫자, 특수문자 중 3종류 이상을 조합한다.", "password.complexity_classes", 3),
])
def test_password_variants(text, param, value):
    assert values(text, article="제5조(패스워드 작성규칙)")[param] == value


def test_one_char_each_is_not_min_length():
    v = values("영문 대문자·소문자·숫자·특수문자를 각각 1자 이상 포함한다.", article="제5조(비밀번호)")
    assert "password.min_length" not in v and v["password.require_symbol"] is True


@pytest.mark.parametrize("text,days", [
    ("분기별 1회 점검한다", 92), ("반기마다 검토한다", 184), ("매년 실시한다", 366), ("매월 확인한다", 31),
    ("6개월마다 수행한다", 184), ("연 1회 이상 실시한다", 366),
])
def test_cycle_words(text, days):
    assert cycle_days(text) == days


@pytest.mark.parametrize("text,param", [
    ("사용자 계정은 신청서를 제출하고 소속 부서장 승인을 받은 후 발급한다.", "account.request_approval"),
    ("권한은 직무별 IAM 그룹에만 부여하며 사용자에게 정책을 직접 연결하지 않는다.", "access.group_based"),
    ("admin, test 등 유추하기 쉬운 ID는 사용하지 않는다.", "account.no_guessable_id"),
    ("관리자 콘솔 접속 시 2단계 인증을 적용한다.", "mfa.console_required"),
    ("특수권한자 현황을 작성하여 분기마다 갱신한다.", "privileged.list_required"),
    ("외부 업체 유지보수 계정은 사용기한을 정하여 발급한다.", "account.vendor_expiry_required"),
    ("DB 인스턴스에는 퍼블릭 액세스를 허용하지 않는다.", "network.db_private"),
    ("RDS 등 블록 스토리지 볼륨은 모두 암호화한다.", "crypto.disk_at_rest"),
    ("개인정보가 담긴 S3 버킷은 SSE-KMS로 암호화한다.", "crypto.personal_object_kms"),
    ("웹 서비스는 HTTPS로만 제공한다.", "transport.https_only"),
    ("고객 관리형 키는 자동 키 교체를 활성화한다.", "key.rotation_required"),
    ("CloudTrail은 전체 리전을 대상으로 기록한다.", "log.audit_trail_required"),
    ("GuardDuty를 모든 계정에서 활성화한다.", "monitor.threat_detection_required"),
    ("백업본은 다른 리전에 복제하여 보관한다.", "backup.cross_region_required"),
])
def test_flag_variants(text, param):
    assert values(text, article="제9조(기준)")[param] is True


def test_cidrs_listed_in_items_are_merged():
    v = values("1. 본사 관리망: 198.51.100.16/28", "2. 원격 접속 VPN: 10.200.0.0/24", article="제12조(원격 관리)",
               parent="① 서버 원격 관리(SSH, RDP)는 다음 각 호의 관리망에서만 허용한다.")
    assert v["network.admin_source_cidrs"] == ["10.200.0.0/24", "198.51.100.16/28"]


def test_retention_years_and_months():
    assert values("접속기록은 3년간 보관한다.")["log.retention_days"] == 1095
    assert values("감사 로그는 18개월 이상 보관한다.")["log.retention_days"] == 540
    assert values("DB 백업은 14일간 보관한다.")["backup.retention_days"] == 14


def test_dr_drill_is_not_restore_test():
    assert values("재해 복구 훈련은 매년 실시한다.") == {"dr.drill_cycle_days": 366}
    assert values("연 1회 이상 재해복구(BCP) 모의훈련을 실시한다.") == {"dr.drill_cycle_days": 366}
    assert values("백업 복구(리스토어) 시험은 분기별 1회 수행한다.") == {"backup.restore_test_cycle_days": 92}


def _doc(paragraphs):
    d = docx.Document()
    t = d.add_table(rows=1, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "문서번호", "T-1"
    for style, text in paragraphs:
        d.add_paragraph(text, style=style)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_article_title_and_body_on_one_line():
    data = _doc([("Normal", "제3조(계정 신청) 계정은 신청서를 제출하고 팀장 승인을 받은 후 발급한다."),
                 ("Normal", "제4조에 따른 예외는 정보보호팀이 판단한다."),
                 ("Heading 2", "제5조(목적)")])
    _, cs = parse_docx(data, "T-1", "s")
    assert [(c.article, c.text) for c in cs] == [
        ("제3조(계정 신청)", "계정은 신청서를 제출하고 팀장 승인을 받은 후 발급한다."),
        ("제3조(계정 신청)", "제4조에 따른 예외는 정보보호팀이 판단한다.")]   # '제4조에 따른'은 새 조가 아님


def test_definition_article_is_skipped_even_if_numbered_differently():
    v = values("“패스워드”란 8자 이상의 문자열을 말한다.", article="제2조(용어의 정의)")
    assert v == {}
