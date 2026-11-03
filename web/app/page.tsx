"use client";

import { useCallback, useEffect, useState } from "react";
import { StatusBadge, StatusIcon, TONE_WORD, Tone } from "./components/Status";
import { useToast } from "./components/Toast";
import { api, fmtTime, post } from "./lib/api";
import { splitOrg, targetLabel, usePref } from "./lib/prefs";

type Strip = { ar_id: string; question: string; status: string; tone: Tone; reviewed: boolean; findings: number };
type Owner = { owner: string; total: number; done: number };
type Task = { task_id: string; run_id: string; owner: string; question: string; found: string[]; done: boolean };
type RunRow = { run_id: string; target: string; organization: string; generated_at: string; result_hash: string; counts: Record<string, number> };
type Counts = Record<Tone, number>;
type Dash = { latest: (RunRow & { snapshot: { source: string }; headline: string }) | null; strip: Strip[]; counts: Counts;
  trend: { before: Counts; after: Counts; generated_at: string } | null; owners: Owner[]; next_tasks: Task[];
  open_tasks: number; total_tasks: number; recent: RunRow[]; review_progress: { reviewed: number; total: number };
  criteria: { id: string; name: string; ars: string[] }[] };

function Trend({ t }: { t: Dash["trend"] }) {
  if (!t) return <span className="small muted">이 대상의 첫 진단이에요</span>;
  const diff = t.after.fix - t.before.fix;
  if (diff === 0) return <span className="small muted">지난 진단({fmtTime(t.generated_at)})과 고칠 것 개수가 같아요</span>;
  return (
    <span className="small" style={{ color: diff < 0 ? "var(--ok)" : "var(--fix)", fontWeight: 600 }}>
      지난 진단보다 고칠 것이 {Math.abs(diff)}개 {diff < 0 ? "줄었어요" : "늘었어요"} ({t.before.fix}개 → {t.after.fix}개)
    </span>
  );
}

export default function Dashboard() {
  const [target, , ready] = usePref("target");
  const [name] = usePref("name");
  const toast = useToast();
  const [d, setD] = useState<Dash | null>(null);
  const [health, setHealth] = useState<number | null>(null);
  const [err, setErr] = useState("");
  const [running, setRunning] = useState(false);
  const [cl, setCl] = useState<{ checkpoints: number; fix: number; ok: number; na: number; unknown: number; criteria: number; criteria_decided: number; criteria_fix: number; automated_criteria: number; automated_checkpoints: number } | null>(null);

  const load = useCallback(() => {
    if (!ready || !target) return;
    api<Dash>(`/dashboard?target=${encodeURIComponent(target)}`).then(setD).catch((e) => setErr(e.message));
    api<{ totals: NonNullable<typeof cl> }>(`/checklist?target=${encodeURIComponent(target)}`).then((x) => setCl(x.totals)).catch(() => setCl(null));
  }, [ready, target]);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ checks: Record<string, { ok: boolean }> }>("/health")
      .then((h) => setHealth(Object.values(h.checks).filter((c) => c.ok).length)).catch(() => setHealth(null));
  }, []);

  const runNow = async () => {
    setRunning(true);
    try { await post("/runs", { target }); toast("진단을 마쳤어요. 결과를 새로 불러왔어요."); load(); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setRunning(false); }
  };
  const complete = async (t: Task) => {
    if (!name) { toast("오른쪽 위에서 이름을 먼저 설정해 주세요.", "error"); return; }
    try { await post(`/runs/${t.run_id}/tasks/${encodeURIComponent(t.task_id)}`, { done: true, by: name }); toast("완료로 표시했어요."); load(); }
    catch (e) { toast((e as Error).message, "error"); }
  };

  if (err) return <p className="error">서버(api)에 연결하지 못했어요. docker compose가 켜져 있는지 확인하세요. ({err})</p>;
  if (!d) return <p className="muted">불러오는 중…</p>;
  if (!d.latest) return (
    <div className="panel stack" style={{ maxWidth: 560 }}>
      <h1>{targetLabel(target)}은(는) 아직 진단하지 않았어요</h1>
      <p className="muted">진단을 시작하면 규정 문서와 실제 설정을 비교해 고칠 부분을 찾아 드려요. 보통 몇 초면 끝나요.</p>
      <div className="row"><button className="btn btn-primary" onClick={runNow} disabled={running}>{running ? "진단하는 중…" : "지금 진단하기"}</button>
        <a className="btn" href="/upload">자료부터 올리기</a></div>
    </div>
  );

  const L = d.latest;
  const groups = d.criteria.length ? d.criteria : [{ id: "", name: "", ars: d.strip.map((s) => s.ar_id) }];
  const org = splitOrg(L.organization);
  const rid = L.run_id;

  return (
    <div className="stack" style={{ gap: 24 }}>
      <div className="page-head">
        <div>
          <h1>{org.name} ISMS-P 갭분석 현황</h1>
          <p className="muted small">{org.note ? `${org.note}. ` : ""}마지막 진단 {fmtTime(L.generated_at)}{L.snapshot.source === "fixture" ? ", 예제 AWS 데이터 사용" : ""}</p>
        </div>
        <div className="row">
          <a className="btn" href={`/runs/${rid}`}>결과 자세히 보기</a>
          <button className="btn btn-primary" onClick={runNow} disabled={running}>{running ? "진단하는 중…" : "다시 진단하기"}</button>
        </div>
      </div>

      {cl && (
        <a className="panel cl-card" href="/checklist" aria-label="전체 점검표 열기">
          <div>
            <h2 style={{ margin: 0 }}>ISMS-P 전체 점검표</h2>
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              인증기준 {cl.criteria}개, 확인사항 {cl.checkpoints}개. 그중 확인사항 {cl.automated_checkpoints}개({cl.automated_criteria}개 기준)는 자동 점검 결과로 채워지고, 나머지는 담당자가 판단해요.
              모든 확인사항을 판단한 기준은 {cl.criteria_decided}개예요.
            </p>
          </div>
          <div className="cl-card-bar" aria-hidden>
            {(["fix", "ok", "na", "unknown"] as const).map((k) => cl[k] > 0 && <i key={k} className={`b-${k}`} style={{ flexGrow: cl[k] }} />)}
          </div>
          <div className="row small" style={{ gap: 12 }}>
            <span className="muted" style={{ order: -1 }}>확인사항 기준</span>
            <span><b style={{ color: "var(--fix)" }}>{cl.fix}</b> 고칠 것</span><span><b style={{ color: "var(--ok)" }}>{cl.ok}</b> 규칙대로</span>
            <span><b>{cl.na}</b> 해당 없음</span><span><b>{cl.unknown}</b> 미확인</span>
          </div>
        </a>
      )}

      <section aria-labelledby="sum-h" className="stack" style={{ gap: 10 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2 id="sum-h" style={{ margin: 0 }}>자동 점검 규칙 {d.strip.length}개</h2>
            <p className="small muted" style={{ margin: "2px 0 0" }}>규칙 하나가 확인사항 하나의 일부를 봐요. 한 확인사항에 규칙이 여러 개면, 하나라도 고칠 것이 있으면 점검표에서는 그 확인사항이 '고칠 것'이 돼요.</p>
          </div>
          <Trend t={d.trend} />
        </div>
        <div className="filters" aria-label="상태별로 결과 보기">
          {(["fix", "ok", "unknown"] as Tone[]).map((t) => (
            <a key={t} className="chip" href={`/runs/${rid}?filter=${t}`}>
              <span style={{ color: `var(--${t === "unknown" ? "unk" : t})`, display: "inline-flex" }}><StatusIcon tone={t} /></span>
              {TONE_WORD[t]} <span className="n">{d.counts[t]}</span>
            </a>
          ))}
          <span className="chip" style={{ cursor: "default" }}>담당자 확인 <span className="n">{d.review_progress.reviewed}/{d.review_progress.total}</span></span>
        </div>
        <div className="strip-groups">
          {groups.map((g) => {
            const items = d.strip.filter((s) => g.ars.includes(s.ar_id));
            const nfix = items.filter((s) => s.tone === "fix").length;
            const nunk = items.filter((s) => s.tone === "unknown").length;
            return (
              <div key={g.id} className="strip-row">
                <a className="strip-label" href={`/checklist#${g.id}`}>
                  <b>{g.id}</b> <span>{g.name}</span>
                  <span className="small" style={{ color: nfix ? "var(--fix)" : nunk ? "var(--unk)" : "var(--ok)", fontWeight: 600 }}>
                    {nfix ? `고칠 것 ${nfix}` : nunk ? `판단 못함 ${nunk}` : "고칠 것 없음"}
                  </span>
                </a>
                <div className="strip">
                  {items.map((s) => (
                    <a key={s.ar_id} className={s.tone} href={`/runs/${rid}#${s.ar_id}`}>
                      <div className="q">{s.question}</div>
                      <div style={{ marginTop: 10 }}><StatusBadge tone={s.tone}>{s.status}</StatusBadge></div>
                      <div className="small muted" style={{ marginTop: 6 }}>{s.findings ? `${s.findings}건 발견, ` : ""}{s.reviewed ? "담당자 확인함" : "담당자 확인 전"}</div>
                    </a>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="grid-2">
        <section className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
            <h2 style={{ margin: 0 }}>다음에 할 일</h2>
            <a href="/tasks" className="small">전체 {d.open_tasks}개 보기</a>
          </div>
          {d.next_tasks.length === 0
            ? <p className="muted" style={{ padding: "12px 0" }}>남은 조치가 없어요. 고친 뒤에는 다시 진단해서 결과가 바뀌는지 확인하세요.</p>
            : d.next_tasks.map((t) => (
              <div key={t.task_id} className="task-row">
                <div style={{ minWidth: 0 }}>
                  <div className="small muted">{t.owner}</div>
                  <div style={{ fontWeight: 600 }}>{t.question}</div>
                  <div className="small muted clamp1">{t.found[0]}</div>
                </div>
                <button className="btn" onClick={() => complete(t)}>완료</button>
              </div>
            ))}
        </section>

        <section className="panel">
          <h2>담당자별 진행</h2>
          {d.owners.length === 0 ? <p className="muted">맡은 조치가 없어요.</p> : (
            <table className="table">
              <tbody>{d.owners.map((o) => (
                <tr key={o.owner}>
                  <td className="owner-cell"><a href={`/tasks?owner=${encodeURIComponent(o.owner)}`}>{o.owner}</a></td>
                  <td style={{ width: "34%", verticalAlign: "middle" }}>
                    <div className="meter" role="img" aria-label={`${o.total}개 중 ${o.done}개 완료`}><i style={{ width: `${(o.done / o.total) * 100}%` }} /></div>
                  </td>
                  <td className="small" style={{ textAlign: "right", whiteSpace: "nowrap" }}>{o.done}/{o.total} 완료</td>
                </tr>))}
              </tbody>
            </table>)}
          <p className="small muted" style={{ marginTop: 10 }}>완료 표시는 담당자의 신고예요. 실제로 고쳐졌는지는 다음 진단에서 확인돼요.</p>
        </section>
      </div>

      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
          <h2 style={{ margin: 0 }}>이 대상의 진단 기록</h2><a className="small" href="/runs">전체 기록</a>
        </div>
        <table className="table">
          <thead><tr><th>진단 시각</th><th>고칠 것</th><th>규칙대로</th><th>결과 지문</th></tr></thead>
          <tbody>{d.recent.map((r) => (
            <tr key={r.run_id}>
              <td><a href={`/runs/${r.run_id}`}>{fmtTime(r.generated_at)}</a>{r.run_id === rid && <span className="small muted"> (지금 보는 결과)</span>}</td>
              <td>{r.counts.CANDIDATE_NONCONFORMITY ?? 0}</td>
              <td>{r.counts.CANDIDATE_CONFORMING ?? 0}</td>
              <td className="small muted"><code>{r.result_hash.slice(0, 10)}</code></td>
            </tr>))}
          </tbody>
        </table>
      </section>

      <p className="small muted"><a href="/system">시스템 상태</a>: {health === null ? "확인하지 못했어요" : health === 5 ? "모두 정상" : `5개 중 ${health}개 정상`}</p>
    </div>
  );
}
