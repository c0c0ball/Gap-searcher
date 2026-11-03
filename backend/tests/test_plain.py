"""쉬운 설명: 문장 품질 규칙과 상태 문구."""
import pytest
from conftest import REPO, SCENARIO, edit_yaml

from gapcheck.compiler.lint import FORBIDDEN_PLAIN, JARGON
from gapcheck.pipeline import run_scenario
from gapcheck.plain import copula, euro, josa


@pytest.fixture(scope="module")
def plain():
    return run_scenario(SCENARIO, REPO)["plain"]


def _all_text(p):
    out = [p["headline"], p["notice"]]
    for it in p["items"]:
        out += [it["question"], it["status"], it["status_sub"], it["why"], it["owner"], it["note"], *it["found"], *it["fix"]]
    return " ".join(out)


def test_headline_counts(plain):
    assert plain["headline"] == ("계정·비밀번호 관리에 대해 16가지를 확인했어요. "
                                 "14가지는 고칠 부분이 있어 보이고, 2가지는 규칙대로 되어 있어 보여요.")


def test_no_forbidden_or_jargon(plain):
    text = _all_text(plain)
    for w in FORBIDDEN_PLAIN + JARGON + ["111111111111", "MinimumPasswordLength", "CANDIDATE"]:
        assert w not in text, w


def test_findings_use_friendly_names(plain):
    found = {it["ar_id"]: it["found"] for it in plain["items"]}
    assert found["AR-2.5.4-02"] == [
        "운영 계정(a-prod)의 비밀번호 최소 길이가 8자로 되어 있어요. 회사 규칙은 10자예요.",
        "테스트(스테이징) 계정(a-stg)에는 비밀번호 규칙이 아예 설정되어 있지 않아요. 그래서 짧고 쉬운 비밀번호도 만들 수 있어요.",
    ]
    assert "185일째" in found["AR-2.5.4-04"][0]


def test_fix_steps_only_when_something_to_fix(plain):
    items = {it["ar_id"]: it for it in plain["items"]}
    assert items["AR-2.5.4-01"]["fix"] == []
    assert items["AR-2.5.4-02"]["fix"] and items["AR-2.5.4-02"]["owner"]


def test_conforming_item_says_what_was_confirmed(plain):
    it = next(i for i in plain["items"] if i["ar_id"] == "AR-2.5.4-01")
    assert "접근통제 지침" in it["found"][0]
    it = next(i for i in plain["items"] if i["ar_id"] == "AR-2.5.1-01")
    assert "계정관리 절차서" in it["found"][0]


def test_unknown_is_not_reassuring(scenario):
    edit_yaml(scenario / "scope.yaml", lambda s: s["facts"].pop("scope.has_aws_accounts"))
    p = run_scenario(scenario, REPO)["plain"]
    it = next(i for i in p["items"] if i["ar_id"] == "AR-2.5.4-02")
    assert it["status"] == "아직 판단하지 못했어요"
    assert "해당하는지" in it["note"]
    assert "아직 판단하지 못했" in p["headline"]


@pytest.mark.parametrize("word,pair,expect", [
    ("비밀번호 최소 길이", "이/가", "비밀번호 최소 길이가"),
    ("영문 대문자 포함", "이/가", "영문 대문자 포함이"),
])
def test_josa(word, pair, expect):
    assert josa(word, pair) == expect


@pytest.mark.parametrize("word,expect", [("10자", "10자예요"), ("90일", "90일이에요"), ("만료 없음", "만료 없음이에요")])
def test_copula(word, expect):
    assert copula(word) == expect


@pytest.mark.parametrize("word,expect", [("8자", "8자로"), ("90일", "90일로"), ("만료 없음", "만료 없음으로")])
def test_euro(word, expect):
    assert euro(word) == expect


def test_questions_use_ismsp_checkpoint_tone(plain):
    for it in plain["items"]:
        assert it["question"].endswith("있는가?"), it["question"]
