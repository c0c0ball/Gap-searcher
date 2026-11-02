export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, init);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body as { detail?: string }).detail ?? `요청 실패 (${r.status})`);
  return body as T;
}

export const post = <T,>(path: string, data: unknown) =>
  api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

/** 이 브라우저에서만 쓰는 편의 저장 (이름 등). 실패해도 동작에 지장 없음 */
/** @deprecated prefs.ts 의 usePref 사용 */
export const local = {
  get(k: string) { try { return localStorage.getItem(k) ?? ""; } catch { return ""; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* 무시 */ } },
};

export const fmtTime = (iso: string) => {
  try { return new Date(iso).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; }
};

export const TONE_OF_VERDICT: Record<string, "fix" | "ok" | "unknown"> = {
  CANDIDATE_NONCONFORMITY: "fix", CANDIDATE_CONFORMING: "ok",
};
export const VERDICT_LABEL: Record<string, string> = {
  CANDIDATE_NONCONFORMITY: "결함 후보", CANDIDATE_CONFORMING: "적합 후보", CANDIDATE_PARTIAL: "부분 (미확인)",
  INSUFFICIENT_EVIDENCE: "미확인", NOT_APPLICABLE_PENDING: "적용제외 검토",
};
export const PARAM_LABEL: Record<string, string> = {
  "password.min_length": "직원 비밀번호 최소 길이", "password.require_uppercase": "대문자 포함",
  "password.require_lowercase": "소문자 포함", "password.require_number": "숫자 포함",
  "password.require_symbol": "특수문자 포함", "password.complexity_classes": "섞어 쓸 문자 종류 수",
  "password.max_age_days": "변경 주기(일)", "password.reuse_prevention": "재사용 금지 개수",
  "password.temp_force_change": "임시 비밀번호 첫 로그인 때 변경",
  "customer_password.min_length": "회원 비밀번호 최소 길이", "customer_password.complexity_classes": "회원 비밀번호 문자 종류 수",
};
