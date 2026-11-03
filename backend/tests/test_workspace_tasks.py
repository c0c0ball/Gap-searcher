"""작업공간 업로드 · 담당자별 할 일 · 대시보드."""
import io
import zipfile

import pytest
from conftest import REPO, SCENARIO
from fastapi.testclient import TestClient

ACL = SCENARIO / "docs" / "A사_접근통제지침_v2.1.docx"


def docx_variant(src: bytes, old: str, new: str) -> bytes:
    zin = zipfile.ZipFile(io.BytesIO(src))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = data.decode().replace(old, new).encode()
            zout.writestr(item, data)
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GAPCHECK_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("GAPCHECK_WORKSPACES", str(tmp_path / "ws"))
    monkeypatch.setenv("CLAMAV_PORT", "1")       # 검역기 없음 → not_scanned 로 기록
    monkeypatch.setenv("MINIO_ENDPOINT", "127.0.0.1:1")
    from gapcheck.config import get_settings
    get_settings.cache_clear()
    from gapcheck.api import app
    yield TestClient(app)
    get_settings.cache_clear()


def _run(target):
    from gapcheck.paths import resolve_target
    from gapcheck.pipeline import run_scenario
    from gapcheck.runs import save_run
    return save_run(run_scenario(resolve_target(target), REPO), target)


def test_create_upload_preview_and_run(client):
    assert client.post("/workspaces", json={"name": "A사-개정안", "base": "a-corp-dev"}).status_code == 200
    v22 = docx_variant(ACL.read_bytes(), "최소 10자", "최소 12자")
    r = client.post("/workspaces/A사-개정안/files", data={"kind": "policy_document"},
                    files={"file": ("A사_접근통제지침_v2.2.docx", v22)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["artifact"]["scan_status"] == "not_scanned"
    assert body["minio"].startswith("skipped")
    ext = {e["param"]: e for e in body["preview"]["extracted"]}
    assert ext["password.min_length"]["value"] == 12
    assert "제5조" in ext["password.min_length"]["locator"]

    # 구판과 개정판이 함께 있으면 값이 충돌 → AR-02는 결함도 적합도 아님
    rid = _run("ws:A사-개정안")
    dec = {d["ar_id"]: d for d in client.get(f"/runs/{rid}").json()["result"]["decisions"]}
    assert dec["AR-2.5.4-01"]["reason_code"] == "CONFLICTING_EVIDENCE"

    # 구판을 빼면 12자 기준으로 비교 → prod 8자는 여전히 결함
    assert client.post("/workspaces/A사-개정안/files/remove",
                       json={"file": "docs/A사_접근통제지침_v2.1.docx"}).status_code == 200
    rid2 = _run("ws:A사-개정안")
    r2 = client.get(f"/runs/{rid2}").json()["result"]
    f = [x for x in r2["findings"] if x["ar_id"] == "AR-2.5.4-02"]
    assert any("8, 정책 기준 >= 12" in x["summary"] for x in f)


def test_upload_rejections(client):
    client.post("/workspaces", json={"name": "ws1"})
    fake = client.post("/workspaces/ws1/files", data={"kind": "policy_document"},
                       files={"file": ("정책.docx", b"%PDF-1.7 not a docx")})
    assert fake.status_code == 422 and "실제 내용" in fake.json()["detail"]
    hwp = client.post("/workspaces/ws1/files", data={"kind": "policy_document"},
                      files={"file": ("정책.hwp", b"HWP")})
    assert hwp.status_code == 422
    empty = docx_variant(ACL.read_bytes(), "제", "X")  # 조항 표시를 없앤 문서
    r = client.post("/workspaces/ws1/files", data={"kind": "policy_document"},
                    files={"file": ("빈문서.docx", empty)})
    assert r.status_code == 422 and "조항" in r.json()["detail"]


def test_bad_workspace_names(client):
    assert client.post("/workspaces", json={"name": "../evil"}).status_code == 422
    client.post("/workspaces", json={"name": "dup"})
    assert client.post("/workspaces", json={"name": "dup"}).status_code == 409
    assert client.get("/workspaces/..%2F..").status_code == 404


def test_targets_include_workspaces(client):
    client.post("/workspaces", json={"name": "내작업"})
    t = {x["target"] for x in client.get("/targets").json()}
    assert {"a-corp-dev", "ws:내작업"} <= t


def test_tasks_split_by_owner_and_toggle(client):
    rid = _run("a-corp-dev")
    owners = {o["owner"]: o for o in client.get("/tasks").json()["owners"]}
    assert set(owners) == {"클라우드(AWS) 관리자", "해당 직원", "개발팀(회원 서비스)", "정보보호팀",
                           "해당 부서장", "운영팀"}
    aws = sorted(t["ar_id"] for t in owners["클라우드(AWS) 관리자"]["tasks"])
    assert aws == ["AR-2.2.5-01", "AR-2.5.1-02", "AR-2.5.2-01", "AR-2.5.3-01", "AR-2.5.3-02",
                   "AR-2.5.4-02", "AR-2.5.4-03", "AR-2.5.4-04", "AR-2.5.5-01", "AR-2.5.5-02", "AR-2.5.6-02",
                   "AR-2.6.1-01", "AR-2.6.1-02", "AR-2.6.2-01", "AR-2.6.4-01", "AR-2.6.6-01", "AR-2.6.7-01"]
    tid = "AR-2.5.4-03:해당 직원"
    assert client.post(f"/runs/{rid}/tasks/{tid}", json={"done": True, "by": ""}).status_code == 422
    assert client.post(f"/runs/{rid}/tasks/{tid}", json={"done": True, "by": "김○○"}).status_code == 200
    owners = {o["owner"]: o for o in client.get("/tasks").json()["owners"]}
    assert owners["해당 직원"]["done"] == 1


def test_rejected_review_removes_task(client):
    rid = _run("a-corp-dev")
    client.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-05", "decision": "reject",
                                                "reviewer": "한동훈", "comment": "Cognito 풀이 운영 대상인지 재확인"})
    owners = {o["owner"] for o in client.get("/tasks").json()["owners"]}
    assert "개발팀(회원 서비스)" not in owners


def test_dashboard(client):
    assert client.get("/dashboard").json()["latest"] is None
    rid = _run("a-corp-dev")
    client.post(f"/runs/{rid}/reviews", json={"ar_id": "AR-2.5.4-02", "decision": "approve", "reviewer": "한동훈"})
    d = client.get("/dashboard").json()
    assert d["latest"]["run_id"] == rid
    tones = {s["ar_id"]: s["tone"] for s in d["strip"]}
    assert len(tones) == 22
    assert [a for a, t in tones.items() if t == "ok"] == ["AR-2.5.1-01", "AR-2.5.4-01"]
    s02 = next(s for s in d["strip"] if s["ar_id"] == "AR-2.5.4-02")
    assert s02["status"] == "고쳐야 해요" and s02["reviewed"]
    assert d["review_progress"] == {"reviewed": 1, "total": 22}


def test_dashboard_scoped_by_target_and_trend(client):
    import json
    from gapcheck.paths import resolve_target
    from gapcheck.pipeline import run_scenario
    from gapcheck.runs import save_run
    from gapcheck import workspaces
    rid_ex = _run("a-corp-dev")
    workspaces.create_workspace("개선", "a-corp-dev")
    ws = resolve_target("ws:개선")
    _run("ws:개선")                       # 첫 실행: 고칠 것 20
    p = ws / "aws-snapshot/111111111111/cognito_user_pools.json"
    d = json.loads(p.read_text()); d[0]["Policies"]["PasswordPolicy"]["MinimumLength"] = 8
    p.write_text(json.dumps(d))
    import time; time.sleep(1.1)          # generated_at 정렬용
    _run("ws:개선")                       # 두 번째: Cognito 고침 → 고칠 것 19
    dd = client.get("/dashboard", params={"target": "ws:개선"}).json()
    assert dd["latest"]["target"] == "ws:개선"
    assert dd["trend"]["before"]["fix"] == 20 and dd["trend"]["after"]["fix"] == 19
    assert client.get("/dashboard", params={"target": "a-corp-dev"}).json()["latest"]["run_id"] == rid_ex
    assert client.get("/tasks", params={"target": "ws:개선"}).json()["run_id"] != rid_ex
