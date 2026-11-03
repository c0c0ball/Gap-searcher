"""규정 문서(docx)를 조·항·호 단위 Clause로 정규화한다.

인식 규칙
- 'Heading 2' 또는 '제N조(…)'로 시작하는 문단 → 조(article)
- '①'~'⑳'으로 시작 → 항
- '1.' 형식 → 호 (상위 항 문장을 parent_text로 보관)
- '부칙' 이후 문단은 article='부칙'
- 표는 문서 정보(문서번호·버전·시행일) 추출에만 쓰고 Clause로 만들지 않는다 (개정 이력 오탐 방지)
"""
from __future__ import annotations

import io
import re
import unicodedata

from docx import Document

from ..model import Clause

ARTICLE = re.compile(r"^제\s*(\d+)\s*조\s*(\(.*?\))?")
PARA = re.compile(r"^([①-⑳])\s*")
ITEM = re.compile(r"^(\d+)\.\s+")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def parse_docx(data: bytes, doc_id_hint: str, artifact_sha256: str) -> tuple[dict, list[Clause]]:
    doc = Document(io.BytesIO(data))
    meta: dict[str, str] = {}
    for table in doc.tables:
        for row in table.rows:
            cells = [norm(c.text) for c in row.cells]
            if len(cells) == 2 and cells[0] in {"문서번호", "버전", "시행일", "승인자", "소관부서", "보안등급"}:
                meta[cells[0]] = cells[1]
    # 개정 이력 표(버전·일자 칸이 있는 표)의 가장 늦은 날짜 → 마지막 제·개정(검토)일
    dates = []
    for table in doc.tables:
        rows = [[norm(c.text) for c in r.cells] for r in table.rows]
        if rows and "일자" in rows[0] and any("버전" in h for h in rows[0]):
            i = rows[0].index("일자")
            dates += [r[i] for r in rows[1:] if len(r) > i and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[i])]
    if dates:
        meta["최종개정일"] = max(dates)
    doc_id = meta.get("문서번호", doc_id_hint)
    title = next((norm(p.text) for p in doc.paragraphs if p.style.name == "Title"), "")
    meta["제목"] = title

    clauses: list[Clause] = []
    article, para_label, para_text = "", "", ""
    in_addenda = False
    order = 0
    for p in doc.paragraphs:
        text = norm(p.text)
        if not text or p.style.name == "Title":
            continue
        style = p.style.name
        if style == "Heading 1":
            in_addenda = text.startswith("부칙")
            if in_addenda:
                article, para_label, para_text = "부칙", "", ""
            continue
        m = ARTICLE.match(text)
        if (style == "Heading 2" or m) and not in_addenda and m:
            article = text
            para_label, para_text = "", ""
            continue
        if not article:
            continue  # 표지·서문
        pm, im = PARA.match(text), ITEM.match(text)
        if pm:
            para_label, para_text = pm.group(1), text
            label, parent = para_label, ""
        elif im:
            label = f"{para_label}-{im.group(1)}" if para_label else f"{im.group(1)}호"
            parent = para_text
        else:
            label, parent = "", ""
            para_text = text if not para_label else para_text
        order += 1
        art_key = re.sub(r"\(.*", "", article).replace(" ", "")
        cid = f"{doc_id}#{art_key}" + (f"-{label}" if label else f"-p{order}")
        clauses.append(Clause(
            clause_id=cid, doc_id=doc_id, artifact_sha256=artifact_sha256,
            article=article, label=label, text=text, parent_text=parent, order=order,
        ))
    return meta, clauses
