"use client";

import { StatusBadge, Tone } from "./Status";

type Item = { ar_id: string; question: string; status: string; status_sub: string; icon: string;
  found: string[]; note: string; why: string; fix: string[]; owner: string };
export type Plain = { headline: string; notice: string; items: Item[] };
export type PlainStatus = { status: string; status_sub: string; icon: string };

const TONE: Record<string, string> = { "🔴": "fix", "🟢": "ok" };

export const toneOf = (icon: string): Tone => (TONE[icon] as Tone) ?? "unknown";

export default function EasyView({ plain, reviewed, filter }: { plain: Plain; reviewed: Record<string, PlainStatus>; filter: string }) {
  return (
    <div className="stack" style={{ fontSize: 16 }}>
      <p className="notice">{plain.notice}</p>
      {plain.items.map((it) => {
        const s = reviewed[it.ar_id] ?? { status: it.status, status_sub: it.status_sub, icon: it.icon };
        const tone = toneOf(s.icon);
        if (filter && filter !== tone) return null;
        return (
          <section key={it.ar_id} id={it.ar_id} className="panel"
            style={{ background: `var(--${tone === "unknown" ? "unk" : tone}-bg)`, borderColor: "transparent", boxShadow: "none", scrollMarginTop: 16 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
              <h2 style={{ fontSize: 18, margin: 0, maxWidth: "70ch" }}>{it.question}</h2>
              <StatusBadge tone={tone}>{s.status}</StatusBadge>
            </div>
            {s.status_sub && <p className="small muted" style={{ marginTop: 2 }}>{s.status_sub}</p>}
            {(it.found.length > 0 || it.note) && (
              <ul style={{ margin: "12px 0 0", paddingLeft: 20, maxWidth: "75ch" }}>
                {it.found.map((f, i) => <li key={i}>{f}</li>)}
                {it.note && <li>{it.note}</li>}
              </ul>
            )}
            {it.fix.length > 0 && (
              <div className="grid-2" style={{ marginTop: 16, gap: 14, gridTemplateColumns: "1.2fr 1fr" }}>
                <div style={{ background: "var(--surface)", borderRadius: 8, padding: "12px 16px" }}>
                  <h3>어떻게 고치나요?</h3>
                  <ol style={{ margin: "6px 0 0", paddingLeft: 20, fontSize: 15 }}>{it.fix.map((f, i) => <li key={i}>{f}</li>)}</ol>
                  <p className="small" style={{ marginTop: 8 }}>맡은 사람: <b>{it.owner}</b></p>
                </div>
                <div style={{ padding: "12px 4px" }}>
                  <h3>왜 중요해요?</h3>
                  <p style={{ fontSize: 15, marginTop: 6 }}>{it.why}</p>
                </div>
              </div>
            )}
          </section>
        );
      })}
      <details className="small muted">
        <summary>이 화면에 쓰인 말 풀이</summary>
        <ul>
          <li><b>고칠 부분이 있어 보여요</b>: 자동 점검에서 회사 규칙과 다른 점이 나왔어요. 담당자가 확인하면 &lsquo;고쳐야 해요&rsquo;로 바뀌어요.</li>
          <li><b>규칙대로 되어 있어 보여요</b>: 자동 점검에서 문제가 나오지 않았어요. 담당자가 확인하면 &lsquo;규칙대로 되어 있어요&rsquo;로 바뀌어요.</li>
          <li><b>아직 판단하지 못했어요</b>: 자료가 부족하거나 일부 시스템을 확인하지 못했어요. 문제가 없다는 뜻이 아니에요.</li>
          <li>이 점검은 회사가 정한 규칙과 실제 설정을 비교한 것이고, 인증 심사 결과를 대신하지 않아요.</li>
        </ul>
      </details>
    </div>
  );
}
