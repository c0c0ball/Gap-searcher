"""전체 점검표: 카탈로그(골격/원문), 자동 결과 결합, 사람 판단, 증적, 보고서."""
import pytest
from conftest import REPO, SCENARIO
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GAPCHECK_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("GAPCHECK_ASSESS", str(tmp_path / "assess"))
    monkeypatch.setenv("CLAMAV_PORT", "1")
    from gapcheck import catalog
    from gapcheck.config import get_settings
    catalog.load.cache_clear(); get_settings.cache_clear()
    from gapcheck.api import app
    yield TestClient(app)
    catalog.load.cache_clear(); get_settings.cache_clear()


def _run():
    from gapcheck.pipeline import run_scenario
    from gapcheck.runs import save_run
    return save_run(run_scenario(SCENARIO, REPO), "a-corp-dev")


def test_skeleton_is_public_and_complete():
    import json
    sk = json.loads((REPO / "sources/ismsp_catalog_skeleton.json").read_text(encoding="utf-8"))["items"]
    assert len(sk) == 101
    assert sum(i["checkpoints"] for i in sk) == 328
    assert sum(i["cases"] for i in sk) == 381
    assert all("criterion" not in i and "detail" not in i for i in sk)   # 원문은 골격에 없음


def test_catalog_without_private_text(client, monkeypatch, tmp_path):
    from gapcheck import catalog
    monkeypatch.setenv("GAPCHECK_CATALOG", str(tmp_path / "없음.json"))
    catalog.load.cache_clear()
    c = client.get("/catalog").json()
    assert c["has_text"] is False and len(c["items"]) == 101
    cl = client.get("/checklist", params={"target": "a-corp-dev"}).json()
    assert cl["totals"]["checkpoints"] == 328


@pytest.mark.skipif(not (REPO / "data/sources/ISMS-P_인증기준_2023-11.json").exists(), reason="비공개 원문 없음")
def test_catalog_with_private_text(client):
    c = client.get("/catalog/2.5.4").json()
    assert len(c["checkpoints"]) == 3 and len(c["cases"]) == 3
    assert c["print_page"] == 94 and c["pdf_page"] == 99


def test_all_unknown_before_any_run(client):
    t = client.get("/checklist", params={"target": "a-corp-dev"}).json()["totals"]
    assert t["unknown"] == 328 and t["criteria_decided"] == 0


def test_auto_results_fill_2_5_4(client):
    _run()
    cl = client.get("/checklist", params={"target": "a-corp-dev"}).json()
    c = next(x for x in cl["criteria"] if x["id"] == "2.5.4")
    s = {cp["index"]: (cp["state"], cp["source"]) for cp in c["checkpoints"]}
    assert s[1] == ("fix", "auto")      # AR-01 ok + AR-02~04 fix → 가장 나쁜 상태
    assert s[2] == ("fix", "auto")      # AR-05
    assert s[3] == ("unknown", "none")  # 아직 AR 없음
    assert c["state"] == "fix" and c["automated"]
    assert cl["totals"]["automated_criteria"] == 7   # 2.2.5, 2.5.1~2.5.6


def test_manual_judgement_overrides_and_validates(client):
    _run()
    base = {"target": "a-corp-dev", "by": "한동훈"}
    assert client.post("/checklist/2.5.4/3", json={**base, "state": "fix"}).status_code == 422   # 사유 필요
    assert client.post("/checklist/2.5.4/9", json={**base, "state": "ok"}).status_code == 404
    assert client.post("/checklist/9.9.9/1", json={**base, "state": "ok"}).status_code == 404
    assert client.post("/checklist/2.5.4/3", json={**base, "state": "ok", "by": ""}).status_code == 422
    r = client.post("/checklist/2.5.4/3", json={**base, "state": "ok", "comment": "콘솔 MFA 전원 적용 확인"})
    assert r.status_code == 200
    cl = client.get("/checklist", params={"target": "a-corp-dev"}).json()
    cp3 = next(x for x in cl["criteria"] if x["id"] == "2.5.4")["checkpoints"][2]
    assert (cp3["state"], cp3["source"]) == ("ok", "manual")
    client.post("/checklist/1.1.1/1", json={**base, "state": "na", "comment": "시험"})
    client.post("/checklist/1.1.1/1", json={**base, "state": "unknown"})       # 되돌리기 = 새 기록
    hist = client.get("/checklist/history", params={"target": "a-corp-dev", "cid": "1.1.1"}).json()
    assert [h["state"] for h in hist] == ["na", "unknown"]


def test_evidence_attach_and_download(client):
    r = client.post("/checklist/2.2.5/1/files", data={"target": "a-corp-dev", "by": "한동훈"},
                    files={"file": ("퇴직자_계정회수_기록.csv", b"user,date\nkim,2026-10-01\n")})
    assert r.status_code == 200, r.text
    sha = r.json()["sha256"]
    got = client.get(f"/checklist/files/{sha}", params={"target": "a-corp-dev"})
    assert got.status_code == 200 and got.content.startswith(b"user,date")
    assert client.get("/checklist/files/../../etc", params={"target": "a-corp-dev"}).status_code == 404
    bad = client.post("/checklist/2.2.5/1/files", data={"target": "a-corp-dev"},
                      files={"file": ("x.png", b"not png")})
    assert bad.status_code == 422


def test_checklist_report(client):
    _run()
    r = client.get("/checklist/report.xlsx", params={"target": "a-corp-dev"})
    assert r.status_code == 200 and r.content[:2] == b"PK"
    import io
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(r.content))["점검표"]
    assert ws.max_row == 329   # 머리글 + 328
