"""쉬운 설명 — 일반 직원이 읽는 문장을 만든다.

원칙
- LLM 없이 템플릿으로 만든다. 같은 결과면 항상 같은 문장 (결과 해시에 포함).
- 해요체, 전문용어·조항번호 없이. 계정은 ID 대신 '운영 계정(a-prod)'처럼 부른다.
- 검토 승인 전에는 '확인 중'을 붙인다. '인증 결함 확정' 같은 표현은 쓰지 않는다.
"""
from __future__ import annotations

from typing import Any

PLAIN_VERSION = "0.2.0"

STATUS_PENDING = {
    "CANDIDATE_NONCONFORMITY": ("고칠 부분이 있어 보여요", "담당자가 확인하고 있어요", "🔴"),
    "CANDIDATE_CONFORMING": ("규칙대로 되어 있어 보여요", "담당자가 확인하고 있어요", "🟢"),
    "CANDIDATE_PARTIAL": ("아직 판단하지 못했어요", "일부 자료만 확인됐어요", "⚪"),
    "INSUFFICIENT_EVIDENCE": ("아직 판단하지 못했어요", "판단에 필요한 자료가 부족해요", "⚪"),
    "NOT_APPLICABLE_PENDING": ("우리 회사에 해당하는지 확인 중이에요", "", "⚪"),
}
STATUS_APPROVED = {
    "APPROVED_NONCONFORMITY": ("고쳐야 해요", "담당자가 확인했어요", "🔴"),
    "APPROVED_CONFORMING": ("규칙대로 되어 있어요", "담당자가 확인했어요", "🟢"),
    "APPROVED_INSUFFICIENT": ("아직 판단하지 못했어요", "자료를 더 받아야 해요", "⚪"),
    "APPROVED_NOT_APPLICABLE": ("우리 회사에는 해당하지 않아요", "담당자가 확인했어요", "⚪"),
    "REJECTED": ("다시 확인하고 있어요", "담당자가 결과를 다시 보기로 했어요", "⚪"),
    "EVIDENCE_REQUESTED": ("자료를 더 받고 있어요", "담당자가 추가 자료를 요청했어요", "⚪"),
}

FIELD = {
    "MinimumPasswordLength": ("비밀번호 최소 길이", "len"),
    "MinimumLength": ("비밀번호 최소 길이", "len"),
    "RequireUppercaseCharacters": ("영문 대문자 포함", "bool"),
    "RequireLowercaseCharacters": ("영문 소문자 포함", "bool"),
    "RequireNumbers": ("숫자 포함", "bool"),
    "RequireSymbols": ("특수문자 포함", "bool"),
    "MaxPasswordAge": ("비밀번호 변경 주기", "days"),
    "PasswordReusePrevention": ("예전 비밀번호 재사용 금지", "count"),
}

REASON = {
    "SCOPE_INCOMPLETE": "우리 회사에 해당하는지 판단할 정보가 아직 없어요.",
    "SCOPE_NOT_APPLICABLE": "우리 회사에는 해당하지 않을 수 있어요. 담당자가 확인해야 해요.",
    "PARTIAL_COLLECTION": "일부 시스템 자료를 가져오지 못했어요.",
    "DENOMINATOR_UNKNOWN": "어떤 규정 문서를 봐야 하는지 목록이 없어요.",
    "CONFLICTING_EVIDENCE": "자료끼리 내용이 서로 달라요.",
    "REQUIRED_EVIDENCE_GAP": "판단에 필요한 자료가 아직 없어요.",
}


def _has_batchim(word: str) -> bool:
    ch = word.rstrip("'\" )")[-1:] if word else ""
    if not ch:
        return False
    if "가" <= ch <= "힣":
        return (ord(ch) - 0xAC00) % 28 != 0
    return ch in "136780lmnLMN"  # 숫자·영문은 읽는 소리 기준 (일·삼·육·칠·팔·영, -l/-m/-n)


def josa(word: str, pair: str) -> str:
    """josa('길이', '이/가') → '길이가'"""
    a, b = pair.split("/")
    return word + (a if _has_batchim(word) else b)


def euro(word: str) -> str:
    """'8자' → '8자로', '만료 없음' → '만료 없음으로', '90일' → '90일로' (ㄹ 받침은 '로')"""
    ch = word[-1:] if word else ""
    if "가" <= ch <= "힣":
        jong = (ord(ch) - 0xAC00) % 28
        return word + ("으로" if jong not in (0, 8) else "로")
    return word + ("으로" if _has_batchim(word) and ch not in "1780lL" else "로")


def copula(word: str) -> str:
    """'10자' → '10자예요', '90일' → '90일이에요'"""
    return word + ("이에요" if _has_batchim(word) else "예요")


def _human(kind: str, v: Any) -> str:
    if v is None:
        return {"days": "만료 없음", "bool": "설정 안 됨"}.get(kind, "설정 안 됨")
    if kind == "len":
        return f"{v}자"
    if kind == "bool":
        return "필수" if v else "필수 아님"
    if kind == "days":
        return f"{v}일"
    if kind == "count":
        return f"최근 {v}개"
    return str(v)


def account_name(aid: str, accounts: dict[str, dict]) -> str:
    a = accounts.get(aid, {})
    label, alias = a.get("label"), a.get("alias")
    if label and alias:
        return f"{label} 계정({alias})"
    return f"{alias or aid} 계정"


def finding_sentence(v: dict, obs: dict, accounts: dict[str, dict]) -> str:
    """결함 1건을 쉬운 문장 1~2개로."""
    if v.get("plain"):
        aid = str(v.get("subject", "")).split("/")[0]
        return v["plain"].replace("{account}", account_name(aid, accounts))
    o = next((obs[i] for i in v.get("obs_ids", []) if i in obs and obs[i]["axis"] == "technical"), None)
    if v["op"] == "exists":
        return "회사 규정 어디에도 이 내용이 적혀 있지 않아요."
    if o is None:
        return "회사 규칙과 다른 설정이 발견됐어요."
    vals = o["values"]
    aid = vals.get("account_id", o["subject"].split("/")[0])
    who = account_name(aid, accounts)
    if o["kind"] == "aws_password_policy" and vals.get("policy_exists") is False:
        return f"{who}에는 비밀번호 규칙이 아예 설정되어 있지 않아요. 그래서 짧고 쉬운 비밀번호도 만들 수 있어요."
    if v["op"] == "forbids":
        return f"{who}의 {vals.get('user')}님은 처음 받은 임시 비밀번호를 바꾸지 않고 그대로 쓰고 있어요."
    if o["kind"] == "aws_user":  # 주기
        return (f"{who}의 {vals.get('user')}님은 비밀번호를 {v['observed']}째 바꾸지 않았어요. "
                f"회사 규칙은 {str(v['expected']).replace('≤ ', '')}마다 바꾸는 거예요.")
    field_ = v.get("field") or _field_from_message(v["message"])
    label, kind = FIELD.get(field_, (field_, ""))
    place = "쇼핑몰 회원 가입" if o["kind"] == "cognito_pool" else who
    obs_v, exp_v = _human(kind, v["observed"]), _human(kind, v["expected"])
    return f"{place}의 {josa(label, '이/가')} {euro(obs_v)} 되어 있어요. 회사 규칙은 {copula(exp_v)}."


def _field_from_message(msg: str) -> str:
    head = msg.split(": ", 1)[-1]
    return head.split(" ", 1)[0]


def doc_rules_sentence(params: list[str], doc_obs: dict[str, dict], doc_titles: dict[str, str]) -> str | None:
    """규칙대로인 항목: 문서에서 확인한 규칙을 한 문장으로."""
    got = {p: doc_obs[f"doc:{p}"] for p in params if f"doc:{p}" in doc_obs
           and doc_obs[f"doc:{p}"]["quality"] != "fail" and doc_obs[f"doc:{p}"]["values"].get("value") is not None}
    if not got:
        return None
    v = {p.split(".", 1)[1]: o["values"]["value"] for p, o in got.items()}
    bits = []
    if "min_length" in v:
        bits.append(f"최소 {v['min_length']}자")
    kinds = [n for k, n in (("require_uppercase", "대문자"), ("require_lowercase", "소문자"),
                            ("require_number", "숫자"), ("require_symbol", "특수문자")) if v.get(k)]
    if kinds:
        bits.append("·".join(kinds) + " 포함")
    elif "complexity_classes" in v:
        bits.append(f"{v['complexity_classes']}가지 문자 섞기")
    if "max_age_days" in v:
        bits.append(f"{v['max_age_days']}일마다 변경")
    if "reuse_prevention" in v:
        bits.append(f"최근 {v['reuse_prevention']}개 재사용 금지")
    if v.get("temp_force_change"):
        bits.append("임시 비밀번호는 첫 로그인 때 변경")
    docs = sorted({doc_titles.get(c["locator"].split(" ")[0], c["locator"].split(" ")[0])
                   for o in got.values() for c in o["citations"]})
    if not bits:
        return f"회사 규정({', '.join(docs)})에 이 내용이 적혀 있어요."
    return f"회사 규정({', '.join(docs)})에 {', '.join(bits)} 규칙이 적혀 있어요."


def build(result_body: dict, requirements: list, accounts: dict[str, dict]) -> dict:
    """결과 본문에서 쉬운 설명 묶음을 만든다. pipeline이 결과에 넣는다."""
    obs = {o["obs_id"]: o for o in result_body["observations"]}
    ev_by = {e["ar_id"]: e for e in result_body["evaluations"]}
    doc_titles = {m.get("문서번호"): m.get("제목") for m in result_body.get("documents", {}).values()}
    items = []
    for ar, d in zip(requirements, result_body["decisions"]):
        p = ar.plain
        head, sub, icon = STATUS_PENDING[d["verdict"]]
        found = [finding_sentence({**v, "field": v["message"].split(": ", 1)[-1].split(" ", 1)[0]}, obs, accounts)
                 for v in ev_by[d["ar_id"]]["violations"]]
        if d["verdict"] == "CANDIDATE_CONFORMING":
            params = [p for t in ar.tests if t.type == "DOCUMENT_EXTRACT" for p in t.params]
            good = doc_rules_sentence(params, obs, doc_titles)
            found = [good] if good else []
            if any(t.type == "CONFIG_COLLECT" for t in ar.tests):
                found.append("확인한 계정과 사용자 모두 회사 규칙과 같았어요.")
        note = REASON.get(d["reason_code"], "") if d["verdict"] not in (
            "CANDIDATE_NONCONFORMITY", "CANDIDATE_CONFORMING") else ""
        items.append({
            "ar_id": ar.id,
            "question": p.question if p else ar.title,
            "status": head, "status_sub": sub, "icon": icon,
            "found": found,
            "note": note,
            "why": p.why if p else "",
            "fix": (p.fix if p else []) if d["verdict"] == "CANDIDATE_NONCONFORMITY" else [],
            "owner": p.owner if p else "",
        })
    n_fix = sum(1 for d in result_body["decisions"] if d["verdict"] == "CANDIDATE_NONCONFORMITY")
    n_ok = sum(1 for d in result_body["decisions"] if d["verdict"] == "CANDIDATE_CONFORMING")
    n_unk = len(result_body["decisions"]) - n_fix - n_ok
    parts = []
    if n_fix:
        parts.append((f"{n_fix}가지는 고칠 부분이 있어 보이고", f"{n_fix}가지는 고칠 부분이 있어 보여요"))
    if n_ok:
        parts.append((f"{n_ok}가지는 규칙대로 되어 있어 보이고", f"{n_ok}가지는 규칙대로 되어 있어 보여요"))
    if n_unk:
        parts.append((f"{n_unk}가지는 아직 판단하지 못했고", f"{n_unk}가지는 아직 판단하지 못했어요"))
    tail = ", ".join([p[0] for p in parts[:-1]] + [parts[-1][1]]) if parts else ""
    headline = f"계정·비밀번호 관리에 대해 {len(items)}가지를 확인했어요. {tail}."
    return {"version": PLAIN_VERSION, "headline": headline,
            "notice": "이 결과는 자동으로 계산한 것이라 담당자가 확인하기 전까지는 '확인 중'이에요.",
            "items": items}


def status_after_review(state: str) -> tuple[str, str, str]:
    return STATUS_APPROVED.get(state, ("확인 중이에요", "", "⚪"))
