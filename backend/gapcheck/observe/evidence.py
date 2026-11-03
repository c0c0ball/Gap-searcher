"""증적 관측: 제출된 표(xlsx)를 읽어 Observation으로 바꾼다.

파일 이름이 아니라 첫 줄(머리글)로 어떤 서류인지 알아낸다. 그래서 작업공간에 올린 파일도 같은 방식으로 읽힌다.

종류                머리글에 있어야 하는 칸                         관측 kind
account_list       계정ID, IAM 사용자, 사번, 용도                  account_entry  (계정 관리대장)
hr_roster          사번, 성명, 상태, 퇴직일                        hr_account     (인사 명부 × 계정 관리대장)
privileged_list    AWS 계정, IAM 사용자, 권한, 승인자               privileged_entry (특수권한자 목록)
access_review_log  검토일, 검토자, 결과                            access_review  (접근권한 검토 기록)
asset_list         자산ID, 자산명, 유형, 개인정보                    asset_entry    (정보자산 목록)
key_ledger         키 별칭, AWS 계정, 키 ID, 용도                    key_entry      (암호키 관리대장)
access_log_review  점검일, 점검자, 결과                            access_log_check (접속기록 점검 기록)
restore_test_log   시험일, 대상, 결과, 확인자                       restore_test   (백업 복구 테스트 기록)
dr_drill_log       훈련일, 시나리오, 결과                          dr_drill       (재해 복구 훈련 기록)

- 개인 이름은 마스킹된 채로 두고 판정에는 사번·IAM 사용자 이름만 쓴다.
- 인사 명부는 계정 관리대장과 사번으로 이어서 'IAM 사용자 ↔ 재직 상태'를 만든다.
  관리대장이 없으면 연결하지 못한 것으로 남긴다 (key = None).
"""
from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any

from ..model import Observation

SIGNATURES: dict[str, set[str]] = {
    "account_list": {"계정ID", "IAM 사용자", "사번", "용도"},
    "hr_roster": {"사번", "성명", "상태", "퇴직일"},
    "privileged_list": {"AWS 계정", "IAM 사용자", "권한", "승인자"},
    "access_review_log": {"검토일", "검토자", "결과"},
    "asset_list": {"자산ID", "자산명", "유형", "개인정보"},
    "key_ledger": {"키 별칭", "AWS 계정", "키 ID", "용도"},
    "access_log_review": {"점검일", "점검자", "결과"},
    "restore_test_log": {"시험일", "대상", "결과", "확인자"},
    "dr_drill_log": {"훈련일", "시나리오", "결과"},
}
KIND_OBS = {"account_list": "account_entry", "hr_roster": "hr_account",
            "privileged_list": "privileged_entry", "access_review_log": "access_review",
            "asset_list": "asset_entry", "key_ledger": "key_entry",
            "access_log_review": "access_log_check", "restore_test_log": "restore_test", "dr_drill_log": "dr_drill"}
# 날짜 한 칸이 핵심인 기록류: 종류 → (날짜 칸, 관측 필드)
DATED = {"access_log_review": ("점검일", "checked_on"), "restore_test_log": ("시험일", "tested_on"),
         "dr_drill_log": ("훈련일", "drilled_on")}


def _cell(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        v = v.strip()
        return None if v in ("", "-") else v
    return v


def read_tables(data: bytes) -> list[tuple[str, str, list[dict]]]:
    """(종류, 시트 이름, 행 목록). 종류를 알 수 없는 시트는 건너뛴다."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        head = [str(h).strip() if h is not None else "" for h in rows[0]]
        kind = next((k for k, sig in SIGNATURES.items() if sig <= set(head)), None)
        if kind is None:
            continue
        recs = []
        for r in rows[1:]:
            if not any(c is not None and str(c).strip() for c in r):
                continue
            recs.append({h: _cell(v) for h, v in zip(head, r) if h})
        out.append((kind, ws.title, recs))
    return out


def _alias_map(accounts: dict[str, dict]) -> dict[str, str]:
    m = {}
    for aid, a in accounts.items():
        m[aid] = aid
        if a.get("alias"):
            m[a["alias"]] = aid
    return m


def evidence_observations(files: list[tuple[str, bytes, str]], accounts: dict[str, dict]) -> tuple[list[Observation], list[dict]]:
    """files: [(경로, 내용, sha256)], accounts: account_id → scope 항목 (별칭 해석용)

    반환: (관측 목록, 읽은 표 목록[{file, kind, sheet, rows}])
    """
    alias = _alias_map(accounts)
    tables: list[tuple[str, str, str, str, list[dict]]] = []
    read: list[dict] = []
    for path, data, sha in files:
        if not path.lower().endswith(".xlsx"):
            continue
        try:
            for kind, sheet, recs in read_tables(data):
                tables.append((path, sha, kind, sheet, recs))
                read.append({"file": path, "kind": kind, "sheet": sheet, "rows": len(recs)})
        except Exception as e:  # 깨진 표는 관측 없이 기록만 (결함 근거가 아님)
            read.append({"file": path, "kind": None, "error": f"{type(e).__name__}: {e}"})

    def src(path: str, sha: str, sheet: str, row: int) -> dict:
        return {"source": "evidence", "file": path, "sha256": sha, "sheet": sheet, "row": row}

    obs: list[Observation] = []
    emp_keys: dict[str, list[str]] = {}
    have_account_list = False
    for path, sha, kind, sheet, recs in tables:
        if kind != "account_list":
            continue
        have_account_list = True
        for i, r in enumerate(recs, start=2):
            aid = alias.get(str(r.get("계정ID") or ""), str(r.get("계정ID") or ""))
            user = r.get("IAM 사용자")
            if not user:
                continue
            key = f"{aid}/{user}"
            emp = r.get("사번")
            if emp:
                emp_keys.setdefault(str(emp), []).append(key)
            shared = emp is None and str(r.get("콘솔 비밀번호") or "") == "사용"
            obs.append(Observation(
                obs_id=f"ev:account:{key}", axis="evidence", kind="account_entry", subject=key,
                values={"key": key, "account_id": aid, "user": user, "emp_no": emp, "purpose": r.get("용도"),
                        "console": r.get("콘솔 비밀번호") == "사용", "shared": shared,
                        # 표의 빈 칸은 '판단 불가'가 아니라 '적지 않음'이다 (승인자는 빈 문자열로 둔다)
                        "approver": r.get("승인자") or "", "expires": r.get("사용기한")},
                extractor="evidence", source=src(path, sha, sheet, i)))

    for path, sha, kind, sheet, recs in tables:
        for i, r in enumerate(recs, start=2):
            if kind == "hr_roster":
                emp = str(r.get("사번") or "")
                keys = emp_keys.get(emp) if have_account_list else None
                base = {"emp_no": emp, "status": r.get("상태"), "retired_on": r.get("퇴직일"),
                        "department": r.get("부서"), "role": r.get("직무")}
                for k in (keys or [None]):
                    obs.append(Observation(
                        obs_id=f"ev:hr:{emp}:{k or '-'}", axis="evidence", kind="hr_account",
                        subject=f"사번 {emp}" + (f" → {k}" if k else ""),
                        values={**base, "key": k, "linked": k is not None},
                        extractor="evidence", source=src(path, sha, sheet, i)))
            elif kind == "privileged_list":
                aid = alias.get(str(r.get("AWS 계정") or ""), str(r.get("AWS 계정") or ""))
                key = f"{aid}/{r.get('IAM 사용자')}"
                obs.append(Observation(
                    obs_id=f"ev:priv:{key}", axis="evidence", kind="privileged_entry", subject=key,
                    values={"key": key, "permission": r.get("권한"), "approver": r.get("승인자"),
                            "approved_on": r.get("승인일")},
                    extractor="evidence", source=src(path, sha, sheet, i)))
            elif kind == "asset_list":
                aid = alias.get(str(r.get("AWS 계정") or ""), str(r.get("AWS 계정") or ""))
                rid = r.get("리소스ID")
                key = f"{aid}/{rid}" if rid else None
                obs.append(Observation(
                    obs_id=f"ev:asset:{r.get('자산ID')}", axis="evidence", kind="asset_entry",
                    subject=f"{r.get('자산ID')} {r.get('자산명')}",
                    values={"key": key, "account_id": aid, "asset_id": r.get("자산ID"), "name": r.get("자산명"), "type": r.get("유형"),
                            "personal": str(r.get("개인정보") or "").upper() in ("Y", "O", "예", "포함"),
                            "importance": r.get("중요도"), "owner": r.get("관리자")},
                    extractor="evidence", source=src(path, sha, sheet, i)))
            elif kind == "key_ledger":
                aid = alias.get(str(r.get("AWS 계정") or ""), str(r.get("AWS 계정") or ""))
                key = f"{aid}/{r.get('키 ID')}"
                obs.append(Observation(
                    obs_id=f"ev:key:{key}", axis="evidence", kind="key_entry", subject=key,
                    values={"key": key, "alias": r.get("키 별칭"), "purpose": r.get("용도"),
                            "approver": r.get("생성 승인자") or "", "manager": r.get("담당자")},
                    extractor="evidence", source=src(path, sha, sheet, i)))
            elif kind in DATED:
                col, fld = DATED[kind]
                obs.append(Observation(
                    obs_id=f"ev:{kind}:{r.get(col)}:{i}", axis="evidence", kind=KIND_OBS[kind],
                    subject=f"{col} {r.get(col)}",
                    values={fld: r.get(col), **{k: v for k, v in r.items() if k != col}},
                    extractor="evidence", source=src(path, sha, sheet, i)))
            elif kind == "access_review_log":
                obs.append(Observation(
                    obs_id=f"ev:review:{r.get('검토일')}:{i}", axis="evidence", kind="access_review",
                    subject=f"접근권한 검토 {r.get('검토일')}",
                    values={"reviewed_on": r.get("검토일"), "reviewer": r.get("검토자"), "scope": r.get("범위"),
                            "result": r.get("결과"), "action": r.get("조치")},
                    extractor="evidence", source=src(path, sha, sheet, i)))
    return obs, read
