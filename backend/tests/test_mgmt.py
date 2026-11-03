"""관리체계(1.x) 테스트: 문서 표지·개정 이력, 법령 인용, 회의·평가·감사 주기, 개선 조치, 자산 목록 대조."""
from conftest import REPO, _docx_edit, edit_json, edit_xlsx, edit_yaml, fix_mgmt

from gapcheck.pipeline import run_scenario

MGMT = ("AR-1.1.2-01", "AR-1.1.3-01", "AR-1.1.5-01", "AR-1.1.5-02", "AR-1.2.1-01", "AR-1.2.3-01",
        "AR-1.4.1-01", "AR-1.4.2-01", "AR-1.4.3-01")


def decision(r, ar):
    return next(d for d in r["decisions"] if d["ar_id"] == ar)


def subjects(r, ar):
    return sorted(f["subject"] for f in r["findings"] if f["ar_id"] == ar)


def test_all_mgmt_rules_conforming_after_fix(scenario):
    fix_mgmt(scenario)
    r = run_scenario(scenario, REPO)
    assert {a: decision(r, a)["verdict"] for a in MGMT if decision(r, a)["verdict"] != "CANDIDATE_CONFORMING"} == {}


def test_last_revised_comes_from_history_table():
    r = run_scenario(REPO / "scenarios/a-corp-dev", REPO)
    meta = {o["subject"]: o["values"] for o in r["observations"] if o["kind"] == "policy_doc"}
    assert meta["A-ISG-004"]["last_revised"] == "2026-06-20"     # 개정 이력 3줄 중 가장 늦은 날짜
    assert meta["A-ISP-004-01"]["approver"] == "정보보호팀장"


def test_blank_approver_is_violation(scenario):
    fix_mgmt(scenario)

    def blank(d):
        for row in d.tables[0].rows:
            if row.cells[0].text == "승인자":
                row.cells[1].paragraphs[0].runs[0].text = ""
    _docx_edit(scenario / "docs/A사_운영보안지침_v1.0.docx", blank)
    assert subjects(run_scenario(scenario, REPO), "AR-1.1.5-01") == ["A-ISG-008"]


def test_law_citation_without_number_is_not_flagged(scenario):
    """고시 번호 없이 이름만 인용하면 판단 대상이 아니다 (현행 여부를 알 수 없음)."""
    fix_mgmt(scenario)

    def drop(d):
        for p in d.paragraphs:
            if "고시 제2026-9호" in p.text:
                p.runs[0].text = p.text.replace("(개인정보보호위원회 고시 제2026-9호)", "")
                for r in p.runs[1:]:
                    r.text = ""
    _docx_edit(scenario / "docs/A사_암호통제지침_v1.0.docx", drop)
    r = run_scenario(scenario, REPO)
    cites = [o for o in r["observations"] if o["kind"] == "law_citation"]
    assert [c["values"]["doc_id"] for c in cites] == ["A-ISG-008"]
    assert subjects(r, "AR-1.4.1-01") == []


def test_overlay_inactive_means_no_basis(tmp_path, scenario):
    """현행 고시 번호를 원문 대조하지 않았다면(active: false) 비교하지 않는다."""
    import shutil
    repo = tmp_path / "repo"
    for d in ("requirements", "sources"):
        shutil.copytree(REPO / d, repo / d)
    p = repo / "sources/legal_overlay.yaml"
    p.write_text(p.read_text().replace('value: "2026-9"\n    source_ref: SRC-LAW-SAFEGUARD-STD\n    locator: "개인정보보호위원회 고시 제2026-9호 (registry sha256 대조, 2026-11-03)"\n    active: true',
                                       'value: "2026-9"\n    source_ref: SRC-LAW-SAFEGUARD-STD\n    locator: "미대조"\n    active: false'))
    from gapcheck.compiler.lint import lint_paths
    rep = lint_paths(repo / "requirements", repo / "sources")
    assert any(f.rule == "RC-004" and "AR-1.4.1-01" in f.where for f in rep.errors)


def test_new_bucket_without_asset_entry(scenario):
    fix_mgmt(scenario)
    edit_json(scenario / "aws-snapshot/222222222222/s3_buckets.json", lambda bs: bs.append(
        {"Name": "a-stg-shadow-copy", "Region": "ap-northeast-2", "Encryption": [], "Lifecycle": []}))
    assert subjects(run_scenario(scenario, REPO), "AR-1.2.1-01") == ["222222222222/a-stg-shadow-copy"]


def test_asset_list_missing_is_not_conforming(scenario):
    fix_mgmt(scenario)
    edit_yaml(scenario / "scope.yaml", lambda s: s.update(
        evidence=[e for e in s["evidence"] if e.get("kind") != "asset_list"]))
    r = run_scenario(scenario, REPO)
    d = decision(r, "AR-1.2.1-01")
    assert d["verdict"] != "CANDIDATE_CONFORMING"


def test_open_item_without_due_date_is_violation(scenario):
    fix_mgmt(scenario)
    edit_xlsx(scenario / "evidence/개선조치관리대장_2026.xlsx", lambda rs: rs.append(
        {"조치번호": "IA-2026-05", "발견사항": "로그 점검 기준 미수립", "담당": "정보보호팀", "완료예정일": None, "상태": "진행중"}))
    assert subjects(run_scenario(scenario, REPO), "AR-1.4.3-01") == ["조치 IA-2026-05"]


def test_risk_and_committee_in_one_sentence_counts_once(scenario):
    """한 문장에 위험평가와 위원회가 같이 나와도 위험평가 주기로만 뽑는다."""
    import docx
    from gapcheck.normalize.docx_parser import parse_docx
    from gapcheck.observe.document import RuleExtractor
    p = scenario / "docs/A사_정보보호정책서_v1.0.docx"

    def edit(d):
        for para in d.paragraphs:
            if para.text.startswith("정보보호팀은 연 1회 이상 위험평가"):
                para.runs[0].text = "정보보호팀은 연 1회 이상 위험평가를 수행하고 그 결과를 정보보호위원회에 보고한다."
                for r in para.runs[1:]:
                    r.text = ""
    _docx_edit(p, edit)
    _, clauses = parse_docx(p.read_bytes(), "A-ISP-001", "x")
    found = [f for f in RuleExtractor().extract(clauses) if "제9조" in f.clause.article]
    assert [f.param for f in found] == ["risk.assessment_cycle_days"]
