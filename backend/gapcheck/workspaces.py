"""진단 작업공간: 기존 시나리오를 복제해 만들고, 브라우저에서 문서·증적을 올려 바꾼다.

업로드 1건의 처리 순서
  형식·매직바이트 확인 → ClamAV 검역(가능하면) → SHA-256 → 작업공간 폴더 저장 → MinIO 원본 보관(가능하면)
  → scope.yaml 목록 갱신 → (docx) 조항 정규화와 비밀번호 규칙 추출 미리보기
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .config import get_settings
from .ingest.ingest import RejectedArtifact, ingest_bytes
from .model import to_dict
from .normalize.docx_parser import parse_docx
from .observe.document import RuleExtractor, to_observations
from .paths import scenarios_dir, workspaces_dir

MAX_BYTES = 20 * 1024 * 1024
NAME = re.compile(r"^[\w가-힣\-]{2,40}$")
KINDS = {"policy_document": "docs", "evidence": "evidence"}


def _scanner():
    import socket

    from .ingest.scanner import ClamdScanner
    s = get_settings()
    try:
        socket.create_connection((s.clamav_host, s.clamav_port), timeout=1).close()
        return ClamdScanner(s.clamav_host, s.clamav_port)
    except OSError:
        return None


def _store_minio(sha: str, name: str, data: bytes) -> str:
    """원본을 MinIO raw 버킷에 sha256 키로 보관. 실패해도 업로드는 계속하고 상태만 남긴다."""
    try:
        import io

        import urllib3
        from minio import Minio
        s = get_settings()
        http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=2, read=10), retries=False)
        c = Minio(s.minio_endpoint, access_key=s.minio_root_user, secret_key=s.minio_root_password,
                  secure=False, http_client=http)
        if not c.bucket_exists("raw"):
            c.make_bucket("raw")
        c.put_object("raw", f"{sha}/{name}", io.BytesIO(data), len(data))
        return "stored"
    except Exception as e:
        return f"skipped ({type(e).__name__})"


def _safe_filename(name: str) -> str:
    name = Path(name).name.replace("\x00", "")
    if not name or name.startswith("."):
        raise RejectedArtifact("파일 이름이 올바르지 않음")
    return name


def list_workspaces() -> list[dict]:
    out = []
    for d in sorted(workspaces_dir().iterdir()):
        if (d / "scope.yaml").exists():
            scope = yaml.safe_load((d / "scope.yaml").read_text(encoding="utf-8"))
            out.append({"name": d.name, "target": f"ws:{d.name}", "organization": scope.get("organization"),
                        "documents": len(scope.get("policy_documents") or []),
                        "evidence": len(scope.get("evidence") or []), "base": scope.get("_base")})
    return out


def create_workspace(name: str, base: str) -> dict:
    if not NAME.match(name):
        raise ValueError("이름은 한글·영문·숫자·-·_ 2~40자")
    src = (scenarios_dir() / base).resolve()
    if src.parent != scenarios_dir().resolve() or not (src / "scope.yaml").exists():
        raise FileNotFoundError(base)
    dst = workspaces_dir() / name
    if dst.exists():
        raise FileExistsError(name)
    # 정답지와 Terraform은 작업공간에 필요 없다
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("expected", "terraform", "README.md"))
    scope = yaml.safe_load((dst / "scope.yaml").read_text(encoding="utf-8"))
    scope["_base"] = base
    (dst / "scope.yaml").write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"name": name, "target": f"ws:{name}"}


def workspace_detail(name: str) -> dict:
    d = _ws(name)
    scope = yaml.safe_load((d / "scope.yaml").read_text(encoding="utf-8"))
    files = []
    for kind, key in (("policy_document", "policy_documents"), ("evidence", "evidence")):
        for item in scope.get(key) or []:
            p = d / item["file"]
            files.append({"kind": kind, "file": item["file"], "exists": p.exists(),
                          "size": p.stat().st_size if p.exists() else 0, **{k: v for k, v in item.items() if k != "file"}})
    return {"name": name, "target": f"ws:{name}", "organization": scope.get("organization"),
            "as_of": str(scope.get("as_of")), "base": scope.get("_base"), "files": files}


def _ws(name: str) -> Path:
    d = (workspaces_dir() / name).resolve()
    if d.parent != workspaces_dir().resolve() or not (d / "scope.yaml").exists():
        raise FileNotFoundError(name)
    return d


def upload(name: str, filename: str, data: bytes, kind: str) -> dict:
    d = _ws(name)
    if kind not in KINDS:
        raise ValueError(f"kind는 {sorted(KINDS)} 중 하나")
    if len(data) > MAX_BYTES:
        raise RejectedArtifact(f"파일이 너무 큼 ({len(data) // 1024 // 1024}MB > 20MB)")
    filename = _safe_filename(filename)
    if kind == "policy_document" and not filename.lower().endswith(".docx"):
        raise RejectedArtifact("규정 문서는 .docx만 받습니다 (HWP·PDF는 다음 단계)")
    art = ingest_bytes(filename, data, kind, _scanner())

    preview: dict = {}
    if kind == "policy_document":
        try:
            meta, clauses = parse_docx(data, Path(filename).stem, art.sha256)
        except Exception as e:
            raise RejectedArtifact(f"문서를 읽을 수 없음: {type(e).__name__}")
        if not any(c.article != "부칙" for c in clauses):
            raise RejectedArtifact("조항(제N조)을 하나도 찾지 못함 — 규정 형식 문서인지 확인")
        obs, conflicts = to_observations(RuleExtractor().extract(clauses))
        preview = {
            "meta": meta,
            "clauses": len(clauses),
            "articles": sorted({c.article for c in clauses}, key=lambda a: [c.order for c in clauses if c.article == a][0]),
            "extracted": [{"param": o.subject, "value": o.values.get("value"),
                           "locator": o.citations[0].locator if o.citations else "",
                           "quote": o.citations[0].quote if o.citations else ""} for o in obs],
            "conflicts": conflicts,
        }

    rel = f"{KINDS[kind]}/{filename}"
    (d / KINDS[kind]).mkdir(exist_ok=True)
    (d / rel).write_bytes(data)
    stored = _store_minio(art.sha256, filename, data)

    scope_p = d / "scope.yaml"
    scope = yaml.safe_load(scope_p.read_text(encoding="utf-8"))
    key = "policy_documents" if kind == "policy_document" else "evidence"
    items = [i for i in (scope.get(key) or []) if i["file"] != rel]
    entry = {"file": rel, "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sha256": art.sha256}
    if kind == "policy_document":
        entry["doc_id"] = preview["meta"].get("문서번호", Path(filename).stem)
    else:
        entry["kind"] = "evidence"
    items.append(entry)
    scope[key] = items
    scope_p.write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"artifact": to_dict(art), "file": rel, "minio": stored, "preview": preview}


def remove(name: str, rel: str) -> None:
    """목록에서 빼고 작업공간 사본을 지운다. MinIO 원본은 계보 보존을 위해 남긴다."""
    d = _ws(name)
    scope_p = d / "scope.yaml"
    scope = yaml.safe_load(scope_p.read_text(encoding="utf-8"))
    found = False
    for key in ("policy_documents", "evidence"):
        before = scope.get(key) or []
        after = [i for i in before if i["file"] != rel]
        found |= len(after) != len(before)
        scope[key] = after
    if not found:
        raise FileNotFoundError(rel)
    p = (d / rel).resolve()
    if p.is_relative_to(d) and p.exists():
        p.unlink()
    scope_p.write_text(yaml.safe_dump(scope, allow_unicode=True, sort_keys=False), encoding="utf-8")
