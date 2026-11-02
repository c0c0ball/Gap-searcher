import json
import shutil
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SCENARIO = REPO / "scenarios" / "a-corp-dev"


@pytest.fixture
def scenario(tmp_path) -> Path:
    """개발 시나리오 사본. 테스트마다 한 곳씩 바꿔서 쓴다."""
    dst = tmp_path / "a-corp-dev"
    shutil.copytree(SCENARIO, dst, ignore=shutil.ignore_patterns("terraform"))
    return dst


def edit_json(path: Path, fn):
    data = json.loads(path.read_text())
    fn(data)  # 제자리 수정. 반환값은 무시한다 (pop 등의 반환값으로 덮어쓰지 않도록)
    path.write_text(json.dumps(data, indent=2))


def edit_yaml(path: Path, fn):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
