# -*- coding: utf-8 -*-
"""
markdown_exporter.py - Render a writer-first Full Content Brief.

The output is optimized for implementation by content writers:
- no appendix-style strategist noise
- no duplicated A/B/C/E scaffolding
- section guidance is unique per H2
- semantic terms from previous research are reused to reduce keyword stuffing
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from modules.eav_verifier import row_anchor_text
from modules.semantic_purity import (
    clean_fact_text,
    is_clean_fact_candidate,
    normalize_text,
    overlap_score,
)

logger = logging.getLogger(__name__)

FINANCIAL_MARKERS = ()

BROKEN_ENTITY_NGRAMS = set()


def export_to_markdown(brief: Dict, output_dir: str) -> Tuple[str, str, str]:
    os.makedirs(output_dir, exist_ok=True)
    topic = _topic(brief) or "untitled"
    filename = _slugify(topic) + ".md"
    filepath = os.path.join(output_dir, filename)
    content = _render_markdown(brief)
    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write(content)
    logger.info("  -> Đã xuất: %s", filepath)
    return os.path.abspath(filepath), "", content


def _slugify(text: str) -> str:
    raw = _normalize_ascii(text)
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    return re.sub(r"-{2,}", "-", raw).strip("-") or "untitled"


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _truncate_words(text: Any, limit: int = 50) -> str:
    words = _clean_text(text).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(".,;:") + "."


def _normalize_ascii(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"\s+", " ", text).lower().strip()


def _topic(brief: Dict) -> str:
    return _clean_text(brief.get("central_entity") or brief.get("topic") or brief.get("seed_keyword"))


def _project_info(brief: Dict) -> Dict[str, str]:
    project = brief.get("_project_context")
    if not project:
        return {"name": "", "industry": "", "scope": ""}
    industry = _clean_text(getattr(project, "industry", "") or getattr(project, "project_type", ""))
    if not industry:
        industry = _clean_text(getattr(project, "description", ""))
    scope = _clean_text(getattr(project, "source_context", "") or getattr(project, "description", ""))
    return {
        "name": _clean_text(getattr(project, "name", "")),
        "industry": industry,
        "scope": scope,
    }


def _intent_payload(brief: Dict) -> Dict[str, str]:
    payload = brief.get("search_intent") or {}
    if isinstance(payload, dict):
        intent_type = _normalize_ascii(payload.get("type"))
        desc = _clean_text(payload.get("description"))
        focus = _clean_text(payload.get("content_focus"))
    else:
        intent_type = _normalize_ascii(payload)
        desc = ""
        focus = ""
    if intent_type not in {"informational", "commercial", "transactional", "navigational"}:
        if "commercial" in desc.lower() or "so sánh" in desc.lower() or "đánh giá" in desc.lower():
            intent_type = "commercial"
        else:
            intent_type = "informational"
    return {"type": intent_type, "description": desc, "content_focus": focus}


def _financial_context(brief: Dict) -> bool:
    return False

def _safe_page_type(brief: Dict) -> str:
    framework = brief.get("outline_content_framework", {}) if isinstance(brief.get("outline_content_framework"), dict) else {}
    page_type = _clean_text(framework.get("page_type"))
    if page_type:
        return page_type
    intent_type = _intent_payload(brief).get("type", "informational")
    if _financial_context(brief):
        return "Blog informational"
    if intent_type == "transactional":
        return "Product / Landing page"
    if intent_type == "commercial":
        return "Comparison / review page"
    return "Blog informational"


def _is_informational_page(brief: Dict) -> bool:
    page_type = _normalize_ascii(_safe_page_type(brief))
    return "informational" in page_type or "blog" in page_type or "article" in page_type


def _brand_terms(brief: Dict) -> set[str]:
    project = brief.get("_project_context")
    values = []
    if project:
        for field in ("brand_name", "name", "domain"):
            value = _clean_text(getattr(project, field, ""))
            if value:
                values.append(value)
    competitor = brief.get("competitor_analysis", {}) if isinstance(brief.get("competitor_analysis"), dict) else {}
    for item in competitor.get("competitors_detail", []) or []:
        if not isinstance(item, dict):
            continue
        url = _clean_text(item.get("url"))
        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        if match:
            values.append(match.group(1).split(".")[0])
    return {_normalize_ascii(value) for value in values if _normalize_ascii(value)}


def _valid_context_term(term: Any, brief: Dict) -> bool:
    text = _clean_text(term)
    norm = _normalize_ascii(text)
    if not text or not norm:
        return False
    if norm in BROKEN_ENTITY_NGRAMS:
        return False
    tokens = norm.split()
    if any(len(token) < 3 for token in tokens):
        return False
    brands = _brand_terms(brief)
    if norm in brands or any(norm == brand or norm.startswith(brand + " ") for brand in brands):
        return False
    topic_norm = _normalize_ascii(_topic(brief))
    if norm == topic_norm:
        return False
    return not _is_noise_term(text, topic_norm)


def _domain_safe_h2(brief: Dict, heading: str, kind: str = "") -> str:
    clean = _clean_heading_text(heading)
    lower = _normalize_ascii(clean)
    if lower.endswith(" hoat dong") or lower.endswith(" hoat dong?"):
        return clean.rstrip("?") + " như thế nào?"
    return clean

def _outline_items(brief: Dict) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for heading in brief.get("heading_structure", []) or []:
        if not isinstance(heading, dict):
            continue
        level = _clean_text(heading.get("level")).upper()
        text = _clean_heading_text(heading.get("text"))
        if not text:
            continue
        if level == "H2":
            current = {"text": text, "h3": []}
            items.append(current)
        elif level == "H3" and current is not None:
            current["h3"].append(text)
    role_priority = {
        "definition": 0,
        "attribute": 1,
        "classification": 2,
        "method": 3,
        "condition": 4,
        "comparison": 5,
        "decision": 6,
        "impact": 7,
        "risk": 8,
        "faq": 9,
        "general": 10,
    }
    total = len(items)
    indexed = [(idx, item) for idx, item in enumerate(items)]
    def sort_key(pair):
        idx, item = pair
        raw_kind = _section_kind(item["text"], idx, total)
        rendered_kind = _section_kind(_rewrite_h2(item["text"], idx), idx, total)
        priority = min(
            role_priority.get(raw_kind, role_priority["general"]),
            role_priority.get(rendered_kind, role_priority["general"]),
        )
        return (priority, idx)

    indexed.sort(key=sort_key)
    items = [item for _, item in indexed]
    return items


def _clean_heading_text(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"^\[[A-Z]+\]\s*", "", text)
    text = re.sub(r"^(?:\[[^\]]{2,80}\]\s*)+", "", text).strip()
    text = re.sub(r"\bduoc\b", "được", text, flags=re.IGNORECASE)
    text = re.sub(r"\bphan loai\b", "phân loại", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnhung\b", "những", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnhom\b", "nhóm", text, flags=re.IGNORECASE)
    text = re.sub(r"\bhoat dong\b", "hoạt động", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnhu the nao\b", "như thế nào", text, flags=re.IGNORECASE)
    text = re.sub(r"\bla gi\b", "là gì", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcan duoc hieu\b", "cần được hiểu", text, flags=re.IGNORECASE)
    return text.strip(" -:")


def _parse_eav_rows(brief: Dict) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    raw_rows = brief.get("eav_table_rows", []) or []
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            parsed = {
                "entity": _clean_text(row.get("entity") or row.get("Entity")),
                "attribute": _clean_text(row.get("attribute") or row.get("Attribute")),
                "value": _clean_text(row.get("value") or row.get("Value")),
                "attribute_family": _clean_text(row.get("attribute_family")),
                "source_type": _clean_text(row.get("source_type")),
                "confidence": row.get("confidence", 0.0),
                "is_numeric": bool(row.get("is_numeric")),
                "is_verified": bool(row.get("is_verified")),
                "needs_verification": bool(row.get("needs_verification")),
            }
            if _usable_eav_row(parsed):
                rows.append(parsed)
    if rows:
        return rows

    table = _clean_text(brief.get("eav_table"))
    if not table:
        return []
    for line in table.splitlines():
        if "|" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if _normalize_ascii(cells[0]) == "entity" or set("".join(cells)) == {"-"}:
            continue
        row = {
            "entity": cells[0],
            "attribute": cells[1],
            "value": cells[2],
            "attribute_family": "",
            "source_type": "eav_table",
            "confidence": 0.0,
            "is_numeric": bool(re.search(r"\d", cells[2])),
            "is_verified": False,
            "needs_verification": bool(re.search(r"\d", cells[2])),
        }
        if _usable_eav_row(row):
            rows.append(row)
    return rows


def _usable_eav_row(row: Dict[str, str]) -> bool:
    attr = _normalize_ascii(row.get("attribute"))
    value = _normalize_ascii(row.get("value"))
    if not attr or not value:
        return False
    if attr in {"root_attributes", "rare_attributes", "unique_attributes"}:
        return False
    if "can xac minh" in value or "khong co thuoc tinh" in value:
        return False
    if not is_clean_fact_candidate(row.get("attribute", ""), row.get("value", "")):
        return False
    return True


def _fact_text(row: Dict[str, Any], prefer_value: bool = False) -> str:
    attribute = clean_fact_text(row.get("attribute", ""))
    value = clean_fact_text(row.get("value", ""))
    attr_norm = _normalize_ascii(attribute)
    if prefer_value and value:
        return value
    if attr_norm in {"dinh nghia", "khai niem", "phan loai"} and value:
        return value
    if attribute and value:
        return f"{attribute}: {value}"
    return value or attribute


def _is_noise_term(text: Any, topic_norm: str = "") -> bool:
    norm = _normalize_ascii(text)
    if not norm:
        return True
    banned_phrases = {
        "bai viet lien quan",
        "lien quan",
        "viet nam",
        "download",
        "ung dung",
        "placeholder",
    }
    if norm in banned_phrases:
        return True
    if "?" in str(text) or " la gi" in norm:
        return True
    if topic_norm and (norm == topic_norm or norm.startswith(topic_norm + " la gi")):
        return True
    return False


def _outline_signals(brief: Dict) -> Dict[str, List[str]]:
    signals = brief.get("outline_signals") or {}
    topic_norm = _normalize_ascii(_topic(brief))
    if not isinstance(signals, dict):
        return {"consensus": [], "gap_h2": [], "gap_h3": []}
    return {
        "consensus": [
            _clean_text(x)
            for x in signals.get("consensus_points", [])
            if _clean_text(x) and not _is_noise_term(x, topic_norm)
        ],
        "gap_h2": [_clean_text(x) for x in signals.get("gap_h2_candidates", []) if _clean_text(x)],
        "gap_h3": [_clean_text(x) for x in signals.get("gap_h3_candidates", []) if _clean_text(x)],
    }


def _semantic_reasoning(brief: Dict) -> Dict[str, Any]:
    data = brief.get("semantic_reasoning") or {}
    if not isinstance(data, dict):
        return {
            "dominant_user_task": "",
            "supporting_tasks": [],
            "decision_blockers": [],
            "misinterpretation_risks": [],
            "consensus_facts": [],
            "gap_map": {"h2_worthy": [], "supporting_detail": [], "topical_expansion": [], "noise": []},
            "section_evidence_plan": {},
            "semantic_terms_curated": [],
            "preferred_flow": [],
        }
    gap_map = data.get("gap_map") if isinstance(data.get("gap_map"), dict) else {}
    return {
        "dominant_user_task": _clean_text(data.get("dominant_user_task")),
        "supporting_tasks": [_clean_text(x) for x in data.get("supporting_tasks", []) if _clean_text(x)],
        "decision_blockers": [_clean_text(x) for x in data.get("decision_blockers", []) if _clean_text(x)],
        "misinterpretation_risks": [_clean_text(x) for x in data.get("misinterpretation_risks", []) if _clean_text(x)],
        "consensus_facts": [_clean_text(x) for x in data.get("consensus_facts", []) if _clean_text(x)],
        "gap_map": {
            "h2_worthy": [_clean_text(x) for x in gap_map.get("h2_worthy", []) if _clean_text(x)],
            "supporting_detail": [_clean_text(x) for x in gap_map.get("supporting_detail", []) if _clean_text(x)],
            "topical_expansion": [_clean_text(x) for x in gap_map.get("topical_expansion", []) if _clean_text(x)],
            "noise": [_clean_text(x) for x in gap_map.get("noise", []) if _clean_text(x)],
        },
        "section_evidence_plan": data.get("section_evidence_plan") if isinstance(data.get("section_evidence_plan"), dict) else {},
        "verified_eav_rows": [row for row in data.get("verified_eav_rows", []) if isinstance(row, dict)],
        "eav_quality": data.get("eav_quality") if isinstance(data.get("eav_quality"), dict) else {},
        "semantic_terms_curated": [_clean_text(x) for x in data.get("semantic_terms_curated", []) if _clean_text(x)],
        "preferred_flow": [_clean_text(x) for x in data.get("preferred_flow", []) if _clean_text(x)],
    }


def _faq_questions(brief: Dict) -> List[str]:
    data = brief.get("faq_questions") or brief.get("suggested_questions") or []
    return [_clean_text(x) for x in data if _clean_text(x)]


def _lsi_terms(brief: Dict) -> List[str]:
    seen = set()
    terms: List[str] = []
    topic_norm = _normalize_ascii(_topic(brief))

    def push(item: Any) -> None:
        text = _clean_text(item)
        norm = _normalize_ascii(text)
        if not text or not norm or norm in seen:
            return
        if len(norm.split()) == 1 and len(norm) < 4:
            return
        if not _valid_context_term(text, brief):
            return
        if _is_noise_term(text, topic_norm):
            return
        seen.add(norm)
        terms.append(text)

    for item in brief.get("semantic_expansion_keywords", []) or []:
        push(item)

    ngram_str = _clean_text(brief.get("smart_ngrams_str"))
    if ngram_str:
        for part in re.split(r",|\n", ngram_str):
            cleaned = re.sub(r"\(\d+\)", "", part).strip()
            push(cleaned)

    network = brief.get("query_network") or {}
    clusters = network.get("clusters", []) if isinstance(network, dict) else []
    if isinstance(clusters, dict):
        clusters = clusters.get("clusters", [])
    if isinstance(clusters, list):
        for cluster in clusters[:5]:
            if isinstance(cluster, dict):
                for kw in cluster.get("keywords", [])[:6]:
                    push(kw)

    competitor = brief.get("competitor_analysis") or {}
    for heading in competitor.get("common_headings", [])[:8]:
        push(heading)

    return terms[:20]


def _token_set(text: str) -> set:
    stop = {"nhung", "cach", "la", "gi", "cho", "voi", "the", "nao", "trong", "cac", "mot", "tai", "ve"}
    tokens = re.findall(r"[a-z0-9]{3,}", _normalize_ascii(text))
    return {token for token in tokens if token not in stop}


def _overlap(a: str, b: str) -> float:
    left = _token_set(a)
    right = _token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def _best_eav_for_heading(brief: Dict, heading_text: str, limit: int = 2) -> List[Dict[str, str]]:
    reasoning = _semantic_reasoning(brief)
    per_heading = reasoning.get("section_evidence_plan", {}).get("per_heading", {}) if isinstance(reasoning.get("section_evidence_plan", {}), dict) else {}
    for key, meta in per_heading.items():
        if _normalize_ascii(key) == _normalize_ascii(heading_text) and isinstance(meta, dict):
            matched = [
                row for row in meta.get("matched_eav", [])
                if isinstance(row, dict) and row.get("is_verified") and is_clean_fact_candidate(row.get("attribute", ""), row.get("value", ""))
            ]
            if matched:
                return matched[:limit]
    scored: List[Tuple[float, Dict[str, str]]] = []
    for row in _parse_eav_rows(brief):
        if row.get("needs_verification"):
            continue
        score = max(
            _overlap(heading_text, row.get("attribute", "")),
            _overlap(heading_text, row.get("attribute", "") + " " + row.get("value", "")),
        )
        attr_norm = _normalize_ascii(row.get("attribute"))
        heading_norm = _normalize_ascii(heading_text)
        family = _normalize_ascii(row.get("attribute_family"))
        if "dinh nghia" in attr_norm and any(key in heading_norm for key in ["khai niem", "la gi", "tong quan"]):
            score += 0.4
        if "phan loai" in attr_norm and any(key in heading_norm for key in ["phan loai", "cau phan", "cac loai"]):
            score += 0.4
        if family in {"definition", "classification"} and any(key in heading_norm for key in ["khai niem", "la gi", "dinh nghia", "tong quan"]):
            score += 0.5
        if family in {"risk", "condition"} and any(key in heading_norm for key in ["rui ro", "luu y", "sai lam", "canh bao"]):
            score += 0.5
        if row.get("is_verified"):
            score += 0.25 + min(0.4, float(row.get("confidence", 0.0)) / 2)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:limit]]


def _best_gap_for_heading(brief: Dict, heading_text: str, limit: int = 2) -> List[str]:
    reasoning = _semantic_reasoning(brief)
    per_heading = reasoning.get("section_evidence_plan", {}).get("per_heading", {}) if isinstance(reasoning.get("section_evidence_plan", {}), dict) else {}
    for key, meta in per_heading.items():
        if _normalize_ascii(key) == _normalize_ascii(heading_text) and isinstance(meta, dict):
            matched = [str(item.get("text", "")) for item in meta.get("matched_gaps", []) if isinstance(item, dict) and _clean_text(item.get("text"))]
            if matched:
                return matched[:limit]
    signals = _outline_signals(brief)
    pool = signals["gap_h2"] + signals["gap_h3"] + [_clean_text(x) for x in (brief.get("content_gaps") or []) if _clean_text(x)]
    scored = [(max(_overlap(heading_text, item), 0.0), item) for item in pool]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _best_consensus_for_heading(brief: Dict, heading_text: str, limit: int = 2) -> List[str]:
    reasoning = _semantic_reasoning(brief)
    per_heading = reasoning.get("section_evidence_plan", {}).get("per_heading", {}) if isinstance(reasoning.get("section_evidence_plan", {}), dict) else {}
    for key, meta in per_heading.items():
        if _normalize_ascii(key) == _normalize_ascii(heading_text) and isinstance(meta, dict):
            matched = [_clean_text(item) for item in meta.get("matched_consensus_facts", []) if _clean_text(item)]
            if matched:
                return matched[:limit]
    scored = [(max(_overlap(heading_text, item), 0.0), item) for item in _outline_signals(brief)["consensus"]]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _best_lsi_for_heading(brief: Dict, heading_text: str, limit: int = 4) -> List[str]:
    reasoning_terms = _semantic_reasoning(brief).get("semantic_terms_curated", [])
    pool = [term for term in (reasoning_terms or _lsi_terms(brief)) if _valid_context_term(term, brief)]
    scored = [(max(_overlap(heading_text, item), 0.0), item) for item in pool]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:limit]]


def _fallback_terms_for_kind(brief: Dict, kind: str) -> List[str]:
    by_kind = {
        "definition": ["khai niem", "pham vi", "ranh gioi", "ngu canh"],
        "attribute": ["thuoc tinh", "tieu chi", "nhom chinh", "khac biet"],
        "method": ["quy trinh", "buoc thuc hien", "dau vao", "ket qua"],
        "risk": ["rui ro", "gioi han", "hieu nham", "dieu kien an"],
        "impact": ["tac dong", "loi ich", "ket qua", "muc phu hop"],
        "comparison": ["tieu chi", "lua chon", "khac biet", "uu tien"],
        "faq": ["cau hoi", "dieu kien", "vi du", "luu y"],
    }
    return by_kind.get(kind, by_kind["attribute"])

def _section_context_terms(
    brief: Dict,
    heading_text: str,
    kind: str,
    used_terms: set[str],
    previous_terms: set[str],
    limit: int = 4,
) -> List[str]:
    pool: List[str] = []
    pool.extend(_best_lsi_for_heading(brief, heading_text, limit=8))
    pool.extend(_lsi_terms(brief))
    pool.extend(_fallback_terms_for_kind(brief, kind))

    chosen: List[str] = []
    seen = set()
    for term in pool:
        text = _clean_text(term)
        norm = _normalize_ascii(text)
        if not _valid_context_term(text, brief) or norm in seen or norm in used_terms:
            continue
        if norm in previous_terms and len(chosen) < 2:
            continue
        seen.add(norm)
        chosen.append(text)
        if len(chosen) >= limit:
            break

    if len(chosen) < limit:
        for term in _fallback_terms_for_kind(brief, kind):
            norm = _normalize_ascii(term)
            if norm not in seen and norm not in used_terms:
                chosen.append(term)
                seen.add(norm)
            if len(chosen) >= limit:
                break
    return chosen[:limit]


def _internal_link_nodes(brief: Dict) -> List[Dict[str, str]]:
    linking = brief.get("internal_linking") or {}
    nodes = linking.get("cluster_nodes") or []
    normalized: List[Dict[str, str]] = []
    for node in nodes:
        if isinstance(node, dict):
            anchor = _clean_text(node.get("anchor") or node.get("title") or node.get("keyword"))
            keyword = _clean_text(node.get("keyword") or anchor)
            if anchor:
                normalized.append({"anchor": anchor, "keyword": keyword})
    return normalized


def _best_link_for_heading(brief: Dict, heading_text: str) -> Optional[str]:
    best_anchor = ""
    best_score = 0.0
    for node in _internal_link_nodes(brief):
        score = max(_overlap(heading_text, node["anchor"]), _overlap(heading_text, node["keyword"]))
        if score > best_score:
            best_anchor = node["anchor"]
            best_score = score
    return best_anchor if best_score > 0.15 else None


def _micro_for_heading(brief: Dict, heading_text: str) -> Dict[str, Any]:
    best: Dict[str, Any] = {}
    best_score = 0.0
    for item in brief.get("micro_briefing", []) or []:
        if not isinstance(item, dict):
            continue
        label = _clean_text(item.get("heading") or item.get("section_title") or item.get("h2"))
        score = _overlap(heading_text, label)
        if _normalize_ascii(label) == _normalize_ascii(heading_text):
            score += 1.0
        if score > best_score:
            best = item
            best_score = score
    return best if best_score > 0.15 else {}


def _rewrite_h2(text: str, index: int) -> str:
    clean = _clean_heading_text(text)
    clean = re.sub(r"\bchi phí\s+chi phí\b", "chi phí", clean, flags=re.IGNORECASE)
    lower = _normalize_ascii(clean)
    if any(sig in lower for sig in ["hien nay", "hom nay", "moi nhat", "cap nhat"]):
        clean = re.sub(r"\b(hiện nay|hôm nay|mới nhất|cập nhật)\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" -:")
        if any(token in lower for token in ["gia", "price"]):
            clean = re.sub(r"^(Giá|Gia)\s+", "Yếu tố ảnh hưởng đến giá ", clean, flags=re.IGNORECASE)
        lower = _normalize_ascii(clean)
    if "faq" in lower or "cau hoi thuong gap" in lower:
        return "Câu hỏi thường gặp về chủ đề này"
    if "nhung sai lam" in lower or "cac sai lam" in lower:
        match = re.search(r"((?:Những|Các)\s+sai lầm.+)$", clean, flags=re.IGNORECASE)
        return match.group(1).strip() if match else clean
    if any(key in lower for key in ["la gi", "dinh nghia", "tong quan"]):
        topic = re.sub(r"\?\s*$", "", clean)
        topic = re.sub(r"\s+là gì.*$", "", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\s+la gi.*$", "", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\s+dinh nghia.*$", "", topic, flags=re.IGNORECASE)
        return f"Khái niệm {topic}".strip()
    if lower.startswith("huong dan toi uu hoa") or lower.startswith("hướng dẫn tối ưu hóa"):
        return re.sub(r"^(Hướng dẫn|Huong dan)", "Chiến lược", clean, flags=re.IGNORECASE)
    if lower.startswith("bang phan tich") or lower.startswith("bảng phân tích"):
        return clean
    if lower.startswith("cach tinh"):
        return re.sub(r"^(Cách tính|Cach tinh)", "Phương pháp tính", clean, flags=re.IGNORECASE)
    if lower.endswith(" hoat dong") or lower.endswith(" hoat dong?"):
        return clean.rstrip("?") + " như thế nào?"
    if "anh huong" in lower or "nhu the nao" in lower:
        text2 = clean
        text2 = re.sub(r"như thế nào\??$", "", text2, flags=re.IGNORECASE)
        text2 = re.sub(r"nhu the nao\??$", "", text2, flags=re.IGNORECASE)
        return text2.strip()
    if lower.startswith("so sanh"):
        return re.sub(r"^(So sánh|So sanh)", "Bảng đánh giá", clean, flags=re.IGNORECASE)
    if lower.startswith("nhung ") or lower.startswith("cac "):
        return clean
    return clean


def _rendered_h2_key(text: str) -> str:
    norm = _normalize_ascii(text)
    if norm.startswith(("khai niem ", "dinh nghia ")):
        norm = norm.split(":", 1)[0].strip()
    return norm


def _numeric_fact(rows: List[Dict[str, str]]) -> str:
    for row in rows:
        value = row.get("value", "")
        if re.search(r"\d", value):
            return f"{row['attribute']}: {value}"
    if rows:
        return f"{rows[0]['attribute']}: {rows[0]['value']}"
    return ""


def _verified_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    verified = [row for row in rows if isinstance(row, dict) and row.get("is_verified")]
    return verified or [row for row in rows if isinstance(row, dict) and not row.get("needs_verification")]


def _safe_numeric_fact(rows: List[Dict[str, Any]]) -> str:
    for row in _verified_rows(rows):
        if row.get("is_numeric") and row.get("is_verified") and re.search(r"\d", str(row.get("value", ""))):
            return row_anchor_text(row)
    return ""


def _anchor_fact_for_section(
    brief: Dict,
    heading_text: str,
    kind: str,
    rows: List[Dict[str, Any]],
    used_facts: set[str],
) -> str:
    for row in _verified_rows(rows):
        fact = row_anchor_text(row)
        norm = _normalize_ascii(fact)
        if fact and norm and norm not in used_facts:
            used_facts.add(norm)
            return fact

    fallback_by_kind = {
        "definition": f"Làm rõ {heading_text} bằng phạm vi nghĩa, entity trung tâm và ranh giới với khái niệm gần nghĩa.",
        "attribute": "Chỉ dùng thuộc tính ảnh hưởng trực tiếp đến user need, intent và quyết định tiếp theo của người đọc.",
        "method": "Mô tả cơ chế bằng chuỗi điều kiện -> hành động -> kết quả, chỉ dựa trên evidence hiện tại.",
        "risk": "Rủi ro phải gắn với điều kiện áp dụng, hiểu sai phổ biến hoặc điểm dữ liệu cần kiểm chứng.",
        "impact": "Lợi ích chỉ có giá trị khi đặt cạnh bối cảnh áp dụng, giới hạn và mức đánh đổi liên quan.",
        "comparison": "Mọi so sánh phải dùng cùng bộ tiêu chí để tránh biến section thành danh sách rời rạc.",
        "faq": "Mỗi câu trả lời FAQ phải ngắn, trực tiếp và không lặp nguyên văn H2 định nghĩa.",
    }
    fact = fallback_by_kind.get(kind, f"Neo section vào một luận điểm duy nhất liên quan trực tiếp đến {heading_text}.")
    norm = _normalize_ascii(fact)
    if norm in used_facts:
        fact = f"{fact} Góc triển khai riêng: {heading_text}."
        norm = _normalize_ascii(fact)
    used_facts.add(norm)
    return fact


def _decision_blocker_for_section(brief: Dict, heading_text: str, kind: str, index: int) -> str:
    reasoning = _semantic_reasoning(brief)
    candidates = reasoning.get("decision_blockers", []) or []
    scored = [(max(_overlap(heading_text, item), 0.0), item) for item in candidates if _clean_text(item)]
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        return scored[0][1]
    topic = _topic(brief)
    by_kind = {
        "definition": f"Người đọc chưa biết {topic} là gì, phạm vi áp dụng ra sao và khác gì với khái niệm gần nghĩa.",
        "attribute": "Người đọc chưa biết tiêu chí nào thật sự ảnh hưởng đến cách hiểu, đánh giá hoặc hành động tiếp theo.",
        "method": "Người đọc chưa hình dung cơ chế vận hành từ điều kiện đầu vào đến kết quả đầu ra.",
        "risk": "Người đọc chưa biết điều kiện nào có thể làm cách hiểu hoặc quyết định trở nên sai lệch.",
        "impact": "Người đọc chưa rõ lợi ích chỉ đúng trong bối cảnh nào và khi nào không nên áp dụng.",
        "comparison": "Người đọc chưa có bộ tiêu chí để so sánh lựa chọn mà không bị nhiễu bởi thông tin phụ.",
        "faq": "Người đọc cần câu trả lời nhanh cho các nghi vấn còn lại trước khi hành động.",
    }
    return by_kind.get(kind, f"Người đọc chưa rõ phần {index + 1} đóng vai trò gì trong quyết định tìm kiếm.")


def _section_format(kind: str) -> str:
    return {
        "definition": "para + short list",
        "attribute": "table/list",
        "method": "numbered list",
        "risk": "warning list",
        "impact": "para + example",
        "comparison": "comparison table",
        "faq": "FAQ short answers",
    }.get(kind, "para/list")


def _word_target(kind: str, h3_count: int) -> int:
    base = {
        "definition": 520,
        "attribute": 480,
        "method": 520,
        "risk": 460,
        "impact": 420,
        "comparison": 480,
        "faq": 220,
    }.get(kind, 420)
    return base + max(0, h3_count - 2) * 80


def _anchor_plan_for_heading(brief: Dict, parent_heading: str) -> Dict[str, Dict[str, Any]]:
    reasoning = _semantic_reasoning(brief)
    per_heading = reasoning.get("section_evidence_plan", {}).get("per_heading", {}) if isinstance(reasoning.get("section_evidence_plan", {}), dict) else {}
    for key, meta in per_heading.items():
        if _normalize_ascii(key) == _normalize_ascii(parent_heading) and isinstance(meta, dict):
            plan = meta.get("anchor_plan", []) or []
            result: Dict[str, Dict[str, Any]] = {}
            for item in plan:
                if not isinstance(item, dict):
                    continue
                h3 = _clean_text(item.get("h3"))
                if h3:
                    result[_normalize_ascii(h3)] = item
            return result
    return {}








def _vector_lock(brief: Dict) -> str:
    reasoning = _semantic_reasoning(brief)
    if reasoning["consensus_facts"] or reasoning["misinterpretation_risks"] or reasoning["semantic_terms_curated"]:
        chunks: List[str] = [f"Giữ trọng tâm bài viết ở thực thể [{_topic(brief)}]"]
        project = _project_info(brief)
        if project["industry"]:
            chunks.append(f"trong ngữ cảnh [{project['industry']}]")
        if reasoning["consensus_facts"]:
            chunks.append("và các fact đồng thuận cần giữ như " + "; ".join(reasoning["consensus_facts"][:4]))
        if reasoning["misinterpretation_risks"]:
            chunks.append(". Tránh drift sang: " + "; ".join(reasoning["misinterpretation_risks"][:4]))
        if reasoning["semantic_terms_curated"]:
            chunks.append(". Ưu tiên dùng biến thể ngữ nghĩa như " + ", ".join(reasoning["semantic_terms_curated"][:8]) + " để giảm lặp exact-match.")
        return " ".join(chunks)
    topic = _topic(brief)
    project = _project_info(brief)
    consensus = _outline_signals(brief)["consensus"][:3]
    lsi = _lsi_terms(brief)[:6]
    chunks = [f"Giữ trọng tâm bài viết ở thực thể [{topic}]"]
    if project["industry"]:
        chunks.append(f"trong ngữ cảnh [{project['industry']}]")
    if consensus:
        chunks.append(f"và các trục nội dung bắt buộc như {', '.join(consensus)}")
    if lsi:
        chunks.append(f". Ưu tiên dùng biến thể ngữ nghĩa như {', '.join(lsi)} để giảm lặp exact-match.")
    return " ".join(chunks)












def _info_gain_line(kind: str, consensus: List[str], gaps: List[str]) -> str:
    if kind == "definition":
        return "Điểm vượt phải là làm rõ phạm vi nghĩa và ranh giới với các khái niệm gần nghĩa mà đối thủ thường gộp hoặc nói lẫn."
    if kind == "method":
        return "Điểm vượt phải là có ví dụ, cơ chế hoặc tình huống thực tế thay vì chỉ mô tả nguyên lý chung."
    if kind == "risk":
        return "Điểm vượt phải là chỉ ra điều kiện ẩn, sai lầm hoặc hậu quả thực tế mà đối thủ chưa diễn giải đủ."
    if kind == "impact":
        return "Điểm vượt phải là nối yếu tố đang bàn với thay đổi trong kết quả, quyết định hoặc mức độ phù hợp."
    if kind == "comparison":
        return "Điểm vượt phải là có bộ tiêu chí so sánh rõ ràng, không chỉ liệt kê tên lựa chọn hoặc đặc điểm bề mặt."
    if gaps:
        return "Điểm vượt nên khai thác trực tiếp các khoảng trống như " + ", ".join(gaps[:2]) + "."
    if consensus:
        return "Điểm vượt nên đi sâu hơn lớp đồng thuận phổ biến như " + ", ".join(consensus[:2]) + "."
    return "Điểm vượt phải nằm ở ví dụ, dữ kiện cụ thể hoặc góc nhìn mà top đối thủ chưa triển khai đủ."




def _transition_line(kind: str, next_heading: str, link_anchor: Optional[str]) -> str:
    if kind == "definition":
        base = "Khép phần này bằng câu nối từ khái niệm sang thuộc tính hoặc cơ chế cốt lõi của chủ đề."
    elif kind == "method":
        base = "Khép phần này bằng câu nối từ cơ chế hoặc cách áp dụng sang điều kiện ẩn hoặc rủi ro trong thực tế."
    elif kind == "risk":
        base = "Khép phần này bằng câu nối cho thấy vì sao người đọc cần nhìn tiếp tác động của các điều kiện này đến quyết định thực tế."
    elif kind == "impact":
        base = "Khép phần này bằng câu nối sang phần so sánh để người đọc biết nên đánh giá các lựa chọn theo tiêu chí gì."
    elif kind == "comparison":
        base = "Khép phần này bằng một CTA mềm hoặc chuyển về FAQ để giải quyết câu hỏi đuôi."
    else:
        base = "Khép phần này bằng một câu nối logic sang nội dung kế tiếp."
    if next_heading:
        base += f" Phần kế tiếp nên mở tự nhiên sang: {next_heading}."
    if link_anchor:
        base += f" Nếu cần nối topical graph, có thể dẫn mềm sang node [{link_anchor}]."
    return base




def _render_outline(brief: Dict, outline_items: List[Dict[str, Any]]) -> str:
    lines: List[str] = ["## 7. Dàn ý chi tiết", ""]
    total = len(outline_items)
    reasoning = _semantic_reasoning(brief)
    section_plan = reasoning.get("section_evidence_plan", {}) if isinstance(reasoning.get("section_evidence_plan"), dict) else {}
    per_heading = section_plan.get("per_heading", {}) if isinstance(section_plan.get("per_heading"), dict) else {}
    used_terms: set[str] = set()
    previous_terms: set[str] = set()
    used_facts: set[str] = set()
    seen_h3: set[str] = set()
    seen_h2: set[str] = set()
    for index, item in enumerate(outline_items):
        raw_heading = item["text"]
        heading_meta = per_heading.get(raw_heading) if isinstance(per_heading.get(raw_heading), dict) else {}
        kind = str(heading_meta.get("kind") or _section_kind(raw_heading, index, total))
        heading = _domain_safe_h2(brief, _rewrite_h2(raw_heading, index), kind)
        heading_key = _rendered_h2_key(heading)
        if heading_key in seen_h2:
            continue
        seen_h2.add(heading_key)
        rows = _best_eav_for_heading(brief, heading)
        micro = {} if kind == "faq" else _micro_for_heading(brief, raw_heading)
        h3_items = item.get("h3", []) or []
        if kind == "faq":
            h3_items = _faq_questions(brief) or h3_items
        h3_items = [
            _clean_text(h3)
            for h3 in h3_items
            if _clean_text(h3)
            and (kind != "faq" or _normalize_ascii(h3) not in seen_h3)
        ]
        for h3 in h3_items:
            seen_h3.add(_normalize_ascii(h3))

        terms = _section_context_terms(brief, heading, kind, used_terms, previous_terms)
        for term in terms:
            used_terms.add(_normalize_ascii(term))
        previous_terms = {_normalize_ascii(term) for term in terms}
        anchor_fact = _anchor_fact_for_section(brief, heading, kind, rows, used_facts)
        decision_blocker = _decision_blocker_for_section(brief, heading, kind, index)
        word_target = _word_target(kind, len(h3_items))

        lines.extend(
            [
                f"### H2: {heading} | ~{word_target} words | Format: {_section_format(kind)}",
                f"Decision blocker: {decision_blocker}",
                f"FS target: {_truncate_words(_featured_snippet(brief, heading, kind, rows, micro), 50)}",
                f"Context terms riêng: {', '.join(terms)} | Anchor fact: {anchor_fact}",
            ]
        )

        if h3_items:
            lines.append("H3 cần viết:")
            lines.extend(_h3_line(brief, h3_text, heading) for h3_text in h3_items if _clean_text(h3_text))

        lines.append("")
    return "\n".join(lines).strip()


def _deep_intent(brief: Dict, outline_items: List[Dict[str, Any]]) -> str:
    reasoning = _semantic_reasoning(brief)
    if reasoning["dominant_user_task"]:
        chunks = [reasoning["dominant_user_task"]]
        if reasoning["supporting_tasks"]:
            chunks.append("Các nhu cầu phụ cần được giải quyết gồm: " + "; ".join(reasoning["supporting_tasks"][:5]) + ".")
        if reasoning["decision_blockers"]:
            chunks.append("Các điểm khiến người đọc chưa thể ra quyết định ngay gồm: " + "; ".join(reasoning["decision_blockers"][:4]) + ".")
        if reasoning["preferred_flow"]:
            chunks.append("Luồng trả lời nên đi theo thứ tự: " + " -> ".join(reasoning["preferred_flow"][:7]) + ".")
        return " ".join(chunks)

    topic = _topic(brief)
    intent = _intent_payload(brief)
    project = _project_info(brief)
    h2_flow = ", ".join(
        _domain_safe_h2(brief, _rewrite_h2(item["text"], i), _section_kind(item["text"], i, len(outline_items)))
        for i, item in enumerate(outline_items[:4])
    )
    if intent["type"] == "commercial":
        base = (
            f"Người tìm kiếm đang ở giai đoạn cân nhắc lựa chọn: họ muốn biết {topic} gồm những khía cạnh nào, "
            "khác nhau ra sao giữa các lựa chọn và tiêu chí nào thực sự ảnh hưởng đến quyết định."
        )
    elif intent["type"] == "transactional":
        base = (
            f"Người tìm kiếm cần tiến tới hành động, nên họ quan tâm trực tiếp đến điều kiện áp dụng, cách thực hiện "
            f"và các điểm cần kiểm tra trước khi bắt đầu với {topic}."
        )
    elif intent["type"] == "navigational":
        base = (
            f"Người tìm kiếm muốn xác nhận mình đã tới đúng thực thể liên quan đến {topic} "
            "và cần con đường ngắn nhất để hiểu câu trả lời hoặc đi tới thông tin phù hợp."
        )
    else:
        base = (
            f"Người tìm kiếm không chỉ muốn hiểu {topic} là gì mà còn muốn biết các thuộc tính quan trọng, "
            "điểm khác biệt, ngữ cảnh áp dụng và các lưu ý thực tế."
        )
    if project["industry"]:
        base += f" Toàn bộ bài phải khóa trong ngữ cảnh {project['industry']}."
    if h2_flow:
        base += f" Luồng trả lời nên đi theo thứ tự: {h2_flow}."
    return base


def _article_mission(brief: Dict, outline_items: List[Dict[str, Any]]) -> str:
    reasoning = _semantic_reasoning(brief)
    if reasoning["dominant_user_task"]:
        mission = f"Bài viết phải hoàn thành user task chính là: {reasoning['dominant_user_task']}"
        if reasoning["preferred_flow"]:
            mission += " Thứ tự triển khai nên bám flow: " + " -> ".join(reasoning["preferred_flow"][:7]) + "."
        if reasoning["decision_blockers"]:
            mission += " Mỗi H2 cần tháo gỡ ít nhất một decision blocker thay vì lặp lại định nghĩa gốc."
        return mission
    topic = _topic(brief)
    intent = _intent_payload(brief)
    mission = (
        f"Bài viết phải giúp người đọc hiểu đúng bản chất của {topic}, biết các yếu tố cốt lõi cần xem xét "
        "và có đủ cơ sở để ra quyết định hoặc áp dụng đúng ngữ cảnh."
    )
    if intent.get("content_focus"):
        mission += f" Trọng tâm triển khai: {intent['content_focus']}."
    if outline_items:
        mission += " Không được lặp lại cùng một định nghĩa ở nhiều section; mỗi H2 phải giải quyết một câu hỏi khác nhau."
    return mission


def _info_gain_map(brief: Dict) -> str:
    reasoning = _semantic_reasoning(brief)
    gap_map = reasoning.get("gap_map", {})
    if reasoning["consensus_facts"] or any(gap_map.get(key) for key in ["h2_worthy", "supporting_detail", "topical_expansion"]):
        chunks: List[str] = []
        if reasoning["consensus_facts"]:
            chunks.append("Các lớp thông tin bắt buộc phải có vì nhiều nguồn cùng xác nhận: " + "; ".join(reasoning["consensus_facts"][:4]) + ".")
        h2_gaps = [item for item in gap_map.get("h2_worthy", [])]
        support_gaps = [item for item in gap_map.get("supporting_detail", [])]
        expansion_gaps = [item for item in gap_map.get("topical_expansion", [])]
        if h2_gaps:
            chunks.append("Các khoảng trống đủ lớn để nâng thành H2 riêng: " + "; ".join(h2_gaps[:4]) + ".")
        if support_gaps:
            chunks.append("Các khoảng trống chỉ nên triển khai như H3 hoặc ví dụ hỗ trợ: " + "; ".join(support_gaps[:4]) + ".")
        if expansion_gaps:
            chunks.append("Các topical expansion chỉ dùng khi còn phục vụ intent chính: " + "; ".join(expansion_gaps[:3]) + ".")
        return " ".join(chunks)
    signals = _outline_signals(brief)
    consensus = signals["consensus"][:3]
    gaps = signals["gap_h2"][:4] + signals["gap_h3"][:2]
    chunks: List[str] = []
    if consensus:
        chunks.append("Các lớp thông tin bắt buộc phải có vì nhiều nguồn cùng lặp lại: " + "; ".join(consensus) + ".")
    if gaps:
        chunks.append("Các điểm vượt đối thủ cần biến thành nội dung thật thay vì chỉ nêu tên: " + "; ".join(gaps) + ".")
    if not chunks:
        chunks.append("Nếu dữ liệu đối thủ yếu, vẫn phải bổ sung ít nhất 1 bảng, 1 ví dụ cụ thể và 1 lớp cảnh báo hoặc phân biệt để tạo information gain.")
    return " ".join(chunks)




def _meta_description_notes(brief: Dict) -> str:
    meta = _clean_text(brief.get("meta_description"))
    meta_norm = _normalize_ascii(meta)
    if meta:
        return f"Giữ meta description theo hướng lợi ích và quyết định: {meta}"
    topic = _topic(brief)
    if _financial_context(brief):
        return (
            f"Viết meta description 145-160 ký tự theo intent informational: giải thích {topic}, "
            "cách hoạt động, lợi ích, rủi ro và điều kiện cần biết. Không suy diễn ngoài dữ liệu đã thu thập."
        )
    return "Viết meta description 145-160 ký tự, nhấn vào giá trị chính, điểm khác biệt và lợi ích thông tin cho người đọc."


def _schema_notes(brief: Dict) -> str:
    framework = brief.get("outline_content_framework", {}) if isinstance(brief.get("outline_content_framework"), dict) else {}
    meta_pack = framework.get("meta_schema_package", {}) if isinstance(framework.get("meta_schema_package"), dict) else {}
    schemas = meta_pack.get("schema_skeletons", []) if isinstance(meta_pack.get("schema_skeletons"), list) else []
    labels = [_clean_text(item.get("label")) for item in schemas if isinstance(item, dict) and _clean_text(item.get("label"))]
    if _is_informational_page(brief):
        labels = [label for label in labels if label != "Product"]
        if "Article" not in labels:
            labels.insert(0, "Article")
        if _faq_questions(brief) and "FAQPage" not in labels:
            labels.append("FAQPage")
        return "Schema dùng cho bài informational: " + " + ".join(labels) + ". Không dùng Product schema hoặc price rỗng."
    if labels:
        return "Schema đề xuất: " + " + ".join(labels) + ". Chỉ thêm Offer khi có giá thật đã xác minh."
    return "Schema đề xuất: Article. Chỉ thêm schema khác khi page type và dữ liệu thật đủ điều kiện."




def _verified_rows_for_heading(brief: Dict, heading_text: str, limit: int = 3) -> List[Dict[str, Any]]:
    rows = _best_eav_for_heading(brief, heading_text, limit=limit)
    return [row for row in rows if isinstance(row, dict) and row.get("is_verified")]


def _opening_fact(brief: Dict, heading_text: str) -> str:
    rows = _verified_rows_for_heading(brief, heading_text, limit=3)
    numeric = _safe_numeric_fact(rows)
    if numeric:
        return numeric
    for row in rows:
        if _normalize_ascii(str(row.get("attribute", ""))) in {"dinh nghia", "khai niem", "phan loai"}:
            return _fact_text(row, prefer_value=True)
    return _fact_text(rows[0], prefer_value=True) if rows else ""


def _has_verified_numeric_fact(brief: Dict) -> bool:
    reasoning = _semantic_reasoning(brief)
    for row in reasoning.get("verified_eav_rows", []) or []:
        if isinstance(row, dict) and row.get("is_verified") and row.get("is_numeric"):
            return True
    return False




def _facts_line(rows: List[Dict[str, str]], lsi: List[str]) -> str:
    verified_rows = _verified_rows(rows)
    chunks: List[str] = []
    if verified_rows:
        chunks.append("Dữ kiện bắt buộc: " + "; ".join(row_anchor_text(row) for row in verified_rows[:2]) + ".")
    else:
        chunks.append("Dữ kiện bắt buộc: chỉ dùng fact đã xác minh; nếu thiếu số liệu thật thì viết theo nghĩa lõi, điều kiện áp dụng hoặc ví dụ không gắn số bịa.")
    if lsi:
        chunks.append("Ưu tiên dùng biến thể ngữ nghĩa: " + ", ".join(lsi[:4]) + ".")
    return " ".join(chunks)


def _h3_line(brief: Dict, h3_text: str, parent_heading: str) -> str:
    anchor_plan = _anchor_plan_for_heading(brief, parent_heading)
    h3_text = _clean_heading_text(h3_text)
    if len(h3_text.split()) > 18:
        h3_text = h3_text.split(":", 1)[0].strip()
        h3_text = " ".join(h3_text.split()[:18]).rstrip(" ,;:-")
    planned = anchor_plan.get(_normalize_ascii(h3_text), {})
    rows = _best_eav_for_heading(brief, h3_text, limit=1) or _best_eav_for_heading(brief, parent_heading, limit=1)
    lsi = _best_lsi_for_heading(brief, h3_text, limit=2)
    clean_bits = [f"- {h3_text}"]
    if planned and _clean_text(planned.get("anchor_text")):
        clean_bits.append(f"Dữ kiện cần dùng: {_clean_text(planned.get('anchor_text'))}")
    elif rows:
        row = rows[0]
        clean_bits.append(f"Dữ kiện cần dùng: {str(row.get('attribute', '')).lower()} - {str(row.get('value', ''))}")
    if lsi:
        clean_bits.append(f"Biến thể ngữ nghĩa phù hợp: {', '.join(lsi)}")
    return " - ".join(clean_bits)
    bits = [f"- {h3_text}"]
    if planned and _clean_text(planned.get("anchor_text")):
        bits.append(f"neo vào {str(planned.get('anchor_type', 'fact'))}: {_clean_text(planned.get('anchor_text'))}")
    elif rows:
        row = rows[0]
        bits.append(f"neo vào dữ kiện {str(row.get('attribute', '')).lower()}: {str(row.get('value', ''))}")
    if lsi:
        bits.append(f"dùng thêm cụm {', '.join(lsi)}")
    return " — ".join(bits)




def _render_markdown(brief: Dict) -> str:
    topic = _topic(brief) or "Untitled"
    title_tag = _clean_text(brief.get("title_tag")) or topic
    outline_items = _outline_items(brief)
    readiness_markdown = _koray_readiness_snapshot(brief)
    blocks = [
        f"# FULL CONTENT BRIEF: {title_tag}",
        "",
        f"*Seed keyword: {topic}*",
        "",
        "## 1. Search Intent sâu thẳm của người dùng là gì",
        _deep_intent(brief, outline_items),
        "",
        "## 2. Nhiệm vụ của bài viết",
        _article_mission(brief, outline_items),
        "",
        "## 3. Khóa Vector Ngữ Cảnh (Contextual Vector Lock)",
        _vector_lock(brief),
        "",
        "## 4. Chiến lược lấp đầy lỗ hổng (Information Gain Mapping)",
        _info_gain_map(brief),
        "",
        "## 5. Sapo",
        _sapo(brief, outline_items),
        "",
        "## 6. Meta Description",
        _meta_description_notes(brief),
        "",
        "## 6.1 Schema định hướng",
        _schema_notes(brief),
        "",
        _render_outline(brief, outline_items),
        "",
    ]
    if readiness_markdown:
        blocks.extend([
            "## 8. Koray Readiness Snapshot",
            readiness_markdown,
            "",
        ])
    blocks.extend([
        "*Full Content Brief - Koray-style writer brief*",
    ])
    return "\n".join(blocks).strip() + "\n"


def _section_kind(heading_text: str, index: int, total: int) -> str:
    lower = _normalize_ascii(heading_text)
    if "faq" in lower or "cau hoi thuong gap" in lower:
        return "faq"
    if any(key in lower for key in ["so sanh", "bang danh gia", "giua cac", "don vi", "san giao dich"]):
        return "comparison"
    if any(key in lower for key in ["rui ro", "luu y", "sai lam", "canh bao"]):
        return "risk"
    if any(key in lower for key in ["thuoc tinh", "cau phan", "yeu to nao", "gom nhung", "dac diem"]):
        return "attribute"
    if any(key in lower for key in ["phan loai", "cac loai", "loai hinh", "nhom chinh", "nhung nhom"]):
        return "classification"
    if any(key in lower for key in ["khi nao", "phu hop", "nguon nuoc", "dieu kien", "boi canh ap dung", "ngu canh", "truong hop", "khong nen"]):
        return "condition"
    if any(key in lower for key in ["cach thuc hien", "lam the nao", "huong dan", "phan tich ky thuat", "cach tinh", "phuong phap", "co che", "hoat dong", "quy trinh"]):
        return "method"
    if any(key in lower for key in ["chi phi", "gia", "von", "tieu chi", "chon", "mua"]):
        return "decision"
    if any(key in lower for key in ["toi uu", "chien luoc", "tac dong", "anh huong", "ket qua", "loi ich"]):
        return "impact"
    if index == 0 or any(key in lower for key in ["la gi", "dinh nghia", "khai niem", "tong quan"]):
        return "definition"
    return "general"


def _section_focus_label(heading_text: str) -> str:
    text = _clean_text(heading_text)
    for prefix in [
        "Khái niệm ",
        "Các ",
        "Những ",
        "Cách ",
        "Bảng đánh giá ",
        "Phí Giao Dịch Hàng Hóa Phái Sinh: ",
    ]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text[:120] if text else _clean_text(heading_text)


def _body_requirements(brief: Dict, heading_text: str, kind: str, rows: List[Dict[str, str]], lsi: List[str], gaps: List[str], micro: Dict[str, Any]) -> str:
    micro_analysis = _clean_text(micro.get("analysis") or micro.get("body"))
    if micro_analysis:
        return micro_analysis

    focus = _section_focus_label(heading_text).lower()
    lsi_text = ", ".join(lsi[:4]) if lsi else ""
    row_text = "; ".join(f"{row['attribute']}: {row['value']}" for row in rows[:2])
    gap_text = ", ".join(gaps[:2])

    if kind == "definition":
        base = f"Mở section bằng nghĩa lõi của {focus}, xác định phạm vi áp dụng rồi chốt ranh giới với các khái niệm dễ bị nhầm."
        if row_text:
            base += f" Dùng các dữ kiện nền như {row_text} để khóa phạm vi nghĩa."
        if lsi_text:
            base += f" Có thể rải thêm các biến thể ngữ nghĩa như {lsi_text} nhưng không làm loãng thực thể trung tâm."
        return base
    if kind == "attribute":
        base = f"Tách {focus} thành từng nhóm thuộc tính hoặc cấu phần rõ ràng, chỉ ra nhóm nào là phần lõi và nhóm nào chỉ là điều kiện hỗ trợ."
        if row_text:
            base += f" Ưu tiên đối chiếu bằng các fact như {row_text}."
        if gap_text:
            base += f" Nếu cần mở rộng, nối thêm sang các ý như {gap_text}."
        return base
    if kind == "method":
        base = f"Đi từ cơ chế hoặc quy trình của {focus}, sau đó minh họa bằng bước thực hiện, ví dụ hoặc tình huống có thể đối chiếu trong thực tế."
        if gap_text:
            base += f" Hãy biến các gap như {gap_text} thành ví dụ có đầu vào, điều kiện và kết quả rõ ràng."
        if lsi_text:
            base += f" Rải đều các cụm hỗ trợ như {lsi_text} thay vì lặp exact-match."
        return base
    if kind == "risk":
        base = f"Làm rõ các điều kiện ẩn, sai lầm thường gặp và hậu quả thực tế xoay quanh {focus}, thay vì chỉ dừng ở mô tả bề mặt."
        if row_text:
            base += f" Có thể dùng các dữ kiện nền như {row_text} làm mốc đối chiếu."
        if gap_text:
            base += f" Ưu tiên đào sâu các điểm như {gap_text}."
        return base
    if kind == "impact":
        base = f"Chỉ ra {focus} làm thay đổi kết quả, mức độ phù hợp hoặc quyết định triển khai trong thực tế ra sao."
        if row_text:
            base += f" Neo lập luận vào các fact như {row_text} thay vì mô tả chung."
        if lsi_text:
            base += f" Các cụm hỗ trợ như {lsi_text} chỉ nên dùng để mở rộng semantic field, không thay trục chính."
        return base
    if kind == "comparison":
        base = f"Đặt các lựa chọn trong {focus} lên cùng một bộ tiêu chí cố định, rồi giải thích cách người đọc nên dùng từng tiêu chí để ra quyết định."
        if gap_text:
            base += f" Phần vượt đối thủ nên tập trung vào {gap_text}."
        if row_text:
            base += f" Nếu có fact đã xác minh, dùng chúng làm chuẩn đối chiếu như {row_text}."
        return base
    if kind == "faq":
        return "Trả lời ngắn, đi thẳng vào điều kiện áp dụng, giới hạn và hiểu nhầm phổ biến; nếu thiếu số liệu thật thì ưu tiên nghĩa lõi và ví dụ không gắn số bịa."
    return f"Triển khai {focus} theo đúng intent của heading, thêm fact đã xác minh và tránh lặp lại định nghĩa hoặc khung phân tích của section trước."


def _featured_snippet(brief: Dict, heading_text: str, kind: str, rows: List[Dict[str, str]], micro: Dict[str, Any]) -> str:
    verified_rows = _verified_rows(rows)
    topic = _topic(brief)
    micro_snippet = _clean_text(micro.get("snippet"))
    if micro_snippet:
        micro_norm = _normalize_ascii(micro_snippet)
        if (
            not micro_norm.startswith("cac h3 trong phan nay")
            and (not re.search(r"\d", micro_snippet) or _has_verified_numeric_fact(brief))
        ):
            return micro_snippet

    definition_fact = next(
        (_fact_text(row, prefer_value=True) for row in verified_rows if _normalize_ascii(str(row.get("attribute", ""))) in {"dinh nghia", "khai niem"}),
        "",
    )
    classification_fact = next(
        (_fact_text(row, prefer_value=True) for row in verified_rows if _normalize_ascii(str(row.get("attribute", ""))) == "phan loai"),
        "",
    )
    numeric_fact = _safe_numeric_fact(verified_rows)
    focus = _section_focus_label(heading_text).lower()

    if kind == "definition":
        if definition_fact:
            return definition_fact if definition_fact.endswith(".") else definition_fact + "."
        if classification_fact:
            return f"{topic} thường được hiểu rõ hơn khi tách theo {classification_fact.lower()}, từ đó mới xác định đúng phạm vi áp dụng."
        return f"{topic} nên được hiểu từ nghĩa lõi, phạm vi áp dụng và ranh giới với các khái niệm gần nghĩa trước khi đi sang các phần hỗ trợ."
    if kind == "attribute":
        if classification_fact:
            return f"{focus.capitalize()} nên được đọc theo từng nhóm cấu phần như {classification_fact.lower()}, rồi mới đối chiếu chi tiết trong thực tế."
        if numeric_fact:
            return f"{focus.capitalize()} cần được đối chiếu theo các thông số hoặc mốc áp dụng như {numeric_fact.lower()} thay vì chỉ nhìn một chỉ số đơn lẻ."
        return f"{focus.capitalize()} cần được tách theo từng nhóm thuộc tính để người đọc thấy rõ phần lõi và phần điều kiện hỗ trợ."
    if kind == "method":
        if numeric_fact:
            return f"{focus.capitalize()} cần được giải thích theo cơ chế, đơn vị áp dụng hoặc ví dụ thực tế, có thể đối chiếu bằng mốc như {numeric_fact.lower()}."
        opening = next((_fact_text(row, prefer_value=True) for row in verified_rows if _normalize_ascii(str(row.get("attribute_family", ""))) in {"process", "application"}), "")
        if opening:
            return opening if opening.endswith(".") else opening + "."
        return f"{focus.capitalize()} cần được giải thích bằng cơ chế, điều kiện áp dụng hoặc ví dụ thực tế thay vì chỉ mô tả khái quát."
    if kind == "risk":
        if numeric_fact:
            return f"Rủi ro hoặc điều kiện ẩn trong {focus} cần được đọc cùng các mốc áp dụng như {numeric_fact.lower()} để tránh đánh giá sai trong thực tế."
        return f"Rủi ro của {focus} thường nằm ở điều kiện ẩn, cách hiểu sai phạm vi áp dụng hoặc việc bỏ qua yếu tố làm thay đổi kết quả thực tế."
    if kind == "impact":
        return f"{focus.capitalize()} có thể làm thay đổi kết quả, mức độ phù hợp và quyết định triển khai trong thực tế, nên cần được giải thích theo hệ quả chứ không chỉ theo định nghĩa."
    if kind == "comparison":
        return f"So sánh {focus} chỉ có ý nghĩa khi các lựa chọn được đặt lên cùng bộ tiêu chí về phạm vi áp dụng, cấu phần và điều kiện phát sinh."
    if kind == "faq":
        return "FAQ cần trả lời nhanh các câu hỏi đuôi bằng câu trả lời trực diện, ngắn và bám đúng điều kiện áp dụng thực tế."
    opening = next((_fact_text(row, prefer_value=True) for row in verified_rows), "")
    if opening:
        return opening if opening.endswith(".") else opening + "."
    return f"{focus.capitalize()} cần được trả lời bằng một ý chính rõ ràng, bám đúng loại evidence của section và tránh lặp định nghĩa chung."


def _sapo(brief: Dict, outline_items: List[Dict[str, Any]]) -> str:
    topic = _topic(brief)
    verified_rows = _verified_rows(_parse_eav_rows(brief))
    definition = next(
        (
            _fact_text(row, prefer_value=True)
            for row in verified_rows
            if _normalize_ascii(str(row.get("attribute", ""))) in {"dinh nghia", "khai niem"}
        ),
        "",
    )
    classification = next(
        (
            _fact_text(row, prefer_value=True)
            for row in verified_rows
            if _normalize_ascii(str(row.get("attribute", ""))) == "phan loai"
        ),
        "",
    )
    numeric = _safe_numeric_fact(verified_rows)
    ordered_main = [
        _domain_safe_h2(brief, _rewrite_h2(item["text"], i), _section_kind(item["text"], i, len(outline_items)))
        for i, item in enumerate(outline_items)
        if _section_kind(item["text"], i, len(outline_items)) != "faq"
    ]

    parts: List[str] = []
    if definition:
        parts.append(definition if definition.endswith(".") else definition + ".")
    else:
        if classification:
            parts.append(f"{topic} thường được nhìn qua các nhóm hoặc cấu phần như {classification.lower()}, từ đó mới xác định đúng phạm vi áp dụng trong thực tế.")
        else:
            parts.append(f"{topic} cần được hiểu qua phạm vi áp dụng, cấu phần chính và các điều kiện làm thay đổi cách đọc thông tin trong thực tế.")
    if classification:
        parts.append(f"Trong thực tế, chủ đề này thường được tách theo các nhóm hoặc cấu phần như {classification.lower()}.")
    if numeric:
        parts.append(f"Nếu có dữ kiện xác minh, người đọc nên đối chiếu thêm các mốc áp dụng như {numeric.lower()}.")
    if ordered_main:
        parts.append("Từ nền tảng đó, bài viết lần lượt đi qua " + " -> ".join(ordered_main[:7]) + ".")
    parts.append("Mạch triển khai này giúp người đọc chuyển từ phần khái niệm sang tiêu chí đánh giá, điều kiện áp dụng và các lưu ý ra quyết định mà không bị lặp lại cùng một ý gốc.")
    return " ".join(parts).strip()


def _koray_readiness_snapshot(brief: Dict) -> str:
    report = brief.get("koray_outline_readiness", {}) if isinstance(brief.get("koray_outline_readiness", {}), dict) else {}
    if not report:
        return ""

    metrics = report.get("metrics", {}) if isinstance(report.get("metrics", {}), dict) else {}
    checks = report.get("checks", {}) if isinstance(report.get("checks", {}), dict) else {}
    blockers = [str(item).strip() for item in report.get("blockers", []) if str(item).strip()]
    recommendations = [str(item).strip() for item in report.get("recommendations", []) if str(item).strip()]

    verdict = _clean_text(report.get("verdict")) or "needs_tuning"
    verdict_label = {
        "ready": "READY",
        "needs_tuning": "NEEDS_TUNING",
        "not_ready": "NOT_READY",
    }.get(verdict, verdict.upper())
    icon = {"ready": "✅", "needs_tuning": "⚠️", "not_ready": "❌"}.get(verdict, "⚠️")

    ratio = metrics.get("h3_coverage_ratio")
    ratio_text = f"{int(float(ratio) * 100)}%" if isinstance(ratio, (int, float)) else "N/A"
    lines = [
        f"- Verdict: {icon} {verdict_label}",
        f"- Summary: {_clean_text(report.get('summary'))}",
        f"- Metrics: H2={metrics.get('h2_count', 0)}, MAIN={metrics.get('main_h2_count', 0)}, SUPP={metrics.get('supp_h2_count', 0)}, H3={metrics.get('h3_count', 0)}, H3 coverage={ratio_text}, Quality={metrics.get('quality_score', 'N/A')}",
    ]

    if checks:
        lines.append(
            "- Checks: "
            + ", ".join(
                f"{name}={'OK' if value else 'FAIL'}"
                for name, value in checks.items()
            )
        )
    if blockers:
        lines.append("- Blockers: " + "; ".join(blockers[:4]))
    if recommendations:
        lines.append("- Next actions: " + "; ".join(recommendations[:4]))
    return "\n".join(lines).strip()
