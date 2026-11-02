"""원본 수용: 매직바이트 확인 → 검역 → 해시 → 원본 등록.

검역에 실패한 파일은 파이프라인의 다음 단계로 넘어가지 않는다.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..model import Artifact
from .scanner import NoScanner, Scanner

# 허용 형식과 매직바이트. docx/xlsx는 ZIP 컨테이너다.
MAGIC = {
    ".docx": b"PK\x03\x04",
    ".xlsx": b"PK\x03\x04",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".pdf": b"%PDF",
    ".json": None,
    ".csv": None,
    ".yaml": None,
}


class RejectedArtifact(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ingest_bytes(name: str, data: bytes, kind: str, scanner: Scanner | None = None) -> Artifact:
    ext = Path(name).suffix.lower()
    if ext not in MAGIC:
        raise RejectedArtifact(f"허용하지 않는 형식: {ext}")
    magic = MAGIC[ext]
    if magic is not None and not data.startswith(magic):
        raise RejectedArtifact(f"확장자({ext})와 실제 내용이 다름")
    status, detail = (scanner or NoScanner()).scan(data)
    if status == "infected":
        raise RejectedArtifact(f"악성코드 탐지: {detail}")
    digest = sha256_bytes(data)
    return Artifact(
        artifact_id=f"art-{digest[:12]}",
        path=name,
        sha256=digest,
        size=len(data),
        kind=kind,
        scan_status=status,  # error/not_scanned는 통과시키되 품질 단계에서 표시
        scan_detail=detail,
    )


def ingest_file(root: Path, rel: str, kind: str, scanner: Scanner | None = None) -> tuple[Artifact, bytes]:
    data = (root / rel).read_bytes()
    return ingest_bytes(rel, data, kind, scanner), data
