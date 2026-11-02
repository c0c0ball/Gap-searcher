"""보고서: xlsx(검토용 상세)와 markdown(요약). 문구는 보고서 문구 정책(v1.2 13.3)을 따른다."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

FILL = {
    "CANDIDATE_NONCONFORMITY": "FDECEE",
    "CANDIDATE_CONFORMING": "EAF6EA",
    "CANDIDATE_PARTIAL": "FFF3E6",
    "INSUFFICIENT_EVIDENCE": "F1F2F4",
    "NOT_APPLICABLE_PENDING": "F1F2F4",
}
DISCLAIMER = ("이 결과는 제출·수집된 자료와 정해진 규칙으로 계산한 '후보'입니다. 검토자가 승인하기 전에는 "
              "결함 확정이나 인증 적합을 뜻하지 않습니다.")


def _sheet(wb, title, head, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8EEF6")
    for r in rows:
        ws.append(r)
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    return ws


def write_xlsx(result: dict, path: Path, reviews: dict[str, dict] | None = None) -> None:
    reviews = reviews or {}
    wb = Workbook()
    ws = wb.active
    ws.title = "개요"
    for k, v in [("조직", result["organization"]), ("기준일", result["as_of"]), ("기준", result["criterion"]),
                 ("결과 해시", result["result_hash"]), ("스냅샷", result["snapshot"]["snapshot_id"]),
                 ("스냅샷 출처", result["snapshot"]["source"]), ("문서 범위", result["document_coverage"]["detail"]),
                 ("주의", DISCLAIMER)]:
        ws.append([k, v])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 14, 100
    for c in ws["A"]:
        c.font = Font(bold=True)

    # 쉬운 설명 시트 — 일반 직원 공유용. 검토 결과가 있으면 그 상태를 쓴다.
    from .plain import status_after_review
    pl = result.get("plain")
    if pl:
        ps = wb.create_sheet("쉬운 설명", 0)
        ps.append([pl["headline"]])
        ps.append([pl["notice"]])
        ps.append([])
        ps.append(["확인한 것", "결과", "발견한 내용", "왜 중요해요?", "어떻게 고치나요?", "누가"])
        for c in ps[4]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="E8EEF6")
        for it in pl["items"]:
            rv = reviews.get(it["ar_id"])
            st, sub, icon = status_after_review(rv["state"]) if rv else (it["status"], it["status_sub"], it["icon"])
            ps.append([it["question"], f"{icon} {st}" + (f"\n({sub})" if sub else ""),
                       "\n".join(f"• {f}" for f in it["found"]) or it["note"], it["why"],
                       "\n".join(f"{i}. {f}" for i, f in enumerate(it["fix"], 1)), it["owner"]])
        ps["A1"].font = Font(bold=True, size=13)
        for col, w in zip("ABCDEF", (34, 22, 60, 48, 60, 20)):
            ps.column_dimensions[col].width = w
        for row in ps.iter_rows(min_row=5):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        wb.active = 0

    ev_by = {e["ar_id"]: e for e in result["evaluations"]}
    title = {q["ar_id"]: q["title"] for q in result.get("requirements", [])}
    rows = []
    for d in result["decisions"]:
        rv = reviews.get(d["ar_id"], {})
        rows.append([d["ar_id"], title.get(d["ar_id"], ""), d["verdict"], rv.get("external_label", d["external_label_pending"]),
                     d["reason"], ev_by[d["ar_id"]]["coverage_detail"], rv.get("decision", "미검토")])
    s = _sheet(wb, "요구사항별 결과", ["AR", "요구사항", "후보 판정", "외부 표기", "사유", "범위", "검토"], rows,
               [14, 40, 26, 22, 60, 50, 12])
    for r in s.iter_rows(min_row=2):
        r[2].fill = PatternFill("solid", fgColor=FILL.get(r[2].value, "FFFFFF"))

    obs_by = {o["obs_id"]: o for o in result["observations"]}
    frows = []
    for f in result["findings"]:
        cites = []
        for oid in f["obs_ids"]:
            o = obs_by.get(oid, {})
            for c in o.get("citations", []):
                cites.append(f"{c['locator']}: \"{c['quote']}\"")
            if o.get("source", {}).get("api"):
                cites.append(f"{o['source']['api']} @ {o['source'].get('account_id')} ({o['source'].get('collected_at')})")
        frows.append([f["finding_id"], f["primary_criterion"], ", ".join(f["related_criteria"]), f["subject"],
                      f["summary"], "\n".join(cites)])
    _sheet(wb, "결함 후보", ["ID", "대표 기준", "관련 기준(참고)", "대상", "내용", "근거"], frows,
           [20, 10, 14, 26, 60, 80])

    orows = []
    for o in result["observations"]:
        vals = ", ".join(f"{k}={v}" for k, v in o["values"].items() if k != "candidates")
        orows.append([o["obs_id"], o["axis"], o["extractor"], o["quality"], "; ".join(o["quality_reasons"]), vals])
    _sheet(wb, "관측", ["관측 ID", "축", "추출", "품질", "품질 사유", "값"], orows, [40, 10, 12, 8, 40, 80])

    arows = [[a["path"], a["kind"], a["sha256"], a["scan_status"]] for a in result["artifacts"]]
    _sheet(wb, "원본(계보)", ["경로", "종류", "SHA-256", "검역"], arows, [50, 18, 70, 12])
    wb.save(path)


def write_markdown(result: dict, path: Path) -> None:
    L = [f"# {result['organization']} — {result['criterion']} 갭분석 결과 (기준일 {result['as_of']})", "",
         f"> {DISCLAIMER}", "",
         f"- 결과 해시: `{result['result_hash'][:16]}…`",
         f"- 스냅샷: {result['snapshot']['snapshot_id']} ({result['snapshot']['source']}, {result['snapshot']['collected_at']})",
         f"- 문서 범위: {result['document_coverage']['detail']}", "",
         "| AR | 요구사항 | 후보 판정 | 외부 표기(검토 전) | 사유 |", "|---|---|---|---|---|"]
    title = {q["ar_id"]: q["title"] for q in result.get("requirements", [])}
    for d in result["decisions"]:
        L.append(f"| {d['ar_id']} | {title.get(d['ar_id'], '')} | {d['verdict']} | {d['external_label_pending']} | {d['reason']} |")
    pl = result.get("plain")
    if pl:
        L += ["", "## 쉬운 설명", "", pl["headline"], "", f"> {pl['notice']}", ""]
        for it in pl["items"]:
            L.append(f"### {it['icon']} {it['question']} — {it['status']}")
            for f in it["found"]:
                L.append(f"- {f}")
            if it["note"]:
                L.append(f"- {it['note']}")
            if it["fix"]:
                L.append(f"- **왜 중요해요?** {it['why']}")
                L.append("- **어떻게 고치나요?**")
                L += [f"  {i}. {f}" for i, f in enumerate(it["fix"], 1)]
                L.append(f"- **누가:** {it['owner']}")
            L.append("")
    L += ["", "## 결함 후보", ""]
    for f in result["findings"]:
        L.append(f"- **{f['finding_id']}** ({f['primary_criterion']}) {f['summary']}")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
