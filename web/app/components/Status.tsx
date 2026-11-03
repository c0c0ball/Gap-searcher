export type Tone = "fix" | "ok" | "unknown" | "na";

/** 상태는 색 + 모양 + 글자 세 가지로 구분한다 (색만으로 구분하지 않음) */
export function StatusIcon({ tone, size = 16 }: { tone: Tone; size?: number }) {
  const path = tone === "fix"
    ? <path d="M12 7v6m0 3.5v.5" strokeWidth="2.4" strokeLinecap="round" />
    : tone === "ok"
      ? <path d="M7.5 12.5l3 3 6-6.5" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      : tone === "na"
        ? <path d="M8 16L16 8" strokeWidth="2.2" strokeLinecap="round" />
        : <path d="M8 12h8" strokeWidth="2.4" strokeLinecap="round" />;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ flex: "none" }}>
      <circle cx="12" cy="12" r="11" fill="currentColor" />
      <g stroke="var(--icon-ink)">{path}</g>
    </svg>
  );
}

export function StatusBadge({ tone, children }: { tone: Tone; children: React.ReactNode }) {
  return <span className={`badge t-${tone}`}><StatusIcon tone={tone} size={15} />{children}</span>;
}

export const TONE_WORD: Record<Tone, string> = { fix: "고칠 것", ok: "규칙대로", unknown: "판단 못함", na: "해당 없음" };
