"use client";

import { useEffect, useState } from "react";

/** 이 브라우저에만 저장되는 설정 (진단 대상, 내 이름, 내 담당, 테마). 탭끼리도 맞춰진다. */
const EVT = "pref-change";

export function getPref(key: string): string {
  try { return localStorage.getItem(`gap.${key}`) ?? ""; } catch { return ""; }
}

export function setPref(key: string, value: string) {
  try { localStorage.setItem(`gap.${key}`, value); } catch { /* 저장 불가 환경은 무시 */ }
  window.dispatchEvent(new CustomEvent(EVT, { detail: { key, value } }));
}

export function usePref(key: string): [string, (v: string) => void, boolean] {
  const [v, setV] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setV(getPref(key));
    setReady(true);
    const on = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d?.key === key) setV(d.value);
    };
    const onStorage = (e: StorageEvent) => { if (e.key === `gap.${key}`) setV(e.newValue ?? ""); };
    window.addEventListener(EVT, on);
    window.addEventListener("storage", onStorage);
    return () => { window.removeEventListener(EVT, on); window.removeEventListener("storage", onStorage); };
  }, [key]);
  return [v, (nv: string) => setPref(key, nv), ready];
}

/** "A사 (가상 이커머스, 임직원 약 40명)" → 이름과 설명으로 나눈다 */
export function splitOrg(s: string | null | undefined): { name: string; note: string } {
  const m = (s ?? "").match(/^(.*?)\s*\((.*)\)\s*$/);
  return m ? { name: m[1], note: m[2] } : { name: s ?? "", note: "" };
}

export const targetLabel = (t: string) => (t.startsWith("ws:") ? t.slice(3) : `예제 · ${t}`);
