from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import health, runs, tasks, workspaces
from .ingest.ingest import RejectedArtifact
from .compiler.lint import lint_paths
from .paths import repo_root, runs_dir, scenarios_dir

app = FastAPI(title="ISMS-P 갭분석 자동화 API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def get_health() -> dict:
    checks = health.run_all()
    return {"ok": all(c["ok"] for c in checks.values()), "checks": checks}


@app.post("/health/worker")
def worker_roundtrip() -> dict:
    """api → redis → worker → redis → api 왕복 확인."""
    from .worker import ping

    try:
        result = ping.delay().get(timeout=10)
        return {"ok": result == "pong", "detail": result}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


@app.get("/requirements/lint")
def requirements_lint() -> dict:
    return lint_paths(repo_root() / "requirements", repo_root() / "sources").as_dict()


@app.get("/scenarios")
def list_scenarios() -> list[str]:
    d = scenarios_dir()
    return sorted(p.name for p in d.iterdir() if (p / "scope.yaml").exists()) if d.exists() else []


@app.get("/targets")
def list_targets() -> list[dict]:
    """실행할 수 있는 대상: 예제 시나리오 + 내 작업공간"""
    out = [{"target": n, "label": f"예제: {n}", "kind": "scenario"} for n in list_scenarios()]
    out += [{"target": w["target"], "label": w["name"], "kind": "workspace"} for w in workspaces.list_workspaces()]
    return out


class RunRequest(BaseModel):
    target: str | None = None
    scenario: str | None = None   # 이전 버전 호환
    llm: bool = False


@app.post("/runs")
def create_run(req: RunRequest) -> dict:
    from .worker import run_scenario_task

    try:
        rid = run_scenario_task.delay(req.target or req.scenario, req.llm).get(timeout=180)
    except Exception as e:
        raise HTTPException(502, f"실행 실패: {type(e).__name__}: {e}")
    return {"run_id": rid}


@app.get("/runs")
def get_runs() -> list[dict]:
    return runs.list_runs()


@app.get("/runs/{rid}")
def get_run(rid: str) -> dict:
    try:
        r = runs.load_run(rid)
    except FileNotFoundError:
        raise HTTPException(404, "실행 결과 없음")
    latest, events = runs.reviews(rid)
    from .plain import status_after_review
    plain_status = {ar: dict(zip(("status", "status_sub", "icon"), status_after_review(rv["state"])))
                    for ar, rv in latest.items()}
    return {"run_id": rid, "result": r, "reviews": latest, "review_log": events, "plain_status": plain_status}


class ReviewRequest(BaseModel):
    ar_id: str
    decision: str
    reviewer: str
    comment: str = ""


@app.post("/runs/{rid}/reviews")
def post_review(rid: str, req: ReviewRequest) -> dict:
    try:
        return runs.add_review(rid, req.ar_id, req.decision, req.reviewer, req.comment)
    except FileNotFoundError:
        raise HTTPException(404, "실행 결과 없음")
    except KeyError:
        raise HTTPException(404, "AR 없음")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/runs/{rid}/report.xlsx")
def get_report(rid: str):
    from .report import write_xlsx

    try:
        r = runs.load_run(rid)
    except FileNotFoundError:
        raise HTTPException(404, "실행 결과 없음")
    latest, _ = runs.reviews(rid)
    out = runs_dir() / rid / "report.xlsx"
    write_xlsx(r, out, latest)
    return FileResponse(out, filename=f"{rid}.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ── 담당자별 할 일 ─────────────────────────────────────────────────────────

def _runs_of(target: str | None) -> list[dict]:
    rs = runs.list_runs()
    return [r for r in rs if r["target"] == target] if target else rs


@app.get("/tasks")
def get_tasks(target: str | None = None, run_id: str | None = None) -> dict:
    rs = _runs_of(target)
    rid = run_id or (rs[0]["run_id"] if rs else None)
    if rid is None:
        return {"run_id": None, "owners": []}
    try:
        return {"run_id": rid, "owners": tasks.by_owner(tasks.task_list(rid))}
    except FileNotFoundError:
        raise HTTPException(404, "실행 결과 없음")


class TaskUpdate(BaseModel):
    done: bool
    by: str
    memo: str = ""


@app.post("/runs/{rid}/tasks/{task_id}")
def update_task(rid: str, task_id: str, req: TaskUpdate) -> dict:
    try:
        return tasks.set_done(rid, task_id, req.done, req.by, req.memo)
    except FileNotFoundError:
        raise HTTPException(404, "실행 결과 없음")
    except KeyError:
        raise HTTPException(404, "할 일 없음")
    except ValueError as e:
        raise HTTPException(422, str(e))


# ── 대시보드 ──────────────────────────────────────────────────────────────

def _strip(rid: str) -> list[dict]:
    from .plain import status_after_review
    r = runs.load_run(rid)
    reviewed, _ = runs.reviews(rid)
    out = []
    for it in (r.get("plain") or {}).get("items", []):
        rv = reviewed.get(it["ar_id"])
        st, sub, icon = status_after_review(rv["state"]) if rv else (it["status"], it["status_sub"], it["icon"])
        out.append({"ar_id": it["ar_id"], "question": it["question"], "status": st, "status_sub": sub,
                    "tone": {"🔴": "fix", "🟢": "ok"}.get(icon, "unknown"), "reviewed": bool(rv),
                    "findings": len(it["found"]) if icon == "🔴" else 0})
    return out


def _tone_counts(strip: list[dict]) -> dict:
    return {t: sum(1 for s in strip if s["tone"] == t) for t in ("fix", "ok", "unknown")}


@app.get("/dashboard")
def dashboard(target: str | None = None) -> dict:
    rs = _runs_of(target)
    if not rs:
        return {"latest": None, "recent": [], "owners": [], "strip": [], "next_tasks": []}
    latest = rs[0]
    r = runs.load_run(latest["run_id"])
    reviewed, _ = runs.reviews(latest["run_id"])
    strip = _strip(latest["run_id"])
    # 같은 대상의 '결과가 다른' 직전 실행과 비교 (같은 지문의 재실행은 건너뜀)
    prev = next((x for x in rs[1:] if x["result_hash"] != latest["result_hash"]), None)
    trend = None
    if prev:
        trend = {"run_id": prev["run_id"], "generated_at": prev["generated_at"],
                 "before": _tone_counts(_strip(prev["run_id"])), "after": _tone_counts(strip)}
    all_tasks = tasks.task_list(latest["run_id"])
    owners = tasks.by_owner(all_tasks)
    open_tasks = [t for t in all_tasks if not t["done"]]
    return {"latest": {**latest, "snapshot": r["snapshot"], "headline": (r.get("plain") or {}).get("headline", "")},
            "strip": strip, "counts": _tone_counts(strip), "trend": trend,
            "owners": [{k: v for k, v in o.items() if k != "tasks"} for o in owners],
            "next_tasks": open_tasks[:4], "open_tasks": len(open_tasks), "total_tasks": len(all_tasks),
            "recent": rs[:5],
            "review_progress": {"reviewed": len(reviewed), "total": len(r["decisions"])}}


# ── 작업공간 · 자료 올리기 ───────────────────────────────────────────────────

@app.get("/workspaces")
def get_workspaces() -> list[dict]:
    return workspaces.list_workspaces()


class WorkspaceCreate(BaseModel):
    name: str
    base: str = "a-corp-dev"


@app.post("/workspaces")
def post_workspace(req: WorkspaceCreate) -> dict:
    try:
        return workspaces.create_workspace(req.name, req.base)
    except FileExistsError:
        raise HTTPException(409, "같은 이름의 작업공간이 있음")
    except FileNotFoundError:
        raise HTTPException(404, "기반 시나리오 없음")
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/workspaces/{name}")
def get_workspace(name: str) -> dict:
    try:
        return workspaces.workspace_detail(name)
    except FileNotFoundError:
        raise HTTPException(404, "작업공간 없음")


@app.post("/workspaces/{name}/files")
async def post_file(name: str, kind: str = Form(...), file: UploadFile = File(...)) -> dict:
    data = await file.read(workspaces.MAX_BYTES + 1)
    try:
        return workspaces.upload(name, file.filename or "", data, kind)
    except FileNotFoundError:
        raise HTTPException(404, "작업공간 없음")
    except RejectedArtifact as e:
        raise HTTPException(422, f"받을 수 없는 파일: {e}")
    except ValueError as e:
        raise HTTPException(422, str(e))


class FileRemove(BaseModel):
    file: str


@app.post("/workspaces/{name}/files/remove")
def remove_file(name: str, req: FileRemove) -> dict:
    try:
        workspaces.remove(name, req.file)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(404, "파일 없음")
