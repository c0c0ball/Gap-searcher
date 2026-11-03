"""시나리오(또는 진단 1건) 실행: 원본 수용 → 정규화 → 관측 → Q/C/P → 판정 → 귀속.

결과의 result_hash 는 실행 시각을 제외한 모든 내용의 해시다. 같은 입력이면 같은 해시가 나와야 한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .adjudicate import adjudicate
from .attribution import attribute
from .compiler.lint import lint_paths
from .compiler.schema import CriterionFile
from .ingest.ingest import ingest_bytes, ingest_file
from .ingest.scanner import Scanner
from .model import Artifact, Observation, to_dict
from .normalize.docx_parser import parse_docx
from .observe.aws import load_snapshot, snapshot_observations
from .observe.evidence import evidence_observations, policy_doc_observations
from .observe.document import LlmClient, LlmExtractor, RuleExtractor, to_observations
from .quality import apply_quality, document_coverage
from .rules.evaluator import EVALUATOR_VERSION, Context, evaluate

PIPELINE_VERSION = "0.2.0"


@dataclass
class RunOptions:
    as_of: date | None = None
    criterion: str | None = None      # None이면 requirements/ 의 기준 전체
    llm: LlmClient | None = None
    scanner: Scanner | None = None


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _crit_key(c: str) -> tuple[int, ...]:
    return tuple(int(x) for x in c.split("."))


def load_requirements(repo_root: Path, criterion: str | None = None) -> tuple[list[CriterionFile], str]:
    """기준 파일 목록(번호순)과 전체 해시. criterion을 주면 그 기준 하나만."""
    rep = lint_paths(repo_root / "requirements", repo_root / "sources")
    if rep.errors:
        raise RuntimeError("요구사항 lint 오류가 있어 실행하지 않음: " +
                           "; ".join(f"[{f.rule}] {f.where}: {f.message}" for f in rep.errors))
    files: list[tuple[CriterionFile, bytes]] = []
    for p in sorted((repo_root / "requirements").rglob("*.yaml")):
        raw = p.read_bytes()
        doc = yaml.safe_load(raw)
        if criterion is None or doc.get("criterion") == criterion:
            files.append((CriterionFile.model_validate(doc), raw))
    if not files:
        raise FileNotFoundError(f"기준 {criterion} 요구사항 파일 없음")
    files.sort(key=lambda x: _crit_key(x[0].criterion))
    h = hashlib.sha256()
    for cf, raw in files:
        h.update(cf.criterion.encode() + b"\0" + hashlib.sha256(raw).digest())
    return [cf for cf, _ in files], h.hexdigest()


def _active_overlay(repo_root: Path) -> dict:
    from .compiler.lint import load_sources
    _, ov = load_sources(repo_root / "sources")
    return {p.id: p.value for p in ov.params if p.active}


def run_scenario(scenario: Path, repo_root: Path, opts: RunOptions | None = None) -> dict:
    opts = opts or RunOptions()
    scope = yaml.safe_load((scenario / "scope.yaml").read_text(encoding="utf-8"))
    as_of = opts.as_of or date.fromisoformat(str(scope["as_of"]))
    facts = scope.get("facts", {})
    accounts = [a["account_id"] for a in scope.get("aws_accounts", []) if a.get("in_scope")]

    artifacts: dict[str, Artifact] = {}
    rejected: list[dict] = []

    # ① ~ ④ 정책 문서: 수용 → 정규화
    clauses, doc_meta, parsed, failed, doc_arts = [], {}, {}, [], []
    for d in scope.get("policy_documents", []) or []:
        try:
            art, data = ingest_file(scenario, d["file"], "policy_document", opts.scanner)
            artifacts[art.sha256] = art
            meta, cs = parse_docx(data, d.get("doc_id", d["file"]), art.sha256)
            doc_meta[d["file"]] = meta
            doc_arts.append((d["file"], meta, art.sha256))
            parsed[d["file"]] = len(cs)
            clauses += cs
        except Exception as e:
            failed.append(d["file"])
            rejected.append({"file": d["file"], "reason": f"{type(e).__name__}: {e}"})
    doc_cov = document_coverage(scope.get("policy_documents"), parsed, failed)

    ev_files: list[tuple[str, bytes, str]] = []
    for ev in scope.get("evidence", []) or []:
        try:
            art, data = ingest_file(scenario, ev["file"], ev.get("kind", "evidence"), opts.scanner)
            artifacts[art.sha256] = art
            if art.scan_status == "clean" or opts.scanner is None:
                ev_files.append((ev["file"], data, art.sha256))
        except Exception as e:
            rejected.append({"file": ev["file"], "reason": f"{type(e).__name__}: {e}"})
    ev_obs, ev_read = evidence_observations(
        ev_files, {a["account_id"]: a for a in scope.get("aws_accounts", [])})
    ev_obs += policy_doc_observations(doc_arts, clauses)

    # ⑤ 관측 — 문서
    found = RuleExtractor().extract(clauses)
    llm_rejected: list[dict] = []
    if opts.llm is not None:
        ext = LlmExtractor(opts.llm)
        found += ext.extract(clauses)
        llm_rejected = ext.rejected
    doc_obs, doc_conflicts = to_observations(found)

    # ⑤ 관측 — 기술 (스냅샷)
    snap_dir = scenario / "aws-snapshot"
    manifest, files = load_snapshot(snap_dir)
    sha: dict[str, str] = {}
    for aid, fs in files.items():
        for name, data in fs.items():
            art = ingest_bytes(f"aws-snapshot/{aid}/{name}", data, "aws_snapshot_file", opts.scanner)
            artifacts[art.sha256] = art
            sha[f"{aid}/{name}"] = art.sha256
    tech_obs = snapshot_observations(manifest, files, sha)

    # ⑥ Q/C/P
    all_obs: list[Observation] = doc_obs + tech_obs + ev_obs
    apply_quality(all_obs, artifacts, as_of)

    # ⑦ 판정 · ⑧ 귀속
    cfs, req_sha = load_requirements(repo_root, opts.criterion)
    ars = [ar for cf in cfs for ar in cf.requirements]
    ctx = Context(facts=facts, accounts_in_scope=accounts, doc_obs={o.subject: o for o in doc_obs},
                  tech_obs=tech_obs, doc_coverage=doc_cov,
                  manifest_accounts={a["account_id"]: a for a in manifest["accounts"]},
                  as_of=as_of, doc_conflicts=doc_conflicts, evidence_obs=ev_obs,
                  overlay=_active_overlay(repo_root))
    evaluations, decisions, findings = [], [], []
    for ar in ars:
        ev = evaluate(ar, ctx)
        dec = adjudicate(ar, ev)
        evaluations.append(ev)
        decisions.append(dec)
        findings += attribute(dec, ev)

    body = {
        "scenario": scenario.name,
        "organization": scope.get("organization"),
        "as_of": as_of.isoformat(),
        "criterion": ", ".join(cf.criterion for cf in cfs),
        "criteria": [{"id": cf.criterion, "name": cf.name, "ars": [a.id for a in cf.requirements]} for cf in cfs],
        "versions": {"pipeline": PIPELINE_VERSION, "evaluator": EVALUATOR_VERSION,
                     "requirements_sha256": req_sha, "llm": "on" if opts.llm else "off"},
        "snapshot": {k: manifest.get(k) for k in ("snapshot_id", "source", "collected_at")},
        "document_coverage": {"status": doc_cov[0], "detail": doc_cov[1]},
        "documents": doc_meta,
        "artifacts": sorted((to_dict(a) for a in artifacts.values()), key=lambda a: a["path"]),
        "rejected": rejected,
        "evidence_tables": ev_read,
        "llm_rejected": llm_rejected,
        "clauses": len(clauses),
        "observations": sorted((to_dict(o) for o in all_obs), key=lambda o: o["obs_id"]),
        "evaluations": [to_dict(e) for e in evaluations],
        "requirements": [{"ar_id": ar.id, "title": ar.title, "summary": ar.summary,
                          "source_locator": ar.source.locator, "case_refs": ar.case_refs} for ar in ars],
        "decisions": [to_dict(d) for d in decisions],
        "findings": [to_dict(f) for f in findings],
    }
    from .plain import build as build_plain
    body["plain"] = build_plain(body, ars,
                                {a["account_id"]: a for a in scope.get("aws_accounts", [])})
    body["versions"]["plain"] = body["plain"]["version"]
    result_hash = hashlib.sha256(canonical(body).encode()).hexdigest()
    return {"result_hash": result_hash,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **body}
