"""저장소 루트와 실행 결과 폴더 위치. 컨테이너(/app)와 로컬(저장소 루트) 모두에서 동작한다."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    if env := os.environ.get("GAPCHECK_ROOT"):
        return Path(env)
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "requirements").is_dir() and (p / "sources").is_dir():
            return p
    return here.parents[1]


def runs_dir() -> Path:
    d = Path(os.environ.get("GAPCHECK_RUNS", repo_root() / "runs"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def scenarios_dir() -> Path:
    return repo_root() / "scenarios"


def workspaces_dir() -> Path:
    """업로드로 만드는 진단 작업공간. 시나리오와 같은 구조이며 쓰기 가능하다."""
    d = Path(os.environ.get("GAPCHECK_WORKSPACES", repo_root() / "workspaces"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_target(name: str) -> Path:
    """'a-corp-dev' → scenarios/, 'ws:이름' → workspaces/. 경로 조작을 막는다."""
    base, key = (workspaces_dir(), name[3:]) if name.startswith("ws:") else (scenarios_dir(), name)
    p = (base / key).resolve()
    if p.parent != base.resolve() or not (p / "scope.yaml").exists():
        raise FileNotFoundError(name)
    return p
