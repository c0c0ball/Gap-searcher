"""lint 규칙 회귀 테스트. 정상 파일 1개를 기준으로 한 곳씩 망가뜨려 해당 규칙이 잡는지 확인한다."""
import copy
from pathlib import Path

import pytest
import yaml

from gapcheck.compiler.lint import lint_paths

ROOT = Path(__file__).resolve().parents[2]
REAL_REQ = ROOT / "requirements"
REAL_SRC = ROOT / "sources"


def base_doc() -> dict:
    return yaml.safe_load((REAL_REQ / "2.5" / "2.5.4.yaml").read_text(encoding="utf-8"))


def run(tmp_path: Path, doc: dict, overlay: dict | None = None, verified: bool | None = None):
    req = tmp_path / "req"
    src = tmp_path / "src"
    req.mkdir()
    src.mkdir()
    (req / "x.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    reg = yaml.safe_load((REAL_SRC / "registry.yaml").read_text(encoding="utf-8"))
    if verified is not None:   # None이면 저장소의 실제 상태 그대로
        for s in reg["sources"]:
            s["status"] = "verified" if verified else "unverified"
    (src / "registry.yaml").write_text(yaml.safe_dump(reg, allow_unicode=True), encoding="utf-8")
    ov = overlay if overlay is not None else yaml.safe_load(
        (REAL_SRC / "legal_overlay.yaml").read_text(encoding="utf-8"))
    (src / "legal_overlay.yaml").write_text(yaml.safe_dump(ov, allow_unicode=True), encoding="utf-8")
    return lint_paths(req, src)


def rules(rep, severity="error"):
    return {f.rule for f in rep.findings if f.severity == severity}


def ar(doc, i):
    return doc["requirements"][i]


def test_real_requirements_have_no_errors():
    rep = lint_paths(REAL_REQ, REAL_SRC)
    assert rep.requirements >= 5
    assert not rep.errors, [f.__dict__ for f in rep.errors]


def test_draft_with_unverified_source_is_warning(tmp_path):
    doc = base_doc()
    for a in doc["requirements"]:
        a["status"] = "draft"
    rep = run(tmp_path, doc, verified=False)
    assert "RC-002" in rules(rep, "warning")
    assert "RC-002" not in rules(rep)


def test_active_with_unverified_source_is_error(tmp_path):
    doc = base_doc()
    ar(doc, 1)["status"] = "active"
    assert "RC-002" in rules(run(tmp_path, doc, verified=False))


def test_active_with_verified_source_passes(tmp_path):
    doc = base_doc()
    ar(doc, 1)["status"] = "active"
    assert "RC-002" not in rules(run(tmp_path, doc, verified=True))


def test_rc001_bad_id(tmp_path):
    doc = base_doc()
    ar(doc, 0)["id"] = "AR-2.5.3-01"
    assert "RC-001" in rules(run(tmp_path, doc))


def test_rc003_single_axis_without_justification(tmp_path):
    doc = base_doc()
    ar(doc, 0).pop("single_axis_justification")
    assert "RC-003" in rules(run(tmp_path, doc))


def test_rc003_document_plus_technical_is_two_axes(tmp_path):
    # AR-02의 [T1,T2,T3] = document + technical → 통과해야 함
    rep = run(tmp_path, base_doc())
    assert not any(f.rule == "RC-003" and "AR-2.5.4-02" in f.where for f in rep.findings)


def test_rc004_inactive_overlay_cannot_be_expected(tmp_path):
    doc = base_doc()
    ar(doc, 1)["tests"][2]["compare"][0]["expected"] = "overlay:law.x"
    ov = {"params": [{"id": "law.x", "description": "x", "value": 8, "source_ref": "SRC-LAW-SAFEGUARD-STD", "active": False}]}
    rep = run(tmp_path, doc, overlay=ov)
    assert "RC-004" in rules(rep)


def test_rc004_active_overlay_is_allowed(tmp_path):
    doc = base_doc()
    ar(doc, 1)["tests"][2]["compare"][0]["expected"] = "overlay:law.x"
    ov = {"params": [{"id": "law.x", "description": "x",
                      "value": True, "source_ref": "SRC-LAW-SAFEGUARD-STD", "active": True}]}
    assert "RC-004" not in rules(run(tmp_path, doc, overlay=ov))


def test_rc004_observed_must_be_real_observation(tmp_path):
    doc = base_doc()
    ar(doc, 1)["tests"][2]["compare"][0]["observed"] = "const:14"
    assert "RC-004" in rules(run(tmp_path, doc))


def test_rc005_unknown_param_reference(tmp_path):
    doc = base_doc()
    ar(doc, 1)["tests"][2]["compare"][0]["expected"] = "T1.password.min_lenght"
    assert "RC-005" in rules(run(tmp_path, doc))


def test_rc005_unknown_test_in_path(tmp_path):
    doc = base_doc()
    ar(doc, 1)["conforming_paths"] = [["T1", "T9"]]
    assert "RC-005" in rules(run(tmp_path, doc))


def test_rc006_cadence_requires_population(tmp_path):
    doc = base_doc()
    ar(doc, 3).pop("population")
    assert "RC-006" in rules(run(tmp_path, doc))


def test_rc007_inquiry_only_path(tmp_path):
    doc = base_doc()
    a = ar(doc, 0)
    a["tests"].append({"id": "T2", "type": "HUMAN_CONFIRMATION",
                       "description": "담당자 인터뷰", "params": ["answer"]})
    a["conforming_paths"] = [["T2"]]
    assert "RC-007" in rules(run(tmp_path, doc))


def test_rc008_inquiry_cannot_be_violation_basis(tmp_path):
    doc = base_doc()
    a = ar(doc, 0)
    a["tests"].append({"id": "T2", "type": "HUMAN_CONFIRMATION",
                       "description": "담당자 인터뷰", "params": ["answer"]})
    a["violation_when"] = [{"test": "T2", "condition": "담당자가 모른다고 답함"}]
    assert "RC-008" in rules(run(tmp_path, doc))


def test_rc009_checkpoint_without_ar_and_note_is_error(tmp_path):
    doc = base_doc()
    doc["checkpoints"][2].pop("note")
    assert "RC-009" in rules(run(tmp_path, doc))


def test_rc010_default_must_be_unknown(tmp_path):
    doc = base_doc()
    ar(doc, 0)["applicability"]["default"] = "APPLICABLE"
    assert "RC-010" in rules(run(tmp_path, doc))


def test_yaml_no_key_trap_is_caught(tmp_path):
    # YAML 1.1에서 'no'는 false로 읽힌다 → 스키마 오류로 잡혀야 함
    doc = base_doc()
    doc["checkpoints"][0] = {False: 1, "covered_by": []}
    rep = run(tmp_path, doc)
    assert "RC-000" in rules(rep)


@pytest.mark.parametrize("field", ["kisa_text", "original"])
def test_unknown_fields_rejected(tmp_path, field):
    # 원문 복제용 필드를 몰래 추가하지 못하도록 extra=forbid
    doc = base_doc()
    ar(doc, 0)[field] = "원문 그대로"
    assert "RC-000" in rules(run(tmp_path, doc))


def test_rc011_forbidden_phrase_in_plain(tmp_path):
    doc = base_doc()
    ar(doc, 1)["plain"]["why"] = "이대로면 인증 불가예요."
    assert "RC-011" in rules(run(tmp_path, doc))


def test_rc011_missing_plain_blocks_active(tmp_path):
    doc = base_doc()
    ar(doc, 1).pop("plain")
    ar(doc, 1)["status"] = "active"
    assert "RC-011" in rules(run(tmp_path, doc, verified=True))


def test_rc011_question_must_use_ismsp_tone(tmp_path):
    doc = base_doc()
    ar(doc, 1)["plain"]["question"] = "회사 규칙이 AWS에도 들어가 있나요?"
    assert "RC-011" in rules(run(tmp_path, doc))


def test_real_requirements_are_active_and_verified():
    rep = lint_paths(REAL_REQ, REAL_SRC)
    assert not [f for f in rep.findings if f.rule == "RC-002"]
