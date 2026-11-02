"use client";

import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "../components/Status";
import { useToast } from "../components/Toast";
import { api, fmtTime, post } from "../lib/api";
import { targetLabel, usePref } from "../lib/prefs";

type Task = { task_id: string; run_id: string; ar_id: string; owner: string; question: string; found: string[]; fix: string[];
  why: string; confirmed: boolean; done: boolean; done_by?: string; done_at?: string };
type Group = { owner: string; total: number; done: number; tasks: Task[] };

export default function Tasks() {
  const [target, , ready] = usePref("target");
  const [name] = usePref("name");
  const [mine, setMine] = usePref("myOwner");
  const toast = useToast();
  const [data, setData] = useState<{ run_id: string | null; owners: Group[] } | null>(null);
  const [owner, setOwner] = useState<string>("");
  const [hideDone, setHideDone] = useState(true);

  const load = useCallback(() => {
    if (!ready || !target) return;
    api<{ run_id: string | null; owners: Group[] }>(`/tasks?target=${encodeURIComponent(target)}`).then(setData)
      .catch((e) => toast(e.message, "error"));
  }, [ready, target, toast]);
  useEffect(load, [load]);
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("owner");
    if (q) setOwner(q); else if (mine) setOwner(mine);
  }, [mine]);

  const toggle = async (t: Task) => {
    if (!name) { toast("오른쪽 위에서 이름을 먼저 설정해 주세요. 완료 기록에 남아요.", "error"); return; }
    try {
      await post(`/runs/${t.run_id}/tasks/${encodeURIComponent(t.task_id)}`, { done: !t.done, by: name });
      toast(t.done ? "완료 표시를 취소했어요." : "완료로 표시했어요. 다음 진단에서 실제로 고쳐졌는지 확인돼요.");
      load();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  if (!data) return <p className="muted">불러오는 중…</p>;
  if (!data.run_id) return (
    <div className="panel stack" style={{ maxWidth: 560 }}>
      <h1>할 일이 없어요</h1>
      <p className="muted">{targetLabel(target)}은(는) 아직 진단하지 않았어요. 진단하면 고칠 부분이 담당자별 할 일로 정리돼요.</p>
      <a className="btn btn-primary" href="/">대시보드에서 진단하기</a>
    </div>
  );
  const groups = data.owners.filter((g) => !owner || g.owner === owner);
  const all = data.owners.reduce((a, g) => a + g.total, 0);
  const done = data.owners.reduce((a, g) => a + g.done, 0);

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>할 일</h1><p className="muted small">{targetLabel(target)}의 최근 진단에서 나온 조치예요. 전체 {all}개 중 {done}개 완료.</p></div>
        <a className="btn" href={`/runs/${data.run_id}`}>근거가 된 진단 결과</a>
      </div>

      <div className="toolbar">
        <div className="filters" role="group" aria-label="담당자로 거르기">
          <button className="chip" aria-pressed={owner === ""} onClick={() => setOwner("")}>모든 담당 <span className="n">{all - done}</span></button>
          {data.owners.map((g) => (
            <button key={g.owner} className="chip" aria-pressed={owner === g.owner} onClick={() => setOwner(g.owner)}>
              {g.owner}{mine === g.owner ? " (나)" : ""} <span className="n">{g.total - g.done}</span>
            </button>
          ))}
        </div>
        <div className="row" style={{ gap: 12 }}>
          {owner && owner !== mine && <button className="btn btn-ghost small" onClick={() => setMine(owner)}>&lsquo;{owner}&rsquo;을 내 담당으로 기억</button>}
          {owner && owner === mine && <button className="btn btn-ghost small" onClick={() => setMine("")}>내 담당 기억 해제</button>}
          <label className="small row" style={{ gap: 6 }}><input type="checkbox" checked={hideDone} onChange={(e) => setHideDone(e.target.checked)} />완료한 일 숨기기</label>
        </div>
      </div>

      {groups.map((g) => {
        const visible = g.tasks.filter((t) => !(hideDone && t.done));
        return (
          <section key={g.owner} className="panel">
            <div className="row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
              <h2 style={{ margin: 0 }}>{g.owner}</h2>
              <span className="small muted">{g.done}/{g.total} 완료</span>
            </div>
            {visible.length === 0 && <p className="muted small" style={{ padding: "10px 0" }}>남은 일이 없어요.</p>}
            {visible.map((t) => (
              <article key={t.task_id} className="task">
                <input type="checkbox" checked={t.done} onChange={() => toggle(t)} aria-label={`${t.question} 완료 표시`} />
                <div style={{ opacity: t.done ? 0.6 : 1, minWidth: 0 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <h3 style={{ textDecoration: t.done ? "line-through" : "none" }}>{t.question}</h3>
                    {t.confirmed ? <StatusBadge tone="fix">담당자 확인함</StatusBadge> : <StatusBadge tone="unknown">확인 전</StatusBadge>}
                  </div>
                  <ul className="small" style={{ margin: "6px 0", paddingLeft: 18 }}>{t.found.map((f, i) => <li key={i}>{f}</li>)}</ul>
                  <details>
                    <summary className="small" style={{ color: "var(--accent)", fontWeight: 600 }}>고치는 방법 {t.fix.length}단계</summary>
                    <ol className="small" style={{ margin: "6px 0 4px", paddingLeft: 20 }}>{t.fix.map((f, i) => <li key={i}>{f}</li>)}</ol>
                    <p className="small muted">왜 중요해요? {t.why}</p>
                  </details>
                  {t.done && <p className="small muted" style={{ marginTop: 4 }}>{t.done_by}님이 {t.done_at ? fmtTime(t.done_at) : ""}에 완료로 표시함</p>}
                </div>
              </article>
            ))}
          </section>
        );
      })}
    </div>
  );
}
