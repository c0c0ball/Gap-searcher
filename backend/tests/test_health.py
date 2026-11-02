"""외부 서비스 없이도 health가 예외 없이 '실패'를 보고하는지 확인."""
from gapcheck.config import Settings
from gapcheck.health import run_all


def test_health_reports_failures_without_raising():
    s = Settings(
        database_url="postgresql://x:x@127.0.0.1:1/x",
        redis_url="redis://127.0.0.1:1/0",
        minio_endpoint="127.0.0.1:1",
        clamav_host="127.0.0.1", clamav_port=1,
        ollama_url="http://127.0.0.1:1",
    )
    res = run_all(s)
    assert set(res) == {"postgres", "redis", "minio", "clamav", "ollama"}
    assert all(r["ok"] is False for r in res.values())
