"""ISMS-P 기준 카탈로그.

- 공개 골격(sources/ismsp_catalog_skeleton.json): 번호·이름·분야·쪽·개수. 저장소에 포함.
- 비공개 원문(data/sources/ISMS-P_인증기준_2023-11.json): 인증기준·주요 확인사항·관련 법규·증거자료 예시·
  결함사례·세부 설명. 공공누리 4유형(변경금지·비상업)이라 저장소에 넣지 않고, 있으면 읽어서 붙인다.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from .paths import repo_root

TEXT_FIELDS = ("criterion", "checkpoints", "laws", "evidence", "cases", "detail", "law_notes")


def _private_path() -> Path:
    return Path(os.environ.get("GAPCHECK_CATALOG", repo_root() / "data" / "sources" / "ISMS-P_인증기준_2023-11.json"))


@lru_cache
def load() -> dict:
    sk = json.loads((repo_root() / "sources" / "ismsp_catalog_skeleton.json").read_text(encoding="utf-8"))
    items = {i["id"]: dict(i) for i in sk["items"]}
    p = _private_path()
    full = p.exists()
    if full:
        for i in json.loads(p.read_text(encoding="utf-8")):
            if i["id"] in items:
                items[i["id"]].update({k: i.get(k) for k in TEXT_FIELDS})
    order = [i["id"] for i in sk["items"]]
    return {"has_text": full, "source": sk["source"], "order": order, "items": items}


def criterion(cid: str) -> dict | None:
    return load()["items"].get(cid)


def checkpoint_count(cid: str) -> int:
    c = criterion(cid)
    return c["checkpoints"] if isinstance(c["checkpoints"], int) else len(c["checkpoints"])
