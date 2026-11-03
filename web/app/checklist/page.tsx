"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge, StatusIcon, Tone } from "../components/Status";
import { useToast } from "../components/Toast";
import { API, api, fmtTime, post } from "../lib/api";
import { targetLabel, usePref } from "../lib/prefs";

type State = "fix" | "ok" | "na" | "unknown";
type AutoAr = { ar_id: string; tone: State; reviewed: boolean; reason: string; found: string[] };
type Judgement = { state: State; by: string; comment: string; at: string };
type EvFile = { file: string; sha256: string; size: number; scan_status: string; by: string; at: string };
type CP = { index: number; state: State; source: "manual" | "auto" | "none"; auto: { tone: State; ars: AutoAr[]; run_id: string } | null;
  manual: Judgement | null; files: EvFile[]; covered_by_ar: string[] };
type Crit = { id: string; name: string; field_id: string; field: string; area: string; scope: string; print_page: number;
  state: State; counts: Record<State, number>; automated: boolean; checkpoints: CP[] };
type Checklist = { target: string; run_id: string | null; has_text: boolean; criteria: Crit[];
  totals: Record<State, number> & { checkpoints: number; criteria: number; criteria_decided: number; criteria_fix: number; automated_criteria: number } };
type Full = { id: string; criterion?: string; checkpoints?: string[] | number; laws?: string[]; evidence?: string[];
  cases?: { no: number; text: string }[]; detail?: string; law_notes?: string[]; print_page: number; print_end_page: number; pdf_page: number };

const WORD: Record<State, string> = { fix: "고칠 것", ok: "규칙대로", na: "해당 없음", unknown: "미확인" };
const ORDER: State[] = ["fix", "unknown", "ok", "na"];

function Detail({ text }: { text: string }) {
  const out: { c: string; t: string }[] = [];
  text.split("\n").forEach((raw) => {
    const l = raw.trim(); if (!l) return;
    let c = "", t = l;
    if (l.startsWith("□")) { c = "d1"; t = l.slice(1).trim(); } else if (l.startsWith("▶")) { c = "d2"; } else if (l.startsWith("·")) { c = "d3"; }
    else if (l.startsWith("※") || l.startsWith("[참고]")) { c = "dn"; }
    if (c || !out.length) out.push({ c: c || "d0", t }); else out[out.length - 1].t += " " + t;
  });
  return <div className="detail">{out.map((o, i) => <div key={i} className={o.c}>{o.t}</div>)}</div>;
}

function CheckpointCard({ cp, text, target, cid, name, onSaved }: { cp: CP; text: string; target: string; cid: string; name: string; onSaved: () => void }) {
  const toast = useToast();
  const [state, setState] = useState<State>(cp.manual?.state ?? cp.state);
  const [comment, setComment] = useState(cp.manual?.comment ?? "");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => { setState(cp.manual?.state ?? cp.state); setComment(cp.manual?.comment ?? ""); }, [cp]);
  const changed = state !== (cp.manual?.state ?? cp.state) || comment !== (cp.manual?.comment ?? "");
  const dirty = changed || (!cp.manual && state !== "unknown");

  const save = async () => {
    if (!name) { toast("오른쪽 위에서 이름을 먼저 설정해 주세요. 판단 기록에 남아요.", "error"); return; }
    setBusy(true);
    try { await post(`/checklist/${cid}/${cp.index}`, { target, state, by: name, comment }); toast(`${cid} 확인사항 ${cp.index}: ${WORD[state]}(으)로 기록했어요.`); onSaved(); }
    catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
  };
  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    for (const f of Array.from(files)) {
      const fd = new FormData(); fd.append("target", target); fd.append("by", name); fd.append("file", f);
      const r = await fetch(`${API}/checklist/${cid}/${cp.index}/files`, { method: "POST", body: fd });
      const b = await r.json();
      if (!r.ok) toast(`${f.name}: ${b.detail}`, "error"); else toast(`${f.name}을 증적으로 붙였어요.`);
    }
    onSaved();
  };

  return (
    <article className={`cp tone-${cp.state}`} id={`${cid}-${cp.index}`}>
      <div className="cp-head">
        <span className="cp-no">{cp.index}</span>
        <p className="cp-text">{text || `확인사항 ${cp.index} (원문 정리본이 없어 번호만 표시)`}</p>
        <div className="cp-status">
          <StatusBadge tone={cp.state === "na" ? "na" : (cp.state as Tone)}>{WORD[cp.state]}</StatusBadge>
          <span className="small muted">{cp.source === "manual" ? `담당자 ${cp.manual?.by}, ${fmtTime(cp.manual!.at)}` : cp.source === "auto" ? "자동 점검 결과" : "아직 판단 없음"}</span>
        </div>
      </div>

      {cp.auto && (
        <div className="cp-auto">
          <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>자동 점검 {cp.auto.ars.length}건 <a className="small" href={`/runs/${encodeURIComponent(cp.auto.run_id)}`}>진단 결과 보기</a></div>
          {cp.auto.ars.map((a) => (
            <div key={a.ar_id} className="small" style={{ margin: "4px 0" }}>
              <StatusBadge tone={a.tone as Tone}>{WORD[a.tone]}{a.reviewed ? " · 검토됨" : ""}</StatusBadge> <code>{a.ar_id}</code>
              {a.found.length > 0 && <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{a.found.map((f, i) => <li key={i}>{f}</li>)}</ul>}
            </div>
          ))}
        </div>
      )}

      <div className="cp-judge">
        <div className="seg" role="group" aria-label="담당자 판단">
          {(["fix", "ok", "na", "unknown"] as State[]).map((s) => (
            <button key={s} aria-pressed={state === s} onClick={() => setState(s)}>{WORD[s]}</button>
          ))}
        </div>
        <textarea className="input" rows={2} value={comment} onChange={(e) => setComment(e.target.value)}
          placeholder={state === "fix" ? "무엇이 문제인지 적어 주세요 (필수)" : state === "na" ? "해당하지 않는 이유를 적어 주세요 (필수)" : "확인한 근거나 메모 (선택)"} aria-label="근거·의견" />
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn" onClick={() => fileRef.current?.click()}>증적 붙이기</button>
            <input ref={fileRef} type="file" multiple hidden onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
            {cp.files.map((f) => (
              <a key={f.sha256 + f.at} className="chip small" href={`${API}/checklist/files/${f.sha256}?target=${encodeURIComponent(target)}`}>{f.file}</a>
            ))}
          </div>
          <button className="btn btn-primary" onClick={save} disabled={busy || !dirty}>{busy ? "기록하는 중…" : !cp.manual && !changed && cp.auto ? "자동 결과로 확정" : "판단 기록"}</button>
        </div>
      </div>
    </article>
  );
}

export default function ChecklistPage() {
  const [target, , ready] = usePref("target");
  const [name] = usePref("name");
  const [data, setData] = useState<Checklist | null>(null);
  const [full, setFull] = useState<Full | null>(null);
  const [sel, setSel] = useState("");
  const [area, setArea] = useState("");
  const [filter, setFilter] = useState<State | "">("");
  const [autoOnly, setAutoOnly] = useState(false);
  const [q, setQ] = useState("");
  const [names, setNames] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");

  const load = useCallback(() => {
    if (!ready || !target) return;
    api<Checklist>(`/checklist?target=${encodeURIComponent(target)}`).then(setData).catch((e) => setErr(e.message));
  }, [ready, target]);
  useEffect(load, [load]);
  useEffect(() => { setSel(decodeURIComponent(window.location.hash.slice(1)) || "2.5.4"); }, []);
  useEffect(() => { if (sel) api<Full>(`/catalog/${sel}`).then(setFull).catch(() => setFull(null)); }, [sel]);

  const visible = useMemo(() => {
    if (!data) return [];
    const k = q.trim().toLowerCase();
    return data.criteria.filter((c) => (!area || c.id[0] === area) && (!autoOnly || c.automated)
      && (!filter || c.counts[filter] > 0) && (!k || `${c.id} ${c.name} ${c.field}`.toLowerCase().includes(k)));
  }, [data, area, filter, autoOnly, q]);

  const go = (id: string) => { setSel(id); history.replaceState(null, "", `#${id}`); const el = document.getElementById("cl-detail");
    if (el && window.matchMedia("(max-width: 900px)").matches) el.scrollIntoView({ behavior: "smooth", block: "start" }); };
  useEffect(() => { setNames({}); }, [target]);

  if (err) return <p className="error">{err}</p>;
  if (!data) return <p className="muted">불러오는 중…</p>;
  const T = data.totals;
  const c = data.criteria.find((x) => x.id === sel) ?? data.criteria[0];
  const texts = Array.isArray(full?.checkpoints) ? (full!.checkpoints as string[]) : [];
  let lastField = "";

  return (
    <div className="stack" style={{ gap: 14 }}>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>전체 점검표</h1>
          <p className="muted small">{targetLabel(target)}의 ISMS-P 인증기준 {T.criteria}개, 주요 확인사항 {T.checkpoints}개. 자동 점검이 있는 기준 {T.automated_criteria}개, 나머지는 담당자가 판단해 기록해요.</p>
        </div>
        <a className="btn" href={`${API}/checklist/report.xlsx?target=${encodeURIComponent(target)}`}>점검표 내려받기 (xlsx)</a>
      </div>

      <section className="panel cl-summary">
        <div>
          <div className="small muted">확인사항을 모두 판단한 인증기준</div>
          <div className="row" style={{ gap: 10, alignItems: "baseline" }}><b style={{ fontSize: 22 }}>{T.criteria_decided}</b><span className="muted">/ {T.criteria}</span>
            <span className="small" style={{ color: "var(--fix)", fontWeight: 600 }}>고칠 것이 있는 기준 {T.criteria_fix}개</span></div>
          <div className="meter" style={{ marginTop: 6 }}><i style={{ width: `${(T.criteria_decided / T.criteria) * 100}%` }} /></div>
        </div>
        <div className="filters" role="group" aria-label="확인사항 상태로 거르기">
          <button className="chip" aria-pressed={filter === ""} onClick={() => setFilter("")}>전체 <span className="n">{T.checkpoints}</span></button>
          {ORDER.map((s) => (
            <button key={s} className="chip" aria-pressed={filter === s} onClick={() => setFilter(filter === s ? "" : s)}>
              <span style={{ color: `var(--${s === "fix" ? "fix" : s === "ok" ? "ok" : "unk"})`, display: "inline-flex" }}><StatusIcon tone={s as Tone} /></span>
              {WORD[s]} <span className="n">{T[s]}</span>
            </button>
          ))}
        </div>
      </section>
      {!data.has_text && <p className="notice">안내서 정리본(data/sources/ISMS-P_인증기준_2023-11.json)이 없어 번호와 이름만 보여요. 파일을 넣고 다시 시작하면 인증기준·확인사항·결함사례가 함께 보여요.</p>}

      <div className="cl">
        <aside className="cl-list">
          <div className="cl-tools">
            <input className="input" placeholder="번호나 이름으로 찾기" value={q} onChange={(e) => setQ(e.target.value)} aria-label="인증기준 찾기" />
            <div className="row" style={{ gap: 4 }}>
              {["", "1", "2", "3"].map((a) => <button key={a} className="chip small" aria-pressed={area === a} onClick={() => setArea(a)}>{a ? `${a}영역` : "전체"}</button>)}
              <label className="small row" style={{ gap: 4, marginLeft: 4 }}><input type="checkbox" checked={autoOnly} onChange={(e) => setAutoOnly(e.target.checked)} />자동 점검</label>
            </div>
          </div>
          <div className="cl-scroll" role="listbox" aria-label="인증기준 목록">
            {visible.length === 0 && <p className="muted small" style={{ padding: 14 }}>조건에 맞는 인증기준이 없어요.</p>}
            {visible.map((x) => {
              const head = x.field_id !== lastField ? (lastField = x.field_id, true) : false;
              const fieldItems = data.criteria.filter((y) => y.field_id === x.field_id);
              const done = fieldItems.filter((y) => y.counts.unknown === 0).length;
              return (
                <div key={x.id}>
                  {head && <div className="cl-grp"><span>{x.field_id} {x.field}</span><span>{done}/{fieldItems.length}</span></div>}
                  <button className="cl-item" role="option" aria-selected={x.id === c.id} onClick={() => go(x.id)}>
                    <span style={{ color: `var(--${x.state === "fix" ? "fix" : x.state === "ok" ? "ok" : "unk"})`, display: "inline-flex" }}><StatusIcon tone={x.state as Tone} size={15} /></span>
                    <span className="cl-id">{x.id}</span>
                    <span className="cl-name">{x.name}</span>
                    {x.automated && <span className="cl-auto">자동</span>}
                  </button>
                </div>
              );
            })}
          </div>
        </aside>

        <section className="cl-detail" id="cl-detail" aria-live="polite">
          <div className="small muted">{c.area} › {c.field_id} {c.field}</div>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <h2 style={{ fontSize: 22, margin: "2px 0 6px" }}>{c.id} {c.name}</h2>
            <StatusBadge tone={c.state as Tone}>{WORD[c.state]}</StatusBadge>
          </div>
          <div className="row small" style={{ gap: 6, marginBottom: 12 }}>
            {full && <span className="chip small" style={{ cursor: "default" }}>안내서 {full.print_page}{full.print_end_page !== full.print_page ? `~${full.print_end_page}` : ""}쪽 (PDF {full.pdf_page})</span>}
            <span className="chip small" style={{ cursor: "default" }}>적용 {c.scope}</span>
            <span className="chip small" style={{ cursor: "default" }}>확인사항 {c.checkpoints.length}개 중 판단 {c.checkpoints.length - c.counts.unknown}개</span>
          </div>
          {full?.criterion && <p className="cl-crit">{full.criterion}</p>}
          {full?.laws && (
            <p className="small" style={{ marginTop: 8 }}><b>관련 법규</b> {full.laws.length ? full.laws.join(" / ") : "안내서에 표기 없음"}</p>
          )}
          {full?.law_notes?.map((n, i) => <p key={i} className="notice small" style={{ marginTop: 6, background: "var(--fix-bg)" }}>{n}</p>)}

          <h3 style={{ margin: "18px 0 8px" }}>주요 확인사항</h3>
          <div className="stack" style={{ gap: 10 }}>
            {c.checkpoints.map((cp) => (
              <CheckpointCard key={`${c.id}-${cp.index}-${cp.manual?.at ?? ""}-${cp.files.length}`} cp={cp} text={texts[cp.index - 1] ?? ""}
                target={target} cid={c.id} name={name} onSaved={load} />
            ))}
          </div>

          {full?.evidence && full.evidence.length > 0 && (
            <details className="cl-more" open>
              <summary>준비할 자료 (안내서의 증거자료 예시 {full.evidence.length}개)</summary>
              <ul>{full.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
            </details>
          )}
          {full?.cases && full.cases.length > 0 && (
            <details className="cl-more">
              <summary>참고 결함사례 {full.cases.length}건</summary>
              <ol>{full.cases.map((k) => <li key={k.no}>{k.text}</li>)}</ol>
            </details>
          )}
          {full?.detail && (
            <details className="cl-more">
              <summary>세부 설명</summary>
              <Detail text={full.detail} />
              <p className="small muted">표는 줄글로 펼쳐져 있어요. 표 모양은 안내서 {full.print_page}쪽에서 확인하세요.</p>
            </details>
          )}
          <p className="small muted" style={{ marginTop: 18 }}>출처: 개인정보보호위원회·KISA, ISMS-P 인증기준 안내서(2023.11). 원문은 이 서비스 안에서만 보여 주고 저장소에는 올리지 않아요.</p>
        </section>
      </div>
    </div>
  );
}
