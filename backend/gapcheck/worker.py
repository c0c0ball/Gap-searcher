from celery import Celery

from .config import get_settings

_s = get_settings()
app = Celery("gapcheck", broker=_s.redis_url, backend=_s.redis_url)
app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"])


@app.task(name="gapcheck.ping")
def ping() -> str:
    """worker가 큐에서 작업을 꺼내 처리할 수 있는지 확인한다."""
    return "pong"


@app.task(name="gapcheck.run_scenario")
def run_scenario_task(target: str, use_llm: bool = False) -> str:
    """시나리오('a-corp-dev') 또는 작업공간('ws:이름') 1건 실행 → runs/에 저장 → run_id 반환."""
    from .observe.document import OllamaClient
    from .paths import repo_root, resolve_target
    from .pipeline import RunOptions, run_scenario
    from .runs import save_run
    from .workspaces import _scanner

    path = resolve_target(target)
    s = get_settings()
    llm = OllamaClient(s.ollama_url, s.ollama_gen_model) if use_llm else None
    result = run_scenario(path, repo_root(), RunOptions(llm=llm, scanner=_scanner()))
    return save_run(result, target)
