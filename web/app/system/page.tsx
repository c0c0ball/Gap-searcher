"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";

type Check = { ok: boolean; detail: string };
type Health = { ok: boolean; checks: Record<string, Check> };
type Finding = { rule: string; severity: string; where: string; message: string };
type Lint = { ok: boolean; files: number; requirements: number; errors: Finding[]; warnings: Finding[] };

const LABEL: Record<string, [string, string]> = {
  postgres: ["데이터베이스", "PostgreSQL + pgvector"],
  redis: ["작업 대기열", "Redis"],
  minio: ["원본 파일 보관소", "MinIO"],
  clamav: ["업로드 파일 검사", "ClamAV"],
  ollama: ["문서 읽기 보조 AI", "Ollama (내 컴퓨터)"],
};

export default function System() {
  const [h, setH] = useState<Health | null>(null);
  const [lint, setLint] = useState<Lint | null>(null);
  const [w, setW] = useState<Check | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    setErr("");
    Promise.all([api<Health>("/health"), api<Lint>("/requirements/lint")]).then(([a, b]) => { setH(a); setLint(b); })
      .catch((e) => setErr(String(e.message)));
  }, []);
  useEffect(load, [load]);
  const ping = async () => { setW(null); setW(await api<Check>("/health/worker", { method: "POST" }).catch((e) => ({ ok: false, detail: String(e.message) }))); };

  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>시스템 상태</h1><p className="muted">서비스를 이루는 구성요소가 제대로 연결됐는지 확인해요.</p></div>
        <button className="btn" onClick={load}>다시 확인</button>
      </div>
      {err && <p className="error">서버(api)에 연결하지 못했어요: {err}</p>}
      <section className="panel">
        <table className="table">
          <thead><tr><th>구성요소</th><th>상태</th><th>자세히</th></tr></thead>
          <tbody>
            {Object.entries(LABEL).map(([k, [name, tech]]) => {
              const c = h?.checks[k];
              return (
                <tr key={k}>
                  <td><b>{name}</b><div className="small muted">{tech}</div></td>
                  <td>{c ? <span className={`pill ${c.ok ? "t-ok" : "t-fix"}`}>{c.ok ? "정상" : "문제 있음"}</span> : <span className="pill t-unknown">확인 중</span>}</td>
                  <td className="small muted" style={{ wordBreak: "break-all" }}>{c?.detail}</td>
                </tr>
              );
            })}
            <tr>
              <td><b>작업 처리기</b><div className="small muted">Celery worker</div></td>
              <td>{w ? <span className={`pill ${w.ok ? "t-ok" : "t-fix"}`}>{w.ok ? "정상" : "문제 있음"}</span> : <button className="btn" onClick={ping}>왕복 확인</button>}</td>
              <td className="small muted">{w?.detail ?? "api → 대기열 → worker → api로 신호를 한 번 보내 봐요."}</td>
            </tr>
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>점검 규칙 검사</h2>
        {lint && <>
          <p className="row"><span className={`pill ${lint.ok ? "t-ok" : "t-fix"}`}>{lint.ok ? "오류 없음" : `오류 ${lint.errors.length}건`}</span>
            <span className="small muted">규칙 파일 {lint.files}개, 확인 항목 {lint.requirements}개, 참고 경고 {lint.warnings.length}건</span></p>
          {(lint.errors.length + lint.warnings.length > 0) && (
            <details style={{ marginTop: 10 }}><summary className="small">경고·오류 목록 보기</summary>
              <ul className="small">{[...lint.errors, ...lint.warnings].map((f, i) => (
                <li key={i} style={{ color: f.severity === "error" ? "var(--fix)" : "var(--muted)" }}>[{f.rule}] {f.where}: {f.message}</li>))}
              </ul></details>)}
        </>}
      </section>
    </div>
  );
}
