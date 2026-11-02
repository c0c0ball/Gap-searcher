"""API: 실행 결과 조회·검토 기록·보고서. celery 없이 저장 계층을 직접 써서 확인한다."""
import pytest
from conftest import REPO, SCENARIO
from fastapi.testclient import TestClient

from gapcheck.pipeline import run_scenario


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GAPCHECK_RUNS", str(tmp_path / "runs"))
    from gapcheck import runs
    from gapcheck.api import app
    rid = runs.save_run(run_scenario(SCENARIO, REPO))
    return TestClient(app), rid


def test_list_and_get(client):
    c, rid = client
    assert c.get("/runs").json()[0]["run_id"] == rid
    body = c.get(f"/runs/{rid}").json()
    assert body["result"]["result_hash"].startswith(rid.split("-")[-1])
    assert body["reviews"] == {}


def test_review_flow_changes_external_label(client):
    c, rid = client
    r = c.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-02", "decision": "approve", "reviewer": "한동훈"})
    assert r.status_code == 200 and r.json()["external_label"] == "결함"
    r = c.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-01", "decision": "approve", "reviewer": "한동훈"})
    assert r.json()["external_label"] == "결함 없음(확인)"
    body = c.get(f"/runs/{rid}").json()
    assert set(body["reviews"]) == {"AR-2.5.4-01", "AR-2.5.4-02"}


def test_reject_requires_reason(client):
    c, rid = client
    r = c.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-03", "decision": "reject", "reviewer": "한동훈"})
    assert r.status_code == 422


def test_review_log_is_append_only(client):
    c, rid = client
    for d, cm in [("approve", ""), ("reject", "발급 시각 해석 재확인 필요")]:
        c.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-03", "decision": d, "reviewer": "한동훈", "comment": cm})
    body = c.get(f"/runs/{rid}").json()
    assert len(body["review_log"]) == 2
    assert body["reviews"]["AR-2.5.4-03"]["state"] == "REJECTED"


def test_path_traversal_blocked(client):
    c, _ = client
    assert c.get("/runs/..%2F..%2Fetc").status_code == 404


def test_report_download(client):
    c, rid = client
    r = c.get(f"/runs/{rid}/report.xlsx")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_plain_status_follows_review(client):
    c, rid = client
    c.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-04", "decision": "approve", "reviewer": "한동훈"})
    body = c.get(f"/runs/{rid}").json()
    assert body["plain_status"]["AR-2.5.4-04"]["status"] == "고쳐야 해요"
    assert body["result"]["plain"]["items"][3]["status"] == "고칠 부분이 있어 보여요"  # 원 결과는 불변
