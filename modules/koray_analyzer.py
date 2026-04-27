# -*- coding: utf-8 -*-
"""
modules/koray_analyzer.py - Phase 33: 7 Koray SEO Columns (L→R).

Sinh nội dung cho 7 cột Koray Semantic SEO mới:
  L: Macro Context & Central Entity    (LLM)
  M: EAV Table                         (LLM)
  N: Attribute Filtration & Order      (LLM)
  O: FS/PAA Map                        (LLM)
  P: Main vs Supplementary Split       (rule-based)
  Q: Source Context Alignment          (rule-based)
  R: Koray Quality Score               (rule-based)
"""

import csv
import logging
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


AUDIT_CONTAMINATION_TERMS = []


def _normalize_plain_text(text: Any) -> str:
    """Lowercase + strip accents for robust matching."""
    if text is None:
        return ""
    raw = str(text).strip().lower()
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9\s]+", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _split_context_phrases(value: Any) -> List[str]:
    """Split context fields into a flat list of phrases."""
    if not value:
        return []
    text = str(value)
    chunks = re.split(r"[,;/\n|]+", text)
    result = []
    for chunk in chunks:
        cleaned = chunk.strip()
        if cleaned:
            result.append(cleaned)
    return result


def _collect_topic_terms(brief: Dict, project=None) -> List[str]:
    """Build a compact topic vocabulary for semantic checks."""
    raw_values: List[Any] = []
    if isinstance(brief, dict):
        raw_values.extend([
            brief.get("topic", ""),
            brief.get("central_entity", ""),
            brief.get("macro_context", ""),
            brief.get("search_intent", ""),
        ])
        content_gaps = brief.get("content_gaps", [])
        if isinstance(content_gaps, list):
            raw_values.extend(content_gaps)
        elif content_gaps:
            raw_values.append(content_gaps)
        eav = brief.get("eav_table", "")
        if eav:
            raw_values.append(eav)
    if project:
        raw_values.extend(_build_project_scope_terms(project))

    terms: List[str] = []
    for value in raw_values:
        terms.extend(_split_context_phrases(value))

    deduped: List[str] = []
    seen = set()
    for term in terms:
        norm = _normalize_plain_text(term)
        if not norm or len(norm) < 3:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(term.strip())
    return deduped[:40]


def _semantic_reasoning_payload(brief: Dict) -> Dict[str, Any]:
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
        "dominant_user_task": str(data.get("dominant_user_task", "")).strip(),
        "supporting_tasks": [str(x).strip() for x in data.get("supporting_tasks", []) if str(x).strip()],
        "decision_blockers": [str(x).strip() for x in data.get("decision_blockers", []) if str(x).strip()],
        "misinterpretation_risks": [str(x).strip() for x in data.get("misinterpretation_risks", []) if str(x).strip()],
        "consensus_facts": [str(x).strip() for x in data.get("consensus_facts", []) if str(x).strip()],
        "gap_map": {
            "h2_worthy": [str(x).strip() for x in gap_map.get("h2_worthy", []) if str(x).strip()],
            "supporting_detail": [str(x).strip() for x in gap_map.get("supporting_detail", []) if str(x).strip()],
            "topical_expansion": [str(x).strip() for x in gap_map.get("topical_expansion", []) if str(x).strip()],
            "noise": [str(x).strip() for x in gap_map.get("noise", []) if str(x).strip()],
        },
        "section_evidence_plan": data.get("section_evidence_plan") if isinstance(data.get("section_evidence_plan"), dict) else {},
        "verified_eav_rows": [row for row in data.get("verified_eav_rows", []) if isinstance(row, dict)],
        "eav_quality": data.get("eav_quality") if isinstance(data.get("eav_quality"), dict) else {},
        "semantic_terms_curated": [str(x).strip() for x in data.get("semantic_terms_curated", []) if str(x).strip()],
        "preferred_flow": [str(x).strip() for x in data.get("preferred_flow", []) if str(x).strip()],
    }


def _heading_kind(text: str) -> str:
    norm = _normalize_plain_text(text)
    if ":" in norm:
        suffix = norm.split(":", 1)[1].strip()
        if len(suffix.split()) >= 2:
            norm = suffix
    if any(sig in norm for sig in ["dinh nghia", "khai niem", "phan loai", "la gi"]):
        return "definition"
    if any(sig in norm for sig in ["faq", "cau hoi"]):
        return "faq"
    if any(sig in norm for sig in ["so sanh", "khac nhau", "vs", "danh gia"]):
        return "comparison"
    if any(sig in norm for sig in ["dac diem", "thanh phan", "cau truc", "yeu to", "cac loai", "loai hinh"]):
        return "attribute"
    if any(sig in norm for sig in ["rui ro", "luu y", "sai lam", "canh bao"]):
        return "risk"
    if any(sig in norm for sig in ["chien luoc", "loi ich", "ung dung", "phu hop", "tac dong", "anh huong"]):
        return "impact"
    if any(sig in norm for sig in ["co che", "quy trinh", "cach", "thoi gian", "dieu kien"]):
        return "calculation"
    if "khong nen" in norm:
        return "risk"
    return "attribute"


def _flow_item_expected_kinds(item: str) -> List[str]:
    norm = _normalize_plain_text(item)
    expected: List[str] = []
    if any(sig in norm for sig in ["definition", "clarification", "dinh nghia", "khai niem", "scope"]):
        expected.append("definition")
    if any(sig in norm for sig in ["attribute", "forms", "structure", "classification", "market", "thuoc tinh", "phan loai"]):
        expected.append("attribute")
    if any(sig in norm for sig in ["process", "how it works", "conditions", "steps", "co che", "quy trinh", "dieu kien"]):
        expected.append("calculation")
    if any(sig in norm for sig in ["comparison", "difference", "trade off", "evaluation", "so sanh", "khac biet"]):
        expected.append("comparison")
    if any(sig in norm for sig in ["application", "benefit", "impact", "fit", "chien luoc", "loi ich", "ung dung"]):
        expected.append("impact")
    if any(sig in norm for sig in ["risk", "caution", "warning", "luu y", "rui ro", "canh bao"]):
        expected.append("risk")
    if any(sig in norm for sig in ["faq", "support", "cau hoi"]):
        expected.append("faq")
    if not expected:
        expected.append("attribute")
    return expected


def generate_outline_readiness_report(brief: Dict, headings: List[Dict], project=None) -> Dict[str, Any]:
    """Summarize whether the current brief is structurally ready for a Koray-style article draft."""
    reasoning = _semantic_reasoning_payload(brief)
    h2_texts = [str(h.get("text", "")).strip() for h in headings if isinstance(h, dict) and h.get("level") == "H2" and str(h.get("text", "")).strip()]
    h2_norms = [_normalize_plain_text(text) for text in h2_texts]
    main_h2 = [text for text in h2_texts if "[MAIN]" in text.upper()]
    supp_h2 = [text for text in h2_texts if "[SUPP]" in text.upper()]

    h2_with_h3 = 0
    total_h3 = 0
    current_h2_open = False
    for item in headings:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "")).upper()
        if level == "H2":
            current_h2_open = True
        elif level == "H3":
            total_h3 += 1
            if current_h2_open:
                h2_with_h3 += 1
                current_h2_open = False
    main_h2_count = len(main_h2)
    h3_coverage_ratio = (h2_with_h3 / len(h2_texts)) if h2_texts else 0.0

    query_terms = _collect_topic_terms(brief, project)
    query_norm_terms = [_normalize_plain_text(term) for term in query_terms if _normalize_plain_text(term)]
    first_h2_norm = h2_norms[0] if h2_norms else ""
    first_h2_definition_like = any(token in first_h2_norm for token in ["la gi", "dinh nghia", "khai niem", "tong quan"])
    first_h2_query_overlap = any(term and len(term) >= 4 and term in first_h2_norm for term in query_norm_terms[:8])
    first_h2_ok = bool(first_h2_norm) and (first_h2_definition_like or first_h2_query_overlap)

    preferred_flow = [_normalize_plain_text(x) for x in reasoning.get("preferred_flow", []) if str(x).strip()]
    main_h2_norms = [_normalize_plain_text(text) for text in h2_texts if "[SUPP]" not in str(text).upper()]
    actual_flow_kinds = [
        _heading_kind(text)
        for text in h2_texts
        if "[SUPP]" not in str(text).upper()
    ]
    flow_hits = 0
    cursor = 0
    for flow_item in preferred_flow:
        expected_kinds = _flow_item_expected_kinds(flow_item)
        flow_tokens = [token for token in flow_item.split() if len(token) >= 4]
        probe = cursor
        while probe < len(actual_flow_kinds):
            lexical_match = flow_tokens and any(token in main_h2_norms[min(probe, len(main_h2_norms) - 1)] for token in flow_tokens)
            if actual_flow_kinds[probe] in expected_kinds or lexical_match:
                flow_hits += 1
                cursor = probe + 1
                break
            probe += 1
    preferred_flow_ratio = (flow_hits / len(preferred_flow)) if preferred_flow else 1.0

    micro = brief.get("micro_briefing", [])
    if isinstance(micro, dict):
        micro = micro.get("items", []) if "items" in micro else list(micro.values())
    placeholder_sections = 0
    main_micro_sections = 0
    if isinstance(micro, list):
        for item in micro:
            if not isinstance(item, dict):
                continue
            h2 = str(item.get("h2", "")).upper()
            if "[MAIN]" not in h2:
                continue
            main_micro_sections += 1
            joined = " ".join(
                str(item.get(field, ""))
                for field in ["analysis", "info_gain", "bridge", "transition", "guidance"]
            )
            if any(marker in _normalize_plain_text(joined) for marker in [
                "section nay", "theo semantic seo", "content gaps", "topical border", "phan nay se"
            ]):
                placeholder_sections += 1
    placeholder_ratio = (placeholder_sections / main_micro_sections) if main_micro_sections else 0.0

    per_h2 = brief.get("contextual_structure_v4", {}) if isinstance(brief.get("contextual_structure_v4", {}), dict) else {}
    per_h2_map = per_h2.get("per_h2", {}) if isinstance(per_h2, dict) else {}
    has_per_h2 = bool(per_h2_map)

    quality_text = str(brief.get("koray_quality_score_md") or brief.get("koray_quality_score") or "")
    match = re.search(r"(\d{1,3})/100", quality_text)
    quality_score = int(match.group(1)) if match else None

    checks = [
        ("first_h2", first_h2_ok),
        ("main_supp_split", bool(main_h2 and supp_h2)),
        ("h3_coverage", h3_coverage_ratio >= 0.5 and total_h3 >= max(1, len(h2_texts) // 2)),
        ("preferred_flow", preferred_flow_ratio >= 0.5),
        ("per_h2_guidance", has_per_h2),
        ("micro_specificity", placeholder_ratio <= 0.2),
    ]
    passed = sum(1 for _, ok in checks if ok)

    blockers: List[str] = []
    recommendations: List[str] = []
    if not first_h2_ok:
        blockers.append("H2 đầu chưa trả lời trực diện search intent hoặc primary definitional query.")
        recommendations.append("Đưa định nghĩa hoặc primary question lên H2#1 theo đúng mindshare model.")
    if not supp_h2:
        blockers.append("Thiếu [SUPP] section để chốt FAQ / CTA / closing bridge.")
        recommendations.append("Bổ sung ít nhất 1 [SUPP] section cuối bài.")
    if h3_coverage_ratio < 0.5:
        blockers.append("Contextual hierarchy còn nông: dưới 50% H2 có H3 thật sự.")
        recommendations.append("Tăng H3 cho các H2 MAIN, ưu tiên bám PAA và derived attributes từ EAV.")
    if preferred_flow and preferred_flow_ratio < 0.5:
        blockers.append("Outline mới chỉ bám yếu preferred_flow từ semantic reasoning.")
        recommendations.append("Reorder H2 theo flow intent: định nghĩa -> thuộc tính -> ứng dụng/so sánh -> cảnh báo/FAQ.")
    if placeholder_ratio > 0.2:
        blockers.append("Writer brief còn placeholder/generic text ở nhiều section.")
        recommendations.append("Chuẩn hóa analysis / info_gain / bridge theo từng H2 thay vì dùng template lặp.")
    if not has_per_h2:
        blockers.append("Thiếu per-H2 contextual instructions cho writer.")
        recommendations.append("Sinh lại contextual_structure_v4 trước khi export brief.")
    if quality_score is not None and quality_score < 75:
        blockers.append(f"Koray quality score hiện chỉ ở mức {quality_score}/100.")
        recommendations.append("Chưa nên publish; cần sửa structure và writer brief trước.")

    if passed == len(checks) and (quality_score is None or quality_score >= 80):
        verdict = "ready"
    elif passed >= max(4, len(checks) - 1) and (quality_score is None or quality_score >= 65):
        verdict = "needs_tuning"
    else:
        verdict = "not_ready"

    return {
        "verdict": verdict,
        "summary": (
            "Outline đã đủ nền tảng Koray để triển khai bài viết."
            if verdict == "ready"
            else (
                "Outline đã có trục semantic đúng nhưng vẫn cần tinh chỉnh trước khi giao writer."
                if verdict == "needs_tuning"
                else "Outline hiện chưa đạt mức sẵn sàng để triển khai theo chuẩn Koray."
            )
        ),
        "metrics": {
            "h2_count": len(h2_texts),
            "main_h2_count": main_h2_count,
            "supp_h2_count": len(supp_h2),
            "h3_count": total_h3,
            "h2_with_h3": h2_with_h3,
            "h3_coverage_ratio": round(h3_coverage_ratio, 2),
            "preferred_flow_hits": flow_hits,
            "preferred_flow_total": len(preferred_flow),
            "placeholder_ratio": round(placeholder_ratio, 2),
            "quality_score": quality_score,
        },
        "checks": {name: ok for name, ok in checks},
        "blockers": blockers,
        "recommendations": recommendations[:6],
    }


def _snippet_semantically_valid(snippet: str, topic_terms: List[str], heading_terms: List[str] = None) -> bool:
    """Return True when a snippet has topical signal and is not a placeholder template."""
    if not snippet:
        return False
    raw = str(snippet).strip()
    if not raw:
        return False
    norm = _normalize_plain_text(raw)
    if not norm:
        return False

    placeholder_markers = [
        "can xac minh",
        "khong co thuoc tinh",
        "chu de nay",
        "khoi thong tin can mo ta",
        "can duoc trinh bay",
        "theo tung buoc",
        "bai viet nay se",
        "duoc dien giai ngan gon",
    ]
    if any(marker in norm for marker in placeholder_markers):
        return False

    word_count = len(raw.split())
    if not (10 <= word_count <= 40):
        return False

    candidates = []
    for term in (heading_terms or []) + (topic_terms or []):
        term_norm = _normalize_plain_text(term)
        if term_norm and len(term_norm) >= 3:
            candidates.append(term_norm)
    candidates = list(dict.fromkeys(candidates))

    hit_count = sum(1 for term in candidates if term in norm)
    if hit_count >= 2:
        return True

    generic_templates = [
        "la khoi thong tin",
        "can duoc hieu theo dung ngu canh",
        "thuong duoc xac dinh",
        "can duoc doi chieu",
        "can duoc dien giai",
    ]
    if any(template in norm for template in generic_templates):
        return False

    # Allow one topical hit only if snippet also contains a concrete quantitative cue.
    if hit_count == 1 and re.search(r"\d|%|vnd|usd|usd|m\d|kg|mm|mpa", norm):
        return True

    return False


def _count_meaningful_eav_rows(eav_table_md: str, entity_attrs: Any = None) -> tuple[int, int]:
    """Count meaningful EAV rows vs placeholder rows."""
    real_rows = 0
    placeholder_rows = 0

    def _row_is_placeholder(parts: List[str]) -> bool:
        joined = " ".join(parts).lower()
        if not joined.strip():
            return True
        placeholder_signals = [
            "[can xac minh]",
            "khong co thuoc tinh",
            "root_attributes",
            "rare_attributes",
            "unique_attributes",
            "n/a",
            "placeholder",
        ]
        return any(sig in joined for sig in placeholder_signals)

    if eav_table_md and len(str(eav_table_md).strip()) > 10:
        for line in str(eav_table_md).splitlines():
            line = line.strip()
            if not line.startswith("|") or "---" in line:
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) < 3:
                continue
            if parts[0].lower() == "entity" and parts[1].lower() == "attribute":
                continue
            if _row_is_placeholder(parts):
                placeholder_rows += 1
            else:
                real_rows += 1
    elif isinstance(entity_attrs, dict):
        for key, value in entity_attrs.items():
            key_norm = _normalize_plain_text(key)
            val_norm = _normalize_plain_text(value)
            if not key_norm and not val_norm:
                continue
            if key_norm in {"root_attributes", "rare_attributes", "unique_attributes"}:
                placeholder_rows += 1
                continue
            if val_norm.startswith("khong co thuoc tinh") or val_norm.startswith("[can xac minh]"):
                placeholder_rows += 1
                continue
            real_rows += 1
    return real_rows, placeholder_rows


def _verified_eav_quality(brief: Dict, reasoning: Dict[str, Any]) -> Dict[str, Any]:
    quality = reasoning.get("eav_quality", {}) if isinstance(reasoning.get("eav_quality"), dict) else {}
    if quality:
        return quality
    rows = [row for row in brief.get("eav_table_rows", []) if isinstance(row, dict) and row.get("is_verified")]
    families = {
        _normalize_plain_text(row.get("attribute_family", ""))
        for row in rows
        if _normalize_plain_text(row.get("attribute_family", ""))
    }
    blocked = [
        f"{row.get('attribute', '')}: {row.get('value', '')}"
        for row in (brief.get("eav_table_rows", []) or [])
        if isinstance(row, dict) and row.get("is_numeric") and not row.get("is_verified")
    ]
    return {
        "verified_rows": len(rows),
        "attribute_families": len(families),
        "coverage_status": "strong" if len(rows) >= 5 and len(families) >= 3 else ("medium" if len(rows) >= 3 and len(families) >= 2 else "weak"),
        "blocked_numeric_rows": blocked,
    }


def _anchor_plan_stats(reasoning: Dict[str, Any]) -> Dict[str, Any]:
    section_plan = reasoning.get("section_evidence_plan", {}) if isinstance(reasoning.get("section_evidence_plan"), dict) else {}
    per_heading = section_plan.get("per_heading", {}) if isinstance(section_plan.get("per_heading"), dict) else {}
    anchors: List[str] = []
    low_distance = 0
    total = 0
    for meta in per_heading.values():
        if not isinstance(meta, dict):
            continue
        for item in meta.get("anchor_plan", []) or []:
            if not isinstance(item, dict):
                continue
            anchor_text = _normalize_plain_text(item.get("anchor_text", ""))
            if anchor_text:
                anchors.append(anchor_text)
            if float(item.get("semantic_distance_score", 0.0) or 0.0) < 0.18:
                low_distance += 1
            total += 1
    if not anchors:
        return {"reuse_ratio": 1.0, "low_distance": 0, "total": 0}
    distinct = len(set(anchors))
    reuse_ratio = 1 - (distinct / max(1, len(anchors)))
    return {"reuse_ratio": reuse_ratio, "low_distance": low_distance, "total": total}


def _guidance_specificity_score(micro: List[Dict], topic_terms: List[str]) -> float:
    """Return a 0..1 score based on how specific per-H2 guidance is."""
    if not micro:
        return 0.0

    topic_norm_terms = [_normalize_plain_text(t) for t in topic_terms if _normalize_plain_text(t)]
    topic_norm_terms = [t for t in topic_norm_terms if len(t) >= 4]
    if not topic_norm_terms:
        topic_norm_terms = []

    specific_count = 0
    distinct_fingerprints = set()
    total = 0

    generic_markers = [
        "viet 80 150 tu",
        "bat dau bang cau tra loi truc tiep",
        "co so lieu ky thuat cu the",
        "phan nay mo rong them cac thuoc tinh",
        "tiep theo la phan",
        "co the ap dung",
    ]

    for item in micro:
        if not isinstance(item, dict):
            continue
        h2_text = str(item.get("h2", "")).strip()
        if not h2_text or "[MAIN]" not in h2_text.upper():
            continue

        total += 1
        pieces = [
            item.get("content_format", ""),
            item.get("first_sentence", ""),
            item.get("micro_terms", ""),
            item.get("sentence_before", ""),
            item.get("preceding_question", ""),
            item.get("contextual_bridge", ""),
            item.get("analysis", ""),
            item.get("info_gain", ""),
            item.get("transition", ""),
        ]
        guidance_text = _normalize_plain_text(" ".join(str(p) for p in pieces if p))
        if not guidance_text:
            continue

        fingerprint = re.sub(r"\s+", " ", guidance_text[:240]).strip()
        distinct_fingerprints.add(fingerprint)

        h2_terms = [
            t for t in _normalize_plain_text(h2_text).split()
            if len(t) >= 4 and t not in {"main", "supp", "h2", "h3"}
        ]
        h2_hits = sum(1 for term in h2_terms[:6] if term in guidance_text)
        generic_hits = sum(1 for marker in generic_markers if marker in guidance_text)
        has_structure = bool(item.get("content_format")) and bool(item.get("first_sentence"))
        has_terms = bool(item.get("micro_terms"))
        if has_structure and has_terms and h2_hits >= 1 and generic_hits <= 2:
            specific_count += 1

    if total == 0:
        return 0.0
    diversity_ratio = len(distinct_fingerprints) / total if total else 0.0
    specificity_ratio = specific_count / total
    return min(1.0, (0.6 * specificity_ratio) + (0.4 * diversity_ratio))

def _load_topical_map_terms(topical_map_csv: str, limit: int = 80) -> List[str]:
    """Load first-column topics from topical map CSV."""
    if not topical_map_csv or not os.path.exists(topical_map_csv):
        return []

    terms: List[str] = []
    try:
        with open(topical_map_csv, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            _ = next(reader, None)
            for row in reader:
                if row and row[0].strip():
                    terms.append(row[0].strip())
                if len(terms) >= limit:
                    break
    except Exception as exc:
        logger.warning("  [AUDIT] Cannot read topical map CSV '%s': %s", topical_map_csv, exc)
    return terms


def _build_project_scope_terms(project) -> List[str]:
    """Build a project vocabulary from source context and topical map."""
    if not project:
        return []

    raw_fields = [
        getattr(project, "brand_name", ""),
        getattr(project, "industry", ""),
        getattr(project, "main_products", ""),
        getattr(project, "target_customers", ""),
        getattr(project, "usp", ""),
        getattr(project, "technical_standards", ""),
        getattr(project, "geo_keywords", ""),
        getattr(project, "competitor_brands", ""),
    ]
    terms: List[str] = []
    for field in raw_fields:
        terms.extend(_split_context_phrases(field))
    terms.extend(_load_topical_map_terms(getattr(project, "topical_map_csv", "") or ""))

    deduped: List[str] = []
    seen = set()
    for term in terms:
        norm = _normalize_plain_text(term)
        if not norm or len(norm) < 3:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        deduped.append(term.strip())
    return deduped


def _find_matching_terms(text: str, terms: List[str]) -> List[str]:
    """Return source-context terms that appear in text."""
    normalized = _normalize_plain_text(text)
    if not normalized:
        return []
    matches = []
    for term in terms:
        norm_term = _normalize_plain_text(term)
        if norm_term and norm_term in normalized:
            matches.append(term)
    return matches[:8]


def _find_contamination_terms(text: str) -> List[str]:
    """Detect obvious cross-domain contamination terms."""
    normalized = _normalize_plain_text(text)
    if not normalized:
        return []
    hits = [term for term in AUDIT_CONTAMINATION_TERMS if term in normalized]
    return hits[:8]


def _stringify_audit_source(value: Any, limit: int = 1200) -> str:
    """Flatten dict/list/string values into audit-friendly text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        chunks = []
        for key in ["clusters", "outbound_nodes", "people_also_ask", "related_searches", "rare_headings"]:
            if key in value:
                chunks.append(f"{key}: {value.get(key)}")
        if not chunks:
            chunks.append(str(value))
        return " | ".join(chunks)[:limit]
    if isinstance(value, list):
        return " | ".join(str(v) for v in value[:20])[:limit]
    return str(value)[:limit]


# ══════════════════════════════════════════════
#  RULE-BASED FUNCTIONS (luôn chạy, không cần LLM)
# ══════════════════════════════════════════════

def extract_main_supp_split(headings: List[Dict]) -> str:
    """
    Phân tích heading_structure, tách ra [MAIN] và [SUPP] sections.
    Detect dựa trên prefix '[MAIN]' và '[SUPP]' do Agent1 đánh dấu.

    Args:
        headings: List of {"level": "H2"|"H3", "text": "..."}

    Returns:
        Markdown text với 2 section rõ ràng.
    """
    main_list = []
    supp_list = []

    for h in headings:
        text = h.get("text", "")
        level = h.get("level", "H2")
        if "[MAIN]" in text:
            clean = text.replace("[MAIN]", "").strip()
            main_list.append(f"- **{level}**: {clean}")
        elif "[SUPP]" in text:
            clean = text.replace("[SUPP]", "").strip()
            supp_list.append(f"- **{level}**: {clean}")
        else:
            # Không có prefix → phân loại theo vị trí (trước/sau SUPP)
            if supp_list:
                supp_list.append(f"- **{level}**: {text}")
            else:
                main_list.append(f"- **{level}**: {text}")

    lines = ["## 📦 MAIN CONTENT\n"]
    if main_list:
        lines.extend(main_list)
    else:
        lines.append("_(Không phát hiện [MAIN] heading)_")

    lines.append("\n\n## 🔗 SUPPLEMENT CONTENT\n")
    if supp_list:
        lines.extend(supp_list)
    else:
        lines.append("_(Không phát hiện [SUPP] heading)_")

    # Bug 2 fix: Đếm riêng H2 và tổng headings
    main_h2 = sum(1 for h in main_list if "**H2**" in h)
    supp_h2 = sum(1 for h in supp_list if "**H2**" in h)
    main_count = len(main_list)
    supp_count = len(supp_list)
    total = main_count + supp_count
    supp_pct = round(supp_count / total * 100) if total > 0 else 0

    lines.append(f"\n\n**Tỉ lệ:** Main={main_h2} H2 ({main_count} headings) | Supp={supp_h2} H2 ({supp_count} headings) — {supp_pct}% supplement")
    if supp_pct < 20:
        lines.append("⚠️ CẢNH BÁO: Supplement Content < 20%. Xem xét thêm [SUPP] headings.")
    elif supp_pct > 35:
        lines.append("⚠️ CẢNH BÁO: Supplement Content > 35%. Có thể quá nhiều.")
    else:
        lines.append("✅ Tỉ lệ Main/Supp đạt chuẩn (20-35% Supp).")

    return "\n".join(lines)


def generate_source_context_alignment(brief: Dict, project=None) -> str:
    """
    Auto-check xem brief có align với Source Context không.
    Kiểm tra: brand mention, GEO keywords, CTA, NAP, Schema.

    Returns:
        Checklist ✅/❌ markdown.
    """
    lines = ["## 🎯 SOURCE CONTEXT ALIGNMENT CHECKLIST\n"]

    if not project:
        lines.append("_(Không có Project/Source Context để kiểm tra)_")
        return "\n".join(lines)

    # Tổng hợp toàn bộ text để kiểm tra
    all_text = ""
    headings = brief.get("heading_structure", [])
    for h in headings:
        all_text += " " + h.get("text", "")
    micro_briefings = brief.get("micro_briefing", [])
    for mb in micro_briefings:
        if isinstance(mb, dict):
            all_text += " " + str(mb.get("snippet", ""))
            all_text += " " + str(mb.get("bridge", ""))
    all_text = all_text.lower()
    scope_terms = _build_project_scope_terms(project)
    scope_preview = ", ".join(scope_terms[:8]) if scope_terms else "N/A"
    topical_hits = _find_matching_terms(all_text, scope_terms)
    contamination_hits = _find_contamination_terms(all_text)

    if scope_terms:
        lines.append(f"✅ **Topical Scope**: {scope_preview}")
        if contamination_hits:
            lines.append(f"⚠️ **Topical Border**: phát hiện lệch ngành {', '.join(contamination_hits)}")
        elif topical_hits:
            lines.append(f"✅ **Topical Border**: {', '.join(topical_hits[:3])}")
        else:
            lines.append("⚠️ **Topical Border**: chưa thấy vocabulary đủ rõ của project")
    else:
        lines.append("⚠️ **Topical Scope**: Không có topical map/source vocabulary để đối chiếu")

    # 1. Brand mention
    brand_lower = project.brand_name.lower()
    brand_ok = brand_lower in all_text
    lines.append(f"{'✅' if brand_ok else '❌'} **Brand mention**: '{project.brand_name}' {'có' if brand_ok else 'KHÔNG'} xuất hiện trong brief")

    # 2. GEO Keywords
    geo_keywords = [g.strip().lower() for g in (project.geo_keywords or "").split(",") if g.strip()]
    geo_found = any(geo in all_text for geo in geo_keywords) if geo_keywords else False
    lines.append(f"{'✅' if geo_found else '⚠️'} **GEO Keywords**: {'Tìm thấy' if geo_found else 'KHÔNG tìm thấy'} ({', '.join(project.geo_keywords.split(',')[:3]) if project.geo_keywords else 'N/A'})")

    # 3. SUPP section có NAP
    has_supp = any("[SUPP]" in h.get("text", "") for h in headings)
    lines.append(f"{'✅' if has_supp else '⚠️'} **Supplement Section**: {'Có [SUPP] heading' if has_supp else 'KHÔNG tìm thấy [SUPP] heading (cần có NAP ở Supp)'}")

    # 4. Hotline/Contact
    hotline_clean = re.sub(r'\D', '', project.hotline or "")
    hotline_found = hotline_clean in re.sub(r'\D', '', all_text) if hotline_clean else False
    lines.append(f"{'✅' if hotline_found else '⚠️'} **NAP Hotline**: {'Có' if hotline_found else 'KHÔNG'} tìm thấy hotline '{project.hotline}' trong brief")

    # 5. Competitor brands không xuất hiện dạng H2 độc lập
    competitor_brands_raw = project.competitor_brands or ""
    comp_list = [c.strip().lower() for c in competitor_brands_raw.split(",") if c.strip()]
    h2_texts = [h.get("text", "").lower() for h in headings if h.get("level") == "H2"]
    competitor_violation = any(
        any(comp in h2 for comp in comp_list)
        for h2 in h2_texts
    )
    lines.append(f"{'✅' if not competitor_violation else '❌'} **Competitor Brand Rule**: {'Không vi phạm' if not competitor_violation else 'VI PHẠM — brand đối thủ xuất hiện dạng H2 độc lập!'}")

    # Tổng điểm
    checks = [brand_ok, geo_found, has_supp, not competitor_violation]
    score = sum(checks)
    lines.append(f"\n**Điểm Alignment: {score}/{len(checks)}** ({'Tốt' if score >= 3 else 'Cần cải thiện'})")

    return "\n".join(lines)


# ── Phase 36: CONSTANTS for quality scoring ───────────────────────────────────
# Structural cap: điểm tối đa dựa trên số lượng H2 thực tế
# < 3 H2 → yếu, 3 H2 → OK, 4 H2 → tốt, ≥5 H2 → không bị cap
STRUCTURAL_CAPS = {
    0: 0, 1: 10, 2: 25, 3: 60, 4: 80, 5: 100
}


def calculate_quality_score(brief: Dict, headings: List[Dict], project=None) -> str:
    """
    Tính điểm Koray Quality /100 dựa trên 10 tiêu chí rule-based.

    Returns:
        Bảng markdown điểm + danh sách lỗi phát hiện.
    """
    scores = {}
    issues = []
    strict_penalties = 0
    topic_terms = _collect_topic_terms(brief, project)
    reasoning = _semantic_reasoning_payload(brief)
    preferred_flow = [_normalize_plain_text(x) for x in reasoning.get("preferred_flow", []) if str(x).strip()]
    content_gap_terms = _split_context_phrases(brief.get("content_gaps", []))
    if not content_gap_terms:
        content_gap_terms = _split_context_phrases(brief.get("semantic_query_network", ""))

    # 1. Contextual Vector — reward SPECIFIC headings, not penalize generic
    h2_texts = [h.get("text", "") for h in headings if h.get("level") == "H2"]
    h2_count = len(h2_texts)
    h2_norms = [_normalize_plain_text(h) for h in h2_texts]

    if preferred_flow and h2_norms:
        flow_hits = 0
        pointer = 0
        main_h2_norms = [_normalize_plain_text(h) for h in h2_texts if "[SUPP]" not in str(h).upper()]
        main_h2_kinds = [_heading_kind(h) for h in h2_texts if "[SUPP]" not in str(h).upper()]
        for flow_item in preferred_flow:
            flow_tokens = [tok for tok in flow_item.split() if len(tok) >= 4]
            expected_kinds = _flow_item_expected_kinds(flow_item)
            probe = pointer
            while probe < len(main_h2_norms):
                lexical_match = flow_tokens and any(tok in main_h2_norms[probe] for tok in flow_tokens)
                if main_h2_kinds[probe] in expected_kinds or lexical_match:
                    flow_hits += 1
                    pointer = probe + 1
                    break
                probe += 1
        if flow_hits == 0:
            issues.append("⚠️ Outline chưa phản ánh preferred_flow từ semantic_reasoning.")
            strict_penalties += 4
        elif flow_hits < max(1, min(len(preferred_flow), h2_count) // 2):
            issues.append(f"⚠️ Outline chỉ bám yếu preferred_flow ({flow_hits}/{len(preferred_flow)} tín hiệu).")
            strict_penalties += 2

    # Pattern càng specific → điểm càng cao
    specific_patterns = [
        # Question-based (Koray Mindshare Model start)
        "là gì", "như thế nào", "bao nhiêu", "tại sao", "vì sao",
        # Comparison/contrast
        "so sánh", "khác nhau", "ưu nhược", "giống nhau",
        # Technical specs (strong E-E-A-T signal)
        "mm", "kg", "m2", "mét", "cm", "inch", "mm2", "kg/m",
        # Commercial intent
        "giá", "bảng giá", "báo giá", "chi phí", "mua", "bán", "cách chọn",
        # Koray Mindshare Model action words
        "quy trình", "cách làm", "cách phân biệt", "phân loại", "so sánh",
    ]

    if h2_count < 3:
        s1 = 0
        issues.append(f"❌ Cấu trúc thiếu H2 nghiêm trọng ({h2_count} H2). Cần tối thiểu 3 H2.")
    else:
        specific_h2s = 0
        aligned_h2s = 0
        for h in h2_texts:
            h_norm = _normalize_plain_text(h)
            pattern_hits = sum(1 for p in specific_patterns if p in h_norm)
            if pattern_hits >= 2:
                specific_h2s += 1
            topical_hits = 0
            for term in topic_terms[:20]:
                term_norm = _normalize_plain_text(term)
                if term_norm and term_norm in h_norm and len(term_norm) >= 4:
                    topical_hits += 1
            for gap in content_gap_terms[:12]:
                gap_norm = _normalize_plain_text(gap)
                if gap_norm and gap_norm in h_norm and len(gap_norm) >= 4:
                    topical_hits += 1
            if topical_hits >= 1:
                aligned_h2s += 1
        # Koray G4 Heading Harmony: detect pattern mixing at same H2 level
        # Pattern A (Question): ends with '?' or contains "như thế nào", "bao nhiêu", "la gi", "lam sao"
        # Pattern B (Noun phrase): "cua X", "cua X", "X va Y" — no question mark
        # Pattern C (Verb phrase): "cach X", "quy trinh X", "huong dan X"
        harmony_violations = 0
        main_h2s = [h for h in h2_texts if "[MAIN]" in h]
        if len(main_h2s) >= 2:
            for i in range(len(main_h2s) - 1):
                h_curr = main_h2s[i]
                h_next = main_h2s[i + 1]
                h_curr_clean = h_curr.replace("[MAIN]", "").replace("[SUPP]", "").strip()
                h_next_clean = h_next.replace("[MAIN]", "").replace("[SUPP]", "").strip()
                # Pattern A: ends with ? or contains question keyword
                is_question = lambda t: (t.endswith("?") or
                    any(kw in t.lower() for kw in ["như thế nào", "bao nhiêu", "là gì", "là sao", "có gì", "ra sao"]))
                is_noun_phrase = lambda t: (not is_question(t) and
                    not any(t.lower().startswith(p) for p in ["cách ", "cách ", "quy trình ", "hướng dẫn ", "so sánh ", "phân loại ", "chọn "]))

                curr_is_q = is_question(h_curr_clean)
                next_is_q = is_question(h_next_clean)
                curr_is_n = is_noun_phrase(h_curr_clean)
                next_is_n = is_noun_phrase(h_next_clean)

                # Violation: Question followed by Noun phrase (or vice versa) at same level
                if (curr_is_q and next_is_n) or (curr_is_n and next_is_q):
                    harmony_violations += 1
        if harmony_violations > 0:
            issues.append(f"⚠️ Koray G4 VIOLATION: {harmony_violations} Heading Harmony mixing (Question ↔ Noun phrase) — gây Contextual Dilution. Nên giữ 1 pattern cho cùng level.")
            strict_penalties += harmony_violations * 3

        # Reward specificity first, then topical alignment with gaps/terms.
        s1 = min(10, (specific_h2s * 3) + min(3, aligned_h2s))
        if specific_h2s == 0:
            if aligned_h2s > 0:
                issues.append("⚠️ Heading có topical alignment nhưng vẫn thiếu specificity rõ ràng.")
            else:
                issues.append("❌ Không có heading nào đủ specific (Koray Mindshare Model).")
        elif specific_h2s < h2_count * 0.5:
            issues.append(f"⚠️ Chỉ {specific_h2s}/{h2_count} heading specific.")
    scores["1. Contextual Vector"] = s1

    # 2. Contextual Hierarchy (có H3 dưới ít nhất 50% H2)
    h3_count = sum(1 for h in headings if h.get("level") == "H3")
    h3_ratio = h3_count / h2_count if h2_count > 0 else 0
    
    if h2_count < 3:
        s2 = 0 # Không có hierarchy nếu chỉ có 1-2 H2
        issues.append("❌ Điểm Hierarchy bằng 0 do cấu trúc H2 không đủ (cần ≥3 H2).")
    else:
        s2 = 10 if h3_ratio >= 1.0 else (7 if h3_ratio >= 0.5 else 3)
        if h3_ratio < 0.5:
            issues.append(f"⚠️ Cấu trúc nông: Chỉ {h3_ratio*100:.0f}% H2 có triển khai H3 (khuyến nghị ≥50% tùy chủ đề).")
    scores["2. Contextual Hierarchy (H3)"] = s2

    # V11-R1: H3 TEMPLATE QUALITY DETECTION
    # Detect H3 headings that are template-generated (contain '??' or '[' brackets)
    # Phase 36: Removed redundant `import re` — already at module top
    def _is_template_h3(t: str) -> bool:
        if "??" in t or t.endswith("??"):
            return True
        if "[[" in t:
            return True
        if t.strip().startswith("["):
            # Allow bracketed standard/code tokens when they are actual evidence, not placeholders.
            if re.match(r'^\[[A-Z0-9\-\/ ]+\]', t.strip()):
                return False
            return True
        return False

    h3_texts = [h.get("text", "") for h in headings if h.get("level") == "H3"]
    if h3_texts:
        template_h3_count = sum(1 for t in h3_texts if _is_template_h3(t))
        template_ratio = template_h3_count / len(h3_texts)
        if template_ratio > 0.3:
            issues.append(
                f"❌ STRICT PENALTY: {template_h3_count}/{len(h3_texts)} H3 "
                f"({template_ratio*100:.0f}%) là template chất lượng thấp (chứa '??' hoặc '['). Trừ 8 điểm."
            )
            strict_penalties += 8

    # 3. FS Block (micro_briefing có snippet ngắn)
    # Bug B fix: normalize dict wrapper {"items": [...]} → flat list [...]
    micro_raw = brief.get("micro_briefing", [])
    if isinstance(micro_raw, dict):
        brief["micro_briefing"] = micro_raw.get("items", []) if "items" in micro_raw else list(micro_raw.values())
    elif isinstance(micro_raw, list):
        brief["micro_briefing"] = micro_raw
    else:
        brief["micro_briefing"] = []
    micro = brief["micro_briefing"]
    valid_fs = 0
    meaningful_fs = 0
    long_fs = 0
    llm_failed_fs = 0  # Count FS blocks that are generic fallbacks (LLM failed)
    for mb in micro:
        snippet = str(mb.get("snippet", ""))
        word_count = len(snippet.split())
        snippet_lower = snippet.lower()

        # Detect LLM failure: FS is a generic fallback
        # Indicators: "can xac minh", "khoi thong tin", "duoc dien giai", "section nay"
        # or "Heading text" repeated verbatim as content (H2 name = FS content)
        is_llm_failed = any(p in snippet_lower for p in [
            "can xac minh", "khoi thong tin", "can duoc trinh bay",
            "duoc dien giai ngan gon", "section nay", "theo semantic seo",
            "khoang trang", "dinh nghia rõ"
        ])
        # Also: if H2 name appears as the majority of the snippet (copy-paste H2 as FS)
        h2_name = str(mb.get("h2", "")).replace("[MAIN]", "").replace("[SUPP]", "").strip()
        if h2_name and len(snippet) > 20:
            h2_word_count = len(h2_name.split())
            if word_count <= h2_word_count + 10:
                # FS is almost exactly the H2 name — LLM failed
                is_llm_failed = True

        if 10 < word_count <= 40:
            valid_fs += 1
            heading_terms = _split_context_phrases(mb.get("h2", ""))
            if is_llm_failed:
                llm_failed_fs += 1
            elif _snippet_semantically_valid(snippet, topic_terms, heading_terms):
                meaningful_fs += 1
        elif word_count > 40:
            long_fs += 1
            
    if meaningful_fs >= max(1, h2_count - 1):
        s3 = 10
    elif meaningful_fs > 0:
        s3 = 7 if llm_failed_fs == 0 else 5
    elif valid_fs > 0:
        s3 = 3
    else:
        s3 = 0
    # Koray strict penalty: if ALL FS blocks are LLM-failed fallbacks → cap score
    if llm_failed_fs > 0 and meaningful_fs == 0:
        issues.append(f"❌ LLM FAILURE: Tất cả FS Blocks là generic fallback ({llm_failed_fs}/{len(micro)}). Agent 3 không hoạt động. Kiểm tra API key và LLM availability.")
        s3 = max(s3, 3)
    scores["3. FS Blocks (≤40 từ)"] = s3
    if meaningful_fs < max(1, h2_count - 1):
        if valid_fs > 0 and meaningful_fs == 0:
            issues.append(f"⚠️ FS có {valid_fs} snippet đúng word-count nhưng chưa đủ tín hiệu ngữ nghĩa.")
        else:
            issues.append(f"⚠️ Chỉ {meaningful_fs}/{h2_count} H2 có FS snippet đủ ngắn và có nghĩa.")
    elif valid_fs < max(1, h2_count - 1):
        issues.append(f"⚠️ Chỉ {valid_fs}/{h2_count} H2 có FS snippet độ dài lý tưởng (10-40 từ).")
    if long_fs > 0:
        issues.append(f"⚠️ Có {long_fs} FS snippet khá dài (> 40 từ). Cân nhắc rút gọn để tối ưu Featured Snippet.")

    per_heading_plan = {}
    section_plan = reasoning.get("section_evidence_plan", {})
    if isinstance(section_plan, dict) and isinstance(section_plan.get("per_heading"), dict):
        per_heading_plan = section_plan.get("per_heading", {})
    if per_heading_plan:
        evidence_mismatches = 0
        drift_hits = 0
        consensus_hits = 0
        consensus_facts = [_normalize_plain_text(x) for x in reasoning.get("consensus_facts", []) if str(x).strip()]
        brief_text = " ".join(
            [str(h.get("text", "")) for h in headings] +
            [str(mb.get("snippet", "")) + " " + str(mb.get("analysis", "")) for mb in micro if isinstance(mb, dict)]
        )
        brief_text_norm = _normalize_plain_text(brief_text)
        for fact in consensus_facts:
            if fact and fact in brief_text_norm:
                consensus_hits += 1
        if consensus_facts and consensus_hits < max(1, len(consensus_facts) // 2):
            issues.append(f"⚠️ Consensus facts coverage yếu ({consensus_hits}/{len(consensus_facts)}).")
            strict_penalties += 3

        for heading_text in h2_texts:
            meta = per_heading_plan.get(heading_text)
            if not isinstance(meta, dict):
                continue
            heading_norm = _normalize_plain_text(heading_text)
            kind = _normalize_plain_text(meta.get("kind", ""))
            matched_eav = meta.get("matched_eav", []) if isinstance(meta.get("matched_eav", []), list) else []
            avoid_drift = [_normalize_plain_text(x) for x in meta.get("avoid_drift", []) if str(x).strip()]
            if kind in {"calculation", "comparison", "impact", "risk"} and matched_eav:
                attrs_norm = [_normalize_plain_text(str(row.get("attribute", ""))) for row in matched_eav if isinstance(row, dict)]
                if attrs_norm and all(attr and attr in {"dinh nghia", "definition"} for attr in attrs_norm[:1]):
                    evidence_mismatches += 1
            if avoid_drift and any(risk and risk in heading_norm for risk in avoid_drift):
                drift_hits += 1
        if evidence_mismatches > 0:
            issues.append(f"⚠️ Có {evidence_mismatches} H2 dùng evidence chưa khớp section kind theo semantic_reasoning.")
            strict_penalties += min(6, evidence_mismatches * 2)
        if drift_hits > 0:
            issues.append(f"⚠️ Có {drift_hits} H2 chạm vùng drift đã được semantic_reasoning cảnh báo.")
            strict_penalties += min(4, drift_hits)

    # 4. PAA Map — P2.4 FIX: 0 điểm khi không có PAA thực
    paa_from_serp = brief.get("serp_analysis", {}).get("people_also_ask", [])
    paa_from_analysis = brief.get("suggested_questions", [])
    paa_all = paa_from_serp or paa_from_analysis
    # Lọc bỏ PAA placeholder ("N/A", empty strings)
    paa_real = [q for q in paa_all if q and not str(q).startswith("N/A")]
    s4 = 10 if len(paa_real) >= 3 else (5 if paa_real else 0)
    scores["4. PAA Mapping"] = s4
    anchor_stats = _anchor_plan_stats(reasoning)
    if anchor_stats["total"] > 0 and anchor_stats["reuse_ratio"] > 0.45:
        issues.append(f"Anchor reuse overload: {anchor_stats['reuse_ratio']:.0%} H3 anchor bi lap lai.")
        strict_penalties += min(8, int(anchor_stats["reuse_ratio"] * 10))
    if anchor_stats["low_distance"] > 0:
        issues.append(f"Co {anchor_stats['low_distance']} H3 co semantic distance qua thap voi anchor.")
        strict_penalties += min(6, anchor_stats["low_distance"])
    if not paa_real:
        issues.append("❌ Không có dữ liệu PAA thực từ SERP — FS Blocks không thể tạo")
    elif len(paa_real) < 3:
        issues.append(f"⚠️ Chỉ có {len(paa_real)} PAA questions (khuyến nghị ≥3)")

    # 5. Main/Supp Split
    has_main = any("[MAIN]" in h.get("text", "") for h in headings)
    has_supp = any("[SUPP]" in h.get("text", "") for h in headings)
    s5 = 10 if (has_main and has_supp) else (5 if has_main else 0)
    scores["5. Main/Supp Split"] = s5
    if not has_supp:
        issues.append("❌ Không có [SUPP] section — thiếu NAP và CTA")

    # 6. EAV Coverage — P2.4 FIX: 0 điểm khi EAV Table trống
    eav_table_md = brief.get("eav_table", "")
    eav_data = brief.get("entity_attributes", {})
    real_eav_rows, placeholder_eav_rows = _count_meaningful_eav_rows(eav_table_md, eav_data)
    verified_quality = _verified_eav_quality(brief, reasoning)
    verified_rows = int(verified_quality.get("verified_rows", 0))
    attribute_families = int(verified_quality.get("attribute_families", 0))
    if verified_rows >= 5 and attribute_families >= 3:
        s6 = 10
    elif verified_rows >= 3 and attribute_families >= 2:
        s6 = 7
    elif verified_rows >= 2:
        s6 = 5
    elif verified_rows == 1:
        s6 = 3
    else:
        s6 = 0
    if placeholder_eav_rows > 0:
        s6 = max(0, s6 - min(2, placeholder_eav_rows))
    scores["6. EAV Coverage"] = s6
    if verified_rows < 3:
        issues.append(f"Chi co {verified_rows} dong EAV da verify (can >=3).")
    blocked_numeric_rows = verified_quality.get("blocked_numeric_rows", []) or []
    if blocked_numeric_rows:
        issues.append(f"Co {len(blocked_numeric_rows)} numeric EAV rows chua verify, khong nen dua vao snippet hoac sapo.")
    if real_eav_rows < 3:
        issues.append(f"⚠️ Chỉ có {real_eav_rows} dòng EAV thực (cần ≥3).")
    if placeholder_eav_rows > 0:
        issues.append(f"⚠️ EAV có {placeholder_eav_rows} dòng placeholder / cần xác minh.")

    # 7. Source Context Alignment — MUST scan headings + micro_briefing (consistent with generate_source_context_alignment)
    if project:
        all_text = " ".join(h.get("text", "") for h in headings)
        for mb in micro:
            if isinstance(mb, dict):
                all_text += " " + str(mb.get("snippet", ""))
                all_text += " " + str(mb.get("bridge", ""))
        all_text_lower = all_text.lower()
        # Check 3 tiêu chí: brand, geo, hotline
        brand_ok = project.brand_name.lower() in all_text_lower
        geo_keywords = [g.strip().lower() for g in (project.geo_keywords or "").split(",") if g.strip()]
        geo_ok = any(geo in all_text_lower for geo in geo_keywords) if geo_keywords else True
        hotline_clean = re.sub(r'\D', '', project.hotline or "")
        hotline_ok = hotline_clean in re.sub(r'\D', '', all_text) if hotline_clean else True
        checks_passed = sum([brand_ok, geo_ok, hotline_ok])
        s7 = {3: 10, 2: 7, 1: 4, 0: 0}.get(checks_passed, 0)  # Phase 36: .get() safe
        if not brand_ok:
            issues.append("⚠️ Brand chưa xuất hiện trong phần body/[SUPP] bridge (không tính SAPO)")
    else:
        s7 = 5  # Neutral khi không có project
    scores["7. Source Context Alignment"] = s7

    # 8. Internal Link Logic (SUPP có linking, MAIN không)
    linking = brief.get("internal_linking", {})
    outbound = linking.get("outbound_nodes", []) if isinstance(linking, dict) else []
    
    # FIX 7: Kiểm tra chất lượng anchor chữ (phải có từ 2 chữ trở lên) chứ không chỉ check presence
    anchor_quality = all(len(n.get("anchor", "").split()) >= 2 for n in outbound)
    s8 = 10 if (outbound and anchor_quality) else (7 if outbound else 5)  # Rule-based check cơ bản
    scores["8. Internal Link Logic"] = s8
    
    if not outbound:
        issues.append("❌ STRICT PENALTY: Không có Internal Links hợp lệ (Root không có Node ra). Trừ 15 điểm tổng.")
        strict_penalties += 15
    elif not anchor_quality:
        issues.append("❌ STRICT PENALTY: Anchor text sơ sài (1 chữ). Trừ 5 điểm tổng.")
        strict_penalties += 5

    # 9. Sapo Quality (micro_briefing[0] là SAPO)
    # SAPO Quality: 3-dimensional scoring (Koray Formula)
    # D1: Word count (40%)   D2: Content quality (35%)   D3: EAV value presence (25%)
    sapo_mb = micro[0] if micro else {}
    sapo_snippet = str(sapo_mb.get("snippet", ""))
    sapo_words = len(sapo_snippet.split())
    sapo_lower = sapo_snippet.lower()

    # D1: Word count — SAPO must be 80-120 words (Koray: ≥80 for Mindshare Model)
    # Fallback: 56-156 with warning; below 56 = critical
    if sapo_words >= 80:
        d1_score = 10  # Full score
    elif 56 <= sapo_words < 80:
        d1_score = 5  # Acceptable with warning
    elif sapo_words > 0:
        d1_score = 2  # Too short — critical
    else:
        d1_score = 0  # Empty

    # D2: Content quality — detect placeholder patterns
    placeholder_markers = [
        "section nay", "theo semantic seo", "khoang trang",
        "can xac minh", "cac thuoc tinh", "topical border",
        "phan tich theo", "ban topical", "content gaps",
    ]
    is_placeholder = any(p in sapo_lower for p in placeholder_markers)

    # Count keyword repetition ratio (keyword stuffing detection)
    topic_text = str(brief.get("topic", "")).lower().strip()
    topic_terms = [t for t in re.split(r"\s+", topic_text) if len(t) >= 3][:5]
    keyword_count = sum(sapo_lower.count(t) for t in topic_terms)
    keyword_density = keyword_count / sapo_words if sapo_words > 0 else 0
    keyword_stuffing = keyword_density > 0.15  # >15% = stuffing

    # EAV value extraction check: SAPO should contain actual values
    eav_pattern = re.compile(r'\d+[.,]\d+%|\d+[.,]\d+\s*(VND|USD|MPa|kg|mm|%)', re.IGNORECASE)
    eav_matches = eav_pattern.findall(sapo_snippet)
    has_verified_numeric = verified_rows > 0 and any(
        isinstance(row, dict) and row.get("is_verified") and row.get("is_numeric")
        for row in reasoning.get("verified_eav_rows", [])
    )

    if is_placeholder or keyword_stuffing:
        d2_score = 0  # Total failure
    elif sapo_words >= 80 and eav_matches:
        d2_score = 10  # Full quality: real content + EAV values
    elif sapo_words >= 80:
        d2_score = 7  # Good: real content, no EAV values
    elif sapo_words > 0:
        d2_score = 3  # Weak: real content but too short
    else:
        d2_score = 0

    # D3: EAV value presence (Koray: SAPO must contain at least 1 concrete value)
    if eav_matches and has_verified_numeric:
        d3_score = 10
    elif eav_matches and not has_verified_numeric:
        d3_score = 0
        strict_penalties += 4
    elif sapo_words >= 80:
        d3_score = 3  # Content exists but no concrete values
    else:
        d3_score = 0

    # Weighted total: D1(40%) + D2(35%) + D3(25%)
    s9_raw = (d1_score * 0.40) + (d2_score * 0.35) + (d3_score * 0.25)
    s9 = round(s9_raw)

    # Build issue messages
    if is_placeholder:
        issues.append("❌ SAPO là PLACEHOLDER TEXT — 'Section này phân tích [...] theo semantic SEO'. LLM Agent 3 không hoạt động. Cần bật API key hoặc kiểm tra prompt.")
        strict_penalties += 5
    if keyword_stuffing:
        issues.append(f"⚠️ SAPO keyword stuffing: {keyword_density:.0%} ({keyword_count} từ khóa trong {sapo_words} từ). Giới hạn ≤15%.")
    if sapo_words < 80 and sapo_words > 0 and not is_placeholder:
        issues.append(f"⚠️ Sapo có {sapo_words} từ — dưới ngưỡng 80 từ tối thiểu (Koray Mindshare Model).")
    if not eav_matches and sapo_words >= 80:
        issues.append("⚠️ SAPO không chứa giá trị EAV cụ thể (%, VND, MPa, mm). Nên trích xuất key values từ EAV Table.")
    scores["9. Sapo Quality"] = s9
    if eav_matches and not has_verified_numeric:
        issues.append("SAPO dang dung so lieu nhung fact numeric chua duoc verify.")

    # 10. Attribute Filtration (số H2 hợp lý 5-12)
    s10 = 10 if 5 <= h2_count <= 12 else (5 if 3 <= h2_count < 5 else 0)
    scores["10. Attribute Filtration (H2 count)"] = s10
    if not (5 <= h2_count <= 12):
        issues.append(f"⚠️ Có {h2_count} H2 (khuyến nghị 5-12)")

    # 11. Per-H2 Writing Guidance — detect placeholder text + Koray 12-Writing compliance
    # Phase: Detect "Section này phân tích [...] theo semantic SEO" in micro_briefing sections
    micro = brief.get("micro_briefing", [])
    main_micro = [
        m for m in micro
        if isinstance(m, dict) and "[MAIN]" in m.get("h2", "").upper()
    ]
    # Placeholder detection across all sections
    placeholder_patterns = [
        "section nay", "theo semantic seo", "khoang trang",
        "can xac minh", "ban topical", "content gaps",
        "phan tich theo", "ban semantic", "topical border",
        "cac thuoc tinh can", "cac thuoc tinh chinh",
    ]
    section_names = ["analysis", "info_gain", "bridge", "transition"]

    placeholder_sections = 0
    total_sections = 0
    for m in main_micro:
        for sec in section_names:
            val = str(m.get(sec, "")).lower()
            total_sections += 1
            if any(p in val for p in placeholder_patterns):
                placeholder_sections += 1

    placeholder_ratio = placeholder_sections / total_sections if total_sections > 0 else 0

    if main_micro:
        specificity_ratio = _guidance_specificity_score(main_micro, topic_terms)
        guidance_fingerprints = set()
        for m in main_micro:
            parts = [
                m.get("content_format", ""),
                m.get("first_sentence", ""),
                m.get("micro_terms", ""),
                m.get("sentence_before", ""),
                m.get("preceding_question", ""),
                m.get("contextual_bridge", ""),
                m.get("analysis", ""),
                m.get("info_gain", ""),
                m.get("transition", ""),
            ]
            guidance_fingerprints.add(re.sub(r"\s+", " ", _normalize_plain_text(" ".join(str(p) for p in parts if p)))[:220])
        diversity_ratio = len([fp for fp in guidance_fingerprints if fp]) / len(main_micro)

        # Downweight for placeholder contamination
        quality_multiplier = max(0.2, 1.0 - (placeholder_ratio * 1.5))
        combined_ratio = min(1.0, (0.6 * specificity_ratio + 0.4 * diversity_ratio) * quality_multiplier)
        s11 = 10 if combined_ratio >= 0.75 else (7 if combined_ratio >= 0.5 else (3 if combined_ratio > 0.2 else 0))
    else:
        s11 = 0

    # Koray 12-Writing strict penalty: placeholder text indicates LLM failure
    if placeholder_ratio > 0.5:
        issues.append(f"❌ PER-H2 PLACEHOLDER TEXT: {placeholder_sections}/{total_sections} sections chứa placeholder ('Section này phân tích [...]'). Agent 3 LLM không hoạt động. Cần kiểm tra API key.")
        strict_penalties += 10
    elif placeholder_ratio > 0.2:
        issues.append(f"⚠️ Per-H2: {placeholder_ratio:.0%} sections chứa placeholder text — cần cải thiện content quality.")
        s11 = max(3, s11 - 2)

    if main_micro and s11 < 10 and placeholder_ratio <= 0.2:
        issues.append(
            "⚠️ Per-H2 guidance còn generic hoặc trùng lặp giữa các H2 MAIN. "
            "Cần tăng độ riêng của content_format, first_sentence và micro_terms."
        )

    snippet_fingerprints = []
    for mb in micro:
        if not isinstance(mb, dict):
            continue
        snippet = re.sub(r"\s+", " ", _normalize_plain_text(mb.get("snippet", "")))
        if snippet:
            snippet_fingerprints.append(snippet[:180])
    if snippet_fingerprints:
        unique_ratio = len(set(snippet_fingerprints)) / len(snippet_fingerprints)
        if unique_ratio < 0.65:
            issues.append(f"Section uniqueness yeu: snippet uniqueness ratio chi {unique_ratio:.0%}.")
            strict_penalties += min(8, int((1 - unique_ratio) * 10))

    body_fingerprints = []
    for mb in main_micro:
        if not isinstance(mb, dict):
            continue
        body = " ".join(
            str(part)
            for part in [
                mb.get("analysis", ""),
                mb.get("content_format", ""),
                mb.get("info_gain", ""),
                mb.get("transition", ""),
            ]
            if str(part).strip()
        )
        body_norm = re.sub(r"\s+", " ", _normalize_plain_text(body)).strip()
        if body_norm:
            body_fingerprints.append(body_norm[:220])
    if body_fingerprints:
        body_unique_ratio = len(set(body_fingerprints)) / len(body_fingerprints)
        if body_unique_ratio < 0.70:
            issues.append(f"Section uniqueness yeu: body guidance uniqueness ratio chi {body_unique_ratio:.0%}.")
            strict_penalties += min(8, int((1 - body_unique_ratio) * 10))

    total = int(sum(scores.values()) * 10 / len(scores))

    # ══════════════════════════════════════════
    # STRUCTURAL FAILURE GATE
    # Cap điểm tổng nếu H2 không đủ cho intent
    # Phase 2.2: Use centralized intent module
    # ══════════════════════════════════════════
    from modules.intent import get_h2_minimum
    detected_intent = brief.get("search_intent", {})
    if isinstance(detected_intent, dict):
        detected_intent = detected_intent.get("type", "informational").lower()
    else:
        detected_intent = str(detected_intent).lower()
    min_h2_required = get_h2_minimum(detected_intent)
    structural_cap = STRUCTURAL_CAPS.get(h2_count, 100)  # ≥5 H2 = không bị cap

    if h2_count < min_h2_required:
        issues.append(
            f"❌ STRUCTURAL FAILURE: Chỉ có {h2_count} H2 cho intent '{detected_intent}' "
            f"(cần tối thiểu {min_h2_required}). Điểm bị giới hạn {structural_cap}/100."
        )
    total = min(total, structural_cap)

    # ══════════════════════════════════════════
    # PROMINENCE PENALTY
    # Phạt -5 điểm cho mỗi H2 từ Rare Headings không có PAA support
    # ══════════════════════════════════════════
    paa_from_serp = brief.get("serp_analysis", {}).get("people_also_ask", [])
    paa_from_analysis = brief.get("suggested_questions", [])
    paa_all = paa_from_serp or paa_from_analysis
    paa_lower = [str(p).lower() for p in paa_all]

    info_gain = brief.get("serp_analysis", {}).get("information_gain", {})
    if isinstance(info_gain, dict):
        rare_headings = info_gain.get("rare_headings", [])
    else:
        rare_headings = []

    h2_headings_lower = [h.get("text", "").lower() for h in headings if h.get("level") == "H2"]

    unverified_rare_count = 0
    for rare_h in rare_headings:
        rare_lower = str(rare_h).lower()
        # Kiểm tra H2 này có trong outline không
        in_outline = any(rare_lower in h2 or h2 in rare_lower for h2 in h2_headings_lower)
        # Kiểm tra có PAA support không
        has_paa_support = any(rare_lower in paa or paa in rare_lower for paa in paa_lower)
        
        if in_outline and not has_paa_support:
            unverified_rare_count += 1

    prominence_penalty = unverified_rare_count * 5
    if prominence_penalty > 0:
        issues.append(
            f"⚠️ PROMINENCE PENALTY: -{prominence_penalty} điểm "
            f"({unverified_rare_count} H2 từ Rare Headings không có PAA support)."
        )
    
    total = max(0, total - prominence_penalty - strict_penalties)

    grade = "A" if total >= 85 else ("B" if total >= 70 else ("C" if total >= 55 else ("D" if total >= 40 else "F")))

    # Build output
    lines = [f"## 📊 KORAY QUALITY SCORE: **{total}/100** (Grade {grade})\n"]
    lines.append("| Tiêu chí | Điểm |")
    lines.append("|----------|------|")
    for criterion, score in scores.items():
        icon = "✅" if score >= 8 else ("⚠️" if score >= 5 else "❌")
        lines.append(f"| {icon} {criterion} | {score}/10 |")

    if issues:
        lines.append("\n### ❌ Các vấn đề phát hiện:")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("\n✅ Không phát hiện vấn đề nghiêm trọng!")

    return "\n".join(lines)


# ══════════════════════════════════════════════
#  LLM-BASED FUNCTIONS (có try/except fallback = "")
# ══════════════════════════════════════════════

def _get_openai_client(api_key: str):
    """Helper tạo OpenAI client. Return None nếu không có key."""
    # Phase 43 DEBUG: Log key status
    _api_key_short = (api_key[:12] + "...") if api_key else "(empty)"
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.warning("[KORAY-CLIENT] No API key — client will be None. api_key='%s'", _api_key_short)
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        logger.info("[KORAY-CLIENT] OpenAI client created. api_key='%s'", _api_key_short)
        return client
    except Exception as e:
        logger.error("[KORAY-CLIENT] Failed to create OpenAI client: %s", e)
        return None


def _call_llm(client, model: str, system: str, user: str, max_tokens: int = 1500, response_format: Optional[dict] = None) -> str:
    """Helper gọi LLM và trả về text. Throw exception nếu thất bại."""
    from modules.llm_utils import call_llm_with_retry, LLM_DEFAULTS
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return call_llm_with_retry(
            client=client,
            model=model,
            messages=messages,
            temperature=LLM_DEFAULTS["temperature_seo"],  # 0.3
            max_tokens=max_tokens,
            timeout=LLM_DEFAULTS["timeout"],              # 60s
            response_format=response_format,
        )
    except Exception as exc:
        logger.warning("[KorayAnalyzer._call_llm] LLM call failed (returning empty): %s", exc)
        return ""


def _fallback_macro_context(topic: str, analysis: Dict, project=None) -> str:
    """Deterministic macro context when the LLM path is unavailable."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    intent = analysis.get("search_intent", {}) if isinstance(analysis, dict) else {}
    intent_type = intent.get("type", "informational") if isinstance(intent, dict) else "informational"
    intent_desc = intent.get("description", "") if isinstance(intent, dict) else ""
    target_user = analysis.get("target_user", "") if isinstance(analysis, dict) else ""
    industry = str(getattr(project, "industry", "") or "").strip()
    main_products = str(getattr(project, "main_products", "") or "").strip()
    target_customers = str(getattr(project, "target_customers", "") or "").strip()
    topic_norm = _normalize_plain_text(str(topic or "")).lower()
    scope_parts = [p for p in [main_products, industry] if p]
    scope = " trong ".join(scope_parts) if len(scope_parts) >= 2 else (scope_parts[0] if scope_parts else "")
    if not scope:
        scope = f"ngữ cảnh của {topic}" if topic else "ngữ cảnh chủ đề"

    macro_context = scope

    parts = [
        f"- **Central Entity**: {entity}",
        f"- **Macro Context**: {macro_context}",
        f"- **Search Intent Type**: {intent_type}",
        f"- **Intent Subtype**: {intent.get('subtype', 'What-is') if isinstance(intent, dict) else 'What-is'}",
        f"- **Nguoi dung muc tieu**: {target_user or target_customers or intent_desc or 'Nguoi dung tim hieu thong tin lien quan den chu de nay'}",
    ]
    return "[LLM_FALLBACK]\n" + "\n".join(parts)


def generate_macro_context(
    topic: str,
    analysis: Dict,
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột L: Gọi LLM sinh Macro Context & Central Entity Analysis.

    Output format:
    - Central Entity, Macro Context, Search Intent Type, Intent Subtype, Target User
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return _fallback_macro_context(topic, analysis, project)

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Ban la chuyen gia Semantic SEO (Koray Framework). Nhiem vu: Phan tich Macro Context cho tu khoa.\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "central_entity": "ten entity chinh (khong qua 10 tu)",\n'
            '  "macro_context": "1 cau mo ta ngon le rong (Contextual Domain)",\n'
            '  "search_intent_type": "Definitional | Comparative | Informational | Commercial | Transactional | Navigational",\n'
            '  "intent_subtype": "What-is | How-to | vs | Price | Guide | Review | List | Definition",\n'
            '  "target_user": "mo ta ngan nguoi dung dang tim kiem (1-2 cau)"\n'
            "}\n\n"
            "RULES:\n"
            "- central_entity: Chi 1 entity duy nhat.\n"
            "- macro_context: Mo ta nganh/linh vuc rong. VD: 'Vat lieu xay dung trong nganh xay dung Viet Nam'.\n"
            "- search_intent_type: Chon 1 trong 6 gia tri chuan.\n"
            "- intent_subtype: Chon 1 trong 7 gia tri pho bien.\n"
            "- target_user: Mo ta persona cu the (chuyen gia ky thuat / chu dau tu / nguoi mua hang...).\n"
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        entity = analysis.get("central_entity", topic)
        intent = analysis.get("search_intent", "informational")
        if isinstance(intent, dict):
            intent = intent.get("type", "informational")

        user = (
            f"Tu khoa: '{topic}'\n"
            f"Central Entity hien tai: '{entity}'\n"
            f"Search Intent phat hien: '{intent}'\n"
            "Hay phan tich va tra ve JSON dung schema tren."
        )

        raw = _call_llm(client, model, system, user, max_tokens=600, response_format={"type": "json_object"})
        import json
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("  [KORAY-L] JSON parse failed, falling back to defaults")
            return _fallback_macro_context(topic, analysis, project)

        ce = str(data.get("central_entity", entity) or "").strip()
        mc = str(data.get("macro_context", "") or "").strip()
        sit = str(data.get("search_intent_type", intent) or "").strip()
        ist = str(data.get("intent_subtype", "") or "").strip()
        tu = str(data.get("target_user", "") or "").strip()

        if not ce or not mc or not sit or not tu:
            logger.warning("  [KORAY-L] Macro Context fields incomplete, using fallback.")
            return _fallback_macro_context(topic, analysis, project)

        lines = [
            f"- **Central Entity**: {ce}",
            f"- **Macro Context**: {mc}",
            f"- **Search Intent Type**: {sit}",
            f"- **Intent Subtype**: {ist}",
            f"- **Nguoi dung muc tieu**: {tu}",
        ]
        result = "\n".join(lines)
        logger.info("  [KORAY-L] Macro Context OK (entity='%s')", ce)
        return result

    except Exception as e:
        logger.warning("  [KORAY-L] Macro Context failed: %s", e)
        return _fallback_macro_context(topic, analysis, project)


def _fmt_val(value: str, row: Dict) -> str:
    """Format EAV value cell — thêm source_hint cho [CAN XAC MINH]."""
    if not value:
        return "[CAN XAC MINH]"
    val = str(value).strip()
    if val == "[CAN XAC MINH]" or val.startswith("[CAN XAC MINH]"):
        hint = row.get("source_hint", "")
        if hint:
            return f"{val} → {hint}"
        return val
    return val


def _fallback_eav_markdown(topic: str, analysis: Dict, project=None) -> str:
    """Deterministic EAV table when the LLM path is unavailable."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    attrs = analysis.get("entity_attributes", {}) if isinstance(analysis, dict) else {}
    industry = str(getattr(project, "industry", "") or "").strip()
    main_products = str(getattr(project, "main_products", "") or "").strip()
    target_customers = str(getattr(project, "target_customers", "") or "").strip()
    topic_norm = _normalize_plain_text(str(topic or "")).lower()
    rows: List[tuple] = []

    if isinstance(attrs, dict) and attrs:
        generic_only = True
        for key, value in list(attrs.items())[:8]:
            attr_name = str(key).strip().replace("_", " ")
            key_norm = _normalize_plain_text(attr_name)
            if isinstance(value, (list, tuple, set)):
                value_text = ", ".join([str(v).strip() for v in list(value)[:4] if str(v).strip()])
            else:
                value_text = str(value).strip() if value is not None else ""
            value_norm = _normalize_plain_text(value_text)
            if key_norm in {"root attributes", "rare attributes", "unique attributes"} or value_norm in {"root_attributes", "rare_attributes", "unique_attributes"}:
                continue
            if not value_text or value_norm.startswith("khong co thuoc tinh") or value_norm.startswith("[can xac minh]"):
                continue
            generic_only = False
            rows.append((entity, attr_name.title(), value_text))

        if generic_only and not rows:
            rows = []

    if not rows:
        intent = analysis.get("search_intent", {}) if isinstance(analysis, dict) else {}
        intent_type = intent.get("type", "informational") if isinstance(intent, dict) else "informational"
        intent_desc = intent.get("description", "") if isinstance(intent, dict) else ""
        scope = main_products or industry or topic
        core_value = f"{entity} can duoc trien khai theo dung ngu canh, evidence va pham vi ap dung cua {scope}."
        rows = [
            (entity, "Định nghĩa", f"{entity} là chủ đề cần hiểu theo ngữ cảnh {topic} và phải gắn với cách tính hoặc phạm vi áp dụng thực tế."),
            (entity, "Bối cảnh ngành", scope or "[CAN XAC MINH]"),
            (entity, "Search Intent", intent_desc or intent_type),
            (entity, "Thuộc tính cốt lõi", core_value),
            (entity, "Lưu ý / rủi ro", "Cần kiểm tra nguồn chính thống và các điều kiện áp dụng trước khi dùng dữ liệu này."),
        ]
    elif industry or main_products or target_customers:
        rows.extend([
            (entity, "Bối cảnh ngành", industry or main_products or topic),
            (entity, "Sản phẩm / dịch vụ liên quan", main_products or "[CAN XAC MINH]"),
            (entity, "Nhóm người dùng mục tiêu", target_customers or "[CAN XAC MINH]"),
        ])

    lines = ["| Entity | Attribute | Value |", "|---|---|---|"]
    for ent, attr, value in rows[:12]:
        lines.append(f"| {ent} | {attr} | {value} |")
    return "[LLM_FALLBACK]\n" + "\n".join(lines)


def _fallback_heading_for_question(question: str, headings: List[Dict]) -> str:
    """Pick the best matching heading for a PAA question."""
    if not headings:
        return "H2: Tong quan"

    q = _normalize_plain_text(question)
    buckets = [
        (["la gi", "dinh nghia", "khai niem"], ["la gi", "dinh nghia", "khai niem"]),
        (["cach", "quy trinh", "huong dan", "lam sao"], ["cach", "quy trinh", "huong dan", "lam sao"]),
        (["rui ro", "luu y", "can than", "can biet"], ["rui ro", "luu y", "can than", "can biet"]),
        (["so sanh", "khac nhau", "vs"], ["so sanh", "khac nhau", "vs"]),
    ]

    best = None
    best_score = -1
    for h in headings:
        if not isinstance(h, dict):
            continue
        text = str(h.get("text", "")).strip()
        if not text:
            continue
        norm = _normalize_plain_text(text)
        score = 0
        for sigs, qs in buckets:
            if any(sig in q for sig in sigs) and any(qsig in norm for qsig in qs):
                score += 2
        if score > best_score:
            best = h
            best_score = score
    if not best:
        best = headings[0] if isinstance(headings[0], dict) else {"level": "H2", "text": str(headings[0])}
    return f"{best.get('level', 'H2')}: {best.get('text', '')}".strip()


def _fallback_fs_answer(topic: str, question: str, heading: str) -> str:
    """Short answer suitable for Featured Snippet blocks — uses topic-specific content."""
    q = _normalize_plain_text(question)
    topic_text = str(topic or "").strip() or "chu de nay"
    heading_text = str(heading or "").strip()
    # Strip role markers from heading for cleaner content
    clean_heading = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", heading_text, flags=re.IGNORECASE).strip()

    if "la gi" in q or "dinh nghia" in q or "khai niem" in q:
        if clean_heading:
            return f"{clean_heading} là khái niệm quan trọng trong lĩnh vực liên quan đến {topic_text}, cần nắm vững định nghĩa và phạm vi áp dụng."
        return f"{topic_text} là khái niệm cần hiểu rõ, bao gồm định nghĩa chính xác, phạm vi áp dụng và vai trò thực tế."

    if any(sig in q for sig in ["cach", "quy trinh", "huong dan", "lam sao"]):
        if clean_heading:
            return f"Quy trinh lien quan den {clean_heading} gom: xac dinh nhu cau -> kiem tra du lieu -> thuc hien -> danh gia ket qua."
        return f"Quy trinh lien quan den {topic_text} gom: xac dinh nhu cau -> kiem tra du lieu -> thuc hien -> danh gia ket qua."


    if any(sig in q for sig in ["rui ro", "luu y", "can than"]):
        if clean_heading:
            return f"Cac diem can luu y lien quan den {clean_heading} gom: gioi han, dieu kien ap dung va diem can kiem chung truoc khi dua vao thuc te."
        return f"Cac diem can luu y khi lam viec voi {topic_text} gom: gioi han, dieu kien ap dung va diem can kiem chung truoc khi dua vao thuc te."

    if any(sig in q for sig in ["so sanh", "khac nhau", "vs"]):
        return f"De so sanh cac phuong an lien quan den {topic_text}, can xem xet tieu chi, hieu qua, dieu kien ap dung va gioi han cua tung lua chon."

    if clean_heading:
        return f"{clean_heading}: thông tin chi tiết cần tìm hiểu kỹ lưỡng, bao gồm đặc điểm, điều kiện và ngữ cảnh áp dụng cụ thể."
    return f"{topic_text} là thông tin quan trọng cần tìm hiểu kỹ lưỡng trước khi đưa ra quyết định liên quan."


def _fallback_fs_paa_markdown(topic: str, paa_questions: List[str], headings: List[Dict], project=None) -> str:
    """Build a deterministic PAA -> heading -> FS table when LLM is unavailable."""
    questions = [str(q).strip() for q in (paa_questions or []) if str(q).strip()]
    if not questions:
        questions = [str(h.get("text", "")).strip() for h in headings if isinstance(h, dict) and str(h.get("text", "")).strip()][:5]
    if not questions:
        questions = [
            f"{topic} la gi?",
            f"{topic} hoat dong nhu the nao?",
            f"Nhung luu y quan trong khi tim hieu {topic}?",
        ]

    lines = ["| PAA Question | Vi tri (H2/H3) | Format | FS Block (<=40 tu) |", "|---|---|---|---|"]
    for question in questions[:8]:
        heading = _fallback_heading_for_question(question, headings)
        fs_block = _fallback_fs_answer(topic, question, heading)
        q_norm = _normalize_plain_text(question)
        if any(sig in q_norm for sig in ["cach", "quy trinh", "huong dan", "lam sao"]):
            fmt = "List"
        elif any(sig in q_norm for sig in ["so sanh", "khac nhau", "vs"]):
            fmt = "Table"
        else:
            fmt = "Snippet"
        lines.append(f"| {question} | {heading} | {fmt} | {fs_block} |")
    return "\n".join(lines)


def generate_eav_table(
    topic: str,
    analysis: Dict,
    competitor_data: Optional[Dict] = None,
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột M: Gọi LLM sinh EAV Table (Entity - Attribute - Value).

    Output format: Bảng markdown | Entity | Attribute | Value |
    Fix V6: VS intent → parse 2 entities, 3-column comparison table, min 6 rows.
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return _fallback_eav_markdown(topic, analysis, project)

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Ban la chuyen gia Semantic SEO (Koray Framework). Nhiem vu: Tao bang EAV (Entity-Attribute-Value).\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "rows": [\n'
            '    {"entity": "string", "attribute": "string", "value": "string gia tri + don vi", "source_hint": "neu CAN XAC MINH: goi y nguon tra cuu"}\n'
            "  ]\n"
            "}\n\n"
            "RULES:\n"
            "1. Toi thieu 6 rows, chia 3 nhom: Root (3), Universal (2-3), Rare (1-2).\n"
            "2. Value phai co don vi phu hop nganh.\n"
            "3. GIA hoac khong chac chan -> BUOC: '[CAN XAC MINH] -> Tra [nguon]'. TUYET DOI KHONG tu bya so.\n"
            "4. source_hint: goi y nguon xac minh phu hop voi source context va entity hien tai.\n"
            "5. VS intent: dung cau truc {entity_a, entity_b, criteria, value_a, value_b, source_hint_a, source_hint_b}.\n"
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        # Evidence-aware unit guidance; never infer vertical units from fixed niche templates.
        industry_units_map = {
            "general": "Dung don vi, gia tri va nguon chi khi chung xuat hien trong evidence hien tai.",
        }
        niche_for_eav = "general"
        try:
            if project and hasattr(project, "industry") and project.industry:
                from modules.content_brief_builder import detect_niche as _dn
                niche_for_eav = _dn(topic, project.industry)
            else:
                from modules.content_brief_builder import detect_niche as _dn
                niche_for_eav = _dn(topic)
        except Exception:
            pass
        unit_guide_str = industry_units_map.get(niche_for_eav, industry_units_map["general"])

        entity = analysis.get("central_entity", topic)
        attrs = analysis.get("entity_attributes", {})
        attrs_str = "\n".join([f"- {k}: {v}" for k, v in attrs.items()]) if attrs else "N/A"

        intent = str(analysis.get("search_intent", {}).get("type", "informational") if isinstance(analysis.get("search_intent"), dict) else analysis.get("search_intent", "informational"))
        is_vs = "vs" in intent.lower() or "comparison" in intent.lower()

        if is_vs:
            # V6: Parse 2 entities from topic
            entity_parts = re.split(
                r'\bvà\b|\bvs\b|\bvới\b|\bso sánh\b|\bkhác nhau\b',
                topic, flags=re.IGNORECASE
            )
            entity_parts = [p.strip() for p in entity_parts if p.strip()]
            # Clean trailing question words
            for rem in ["thế nào", "như thế nào", "khác gì", "là gì", "ra sao"]:
                entity_parts = [p.replace(rem, "").strip() for p in entity_parts]
            entity_parts = [p for p in entity_parts if p]

            if len(entity_parts) >= 2:
                entity_a, entity_b = entity_parts[0], entity_parts[1]
            else:
                entity_a, entity_b = entity, "đối chiếu"

            user = (
                f"Từ khóa: '{topic}'\n"
                f"Search Intent: So sánh (VS)\n"
                f"Entity A: '{entity_a}'\n"
                f"Entity B: '{entity_b}'\n\n"
                f"Hãy tạo bảng EAV so sánh chi tiết.\n\n"
                f"FORMAT BẮT BUỘC 3 CỘT:\n"
                f"| Attribute (Tiêu chí so sánh) | {entity_a} | {entity_b} |\n"
                f"|------|------|------|\n"
                f"| Định nghĩa | [giá trị] | [giá trị] |\n"
                f"| Kích thước/Độ dày | [giá trị + đơn vị] | [giá trị + đơn vị] |\n"
                f"| ... | ... | ... |\n\n"
                f"QUY TẮC:\n"
                f"- Tối thiểu 6 rows (định nghĩa, kích thước, độ bền, ứng dụng, giá, ưu/nhược điểm)\n"
                f"- Don vi do phu hop nganh: {unit_guide_str}\n"
                f"- Gia tham khao LUON danh dau [CAN XAC MINH]\n"
                f"- TUYET DOI: Neu khong chac chan gia tri -> BUOC ghi [CAN XAC MINH], KHONG tu bya so\n"
                f"- KHONG de o trong — neu khong biet ghi [CAN XAC MINH]\n"
            )
        else:
            user = (
                f"Từ khóa: '{topic}'\n"
                f"Central Entity: '{entity}'\n"
                f"Attributes đã biết:\n{attrs_str}\n\n"
                f"Hãy tạo bảng EAV đầy đủ với 3 cột: | Entity | Attribute | Value |.\n"
                f"QUY TAC:\n"
                f"- Moi gia tri SOI phai co don vi do phu hop nganh: {unit_guide_str}\n"
                f"- TUYET DOI: Moi gia tri cu the khong co nguon ro rang -> BUOC ghi [CAN XAC MINH]\n"
                f"- TUYET DOI: Neu khong chac chan -> BUOC ghi [CAN XAC MINH], KHONG tu bya so\n"
                f"- KHONG de o trong — neu khong biet ghi [CAN XAC MINH]\n"
            )

        raw = _call_llm(client, model, system, user, max_tokens=1200, response_format={"type": "json_object"})
        import json
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("  [KORAY-M] JSON parse failed, using raw output")
            data = {"rows": []}

        rows = data.get("rows", []) or data.get("items", [])
        # Phase 42: json_object format wraps rows in dict {"items": [...]} hoặc ["rows": [...]]
        if not isinstance(rows, list):
            rows = rows.get("items", []) if isinstance(rows, dict) else []
        if not rows:
            return _fallback_eav_markdown(topic, analysis, project)

        if is_vs:
            lines = ["| Tiêu chi so sanh | Entity A | Entity B |", "|---|---|---|"]
            for row in rows:
                if isinstance(row, dict):
                    attr = row.get("criteria") or row.get("attribute", "")
                    # Ho tro ca 2 schema: VS {value_a, value_b} va non-VS {value}
                    raw_a = row.get("value_a") or row.get("entity_a") or ""
                    raw_b = row.get("value_b") or row.get("entity_b") or ""
                    if not raw_a:
                        raw_a = row.get("value", "")
                    if not raw_b:
                        raw_b = row.get("value", "")
                    val_a = _fmt_val(raw_a, row)
                    val_b = _fmt_val(raw_b, row)
                    lines.append(f"| {attr} | {val_a} | {val_b} |")
        else:
            lines = ["| Entity | Attribute | Value |", "|---|---|---|"]
            for row in rows:
                if isinstance(row, dict):
                    ent = row.get("entity", "")
                    attr = row.get("attribute", "")
                    val = _fmt_val(row.get("value", ""), row)
                    lines.append(f"| {ent} | {attr} | {val} |")

        result = "\n".join(lines)
        logger.info("  [KORAY-M] EAV Table OK (%d rows)", len(rows))
        return result

    except Exception as e:
        logger.warning("  [KORAY-M] EAV Table failed: %s", e)
        return _fallback_eav_markdown(topic, analysis, project)


def generate_attribute_filtration(
    topic: str,
    headings: List[Dict],
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột N: Gọi LLM giải thích thứ tự H2 theo 3 tiêu chí Koray:
    Prominence, Popularity, Relevance (điểm /10 mỗi tiêu chí).

    Output: text markdown giải thích từng H2 + lý do loại bỏ.
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return ""

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        h2_list = [h["text"] for h in headings if h.get("level") == "H2"]
        if not h2_list:
            return ""

        base_system = (
            "Ban la chuyen gia Semantic SEO (Koray Framework). Nhiem vu: Danh gia thu tu H2 theo 3 tieu chi Koray.\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "items": [\n'
            '    {\n'
            '      "heading": "ten H2 nguyen van",\n'
            '      "prominence": "number 0-10 — Attribute quan trong den muc nao de dinh nghia entity?",\n'
            '      "popularity": "number 0-10 — Attribute nay duoc tim kiem nhieu khong?",\n'
            '      "relevance": "number 0-10 — Attribute phu hop voi Source Context khong?",\n'
            '      "priority_order": "1=UNIQUE (viet truoc - Information Gain), 2=ROOT (dinh nghia), 3=RARE (mo rong)",\n'
            '      "recommendation": "Viet H2 o vi tri nao? Dau (H2#1), giua, cuoi?",\n'
            '      "reason": "giai thich ngan tai sao dat o vi tri nay (1-2 cau)"\n'
            '    }\n'
            "  ]\n"
            "}\n\n"
            "RULES:\n"
            "- prominence: Uu tien attribute ky thuat (tieu chuan, kich thuoc) > thuong mai (gia).\n"
            "- popularity: Dung du lieu SERP/PAA lam co so, khong doan.\n"
            "- relevance: Kiem tra brand keyword va source context, cho diem cao neu match.\n"
            "- reason: Toi da 1-2 cau.\n"
            "- Bo qua H2 generic khong co attribute cu the (diem thap).\n"
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        h2_str = "\n".join([f"{i+1}. {h}" for i, h in enumerate(h2_list)])
        user = (
            f"Từ khóa: '{topic}'\n\n"
            f"Danh sách H2 theo thứ tự trong outline:\n{h2_str}\n\n"
            "Hãy phân tích Attribute Filtration cho từng H2 theo format yêu cầu."
        )

        raw = _call_llm(client, model, system, user, max_tokens=1200, response_format={"type": "json_object"})
        import json
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("  [KORAY-N] JSON parse failed, using raw output")
            data = {"items": []}

        items = data.get("items", [])
        if not items:
            return "_(Khong the phan tich Attribute — du lieu rong)_"

        lines = []
        for item in items:
            if isinstance(item, dict):
                h = item.get("heading", item.get("h2", ""))
                p = item.get("prominence", item.get("P", 0))
                pop = item.get("popularity", item.get("Pop", 0))
                r = item.get("relevance", item.get("R", 0))
                reason = item.get("reason", item.get("lydo", ""))
                lines.append(f"**H2: {h}** — P:{p}/10 Pop:{pop}/10 R:{r}/10 → {reason}")
            elif isinstance(item, str):
                lines.append(item)

        result = "\n".join(lines)
        logger.info("  [KORAY-N] Attribute Filtration OK (%d items)", len(items))
        return result

    except Exception as e:
        logger.warning("  [KORAY-N] Attribute Filtration failed: %s", e)
        return ""




def generate_fs_paa_map(
    topic: str,
    paa_questions: List[str],
    headings: List[Dict],
    project=None,
    api_key: str = "",
) -> str:
    """Override with a fallback-safe implementation."""
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return "[LLM_FALLBACK]\n" + _fallback_fs_paa_markdown(topic, paa_questions, headings, project)
        if not paa_questions:
            return "[LLM_FALLBACK]\n" + _fallback_fs_paa_markdown(topic, paa_questions, headings, project)

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Ban la chuyen gia Semantic SEO. Nhiem vu: Map PAA Questions vao Heading structure.\n"
            "Tra ve JSON co key rows.\n"
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        h_list = [f"{h['level']}: {h['text']}" for h in headings if isinstance(h, dict) and h.get("level") in ["H2", "H3"]]
        headings_str = "\n".join(h_list[:20])
        paa_str = "\n".join([f"- {q}" for q in paa_questions[:15]])
        user = (
            f"Tu khoa (H1): '{topic}'\n\n"
            f"Heading Structure:\n{headings_str}\n\n"
            f"PAA Questions can map:\n{paa_str}\n"
            "Tra ve JSON theo schema trong system prompt."
        )

        raw = _call_llm(client, model, system, user, max_tokens=1500, response_format={"type": "json_object"})
        import json
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return "[LLM_FALLBACK]\n" + _fallback_fs_paa_markdown(topic, paa_questions, headings, project)

        rows = data.get("rows", [])
        if not rows:
            return "[LLM_FALLBACK]\n" + _fallback_fs_paa_markdown(topic, paa_questions, headings, project)

        lines = ["| PAA Question | Vi tri (H2/H3) | Format | FS Block (<=40 tu) |", "|---|---|---|---|"]
        for row in rows:
            if isinstance(row, dict):
                q = row.get("paa_question", row.get("question", ""))
                h = row.get("heading", row.get("h2", ""))
                fmt = row.get("format", "")
                fs = row.get("fs_block", "")
                lines.append(f"| {q} | {h} | {fmt} | {fs} |")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("  [KORAY-O] FS/PAA Map failed: %s", e)
        return "[LLM_FALLBACK]\n" + _fallback_fs_paa_markdown(topic, paa_questions, headings, project)


def _validate_fs_snippets(brief: dict, max_words: int = 40, sapo_max: int = 120) -> dict:
    """
    Post-process: truncate FS snippets và SAPO vượt giới hạn từ.
    Fixes gap giữa agent instruction (≤40 words) và score enforcement (≤40 words) — now fully aligned.

    Args:
        brief: brief dict chứa micro_briefing list
        max_words: giới hạn từ cho FS snippets thông thường (default 40)
        sapo_max: giới hạn từ cho SAPO (default 120)

    Returns:
        brief dict đã được modified in-place
    """
    micro_raw = brief.get("micro_briefing", [])
    # Bug A fix: normalize dict wrapper {"items": [...]} → flat list [...]
    if isinstance(micro_raw, dict):
        micro = micro_raw.get("items", []) if "items" in micro_raw else list(micro_raw.values())
    elif isinstance(micro_raw, list):
        micro = micro_raw
    else:
        micro = []
    brief["micro_briefing"] = micro  # normalize in-place
    if not micro:
        return brief

    def _compact_fs_fallback(mb: dict, heading_fallback: str = "") -> str:
        """
        Build a short, answer-first fallback when the LLM snippet is missing or too long.
        Priority: analysis/info_gain/bridge (real content) > EAV values > first sentence.
        """
        # Step 1: Try real content sources FIRST (skip snippet itself — it is the fallback target)
        sources = [
            str(mb.get("analysis", "")),
            str(mb.get("info_gain", "")),
            str(mb.get("bridge", "")),
        ]
        for source in sources:
            text = re.sub(r"\s+", " ", source).strip()
            if not text:
                continue
            # Skip placeholder markers
            norm = _normalize_plain_text(text)
            if any(p in norm for p in ["section nay", "theo semantic seo", "khoang trang", "can xac minh"]):
                continue
            # Extract first meaningful sentence
            first_sentence = re.split(r"(?<=[.!?])\s+", text)[0].strip()
            word_cnt = len(first_sentence.split())
            if 10 <= word_cnt <= max_words:
                return first_sentence
            if word_cnt > max_words:
                return _truncate_to_words(first_sentence.split(), max_words)

        # Step 2: Try EAV data for attribute-specific answer
        eav_data = brief.get("eav_table_rows", [])
        if eav_data and heading_fallback:
            heading_norm = _normalize_plain_text(str(heading_fallback or ""))
            for row in eav_data:
                attr = _normalize_plain_text(str(row.get("attribute", "")))
                val = str(row.get("value", "")).strip()
                if attr and val and len(val) > 2 and len(val.split()) <= 6:
                    if attr in heading_norm or heading_norm in attr:
                        return f"{str(row.get('attribute', '')).strip()}: {val}."
            # Broader EAV match: look for any value that fits
            for row in eav_data:
                val = str(row.get("value", "")).strip()
                if val and 3 <= len(val.split()) <= 8 and val != "[CAN XAC MINH]":
                    return f"{str(row.get('attribute', '')).strip()}: {val}."

        # Step 3: Generic answer (last resort)
        heading_text = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", str(heading_fallback or "").strip(), flags=re.IGNORECASE).strip()
        if heading_text:
            return f"{heading_text}: cần được giải thích cụ thể với số liệu, đặc điểm và ngữ cảnh áp dụng rõ ràng."
        return "Thông tin cần được trình bày trực tiếp, ngắn gọn với số liệu và ngữ cảnh cụ thể."

    fs_truncated = 0
    sapo_truncated = False

    for idx, mb in enumerate(micro):
        snippet = str(mb.get("snippet", ""))
        words = snippet.split()
        word_count = len(words)
        heading_name = str(mb.get("heading", mb.get("h2", "")))

        # SAPO: micro[0] — giới hạn 80-120 từ
        if idx == 0:
            if word_count > sapo_max:
                truncated = _truncate_to_words(words, sapo_max)
                mb["snippet"] = truncated
                mb["_sapo_truncated"] = True
                sapo_truncated = True
                logger.info(
                    "[KORAY] SAPO truncated: %d → %d từ",
                    word_count, len(truncated.split())
                )
            elif word_count < 56:
                fallback = _compact_fs_fallback(mb, heading_name)
                mb["snippet"] = fallback
                mb["_sapo_rebuilt"] = True
                logger.info(
                    "[KORAY] SAPO rebuilt: %d → %d từ",
                    word_count, len(fallback.split())
                )
        else:
            # FS snippets thường: giới hạn max_words từ
            if word_count > max_words or word_count < 10:
                fallback = _compact_fs_fallback(mb, heading_name)
                if len(fallback.split()) > max_words:
                    fallback = _truncate_to_words(fallback.split(), max_words)
                mb["snippet"] = fallback
                mb["_truncated"] = True
                fs_truncated += 1
                logger.info(
                    "[KORAY] FS normalized (H2 %s): %d → %d từ",
                    mb.get("heading", mb.get("h2", "?")), word_count, len(fallback.split())
                )
            elif word_count > max_words:
                truncated = _truncate_to_words(words, max_words)
                mb["snippet"] = truncated
                mb["_truncated"] = True
                fs_truncated += 1
                logger.info(
                    "[KORAY] FS truncated (H2 %s): %d → %d từ",
                    mb.get("heading", mb.get("h2", "?")), word_count, len(truncated.split())
                )

    brief["_fs_truncated_count"] = fs_truncated
    brief["_sapo_truncated"] = sapo_truncated
    return brief


def _truncate_to_words(words: list, max_words: int) -> str:
    """
    Truncate word list to max_words, preserving complete sentences.
    Keeps sentences up to 70% of max_words boundary.
    """
    truncated = " ".join(words[:max_words])
    # Find last complete sentence
    last_period = truncated.rfind(".")
    last_qmark = truncated.rfind("?")
    last_emark = truncated.rfind("!")

    cut_pos = max(last_period, last_qmark, last_emark)
    if cut_pos > max_words * 0.6:  # sentence complete if >60% of max_words
        truncated = truncated[:cut_pos + 1]

    return truncated.strip()


def generate_column_audit_report(brief: Dict, project=None) -> str:
    """
    Produce a project-aware audit report that works across industries.
    The report uses the active project's source context as the guardrail.
    """
    lines = ["## 🧭 COLUMN AUDIT REPORT", ""]

    topic = brief.get("topic", "")
    central_entity = brief.get("central_entity", "")
    scope_terms = _build_project_scope_terms(project)
    scope_preview = ", ".join(scope_terms[:8]) if scope_terms else "N/A"

    lines.append("### 1. Audit Scope")
    lines.append("")
    if project:
        lines.append(f"- **Project**: {getattr(project, 'brand_name', '')} | `{getattr(project, 'industry', '') or 'general'}`")
        lines.append(f"- **Topical Map**: {getattr(project, 'topical_map_csv', '') or 'N/A'}")
        lines.append(f"- **Allowed Scope Preview**: {scope_preview}")
    else:
        lines.append("- **Project**: N/A")
    lines.append(f"- **Topic**: {topic}")
    lines.append(f"- **Central Entity**: {central_entity}")
    lines.append("")

    def _row(column: str, status: str, finding: str, fix: str) -> str:
        return f"| {column} | {status} | {finding} | {fix} |"

    lines.append("### 2. Column Audit")
    lines.append("")
    lines.append("| Cột | Trạng thái | Phát hiện | Khuyến nghị |")
    lines.append("|---|---|---|---|")

    keyword_text = f"{topic} {central_entity}"
    keyword_matches = _find_matching_terms(keyword_text, scope_terms)
    keyword_hits = _find_contamination_terms(keyword_text)
    if keyword_hits:
        lines.append(_row("Keyword", "❌", f"Lệch scope: {', '.join(keyword_hits)}", f"Canonicalize theo topical map của project ({scope_preview})"))
    elif project and not keyword_matches:
        lines.append(_row("Keyword", "⚠️", "Chưa thấy keyword match rõ với project scope", "Chỉ dùng keyword nếu nó nằm trong topical map hoặc cùng entity-path với project"))
    else:
        lines.append(_row("Keyword", "✅", f"Match scope: {', '.join(keyword_matches[:3]) if keyword_matches else 'ok'}", "Giữ nguyên"))

    macro_text = _stringify_audit_source(brief.get("macro_context", ""))
    macro_matches = _find_matching_terms(macro_text, scope_terms)
    macro_hits = _find_contamination_terms(macro_text)
    if macro_hits:
        lines.append(_row("Macro Context", "❌", f"Có tín hiệu ngành khác: {', '.join(macro_hits)}", "Rewrite macro context theo industry/main_products của project"))
    elif project and getattr(project, "industry", "") and _normalize_plain_text(project.industry) not in _normalize_plain_text(macro_text):
        lines.append(_row("Macro Context", "⚠️", "Thiếu dấu hiệu ngành của project", "Nhúng industry + main_products + target user vào macro context"))
    else:
        lines.append(_row("Macro Context", "✅", f"Match scope: {', '.join(macro_matches[:3]) if macro_matches else 'ok'}", "OK"))

    network_text = brief.get("query_network_str") or _stringify_audit_source(brief.get("query_network", {}))
    network_matches = _find_matching_terms(network_text, scope_terms)
    network_hits = _find_contamination_terms(network_text)
    if network_hits:
        lines.append(_row("Semantic Query Network", "❌", f"Alien clusters: {', '.join(network_hits)}", "Chỉ giữ clusters cùng ngành với project"))
    elif project and not network_matches:
        lines.append(_row("Semantic Query Network", "⚠️", "Clusters chưa bám mạnh vào scope", "Re-cluster theo topical map + source context của project"))
    else:
        lines.append(_row("Semantic Query Network", "✅", f"Matched terms: {', '.join(network_matches[:3]) if network_matches else 'ok'}", "OK"))

    comp_text = _stringify_audit_source(brief.get("competitor_analysis", {}))
    comp_hits = _find_contamination_terms(comp_text)
    if comp_hits:
        lines.append(_row("Top 3 Đối thủ", "⚠️", f"SERP có thể lẫn vertical khác: {', '.join(comp_hits)}", "Verify top URLs cùng vertical; nếu không, loại bỏ trước khi brief"))
    else:
        lines.append(_row("Top 3 Đối thủ", "✅", "Không thấy tín hiệu cross-domain rõ", "OK"))

    gaps_text = _stringify_audit_source(brief.get("competitor_analysis", {}).get("information_gain", {}))
    gap_hits = _find_contamination_terms(gaps_text)
    if gap_hits:
        lines.append(_row("Content Gaps", "❌", f"Rare headings bị lệch ngành: {', '.join(gap_hits)}", "Chỉ giữ rare headings thuộc topical border của project"))
    else:
        lines.append(_row("Content Gaps", "✅", "Rare headings không thấy lệch scope rõ", "OK"))

    eav_text = _stringify_audit_source(brief.get("eav_table", ""))
    eav_matches = _find_matching_terms(eav_text, scope_terms)
    eav_hits = _find_contamination_terms(eav_text)
    if eav_hits:
        lines.append(_row("EAV Table", "❌", f"Giá trị EAV nhiễm ngành khác: {', '.join(eav_hits)}", "Regenerate EAV bằng nguồn dữ liệu và đơn vị đo đúng ngành project"))
    elif project and not eav_matches:
        lines.append(_row("EAV Table", "⚠️", "EAV chưa thể hiện rõ source vocabulary", "Ràng buộc attributes/value theo lĩnh vực của project"))
    else:
        lines.append(_row("EAV Table", "✅", f"Matched scope: {', '.join(eav_matches[:3]) if eav_matches else 'ok'}", "OK"))

    paa_text = _stringify_audit_source(brief.get("suggested_questions", []))
    paa_hits = _find_contamination_terms(paa_text)
    paa_matches = _find_matching_terms(paa_text, scope_terms)
    if paa_hits:
        lines.append(_row("PAA Questions", "❌", f"Question lệch ngành: {', '.join(paa_hits)}", "Giữ lại PAA chỉ khi cùng ngành và cùng intent path với project"))
    elif project and not paa_matches:
        lines.append(_row("PAA Questions", "⚠️", "PAA còn generic, chưa bám ngành", "Sinh lại PAA từ SERP/topical map của project"))
    else:
        lines.append(_row("PAA Questions", "✅", f"Matched scope: {', '.join(paa_matches[:3]) if paa_matches else 'ok'}", "OK"))

    fspaa_text = _stringify_audit_source(brief.get("fs_paa_map", ""))
    fspaa_hits = _find_contamination_terms(fspaa_text)
    if fspaa_hits:
        lines.append(_row("FS/PAA Map", "❌", f"Mapping lệch ngành: {', '.join(fspaa_hits)}", "Re-map chỉ với PAA hợp lệ của project"))
    else:
        lines.append(_row("FS/PAA Map", "✅", "Không thấy lệch scope rõ", "OK"))

    ngram_text = brief.get("smart_ngrams_str") or _stringify_audit_source(brief.get("content_guidelines", ""))
    ngram_hits = _find_contamination_terms(ngram_text)
    if ngram_hits:
        lines.append(_row("Smart N-Grams", "❌", f"N-gram nhiễm vertical khác: {', '.join(ngram_hits)}", "Chỉ giữ n-grams xuất phát từ entity/attributes của project"))
    else:
        lines.append(_row("Smart N-Grams", "✅", "N-gram chưa thấy drift rõ", "OK"))

    ctx_text = _stringify_audit_source(brief.get("context_vectors_str", ""))
    ctx_matches = _find_matching_terms(ctx_text, scope_terms)
    ctx_hits = _find_contamination_terms(ctx_text)
    if ctx_hits:
        lines.append(_row("Context Vectors & Guidelines", "❌", f"Guidelines có tín hiệu lệch ngành: {', '.join(ctx_hits)}", "Rewrite guidelines bám project source context"))
    elif project and not ctx_matches:
        lines.append(_row("Context Vectors & Guidelines", "⚠️", "Guidelines chưa bám đủ vocabulary của project", "Đưa industry/main_products/topical map vào prompt guidance"))
    else:
        lines.append(_row("Context Vectors & Guidelines", "✅", f"Matched scope: {', '.join(ctx_matches[:3]) if ctx_matches else 'ok'}", "OK"))

    outline_text = _stringify_audit_source(brief.get("heading_structure", []))
    outline_hits = _find_contamination_terms(outline_text)
    if outline_hits:
        lines.append(_row("Structure Outline", "❌", f"H2/H3 lệch scope: {', '.join(outline_hits)}", "Rebuild outline theo topical map của project"))
    else:
        lines.append(_row("Structure Outline", "✅", "Outline chưa thấy drift rõ", "OK"))

    linking_text = _stringify_audit_source(brief.get("internal_linking", {}))
    linking_hits = _find_contamination_terms(linking_text)
    if linking_hits:
        lines.append(_row("Internal Links", "❌", f"Link graph có node lệch ngành: {', '.join(linking_hits)}", "Chỉ link trong cùng topical border/project map"))
    else:
        lines.append(_row("Internal Links", "✅", "Không thấy lệch ngành rõ", "OK"))

    src_alignment = generate_source_context_alignment(brief, project)
    src_hits = _find_contamination_terms(src_alignment)
    if src_hits:
        lines.append(_row("Source Context Alignment", "❌", f"Alignment audit phát hiện contamination: {', '.join(src_hits)}", "Fix source context trước khi xuất brief"))
    else:
        lines.append(_row("Source Context Alignment", "✅", "Checklist source context đã sẵn sàng", "OK"))

    quality_text = _stringify_audit_source(brief.get("koray_quality_score_md", "")) or _stringify_audit_source(brief.get("koray_quality_score", ""))
    score_match = re.search(r"(\d{1,3})/100", quality_text)
    score_val = int(score_match.group(1)) if score_match else 0
    if score_val >= 80:
        lines.append(_row("Koray Quality Score", "✅", f"{score_val}/100", "Giữ nguyên và chỉ tune minor issues"))
    elif score_val >= 60:
        lines.append(_row("Koray Quality Score", "⚠️", f"{score_val}/100", "Cần sửa các cột lệch scope trước khi publish"))
    else:
        lines.append(_row("Koray Quality Score", "❌", f"{score_val}/100", "Rebuild brief theo project topical map + source context"))

    lines.append("")
    lines.append("### 3. Priority Fixes")
    lines.append("")
    lines.append("1. Canonicalize keyword và semantic network theo topical map của project, không theo vertical ngoài scope.")
    lines.append("2. Rewrite PAA / EAV / Structure Outline bám chặt industry, main_products và topical map source của project.")
    lines.append("3. Chỉ giữ internal links và source-context elements thuộc cùng topical border với project active.")

    return "\n".join(lines)
