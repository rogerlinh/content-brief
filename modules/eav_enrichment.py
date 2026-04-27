# -*- coding: utf-8 -*-
"""
eav_enrichment.py

Expand the thin EAV layer with fact candidates extracted primarily from
competitor body passages that are already scraped in competitor_data.

This module is deliberately heuristic and source-bound:
- it does not invent new facts
- it only promotes phrases that already exist in scraped competitor pages
- downstream verifier still decides whether a row is strong enough to trust
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modules.semantic_purity import normalize_text, overlap_score


SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.\!\?;:])\s+")
VALUE_SIGNAL_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}|"
    r"\d+(?:[\.,]\d+)?\s*(?:%|vnd|vnđ|usd|đ|dong|trieu|ty|hop dong|gio|ngay|thang|nam))",
    flags=re.IGNORECASE,
)
PROMO_COPY_MARKERS = {
    "xem them",
    "xem chi tiet",
    "dang ky",
    "lien he",
    "tu van",
    "trai nghiem",
    "uu dai",
    "khuyen mai",
    "tai day",
    "kham pha",
}


def _clean_heading(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"^\d+[\.\)]\s*", "", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" -:")
    return raw


def _infer_attribute_family(text: str) -> str:
    norm = normalize_text(text)
    if any(sig in norm for sig in ["dinh nghia", "khai niem", "la gi", "duoc hieu"]):
        return "definition"
    if any(sig in norm for sig in ["phan loai", "cac loai", "nhom", "gom", "bao gom"]):
        return "classification"
    if any(sig in norm for sig in ["so sanh", "khac", "khac gi", "bang danh gia", "tieu chi"]):
        return "comparison"
    if any(sig in norm for sig in ["rui ro", "luu y", "sai lam", "canh bao", "dieu kien an"]):
        return "risk"
    if any(sig in norm for sig in ["cach", "quy trinh", "co che", "hoat dong", "phan tich ky thuat", "thuc hien"]):
        return "process"
    if any(sig in norm for sig in ["chi phi", "phi", "ky quy", "thue", "gia", "muc", "ty le", "cong thuc"]):
        return "cost"
    if any(sig in norm for sig in ["loi ich", "loi nhuan", "tac dong", "anh huong", "ket qua"]):
        return "impact"
    return "attribute"


def _attribute_from_heading(topic: str, heading: str) -> str:
    clean = _clean_heading(heading)
    norm = normalize_text(clean)
    if not clean:
        return ""
    if any(sig in norm for sig in ["dinh nghia", "khai niem", "la gi", "duoc hieu"]):
        return "Định nghĩa"
    if any(sig in norm for sig in ["phan loai", "cac loai", "nhom", "gom", "bao gom"]):
        return "Phân loại"
    if any(sig in norm for sig in ["so sanh", "bang danh gia", "tieu chi", "khac", "khac gi"]):
        return "Tiêu chí so sánh"
    if any(sig in norm for sig in ["rui ro", "luu y", "sai lam", "canh bao"]):
        return "Rủi ro và lưu ý"
    if any(sig in norm for sig in ["chi phi", "phi", "ky quy", "thue", "gia", "muc phi"]):
        return clean
    if any(sig in norm for sig in ["cach", "quy trinh", "co che", "hoat dong", "phan tich", "thuc hien"]):
        return clean
    if overlap_score(clean, topic) >= 0.18:
        return clean
    return ""


def _value_from_heading(heading: str, family: str) -> str:
    clean = _clean_heading(heading)
    if ":" in clean:
        _, right = clean.split(":", 1)
        right = right.strip(" -")
        if right and len(right.split()) >= 2:
            return _canonicalize_fact_value(right, family)
    if family == "classification":
        match = re.search(r"(?:gom|bao gom|nhu)\s+(.+)$", clean, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" -")
            if value and len(value.split()) >= 2:
                return _canonicalize_fact_value(value, family)
    return ""


def _looks_like_promo_copy(text: str) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    return any(marker in norm for marker in PROMO_COPY_MARKERS)


def _canonicalize_fact_value(text: str, family: str = "") -> str:
    raw = re.sub(r"\s+", " ", str(text or "")).strip(" -")
    raw = raw.replace(">>>>", " ").replace(">>>", " ").replace(">>", " ")
    raw = re.sub(r"^[\-\*\u2022\d\.\)]\s*", "", raw).strip()
    if not raw:
        return ""
    if ":" in raw:
        left, right = raw.split(":", 1)
        left_norm = normalize_text(left)
        right = right.strip(" -")
        if len(left_norm.split()) <= 6 and right:
            if len(normalize_text(right).split()) >= 4 or VALUE_SIGNAL_RE.search(right):
                raw = right
    raw = raw.strip(" \"'""")
    if _looks_like_promo_copy(raw):
        return ""
    if raw.endswith(":"):
        return ""
    norm = normalize_text(raw)
    words = norm.split()
    if (
        not VALUE_SIGNAL_RE.search(raw)
        and len(words) <= 6
        and not any(token in norm for token in [" la ", " gom ", " bao gom ", " khong ", " duoc ", " ap dung ", " hieu luc ", " anh huong ", " tac dong "])
        and not any(sep in raw for sep in [",", ";"])
    ):
        return ""
    if len(norm.split()) < 4 and not VALUE_SIGNAL_RE.search(raw):
        return ""
    return raw


def _candidate_passages(body_text: str, max_count: int = 120) -> List[str]:
    body = str(body_text or "").strip()
    if not body:
        return []
    raw_parts = SENTENCE_SPLIT_RE.split(body)
    clean: List[str] = []
    seen = set()
    for part in raw_parts:
        text = re.sub(r"\s+", " ", str(part or "")).strip(" -")
        if not text:
            continue
        text = _canonicalize_fact_value(text)
        if not text:
            continue
        wc = len(text.split())
        if wc < 8 or wc > 60:
            continue
        norm = normalize_text(text)
        if norm in seen or len(norm) < 20:
            continue
        seen.add(norm)
        clean.append(text)
        if len(clean) >= max_count:
            break
    return clean


def _candidate_passages_from_competitor(comp: Dict[str, Any], max_count: int = 120) -> List[str]:
    blocks: List[str] = []
    seen = set()
    for block in (comp.get("content_blocks", []) or []):
        text = re.sub(r"\s+", " ", str(block or "")).strip(" -")
        if not text:
            continue
        text = _canonicalize_fact_value(text)
        if not text:
            continue
        wc = len(text.split())
        if wc < 6 or wc > 80:
            continue
        norm = normalize_text(text)
        if norm in seen:
            continue
        seen.add(norm)
        blocks.append(text)
        if len(blocks) >= max_count:
            break
    for text in _candidate_passages(comp.get("body_text", ""), max_count=max_count):
        norm = normalize_text(text)
        if norm in seen:
            continue
        seen.add(norm)
        blocks.append(text)
        if len(blocks) >= max_count:
            break
    return blocks


def _score_passage(topic: str, heading: str, passage: str, family: str) -> float:
    topic_score = overlap_score(topic, passage)
    heading_score = overlap_score(heading, passage)
    score = topic_score * 0.45 + heading_score * 0.55
    heading_terms = [token for token in normalize_text(heading).split() if len(token) >= 4]
    passage_norm = normalize_text(passage)
    shared_terms = sum(1 for token in heading_terms if token in passage_norm)
    score += min(0.24, shared_terms * 0.06)
    norm = normalize_text(passage)
    if family in {"cost", "impact", "comparison"} and re.search(r"\d|%|vnd|usd|gio|nam", norm):
        score += 0.12
    if VALUE_SIGNAL_RE.search(passage):
        score += 0.08
    if family == "cost" and any(sig in norm for sig in ["chi phi", "phi giao dich", "ky quy", "thue", "phi moi gioi"]):
        score += 0.12
    if family == "risk" and any(sig in norm for sig in ["rui ro", "canh bao", "luu y", "dung lo"]):
        score += 0.12
    if family == "definition" and any(sig in norm for sig in ["la", "duoc hieu", "la viec", "duoc xem la"]):
        score += 0.08
    if family == "classification" and any(sep in passage for sep in [",", ";"]):
        score += 0.06
    return score


def _best_passage(topic: str, heading: str, passages: List[str], family: str) -> str:
    family_markers = {
        "cost": ["chi phi", "phi giao dich", "ky quy", "thue", "phi moi gioi", "%", "vnd", "usd"],
        "risk": ["rui ro", "dung lo", "canh bao", "luu y"],
        "classification": ["gom", "bao gom", ",", ";", "nhom"],
        "definition": ["la", "la viec", "duoc hieu", "duoc xem la"],
        "comparison": ["so sanh", "khac", "khac biet", "tieu chi"],
        "process": ["cach", "quy trinh", "buoc", "thuc hien", "hoat dong"],
        "impact": ["anh huong", "tac dong", "ket qua", "loi nhuan"],
    }
    preferred = []
    markers = family_markers.get(family, [])
    if markers:
        for passage in passages:
            norm = normalize_text(passage)
            if any(marker in norm for marker in markers):
                preferred.append(passage)
    search_pool = preferred or passages

    best_text = ""
    best_score = 0.0
    for passage in search_pool:
        canonical = _canonicalize_fact_value(passage, family)
        if not canonical:
            continue
        score = _score_passage(topic, heading, canonical, family)
        if score > best_score:
            best_score = score
            best_text = canonical
    if best_score < 0.18:
        return ""
    return best_text


def _dedupe_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        key = (
            normalize_text(row.get("attribute", "")),
            normalize_text(row.get("value", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        clean.append(row)
        if len(clean) >= limit:
            break
    return clean


def extract_competitor_fact_rows(
    topic: str,
    competitor_data: Optional[Dict[str, Any]],
    limit: int = 18,
) -> List[Dict[str, Any]]:
    competitors = []
    if isinstance(competitor_data, dict):
        competitors = competitor_data.get("competitors", []) or []

    rows: List[Dict[str, Any]] = []
    for comp in competitors[:5]:
        if not isinstance(comp, dict):
            continue
        url = str(comp.get("url", "")).strip()
        headings = [
            _clean_heading(h.get("text", ""))
            for h in (comp.get("headings", []) or [])
            if isinstance(h, dict) and str(h.get("level", "")).upper() in {"H2", "H3"}
        ]
        headings = [h for h in headings if h]
        passages = _candidate_passages_from_competitor(comp)

        for heading in headings[:18]:
            attribute = _attribute_from_heading(topic, heading)
            if not attribute:
                continue
            family = _infer_attribute_family(attribute + " " + heading)
            best = _best_passage(topic, heading, passages, family)
            if best:
                rows.append(
                    {
                        "entity": topic,
                        "attribute": attribute,
                        "value": best,
                        "source": url,
                        "source_type": "competitor_body",
                    }
                )
                continue
            heading_value = _value_from_heading(heading, family)
            if heading_value and overlap_score(topic, heading_value) >= 0.08 and len(heading_value.split()) >= 5:
                rows.append(
                    {
                        "entity": topic,
                        "attribute": attribute,
                        "value": heading_value,
                        "source": url,
                        "source_type": "competitor_heading_fallback",
                    }
                )

    return _dedupe_rows(rows, limit=limit)


def render_eav_markdown(rows: List[Dict[str, Any]], fallback_table: str = "", limit: int = 12) -> str:
    verified = [row for row in rows if isinstance(row, dict) and row.get("is_verified")]
    source_rows = verified or [row for row in rows if isinstance(row, dict)]
    if not source_rows:
        return fallback_table

    order = {
        "definition": 0,
        "classification": 1,
        "process": 2,
        "cost": 3,
        "comparison": 4,
        "risk": 5,
        "impact": 6,
        "condition": 7,
        "application": 8,
        "attribute": 9,
    }
    source_rows = sorted(
        source_rows,
        key=lambda row: (
            order.get(normalize_text(row.get("attribute_family", "")), 99),
            -float(row.get("confidence", 0.0) or 0.0),
        ),
    )[:limit]

    lines = [
        "| Entity | Attribute | Value |",
        "|---|---|---|",
    ]
    for row in source_rows:
        entity = str(row.get("entity", "")).strip().replace("|", "/")
        attribute = str(row.get("attribute", "")).strip().replace("|", "/")
        value = str(row.get("value", "")).strip().replace("|", "/")
        if len(value) > 180:
            value = value[:177].rstrip() + "..."
        if entity and attribute and value:
            lines.append(f"| {entity} | {attribute} | {value} |")
    if len(lines) <= 2:
        return fallback_table
    return "\n".join(lines)
