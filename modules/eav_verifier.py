# -*- coding: utf-8 -*-
"""
eav_verifier.py

Build a safer EAV fact layer for downstream semantic reasoning.
The goal is not to prove every fact with perfect certainty, but to:
- block obviously weak numeric rows from becoming snippet/sapo facts
- preserve clean definition/classification rows when they are topic-aligned
- expose provenance, confidence, and coverage so downstream code can decide
  whether EAV is strong enough to anchor a section
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modules.semantic_purity import (
    normalize_text,
    overlap_score,
    sanitize_fact_row,
)


NUMERIC_RE = re.compile(r"\d")


def _dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    clean: List[Dict[str, Any]] = []
    for row in rows:
        key = (
            normalize_text(row.get("entity", "")),
            normalize_text(row.get("attribute", "")),
            normalize_text(row.get("value", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        clean.append(row)
    return clean


def parse_markdown_eav_rows(eav_table: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not eav_table:
        return rows
    for line in str(eav_table).splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 3:
            continue
        if normalize_text(parts[0]) == "entity" and normalize_text(parts[1]) == "attribute":
            continue
        rows.append(
            {
                "entity": parts[0],
                "attribute": parts[1],
                "value": parts[2],
                "source": "eav_table",
                "source_type": "eav_table",
            }
        )
    return rows


def _entity_attribute_rows(topic: str, entity_attributes: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    if not isinstance(entity_attributes, dict):
        return rows
    for key, value in entity_attributes.items():
        attr = str(key or "").strip()
        val = str(value or "").strip()
        if not attr or not val:
            continue
        rows.append(
            {
                "entity": topic,
                "attribute": attr,
                "value": val,
                "source": "entity_attributes",
                "source_type": "entity_attribute",
            }
        )
    return rows


def _attribute_family(attribute: str) -> str:
    attr = normalize_text(attribute)
    if any(sig in attr for sig in ["dinh nghia", "khai niem", "la gi"]):
        return "definition"
    if any(sig in attr for sig in ["phan loai", "nhom", "loai hinh", "cau phan"]):
        return "classification"
    if any(sig in attr for sig in ["co che", "hoat dong", "quy trinh", "cach", "phuong phap", "buoc"]):
        return "process"
    if any(sig in attr for sig in ["chi phi", "phi", "gia", "muc", "ty le", "don vi", "cong thuc"]):
        return "cost"
    if any(sig in attr for sig in ["so sanh", "khac biet", "tieu chi", "danh gia"]):
        return "comparison"
    if any(sig in attr for sig in ["rui ro", "luu y", "canh bao", "sai lam", "dieu kien"]):
        return "risk"
    if any(sig in attr for sig in ["loi nhuan", "anh huong", "tac dong", "ket qua", "phu hop"]):
        return "impact"
    if any(sig in attr for sig in ["thoi gian", "ky quy", "gioi han", "yeu cau", "dieu kien toi thieu"]):
        return "condition"
    if any(sig in attr for sig in ["ung dung", "vi du", "truong hop", "doi tuong"]):
        return "application"
    return "attribute"


def _is_numeric_like(value: str) -> bool:
    norm = normalize_text(value)
    if not norm:
        return False
    if NUMERIC_RE.search(norm):
        return True
    return False


def _context_blob(
    source_context: str = "",
    project_scope: str = "",
    common_headings: Optional[List[str]] = None,
    paa_questions: Optional[List[str]] = None,
) -> str:
    chunks = [source_context or "", project_scope or ""]
    chunks.extend(common_headings or [])
    chunks.extend(paa_questions or [])
    return normalize_text(" ".join(str(x or "") for x in chunks if str(x or "").strip()))


def _support_signals(
    topic: str,
    attribute: str,
    value: str,
    context_blob: str,
    common_headings: Optional[List[str]] = None,
    paa_questions: Optional[List[str]] = None,
) -> Dict[str, float]:
    attr_value = f"{attribute} {value}".strip()
    topic_score = max(overlap_score(attr_value, topic), overlap_score(attribute, topic))
    heading_score = max([overlap_score(attr_value, item) for item in (common_headings or [])] or [0.0])
    paa_score = max([overlap_score(attr_value, item) for item in (paa_questions or [])] or [0.0])
    attr_norm = normalize_text(attribute)
    value_norm = normalize_text(value)
    attr_hit = 1.0 if attr_norm and attr_norm in context_blob else 0.0
    value_hit = 1.0 if value_norm and len(value_norm) >= 6 and value_norm in context_blob else 0.0
    return {
        "topic_score": topic_score,
        "heading_score": heading_score,
        "paa_score": paa_score,
        "attr_hit": attr_hit,
        "value_hit": value_hit,
    }


def build_verified_eav_rows(
    topic: str,
    eav_table: str = "",
    entity_attributes: Optional[Dict[str, Any]] = None,
    extra_rows: Optional[List[Dict[str, Any]]] = None,
    source_context: str = "",
    common_headings: Optional[List[str]] = None,
    paa_questions: Optional[List[str]] = None,
    project_scope: str = "",
) -> List[Dict[str, Any]]:
    raw_rows = parse_markdown_eav_rows(eav_table) + _entity_attribute_rows(topic, entity_attributes)
    raw_rows.extend([row for row in (extra_rows or []) if isinstance(row, dict)])
    raw_rows = _dedupe_rows(raw_rows)
    context_blob = _context_blob(
        source_context=source_context,
        project_scope=project_scope,
        common_headings=common_headings,
        paa_questions=paa_questions,
    )

    verified_rows: List[Dict[str, Any]] = []
    for row in raw_rows:
        row = sanitize_fact_row(row) or {}
        attribute = str(row.get("attribute", "")).strip()
        value = str(row.get("value", "")).strip()
        if not attribute or not value:
            continue
        family = _attribute_family(attribute)
        numeric = _is_numeric_like(value)
        signals = _support_signals(
            topic=topic,
            attribute=attribute,
            value=value,
            context_blob=context_blob,
            common_headings=common_headings,
            paa_questions=paa_questions,
        )
        topic_score = signals["topic_score"]
        support_score = (
            topic_score * 0.4
            + signals["heading_score"] * 0.15
            + signals["paa_score"] * 0.15
            + signals["attr_hit"] * 0.15
            + signals["value_hit"] * 0.15
        )

        is_verified = False
        needs_verification = False
        confidence = 0.0
        source_type = str(row.get("source_type", "")).strip() or "unknown"
        has_scraped_source = source_type in {"competitor_body", "competitor_heading", "competitor_heading_fallback", "serp_snippet"}

        if numeric:
            if has_scraped_source and topic_score >= 0.12 and (
                signals["heading_score"] >= 0.08 or family in {"cost", "comparison", "condition", "impact", "risk", "process"}
            ):
                is_verified = True
                confidence = min(0.92, 0.52 + support_score)
            elif signals["value_hit"] > 0 or (signals["attr_hit"] > 0 and signals["heading_score"] >= 0.2):
                is_verified = True
                confidence = min(0.95, 0.45 + support_score)
            else:
                needs_verification = True
                confidence = min(0.49, 0.15 + support_score)
        else:
            if family in {"definition", "classification"} and max(topic_score, signals["heading_score"], signals["paa_score"]) >= 0.12:
                is_verified = True
                confidence = min(0.9, 0.45 + support_score)
            elif has_scraped_source and family == "classification" and (
                any(sig in normalize_text(value) for sig in ["gom", "bao gom"]) or any(sep in value for sep in [",", ";"])
            ):
                is_verified = True
                confidence = min(0.82, 0.38 + support_score)
            elif has_scraped_source and family == "risk" and any(sig in normalize_text(value) for sig in ["rui ro", "canh bao", "dung lo", "luu y"]):
                is_verified = True
                confidence = min(0.82, 0.38 + support_score)
            elif has_scraped_source and family in {"classification", "risk", "process", "comparison", "cost", "application"} and signals["heading_score"] >= 0.18:
                is_verified = True
                confidence = min(0.84, 0.4 + support_score)
            elif has_scraped_source and topic_score >= 0.12 and (signals["heading_score"] >= 0.08 or len(value.split()) >= 8):
                is_verified = True
                confidence = min(0.86, 0.42 + support_score)
            elif support_score >= 0.32:
                is_verified = True
                confidence = min(0.85, 0.4 + support_score)
            else:
                confidence = min(0.49, 0.18 + support_score)

        verified_rows.append(
            {
                "entity": str(row.get("entity", "")).strip() or topic,
                "attribute": attribute,
                "value": value,
                "normalized_value": normalize_text(value),
                "attribute_family": family,
                "source": str(row.get("source", "")).strip() or str(row.get("source_type", "")).strip() or "unknown",
                "source_type": str(row.get("source_type", "")).strip() or "unknown",
                "confidence": round(confidence, 2),
                "is_numeric": numeric,
                "is_verified": is_verified,
                "needs_verification": needs_verification,
            }
        )
    return verified_rows


def summarize_eav_quality(rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    verified = [row for row in (rows or []) if row.get("is_verified")]
    verified_families = sorted(
        {
            str(row.get("attribute_family", "")).strip()
            for row in verified
            if str(row.get("attribute_family", "")).strip()
        }
    )
    blocked_numeric_rows = [
        f"{row.get('attribute', '')}: {row.get('value', '')}"
        for row in (rows or [])
        if row.get("is_numeric") and not row.get("is_verified")
    ]
    if len(verified) >= 5 and len(verified_families) >= 3:
        coverage = "strong"
    elif len(verified) >= 3 and len(verified_families) >= 2:
        coverage = "medium"
    else:
        coverage = "weak"
    return {
        "verified_rows": len(verified),
        "attribute_families": len(verified_families),
        "coverage_status": coverage,
        "blocked_numeric_rows": blocked_numeric_rows[:10],
    }


def row_anchor_text(row: Dict[str, Any]) -> str:
    attribute = str(row.get("attribute", "")).strip()
    value = str(row.get("value", "")).strip()
    if attribute and value:
        return f"{attribute}: {value}"
    return value or attribute


def compact_anchor_text(row: Dict[str, Any], max_words: int = 26) -> str:
    value = str(row.get("value", "")).strip()
    attribute = str(row.get("attribute", "")).strip()
    text = value or row_anchor_text(row)
    split_pattern = r"[;.!?]" if len(text.split()) <= 20 else r"[,;.!?]"
    clauses = [c.strip(" -") for c in re.split(split_pattern, text) if c.strip()]
    if clauses:
        strong_markers = {"khong duoc", "bao gom", "gom", "ap dung", "hieu luc", "co the", "du toan", "yeu cau"}
        ranked = sorted(
            clauses,
            key=lambda c: (
                any(marker in normalize_text(c) for marker in strong_markers),
                bool(re.search(r"\d", c)),
                overlap_score(attribute, c),
                len(c.split()) >= 6,
                -abs(len(c.split()) - 14),
            ),
            reverse=True,
        )
        text = ranked[0]
    words = [w for w in text.split() if w.strip()]
    if len(words) > max_words:
        text = " ".join(words[:max_words]).strip()
    if attribute and value and overlap_score(attribute, text) < 0.5 and normalize_text(attribute) not in normalize_text(text):
        return f"{attribute}: {text}"
    return text


def semantic_distance_score(question: str, anchor_text: str) -> float:
    overlap = overlap_score(question, anchor_text)
    return round(max(0.0, 1.0 - overlap), 2)


def choose_heading_anchor_plan(
    h3_items: List[str],
    matched_rows: List[Dict[str, Any]],
    matched_consensus: List[str],
    matched_gaps: List[Dict[str, Any]],
    reuse_limit: int = 2,
) -> List[Dict[str, Any]]:
    def _question_kind(text: str) -> str:
        norm = normalize_text(text)
        if any(sig in norm for sig in ["la gi", "dinh nghia", "khai niem", "duoc hieu"]):
            return "definition"
        if any(sig in norm for sig in ["phan loai", "loai", "nhom", "gom nhung"]):
            return "classification"
        if any(sig in norm for sig in ["cach tinh", "nhu the nao", "co che", "quy trinh", "hoat dong", "bao nhieu"]):
            return "method"
        if any(sig in norm for sig in ["so sanh", "khac", "khac gi", "phan biet"]):
            return "comparison"
        if any(sig in norm for sig in ["rui ro", "luu y", "an", "sai lam", "canh bao"]):
            return "risk"
        if any(sig in norm for sig in ["anh huong", "tac dong", "loi nhuan", "ket qua", "phu hop"]):
            return "impact"
        return "attribute"

    usage: Dict[str, int] = {}
    plan: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []

    for row in matched_rows:
        if not isinstance(row, dict):
            continue
        if not row.get("is_verified"):
            continue
        anchor_text = compact_anchor_text(row)
        key = f"eav::{normalize_text(anchor_text)}"
        candidates.append(
            {
                "anchor_type": "eav",
                "anchor_text": anchor_text,
                "anchor_source": row.get("source_type", "eav"),
                "key": key,
                "row": row,
                "base_score": (
                    100
                    + float(row.get("confidence", 0.0)) * 10
                    + (8 if str(row.get("source_type", "")) == "competitor_body" else 0)
                    - (8 if str(row.get("source_type", "")) == "competitor_heading_fallback" else 0)
                ),
            }
        )

    for fact in matched_consensus or []:
        text = str(fact or "").strip()
        if not text:
            continue
        candidates.append(
            {
                "anchor_type": "consensus",
                "anchor_text": text,
                "anchor_source": "consensus_fact",
                "key": f"consensus::{normalize_text(text)}",
                "row": None,
                "base_score": 70,
            }
        )

    for gap in matched_gaps or []:
        text = ""
        if isinstance(gap, dict):
            text = str(gap.get("text", "")).strip()
        else:
            text = str(gap or "").strip()
        if not text:
            continue
        candidates.append(
            {
                "anchor_type": "gap",
                "anchor_text": text,
                "anchor_source": "gap_hint",
                "key": f"gap::{normalize_text(text)}",
                "row": None,
                "base_score": 50,
            }
        )

    for h3 in h3_items or []:
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        for candidate in candidates:
            used = usage.get(candidate["key"], 0)
            if used >= reuse_limit:
                continue
            distance = semantic_distance_score(h3, candidate["anchor_text"])
            if distance < 0.18:
                continue
            topical_overlap = overlap_score(h3, candidate["anchor_text"])
            question_kind = _question_kind(h3)
            row_family = normalize_text((candidate.get("row") or {}).get("attribute_family", ""))
            family_bonus = 0.0
            if question_kind == "definition" and row_family == "definition":
                family_bonus += 14
            elif question_kind == "definition" and row_family == "classification":
                family_bonus += 6
            elif question_kind == "definition" and row_family in {"cost", "risk", "condition", "impact"}:
                family_bonus -= 10
            elif question_kind == "classification" and row_family == "classification":
                family_bonus += 12
            elif question_kind == "classification" and row_family == "attribute":
                family_bonus += 8
            elif question_kind == "classification" and row_family in {"cost", "risk", "condition"}:
                family_bonus -= 8
            elif question_kind == "method" and row_family in {"process", "cost", "condition"}:
                family_bonus += 12
            elif question_kind == "method" and row_family in {"definition", "classification"}:
                family_bonus -= 8
            elif question_kind == "comparison" and row_family in {"comparison", "classification", "attribute"}:
                family_bonus += 10
            elif question_kind == "comparison" and row_family in {"definition"}:
                family_bonus -= 6
            elif question_kind == "risk" and row_family in {"risk", "condition", "cost"}:
                family_bonus += 10
            elif question_kind == "risk" and row_family in {"definition", "classification"}:
                family_bonus -= 8
            elif question_kind == "impact" and row_family in {"impact", "risk", "cost"}:
                family_bonus += 10
            elif question_kind == "impact" and row_family in {"definition", "classification"}:
                family_bonus -= 8
            elif question_kind == "attribute" and row_family in {"attribute", "classification", "application"}:
                family_bonus += 8
            elif candidate["anchor_type"] == "consensus":
                family_bonus += 4
            score = float(candidate["base_score"]) + family_bonus + (distance * 10) + (topical_overlap * 4) - (used * 4)
            if score > best_score:
                best_score = score
                best = {**candidate, "semantic_distance_score": distance}
        if best is None and candidates:
            fallback = candidates[0]
            best = {**fallback, "semantic_distance_score": semantic_distance_score(h3, fallback["anchor_text"])}
        if best is None:
            continue
        usage[best["key"]] = usage.get(best["key"], 0) + 1
        row = best.get("row") or {}
        plan.append(
            {
                "h3": h3,
                "anchor_type": best["anchor_type"],
                "anchor_text": best["anchor_text"],
                "anchor_source": best["anchor_source"],
                "semantic_distance_score": best["semantic_distance_score"],
                "attribute": row.get("attribute", ""),
                "value": row.get("value", ""),
            }
        )
    return plan
