"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { targetLabel, usePref } from "../lib/prefs";
import { ToastProvider } from "./Toast";

const NAV = [
  { href: "/", label: "대시보드", d: "M3 12h7V3H3v9Zm0 9h7v-6H3v6Zm11 0h7v-9h-7v9Zm0-18v6h7V3h-7Z" },
  { href: "/checklist", label: "전체 점검표", d: "M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01" },
  { href: "/tasks", label: "할 일", d: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" },
  { href: "/upload", label: "자료 올리기", d: "M12 16V4m0 0-4 4m4-4 4 4M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" },
  { href: "/runs", label: "진단 기록", d: "M12 8v4l3 2M3 12a9 9 0 1 0 18 0 9 9 0 0 0-18 0" },
  { href: "/system", label: "시스템 상태", d: "M3 12h4l3-8 4 16 3-8h4" },
];

type Target = { target: string; label: string; kind: string };

function TargetSwitcher() {
  const [target, setTarget, ready] = usePref("target");
  const [list, setList] = useState<Target[]>([]);
  useEffect(() => {
    api<Target[]>("/targets").then((l) => {
      setList(l);
      if (ready && (!target || !l.some((t) => t.target === target)) && l.length) {
        setTarget((l.find((t) => t.kind === "workspace") ?? l[0]).target);
      }
    }).catch(() => setList([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
  return (
    <label className="switcher">
      <span className="switcher-label">진단 대상</span>
      <select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="진단 대상 선택">
        {list.length === 0 && <option value="">불러오는 중…</option>}
        {list.some((t) => t.kind === "workspace") && (
          <optgroup label="내 작업공간">{list.filter((t) => t.kind === "workspace").map((t) => <option key={t.target} value={t.target}>{targetLabel(t.target)}</option>)}</optgroup>)}
        <optgroup label="예제">{list.filter((t) => t.kind === "scenario").map((t) => <option key={t.target} value={t.target}>{targetLabel(t.target)}</option>)}</optgroup>
      </select>
    </label>
  );
}

function NameChip() {
  const [name, setName] = usePref("name");
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState("");
  if (edit) return (
    <form className="row" style={{ gap: 6 }} onSubmit={(e) => { e.preventDefault(); setName(draft.trim()); setEdit(false); }}>
      <input className="input" autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="이름" style={{ width: 120 }} aria-label="내 이름" />
      <button className="btn" type="submit">저장</button>
    </form>
  );
  return (
    <button className="chip" onClick={() => { setDraft(name); setEdit(true); }} title="검토와 할 일 완료 기록에 남는 이름">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" /></svg>
      {name ? name : "이름 설정"}
    </button>
  );
}

function ThemeButton() {
  const [theme, setTheme] = usePref("theme");
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
  }, [theme]);
  const next = theme === "" ? "dark" : theme === "dark" ? "light" : "";
  const label = theme === "dark" ? "어둡게" : theme === "light" ? "밝게" : "시스템";
  return <button className="chip" onClick={() => setTheme(next)} title="화면 테마 바꾸기">테마: {label}</button>;
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <ToastProvider>
      <a href="#main" className="skip">본문으로 건너뛰기</a>
      <div className="shell">
        <aside className="side">
          <div className="brand">ISMS-P 갭분석<span>규칙과 실제 설정을 맞춰 봅니다</span></div>
          <nav className="nav" aria-label="주요 메뉴">
            {NAV.map((n) => (
              <a key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={n.d} /></svg>
                {n.label}
              </a>
            ))}
          </nav>
        </aside>
        <div className="content">
          <header className="topbar">
            <TargetSwitcher />
            <div className="row" style={{ gap: 8 }}><NameChip /><ThemeButton /></div>
          </header>
          <main className="main" id="main">{children}</main>
        </div>
      </div>
    </ToastProvider>
  );
}
