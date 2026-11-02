"""구성요소별 연결 확인. 각 함수는 예외를 밖으로 던지지 않고 {ok, detail}을 돌려준다."""
from __future__ import annotations

import socket
from typing import Callable

import httpx

from .config import Settings, get_settings

Check = dict[str, object]


def _safe(fn: Callable[[Settings], str], s: Settings) -> Check:
    try:
        return {"ok": True, "detail": fn(s)}
    except Exception as e:  # 연결 실패도 결과로 보고한다
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _postgres(s: Settings) -> str:
    import psycopg

    with psycopg.connect(s.database_url, connect_timeout=3) as conn:
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    if not row:
        raise RuntimeError("pgvector 확장이 설치되지 않음")
    return f"pgvector {row[0]}"


def _redis(s: Settings) -> str:
    import redis

    redis.Redis.from_url(s.redis_url, socket_timeout=3).ping()
    return "PONG"


def _minio(s: Settings) -> str:
    from minio import Minio

    client = Minio(
        s.minio_endpoint,
        access_key=s.minio_root_user,
        secret_key=s.minio_root_password,
        secure=False,
    )
    created = []
    for b in s.bucket_list:
        if not client.bucket_exists(b):
            client.make_bucket(b)
            created.append(b)
    return f"buckets={s.bucket_list} created={created}"


def _clamav(s: Settings) -> str:
    # clamd 프로토콜: zPING\0 → PONG\0
    with socket.create_connection((s.clamav_host, s.clamav_port), timeout=3) as sock:
        sock.sendall(b"zPING\0")
        reply = sock.recv(64).strip(b"\0").decode()
        sock.sendall(b"zVERSION\0")
        version = sock.recv(256).strip(b"\0").decode()
    if reply != "PONG":
        raise RuntimeError(f"예상치 못한 응답: {reply!r}")
    return version


def _ollama(s: Settings) -> str:
    r = httpx.get(f"{s.ollama_url}/api/tags", timeout=3)
    r.raise_for_status()
    names = {m["name"] for m in r.json().get("models", [])}
    have = lambda want: any(n == want or n.startswith(want + ":") for n in names)
    missing = [m for m in (s.ollama_gen_model, s.ollama_embed_model) if not have(m)]
    if missing:
        raise RuntimeError(f"모델 없음: {missing} — `ollama pull <모델>` 필요")
    return f"models ok ({s.ollama_gen_model}, {s.ollama_embed_model})"


CHECKS: dict[str, Callable[[Settings], str]] = {
    "postgres": _postgres,
    "redis": _redis,
    "minio": _minio,
    "clamav": _clamav,
    "ollama": _ollama,
}


def run_all(s: Settings | None = None) -> dict[str, Check]:
    s = s or get_settings()
    return {name: _safe(fn, s) for name, fn in CHECKS.items()}
