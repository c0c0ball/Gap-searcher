"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../components/Toast";
import { API, PARAM_LABEL, TABLE_LABEL, api, post } from "../lib/api";
import { usePref } from "../lib/prefs";

type WS = { name: string; target: string; organization: string; documents: number; evidence: number; base?: string };
type FileRow = { kind: string; file: string; exists: boolean; size: number; uploaded_at?: string; sha256?: string; doc_id?: string };
type Detail = { name: string; target: string; organization: string; as_of: string; base?: string; files: FileRow[] };
type Extracted = { param: string; value: unknown; locator: string; quote: string };
type UploadResult = { file: string; minio: string; artifact: { sha256: string; scan_status: string; scan_detail: string };
  preview: { meta?: Record<string, string>; clauses?: number; articles?: string[]; extracted?: Extracted[]; conflicts?: string[];
    tables?: { kind: string; sheet: string; rows: number }[]; error?: string } };

const SCAN: Record<string, [string, string]> = {
  clean: ["t-ok", "악성코드 없음"], not_scanned: ["t-unknown", "검사하지 못함"], error: ["t-unknown", "검사 오류"],
};
const fmtVal = (v: unknown) => (v === true ? "예" : v === false ? "아니오" : String(v));

export default function Upload() {
  const toast = useToast();
  const [target, setTarget, ready] = usePref("target");
  const [list, setList] = useState<WS[]>([]);
  const [sel, setSelRaw] = useState("");
  const setSel = (n: string) => { setSelRaw(n); if (n) setTarget(`ws:${n}`); };
  const [detail, setDetail] = useState<Detail | null>(null);
  const [newName, setNewName] = useState("");
  const [kind, setKind] = useState<"policy_document" | "evidence">("policy_document");
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState("");
  const [results, setResults] = useState<UploadResult[]>([]);
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const loadList = useCallback(async () => {
    const l = await api<WS[]>("/workspaces").catch((e) => { setErr(e.message); return []; });
    setList(l);
    return l;
  }, []);
  const loadDetail = useCallback(async (name: string) => { if (name) setDetail(await api<Detail>(`/workspaces/${encodeURIComponent(name)}`)); }, []);
  useEffect(() => {
    if (!ready) return;
    loadList().then((l) => {
      const cur = target.startsWith("ws:") ? target.slice(3) : "";
      setSelRaw((prev) => prev || (l.find((w) => w.name === cur)?.name ?? ""));
    });
  }, [loadList, ready, target]);
  useEffect(() => { setResults([]); loadDetail(sel).catch((e) => setErr(e.message)); }, [sel, loadDetail]);

  const create = async () => {
    setErr("");
    try { await post("/workspaces", { name: newName.trim(), base: "a-corp-dev" }); await loadList(); setSel(newName.trim()); toast(`작업공간 '${newName.trim()}'을 만들었어요.`); setNewName(""); }
    catch (e) { setErr((e as Error).message); }
  };

  const send = async (files: FileList | null) => {
    if (!files || !sel) return;
    setErr("");
    for (const f of Array.from(files)) {
      setBusy(`${f.name} 올리는 중…`);
      const fd = new FormData();
      fd.append("kind", kind);
      fd.append("file", f);
      try {
        const r = await fetch(`${API}/workspaces/${encodeURIComponent(sel)}/files`, { method: "POST", body: fd });
        const body = await r.json();
        if (!r.ok) throw new Error(body.detail);
        setResults((x) => [body, ...x]);
        toast(`${f.name}을 올렸어요.`);
      } catch (e) { setErr(`${f.name}: ${(e as Error).message}`); }
    }
    setBusy("");
    loadDetail(sel);
  };

  const remove = async (file: string) => {
    if (!sel) return;
    try { await post(`/workspaces/${encodeURIComponent(sel)}/files/remove`, { file }); toast(`${file.split("/").pop()}을 뺐어요.`); loadDetail(sel); }
    catch (e) { setErr((e as Error).message); }
  };

  const run = async () => {
    if (!detail) return;
    setBusy("진단 실행 중…");
    try { const r = await post<{ run_id: string }>("/runs", { target: detail.target }); window.location.href = `/runs/${r.run_id}`; }
    catch (e) { setErr((e as Error).message); setBusy(""); }
  };

  const docCount: Record<string, number> = {};
  detail?.files.forEach((f) => { if (f.kind === "policy_document" && f.doc_id) docCount[f.doc_id] = (docCount[f.doc_id] ?? 0) + 1; });
  const dupes = Object.entries(docCount).filter(([, n]) => n > 1).map(([k]) => k);

  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>자료 올리기</h1><p className="muted">규정 문서와 증적을 올리면 검사하고 조항을 읽어 둬요. 올린 자료로 바로 진단할 수 있어요.</p></div>
      </div>

      <ol className="steps" aria-label="진행 단계">
        <li className={`step ${sel ? "done" : "now"}`}><b>{sel ? "✓" : "1"}</b><span>작업공간 고르기</span></li>
        <li className={`step ${!sel ? "" : (detail?.files.length ?? 0) > 0 ? "done" : "now"}`}><b>{sel && (detail?.files.length ?? 0) > 0 ? "✓" : "2"}</b><span>자료 올리기</span></li>
        <li className={`step ${sel ? "now" : ""}`}><b>3</b><span>진단하기</span></li>
      </ol>

      <section className="panel row" style={{ justifyContent: "space-between" }}>
        <label className="field">작업공간
          <select className="input" value={sel} onChange={(e) => setSel(e.target.value)} style={{ minWidth: 220 }}>
            <option value="">{list.length === 0 ? "아직 없어요. 오른쪽에서 만드세요" : "작업공간을 고르세요"}</option>
            {list.map((w) => <option key={w.name} value={w.name}>{w.name}</option>)}
          </select>
        </label>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <label className="field">새 작업공간 이름
            <input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="예: 2026-4분기-점검" />
          </label>
          <button className="btn" onClick={create} disabled={newName.trim().length < 2}>만들기</button>
        </div>
      </section>
      <p className="small muted">새 작업공간은 예제 회사(A사)의 자료와 AWS 수집 결과를 복사해서 시작해요. 문서를 바꾸면 결과가 어떻게 달라지는지 시험해 볼 수 있어요.</p>
      {err && <p className="error" role="alert">{err}</p>}

      {detail && <>
        <section className="stack" style={{ gap: 10 }}>
          <div className="row">
            <div className="seg" role="group" aria-label="자료 종류">
              <button aria-pressed={kind === "policy_document"} onClick={() => setKind("policy_document")}>규정 문서 (.docx)</button>
              <button aria-pressed={kind === "evidence"} onClick={() => setKind("evidence")}>증적 (캡처·목록·PDF)</button>
            </div>
          </div>
          <div className={`drop ${over ? "over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
            onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files); }}>
            <p style={{ fontWeight: 600 }}>파일을 여기로 끌어 놓으세요</p>
            <p className="small muted" style={{ margin: "4px 0 12px" }}>
              {kind === "policy_document" ? "제N조 형식의 규정 문서(.docx)를 받아요. 한 번에 20MB까지." : "png·pdf·xlsx·csv를 받아요. 한 번에 20MB까지."}
            </p>
            <button className="btn" onClick={() => fileRef.current?.click()} disabled={!!busy}>파일 고르기</button>
            <input ref={fileRef} type="file" multiple hidden accept={kind === "policy_document" ? ".docx" : ".png,.pdf,.xlsx,.csv"}
              onChange={(e) => { send(e.target.files); e.target.value = ""; }} />
            {busy && <p className="small" style={{ marginTop: 10 }} aria-live="polite">{busy}</p>}
          </div>
        </section>

        {results.map((r) => {
          const [cls, label] = SCAN[r.artifact.scan_status] ?? ["t-unknown", r.artifact.scan_status];
          const p = r.preview;
          return (
            <section key={r.artifact.sha256} className="panel stack" style={{ gap: 12 }}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <h2 style={{ margin: 0 }}>{r.file.split("/").pop()}</h2>
                <div className="row"><span className={`pill ${cls}`}>{label}</span>
                  <span className={`pill ${r.minio === "stored" ? "t-ok" : "t-unknown"}`}>{r.minio === "stored" ? "원본 보관됨" : "원본 보관 안 됨"}</span></div>
              </div>
              <p className="small muted" style={{ wordBreak: "break-all" }}>지문(SHA-256) {r.artifact.sha256}</p>
              {p.meta && <p className="small">{p.meta["제목"]} {p.meta["버전"]} — 시행일 {p.meta["시행일"] ?? "없음"}, 문서번호 {p.meta["문서번호"] ?? "없음"}, 조항 {p.clauses}개를 읽었어요.</p>}
              {p.extracted && (p.extracted.length === 0
                ? <p className="small muted">이 문서에서는 비밀번호·계정 규칙을 찾지 못했어요.</p>
                : <table className="table">
                    <thead><tr><th>찾은 규칙</th><th>값</th><th>문서 속 위치와 문장</th></tr></thead>
                    <tbody>{p.extracted.map((x) => (
                      <tr key={x.param}><td>{PARAM_LABEL[x.param] ?? x.param}</td><td><b>{fmtVal(x.value)}</b></td>
                        <td className="small"><div className="muted">{x.locator}</div>“{x.quote}”</td></tr>))}
                    </tbody>
                  </table>)}
              {p.tables && (p.tables.length === 0
                ? <p className="small muted">{p.error ?? "이 표는 진단에 쓰는 서류(계정 관리대장, 인사 명부, 특수권한자 목록, 접근권한 검토 기록)로 알아보지 못했어요. 첫 줄 제목 칸을 확인해 주세요."}</p>
                : <p className="small">{p.tables.map((t) => `'${t.sheet}' 시트를 ${TABLE_LABEL[t.kind] ?? t.kind}(${t.rows}행)`).join(", ")}로 읽었어요. 진단할 때 자동으로 대조해요.</p>)}
              {p.conflicts && p.conflicts.length > 0 && <p className="error small">문서 안에서 값이 서로 달라요: {p.conflicts.join(", ")}</p>}
            </section>
          );
        })}

        <section className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 6 }}>
            <h2 style={{ margin: 0 }}>{detail.name}에 들어 있는 자료</h2>
            <button className="btn btn-primary" onClick={run} disabled={!!busy || dupes.length > 0}
              title={dupes.length ? "같은 규정이 두 번 들어 있어 진단할 수 없어요" : ""}>이 자료로 진단하기</button>
          </div>
          <table className="table">
            <thead><tr><th>종류</th><th>파일</th><th>크기</th><th /></tr></thead>
            <tbody>{detail.files.map((f) => (
              <tr key={f.file}>
                <td className="small">{f.kind === "policy_document" ? "규정 문서" : "증적"}</td>
                <td>{f.file.split("/").pop()}{!f.exists && <span className="error small"> (파일 없음)</span>}
                  {f.doc_id && dupes.includes(f.doc_id) && <div className="small" style={{ color: "var(--fix)" }}>문서번호 {f.doc_id}가 겹쳐요</div>}</td>
                <td className="small muted">{Math.max(1, Math.round(f.size / 1024))}KB</td>
                <td style={{ textAlign: "right" }}><button className="btn btn-ghost btn-danger small" onClick={() => remove(f.file)}>빼기</button></td>
              </tr>))}
            </tbody>
          </table>
          {dupes.length > 0
            ? <p className="error small" role="alert" style={{ marginTop: 8 }}>같은 규정이 두 번 들어 있어요 ({dupes.join(", ")}). 이대로 진단하면 값이 서로 달라 판단을 보류해요. 옛 판을 빼 주세요.</p>
            : <p className="small muted" style={{ marginTop: 8 }}>같은 규정의 옛 판과 새 판을 함께 두면 값이 충돌해 판단을 보류해요.</p>}
        </section>
      </>}
    </div>
  );
}
