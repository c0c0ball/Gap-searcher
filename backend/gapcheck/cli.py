"""명령줄 도구.

  gapcheck run <시나리오 폴더> [--out runs/] [--llm] [--as-of YYYY-MM-DD]
  gapcheck check <시나리오 폴더>        # 개발용 정답지와 비교
  gapcheck collect --targets targets.yaml --out <폴더>   # live AWS 수집
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import yaml

from .pipeline import RunOptions, run_scenario
from .report import write_markdown, write_xlsx

from .paths import repo_root

REPO = repo_root()


def _opts(a) -> RunOptions:
    llm = None
    if getattr(a, "llm", False):
        from .config import get_settings
        from .observe.document import OllamaClient
        s = get_settings()
        llm = OllamaClient(s.ollama_url, s.ollama_gen_model)
    return RunOptions(as_of=date.fromisoformat(a.as_of) if a.as_of else None, llm=llm)


def compare_expected(result: dict, expected_path: Path) -> list[str]:
    """판정 상태와 결함 대상(subject) 집합을 모두 비교한다."""
    exp = yaml.safe_load(expected_path.read_text(encoding="utf-8"))["expected"]
    got = {d["ar_id"]: d["verdict"] for d in result["decisions"]}
    subj: dict[str, set] = {}
    for f in result["findings"]:
        subj.setdefault(f["ar_id"], set()).add(f["subject"])
    lines = []
    for ar_id, e in exp.items():
        ok_state = got.get(ar_id) == e["state"]
        want, have = set(e.get("subjects", [])), subj.get(ar_id, set())
        ok_subj = want == have
        mark = "✓" if ok_state and ok_subj else "✗"
        line = f"{mark} {ar_id}: 기대 {e['state']} / 실제 {got.get(ar_id)}"
        if want or have:
            line += f" · 결함 대상 {'일치' if ok_subj else f'불일치 (놓침 {sorted(want - have)}, 과탐 {sorted(have - want)})'}"
        lines.append(line)
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gapcheck")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("scenario", type=Path)
    r.add_argument("--out", type=Path, default=REPO / "runs")
    r.add_argument("--as-of")
    r.add_argument("--llm", action="store_true", help="Ollama 문서 추출 함께 사용")
    c = sub.add_parser("check")
    c.add_argument("scenario", type=Path)
    c.add_argument("--as-of")
    c.add_argument("--llm", action="store_true")
    col = sub.add_parser("collect")
    col.add_argument("--targets", type=Path, required=True)
    col.add_argument("--out", type=Path, required=True)
    col.add_argument("--region", default="ap-northeast-2")
    a = p.parse_args(argv)

    if a.cmd == "collect":
        from .observe.aws_collect import collect
        targets = yaml.safe_load(a.targets.read_text(encoding="utf-8"))["targets"]
        m = collect(targets, a.out, a.region)
        for acc in m["accounts"]:
            print(f"{acc['account_id']}: {acc['status']} {acc.get('errors', '')}")
        return 0

    result = run_scenario(a.scenario.resolve(), REPO, _opts(a))
    if a.cmd == "check":
        lines = compare_expected(result, a.scenario / "expected" / "dev_expected.yaml")
        print("\n".join(lines))
        return 0 if all(l.startswith("✓") for l in lines) else 1

    out = a.out / f"{result['scenario']}-{result['as_of']}-{result['result_hash'][:8]}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_xlsx(result, out / "report.xlsx")
    write_markdown(result, out / "summary.md")
    for d in result["decisions"]:
        print(f"{d['ar_id']}: {d['verdict']:<26} {d['reason']}")
    print(f"\n결과 해시 {result['result_hash'][:16]}… → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
