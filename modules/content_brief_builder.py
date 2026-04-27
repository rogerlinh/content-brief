# -*- coding: utf-8 -*-
"""
content_brief_builder.py - Tổng hợp Content Brief từ kết quả phân tích.

Phase 9: Semantic Polish & Contextualization
- Heading Enrichment (LLM hoặc rule-based)
- Smart N-grams Injection (context-aware, có lọc stopwords)
- Dynamic E-E-A-T (niche-based inline instructions)
"""

import unicodedata


def _remove_diacritics(text: str) -> str:
    """Strip Vietnamese diacritics while preserving ASCII tokens."""
    nfkd = unicodedata.normalize('NFKD', text)
    stripped = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("đ", "d").replace("Đ", "D")


def _token_set(text: str) -> set:
    tokens = re.findall(r"[a-z0-9]{3,}", _remove_diacritics(str(text or "").lower()))
    stop = {"nhung", "cach", "la", "gi", "cho", "voi", "the", "nao", "trong", "cac", "mot", "tai", "ve"}
    return {token for token in tokens if token not in stop}


def _overlap_context_phrase(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))




import logging
import os
import re
from typing import Any, Dict, List, Optional

try:
    import openai
except ImportError:  # pragma: no cover - optional dependency in some test contexts
    openai = None

from modules.outline_content_adapter import build_outline_content_framework
from modules.outline_content_prompt_catalog import (
    build_agent1_outline_prompts,
    build_agent2_semantic_prompts,
    build_agent3_micro_brief_prompts,
    build_writer_brief_block,
)
from modules.semantic_purity import (
    build_query_state,
    classify_gap_map,
    curated_semantic_terms,
    derive_consensus_facts,
    derive_decision_blockers,
    derive_dominant_user_task,
    derive_misinterpretation_risks,
    derive_supporting_tasks,
    filter_eav_rows,
    filter_pure_phrases,
    is_clean_fact_candidate,
    normalize_text,
    overlap_score,
    sanitize_fact_row,
)
from modules.eav_verifier import (
    build_verified_eav_rows,
    choose_heading_anchor_plan,
    summarize_eav_quality,
)
from modules.eav_enrichment import (
    extract_competitor_fact_rows,
    render_eav_markdown,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  STOPWORDS & N-GRAM FILTER
# ══════════════════════════════════════════════

# Từ vô nghĩa cần loại bỏ khỏi danh sách N-grams
NGRAM_STOPWORDS = {
    "tuy nhiên", "ngoài ra", "bên cạnh", "trong đó", "chẳng hạn",
    "vì vậy", "do đó", "cũng như", "hơn nữa", "mặc dù",
    "thể sử dụng", "lại lợi ích", "độ ăn",  # fragments vô nghĩa
}


# ══════════════════════════════════════════════
#  NICHE DETECTION
# ══════════════════════════════════════════════

NICHE_KEYWORDS = {}


def detect_niche(keyword: str, project_industry: str = "") -> str:
    """Compatibility hook: source context is passed as evidence, not mapped to fixed niches."""
    return "general"

def _normalize_question_list(raw_questions) -> List[str]:
    """Normalize PAA / FAQ payloads into a clean list of strings."""
    if raw_questions is None:
        return []

    if isinstance(raw_questions, dict):
        raw_questions = (
            raw_questions.get("items")
            or raw_questions.get("questions")
            or raw_questions.get("paa_questions")
            or raw_questions.get("faq_questions")
            or []
        )

    if isinstance(raw_questions, str):
        text = raw_questions.strip()
        if not text:
            return []
        try:
            import json as _json
            parsed = _json.loads(text)
            return _normalize_question_list(parsed)
        except Exception:
            lines = [line.strip().lstrip("-•* ").strip() for line in text.splitlines()]
            raw_questions = [line for line in lines if line]

    if not isinstance(raw_questions, (list, tuple, set)):
        raw_questions = [raw_questions]

    questions = []
    for item in raw_questions:
        if item is None:
            continue
        if isinstance(item, dict):
            nested = (
                item.get("items")
                or item.get("questions")
                or item.get("paa_questions")
                or item.get("faq_questions")
            )
            if nested:
                questions.extend(_normalize_question_list(nested))
                continue
            value = (
                item.get("faq_question")
                or item.get("question")
                or item.get("text")
                or item.get("title")
                or item.get("value")
                or ""
            )
        else:
            value = str(item)

        value = str(value).strip()
        if not value:
            continue

        if value.startswith("{") and value.endswith("}"):
            try:
                import json as _json
                parsed = _json.loads(value)
                nested = _normalize_question_list(parsed)
                if nested:
                    questions.extend(nested)
                    continue
            except Exception:
                pass

        cleaned = value.replace("\r", "\n").strip()
        if "\n" in cleaned and len(cleaned.splitlines()) > 1:
            for line in cleaned.splitlines():
                line = line.strip().lstrip("-•* ").strip()
                line = line.lstrip("0123456789.-) \t").strip()
                if line:
                    questions.append(line)
        else:
            questions.append(cleaned.lstrip("0123456789.-) \t").strip())

    deduped = []
    seen = set()
    for q in questions:
        if q:
            key = q.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(q)
    return deduped


def _build_project_scope_brief(project) -> str:
    """Create a compact project scope string for LLM prompts."""
    if not project:
        return ""

    parts = [
        f"Brand: {getattr(project, 'brand_name', '') or ''}".strip(),
        f"Industry: {getattr(project, 'industry', '') or ''}".strip(),
        f"Main products: {getattr(project, 'main_products', '') or ''}".strip(),
        f"USP: {getattr(project, 'usp', '') or ''}".strip(),
        f"Target customers: {getattr(project, 'target_customers', '') or ''}".strip(),
        f"Topical map: {getattr(project, 'topical_map_csv', '') or ''}".strip(),
    ]
    return " | ".join([p for p in parts if not p.endswith(":") and p.split(":", 1)[-1].strip()])


def _fallback_project_faq_questions(
    topic: str,
    entity: str,
    project=None,
    raw_questions: List[str] = None,
) -> List[str]:
    """Prefer real PAA/search questions; create only minimal generic fallbacks."""
    raw_questions = _normalize_question_list(raw_questions or [])
    if raw_questions:
        return raw_questions[:5]

    base = (entity or topic or "chu de nay").strip()
    return [
        f"{base} la gi?",
        f"{base} can duoc hieu theo boi canh nao?",
        f"Nguoi doc can kiem chung dieu gi ve {base}?",
    ]

def _filter_project_contamination_terms(
    items: List[str],
    project=None,
    topic: str = "",
) -> List[str]:
    """Normalize and dedupe project-facing lists without industry blacklists."""
    clean_items: List[str] = []
    seen = set()
    for item in items or []:
        text = str(item).strip()
        if not text:
            continue
        norm = _remove_diacritics(text.lower())
        if norm in seen:
            continue
        seen.add(norm)
        clean_items.append(text)
    return clean_items

def _derive_outline_consensus_signals(
    competitor_data: Optional[Dict],
    project=None,
    topic: str = "",
) -> Dict[str, List[str]]:
    """
    Derive consensus and gap signals from competitor analysis.

    consensus_points: headings repeated across competitors.
    gap_h2_candidates: broad gaps that can legitimately become H2s.
    gap_h3_candidates: narrow gaps better used as H3/support.
    """
    if not competitor_data or not isinstance(competitor_data, dict):
        return {
            "consensus_points": [],
            "gap_h2_candidates": [],
            "gap_h3_candidates": [],
            "competitor_archetypes": [],
            "archetype_h2_priorities": [],
            "coverage_notes": [],
        }

    info_gain = competitor_data.get("information_gain", {})
    common_headings = _filter_project_contamination_terms(
        [str(h).strip() for h in competitor_data.get("common_headings", []) if str(h).strip()],
        project=project,
        topic=topic,
    )[:8]
    rare_headings = _filter_project_contamination_terms(
        [str(g.get("heading", g) if isinstance(g, dict) else g) for g in info_gain.get("rare_headings", [])],
        project=project,
        topic=topic,
    )[:12]

    def _is_broad_gap(text: str) -> bool:
        norm = _remove_diacritics(str(text or "").lower())
        tokens = [t for t in re.split(r"[^0-9A-Za-z\u00C0-\u1EF9]+", norm) if t]
        first_token = tokens[0] if tokens else ""
        question_shape = norm.endswith("?") or first_token in {
            "ai", "cai", "co", "khi", "lam", "nen", "tai", "vi",
            "what", "when", "where", "who", "why", "how",
        }
        return len(tokens) >= 7 and not question_shape

    gap_h2_candidates = []
    gap_h3_candidates = []
    for gap in rare_headings:
        if _is_broad_gap(gap):
            gap_h2_candidates.append(gap)
        else:
            gap_h3_candidates.append(gap)

    if not gap_h2_candidates and rare_headings:
        gap_h2_candidates = rare_headings[: min(3, len(rare_headings))]
        gap_h3_candidates = [g for g in rare_headings if g not in gap_h2_candidates]

    archetype_summary = competitor_data.get("archetype_summary", {}) if isinstance(competitor_data.get("archetype_summary"), dict) else {}
    top_archetypes = archetype_summary.get("top_archetypes", []) if isinstance(archetype_summary.get("top_archetypes", []), list) else []
    competitor_archetypes = []
    archetype_h2_priorities = []
    for item in top_archetypes[:4]:
        if not isinstance(item, dict):
            continue
        archetype = str(item.get("archetype", "") or "").strip().lower()
        if not archetype:
            continue
        competitor_archetypes.append(archetype)

    return {
        "consensus_points": common_headings[:6],
        "gap_h2_candidates": gap_h2_candidates[:5],
        "gap_h3_candidates": gap_h3_candidates[:7],
        "competitor_archetypes": competitor_archetypes[:4],
        "archetype_h2_priorities": archetype_h2_priorities[:4],
        "coverage_notes": [
            f"Consensus headings: {len(common_headings)}",
            f"Broad gap candidates: {len(gap_h2_candidates)}",
            f"Narrow gap candidates: {len(gap_h3_candidates)}",
            ("Top archetypes: " + ", ".join(competitor_archetypes[:4])) if competitor_archetypes else "Top archetypes: none",
        ],
    }


def _parse_eav_rows(eav_table: str) -> List[Dict[str, str]]:
    """Parse markdown EAV table into rows."""
    rows: List[Dict[str, str]] = []
    if not eav_table:
        return rows
    for line in str(eav_table).splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "Entity" in line:
            continue
        parts = [p.strip() for p in line.split("|") if p.strip()]
        if len(parts) < 3:
            continue
        rows.append({
            "entity": parts[0],
            "attribute": parts[1],
            "value": parts[2],
        })
    return rows




def _collect_prompt_semantic_terms(
    topic: str,
    intent: str,
    project=None,
    candidates: Optional[List[str]] = None,
    limit: int = 10,
) -> List[str]:
    """Keep semantic support terms from current evidence without fixed industry blockers."""
    clean: List[str] = []
    seen = set()
    for raw in candidates or []:
        text = str(raw or "").strip()
        if not text:
            continue
        norm = _remove_diacritics(text.lower())
        if norm in seen:
            continue
        seen.add(norm)
        clean.append(text)
        if len(clean) >= limit:
            break
    return clean


def _infer_topic_focus_pack(
    topic: str,
    intent: str,
    consensus_points: Optional[List[str]] = None,
    gap_h2_candidates: Optional[List[str]] = None,
    gap_h3_candidates: Optional[List[str]] = None,
    eav_rows: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, List[str] | str]:
    """Infer a generic article task from current evidence, not fixed vertical terminology."""
    evidence_terms: List[str] = []
    for item in (consensus_points or []) + (gap_h2_candidates or []) + (gap_h3_candidates or []):
        text = str(item).strip()
        if text:
            evidence_terms.append(text)
    for row in eav_rows or []:
        attr = str(row.get("attribute", "")).strip()
        if attr:
            evidence_terms.append(attr)

    semantic_terms = _collect_prompt_semantic_terms(topic, intent, candidates=evidence_terms, limit=10)
    return {
        "search_task": (
            "Nguoi doc can hieu dung central entity, cac thuoc tinh duoc chung minh boi SERP/source context, "
            "va cach ap dung thong tin vao dung boi canh tim kiem."
        ),
        "must_cover": semantic_terms[:6],
        "avoid_drift": [
            "Khong dua vao outline concept khong xuat phat tu keyword, SERP, PAA, competitor evidence, EAV hoac source context hien tai.",
            "Khong chen lop noi dung theo nganh neu lop do khong duoc du lieu hien tai chung minh.",
        ],
        "preferred_order": [],
        "semantic_terms": semantic_terms,
        "gap_h2_candidates": [str(x).strip() for x in (gap_h2_candidates or []) if str(x).strip()][:5],
        "gap_h3_candidates": [str(x).strip() for x in (gap_h3_candidates or []) if str(x).strip()][:7],
    }


def _fact_semantic_role(text: str) -> str:
    norm = _remove_diacritics(str(text or "").lower())
    if any(sig in norm for sig in ["chien luoc", "dai han", "ngan han", "trung han"]):
        return "strategy"
    if any(sig in norm for sig in ["la gi", "dinh nghia", "khai niem", "pham vi", "ban chat"]):
        return "definition"
    if any(sig in norm for sig in ["thanh phan", "cau tao", "cau truc", "bo phan", "thuoc tinh", "yeu to"]):
        return "attribute"
    if any(sig in norm for sig in ["phan loai", "cac loai", "loai hinh", "nhom", "dang", "cong nghe"]):
        return "classification"
    if any(sig in norm for sig in ["rui ro", "luu y", "sai lam", "hieu lam", "canh bao", "khong nen"]):
        return "risk"
    if any(sig in norm for sig in ["von", "chi phi", "bao nhieu", "tieu chi", "chon", "mua", "danh gia", "gia ca", "gia ban"]):
        return "decision"
    if any(sig in norm for sig in ["hoat dong", "co che", "quy trinh", "cach thuc", "van hanh"]):
        return "process"
    if any(sig in norm for sig in ["khi nao", "dieu kien", "phu hop", "ap dung", "ngu canh"]):
        return "condition"
    if any(sig in norm for sig in ["so sanh", "vs", "khac nhau", "diem khac", "bang danh gia"]):
        return "comparison"
    if any(sig in norm for sig in ["loi ich", "tac dong", "anh huong", "ket qua", "ung dung"]):
        return "impact"
    if any(sig in norm for sig in ["faq", "cau hoi", "?"]):
        return "faq"
    return "support"


def _outline_intent_family(intent: str, topic: str) -> str:
    norm = _remove_diacritics(f"{intent} {topic}".lower())
    if any(sig in norm for sig in [" so sanh ", " vs ", "comparison", "khac nhau"]):
        return "comparison"
    if any(sig in norm for sig in ["la gi", "what", "dinh nghia", "khai niem"]):
        return "what_is"
    if any(sig in norm for sig in ["how-to", "cach ", "huong dan", "quy trinh"]):
        return "how_to"
    if any(sig in norm for sig in ["commercial", "transactional", "mua", "chon", "bao gia", "gia bao nhieu"]):
        return "decision"
    if "informational" in norm:
        return "what_is"
    return "informational"


def _semantic_role_order(intent: str, topic: str, role_counts: Optional[Dict[str, int]] = None) -> List[str]:
    family = _outline_intent_family(intent, topic)
    if family == "comparison":
        base = ["definition", "attribute", "classification", "process", "comparison", "condition", "decision", "risk", "strategy", "faq"]
    elif family == "how_to":
        base = ["definition", "attribute", "classification", "condition", "process", "risk", "decision", "strategy", "faq"]
    elif family == "decision":
        base = ["definition", "attribute", "classification", "process", "condition", "comparison", "decision", "risk", "strategy", "faq"]
    elif family == "what_is":
        base = ["definition", "attribute", "classification", "process", "condition", "comparison", "decision", "risk", "strategy", "faq"]
    else:
        base = ["definition", "attribute", "classification", "process", "impact", "condition", "comparison", "decision", "risk", "strategy", "faq"]

    counts = role_counts or {}
    # Only add optional roles when evidence supports them. Core roles remain as the semantic backbone.
    optional = ["impact", "comparison", "decision", "risk", "strategy"]
    ordered = []
    for role in base:
        if role in optional and counts.get(role, 0) <= 0 and role not in {"decision", "risk"}:
            continue
        if role not in ordered:
            ordered.append(role)
    return ordered


def _role_label(role: str) -> str:
    labels = {
        "definition": "Entity clarity: xác định thực thể, phạm vi và điểm dễ nhầm.",
        "attribute": "Attribute depth: giải thích thuộc tính, cấu phần hoặc tiêu chí nhận diện.",
        "classification": "Classification: nhóm loại hình/công nghệ/dạng biến thể được dữ kiện hỗ trợ.",
        "process": "Mechanism: cách hoạt động, quy trình hoặc quan hệ nhân quả.",
        "condition": "Context fit: điều kiện áp dụng và bối cảnh nên/không nên dùng.",
        "comparison": "Comparison: tiêu chí so sánh giúp phân biệt lựa chọn hoặc khái niệm gần nghĩa.",
        "decision": "Decision support: tiêu chí đánh giá, chi phí, lựa chọn hoặc bước kiểm chứng.",
        "risk": "Risk and misconception: hiểu lầm, rủi ro, giới hạn dữ kiện.",
        "strategy": "Strategy: cách tiếp cận hoặc chiến lược chỉ nên đặt sau khi người đọc đã hiểu thực thể, cơ chế, chi phí và rủi ro.",
        "impact": "Outcome: lợi ích, tác động hoặc hệ quả khi áp dụng đúng bối cảnh.",
        "faq": "Support questions: câu hỏi đuôi không lặp lại H2 chính.",
    }
    return labels.get(role, "Supporting context.")


def _build_semantic_blueprint(
    topic: str,
    intent: str,
    *,
    project=None,
    consensus_points: Optional[List[str]] = None,
    gap_h2_candidates: Optional[List[str]] = None,
    gap_h3_candidates: Optional[List[str]] = None,
    paa_questions: Optional[List[str]] = None,
    eav_rows: Optional[List[Dict[str, Any]]] = None,
    semantic_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Classify evidence into semantic roles before outline synthesis."""
    entity = _topic_core(topic)
    evidence_items: List[Dict[str, str]] = []

    def add_items(items: Optional[List[Any]], source: str) -> None:
        for raw in items or []:
            text = str(raw or "").strip()
            if text:
                evidence_items.append({"text": text, "source": source, "role": _fact_semantic_role(text)})

    add_items(consensus_points, "consensus")
    add_items(gap_h2_candidates, "gap_h2")
    add_items(gap_h3_candidates, "gap_h3")
    add_items(paa_questions, "paa")
    add_items(semantic_terms, "semantic_terms")
    for row in eav_rows or []:
        if not isinstance(row, dict):
            continue
        attr = str(row.get("attribute", "")).strip()
        value = str(row.get("value", "")).strip()
        if attr or value:
            evidence_items.append({
                "text": f"{attr}: {value}".strip(": "),
                "source": "eav",
                "role": _fact_semantic_role(f"{attr} {value}"),
            })

    role_counts: Dict[str, int] = {}
    role_facts: Dict[str, List[str]] = {}
    for item in evidence_items:
        role = item["role"]
        role_counts[role] = role_counts.get(role, 0) + 1
        role_facts.setdefault(role, [])
        if item["text"] not in role_facts[role]:
            role_facts[role].append(item["text"])

    source_context_available = bool(
        _project_field(project, "industry")
        or _project_field(project, "main_products")
        or _project_field(project, "target_customers")
        or _project_field(project, "brand_name")
        or _project_field(project, "topical_map_csv")
    )
    role_order = _semantic_role_order(intent, topic, role_counts)
    role_specs = [
        {
            "role": role,
            "why": _role_label(role),
            "facts": role_facts.get(role, [])[:4],
            "priority": idx + 1,
        }
        for idx, role in enumerate(role_order)
    ]
    return {
        "central_entity": entity,
        "intent_family": _outline_intent_family(intent, topic),
        "source_context_available": source_context_available,
        "evidence_priority": ["source_context", "project_topical_map", "serp_consensus", "competitor_gaps", "paa", "llm_fallback"],
        "role_order": role_order,
        "role_counts": role_counts,
        "role_facts": role_facts,
        "role_specs": role_specs,
        "must_not": [
            "Do not copy raw SERP snippets, brand snippets, or internal instructions into headings.",
            "Do not place benefits, costs, or risks before the reader understands the entity and its attributes/process.",
            "Do not promote a narrow side topic to H2 unless source context or SERP evidence proves it belongs to the main query.",
        ],
    }

def _heading_semantic_kind(text: str) -> str:
    lower = _remove_diacritics(str(text or "").lower())
    if ":" in lower:
        suffix = lower.split(":", 1)[1].strip()
        if len(suffix.split()) >= 2:
            lower = suffix
    if any(sig in lower for sig in ["faq", "cau hoi"]):
        return "faq"
    if any(sig in lower for sig in ["so sanh", "bang danh gia", "khac nhau", "vs"]):
        return "comparison"
    if any(sig in lower for sig in ["phan loai", "cac loai", "loai hinh", "cong nghe"]):
        return "attribute"
    if any(sig in lower for sig in ["dinh nghia", "khai niem", "la gi"]):
        return "definition"
    if any(sig in lower for sig in ["thanh phan", "cau truc", "yeu to", "bo phan"]):
        return "attribute"
    if any(sig in lower for sig in ["rui ro", "luu y", "sai lam", "canh bao"]):
        return "risk"
    if any(sig in lower for sig in ["tac dong", "anh huong", "loi nhuan", "ket qua", "chien luoc", "toi uu", "phu hop"]):
        return "impact"
    if any(sig in lower for sig in ["cach tinh", "cach su dung", "bang phan tich", "phuong phap", "co che", "hoat dong", "quy trinh", "van hanh"]):
        return "calculation"
    if "khong nen" in lower:
        return "risk"
    return "attribute"


def _preferred_flow_stage(item: str) -> List[str]:
    norm = _remove_diacritics(str(item or "").lower())
    stages: List[str] = []
    if any(sig in norm for sig in ["definition", "clarification", "dinh nghia", "khai niem", "scope"]):
        stages.append("definition")
    if any(sig in norm for sig in ["core attributes", "attribute", "forms", "classification", "market structure", "thuoc tinh", "phan loai"]):
        stages.append("attribute")
    if any(sig in norm for sig in ["how it works", "process", "conditions", "steps", "co che", "quy trinh", "dieu kien"]):
        stages.append("calculation")
    if any(sig in norm for sig in ["classification", "phan loai", "cac loai", "loai hinh"]):
        stages.append("classification")
    if any(sig in norm for sig in ["decision", "criteria", "cost", "capital", "tieu chi", "chi phi", "von"]):
        stages.append("decision")
    if any(sig in norm for sig in ["comparison", "trade off", "difference", "evaluation", "so sanh", "khac biet"]):
        stages.append("comparison")
    if any(sig in norm for sig in ["application", "benefit", "impact", "fit", "chien luoc", "loi ich", "ung dung"]):
        stages.append("impact")
    if any(sig in norm for sig in ["risk", "caution", "warning", "luu y", "rui ro", "canh bao"]):
        stages.append("risk")
    if any(sig in norm for sig in ["strategy", "chien luoc", "dai han", "ngan han"]):
        stages.append("strategy")
    if any(sig in norm for sig in ["faq", "support question", "supp", "cau hoi"]):
        stages.append("faq")
    if not stages:
        stages.append("attribute")
    deduped: List[str] = []
    seen = set()
    for stage in stages:
        if stage in seen:
            continue
        seen.add(stage)
        deduped.append(stage)
    return deduped


def _replace_heading_marker(text: str, target: str) -> str:
    cleaned = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", str(text or "").strip(), flags=re.IGNORECASE)
    if not cleaned:
        return cleaned
    return f"[{target}] {cleaned}"


def _strip_heading_prefixes(text: str) -> str:
    cleaned = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", str(text or "").strip(), flags=re.IGNORECASE)
    # Remove topic echo prefixes without touching in-heading brackets.
    cleaned = re.sub(r"^(?:\[[^\]]{2,80}\]\s*)+", "", cleaned).strip()
    return cleaned


def _group_outline_blocks(headings: List[Dict]) -> tuple[List[Dict], List[Dict[str, Any]]]:
    h1_items: List[Dict] = []
    blocks: List[Dict[str, Any]] = []
    current_block: Optional[Dict[str, Any]] = None
    for item in headings:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "")).upper()
        if level == "H1":
            h1_items.append(item)
            continue
        if level == "H2":
            current_block = {"h2": dict(item), "children": []}
            blocks.append(current_block)
            continue
        if current_block is not None:
            current_block["children"].append(dict(item))
    return h1_items, blocks


def _is_support_block(text: str) -> bool:
    norm = _remove_diacritics(str(text or "").lower())
    return "[supp]" in norm or _heading_semantic_kind(text) == "faq"


def _outline_flow_priority(preferred_order: List[str]) -> Dict[str, int]:
    priorities: Dict[str, int] = {}
    cursor = 0
    for item in preferred_order or []:
        for stage in _preferred_flow_stage(item):
            if stage not in priorities:
                priorities[stage] = cursor
            if stage == "calculation":
                priorities.setdefault("process", cursor)
        cursor += 1
    fallback = ["definition", "attribute", "classification", "process", "calculation", "condition", "comparison", "decision", "impact", "risk", "strategy", "faq"]
    for stage in fallback:
        if stage not in priorities:
            priorities[stage] = cursor
            cursor += 1
    return priorities


def _align_outline_to_preferred_flow(
    headings: List[Dict],
    preferred_order: Optional[List[str]] = None,
) -> List[Dict]:
    if not headings:
        return headings

    h1_items, blocks = _group_outline_blocks(headings)
    if len(blocks) < 2:
        return headings

    priorities = _outline_flow_priority(preferred_order or [])
    main_blocks: List[Dict[str, Any]] = []
    supp_blocks: List[Dict[str, Any]] = []
    risk_seen = 0

    for index, block in enumerate(blocks):
        h2_text = str(block["h2"].get("text", "")).strip()
        kind = _heading_semantic_kind(h2_text)
        block["kind"] = kind
        block["index"] = index
        if _is_support_block(h2_text):
            block["h2"]["text"] = _replace_heading_marker(h2_text, "SUPP")
            supp_blocks.append(block)
            continue
        if kind == "risk":
            risk_seen += 1
            if risk_seen > 1:
                block["h2"]["text"] = _replace_heading_marker(h2_text, "SUPP")
                supp_blocks.append(block)
                continue
        block["h2"]["text"] = _replace_heading_marker(h2_text, "MAIN")
        main_blocks.append(block)

    if not main_blocks:
        return headings

    main_blocks.sort(
        key=lambda block: (
            priorities.get(str(block.get("kind") or "attribute"), len(priorities) + 10),
            int(block.get("index", 0)),
        )
    )
    supp_blocks.sort(
        key=lambda block: (
            1 if block.get("kind") == "faq" else 0,
            int(block.get("index", 0)),
        )
    )

    result: List[Dict] = []
    result.extend(h1_items)
    for block in main_blocks + supp_blocks:
        result.append(block["h2"])
        result.extend(block["children"])
    return result


def _heading_blueprint_role(text: str) -> str:
    text = _strip_heading_prefixes(text)
    direct_role = _fact_semantic_role(text)
    if direct_role in {"classification", "process", "condition", "comparison", "decision", "risk", "impact"}:
        return direct_role
    kind = _heading_semantic_kind(text)
    if kind == "calculation":
        norm = _remove_diacritics(str(text or "").lower())
        if any(sig in norm for sig in ["hoat dong", "co che", "quy trinh", "van hanh"]):
            return "process"
        if any(sig in norm for sig in ["khi nao", "dieu kien", "phu hop", "ap dung"]):
            return "condition"
        return "process"
    if kind == "attribute":
        role = _fact_semantic_role(text)
        return role if role in {"attribute", "classification", "condition", "decision"} else "attribute"
    if kind == "impact":
        return "impact"
    return kind


def _semantic_h2_text(entity: str, role: str, support: bool = False) -> str:
    prefix = "[SUPP] " if support else "[MAIN] "
    templates = {
        "definition": f"{entity} là gì và phạm vi cần hiểu",
        "attribute": f"{entity} gồm những thuộc tính, cấu phần hoặc yếu tố nào",
        "classification": f"{entity} được phân loại theo những nhóm nào",
        "process": f"{entity} hoạt động như thế nào",
        "condition": f"Khi nào {entity} phù hợp với ngữ cảnh của người đọc",
        "comparison": f"So sánh các lựa chọn hoặc biến thể liên quan đến {entity}",
        "decision": f"Tiêu chí đánh giá {entity} phù hợp",
        "impact": f"{entity} tạo ra lợi ích hoặc tác động nào trong bối cảnh áp dụng",
        "risk": f"Những hiểu lầm, rủi ro hoặc sai lầm phổ biến về {entity}",
        "strategy": f"Chiến lược tiếp cận {entity} theo từng mục tiêu",
        "faq": "Câu hỏi thường gặp về chủ đề này",
    }
    return prefix + templates.get(role, f"{entity}: nhung diem can lam ro")


def _semantic_h3_children(entity: str, role: str, facts: Optional[List[str]] = None) -> List[Dict[str, str]]:
    facts = [str(x).strip() for x in (facts or []) if str(x).strip()]
    child_map = {
        "definition": [
            f"{entity} khac gi voi cac khai niem gan nghia?",
            f"Pham vi nao can duoc gioi han truoc khi viet?",
        ],
        "attribute": [
            "Thuoc tinh nao giup nhan dien dung thuc the chinh?",
            "Yeu to nao lam thay doi cach ap dung trong thuc te?",
        ],
        "classification": [
            "Cac nhom chinh khac nhau o diem nao?",
            "Khi nao moi nhom tro nen phu hop?",
        ],
        "process": [
            "Các bước, cơ chế hoặc quan hệ nhân quả chính là gì?",
            "Điểm nào cần kiểm chứng bằng dữ liệu trước khi kết luận?",
        ],
        "condition": [
            "Dieu kien nao lam thong tin nay dung hoac sai?",
            "Ngu canh nao khong nen ap dung truc tiep?",
        ],
        "comparison": [
            "Tieu chi so sanh nao quan trong nhat?",
            "Khac biet nao anh huong den quyet dinh cua nguoi doc?",
        ],
        "decision": [
            "Nguoi doc can kiem tra tieu chi nao truoc khi chon?",
            "Chi phi, nguon luc hoac dieu kien nao can duoc tinh den?",
        ],
        "impact": [
            "Loi ich nao chi dung trong mot so dieu kien?",
            "Tac dong nao can duoc giai thich theo boi canh?",
        ],
        "risk": [
            "Hiểu lầm nào dễ khiến người đọc ra quyết định sai?",
            "Giới hạn dữ liệu nào cần nói rõ?",
        ],
        "strategy": [
            "Chiến lược nào phù hợp với từng mục tiêu và khẩu vị rủi ro?",
            "Điều kiện nào cần có trước khi áp dụng chiến lược này?",
        ],
        "faq": [
            f"{entity} can duoc hieu theo boi canh nao?",
            f"Khi nao nen tim them du lieu truoc khi ap dung {entity}?",
        ],
    }
    selected = facts[:2] if facts else child_map.get(role, [])[:2]
    return [{"level": "H3", "text": item} for item in selected if item]


def _apply_semantic_outline_gate(
    headings: List[Dict],
    topic: str,
    semantic_reasoning: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    """Enforce semantic roles without forcing every topic into one fixed template."""
    if not headings:
        return headings
    reasoning = semantic_reasoning if isinstance(semantic_reasoning, dict) else {}
    blueprint = reasoning.get("semantic_blueprint", {}) if isinstance(reasoning.get("semantic_blueprint"), dict) else {}
    role_order = [str(x).strip() for x in blueprint.get("role_order", []) if str(x).strip()]
    if not role_order:
        role_order = _semantic_role_order("", topic)
    role_priority = {role: idx for idx, role in enumerate(role_order)}
    role_facts = blueprint.get("role_facts", {}) if isinstance(blueprint.get("role_facts"), dict) else {}
    entity = str(blueprint.get("central_entity") or _topic_core(topic)).strip()

    h1_items, blocks = _group_outline_blocks(headings)
    if not blocks:
        return headings

    kept: List[Dict[str, Any]] = []
    seen_roles: set[str] = set()
    seen_keys: set[str] = set()
    for idx, block in enumerate(blocks):
        h2_text = str(block["h2"].get("text", "")).strip()
        role = _heading_blueprint_role(h2_text)
        key = _remove_diacritics(_strip_heading_prefixes(h2_text).lower()).split(":", 1)[0].strip()
        if key in seen_keys:
            continue
        if role == "definition" and role in seen_roles:
            continue
        if role == "impact" and "process" not in seen_roles and "attribute" not in seen_roles:
            block["defer_until"] = role_priority.get("impact", 99)
        seen_keys.add(key)
        seen_roles.add(role)
        block["role"] = role
        block["index"] = idx
        kept.append(block)

    mandatory_roles = [role for role in role_order if role in {"definition", "attribute", "classification", "process"}]
    existing_roles = {str(block.get("role")) for block in kept}
    for role in mandatory_roles:
        if role in existing_roles:
            continue
        if role == "classification" and not role_facts.get(role):
            continue
        support = role in {"risk", "faq"}
        kept.append({
            "h2": {"level": "H2", "text": _semantic_h2_text(entity, role, support=support)},
            "children": _semantic_h3_children(entity, role, role_facts.get(role, [])),
            "role": role,
            "index": 100 + len(kept),
        })
        existing_roles.add(role)

    risk_required = (
        "risk" in role_order
        and (
            bool(reasoning.get("decision_blockers"))
            or bool(reasoning.get("misinterpretation_risks"))
            or bool(role_facts.get("risk"))
        )
    )
    existing_roles = {str(block.get("role")) for block in kept}
    if risk_required and "risk" not in existing_roles:
        kept.append({
            "h2": {"level": "H2", "text": _semantic_h2_text(entity, "risk", support=True)},
            "children": _semantic_h3_children(entity, "risk", role_facts.get("risk", [])),
            "role": "risk",
            "index": 200 + len(kept),
        })
        existing_roles.add("risk")

    if not any(str(block.get("role")) in {"faq", "risk"} or _is_support_block(block["h2"].get("text", "")) for block in kept):
        support_role = "risk" if "risk" in role_order else "faq"
        kept.append({
            "h2": {"level": "H2", "text": _semantic_h2_text(entity, support_role, support=True)},
            "children": _semantic_h3_children(entity, support_role, role_facts.get(support_role, [])),
            "role": support_role,
            "index": 200 + len(kept),
        })

    main_blocks: List[Dict[str, Any]] = []
    supp_blocks: List[Dict[str, Any]] = []
    for block in kept:
        role = str(block.get("role") or _heading_blueprint_role(block["h2"].get("text", "")))
        h2_text = str(block["h2"].get("text", "")).strip()
        if role == "faq" or _is_support_block(h2_text):
            block["h2"]["text"] = _replace_heading_marker(h2_text, "SUPP")
            supp_blocks.append(block)
        else:
            block["h2"]["text"] = _replace_heading_marker(h2_text, "MAIN")
            main_blocks.append(block)

    for block in main_blocks + supp_blocks:
        block["h2"]["text"] = _sanitize_outline_heading_text(block["h2"].get("text", ""), level="H2")
        for child in block.get("children", []):
            child["text"] = _sanitize_outline_heading_text(child.get("text", ""), level=str(child.get("level", "H3")))

    main_blocks.sort(key=lambda block: (role_priority.get(str(block.get("role")), 99), int(block.get("index", 0))))
    supp_blocks.sort(key=lambda block: (role_priority.get(str(block.get("role")), 99), int(block.get("index", 0))))

    result: List[Dict] = []
    result.extend(h1_items)
    for block in main_blocks + supp_blocks:
        result.append(block["h2"])
        result.extend(block.get("children", []))
    return result or headings


def _project_field(project, field: str) -> str:
    if project is None:
        return ""
    if isinstance(project, dict):
        return str(project.get(field, "") or "")
    return str(getattr(project, field, "") or "")


def _topic_core(topic: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(topic or "").strip())
    cleaned = re.sub(r"\s+là\s+gì\??\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+la\s+gi\??\s*$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or str(topic or "").strip()


def _title_case_vi(text: str) -> str:
    return " ".join(part[:1].upper() + part[1:] for part in str(text or "").split())


def _append_outline_block(result: List[Dict], h2: str, h3_items: List[str]) -> None:
    result.append({"level": "H2", "text": h2})
    for h3 in h3_items:
        if str(h3 or "").strip():
            result.append({"level": "H3", "text": str(h3).strip()})


def _faq_questions_not_in_body(candidates: List[str], body_h3s: List[str], fallback: List[str], limit: int = 3) -> List[str]:
    body_norms = {_remove_diacritics(str(item or "").lower()).strip(" ?") for item in body_h3s}
    selected: List[str] = []
    seen = set()
    for item in list(candidates or []) + fallback:
        text = str(item or "").strip()
        norm = _remove_diacritics(text.lower()).strip(" ?")
        if not text or norm in seen or norm in body_norms:
            continue
        seen.add(norm)
        selected.append(text)
        if len(selected) >= limit:
            break
    return selected


def _neutralize_cross_industry_phrasing(text: str) -> str:
    """Remove finance-colored wording when a neutral phrase is enough."""
    text = re.sub(r"^(\s*(?:\[(?:MAIN|SUPP)\]\s*)?)Khái niệm\s+(Những|Các)\s+", r"\1\2 ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bchi phí\s+chi phí\b", "chi phí", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _sanitize_outline_heading_text(text: str, level: str = "") -> str:
    marker = ""
    raw = str(text or "").strip()
    marker_match = re.match(r"^\[(MAIN|SUPP)\]\s*", raw, flags=re.IGNORECASE)
    if marker_match:
        marker = marker_match.group(0)
    clean = marker + _strip_heading_prefixes(raw)
    clean = _neutralize_cross_industry_phrasing(clean)
    clean = re.sub(r"\bduoc\b", "được", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bphan loai\b", "phân loại", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bnhung\b", "những", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bnhom\b", "nhóm", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bhoat dong\b", "hoạt động", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bnhu the nao\b", "như thế nào", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bla gi\b", "là gì", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bcan duoc hieu\b", "cần được hiểu", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\s+", " ", clean).strip(" -:")
    if str(level).upper() == "H3":
        clean = clean.split(":", 1)[0].strip() if len(clean.split()) > 18 else clean
        words = clean.split()
        if len(words) > 18:
            clean = " ".join(words[:18]).rstrip(" ,;:-")
    return clean


def _clean_slot_filled_outline(headings: List[Dict], topic: str = "", sanitize: bool = True) -> List[Dict]:
    """Keep the evidence-driven outline; only normalize duplicates."""
    cleaned: List[Dict] = []
    seen = set()
    topic_norm = _remove_diacritics(str(topic or "").lower())
    topic_terms = {
        token for token in re.findall(r"[a-z0-9]+", topic_norm)
        if len(token) >= 3 and token not in {
            "the", "and", "cho", "voi", "cua", "cac", "nhung", "mot", "hai",
            "la", "gi", "nao", "sao", "nhu", "ve", "tong", "quan"
        }
    }
    min_topic_overlap = 2 if len(topic_terms) >= 4 else 1
    skip_current_section = False
    for item in headings or []:
        if not isinstance(item, dict):
            continue
        level = str(item.get("level", "")).upper()
        raw_text = str(item.get("text", "")).strip()
        text = _sanitize_outline_heading_text(raw_text, level=level) if sanitize and level in {"H2", "H3"} else raw_text
        if not text:
            continue

        key_text = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", text, flags=re.IGNORECASE)
        key_text = re.sub(r"\s+", " ", key_text).strip()
        key_norm = _remove_diacritics(key_text.lower())
        if level == "H2" and key_norm.startswith(("khai niem ", "dinh nghia ")):
            key_base = key_norm.split(":", 1)[0].strip()
            key_base_tokens = set(re.findall(r"[a-z0-9]+", key_base))
            if not topic_terms or len(topic_terms & key_base_tokens) >= min_topic_overlap:
                key_norm = key_base
        key = (level, key_norm)
        if level == "H3" and skip_current_section:
            continue
        if level != "H3":
            skip_current_section = False
        if level == "H2" and topic_terms:
            key_tokens = set(re.findall(r"[a-z0-9]+", key[1]))
            is_support = "[SUPP]" in text.upper() or "faq" in key[1] or "cau hoi" in key[1]
            has_evidence_anchor = any(anchor in key[1] for anchor in ["serp", "competitor", "paa", "du lieu"])
            if not is_support and not has_evidence_anchor and len(topic_terms & key_tokens) < min_topic_overlap:
                skip_current_section = True
                continue
        if key in seen:
            if level == "H2":
                skip_current_section = True
            continue
        seen.add(key)
        cleaned.append(dict(item, level=level, text=text))
    return cleaned or headings


def _apply_source_context_outline_gate(
    headings: List[Dict],
    topic: str,
    intent: str = "",
    project=None,
    niche: str = "",
    paa_questions: Optional[List[str]] = None,
) -> List[Dict]:
    """Compatibility hook: do not rewrite or filter headings by fixed phrase lists."""
    return _clean_slot_filled_outline(headings, topic=topic, sanitize=False)

def _ensure_competitor_archetype_coverage(
    headings: List[Dict],
    main_keyword: str,
    intent: str,
    outline_signals: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    """Keep competitor archetypes as prompt evidence; never add canned H2s here."""
    return headings

def _select_relevant_eav_rows(
    eav_rows: List[Dict[str, Any]],
    heading_text: str,
    topic: str = "",
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Score EAV rows by heading semantics so prompts can inject the right facts into the right section."""
    heading_norm = _remove_diacritics(str(heading_text or "").lower())
    kind = _heading_semantic_kind(heading_text)
    weighted_rows = []
    for row in eav_rows:
        attr = str(row.get("attribute", "")).strip()
        value = str(row.get("value", "")).strip()
        if not attr or not value:
            continue
        if row.get("needs_verification"):
            continue
        attr_norm = _remove_diacritics(attr.lower())
        value_norm = _remove_diacritics(value.lower())
        family_norm = _remove_diacritics(str(row.get("attribute_family", "")).lower())
        score = 0

        if attr_norm and attr_norm in heading_norm:
            score += 5
        for token in heading_norm.split():
            if len(token) >= 4 and token in attr_norm:
                score += 2
            if len(token) >= 4 and token in value_norm:
                score += 1

        if kind == "definition" and family_norm in {"definition", "classification"}:
            score += 8
        if kind == "calculation" and family_norm in {"process", "cost", "condition", "comparison"}:
            score += 7
        if kind == "comparison" and family_norm in {"comparison", "classification", "attribute"}:
            score += 6
        if kind == "impact" and family_norm in {"impact", "risk", "cost"}:
            score += 6
        if kind == "risk" and family_norm in {"risk", "condition", "cost"}:
            score += 7
        if kind == "attribute" and family_norm in {"classification", "attribute", "application"}:
            score += 5
        if kind == "faq":
            score += 2

        if kind == "definition" and family_norm in {"cost", "risk", "condition", "impact"}:
            score -= 6
        if kind == "faq" and family_norm == "definition":
            score -= 1
        if row.get("is_verified"):
            score += 4
        score += min(3, int(float(row.get("confidence", 0.0)) * 4))

        if score > 0:
            weighted_rows.append((score, row))

    weighted_rows.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in weighted_rows[:limit]]


def _build_section_context_map(
    headings: List[Dict],
    topic: str,
    intent: str,
    content_gaps: Optional[List[str]] = None,
    classified_ngrams: Optional[Dict] = None,
    entity_attributes: Optional[Dict] = None,
    outline_signals: Optional[Dict] = None,
    eav_rows: Optional[List[Dict[str, Any]]] = None,
    eav_quality: Optional[Dict[str, Any]] = None,
) -> str:
    """Build rich per-H2 prompt context so Agent 3 creates unique sections instead of restating the root definition."""
    if not headings:
        return ""

    content_gaps = [str(x).strip() for x in (content_gaps or []) if str(x).strip()]
    outline_signals = outline_signals or {}
    consensus_points = [str(x).strip() for x in outline_signals.get("consensus_points", []) if str(x).strip()]
    gap_h2_candidates = [str(x).strip() for x in outline_signals.get("gap_h2_candidates", []) if str(x).strip()]
    gap_h3_candidates = [str(x).strip() for x in outline_signals.get("gap_h3_candidates", []) if str(x).strip()]

    eav_rows = [row for row in (eav_rows or []) if isinstance(row, dict)]
    if not eav_rows and isinstance(entity_attributes, dict):
        for key, value in entity_attributes.items():
            eav_rows.append({"entity": topic, "attribute": str(key), "value": str(value)})

    semantic_pool = _collect_prompt_semantic_terms(
        topic,
        intent,
        candidates=(classified_ngrams or {}).get("entity", []) + (classified_ngrams or {}).get("action", []),
        limit=12,
    )
    intent_pack = _infer_topic_focus_pack(
        topic,
        intent,
        consensus_points=consensus_points,
        gap_h2_candidates=gap_h2_candidates,
        gap_h3_candidates=gap_h3_candidates,
        eav_rows=eav_rows,
    )

    lines: List[str] = []
    current_h2 = ""
    current_h3s: List[str] = []
    h2_blocks: List[tuple[str, List[str]]] = []
    for item in headings:
        level = str(item.get("level", ""))
        text = str(item.get("text", "")).strip()
        if level == "H2":
            if current_h2:
                h2_blocks.append((current_h2, current_h3s))
            current_h2 = text
            current_h3s = []
        elif level == "H3" and current_h2:
            current_h3s.append(text)
    if current_h2:
        h2_blocks.append((current_h2, current_h3s))

    for idx, (h2_text, h3_texts) in enumerate(h2_blocks, start=1):
        kind = _heading_semantic_kind(h2_text)
        relevant_rows = _select_relevant_eav_rows(eav_rows, h2_text, topic=topic, limit=3)
        if not relevant_rows and eav_rows and kind != "faq":
            if kind == "definition":
                relevant_rows = eav_rows[:2]
            elif kind in {"calculation", "comparison", "impact", "risk"}:
                relevant_rows = eav_rows[: min(2, len(eav_rows))]
        heading_norm = _remove_diacritics(h2_text.lower())
        matched_gaps = []
        for gap in content_gaps + gap_h2_candidates + gap_h3_candidates:
            gap_norm = _remove_diacritics(gap.lower())
            if gap_norm and (
                gap_norm in heading_norm
                or any(tok in heading_norm for tok in gap_norm.split() if len(tok) >= 5)
            ):
                matched_gaps.append(gap)
        if not matched_gaps:
            matched_gaps = gap_h2_candidates[:2] if kind in {"calculation", "comparison", "impact", "risk"} else content_gaps[:2]

        section_terms = []
        for term in semantic_pool:
            term_norm = _remove_diacritics(term.lower())
            if any(tok in heading_norm for tok in term_norm.split() if len(tok) >= 4):
                section_terms.append(term)
        if not section_terms:
            section_terms = semantic_pool[:4]

        role_map = {
            "definition": "Define the entity, set scope, and separate it from close concepts.",
            "calculation": "Explain the mechanism, quantitative relation, or step logic using evidence when available.",
            "comparison": "Compare options using fixed criteria instead of generic description.",
            "impact": "Show how this factor changes the reader's interpretation, outcome, or decision quality.",
            "risk": "Surface caveats, limits, or misreadings that change the decision.",
            "faq": "Capture tail questions quickly and concretely.",
            "attribute": "Expand the most relevant attribute cluster without restating the root definition.",
        }
        avoid_map = {
            "definition": "Do not use a side attribute as the main proof of definition unless current evidence supports it.",
            "calculation": "Do not restate the root definition; prioritize the relation, unit, rule, or example found in evidence.",
            "comparison": "Do not list brands without a comparison framework.",
            "impact": "Do not repeat attributes only; connect them to outcomes.",
            "risk": "Do not add a risk frame unless the current evidence supports it.",
            "faq": "Do not write long explanations; answer directly.",
            "attribute": "Do not restate the introduction; add new attribute-level detail.",
        }

        lines.append(f"- H2#{idx}: {h2_text}")
        lines.append(f"  + Section kind: {kind}")
        lines.append(f"  + Reader question to answer: {role_map.get(kind, role_map['attribute'])}")
        if relevant_rows:
            lines.append(
                "  + Relevant EAV facts: " +
                " | ".join(f"{r['attribute']}: {r['value']}" for r in relevant_rows)
            )
        if matched_gaps:
            lines.append("  + Gap priorities: " + "; ".join(matched_gaps[:3]))
        if consensus_points:
            lines.append("  + Consensus to keep: " + "; ".join(consensus_points[:2]))
        if section_terms:
            lines.append("  + Semantic variants to prefer: " + ", ".join(section_terms[:4]))
        lines.append("  + Avoid drift: " + avoid_map.get(kind, avoid_map["attribute"]))
        if h3_texts:
            lines.append("  + Child H3s: " + "; ".join(h3_texts[:4]))
        lines.append("")
    if lines:
        lines.insert(0, "SECTION CONTEXT MAP (Use this as hard context; every H2 must answer a different user need):")
        if isinstance(eav_quality, dict) and eav_quality:
            lines.insert(
                1,
                "EAV QUALITY: "
                f"verified_rows={int(eav_quality.get('verified_rows', 0))}; "
                f"attribute_families={int(eav_quality.get('attribute_families', 0))}; "
                f"coverage={str(eav_quality.get('coverage_status', 'weak'))}",
            )
    return "\n".join(lines).strip()


def _dedupe_text_list(items: Optional[List[str]], limit: int = 0) -> List[str]:
    seen = set()
    clean: List[str] = []
    for item in items or []:
        text = str(item or "").strip()
        norm = _remove_diacritics(text.lower()).strip()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        clean.append(text)
        if limit and len(clean) >= limit:
            break
    return clean




def _base_section_evidence_plan() -> Dict[str, Dict[str, List[str] | str]]:
    return {
        "definition": {
            "required_evidence": ["definition", "scope", "difference from near-meaning concepts"],
            "preferred_format": "paragraph + concise distinction list",
            "snippet_expectation": "answer-first definition plus one concrete fact",
        },
        "attribute": {
            "required_evidence": ["attribute breakdown", "grouping logic", "concrete examples"],
            "preferred_format": "paragraph or short grouped bullets",
            "snippet_expectation": "core attribute summary without repeating the root definition",
        },
        "calculation": {
            "required_evidence": ["relation or rule", "source value if available", "worked example if available"],
            "preferred_format": "evidence-led explanation + compact example",
            "snippet_expectation": "answer with the specific relation or rule found in evidence",
        },
        "comparison": {
            "required_evidence": ["fixed criteria", "comparison dimensions", "decision rule"],
            "preferred_format": "criteria table",
            "snippet_expectation": "comparison answer with criteria, not generic prose",
        },
        "impact": {
            "required_evidence": ["outcome impact", "decision consequence", "fit consequence"],
            "preferred_format": "scenario comparison",
            "snippet_expectation": "state what changes in outcomes or decisions",
        },
        "risk": {
            "required_evidence": ["hidden condition", "caveat", "mistake or failure outcome"],
            "preferred_format": "warning paragraph + checklist",
            "snippet_expectation": "surface the hidden condition or caution directly",
        },
        "faq": {
            "required_evidence": ["direct answer", "condition", "fact or example if available"],
            "preferred_format": "short FAQ",
            "snippet_expectation": "short direct answer",
        },
    }


def _dedupe_candidate_fact_rows(rows: List[Dict[str, Any]], limit: int = 24) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = (
            normalize_text(row.get("attribute", "")),
            normalize_text(row.get("value", "")),
        )
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        clean.append(row)
        if len(clean) >= limit:
            break
    return clean


def _heuristic_clean_fact_candidates(
    rows: Optional[List[Dict[str, Any]]],
    query_state: Optional[Dict[str, Any]] = None,
    limit: int = 24,
) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for row in rows or []:
        sanitized = sanitize_fact_row(row, state=query_state)
        if not sanitized:
            continue
        if not is_clean_fact_candidate(
            sanitized.get("attribute", ""),
            sanitized.get("value", ""),
            state=query_state,
        ):
            continue
        clean.append(sanitized)
    return _dedupe_candidate_fact_rows(clean, limit=limit)


def _build_serp_evidence_bridge(serp_data: Optional[Dict[str, Any]], limit: int = 5) -> List[str]:
    if not serp_data or not isinstance(serp_data, dict):
        return []
    lines: List[str] = []
    for result in (serp_data.get("organic_results", []) or [])[:limit]:
        if not isinstance(result, dict):
            continue
        title = str(result.get("title", "")).strip()
        snippet = str(result.get("snippet", "")).strip()
        if not title:
            continue
        line = f"- Title: {title}"
        if snippet:
            line += f" | Snippet: {snippet}"
        lines.append(line)
    return lines


def _llm_filter_fact_candidates(
    topic: str,
    intent: str,
    project=None,
    query_state: Optional[Dict[str, Any]] = None,
    rows: Optional[List[Dict[str, Any]]] = None,
    serp_data: Optional[Dict[str, Any]] = None,
    common_headings: Optional[List[str]] = None,
    paa_questions: Optional[List[str]] = None,
    limit: int = 18,
) -> List[Dict[str, Any]]:
    candidates = _heuristic_clean_fact_candidates(rows, query_state=query_state, limit=limit)
    if not candidates:
        return []

    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return candidates

        import json
        import openai
        from modules.llm_utils import call_llm_seo

        client = openai.OpenAI(api_key=api_key)
        project_scope = _build_project_scope_brief(project)
        serp_evidence = _build_serp_evidence_bridge(serp_data, limit=5)
        system_prompt = (
            "Bạn là Semantic Fact Sanitizer cho pipeline Semantic SEO.\n"
            "Nhiệm vụ: lọc candidate facts lấy từ MAIN BODY của bài đối thủ cho đúng keyword hiện tại.\n\n"
            "CHỈ GIỮ row nếu đồng thời thỏa:\n"
            "1. Bám đúng keyword + search intent + source context/project scope.\n"
            "2. Là fact hoặc câu mô tả có nghĩa độc lập, lấy từ body content; ưu tiên câu đầy đủ hơn heading fragment.\n"
            "3. Không phải CTA, quảng cáo, teaser link, điều hướng, heading dở dang, caption rời, hoặc câu chỉ dùng để kéo click.\n"
            "4. Không phải meta-instruction, không phải prompt text, không phải copy marketing.\n"
            "5. Nếu có nhiều candidate, ưu tiên câu có cơ chế rõ, ngày hiệu lực, tỷ lệ %, VND/USD hoặc điều kiện áp dụng cụ thể.\n"
            "6. Không được bịa thêm fact, không được thêm số, chỉ được rewrite tối thiểu để làm sạch câu.\n\n"
            "OUTPUT JSON OBJECT:\n"
            "{\n"
            '  "items": [\n'
            '    {\n'
            '      "source_index": 0,\n'
            '      "decision": "keep|reject",\n'
            '      "attribute": "attribute đã làm sạch",\n'
            '      "value": "value đã làm sạch",\n'
            '      "reason": "lý do ngắn"\n'
            '    }\n'
            "  ]\n"
            "}\n"
            "Chỉ output JSON object."
        )
        user_prompt = (
            f"Keyword: {topic}\n"
            f"Intent: {intent}\n"
            f"Project scope: {project_scope}\n"
            + ("Search-result evidence:\n" + "\n".join(serp_evidence) + "\n" if serp_evidence else "")
            + ("Common headings:\n- " + "\n- ".join((common_headings or [])[:8]) + "\n" if common_headings else "")
            + ("PAA/project questions:\n- " + "\n- ".join((paa_questions or [])[:8]) + "\n" if paa_questions else "")
            + "\nCandidate rows:\n"
        )
        for idx, row in enumerate(candidates[:limit]):
            user_prompt += (
                f"- [{idx}] attribute={str(row.get('attribute', '')).strip()} | "
                f"value={str(row.get('value', '')).strip()} | "
                f"source_type={str(row.get('source_type', '')).strip()}\n"
            )

        raw = call_llm_seo(
            client=client,
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        data = json.loads(raw) if raw else {}
        items = data.get("items", []) if isinstance(data, dict) else []
        refined: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("decision", "")).strip().lower() != "keep":
                continue
            try:
                source_index = int(item.get("source_index", -1))
            except Exception:
                continue
            if source_index < 0 or source_index >= len(candidates):
                continue
            base_row = dict(candidates[source_index])
            base_row["attribute"] = str(item.get("attribute", base_row.get("attribute", ""))).strip()
            base_row["value"] = str(item.get("value", base_row.get("value", ""))).strip()
            sanitized = sanitize_fact_row(base_row, state=query_state)
            if sanitized:
                refined.append(sanitized)
        return _dedupe_candidate_fact_rows(refined or candidates, limit=limit)
    except Exception as exc:
        logger.warning("  [FACT-SANITIZER] LLM filter failed (%s) -> heuristic clean only.", exc)
        return candidates


def _build_agent3_prompt_packs(
    topic: str,
    intent: str,
    intent_pack: Dict[str, Any],
    reasoning: Dict[str, Any],
    verified_rows: List[Dict[str, Any]],
    serp_data: Optional[Dict[str, Any]],
    section_context_map: str,
) -> Dict[str, str]:
    packs: Dict[str, str] = {}
    parts: List[str] = []
    if intent_pack.get("search_task"):
        parts.append(f"Task chính: {intent_pack.get('search_task')}")
    if reasoning.get("supporting_tasks"):
        parts.append("Nhu cầu phụ: " + "; ".join(str(x) for x in reasoning.get("supporting_tasks", [])[:6]))
    if reasoning.get("decision_blockers"):
        parts.append("Điểm do dự cần tháo: " + "; ".join(str(x) for x in reasoning.get("decision_blockers", [])[:5]))
    if reasoning.get("preferred_flow"):
        parts.append("Flow ưu tiên: " + " -> ".join(str(x) for x in reasoning.get("preferred_flow", [])[:8]))
    packs["intent_bridge"] = "\n".join(parts).strip()

    serp_lines = _build_serp_evidence_bridge(serp_data, limit=5)
    packs["serp_bridge"] = "\n".join(serp_lines).strip()

    fact_lines: List[str] = []
    for row in verified_rows[:10]:
        fact_lines.append(
            f"- {str(row.get('attribute', '')).strip()}: {str(row.get('value', '')).strip()} "
            f"(family={str(row.get('attribute_family', '')).strip()}, source={str(row.get('source_type', '')).strip()}, confidence={str(row.get('confidence', ''))})"
        )
    packs["fact_pack"] = "\n".join(fact_lines).strip()

    quality_rules = [
        "Bạn đang viết writer brief cho biên tập viên con người, không phải viết prompt cho AI khác.",
        "Mỗi snippet phải là câu trả lời trực diện cho section tương ứng, không dùng giọng meta như 'phần này cần', 'bài viết cần'.",
        "Không dùng link text, CTA, dòng 'xem thêm', caption rời hay heading fragment làm fact chính hoặc anchor cho H3.",
        "Nếu đã có fact xác minh chứa ngày, tỷ lệ %, mức phí hoặc điều kiện áp dụng cụ thể, hãy ưu tiên chính fact đó thay vì quay về câu mô tả chung.",
        "Nếu dữ kiện còn yếu, hãy giữ văn phong tự nhiên và trung tính theo đúng section kind; không bịa số liệu hay thêm thuật ngữ ngoài research hiện tại.",
        "Mỗi H2 phải giải quyết một user need khác nhau và không được lặp cùng một khung phân tích.",
    ]
    packs["quality_gate"] = "\n".join(f"- {rule}" for rule in quality_rules)
    packs["section_bridge"] = section_context_map.strip()
    return packs


def _semantic_query_state(
    topic: str,
    intent: str,
    project=None,
    paa_questions: Optional[List[str]] = None,
    common_headings: Optional[List[str]] = None,
    content_gaps: Optional[List[str]] = None,
    eav_rows: Optional[List[Dict[str, str]]] = None,
    semantic_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    project_scope = ""
    if project is not None:
        project_scope = str(getattr(project, "industry", "") or getattr(project, "description", "") or "").strip()
    return build_query_state(
        topic=topic,
        intent=intent,
        paa_questions=paa_questions,
        common_headings=common_headings,
        content_gaps=content_gaps,
        eav_rows=eav_rows,
        semantic_terms=semantic_terms,
        project_scope=project_scope,
    )


def _derive_supporting_tasks(
    topic: str,
    intent: str,
    paa_questions: Optional[List[str]] = None,
    gap_h2_candidates: Optional[List[str]] = None,
) -> List[str]:
    state = _semantic_query_state(
        topic=topic,
        intent=intent,
        paa_questions=paa_questions,
        content_gaps=gap_h2_candidates,
    )
    return derive_supporting_tasks(state, h2_gaps=gap_h2_candidates)


def _derive_decision_blockers(
    topic: str,
    intent: str,
    paa_questions: Optional[List[str]] = None,
    gap_candidates: Optional[List[str]] = None,
) -> List[str]:
    state = _semantic_query_state(
        topic=topic,
        intent=intent,
        paa_questions=paa_questions,
        content_gaps=gap_candidates,
    )
    return derive_decision_blockers(state, gap_candidates=gap_candidates)


def _derive_misinterpretation_risks(
    topic: str,
    project=None,
    semantic_terms: Optional[List[str]] = None,
) -> List[str]:
    state = _semantic_query_state(
        topic=topic,
        intent="",
        project=project,
        semantic_terms=semantic_terms,
    )
    return derive_misinterpretation_risks(state, semantic_terms=semantic_terms)


def _derive_consensus_facts(
    topic: str,
    paa_questions: Optional[List[str]] = None,
    common_headings: Optional[List[str]] = None,
    eav_rows: Optional[List[Dict[str, str]]] = None,
    project=None,
) -> List[str]:
    state = _semantic_query_state(
        topic=topic,
        intent="",
        project=project,
        paa_questions=paa_questions,
        common_headings=common_headings,
        eav_rows=eav_rows,
    )
    return derive_consensus_facts(state, project_scope=state.get("project_scope", ""))


def _classify_semantic_gaps(
    topic: str,
    gaps: Optional[List[str]] = None,
    consensus_facts: Optional[List[str]] = None,
    project=None,
) -> Dict[str, List[str]]:
    state = _semantic_query_state(
        topic=topic,
        intent="",
        project=project,
        content_gaps=gaps,
    )
    return classify_gap_map(state, gaps=gaps, consensus_facts=consensus_facts)


def _build_semantic_reasoning(
    topic: str,
    intent: str,
    serp_data: Optional[Dict] = None,
    project=None,
    paa_questions: Optional[List[str]] = None,
    competitor_data: Optional[Dict] = None,
    content_gaps: Optional[List[str]] = None,
    classified_ngrams: Optional[Dict] = None,
    eav_table: str = "",
    entity_attributes: Optional[Dict] = None,
    outline_signals: Optional[Dict] = None,
    headings: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    common_headings = []
    if competitor_data and isinstance(competitor_data, dict):
        common_headings = _filter_project_contamination_terms(
            [str(h).strip() for h in competitor_data.get("common_headings", []) if str(h).strip()],
            project=project,
            topic=topic,
        )

    raw_semantic_terms = _collect_prompt_semantic_terms(
        topic,
        intent,
        project=project,
        candidates=(classified_ngrams or {}).get("entity", []) + (classified_ngrams or {}).get("action", []),
        limit=20,
    )
    pre_reasoning_state = _semantic_query_state(
        topic=topic,
        intent=intent,
        project=project,
        paa_questions=paa_questions,
        common_headings=common_headings,
        content_gaps=(content_gaps or []) + (outline_signals or {}).get("gap_h2_candidates", []) + (outline_signals or {}).get("gap_h3_candidates", []),
        semantic_terms=raw_semantic_terms,
    )

    enriched_candidate_rows_raw = extract_competitor_fact_rows(
        topic=topic,
        competitor_data=competitor_data,
        limit=24,
    )
    enriched_candidate_rows = _llm_filter_fact_candidates(
        topic=topic,
        intent=intent,
        project=project,
        query_state=pre_reasoning_state,
        rows=enriched_candidate_rows_raw,
        serp_data=serp_data,
        common_headings=common_headings,
        paa_questions=paa_questions,
        limit=18,
    )

    verified_eav_rows = build_verified_eav_rows(
        topic=topic,
        eav_table=eav_table,
        entity_attributes=entity_attributes,
        extra_rows=enriched_candidate_rows,
        source_context=getattr(project, "industry", "") if project else "",
        common_headings=common_headings,
        paa_questions=paa_questions,
        project_scope=getattr(project, "industry", "") if project else "",
    )
    eav_quality = summarize_eav_quality(verified_eav_rows)
    eav_rows = [row for row in verified_eav_rows if row.get("is_verified")]
    if not eav_rows:
        eav_rows = [row for row in verified_eav_rows if not row.get("needs_verification")]

    outline_signals = outline_signals or {"consensus_points": [], "gap_h2_candidates": [], "gap_h3_candidates": []}
    focus_pack = _infer_topic_focus_pack(
        topic,
        intent,
        consensus_points=outline_signals.get("consensus_points", []),
        gap_h2_candidates=outline_signals.get("gap_h2_candidates", []),
        gap_h3_candidates=outline_signals.get("gap_h3_candidates", []),
        eav_rows=eav_rows,
    )
    query_state = _semantic_query_state(
        topic=topic,
        intent=intent,
        project=project,
        paa_questions=paa_questions,
        common_headings=common_headings,
        content_gaps=(content_gaps or []) + outline_signals.get("gap_h2_candidates", []) + outline_signals.get("gap_h3_candidates", []),
        eav_rows=eav_rows,
        semantic_terms=raw_semantic_terms,
    )
    eav_rows = filter_eav_rows(eav_rows, query_state, min_score=0.10)
    common_headings = filter_pure_phrases(common_headings, query_state, min_score=0.12, limit=10)
    gap_candidates = filter_pure_phrases(
        (content_gaps or []) + outline_signals.get("gap_h2_candidates", []) + outline_signals.get("gap_h3_candidates", []),
        query_state,
        min_score=0.10,
        limit=16,
    )
    semantic_terms_curated = curated_semantic_terms(query_state)
    semantic_blueprint = _build_semantic_blueprint(
        topic,
        intent,
        project=project,
        consensus_points=outline_signals.get("consensus_points", []),
        gap_h2_candidates=outline_signals.get("gap_h2_candidates", []),
        gap_h3_candidates=outline_signals.get("gap_h3_candidates", []),
        paa_questions=paa_questions,
        eav_rows=eav_rows,
        semantic_terms=semantic_terms_curated,
    )
    query_state = _semantic_query_state(
        topic=topic,
        intent=intent,
        project=project,
        paa_questions=paa_questions,
        common_headings=common_headings,
        content_gaps=gap_candidates,
        eav_rows=eav_rows,
        semantic_terms=semantic_terms_curated,
    )

    dominant_user_task = derive_dominant_user_task(query_state).strip() or str(focus_pack.get("search_task", "")).strip()
    if dominant_user_task and not dominant_user_task.endswith("."):
        dominant_user_task += "."

    consensus_facts = _derive_consensus_facts(
        topic,
        paa_questions=paa_questions,
        common_headings=common_headings,
        eav_rows=eav_rows,
        project=project,
    )
    gap_map = _classify_semantic_gaps(
        topic,
        gaps=gap_candidates,
        consensus_facts=consensus_facts,
        project=project,
    )

    reasoning: Dict[str, Any] = {
        "dominant_user_task": dominant_user_task,
        "supporting_tasks": _derive_supporting_tasks(
            topic,
            intent,
            paa_questions=paa_questions,
            gap_h2_candidates=gap_map.get("h2_worthy", []),
        ),
        "decision_blockers": _derive_decision_blockers(
            topic,
            intent,
            paa_questions=paa_questions,
            gap_candidates=gap_candidates,
        ),
        "misinterpretation_risks": _derive_misinterpretation_risks(
            topic,
            project=project,
            semantic_terms=semantic_terms_curated,
        ),
        "consensus_facts": consensus_facts,
        "gap_map": gap_map,
        "section_evidence_plan": _base_section_evidence_plan(),
        "raw_enriched_candidate_rows": enriched_candidate_rows_raw,
        "enriched_candidate_rows": enriched_candidate_rows,
        "verified_eav_rows": verified_eav_rows,
        "eav_quality": eav_quality,
        "semantic_terms_curated": semantic_terms_curated,
        "semantic_blueprint": semantic_blueprint,
        "preferred_flow": _dedupe_text_list(
            [str(x).strip() for x in semantic_blueprint.get("role_order", []) if str(x).strip()]
            + [str(x).strip() for x in focus_pack.get("preferred_order", []) if str(x).strip()],
            limit=8,
        ),
    }

    if headings:
        per_heading: Dict[str, Dict[str, Any]] = {}
        for item in headings:
            if not isinstance(item, dict) or str(item.get("level", "")).upper() != "H2":
                continue
            h2_text = str(item.get("text", "")).strip()
            kind = _heading_semantic_kind(h2_text)
            matched_eav = _select_relevant_eav_rows(eav_rows, h2_text, topic=topic, limit=3)
            matched_gaps = []
            for bucket in ["h2_worthy", "supporting_detail", "topical_expansion"]:
                for gap in gap_map.get(bucket, []):
                    if _overlap_context_phrase(h2_text, gap) > 0.2:
                        matched_gaps.append({"text": gap, "gap_class": bucket})
            matched_consensus = []
            for fact in consensus_facts:
                if _overlap_context_phrase(h2_text, fact) > 0.15:
                    matched_consensus.append(fact)
            if not matched_consensus:
                matched_consensus = consensus_facts[:2]
            child_h3s: List[str] = []
            current_h2 = ""
            for block in headings:
                if not isinstance(block, dict):
                    continue
                level = str(block.get("level", "")).upper()
                text = str(block.get("text", "")).strip()
                if level == "H2":
                    current_h2 = text
                elif level == "H3" and current_h2 == h2_text and text:
                    child_h3s.append(text)
            heading_norm = _remove_diacritics(h2_text.lower())
            drift_hits = [
                risk for risk in reasoning["misinterpretation_risks"]
                if any(tok in heading_norm for tok in _remove_diacritics(risk.lower()).split() if len(tok) >= 5)
            ]
            anchor_plan = choose_heading_anchor_plan(
                h3_items=child_h3s,
                matched_rows=matched_eav,
                matched_consensus=matched_consensus,
                matched_gaps=matched_gaps,
                reuse_limit=1 if len(matched_eav) >= 3 else 2,
            )
            per_heading[h2_text] = {
                "kind": kind,
                "matched_eav": matched_eav,
                "matched_consensus_facts": matched_consensus[:3],
                "matched_gaps": matched_gaps[:4],
                "gap_class": matched_gaps[0]["gap_class"] if matched_gaps else ("supporting_detail" if kind == "faq" else "h2_worthy"),
                "primary_user_need": {
                    "definition": "Hiểu đúng khái niệm và phạm vi nghĩa của chủ đề.",
                    "attribute": "Hiểu các cấu phần hoặc thuộc tính chính mà người đọc cần biết.",
                    "calculation": "Biết cách tính hoặc tự ước lượng con số thực tế.",
                    "comparison": "Biết so sánh theo bộ tiêu chí cố định trước khi ra quyết định.",
                    "impact": "Hiểu chi phí thay đổi kết quả và quyết định ra sao.",
                    "risk": "Biết khoản phát sinh, điều kiện ẩn hoặc sai lầm dễ gặp.",
                    "faq": "Giải quyết nhanh các câu hỏi đuôi có giá trị hỗ trợ quyết định.",
                }.get(kind, "Mở rộng một khía cạnh của chủ đề mà không lặp lại định nghĩa gốc."),
                "avoid_drift": drift_hits or reasoning["misinterpretation_risks"][:2],
                "evidence_types": reasoning["section_evidence_plan"].get(kind, {}).get("required_evidence", []),
                "anchor_plan": anchor_plan,
            }
        reasoning["section_evidence_plan"]["per_heading"] = per_heading

    return reasoning


def _inject_outline_h2_candidates(
    outline: List[Dict],
    candidates: List[str],
    main_keyword: str,
) -> List[Dict]:
    """Insert broad consensus/gap candidates as H2s before SUPP sections."""
    if not outline or not candidates:
        return outline

    existing = set()
    for item in outline:
        if isinstance(item, dict) and item.get("level") == "H2":
            existing.add(_remove_diacritics(str(item.get("text", "")).lower()))

    insert_at = len(outline)
    for idx, item in enumerate(outline):
        if isinstance(item, dict) and item.get("level") == "H2":
            text_norm = _remove_diacritics(str(item.get("text", "")).lower())
            if "[supp]" in text_norm or "faq" in text_norm:
                insert_at = idx
                break

    additions = []
    main_norm = _remove_diacritics(str(main_keyword or "").lower())
    for candidate in candidates:
        text = str(candidate or "").strip()
        if not text:
            continue
        cleaned = text.replace("[MAIN]", "").replace("[SUPP]", "").strip()
        cleaned_norm = _remove_diacritics(cleaned.lower())
        if not cleaned_norm or cleaned_norm in existing:
            continue
        if main_norm and main_norm not in cleaned_norm and len(cleaned.split()) <= 3:
            cleaned = f"{main_keyword}: {cleaned}"
            cleaned_norm = _remove_diacritics(cleaned.lower())
            if cleaned_norm in existing:
                continue
        additions.append({"level": "H2", "text": f"[MAIN] {cleaned}"})
        existing.add(cleaned_norm)

    if additions:
        outline = outline[:insert_at] + additions + outline[insert_at:]
    return outline


def refine_paa_questions_for_project(
    topic: str,
    entity: str,
    project=None,
    raw_questions: List[str] = None,
    intent: str = "",
    competitor_data: Optional[Dict] = None,
) -> Dict:
    """
    Convert raw SERP PAA into project-aligned FAQ questions.

    The raw PAA list may drift into adjacent industries, so this step rewrites
    questions to stay inside the active project's topical border.
    """
    raw_questions = _normalize_question_list(raw_questions or [])
    project_scope = _build_project_scope_brief(project)
    niche = detect_niche(topic or entity or "", getattr(project, "industry", "") if project else "")

    if not raw_questions:
        return {
            "raw_questions": [],
            "faq_questions": _fallback_project_faq_questions(topic, entity, project, []),
            "supp_questions": [],
            "mode": "fallback",
        }

    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            raise ValueError("No API key")

        import json
        import openai
        from modules.llm_utils import call_llm_with_retry, LLM_DEFAULTS

        client = openai.OpenAI(api_key=api_key)

        competitor_hint = []
        if competitor_data and isinstance(competitor_data, dict):
            info_gain = competitor_data.get("information_gain", {})
            if isinstance(info_gain, dict):
                competitor_hint = _normalize_question_list(info_gain.get("rare_headings", []))[:5]

        system_prompt = (
            "Bạn là chuyên gia Semantic SEO tập trung vào FAQ normalization.\n"
            "Nhiệm vụ: chuyển các PAA raw từ Google thành FAQ phù hợp với project đang active.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. PAA raw chỉ là tín hiệu, không được bê nguyên nếu lệch ngành.\n"
            "2. Chỉ giữ các câu hỏi có thể trả lời trong topical border của project.\n"
            "3. Nếu raw question thuộc ngành khác, rewrite thành câu hỏi cùng intent nhưng đúng ngành của project.\n"
            "4. Không được đưa vào FAQ các câu hỏi thuộc vertical khác nếu project/source context không xác nhận vertical đó.\n"
            "5. Ưu tiên entity/attribute của project và evidence hiện tại; bỏ qua search term nếu term đó gây drift.\n\n"
            "OUTPUT JSON SCHEMA:\n"
            "{\n"
            '  "items": [\n'
            '    {\n'
            '      "raw_question": "cau hoi goc",\n'
            '      "faq_question": "cau hoi da rewrite",\n'
            '      "relation": "alias|same_root|sibling|reject",\n'
            '      "placement": "FAQ|SUPP|omit",\n'
            '      "reason": "ly do ngan"\n'
            '    }\n'
            "  ]\n"
            "}\n"
            "Trả về tối đa 7 items. Nếu question không phù hợp, đặt placement=omit."
        )

        user_prompt = (
            f"Topic: {topic}\n"
            f"Central entity: {entity}\n"
            f"Search intent: {intent}\n"
            f"Detected niche: {niche}\n"
            f"Project scope: {project_scope}\n\n"
            f"Raw PAA questions:\n- " + "\n- ".join(raw_questions[:10]) + "\n\n"
        )
        if competitor_hint:
            user_prompt += (
                "Rare headings from competitors that may inform intent but must still respect project scope:\n"
                + "\n".join(f"- {q}" for q in competitor_hint)
                + "\n\n"
            )
        user_prompt += (
            "Rewrite the raw PAA into project-aligned FAQs. "
            "Keep the intent, but correct the topical border."
        )

        raw = call_llm_with_retry(
            client=client,
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LLM_DEFAULTS["temperature_seo"],
            max_tokens=1200,
            timeout=LLM_DEFAULTS["timeout"],
            response_format={"type": "json_object"},
        )

        data = {}
        try:
            data = json.loads(raw)
        except Exception:
            data = {}

        items = data.get("items", []) if isinstance(data, dict) else []
        faq_questions = []
        supp_questions = []
        reviewed = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_q = str(item.get("raw_question", "")).strip()
            faq_q = str(item.get("faq_question", "")).strip()
            relation = str(item.get("relation", "")).strip() or "same_root"
            placement = str(item.get("placement", "")).strip() or "FAQ"
            reason = str(item.get("reason", "")).strip()
            if not faq_q:
                continue
            key = _remove_diacritics(faq_q.lower())
            if key in seen:
                continue
            seen.add(key)
            reviewed.append(
                {
                    "raw_question": raw_q,
                    "faq_question": faq_q,
                    "relation": relation,
                    "placement": placement,
                    "reason": reason,
                }
            )
            if placement.upper() == "FAQ" and relation.lower() != "reject":
                faq_questions.append(faq_q)
            elif placement.upper() == "SUPP" and relation.lower() != "reject":
                supp_questions.append(faq_q)

        if not faq_questions:
            faq_questions = _fallback_project_faq_questions(topic, entity, project, raw_questions)

        return {
            "raw_questions": raw_questions,
            "faq_questions": faq_questions[:7],
            "supp_questions": supp_questions[:5],
            "reviewed": reviewed[:10],
            "mode": "llm",
        }
    except Exception as exc:
        logger.warning("  [PAA-REFINE] LLM failed (%s) -> fallback.", exc)
        return {
            "raw_questions": raw_questions,
            "faq_questions": _fallback_project_faq_questions(topic, entity, project, raw_questions)[:7],
            "supp_questions": [],
            "mode": "fallback",
        }


# ══════════════════════════════════════════════
#  HEADING ENRICHMENT
# ══════════════════════════════════════════════

# ══════════════════════════════════════════════
#  POST-PROCESSORS (Rule-based, after Agent 1+2)
# ══════════════════════════════════════════════

# ── P7.2: BRAND KEYWORDS (ĐÃ XÓA TRONG V4) ──
# V4 sử dụng Agent 3a (Structure Validator) để suy luận MAIN/SUPP
# thay vì dùng list brand cố định. Hàm dưới đây giữ lại tên
# để không break exception fallback trong rewrite_headings_semantic.

def _postprocess_brand_h2_reorder(
    headings: List[Dict], intent: str, main_keyword: str
) -> List[Dict]:
    """
    (Deprecated) Phase 7 hardcoded logic.
    V4 uses Agent 3a (review_structure) for this.
    Returns headings unmodified.
    """
    return headings


def _postprocess_prominence_blacklist(
    headings: List[Dict],
    topic: str,
    project=None,
) -> List[Dict]:
    """Compatibility hook: do not remove sections through fixed vertical blacklist terms."""
    return headings


def _postprocess_supp_enforcer(
    headings: List[Dict], main_keyword: str, intent: str,
    paa_questions: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Ensure [SUPP] section exists (≥20% of H2).
    If missing: tag FAQ as [SUPP], tag last H2 as [SUPP], add Antonym Ending.
    Fix V6: Also creates FAQ H2 with PAA-derived H3s when no FAQ exists.
    """
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    if not h2_indices:
        return headings

    supp_count = sum(1 for i in h2_indices if "[SUPP]" in headings[i].get("text", ""))
    total_h2 = len(h2_indices)
    min_supp = max(1, int(total_h2 * 0.2))  # At least 20%, minimum 1

    if supp_count >= min_supp:
        return headings  # Already has enough SUPP

    # Also ensure ALL H2s without prefix get [MAIN]
    for i in h2_indices:
        text = headings[i]["text"]
        if not text.startswith("[MAIN]") and not text.startswith("[SUPP]"):
            headings[i]["text"] = f"[MAIN] {text}"

    # Tag existing FAQ H2 as [SUPP] and record its index
    faq_idx = -1
    for i in h2_indices:
        text = headings[i]["text"].lower()
        if "faq" in text or "câu hỏi" in text:
            headings[i]["text"] = headings[i]["text"].replace("[MAIN] ", "[SUPP] ")
            if not headings[i]["text"].startswith("[SUPP]"):
                headings[i]["text"] = "[SUPP] " + headings[i]["text"]
            faq_idx = i
            break

    # Use PAA only when there is real question evidence; do not fabricate a FAQ section.
    if faq_idx == -1 and paa_questions:
        first_question = str(paa_questions[0]).strip()
        if first_question:
            faq_heading_text = f"[SUPP] {first_question}"
            headings.append({"level": "H2", "text": faq_heading_text})
            logger.info("  [SUPP-ENFORCER] Created evidence-driven question section: %s", faq_heading_text)
            faq_idx = len(headings) - 1

    # Add PAA questions as H3 children (max 3) IF we have them AND
    # the FAQ section doesn't already have H3 children
    if paa_questions and faq_idx != -1:
        # Check if there are already H3s right after the FAQ H2
        has_h3s = False
        if faq_idx + 1 < len(headings) and headings[faq_idx + 1].get("level") == "H3":
            has_h3s = True

        if not has_h3s:
            # Insert PAA H3s right after the FAQ H2
            insert_pos = faq_idx + 1
            for q in reversed(paa_questions[1:4] if faq_idx == len(headings) - 1 else paa_questions[:3]):
                q_text = str(q).strip()
                if q_text:
                    headings.insert(insert_pos, {"level": "H3", "text": q_text})
            logger.info("  [SUPP-ENFORCER] Injected %d PAA H3s into FAQ", min(3, len(paa_questions)))

    # Re-calculate h2_indices after potential addition of FAQ H2/H3s
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    supp_count = sum(1 for i in h2_indices if "[SUPP]" in headings[i].get("text", ""))

    # Tag last H2 as [SUPP] if still need more
    if supp_count < min_supp and h2_indices:
        last_h2_idx = h2_indices[-1]
        text = headings[last_h2_idx]["text"]
        if "[MAIN]" in text:
            headings[last_h2_idx]["text"] = text.replace("[MAIN] ", "[SUPP] ")

    # Add Antonym Ending if missing
    has_antonym = False
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    if h2_indices:
        last_text = headings[h2_indices[-1]]["text"].lower()
        antonym_signals = ["không nên", "khi nào không", "sai lầm", "tránh", "thay thế", "giống nhau", "không phù hợp"]
        has_antonym = any(s in last_text for s in antonym_signals)

    if not has_antonym:
        # Generate contextual antonym question
        entity = main_keyword.strip()
        intent_lower = intent.lower()
        if "vs" in intent_lower:
            # Extract 2 entities from keyword
            parts = [p.strip() for p in re.split(r'\bvà\b|\bvs\b|\bvới\b|\bso sánh\b', entity, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2:
                a = parts[0]
                b = parts[1]
                # Remove trailing question words from b
                for rem in ["khác nhau thế nào", "khác nhau", "thế nào", "như thế nào"]:
                    b = b.replace(rem, "").strip()
                antonym = f"[SUPP] Khi nào {a} và {b} có thể thay thế nhau?"
            else:
                antonym = f"[SUPP] Khi nào không nên sử dụng {entity}?"
        elif "informational" in intent_lower or "what-is" in intent_lower:
            antonym = f"[SUPP] {entity}: Những trường hợp không nên sử dụng"
        else:
            antonym = f"[SUPP] Những sai lầm phổ biến khi chọn {entity}"
        headings.append({"level": "H2", "text": antonym})
        logger.info("  [SUPP-ENFORCER] Added Antonym Ending: %s", antonym)

    logger.info("  [SUPP-ENFORCER] SUPP enforcement complete. H2 count: %d", len([h for h in headings if h.get("level") == "H2"]))
    return headings


def _merge_back_h3s(new_outline: List[Dict], old_outline: List[Dict], step_name: str = "") -> List[Dict]:
    """
    DEFENSE LAYER: Nếu LLM agent vô tình xóa H3, merge H3s từ outline cũ trở lại.

    Logic:
    1. Đếm H3 trong new vs old.
    2. Nếu new có ít H3 hơn old đáng kể (≥50% mất) → merge lại.
    3. Merge bằng cách ghép H3 từ old vào vị trí H2 tương ứng trong new.
    """
    old_h3 = sum(1 for h in old_outline if h.get("level") == "H3")
    new_h3 = sum(1 for h in new_outline if h.get("level") == "H3")

    logger.info("  [H3-DEFENSE %s] H3 count: before=%d, after=%d", step_name, old_h3, new_h3)

    # Nếu new đã có đủ H3, hoặc old cũng không có H3 → return nguyên
    if new_h3 >= old_h3 or old_h3 == 0:
        return new_outline

    # Nếu bị mất ≥50% H3 → merge lại
    if new_h3 < old_h3 * 0.5:
        logger.warning("  [H3-DEFENSE %s] Detected H3 drop (%d→%d). Merging back...", step_name, old_h3, new_h3)

        # Xây map: H2 text → [H3 children] từ old outline
        old_h2_children = {}
        current_h2_key = None
        for h in old_outline:
            if h.get("level") == "H2":
                key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                current_h2_key = key
                if key not in old_h2_children:
                    old_h2_children[key] = []
            elif h.get("level") == "H3" and current_h2_key:
                old_h2_children[current_h2_key].append(h)

        # Xây set các H2 trong new outline đã có H3
        new_h2_has_h3 = set()
        for i, h in enumerate(new_outline):
            if h.get("level") == "H2":
                if i + 1 < len(new_outline) and new_outline[i + 1].get("level") == "H3":
                    key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                    new_h2_has_h3.add(key)

        # Phase 1: Exact-match merge
        result = []
        for h in new_outline:
            result.append(h)
            if h.get("level") == "H2":
                key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                if key not in new_h2_has_h3 and key in old_h2_children:
                    for child_h3 in old_h2_children[key]:
                        result.append(child_h3)
                    new_h2_has_h3.add(key)
                    logger.info("  [H3-DEFENSE] Restored %d H3s under '%s'",
                                len(old_h2_children[key]), h["text"][:50])

        # Phase 2: Fuzzy-match (word overlap) cho các H2 đã bị Agent rewrite text
        restored_h3 = sum(1 for h in result if h.get("level") == "H3")
        if restored_h3 < old_h3 * 0.5:
            logger.info("  [H3-DEFENSE] Exact match insufficient (%d). Trying fuzzy match...", restored_h3)

            # Collect orphan H3s (chưa được ghép)
            matched_keys = set()
            for h in result:
                if h.get("level") == "H2":
                    matched_keys.add(h["text"].lower().replace("[main]", "").replace("[supp]", "").strip())

            orphan_h3s = []
            for key, children in old_h2_children.items():
                if key not in matched_keys:
                    orphan_h3s.extend(children)

            # Ghép orphan H3s vào các H2 chưa có H3 (word overlap matching)
            if orphan_h3s:
                result2 = []
                orphan_idx = 0
                for h in result:
                    result2.append(h)
                    if h.get("level") == "H2" and orphan_idx < len(orphan_h3s):
                        h_key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                        # Skip nếu H2 đã có H3 hoặc là SUPP/FAQ
                        if h_key in new_h2_has_h3 or "[supp]" in h["text"].lower() or "faq" in h["text"].lower():
                            continue
                        # Fuzzy: tính word overlap
                        h2_words = set(h_key.split())
                        best_score = 0
                        best_idx = orphan_idx
                        for oi in range(orphan_idx, min(orphan_idx + 5, len(orphan_h3s))):
                            o_words = set(orphan_h3s[oi]["text"].lower().split())
                            score = len(h2_words & o_words)
                            if score > best_score:
                                best_score = score
                                best_idx = oi
                        # Chèn orphan H3 phù hợp nhất
                        result2.append(orphan_h3s[best_idx])
                        orphan_h3s.pop(best_idx)
                        new_h2_has_h3.add(h_key)
                result = result2

        final_h3 = sum(1 for h in result if h.get("level") == "H3")
        logger.info("  [H3-DEFENSE %s] Final H3 count after merge: %d (was %d)", step_name, final_h3, old_h3)
        return result

    return new_outline


def rewrite_headings_semantic(
    raw_headings: List[Dict],
    main_keyword: str,
    niche: str,
    intent: str,
    topic: str = "",
    entity: str = "",
    serp_data: Optional[Dict] = None,
    competitor_data: Optional[Dict] = None,
    methodology_prompt: str = "",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35
    eav_table: str = "", # Phase 35
    network_data: Optional[Dict] = None, # Phase 35
    context_data: Optional[Dict] = None, # Phase 35
    semantic_reasoning: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    """
    Phase 19: Xây dựng Outline Toàn Diện từ mọi mảng dữ liệu.

    LLM path: Tổng hợp PAA, Content Gaps, Ngrams vào dàn ý.
    Fallback: Rule-based enrichment (nối ngữ cảnh keyword + niche).
    """
    topic = topic or main_keyword
    entity = entity or main_keyword
    paa_qs = serp_data.get("people_also_ask", [])[:5] if serp_data else []
    outline_signals = _derive_outline_consensus_signals(competitor_data, project=project, topic=topic)
    consensus_points = outline_signals.get("consensus_points", [])
    gap_h2_candidates = outline_signals.get("gap_h2_candidates", [])
    gap_h3_candidates = outline_signals.get("gap_h3_candidates", [])

    # Thử LLM path trước: Tổng hợp Outline Toàn Diện
    raw_enriched = _agent_synthesize_raw_outline(
        main_keyword, niche, serp_data, competitor_data, methodology_prompt,
        intent=intent, project=project,
        macro_context=macro_context, eav_table=eav_table, network_data=network_data, # Phase 35
        consensus_points=consensus_points,
        gap_h2_candidates=gap_h2_candidates,
        gap_h3_candidates=gap_h3_candidates,
        semantic_reasoning=semantic_reasoning,
    )
    if raw_enriched:
        # Snapshot trước khi Agent 2 rewrite (để merge-back H3 nếu bị drop)
        pre_agent2_outline = list(raw_enriched)
        pre_agent2_h3 = sum(1 for h in pre_agent2_outline if h.get("level") == "H3")
        logger.info("  [H3-TRACE] Pre-Agent2: %d H3s", pre_agent2_h3)

        # Agent 2: Enforce Semantic SEO rules
        seo_enriched = _agent_enforce_semantic_seo(
            raw_enriched, main_keyword, intent, project=project,
            context_data=context_data # Phase 35
        )
        enriched = seo_enriched if seo_enriched else raw_enriched

        # DEFENSE: Merge back H3s nếu Agent 2 đã drop chúng
        enriched = _merge_back_h3s(enriched, pre_agent2_outline, step_name="Agent2")

        # Raw PAA có thể lệch ngành, nên chuẩn hóa trước khi đưa vào Agent 3
        paa_raw_outline = serp_data.get("people_also_ask", [])[:5] if serp_data else []
        paa_outline_refinement = refine_paa_questions_for_project(
            topic=topic,
            entity=entity,
            project=project,
            raw_questions=paa_raw_outline,
            intent=intent,
            competitor_data=competitor_data,
        )
        paa_qs = paa_outline_refinement.get("faq_questions", []) or _fallback_project_faq_questions(
            topic, entity, project, paa_raw_outline
        )

        # ═══════════════════════════════════════════════════════════
        #  SPEC V4: AGENT 3 — SEMANTIC REVIEWER (MULTI-PASS)
        #  Pass 3a: Structure + Heading Rewrite (Attribute Filtration)
        #  Pass 3b: H3 Depth (5 data sources + 6 rules)
        # ═══════════════════════════════════════════════════════════
        try:
            from modules.agent_reviewer import review_structure, review_h3_depth

            # Chuẩn bị data chung cho cả 2 pass
            content_gaps = []
            keyword_clusters = []

            # Setup data sources for H3 enforcement fallback
            h3_data_sources = []
            h3_data_sources.extend([str(q) for q in paa_qs])

            if competitor_data:
                info_gain = competitor_data.get("information_gain", {})
                content_gaps = [str(g.get("heading", g) if isinstance(g, dict) else g) for g in info_gain.get("rare_headings", [])]
                h3_data_sources.extend(content_gaps)
                for ch in competitor_data.get("common_headings", []):
                    h3_data_sources.append(str(ch))

            if network_data and network_data.get("clusters"):
                network_clusters = network_data.get("clusters", {})
                if isinstance(network_clusters, dict):
                    network_clusters = network_clusters.get("clusters", [])
                if not isinstance(network_clusters, list):
                    network_clusters = []
                for c in network_clusters:
                    if isinstance(c, dict):
                        keyword_clusters.extend(c.get("keywords", [])[:5])

            # ── PASS 3a: Structure + Heading Rewrite (V4.2) ──
            pre_agent3a_outline = list(enriched)  # Snapshot before Agent 3a
            enriched = review_structure(
                enriched, intent,
                macro_context=macro_context,
                main_keyword=main_keyword,
                eav_table=eav_table,
                keyword_clusters=keyword_clusters,
                paa_questions=[str(q) for q in paa_qs],    # Phase 38: bám H2 vào PAA đã chuẩn hóa
                content_gaps_list=gap_h3_candidates,       # Phase 38: H3/narrow gaps
            )
            # DEFENSE: Merge back H3s nếu Agent 3a đã drop chúng
            enriched = _merge_back_h3s(enriched, pre_agent3a_outline, step_name="Agent3a")

            # ── PASS 3b: H3 Depth from 5 Data Sources (V4.1) ──
            enriched = review_h3_depth(
                enriched,
                content_gaps=gap_h3_candidates,
                paa_questions=[str(q) for q in paa_qs],
                keyword_clusters=keyword_clusters,
                main_keyword=main_keyword,
                eav_table=eav_table,
            )

            post_3b_h3 = sum(1 for h in enriched if h.get("level") == "H3")
            logger.info("  [SPEC V4] Agent 3a + 3b completed. H3 count after 3b: %d", post_3b_h3)

        except ImportError:
            logger.warning("  [SPEC V4] agent_reviewer.py not found → fallback to rule-based.")

            # Setup data sources for fallback (in case try block failed before preparing them)
            paa_qs = paa_raw_outline
            h3_data_sources = []
            h3_data_sources.extend([str(q) for q in paa_qs])
            if competitor_data:
                info_gain = competitor_data.get("information_gain", {})
                h3_data_sources.extend([str(g.get("heading", g) if isinstance(g, dict) else g) for g in info_gain.get("rare_headings", [])])
                for ch in competitor_data.get("common_headings", []):
                    h3_data_sources.append(str(ch))
            enriched = _postprocess_brand_h2_reorder(enriched, intent, main_keyword)

        # ── H3 ENFORCEMENT (Luôn luôn chạy sau khi qua Agent) ──
        enriched = _enforce_h3_ratio(enriched, main_keyword, h3_data_sources)

        # ── Deterministic post-processors (luôn chạy) ──
        enriched = _ensure_competitor_archetype_coverage(
            enriched,
            main_keyword,
            intent,
            outline_signals=outline_signals,
        )
        enriched = _postprocess_prominence_blacklist(enriched, project)
        enriched = _postprocess_supp_enforcer(enriched, main_keyword, intent, paa_questions=paa_qs)
        enriched = _align_outline_to_preferred_flow(
            enriched,
            preferred_order=(semantic_reasoning or {}).get("preferred_flow", []),
        )
        enriched = _apply_source_context_outline_gate(
            enriched,
            topic=main_keyword,
            intent=intent,
            project=project,
            niche=niche,
            paa_questions=paa_qs,
        )
        enriched = _apply_semantic_outline_gate(enriched, main_keyword, semantic_reasoning)
        enriched = _enforce_h3_ratio(enriched, main_keyword, h3_data_sources)
        enriched = _clean_slot_filled_outline(enriched, topic=main_keyword)

        # Giữ lại H1 ban đầu (vì LLM chỉ build H2/H3)
        h1 = [h for h in raw_headings if h["level"] == "H1"]
        if not h1:
            h1 = [{"level": "H1", "text": main_keyword.title()}]

        # LỌC BỎ BẤT KỲ H1 NÀO BỊ LLM TẠO THỪA TRONG enriched
        enriched = [h for h in enriched if str(h.get("level", "")).upper() != "H1"]
        return h1 + enriched

    # Fallback: Rule-based enrichment
    logger.info("  [HEADING] Rule-based enrichment (không có LLM hoặc JSON lỗi)")
    enriched = _rule_based_heading_enrichment(
        raw_headings,
        main_keyword,
        niche,
        consensus_points=consensus_points,
        gap_h2_candidates=gap_h2_candidates,
        gap_h3_candidates=gap_h3_candidates,
    )

    # ── POST-PROCESSOR 1: PROMINENCE BLACKLIST ──
    enriched = _ensure_competitor_archetype_coverage(
        enriched,
        main_keyword,
        intent,
        outline_signals=outline_signals,
    )
    enriched = _postprocess_prominence_blacklist(enriched, project)

    # ── POST-PROCESSOR 2: SUPP SECTION ENFORCER ──
    enriched = _postprocess_supp_enforcer(enriched, main_keyword, intent, paa_questions=paa_qs)
    enriched = _align_outline_to_preferred_flow(
        enriched,
        preferred_order=(semantic_reasoning or {}).get("preferred_flow", []),
    )

    # ── POST-PROCESSOR 3: BRAND H2 REORDER (P7.2) ──
    enriched = _apply_source_context_outline_gate(
        enriched,
        topic=main_keyword,
        intent=intent,
        project=project,
        niche=niche,
        paa_questions=paa_qs,
    )
    enriched = _apply_semantic_outline_gate(enriched, main_keyword, semantic_reasoning)
    fallback_h3_sources = []
    fallback_h3_sources.extend([str(q) for q in (paa_qs or [])])
    fallback_h3_sources.extend([str(g) for g in (gap_h3_candidates or [])])
    fallback_h3_sources.extend([str(h) for h in (consensus_points or [])])
    enriched = _enforce_h3_ratio(enriched, main_keyword, fallback_h3_sources)
    enriched = _postprocess_brand_h2_reorder(enriched, intent, main_keyword)
    enriched = _enforce_h3_ratio(enriched, main_keyword, fallback_h3_sources)
    enriched = _clean_slot_filled_outline(enriched, topic=main_keyword)

    h1 = [h for h in raw_headings if h["level"] == "H1"]
    if not h1:
        h1 = [{"level": "H1", "text": main_keyword.title()}]

    enriched = [h for h in enriched if str(h.get("level", "")).upper() != "H1"]
    return h1 + enriched


def _get_min_h2_for_intent(intent: str) -> int:
    """Số H2 tối thiểu theo intent (V17: 4 loại chuẩn)."""
    intent_lower = intent.lower()
    # Backward compat: vs → commercial
    if "vs" in intent_lower or "comparison" in intent_lower:
        intent_lower = "commercial"
    minimums = {
        "commercial": 5,
        "informational": 4,
        "how-to": 4,
        "transactional": 3,
        "navigational": 2,
    }
    return minimums.get(intent_lower, 3)


def _get_min_h2_for_vs_symmetry(outline: list) -> bool:
    """
    VS intent: kiểm tra H2 có symmetric không.
    Symmetric = có ít nhất 1 H2 nói về Entity A riêng VÀ 1 H2 nói về Entity B riêng
    VÀ ít nhất 1 H2 so sánh trực tiếp cả 2.
    Return True nếu OK, False nếu cần retry.
    """
    h2_headings = [h["text"].lower() for h in outline if h.get("level") == "H2"]
    has_comparison_h2 = any(
        any(sig in h for sig in ["so sánh", "khác nhau", "vs", "compare", "khác biệt"])
        for h in h2_headings
    )
    return has_comparison_h2


def _agent_synthesize_raw_outline(
    topic: str,
    niche: str,
    serp_data: Optional[Dict],
    competitor_data: Optional[Dict],
    methodology_prompt: str,
    intent: str = "informational",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35
    eav_table: str = "", # Phase 35
    network_data: Optional[Dict] = None, # Phase 35
    consensus_points: Optional[List[str]] = None,
    gap_h2_candidates: Optional[List[str]] = None,
    gap_h3_candidates: Optional[List[str]] = None,
    semantic_reasoning: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict]]:
    """
    Agent 1: The Synthesizer.
    Tổng hợp dữ liệu PAA, Content Gaps, N-grams vào chung 1 cấu trúc logic tịnh tiến.
    Trả về cấu trúc chuẩn JSON list các dict: [{"level": "H2", "text": "..."}]
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return None

        import openai
        import json
        client = openai.OpenAI(api_key=api_key)

        # ── Chuẩn bị Dữ liệu đầu vào ──
        paa = []
        if serp_data:
            paa = serp_data.get("people_also_ask", [])[:5]

        gaps = []
        ngrams = []
        comp_headings = []
        competitor_archetypes: List[str] = []
        if competitor_data:
            info_gain = competitor_data.get("information_gain", {})
            raw_gaps = info_gain.get("rare_headings", [])[:10]
            # V16-2: Prominence Gate Filter (Universal)
            # Lọc bỏ heading mang tính quy trình/vận hành (procedural/operational)
            # không phù hợp cho bài định nghĩa (informational/what-is).
            # LLM Agent 1 sẽ tự điều chỉnh theo ngành dựa trên Source Context.
            PROCEDURAL_PATTERNS = [
                'quy trình', 'hướng dẫn bảo trì', 'bảo dưỡng định kỳ',
                'kiểm định', 'kiểm tra chất lượng', 'cảnh báo an toàn',
                'hướng dẫn sử dụng', 'cách xử lý sự cố', 'lịch bảo dưỡng',
                'checklist', 'biên bản nghiệm thu', 'sổ tay vận hành',
            ]
            if 'là gì' in topic.lower() or intent == 'informational':
                gaps = [
                    g for g in raw_gaps
                    if not any(p in str(g).lower() for p in PROCEDURAL_PATTERNS)
                ]
            else:
                gaps = raw_gaps
            gaps = gaps[:7]
            ngrams_2 = competitor_data.get("ngrams_2", [])[:10]
            # Convert ngrams to string list
            ngrams = [f"{n[0]} (tần suất {n[1]})" if isinstance(n, tuple) else str(n) for n in ngrams_2]
            comp_headings = _filter_project_contamination_terms(
                [str(h).strip() for h in competitor_data.get("common_headings", []) if str(h).strip()],
                project=project,
                topic=topic,
            )[:10]
            archetype_summary = competitor_data.get("archetype_summary", {}) if isinstance(competitor_data.get("archetype_summary"), dict) else {}
            top_archetypes = archetype_summary.get("top_archetypes", []) if isinstance(archetype_summary.get("top_archetypes", []), list) else []
            competitor_archetypes = [
                str(item.get("archetype", "")).strip()
                for item in top_archetypes[:4]
                if isinstance(item, dict) and str(item.get("archetype", "")).strip()
            ]
            ngrams = _collect_prompt_semantic_terms(
                topic,
                intent,
                project=project,
                candidates=ngrams,
                limit=12,
            )

        consensus_points = [str(x).strip() for x in (consensus_points or []) if str(x).strip()]
        gap_h2_candidates = [str(x).strip() for x in (gap_h2_candidates or []) if str(x).strip()]
        gap_h3_candidates = [str(x).strip() for x in (gap_h3_candidates or []) if str(x).strip()]
        eav_rows = _parse_eav_rows(eav_table)
        intent_pack = _infer_topic_focus_pack(
            topic,
            intent,
            consensus_points=consensus_points,
            gap_h2_candidates=gap_h2_candidates,
            gap_h3_candidates=gap_h3_candidates,
            eav_rows=eav_rows,
        )
        reasoning = semantic_reasoning if isinstance(semantic_reasoning, dict) else {}

        # Phase 35: Xử lý Semantic Query Network string
        # Fix: clusters có thể là dict (LLM wrap với response_format) hoặc numpy array
        # → normalize về list[dict] trước khi truy cập [:4] và .get()
        network_str = ""
        if network_data and network_data.get("clusters"):
            clusters_raw = network_data.get("clusters", [])
            # Normalize: dict{numpy} → list, dict{wrapped} → list, string → empty
            if isinstance(clusters_raw, dict):
                # LLM wrap {"clusters": [...]}: lấy values hoặc items
                if "clusters" in clusters_raw:
                    clusters_raw = clusters_raw["clusters"]
                else:
                    clusters_raw = list(clusters_raw.values()) if clusters_raw else []
            elif not isinstance(clusters_raw, list):
                clusters_raw = []
            # Convert numpy array (nếu có) → list
            try:
                clusters_raw = list(clusters_raw)
            except Exception:
                clusters_raw = []
            lines = []
            for c in clusters_raw[:4]:
                if isinstance(c, dict):
                    name = c.get("name", "Unnamed")
                    keywords = c.get("keywords", [])
                    if isinstance(keywords, list):
                        kw_str = ", ".join(str(k) for k in keywords[:3])
                    else:
                        kw_str = str(keywords) if keywords else ""
                    lines.append(f"- Cluster '{name}': {kw_str}")
            network_str = "\n".join(lines)

        # Prompt contract now lives in modules.outline_content_prompt_catalog.
        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context

        # Phase 35: Chained Context injection
        mc_block = f"📍 MACRO CONTEXT TRỌNG TÂM:\n{macro_context}\n\n" if macro_context else ""
        eav_block = f"📍 EAV TABLE (THỰC THỂ & THUỘC TÍNH BẮT BUỘC COVER):\n{eav_table}\n\n" if eav_table else ""
        net_block = f"📍 SEMANTIC QUERY NETWORK (CLUSTERS):\n{network_str}\n\n" if network_str else ""
        consensus_block = ""
        if consensus_points:
            consensus_block = "📍 CONSENSUS INFORMATION (shared competitor themes):\n- " + "\n- ".join(consensus_points[:6]) + "\n\n"
        gap_h2_block = ""
        if gap_h2_candidates:
            gap_h2_block = "📍 BROAD GAP TOPICS (can become H2):\n- " + "\n- ".join(gap_h2_candidates[:5]) + "\n\n"
        gap_h3_block = ""
        if gap_h3_candidates:
            gap_h3_block = "📍 NARROW GAP TOPICS (better as H3/support):\n- " + "\n- ".join(gap_h3_candidates[:7]) + "\n\n"
        archetype_block = ""
        if competitor_archetypes:
            archetype_block = (
                "📍 COMPETITOR CONTENT ARCHETYPES (full-body patterns from top-ranking pages):\n- "
                + "\n- ".join(competitor_archetypes[:4])
                + "\nUse these only as evidence-backed section-shape hints; include a section type only when the current SERP, competitor body, gap, or EAV data supports it.\n\n"
            )
        intent_lock_block = ""
        if intent_pack:
            must_cover = intent_pack.get("must_cover", []) or []
            avoid_drift = intent_pack.get("avoid_drift", []) or []
            preferred_order = intent_pack.get("preferred_order", []) or []
            semantic_terms = _collect_prompt_semantic_terms(
                topic,
                intent,
                project=project,
                candidates=(intent_pack.get("semantic_terms", []) or []) + ngrams + consensus_points + gap_h2_candidates + gap_h3_candidates,
                limit=10,
            )
            intent_lock_block = (
                "📍 DEEP SEARCH INTENT:\n"
                f"- Real user task: {intent_pack.get('search_task', '')}\n"
                + ("- Must cover:\n- " + "\n- ".join(must_cover[:6]) + "\n" if must_cover else "")
                + ("- Preferred H2 order:\n- " + "\n- ".join(preferred_order[:7]) + "\n" if preferred_order else "")
                + ("- Off-topic exclusions:\n- " + "\n- ".join(avoid_drift[:5]) + "\n" if avoid_drift else "")
                + ("- Preferred semantic support terms:\n- " + "\n- ".join(semantic_terms[:10]) + "\n" if semantic_terms else "")
                + "\n"
            )

        reasoning_block = ""
        if reasoning:
            dominant_user_task = str(reasoning.get("dominant_user_task", "")).strip()
            supporting_tasks = [str(x).strip() for x in reasoning.get("supporting_tasks", []) if str(x).strip()]
            decision_blockers = [str(x).strip() for x in reasoning.get("decision_blockers", []) if str(x).strip()]
            misinterpretation_risks = [str(x).strip() for x in reasoning.get("misinterpretation_risks", []) if str(x).strip()]
            consensus_facts = [str(x).strip() for x in reasoning.get("consensus_facts", []) if str(x).strip()]
            semantic_terms_curated = [str(x).strip() for x in reasoning.get("semantic_terms_curated", []) if str(x).strip()]
            preferred_flow = [str(x).strip() for x in reasoning.get("preferred_flow", []) if str(x).strip()]
            semantic_blueprint = reasoning.get("semantic_blueprint", {}) if isinstance(reasoning.get("semantic_blueprint"), dict) else {}
            gap_map = reasoning.get("gap_map", {}) if isinstance(reasoning.get("gap_map"), dict) else {}
            reasoning_block = "📍 SEMANTIC REASONING LAYER:\n"
            if dominant_user_task:
                reasoning_block += f"- Dominant user task: {dominant_user_task}\n"
            if supporting_tasks:
                reasoning_block += "- Supporting tasks:\n- " + "\n- ".join(supporting_tasks[:6]) + "\n"
            if decision_blockers:
                reasoning_block += "- Decision blockers:\n- " + "\n- ".join(decision_blockers[:5]) + "\n"
            if misinterpretation_risks:
                reasoning_block += "- Misinterpretation risks / drift to avoid:\n- " + "\n- ".join(misinterpretation_risks[:5]) + "\n"
            if consensus_facts:
                reasoning_block += "- Consensus facts readers expect:\n- " + "\n- ".join(consensus_facts[:6]) + "\n"
            if preferred_flow:
                reasoning_block += "- Preferred article flow:\n- " + "\n- ".join(preferred_flow[:8]) + "\n"
            if semantic_blueprint:
                role_lines = []
                for spec in semantic_blueprint.get("role_specs", [])[:8]:
                    if isinstance(spec, dict) and spec.get("role"):
                        role_lines.append(f"{spec.get('role')}: {spec.get('why', '')}")
                if role_lines:
                    reasoning_block += "- Semantic blueprint role order:\n- " + "\n- ".join(role_lines) + "\n"
                if semantic_blueprint.get("source_context_available"):
                    reasoning_block += "- Evidence priority: source context and project topical map outrank SERP fallback.\n"
                else:
                    reasoning_block += "- Evidence priority: no project source context detected; use SERP/competitor/PAA fallback without inventing brand scope.\n"
            if semantic_terms_curated:
                reasoning_block += "- Curated semantic support terms:\n- " + "\n- ".join(semantic_terms_curated[:10]) + "\n"
            if gap_map.get("h2_worthy"):
                reasoning_block += "- H2-worthy gaps:\n- " + "\n- ".join(gap_map.get("h2_worthy", [])[:6]) + "\n"
            if gap_map.get("supporting_detail"):
                reasoning_block += "- Supporting-detail gaps:\n- " + "\n- ".join(gap_map.get("supporting_detail", [])[:6]) + "\n"
            if gap_map.get("topical_expansion"):
                reasoning_block += "- Topical expansions:\n- " + "\n- ".join(gap_map.get("topical_expansion", [])[:5]) + "\n"
            if gap_map.get("noise"):
                reasoning_block += "- Noise to ignore:\n- " + "\n- ".join(gap_map.get("noise", [])[:5]) + "\n"
            reasoning_block += "\n"

        logger.info("  [HEADING SYNTHESIS] Gọi LLM để tổng hợp Outline Toàn Diện...")

        semantic_context = (
            f"{mc_block}{eav_block}{net_block}{consensus_block}{archetype_block}"
            f"{gap_h2_block}{gap_h3_block}{intent_lock_block}{reasoning_block}"
        ).strip()
        competitor_inputs = (
            "PAA Questions:\n- " + "\n- ".join([str(q) for q in paa])
            + "\n\nContent Gaps:\n- " + "\n- ".join([str(g) for g in gaps])
            + "\n\nCommon Headings:\n- " + "\n- ".join([str(h) for h in comp_headings])
            + "\n\nSemantic N-grams:\n- " + "\n- ".join([str(n) for n in ngrams])
        ).strip()
        agent1_system, agent1_user = build_agent1_outline_prompts(
            topic=topic,
            intent_label=intent,
            methodology_prompt=methodology_prompt[:200] if methodology_prompt else "General",
            semantic_context=semantic_context,
            competitor_inputs=competitor_inputs,
        )
        agent1_system += (
            "\n\nTOPIC PURITY RULES:\n"
            "- Khong duoc dua vao outline bat ky concept nao neu concept do khong duoc sinh ra tu query hien tai, consensus hien tai, gap hien tai hoac EAV hien tai.\n"
            "- Khong duoc tai su dung semantic cua keyword truoc.\n"
            "- Moi vi du trong prompt chi la vi du cau truc, khong phai noi dung bat buoc.\n"
            "- Neu query hien tai khong tao ra mot lop thong tin nao, khong tu y them lop thong tin do vao H2/H3.\n"
            "- Uu tien preferred flow, consensus facts va gap classification cua keyword hien tai hon moi template co san.\n"
        )
        system_instruction = inject_semantic_prompt(agent1_system, agent_name="agent_1_outline")
        system_instruction = inject_source_context(system_instruction, project)
        user_content = agent1_user

        # Phase 2.3: Use llm_utils for retry + centralized settings
        from modules.llm_utils import call_llm_outline
        raw_text = call_llm_outline(
            client=client,
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
        )
        # Clean JSON markdown blocks if any
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        # Bug D fix (1/2): wrap json.loads in try/except to prevent crash on invalid JSON
        try:
            outline_data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("  [AGENT 1] JSON parse failed: %s", exc)
            return None

        # V8.1: Parse both nested (children) and flat format
        validated_outline = []
        for item in outline_data:
            if isinstance(item, dict) and "level" in item and "text" in item:
                lvl = str(item["level"]).upper()
                if lvl in ["H2", "H3", "H4"]:
                    validated_outline.append({"level": lvl, "text": item["text"]})
                # V8.1: Flatten nested children into flat list
                children = item.get("children", [])
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, dict) and "text" in child:
                            child_lvl = str(child.get("level", "H3")).upper()
                            if child_lvl in ["H3", "H4"]:
                                validated_outline.append({"level": child_lvl, "text": child["text"]})

        logger.info("  [AGENT 1] Parsed %d headings (H2: %d, H3: %d)",
                     len(validated_outline),
                     sum(1 for h in validated_outline if h["level"] == "H2"),
                     sum(1 for h in validated_outline if h["level"] == "H3"))

        if validated_outline:
            # ── H2 MINIMUM ENFORCEMENT & SYMMETRY CHECK ──
            h2_count = sum(1 for h in validated_outline if h["level"] == "H2")
            min_required = _get_min_h2_for_intent(intent)

            retry_needed = False
            retry_reason = ""

            if h2_count < min_required:
                retry_needed = True
                retry_reason = f"Chỉ có {h2_count} H2, cần tối thiểu {min_required} cho intent '{intent}'."

            if "vs" in intent.lower() and not _get_min_h2_for_vs_symmetry(validated_outline):
                retry_needed = True
                retry_reason += " VS intent thiếu H2 so sánh trực tiếp giữa 2 entity."

            h3_count = sum(1 for h in validated_outline if h["level"] == "H3")
            if h2_count > 0 and (h3_count / h2_count) < 0.5:
                retry_needed = True
                retry_reason += f" Có {h2_count} H2 nhưng chỉ có {h3_count} H3 (Tỷ lệ < 50%)."

            if retry_needed:
                logger.warning(
                    "  [AGENT 1] Validation failed: %s. Retry...",
                    retry_reason
                )
                # Retry 1 lần với explicit penalty warning
                retry_user_content = user_content + (
                    f"\n\n⚠️ CẢNH BÁO: Outline vừa tạo bị từ chối. Lý do: {retry_reason}\n\n"
                    f"YÊU CẦU BẮT BUỘC cho lần này:\n"
                    f"- Tối thiểu {min_required} H2 headings (MAIN content)\n"
                    f"- Mỗi H2 phải cover 1 attribute/aspect riêng biệt\n"
                    f"- BẮT BUỘC: Xây dựng Contextual Hierarchy sâu bằng cách chêm thêm các node H3 mở rộng bên trong cấu trúc H2 lớn.\n"
                    f"- Với 'vs' intent: PHẢI có H2 định nghĩa Entity A, H2 định nghĩa Entity B, "
                    f"VÀ ít nhất 1 H2 so sánh trực tiếp (cả 2 entity trong cùng heading)\n"
                    f"- KHÔNG dùng H2 chỉ nói về 1 entity trong bài 'vs' (ví dụ: chỉ nói về quy trình của A mà không so sánh với B)"
                )
                try:
                    # Phase 2.3: Use llm_utils for retry
                    from modules.llm_utils import call_llm_outline
                    retry_raw = call_llm_outline(
                        client=client,
                        model=LLM_CONFIG.get("model", "gpt-4o-mini"),
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": retry_user_content},
                        ],
                    )
                    if retry_raw.startswith("```json"):
                        retry_raw = retry_raw[7:]
                    if retry_raw.startswith("```"):
                        retry_raw = retry_raw[3:]
                    if retry_raw.endswith("```"):
                        retry_raw = retry_raw[:-3]
                    retry_raw = retry_raw.strip()
                    # Bug D fix (2/2): wrap retry json.loads in try/except + initialize retry_data
                    try:
                        retry_data = json.loads(retry_raw)
                    except (json.JSONDecodeError, TypeError) as exc:
                        logger.warning("  [AGENT 1] Retry JSON parse failed: %s", exc)
                        retry_data = []  # MUST initialize to prevent NameError in loop below
                    retry_outline = []
                    if not retry_data:
                        logger.warning("  [AGENT 1] Retry data empty, using original validated_outline")
                    for item in retry_data:
                        if isinstance(item, dict) and "level" in item and "text" in item:
                            lvl = str(item["level"]).upper()
                            if lvl in ["H2", "H3", "H4"]:
                                retry_outline.append({"level": lvl, "text": item["text"]})
                            for child in item.get("children", []):
                                if isinstance(child, dict) and "text" in child:
                                    child_lvl = str(child.get("level", "H3")).upper()
                                    if child_lvl in ["H3", "H4"]:
                                        retry_outline.append({"level": child_lvl, "text": child["text"]})
                    retry_h2 = sum(1 for h in retry_outline if h["level"] == "H2")
                    if retry_h2 >= min_required:
                        logger.info("  [AGENT 1] Retry thành công: %d H2 (cần %d)", retry_h2, min_required)
                        validated_outline = retry_outline
                    else:
                        logger.warning("  [AGENT 1] Retry vẫn chỉ có %d H2. Dùng outline gốc.", retry_h2)
                except Exception as retry_err:
                    logger.warning("  [AGENT 1] Retry lỗi: %s. Dùng outline gốc.", str(retry_err))

            # ── PROGRAMMATIC H3 ENFORCER (FAIL-SAFE) ──
            h3_src = [str(g.get("heading", g) if isinstance(g, dict) else g) for g in gaps]
            h3_src += [str(h) for h in comp_headings]
            h3_src += [str(q) for q in paa]

            if eav_table:
                for line in eav_table.split("\n"):
                    if line.strip().startswith("|") and "---" not in line and "Entity" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            attr_name = parts[1]
                            if len(attr_name) > 3:
                                # FIX 1: Clean intent modifiers from topic before inserting
                                topic_entity = topic.replace("là gì", "").replace("tổng quan về", "").strip()
                                h3_src.append(f"{attr_name} của {topic_entity} như thế nào?")

            validated_outline = _enforce_h3_ratio(validated_outline, topic, h3_src)

            logger.info("  [HEADING SYNTHESIS] Cấu trúc thành công %d headings!", len(validated_outline))
            return validated_outline
        else:
            logger.warning("  [HEADING SYNTHESIS] JSON không hợp lệ. Fallback.")
            return None

    except Exception as e:
        logger.warning("  [AGENT 1] Lỗi API: %s → Fallback...", str(e))
        return None



def _agent_enforce_semantic_seo(
    headings: List[Dict],
    entity: str,
    intent: str,
    project=None,  # Phase 33: Source Context
    context_data: Optional[Dict] = None, # Phase 35: Chained Context
) -> Optional[List[Dict]]:
    """
    Agent 2: The Semantic SEO Enforcer.
    Chỉ nhận vào 1 mảng JSON outline và làm 1 việc DUY NHẤT:
    Viết lại (Rewrite) tên Heading sao cho đúng chuẩn Semantic.
    Tuyệt đối không thay đổi luồng ý hay logic của outline gốc.
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return None

        import openai
        import json
        client = openai.OpenAI(api_key=api_key)

        # Phase 35: Xử lý Context Vectors string
        vectors_str = ""
        if context_data and context_data.get("vectors"):
            vectors = context_data.get("vectors", [])
            lines = []
            for v in vectors[:3]: # Lấy 3 vectors chính
                lines.append(f"- Context Vector [{v.get('type', '')}]: {v.get('direction', '')}")
            vectors_str = "\n".join(lines)

        # V8.1: Đếm H3 input để enforce trong prompt
        input_h3_count = sum(1 for h in headings if h.get("level") == "H3")
        input_h2_count = sum(1 for h in headings if h.get("level") == "H2")

        # Agent 2 prompt contract is centralized in outline_content_prompt_catalog.
        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context

        logger.info("  [AGENT 2] Gọi LLM Semantic Enforcer để SEO-ify Outline...")

        agent2_system, agent2_user = build_agent2_semantic_prompts(
            entity=entity,
            intent_label=intent,
            vectors_text=vectors_str,
            headings_json=json.dumps(headings, ensure_ascii=False, indent=2),
            input_h2_count=input_h2_count,
            input_h3_count=input_h3_count,
        )
        system_instruction = inject_semantic_prompt(agent2_system, agent_name="agent_2_semantic")
        system_instruction = inject_source_context(system_instruction, project)
        user_content = agent2_user

        # Phase 2.3: Use llm_utils for retry + centralized settings
        from modules.llm_utils import call_llm_seo
        raw_text = call_llm_seo(
            client=client,
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
        )
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        # Bug C fix: wrap json.loads in try/except to prevent crash on invalid JSON
        try:
            outline_data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("  [AGENT 2] JSON parse failed: %s", exc)
            return None

        validated_outline = []
        for item in outline_data:
            if isinstance(item, dict) and "level" in item and "text" in item:
                lvl = str(item["level"]).upper()
                if lvl in ["H2", "H3", "H4"]:
                    validated_outline.append({"level": lvl, "text": item["text"]})

        if validated_outline:
            logger.info("  [AGENT 2] Semantic Enforcer đã rewrite thành công %d headings!", len(validated_outline))
            return validated_outline
        else:
            return None

    except Exception as e:
        logger.warning("  [AGENT 2] Lỗi API: %s", str(e))
        return None


# ── P1.3 FIX: Navigation heading blacklist ──
# Các heading này là navigation elements bị scrape nhầm từ competitor sites,
# KHÔNG phải content heading. Phải lọc bỏ.
NAVIGATION_HEADING_BLACKLIST = [
    "liên kết nhanh", "liên hệ", "chi nhánh", "đăng ký", "đăng nhập",
    "hỗ trợ trực tuyến", "hỗ trợ khách hàng", "hotline", "bản đồ",
    "về chúng tôi", "thông tin liên hệ", "danh mục", "danh mục sản phẩm",
    "tải xuống", "sản phẩm liên quan", "tin tức", "tin tức nổi bật",
    "tin tức & sự kiện", "hình ảnh công ty", "bài viết cùng chủ đề",
    "quick link", "phòng kinh doanh", "trụ sở chính", "đăng ký nhận",
    "bình luận", "để lại một bình luận",
    "từ khóa",
    "các sự kiện liên quan", "các bài viết liên quan", "danh mục tin tức",
    "đăng ký nhận tin", "mô tả",
]


def _is_navigation_heading(text: str) -> bool:
    """Kiểm tra xem heading có phải navigation element không."""
    text_lower = text.lower().strip()
    # Exact match hoặc bắt đầu bằng blacklisted term
    for term in NAVIGATION_HEADING_BLACKLIST:
        if text_lower == term or text_lower.startswith(term):
            return True
    return False


def _h2_has_child_h3(outline: List[Dict], h2_index: int) -> bool:
    """Return True when an H2 owns at least one H3 before the next H2."""
    for item in outline[h2_index + 1:]:
        level = str(item.get("level", "")).upper()
        if level == "H2":
            return False
        if level == "H3":
            return True
    return False


def _enforce_h3_ratio(outline: List[Dict], main_keyword: str, h3_sources: List[str] = None) -> List[Dict]:
    """
    Đảm bảo chắc chắn dàn ý có tỷ lệ H3/H2 >= 50% (Koray Framework).
    Nếu thiếu, sẽ tự động chèn H3 bằng dữ liệu thực, sau đó dùng template ngữ cảnh.

    V8 FIX:
    - Giảm ngưỡng lọc source từ 10→5 ký tự
    - Thêm contextual question templates khi hết data thực
    - KHÔNG BAO GIỜ break sớm — luôn đạt ≥50%
    """
    if h3_sources is None:
        h3_sources = []

    h2_indices = [i for i, h in enumerate(outline) if h.get("level") == "H2"]
    h3_count = sum(1 for h in outline if h.get("level") == "H3")

    if not h2_indices:
        return outline

    h2_with_h3 = sum(1 for idx in h2_indices if _h2_has_child_h3(outline, idx))
    coverage = float(h2_with_h3) / len(h2_indices)
    target_h2_with_h3 = len(h2_indices) // 2 + (1 if len(h2_indices) % 2 != 0 else 0)
    if coverage >= 0.5:
        logger.info(
            "  [ENFORCER] H3 coverage OK: %.0f%% (%d H2 with H3 / %d H2)",
            coverage * 100,
            h2_with_h3,
            len(h2_indices),
        )
        return outline

    logger.warning("  [ENFORCER] Dàn ý thiếu H3 (có %d H3 / %d H2 = %.0f%%). Tự động bổ sung...",
                    h2_with_h3, len(h2_indices), coverage * 100)
    h3_needed = target_h2_with_h3 - h2_with_h3

    # Tìm các H2 [MAIN] chưa có H3 ngay bên dưới
    h2_without_h3 = []
    for idx in h2_indices:
        if not _h2_has_child_h3(outline, idx):
            text_lower = outline[idx]["text"].lower()
            if "[supp]" not in text_lower and "faq" not in text_lower:
                h2_without_h3.append(idx)

    # P7.1: ƯU TIÊN dùng dữ liệu thực từ Content Gaps, PAA, N-grams
    # V8: Giảm ngưỡng từ 10→5 ký tự để giữ được nhiều source hơn
    sources_to_use = []
    for s in (h3_sources or []):
        s_clean = str(s).strip()
        if len(s_clean) < 5:
            continue
        if s_clean.lower().startswith("h1") or s_clean.lower().startswith("h2"):
            continue
        # Lọc navigation junk
        if any(nav in s_clean.lower() for nav in NAVIGATION_HEADING_BLACKLIST):
            continue
        sources_to_use.append(s_clean)

    logger.info("  [ENFORCER] Available sources: %d (need %d H3s for %d H2s without H3)",
                len(sources_to_use), h3_needed, len(h2_without_h3))

    inserted = 0
    offset = 0
    for idx in h2_without_h3:
        if inserted >= h3_needed:
            break

        h2_text = outline[idx + offset]["text"]
        h2_text_clean = h2_text.lower().replace("[main]", "").replace("[supp]", "").strip()

        h3_text = None
        if sources_to_use:
            # Chọn H3 source PHÙ HỢP NHẤT với H2 cha (word overlap)
            best_match_idx = None
            best_score = 0
            for si, src in enumerate(sources_to_use):
                src_words = set(src.lower().split())
                h2_words = set(h2_text_clean.split())
                overlap = len(src_words & h2_words)
                if overlap > best_score:
                    best_score = overlap
                    best_match_idx = si

            # FIX 2: If best_score == 0, trigger boolean fallback instead of random pick
            if best_score > 0 and best_match_idx is not None:
                pick_idx = best_match_idx
                h3_text = sources_to_use.pop(pick_idx)

                # Chuẩn hóa
                h3_text = h3_text.replace("H3:", "").replace("h3:", "").strip("- *:#")
                if h3_text:
                    h3_text = h3_text[0].upper() + h3_text[1:]
                    # V11-R2: Chỉ thêm suffix nếu KHÔNG phải câu hỏi VÀ quá ngắn (1 word)
                    if "?" not in h3_text and len(h3_text.split()) <= 1:
                        if not h3_text.isupper():
                            h3_text = f"{h3_text} — điều gì cần lưu ý?"
                else:
                    h3_text = None

        if not h3_text:
            # V9 FALLBACK: Sinh H3 từ logic semantic (Boolean / Query dạng ngắn) thay vì template chung chung
            h2_core = h2_text_clean
            for stop in ["là gì", "như thế nào", "ra sao", "bao nhiêu", "tổng quan", "chi tiết"]:
                h2_core = h2_core.replace(stop, "").strip()

            if len(h2_core.split()) >= 2:
                # FIX 3: Clean main_keyword to avoid tautology with full keyword
                entity = main_keyword.replace("là gì", "").replace("tổng quan", "").strip().title()

                # V19: Strict semantic overlap check to prevent tautological H3s (e.g., A có A không?)
                h2_words = set(h2_core.lower().strip().split())
                entity_words = set(entity.lower().strip().split())
                overlap = len(h2_words & entity_words) / max(len(entity_words), 1)

                if overlap < 0.6 and h2_core.lower().strip() != entity.lower().strip():
                    h3_text = f"{h2_core}: can lam ro dieu gi tu du lieu SERP?" if inserted % 2 == 0 else f"{h2_core}: dau la diem nguoi doc can kiem chung?"
                else:
                    # Tautology detected: H2 trùng topic → dùng câu hỏi chung phù hợp mọi ngành
                    h3_text = f"{entity}: du lieu nao can duoc giai thich truoc khi ket luan?"
            else:
                # Nếu H2 quá ngắn
                h3_text = f"{h2_text_clean}: can bo sung bang chung nao?"

            logger.info("  [ENFORCER] Generated Logical H3 for '%s': '%s'", h2_text[:40], h3_text)

        # V12: Sanitize H3 — strip ?? artifacts and ensure no broken question marks
        if h3_text:
            h3_text = h3_text.replace("??", "?").rstrip("?") + "?" if "?" in h3_text else h3_text
            # Strip if H3 is already a natural question — don't double-append suffix
            natural_q_signals = ["là gì", "như thế nào", "khi nào", "tại sao", "bao nhiêu", "có nên", "ở đâu"]
            is_natural_q = any(sig in h3_text.lower() for sig in natural_q_signals) or h3_text.endswith("?")
            if is_natural_q and "điều gì cần lưu ý" in h3_text:
                h3_text = h3_text.replace(" — điều gì cần lưu ý?", "?").replace("? — điều gì cần lưu ý", "")

        outline.insert(idx + offset + 1, {"level": "H3", "text": h3_text})
        offset += 1
        inserted += 1

    final_h3 = sum(1 for h in outline if h.get("level") == "H3")
    final_h2 = sum(1 for h in outline if h.get("level") == "H2")
    logger.info("  [ENFORCER] Done: Inserted %d H3s. Final ratio: %d H3 / %d H2 = %.0f%%",
                inserted, final_h3, final_h2, (final_h3 / final_h2 * 100) if final_h2 else 0)
    return outline


def _rule_based_heading_enrichment(
    raw_headings: List[Dict],
    main_keyword: str,
    niche: str,
    consensus_points: Optional[List[str]] = None,
    gap_h2_candidates: Optional[List[str]] = None,
    gap_h3_candidates: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Enrichment rule-based: giữ heading nguyên gốc, chỉ lọc navigation junk.

    P1.2 FIX: KHÔNG thêm suffix "— Lợi ích" vào heading nữa.
    P1.3 FIX: Lọc bỏ navigation headings bị scrape nhầm.
    """
    result = []
    for h in raw_headings:
        if h["level"] == "H1":
            result.append(h)
            continue

        # P1.3: Lọc bỏ navigation headings
        if _is_navigation_heading(h["text"]):
            logger.info("  [HEADING] Lọc bỏ navigation heading: '%s'", h["text"])
            continue

        # Giữ nguyên heading — KHÔNG thêm suffix
        result.append(h)

    result = _inject_outline_h2_candidates(
        result,
        (consensus_points or []) + (gap_h2_candidates or []),
        main_keyword,
    )

    # Enforce H3 ratio cho Fallback path
    result = _enforce_h3_ratio(result, main_keyword)
    return result


# ══════════════════════════════════════════════
#  SMART N-GRAM CLASSIFICATION
# ══════════════════════════════════════════════

def _classify_ngrams(
    ngrams_2: list,
    ngrams_3: list,
) -> Dict[str, List[str]]:
    """
    Phân loại N-grams thành entity (danh từ) và action (hành động).

    Lọc bỏ stopwords và fragments vô nghĩa.

    Returns:
        {"entity": [...], "action": [...], "all_clean": [...]}
    """
    # Danh sách action keywords (động từ, hành động)
    action_verbs = {
        "bổ sung", "chế biến", "nấu", "sử dụng", "lựa chọn",
        "kết hợp", "giảm", "tăng", "cải thiện", "phòng ngừa",
        "điều trị", "bảo quản", "chọn mua", "so sánh", "đánh giá",
        "hướng dẫn", "cách", "làm", "tạo", "xây dựng",
    }

    entity_ngrams = []
    action_ngrams = []
    all_clean = []

    import re
    # Pattern để bắt các cụm rác:
    # 1. Quá nhiều số đo/đơn vị lặp lại (mm mm mm)
    # 2. Bắt đầu/kết thúc bằng từ nối vô nghĩa
    # 3. Ký tự đặc biệt hoặc số đứng một mình
    garbage_pattern = re.compile(r'(\b(mm|cm|m|kg|g)\b\s*){3,}')

    # ── V4: extended_stopwords ĐÃ BỊ XÓA ──
    # Việc lọc ngữ nghĩa bây giờ do Agent 3c (review_ngram_quality) đảm nhiệm.

    for ngram_list in [ngrams_2 or [], ngrams_3 or []]:
        for ng, count in ngram_list:
            ng_clean = ng.strip().lower()

            # Lọc bỏ stopwords và fragments cơ bản
            if ng_clean in NGRAM_STOPWORDS:
                continue
            if len(ng_clean) < 4:
                continue

            # Lọc rác Regex
            if garbage_pattern.search(ng_clean):
                continue

            # Lọc fragments bị cắt dở (ví dụ "chất chống oxy" thay vì "chất chống oxy hóa")
            if ng_clean.endswith(" oxy") or ng_clean.endswith(" có") or ng_clean.endswith(" và") or ng_clean.endswith(" là") or ng_clean.startswith("và ") or ng_clean.startswith("là "):
                continue

            # Lọc ký tự trắng thừa
            ng_clean = re.sub(r'\s+', ' ', ng_clean).strip()

            all_clean.append(ng_clean)

            # Phân loại
            is_action = any(verb in ng_clean for verb in action_verbs)
            if is_action:
                action_ngrams.append(ng_clean)
            else:
                entity_ngrams.append(ng_clean)

    return {
        "entity": entity_ngrams,
        "action": action_ngrams,
        "all_clean": all_clean,
    }


def _smart_pick_ngrams(
    classified: Dict[str, List[str]],
    section_type: str,
    count: int = 4,
) -> str:
    """
    Chọn N-grams theo ngữ cảnh section (không random bừa).

    section_type: "intro", "main", "faq", "conclusion"
    """
    if not classified.get("all_clean"):
        return ""

    pool = []
    if section_type == "intro":
        # Mở bài: entity n-grams (danh từ chính)
        pool = classified.get("entity", [])[:count]
    elif section_type == "main":
        # Main content: mix entity + action, ưu tiên entity
        entities = classified.get("entity", [])
        actions = classified.get("action", [])
        pool = entities[:3] + actions[:2]
    elif section_type == "faq":
        # FAQ: action n-grams (how-to, process)
        pool = classified.get("action", []) or classified.get("entity", [])[:count]
    elif section_type == "conclusion":
        # Kết bài: entity tổng quát
        pool = classified.get("entity", [])[-count:]

    # Fallback nếu pool trống
    if not pool:
        pool = classified["all_clean"][:count]

    # Loại bỏ trùng lặp, giới hạn count
    pool = list(dict.fromkeys(pool))[:count]

    if not pool:
        return ""

    return (
        "\n  **→ Bắt buộc sử dụng các từ khóa ngữ nghĩa sau:** "
        + ", ".join(f'"{s}"' for s in pool)
        + "."
    )


# ══════════════════════════════════════════════
#  DYNAMIC E-E-A-T (Niche-based)
# ══════════════════════════════════════════════

NICHE_EEAT = {
    "general": {
        "experience": "Bo sung trai nghiem, vi du, hoac quan sat thuc te neu chung co trong source context hoac du lieu da thu thap.",
        "expertise": "Dung fact, EAV, SERP evidence va nguon xac minh phu hop voi keyword hien tai; khong tu chen kien thuc nganh co san.",
        "authority": "Neo nhan dinh vao nguon, competitor evidence, brand source context hoac tai lieu co the kiem chung.",
        "trust": "Minh bach ve du lieu con thieu, noi can xac minh va pham vi ap dung cua thong tin.",
        "inline_per_h2": "Moi H2 phai bam vao evidence rieng cua section: SERP, PAA, competitor gap, EAV hoac source context.",
    }
}

def _normalize_intent_key(intent: Any) -> str:
    value = str(intent or "").strip().lower()
    if value in {"commercial", "commercial investigation", "comparison", "vs"}:
        return "commercial investigation"
    if value in {"transactional", "navigational", "informational"}:
        return value
    return "informational" if value else ""


def _merge_intent_decisions(
    topic_intent: Any,
    serp_decision: Optional[Dict[str, Any]],
    competitor_decision: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    serp_decision = serp_decision if isinstance(serp_decision, dict) else {}
    competitor_decision = competitor_decision if isinstance(competitor_decision, dict) else {}

    topic_selected = _normalize_intent_key(topic_intent)
    serp_selected = _normalize_intent_key(serp_decision.get("selected_intent"))
    competitor_selected = _normalize_intent_key(competitor_decision.get("selected_intent"))

    serp_conf = str(serp_decision.get("source_confidence", "") or "").strip().lower()
    competitor_conf = str(competitor_decision.get("source_confidence", "") or "").strip().lower()
    serp_mixed = bool(serp_decision.get("is_mixed", False))
    competitor_mixed = bool(competitor_decision.get("is_mixed", False))

    try:
        serp_dominance = float(serp_decision.get("dominance_share", 0.0) or 0.0)
    except Exception:
        serp_dominance = 0.0
    try:
        competitor_dominance = float(competitor_decision.get("dominance_share", 0.0) or 0.0)
    except Exception:
        competitor_dominance = 0.0

    selected = serp_selected or competitor_selected or topic_selected or "informational"
    rationale_parts = []

    if serp_selected and competitor_selected:
        if serp_selected == competitor_selected:
            selected = serp_selected
            rationale_parts.append("SERP mix and competitor full-body analysis agree")
        elif serp_conf in {"low", "none"} or serp_mixed or serp_dominance < 0.58:
            if competitor_dominance >= 0.56 and not competitor_mixed:
                selected = competitor_selected
                rationale_parts.append("Competitor full-body intent overrides mixed or low-confidence SERP signals")
            else:
                selected = serp_selected
                rationale_parts.append("SERP stays primary because competitor bodies are also mixed")
        else:
            selected = serp_selected
            rationale_parts.append("SERP stays primary because Google top-result mix is clear")
    elif competitor_selected and not serp_selected:
        selected = competitor_selected
        rationale_parts.append("Using competitor full-body intent because SERP intent is unavailable")
    elif serp_selected:
        selected = serp_selected
        rationale_parts.append("Using SERP intent as primary signal")
    elif topic_selected:
        selected = topic_selected
        rationale_parts.append("Falling back to topic intent because SERP and competitor intent are unavailable")

    return {
        "selected_intent": selected or "informational",
        "topic_intent": topic_selected or "",
        "serp_selected_intent": serp_selected or "",
        "competitor_selected_intent": competitor_selected or "",
        "source": "merged_serp_competitor",
        "source_confidence": serp_conf or competitor_conf or "medium",
        "rationale": ". ".join(rationale_parts).strip(),
    }


def build_brief(
    topic: str,
    analysis: Dict,
    serp_data: Optional[Dict] = None,
    competitor_data: Optional[Dict] = None,
    network_data: Optional[Dict] = None,
    context_data: Optional[Dict] = None,
    linking_data: Optional[Dict] = None,
    methodology_prompt: str = "",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35: Chained Context
    eav_table: str = "",     # Phase 35: Chained Context
) -> Dict:
    """
    Xây dựng Content Brief hoàn chỉnh từ kết quả phân tích.

    Phase 9: Heading Enrichment + Smart N-grams + Dynamic E-E-A-T.
    Phase 35: Chained Context Flow.
    """
    entity = analysis["central_entity"]
    topic_intent = analysis["search_intent"]

    # V17: Smart Intent Merge (4 loại chuẩn)
    # Backward compat: normalize legacy "vs" → "commercial"
    if topic_intent == "vs":
        topic_intent = "commercial"
    serp_intent_decision = serp_data.get("intent_decision", {}) if isinstance(serp_data, dict) else {}
    competitor_intent_decision = competitor_data.get("intent_decision", {}) if isinstance(competitor_data, dict) else {}
    merged_intent_decision = _merge_intent_decisions(
        topic_intent=topic_intent,
        serp_decision=serp_intent_decision,
        competitor_decision=competitor_intent_decision,
    )
    serp_selected_intent = ""
    if isinstance(serp_intent_decision, dict):
        serp_selected_intent = str(serp_intent_decision.get("selected_intent", "") or "").strip().lower()
    competitor_selected_intent = str(competitor_intent_decision.get("selected_intent", "") or "").strip().lower() if isinstance(competitor_intent_decision, dict) else ""
    merged_selected_intent = str(merged_intent_decision.get("selected_intent", "") or "").strip().lower()
    serp_intent = serp_data.get("dominant_intent", "") if serp_data else ""
    if merged_selected_intent:
        intent = merged_selected_intent
    elif serp_selected_intent:
        intent = serp_selected_intent  # Intent mix từ SERP thắng nếu có data
    elif competitor_selected_intent:
        intent = competitor_selected_intent
    elif serp_intent:
        intent = serp_intent  # Backward compat
    else:
        intent = topic_intent

    # ── Phase 9: Detect Niche (project.industry priority) ──
    proj_industry = project.industry if project else ""
    niche = detect_niche(topic, proj_industry)
    logger.info("  [NICHE] Detected: '%s' cho topic '%s' (project.industry='%s')", niche, topic, proj_industry)

    # ── Phase 38: CRITICAL — topical_map_csv BẮT BUỘC ──
    topical_csv = getattr(project, "topical_map_csv", "") or ""
    if not topical_csv:
        logger.error(
            "  [TOPICAL MAP] ❌ Project '%s' KHÔNG có topical_map_csv!\n"
            "  → Internal linking sẽ dùng keyword_clusters (chấp nhận).\n"
            "  → KHÔNG dùng global topics.csv (ngành khác — gây nhầm lẫn).\n"
            "  → HƯỚNG DẪN: Mở project → chỉnh sửa → nhập đường dẫn file CSV (VD: 'projects/my_project_topics.csv').\n"
            "    File CSV cần cột 1 = Keyword bài viết.",
            getattr(project, "name", "?"),
        )
        # Không raise — cho phép pipeline tiếp tục với keyword_clusters
        # Nhưng GHI LOG rõ ràng để user biết cần sửa
    elif not os.path.exists(topical_csv):
        logger.warning(
            "  [TOPICAL MAP] ⚠️ File '%s' không tồn tại → dùng keyword_clusters thay thế.",
            topical_csv,
        )

    # ── Phase 9: Heading Enrichment → Phase 19: Comprehensive Outline Synthesis ──
    classified_ngrams_pre = _classify_ngrams(
        competitor_data.get("ngrams_2", []) if competitor_data else [],
        competitor_data.get("ngrams_3", []) if competitor_data else [],
    )
    paa_raw_pre = serp_data.get("people_also_ask", [])[:5] if serp_data else []
    paa_refinement_pre = refine_paa_questions_for_project(
        topic=topic,
        entity=entity,
        project=project,
        raw_questions=paa_raw_pre,
        intent=intent,
        competitor_data=competitor_data,
    )
    paa_questions_pre = paa_refinement_pre.get("faq_questions", []) or _fallback_project_faq_questions(topic, entity, project, paa_raw_pre)
    gaps_pre = []
    if competitor_data:
        info_gain_pre = competitor_data.get("information_gain", {})
        gaps_pre = info_gain_pre.get("rare_headings", [])[:7]
        gaps_pre = _filter_project_contamination_terms(
            [str(g.get("heading", g) if isinstance(g, dict) else g) for g in gaps_pre],
            project=project,
            topic=topic,
        )
    outline_signals_pre = _derive_outline_consensus_signals(competitor_data, project=project, topic=topic)
    semantic_reasoning_pre = _build_semantic_reasoning(
        topic=topic,
        intent=intent,
        serp_data=serp_data,
        project=project,
        paa_questions=paa_questions_pre,
        competitor_data=competitor_data,
        content_gaps=gaps_pre,
        classified_ngrams=classified_ngrams_pre,
        eav_table=eav_table,
        entity_attributes=analysis.get("entity_attributes", {}),
        outline_signals=outline_signals_pre,
    )
    eav_table = render_eav_markdown(
        semantic_reasoning_pre.get("verified_eav_rows", []) or semantic_reasoning_pre.get("enriched_candidate_rows", []),
        fallback_table=eav_table,
        limit=12,
    )

    raw_headings = analysis["heading_structure"]
    enriched_headings = rewrite_headings_semantic(
        raw_headings, topic, niche, intent,
        topic=topic,
        entity=entity,
        serp_data=serp_data,
        competitor_data=competitor_data,
        methodology_prompt=methodology_prompt,
        project=project,  # Phase 33
        macro_context=macro_context, # Phase 35
        eav_table=eav_table, # Phase 35
        network_data=network_data, # Phase 35
        context_data=context_data, # Phase 35
        semantic_reasoning=semantic_reasoning_pre,
    )

    # ── Phase 9: Smart N-gram Classification ──
    classified_ngrams = _classify_ngrams(
        competitor_data.get("ngrams_2", []) if competitor_data else [],
        competitor_data.get("ngrams_3", []) if competitor_data else [],
    )

    # ── Phase 8 Pass 3c: Semantic Quality Gate ──
    # Lọc N-gram rác bằng LLM suy luận thay vì regex/stopwords cố định
    try:
        from modules.agent_reviewer import review_ngram_quality
        if classified_ngrams.get("all_clean"):
            clean_ngrams = review_ngram_quality(
                classified_ngrams["all_clean"],
                entity=topic,
                intent=intent,
            )
            # Cập nhật lại classified_ngrams với danh sách đã lọc
            classified_ngrams["all_clean"] = clean_ngrams
            # Lọc entity/action tương ứng
            clean_set = set(clean_ngrams)
            classified_ngrams["entity"] = [ng for ng in classified_ngrams.get("entity", []) if ng in clean_set]
            classified_ngrams["action"] = [ng for ng in classified_ngrams.get("action", []) if ng in clean_set]
            logger.info("  [PHASE 8] Agent 3c completed: %d clean N-grams.", len(clean_ngrams))
    except ImportError:
        logger.info("  [PHASE 8] agent_reviewer not available for Pass 3c → using rule-based N-grams.")

    # Lấy thêm dữ liệu PAA và Gaps để nạp cho Micro-Briefing
    paa_raw = serp_data.get("people_also_ask", [])[:5] if serp_data else []
    paa_refinement = refine_paa_questions_for_project(
        topic=topic,
        entity=entity,
        project=project,
        raw_questions=paa_raw,
        intent=intent,
        competitor_data=competitor_data,
    )
    paa_questions = paa_refinement.get("faq_questions", []) or _fallback_project_faq_questions(topic, entity, project, paa_raw)
    supp_questions = paa_refinement.get("supp_questions", [])
    gaps = []
    if competitor_data:
        info_gain = competitor_data.get("information_gain", {})
        gaps = info_gain.get("rare_headings", [])[:7]
        gaps = _filter_project_contamination_terms(
            [str(g.get("heading", g) if isinstance(g, dict) else g) for g in gaps],
            project=project,
            topic=topic,
        )

    outline_signals = _derive_outline_consensus_signals(competitor_data, project=project, topic=topic)
    semantic_reasoning = _build_semantic_reasoning(
        topic=topic,
        intent=intent,
        serp_data=serp_data,
        project=project,
        paa_questions=paa_questions,
        competitor_data=competitor_data,
        content_gaps=gaps,
        classified_ngrams=classified_ngrams,
        eav_table=eav_table,
        entity_attributes=analysis.get("entity_attributes", {}),
        outline_signals=outline_signals,
        headings=enriched_headings,
    )
    final_h3_sources = []
    final_h3_sources.extend([str(q) for q in (paa_questions or [])])
    final_h3_sources.extend([str(g) for g in (outline_signals.get("gap_h3_candidates", []) or [])])
    final_h3_sources.extend([str(g) for g in (outline_signals.get("gap_h2_candidates", []) or [])])
    final_h3_sources.extend([str(c) for c in (outline_signals.get("consensus_points", []) or [])])
    enriched_headings = _apply_semantic_outline_gate(enriched_headings, topic, semantic_reasoning)
    enriched_headings = _enforce_h3_ratio(enriched_headings, topic, final_h3_sources)
    enriched_headings = _clean_slot_filled_outline(enriched_headings, topic=topic)

    # Build micro_briefing FIRST so guidelines can use its analysis
    micro_briefing_data = _agent_micro_briefing_writer(
        topic, entity, intent, niche, methodology_prompt, enriched_headings,
        paa_questions=paa_questions, content_gaps=gaps, classified_ngrams=classified_ngrams,
        entity_attributes=analysis.get("entity_attributes", {}),
        serp_data=serp_data,
        outline_signals=outline_signals,
        semantic_reasoning=semantic_reasoning,
        project=project,  # Phase 33
    )

    # Audit Fix: validate + truncate FS snippets (<=40 words) va SAPO (<=120 words)
    try:
        from modules.koray_analyzer import _validate_fs_snippets
        _tmp = {"topic": topic, "micro_briefing": micro_briefing_data}
        _tmp = _validate_fs_snippets(_tmp, max_words=40, sapo_max=120)
        micro_briefing_data = _tmp["micro_briefing"]
    except Exception:
        pass  # non-fatal

    # Keyword clusters from competitor data to pass into internal linking (V5.3)
    # FIX: n-grams are tuples (str, int) — extract just the string portion
    keyword_clusters_raw = []
    if competitor_data:
        for ng in (competitor_data.get("ngrams_2", []) + competitor_data.get("ngrams_3", [])):
            if isinstance(ng, tuple) and len(ng) >= 1:
                keyword_clusters_raw.append(str(ng[0]))
            elif isinstance(ng, str):
                keyword_clusters_raw.append(ng)
    # Also include clusters from network_data if available
    # Defensive: normalize clusters về list[dict] (same logic as line 672-697)
    if network_data and network_data.get("clusters"):
        nc = network_data.get("clusters", [])
        if isinstance(nc, dict):
            if "clusters" in nc:
                nc = nc["clusters"]
            else:
                nc = list(nc.values()) if nc else []
        if isinstance(nc, list):
            for c in nc:
                if isinstance(c, dict):
                    for kw in c.get("keywords", [])[:3]:
                        if isinstance(kw, str) and kw not in keyword_clusters_raw:
                            keyword_clusters_raw.append(kw)
                elif isinstance(c, str) and c not in keyword_clusters_raw:
                    keyword_clusters_raw.append(c)

    brief = {
        "topic": topic,
        "niche": niche,
        "title_tag": _generate_title_tag(topic, entity),
        "meta_description": _generate_meta_description(topic, entity, intent),
        "search_intent": _format_intent(intent),
        "central_entity": entity,
        "entity_attributes": analysis["entity_attributes"],
        "eav_table": eav_table,
        "eav_table_rows": semantic_reasoning.get("verified_eav_rows", []),
        "eav_quality": semantic_reasoning.get("eav_quality", {}),
        "heading_structure": enriched_headings,
        "content_guidelines": _generate_content_guidelines(
            topic, entity, intent, niche, classified_ngrams,
            headings=enriched_headings,
            methodology_prompt=methodology_prompt,
            micro_briefing=micro_briefing_data,
        ),
        "micro_briefing": micro_briefing_data,
        "suggested_questions": paa_questions or analysis["suggested_questions"],
        "faq_questions": paa_questions,
        "supp_questions": supp_questions,
        "paa_refinement": paa_refinement,
        "content_gaps": gaps,
        "internal_linking": _generate_linking_suggestions(
            analysis["related_topics"],
            keyword_clusters=keyword_clusters_raw,
            current_topic=topic,
            enriched_headings=enriched_headings,
            topical_map_csv=getattr(project, "topical_map_csv", "") or "",
            niche=niche,  # Phase 38: dùng niche đã detect (từ project.industry) để filter links
        ),
        "eeat_checklist": _generate_eeat_checklist(entity, niche),
        "methodology_prompt": methodology_prompt,
        "outline_signals": outline_signals,
        "semantic_reasoning": semantic_reasoning,
    }

    # ── Thêm SERP data nếu có ──
    if serp_data:
        brief["serp_analysis"] = {
            "organic_results": serp_data.get("organic_results", []),
            "top_urls_display": serp_data.get("top_urls", []),
            "people_also_ask": serp_data.get("people_also_ask", []),
            "people_also_ask_rewritten": paa_questions,
            "things_to_know": serp_data.get("things_to_know", []),
            "related_searches": serp_data.get("related_searches", []),
            "serp_entities": serp_data.get("serp_entities", {}),
            "serp_attributes": serp_data.get("serp_attributes", []),
            "topic_clusters": serp_data.get("topic_clusters", []),
            "dominant_intent": serp_data.get("dominant_intent", ""),
            "intent_distribution": serp_data.get("intent_distribution", {}),
            "intent_decision": serp_intent_decision if isinstance(serp_intent_decision, dict) else {},
            "competitor_body_intent_distribution": competitor_data.get("intent_distribution", {}) if isinstance(competitor_data, dict) else {},
            "competitor_body_intent_decision": competitor_intent_decision if isinstance(competitor_intent_decision, dict) else {},
            "final_intent_decision": merged_intent_decision,
            "result_intents": serp_data.get("result_intents", []),
            "serp_source": serp_data.get("serp_source", ""),
            "featured_snippet": serp_data.get("featured_snippet", {}),
            "knowledge_panel": serp_data.get("knowledge_panel", {}),
            "serp_features": serp_data.get("serp_features", []),
            "result_format_counts": serp_data.get("result_format_counts", {}),
            "dominant_format": serp_data.get("dominant_format", ""),
        }
        # Merge PAA questions vào suggested_questions
        paa = paa_questions
        if paa:
            existing = set(brief["suggested_questions"])
            for q in paa:
                if q not in existing:
                    brief["suggested_questions"].append(q)

    # ── Thêm Competitor data nếu có ──
    if competitor_data:
        rare_headings = competitor_data.get("information_gain", {}).get("rare_headings", [])
        rare_headings = _filter_project_contamination_terms(
            [str(g.get("heading", g) if isinstance(g, dict) else g) for g in rare_headings],
            project=project,
            topic=topic,
        )
        brief["competitor_analysis"] = {
            "common_headings": competitor_data.get("common_headings", []),
            "ngrams_2": competitor_data.get("ngrams_2", []),
            "ngrams_3": competitor_data.get("ngrams_3", []),
            "heading_frequency_matrix": competitor_data.get("heading_frequency_matrix", {}),
            "intent_distribution": competitor_data.get("intent_distribution", {}),
            "intent_decision": competitor_intent_decision if isinstance(competitor_intent_decision, dict) else {},
            "content_intents": competitor_data.get("content_intents", []),
            "content_archetypes": competitor_data.get("content_archetypes", []),
            "archetype_summary": competitor_data.get("archetype_summary", {}),
            "information_gain": {
                **competitor_data.get("information_gain", {}),
                "rare_headings": rare_headings,
            },
            "competitor_count": len(competitor_data.get("competitors", [])),
            "competitors_detail": [
                {
                    "url": c.get("url", ""),
                    "headings": c.get("headings", []),
                    "word_count": c.get("word_count", 0),
                }
                for c in competitor_data.get("competitors", [])
            ],
            "competitors_summary": [
                {
                    "url": c.get("url", ""),
                    "heading_count": len(c.get("headings", [])),
                    "word_count": c.get("word_count", 0),
                }
                for c in competitor_data.get("competitors", [])
            ],
        }
        if "serp_analysis" not in brief:
            brief["serp_analysis"] = {}
        if isinstance(brief["serp_analysis"], dict):
            brief["serp_analysis"]["information_gain"] = brief["competitor_analysis"]["information_gain"]
            brief["serp_analysis"]["competitor_body_intent_distribution"] = competitor_data.get("intent_distribution", {})
            brief["serp_analysis"]["competitor_body_intent_decision"] = competitor_intent_decision if isinstance(competitor_intent_decision, dict) else {}
            brief["serp_analysis"]["final_intent_decision"] = merged_intent_decision

    # ── Thêm Query Network data nếu có ──
    if network_data:
        brief["query_network"] = network_data

    # ── Thêm Context Builder data nếu có ──
    if context_data:
        brief["context_builder"] = context_data

    # ── Override linking tĩnh bằng linking động từ Topical Map (nếu có) ──
    if linking_data:
        brief["internal_linking"] = linking_data

    # ═══════════════════════════════════════════════════════════
    #  SPEC V4.3: AGENT 3d — ANCHOR TEXT REVIEWER
    # ═══════════════════════════════════════════════════════════
    try:
        from modules.agent_reviewer import review_anchor_quality
        link_data = brief.get("internal_linking", {})
        outbound = link_data.get("outbound_nodes", [])
        if outbound:
            reviewed_anchors = review_anchor_quality(
                outbound, central_entity=entity, intent=intent,
            )
            link_data["outbound_nodes"] = reviewed_anchors
            brief["internal_linking"] = link_data
            logger.info("  [SPEC V4] Agent 3d: Anchor review completed.")
    except ImportError:
        logger.info("  [SPEC V4] agent_reviewer not available for Anchor review.")

    # ═══════════════════════════════════════════════════════════
    #  SPEC V4.4: AGENT 4 — PER-H2 CONTEXTUAL STRUCTURE
    # ═══════════════════════════════════════════════════════════
    per_h2 = None
    try:
        from modules.agent_reviewer import generate_per_h2_instructions
        per_h2 = generate_per_h2_instructions(
            outline=enriched_headings,
            main_keyword=topic,
            intent=intent,
            classified_ngrams=classified_ngrams,
            eav_table=eav_table,
        )
        if per_h2:
            brief["contextual_structure_v4"] = per_h2
            logger.info("  [SPEC V4] Agent 4: Per-H2 instructions generated.")
    except ImportError:
        logger.info("  [SPEC V4] agent_reviewer not available for Per-H2 instructions.")

    # Phase 42: Inject word_count_target from per_h2 (Agent 4) into micro_briefing items
    # Fixes Koray Score 0/10 for criterion 11 (Per-H2 Guidance)
    # MUST come AFTER per_h2 is defined (line ~1907) — was previously placed BEFORE, causing UnboundLocalError
    if per_h2 and isinstance(per_h2, dict) and micro_briefing_data:
        per_h2_map = per_h2.get("per_h2", {})
        for mb in micro_briefing_data:
            if not isinstance(mb, dict):
                continue
            h2_text = mb.get("h2", "")
            if h2_text in per_h2_map:
                h2_inst = per_h2_map[h2_text]
                wc_target = h2_inst.get("word_count_target", "")
                content_fmt = h2_inst.get("content_format", "")
                first_sent = h2_inst.get("first_sentence", "")
                if wc_target:
                    mb["word_count_target"] = wc_target
                existing_guidance = mb.get("guidance", "")
                injected = f"[{content_fmt}] {wc_target} | First: {first_sent}"
                mb["guidance"] = (existing_guidance + " | " + injected).strip(" |")

    try:
        normalized = _normalize_micro_briefing_data(brief, project=project, per_h2=per_h2)
        if normalized:
            micro_briefing_data = brief.get("micro_briefing", micro_briefing_data)
            brief["content_guidelines"] = _generate_content_guidelines(
                topic, entity, intent, niche, classified_ngrams,
                headings=enriched_headings,
                methodology_prompt=methodology_prompt,
                micro_briefing=micro_briefing_data,
            )
            logger.info("  [POST-PROCESS] Micro-briefing normalized for Koray specificity.")
    except Exception as normalize_err:
        logger.warning("  [POST-PROCESS] Micro-briefing normalization failed: %s", normalize_err)

    try:
        if _apply_koray_micro_postprocess(brief, project):
            micro_briefing_data = brief.get("micro_briefing", micro_briefing_data)
            brief["content_guidelines"] = _generate_content_guidelines(
                topic, entity, intent, niche, classified_ngrams,
                headings=enriched_headings,
                methodology_prompt=methodology_prompt,
                micro_briefing=micro_briefing_data,
            )
            logger.info("  [POST-PROCESS] SAPO / SUPP bridge rebuilt outside Koray block.")
    except Exception as post_err:
        logger.warning("  [POST-PROCESS] SAPO / SUPP rebuild failed: %s", post_err)

    try:
        outline_framework = build_outline_content_framework(brief, project=project)
        if outline_framework:
            brief["outline_content_framework"] = outline_framework
    except Exception as framework_err:
        logger.warning("  [OUTLINE-FRAMEWORK] Build failed: %s", framework_err)

    logger.info("Đã xây dựng Content Brief cho: '%s' (niche=%s)%s%s%s%s", topic,
                niche,
                " (+ SERP)" if serp_data else "",
                " (+ Network)" if network_data else "",
                " (+ Context)" if context_data else "",
                " (+ Linking)" if linking_data else "")
    return brief


# ──────────────────────────────────────────────
#  PRIVATE HELPERS
# ──────────────────────────────────────────────

def _generate_title_tag(topic: str, entity: str) -> str:
    """Tạo gợi ý Title Tag tối ưu SEO (50-60 ký tự)."""
    topic_title = topic.strip().title()
    title = f"{topic_title} | Hướng Dẫn Chi Tiết [{_current_year()}]"
    if len(title) > 60:
        title = f"{topic_title} [{_current_year()}]"
    if len(title) > 60:
        title = topic_title[:57] + "..."
    return title


def _generate_meta_description(topic: str, entity: str, intent: str) -> str:
    """Tạo gợi ý Meta Description (150-160 ký tự)."""
    templates = {
        "informational": (
            f"Tìm hiểu {topic.lower()} chi tiết: đặc điểm, phân loại, "
            f"ứng dụng và lưu ý quan trọng. Cập nhật {_current_year()}."
        ),
        "commercial": (
            f"So sánh và đánh giá {entity.lower()} chi tiết. "
            f"Hướng dẫn lựa chọn {entity.lower()} phù hợp nhất."
        ),
        "commercial investigation": (
            f"So sánh và đánh giá {entity.lower()} chi tiết. "
            f"Hướng dẫn lựa chọn {entity.lower()} phù hợp nhất."
        ),
        "transactional": (
            f"Tim hieu {entity.lower()} theo dung nhu cau va boi canh tim kiem. "
            f"Cap nhat thong tin dua tren du lieu da thu thap."
        ),
        "navigational": (
            f"Thông tin chính thức về {entity.lower()}. "
            f"Liên hệ tư vấn và báo giá nhanh chóng."
        ),
    }
    desc = templates.get(intent, templates["informational"])
    if len(desc) > 160:
        desc = desc[:157] + "..."
    return desc


def _format_intent(intent: str) -> Dict:
    """Format thông tin Search Intent cho Content Brief."""
    intent_descriptions = {
        "informational": {
            "type": "Informational",
            "description": "Người dùng muốn TÌM HIỂU thông tin, kiến thức.",
            "content_focus": "Giải thích, hướng dẫn, cung cấp kiến thức chuyên sâu.",
        },
        "vs": {
            "type": "Comparison (VS)",
            "description": "Người dùng muốn SO SÁNH 2 hoặc nhiều đối tượng.",
            "content_focus": "Bảng so sánh chi tiết, tiêu chí kỹ thuật, ưu/nhược điểm, khi nào chọn A vs B.",
        },
        "commercial": {
            "type": "Commercial Investigation",
            "description": "Người dùng đang SO SÁNH, ĐÁNH GIÁ trước khi mua.",
            "content_focus": "So sánh, review, bảng đánh giá, tiêu chí lựa chọn.",
        },
        "commercial investigation": {
            "type": "Commercial Investigation",
            "description": "Người dùng đang SO SÁNH, ĐÁNH GIÁ trước khi mua.",
            "content_focus": "So sánh, review, bảng đánh giá, tiêu chí lựa chọn.",
        },
        "transactional": {
            "type": "Transactional",
            "description": "Người dùng muốn MUA HÀNG hoặc thực hiện giao dịch.",
            "content_focus": "Thông tin sản phẩm, giá cả, CTA rõ ràng.",
        },
        "navigational": {
            "type": "Navigational",
            "description": "Người dùng muốn TÌM ĐẾN một trang/thương hiệu cụ thể.",
            "content_focus": "Thông tin chính thức, liên hệ, thương hiệu.",
        },
    }
    return intent_descriptions.get(intent, intent_descriptions["informational"])


def _fallback_micro_briefing_data(
    topic: str,
    entity: str,
    intent: str,
    niche: str,
    methodology_prompt: str,
    headings: List[Dict],
    paa_questions: List[str] = None,
    content_gaps: List[str] = None,
    classified_ngrams: Dict = None,
    entity_attributes: Dict = None,
    project=None,
) -> List[Dict]:
    """Rule-based micro briefing when LLM is unavailable."""
    paa_questions = _normalize_question_list(paa_questions or [])
    content_gaps = content_gaps or []
    classified_ngrams = classified_ngrams or {}
    entity_attributes = entity_attributes or {}

    h2_items = [h for h in headings if isinstance(h, dict) and h.get("level") == "H2"]
    h3_children: Dict[str, List[str]] = {}
    current_h2 = ""
    for h in headings:
        if not isinstance(h, dict):
            continue
        level = h.get("level", "")
        text = str(h.get("text", "")).strip()
        if level == "H2":
            current_h2 = text
            h3_children.setdefault(current_h2, [])
        elif level == "H3" and current_h2:
            h3_children.setdefault(current_h2, []).append(text)

    def _content_format_for_heading(text: str) -> str:
        lower = _remove_diacritics((text or "").lower())
        if any(sig in lower for sig in ["so sanh", "khac nhau", "vs"]):
            return "Bảng so sánh 3 cột"
        if any(sig in lower for sig in ["quy trinh", "cach", "huong dan", "lam sao"]):
            return "Danh sách 3-5 bước"
        if any(sig in lower for sig in ["faq", "cau hoi"]):
            return "FAQ ngắn"
        if any(sig in lower for sig in ["rui ro", "luu y", "can than"]):
            return "Paragraph + bullet list"
        return "Paragraph"

    def _heading_terms(text: str, limit: int = 5) -> List[str]:
        raw_terms = []
        for token in re.split(r"[^0-9A-Za-zÀ-ỹ]+", text or ""):
            token = token.strip()
            if len(token) >= 4:
                raw_terms.append(token)
        seen = set()
        terms = []
        for term in raw_terms:
            norm = _remove_diacritics(term).lower().strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            terms.append(term)
        return terms[:limit]

    def _short_answer(seed: str, question: str, heading: str = "") -> str:
        q = _remove_diacritics((question or "").lower())
        heading_norm = _remove_diacritics((heading or "").lower())
        topic_text = (seed or entity or topic or "chủ đề này").strip()
        if any(sig in q for sig in ["la gi", "dinh nghia", "khai niem"]):
            return (
                f"{topic_text} là khái niệm được hiểu qua phạm vi áp dụng, thành phần cốt lõi và ranh giới với các khái niệm gần nghĩa trong {heading or topic_text}."
            )
        if any(sig in q for sig in ["cach", "quy trinh", "huong dan", "lam sao"]):
            return (
                f"{topic_text} hoạt động theo từng bước, từ điều kiện đầu vào, cách triển khai đến kết quả đầu ra, nên phần này cần có quy trình hoặc ví dụ thực tế để đối chiếu."
            )
        if any(sig in q for sig in ["rui ro", "luu y", "can than"]):
            return (
                f"{topic_text} đi kèm các rủi ro, giới hạn và điều kiện cần kiểm tra trước khi áp dụng vào thực tế."
            )
        if any(sig in heading_norm for sig in ["so sanh", "khac nhau", "vs"]):
            return (
                f"{topic_text} nên được so sánh theo phạm vi, cấu phần và điều kiện áp dụng giữa các phương án thay vì chỉ liệt kê tên lựa chọn."
            )
        return (
            f"{topic_text} cần được diễn giải ngắn gọn nhưng vẫn đủ ngữ cảnh, tập trung vào nghĩa lõi, thuộc tính quan trọng và điểm cần kiểm chứng trước khi áp dụng."
        )

    def _entity_terms(limit: int = 4) -> str:
        terms = []
        for key in list(entity_attributes.keys())[:limit]:
            key_text = str(key).strip()
            if key_text:
                terms.append(key_text)
        if not terms and classified_ngrams.get("entity"):
            terms = [str(x).strip() for x in classified_ngrams.get("entity", [])[:limit] if str(x).strip()]
        return ", ".join(terms[:limit]) if terms else (entity or topic or "")

    items: List[Dict] = []

    sapo_questions = paa_questions[:3] if paa_questions else []
    sapo_seed = _short_answer(topic or entity or "chủ đề này", sapo_questions[0] if sapo_questions else topic, topic or entity)
    sapo_parts = [sapo_seed]
    if entity or topic:
        sapo_parts.append(
            f"Trục nội dung đi từ phạm vi áp dụng và cấu phần chính của {entity or topic}, rồi mở sang cách đánh giá, điều kiện thực tế và các lưu ý ra quyết định."
        )
    if entity_attributes:
        first_attr = next(iter(entity_attributes.items()))
        sapo_parts.append(f"Thuộc tính nổi bật được ưu tiên là {first_attr[0]}: {str(first_attr[1]).strip()}.")
    if content_gaps:
        sapo_parts.append(f"Các phần tiếp theo sẽ bù những khoảng trống như {', '.join(content_gaps[:2])}.")
    sapo_parts.append("Phần mở đầu cần giúp người đọc chốt nghĩa lõi trước, sau đó mới đi sang cách áp dụng, so sánh và các tình huống thực tế.")
    sapo_text = " ".join(sapo_parts).strip()
    items.append(
        {
            "h2": "SAPO (Doan mo dau)",
            "intent": "Gioi thieu tong quan",
            "snippet": sapo_text,
            "analysis": f"Mở đầu trực tiếp cho {topic} bằng câu trả lời rõ nghĩa, sau đó mở rộng sang phạm vi áp dụng, cấu phần chính và giá trị thực tế.",
            "entities": _entity_terms(4),
            "info_gain": "Cac y chinh trong phan nay bao gom dinh nghia, pham vi, cac thuoc tinh can xac minh va loi ich doc gia nhan duoc sau khi doc bai.",
            "bridge": "Mở sang các H2 tiếp theo bằng cách đi từ định nghĩa sang thuộc tính, so sánh và cách áp dụng.",
            "transition": "Tiep theo la phan lam ro dinh nghia va phan loai.",
            "content_format": "Paragraph",
            "first_sentence": f"{topic or entity} là chủ đề cần hiểu đúng ngay từ đầu.",
            "micro_terms": _heading_terms(topic or entity or "chu de nay", limit=4),
            "word_count_target": "80-120 tu",
        }
    )

    for idx, h2 in enumerate(h2_items[:8]):
        raw_title = str(h2.get("text", "")).strip()
        clean_title = raw_title.replace("[MAIN] ", "").replace("[SUPP] ", "").strip()
        is_supp = "[SUPP]" in raw_title or idx >= 4
        h3s = h3_children.get(raw_title, [])
        question_seed = paa_questions[idx % len(paa_questions)] if paa_questions else clean_title
        snippet = _short_answer(clean_title, question_seed, clean_title)
        analysis = (
            f"Section này phân tích {clean_title.lower()} theo semantic SEO, đồng thời bám topical border và "
            f"ưu tiên các điểm mà content gaps đang thiếu."
        )
        content_format = _content_format_for_heading(clean_title)
        micro_terms = _heading_terms(clean_title, limit=5)
        if entity_attributes:
            for attr_key in list(entity_attributes.keys())[:2]:
                if attr_key and attr_key not in micro_terms:
                    micro_terms.append(str(attr_key))
        if h3s:
            info_gain = "Cac H3 trong phan nay bao gom: " + ", ".join(h3s[:3]) + "."
        else:
            if content_gaps:
                info_gain = f"Phần này ưu tiên lấp khoảng trống: {', '.join(content_gaps[:3])}."
            else:
                info_gain = "Phần này mở rộng ngữ cảnh, điều kiện áp dụng và các lưu ý thực tế."
        bridge = "Kết nối sang section tiếp theo bằng một thuộc tính rõ ràng hoặc một câu hỏi phát sinh."
        if is_supp and project:
            brand = getattr(project, "brand_name", "") or ""
            hotline = getattr(project, "hotline", "") or ""
            geo = getattr(project, "geo_keywords", "") or ""
            bridge_parts = []
            if brand:
                bridge_parts.append(f"Lien he {brand}")
            if hotline:
                bridge_parts.append(f"Hotline/Zalo: {hotline}")
            if geo:
                bridge_parts.append(f"Khu vuc: {geo.split(',')[0].strip()}")
            if bridge_parts:
                bridge = " ".join(bridge_parts) + "."
        items.append(
            {
                "h2": raw_title,
                "intent": "Definitional" if "la gi" in _remove_diacritics(clean_title.lower()) else "Informational",
                "snippet": snippet,
                "analysis": analysis,
                "entities": _entity_terms(5),
                "info_gain": info_gain,
                "bridge": bridge,
                "transition": f"Chuyen sang {h3s[0]}." if h3s else "Chuyen sang section tiep theo.",
                "content_format": content_format,
                "first_sentence": _short_answer(clean_title, question_seed, clean_title),
                "micro_terms": micro_terms,
                "guidance": f"[{content_format}] Trả lời trực tiếp '{question_seed}'. Ưu tiên các terms: {', '.join(micro_terms[:5])}.",
                "word_count_target": "80-150 tu" if not is_supp else "60-100 tu",
            }
        )

    return items


MICRO_PLACEHOLDER_MARKERS = (
    "section nay",
    "theo semantic seo",
    "topical border",
    "content gaps",
    "phan nay se",
    "bai viet se",
    "phan nay phan tich",
    "uu tien cac diem ma",
    "can neu ro",
    "can duoc trinh bay",
    "can xac minh",
)


def _normalize_heading_key(text: Any) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw)
    return _remove_diacritics(raw.lower()).strip()


def _clean_heading_label(text: Any) -> str:
    raw = str(text or "").strip()
    raw = re.sub(r"^\[(MAIN|SUPP)\]\s*", "", raw, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", raw).strip()


def _contains_micro_placeholder(text: Any) -> bool:
    norm = _normalize_heading_key(text)
    if not norm:
        return True
    return any(marker in norm for marker in MICRO_PLACEHOLDER_MARKERS)


def _trim_words(text: Any, max_words: int) -> str:
    words = [word for word in str(text or "").split() if word.strip()]
    if len(words) <= max_words:
        return " ".join(words).strip()
    return " ".join(words[:max_words]).strip()


def _match_per_h2_instruction(per_h2_map: Dict[str, Any], heading_text: str) -> Dict[str, Any]:
    if not isinstance(per_h2_map, dict) or not heading_text:
        return {}
    if heading_text in per_h2_map and isinstance(per_h2_map[heading_text], dict):
        return per_h2_map[heading_text]
    target_norm = _normalize_heading_key(heading_text)
    for key, value in per_h2_map.items():
        if isinstance(value, dict) and _normalize_heading_key(key) == target_norm:
            return value
    return {}


def _heading_kind_for_micro(heading_text: str, is_supp: bool = False) -> str:
    lower = _normalize_heading_key(heading_text)
    if is_supp or "faq" in lower or "cau hoi" in lower:
        return "faq"
    if any(token in lower for token in ["so sanh", "khac nhau", "vs"]):
        return "comparison"
    if any(token in lower for token in ["rui ro", "luu y", "sai lam", "canh bao"]):
        return "risk"
    if any(token in lower for token in ["quy trinh", "cach", "lam sao", "co che", "hoat dong"]):
        return "method"
    if any(token in lower for token in ["la gi", "dinh nghia", "khai niem"]) or not lower:
        return "definition"
    return "general"


def _deterministic_micro_snippet(
    clean_title: str,
    section_kind: str,
    current_snippet: str,
    instruction: Dict[str, Any],
) -> str:
    snippet = str(current_snippet or "").strip()
    if snippet and not _contains_micro_placeholder(snippet) and len(snippet.split()) <= 40:
        return snippet

    first_sentence = str(instruction.get("first_sentence", "")).strip()
    if first_sentence and not _contains_micro_placeholder(first_sentence):
        return _trim_words(first_sentence, 40)

    label = clean_title.lower()
    templates = {
        "definition": f"{clean_title} cần được chốt bằng nghĩa lõi, phạm vi áp dụng và dấu hiệu nhận biết trước khi mở sang các lớp hỗ trợ.",
        "attribute": f"{clean_title} cần được tách theo từng thuộc tính cụ thể để người đọc đối chiếu và ra quyết định nhanh hơn.",
        "method": f"{clean_title} phải được giải thích theo cơ chế, bước triển khai và điều kiện áp dụng thực tế.",
        "comparison": f"So sánh {label} phải đặt lên cùng một bộ tiêu chí cố định để chốt điểm khác biệt thật sự.",
        "risk": f"{clean_title} cần làm rõ điều kiện ẩn, hiểu nhầm thường gặp và hậu quả nếu áp dụng sai.",
        "faq": f"{clean_title} cần được trả lời ngắn, trực diện và bám đúng điều kiện áp dụng thực tế.",
        "general": f"{clean_title} cần được trả lời bằng một ý chính rõ ràng, rồi mới mở sang bằng chứng hỗ trợ phù hợp.",
    }
    return _trim_words(templates.get(section_kind, templates["general"]), 40)


def _deterministic_micro_analysis(
    clean_title: str,
    section_kind: str,
    instruction: Dict[str, Any],
    h3_children: List[str],
    next_heading: str,
) -> str:
    content_format = str(instruction.get("content_format", "")).strip()
    sentence_before = str(instruction.get("sentence_before", "")).strip()
    preceding_question = str(instruction.get("preceding_question", "")).strip()
    contextual_bridge = str(instruction.get("contextual_bridge", "")).strip()
    micro_terms = [str(term).strip() for term in instruction.get("micro_terms", []) if str(term).strip()]

    openers = {
        "definition": f"Làm rõ {clean_title.lower()} bằng nghĩa lõi, phạm vi áp dụng và ranh giới với các khái niệm dễ bị nhầm.",
        "attribute": f"Tách {clean_title.lower()} thành từng thuộc tính hoặc nhóm tiêu chí rõ ràng để writer không dừng ở mô tả chung.",
        "method": f"Triển khai {clean_title.lower()} theo đúng cơ chế, điều kiện đầu vào và các bước khiến người đọc hiểu được cách vận hành thực tế.",
        "comparison": f"Đặt {clean_title.lower()} lên cùng một bộ tiêu chí so sánh cố định, rồi giải thích vì sao từng tiêu chí làm thay đổi quyết định.",
        "risk": f"Bóc tách {clean_title.lower()} theo điều kiện ẩn, sai lầm thường gặp và hậu quả thực tế thay vì chỉ liệt kê cảnh báo bề mặt.",
        "faq": f"Khóa phần bổ trợ này bằng câu trả lời ngắn, trực diện và bám đúng điều kiện áp dụng của {clean_title.lower()}.",
        "general": f"Triển khai {clean_title.lower()} theo đúng user need của heading này, không lặp lại định nghĩa đã nói ở phần trước.",
    }
    parts = [openers.get(section_kind, openers["general"])]
    if content_format:
        parts.append(f"Format nên dùng là {content_format.lower()}.")
    if preceding_question:
        parts.append(f"Câu mở section cần trả lời trực tiếp: '{preceding_question}'.")
    if sentence_before and not _contains_micro_placeholder(sentence_before):
        parts.append(f"Trước list hoặc bảng, dùng câu dẫn: '{sentence_before}'.")
    if h3_children:
        parts.append("Triển khai đúng trục H3 đã chốt để giữ contextual hierarchy: " + "; ".join(h3_children[:3]) + ".")
    if micro_terms:
        parts.append("Giữ các micro context terms này trong section: " + ", ".join(micro_terms[:5]) + ".")
    if next_heading:
        parts.append(f"Câu cuối nên mở tự nhiên sang section kế tiếp là '{next_heading}'.")
    elif contextual_bridge and not _contains_micro_placeholder(contextual_bridge):
        parts.append(f"Câu cuối dùng bridge ngữ cảnh: {contextual_bridge}")
    return " ".join(parts).strip()


def _deterministic_micro_info_gain(
    clean_title: str,
    h3_children: List[str],
    content_gaps: List[str],
    micro_terms: List[str],
) -> str:
    if h3_children:
        return "Các H3 trong phần này bao gồm: " + ", ".join(h3_children[:4]) + "."
    if content_gaps:
        return "Điểm vượt nên khai thác trực tiếp trong phần này là: " + ", ".join(content_gaps[:3]) + "."
    if micro_terms:
        return "Ưu tiên làm rõ các lớp nghĩa và tín hiệu quyết định như: " + ", ".join(micro_terms[:4]) + "."
    return f"Phần này cần tạo information gain bằng cách trả lời đúng user need của '{clean_title}' thay vì lặp lại phần định nghĩa."


def _deterministic_micro_bridge(
    clean_title: str,
    next_heading: str,
    instruction: Dict[str, Any],
    is_supp: bool,
) -> str:
    contextual_bridge = str(instruction.get("contextual_bridge", "")).strip()
    if is_supp:
        return f"Khép phần bổ trợ về {clean_title.lower()} bằng một câu chốt ngắn rồi chuyển sang CTA hoặc bước tiếp theo phù hợp."
    if next_heading:
        return f"Khép phần này bằng một câu nối logic sang: {next_heading}."
    if contextual_bridge and not _contains_micro_placeholder(contextual_bridge):
        return contextual_bridge
    return f"Khép phần này bằng một câu chốt giúp người đọc chuyển tự nhiên sang lớp thông tin tiếp theo của {clean_title.lower()}."


def _normalize_micro_briefing_data(
    brief: Dict[str, Any],
    project=None,
    per_h2: Optional[Dict[str, Any]] = None,
) -> bool:
    if not isinstance(brief, dict):
        return False

    micro = brief.get("micro_briefing", [])
    if isinstance(micro, dict):
        micro = micro.get("items", []) if "items" in micro else list(micro.values())
    if not isinstance(micro, list) or not micro:
        return False

    headings = brief.get("heading_structure", []) or []
    h2_order: List[str] = []
    h3_children_map: Dict[str, List[str]] = {}
    current_h2 = ""
    for heading in headings:
        if not isinstance(heading, dict):
            continue
        level = str(heading.get("level", "")).upper()
        text = str(heading.get("text", "")).strip()
        if not text:
            continue
        if level == "H2":
            current_h2 = text
            h2_order.append(text)
            h3_children_map.setdefault(current_h2, [])
        elif level == "H3" and current_h2:
            h3_children_map.setdefault(current_h2, []).append(text)

    h2_index_map = {_normalize_heading_key(text): idx for idx, text in enumerate(h2_order)}
    per_h2_map = per_h2.get("per_h2", {}) if isinstance(per_h2, dict) else {}
    content_gaps = [str(x).strip() for x in brief.get("content_gaps", []) or [] if str(x).strip()]
    changed = False

    for item in micro:
        if not isinstance(item, dict):
            continue
        heading_text = str(item.get("h2", "")).strip()
        if not heading_text:
            continue
        if _normalize_heading_key(heading_text).startswith("sapo"):
            continue

        heading_key = _normalize_heading_key(heading_text)
        idx = h2_index_map.get(heading_key, -1)
        actual_heading = h2_order[idx] if 0 <= idx < len(h2_order) else heading_text
        clean_title = _clean_heading_label(actual_heading)
        next_heading = _clean_heading_label(h2_order[idx + 1]) if 0 <= idx < len(h2_order) - 1 else ""
        h3_children = [_clean_heading_label(text) for text in h3_children_map.get(actual_heading, []) if _clean_heading_label(text)]
        instruction = _match_per_h2_instruction(per_h2_map, actual_heading)
        micro_terms = [str(term).strip() for term in instruction.get("micro_terms", []) if str(term).strip()]
        is_supp = "[supp]" in heading_text.lower() or "faq" in heading_key
        section_kind = _heading_kind_for_micro(actual_heading, is_supp=is_supp)

        snippet = _deterministic_micro_snippet(
            clean_title=clean_title,
            section_kind=section_kind,
            current_snippet=item.get("snippet", ""),
            instruction=instruction,
        )
        if snippet != str(item.get("snippet", "")).strip():
            item["snippet"] = snippet
            changed = True

        analysis = str(item.get("analysis", "")).strip()
        if _contains_micro_placeholder(analysis) or len(analysis.split()) < 14:
            item["analysis"] = _deterministic_micro_analysis(
                clean_title=clean_title,
                section_kind=section_kind,
                instruction=instruction,
                h3_children=h3_children,
                next_heading=next_heading,
            )
            changed = True

        info_gain = str(item.get("info_gain", "")).strip()
        if _contains_micro_placeholder(info_gain) or ("cac h3" not in _normalize_heading_key(info_gain) and h3_children):
            item["info_gain"] = _deterministic_micro_info_gain(
                clean_title=clean_title,
                h3_children=h3_children,
                content_gaps=content_gaps,
                micro_terms=micro_terms,
            )
            changed = True

        bridge = str(item.get("bridge", "")).strip()
        if _contains_micro_placeholder(bridge) or len(bridge.split()) < 8:
            item["bridge"] = _deterministic_micro_bridge(
                clean_title=clean_title,
                next_heading=next_heading,
                instruction=instruction,
                is_supp=is_supp,
            )
            changed = True

        transition = str(item.get("transition", "")).strip()
        if _contains_micro_placeholder(transition) or len(transition.split()) < 5:
            item["transition"] = (
                f"Chuyển tự nhiên sang {next_heading}."
                if next_heading
                else f"Khép phần {clean_title.lower()} bằng một câu chốt gợi bước tiếp theo."
            )
            changed = True

        if instruction:
            for field in [
                "content_format",
                "first_sentence",
                "sentence_before",
                "preceding_question",
                "contextual_bridge",
                "word_count_target",
                "section_predicates",
            ]:
                value = instruction.get(field)
                if value and (not item.get(field) or _contains_micro_placeholder(item.get(field, ""))):
                    item[field] = value
                    changed = True
            if micro_terms and (not item.get("micro_terms") or not isinstance(item.get("micro_terms"), list)):
                item["micro_terms"] = micro_terms[:5]
                changed = True

        if micro_terms:
            entities_text = ", ".join(micro_terms[:5])
            if _contains_micro_placeholder(item.get("entities", "")) or not str(item.get("entities", "")).strip():
                item["entities"] = entities_text
                changed = True

        guidance = str(item.get("guidance", "")).strip()
        if _contains_micro_placeholder(guidance) or len(guidance.split()) < 8:
            content_format = str(item.get("content_format", "")).strip() or "Paragraph"
            word_target = str(item.get("word_count_target", "")).strip()
            first_sentence = str(item.get("first_sentence", "")).strip()
            guidance_parts = [f"[{content_format}]"]
            if word_target:
                guidance_parts.append(word_target)
            if first_sentence:
                guidance_parts.append(f"Mở section bằng: {first_sentence}")
            if micro_terms:
                guidance_parts.append("Giữ micro terms: " + ", ".join(micro_terms[:4]))
            item["guidance"] = " | ".join(guidance_parts)
            changed = True

    brief["micro_briefing"] = micro
    return changed


def _agent_micro_briefing_writer(
    topic: str,
    entity: str,
    intent: str,
    niche: str,
    methodology_prompt: str,
    headings: List[Dict],
    paa_questions: List[str] = None,
    content_gaps: List[str] = None,
    classified_ngrams: Dict = None,
    entity_attributes: Dict = None,
    serp_data: Optional[Dict] = None,
    outline_signals: Optional[Dict] = None,
    semantic_reasoning: Optional[Dict[str, Any]] = None,
    project=None,  # Phase 33: Source Context
) -> List[Dict]:
    """
    Agent 3: The Micro-Brief Writer.
    Gọi LLM sinh bảng Micro-Briefing (A-B-C-D-E framework) chi tiết cho từng H2 đã chốt.
    Tuyệt đối không được phép đổi tên H2.
    """
    try:
        import json
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return _fallback_micro_briefing_data(
                topic, entity, intent, niche, methodology_prompt, headings,
                paa_questions=paa_questions, content_gaps=content_gaps,
                classified_ngrams=classified_ngrams, entity_attributes=entity_attributes,
                project=project,
            )

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        if openai is None:
            return _fallback_micro_briefing_data(
                topic, entity, intent, niche, methodology_prompt, headings,
                paa_questions=paa_questions, content_gaps=content_gaps,
                classified_ngrams=classified_ngrams, entity_attributes=entity_attributes,
                project=project,
            )
        client = openai.OpenAI(api_key=api_key)

        # V5.1: Pass both H2 and H3 to LLM so it doesn't drop H3s
        outline_structured_text = ""
        current_h2 = ""
        for h in headings:
            if h["level"] == "H2":
                current_h2 = h["text"]
                outline_structured_text += f"- H2: {current_h2}\n"
            elif h["level"] == "H3":
                outline_structured_text += f"  + H3: {h['text']}\n"
            elif h["level"] == "H4":
                outline_structured_text += f"    * H4: {h['text']}\n"

        if_no_h2 = [h["text"] for h in headings if h["level"] == "H2"]
        if not if_no_h2:
            return _fallback_micro_briefing_data(
                topic, entity, intent, niche, methodology_prompt, headings,
                paa_questions=paa_questions, content_gaps=content_gaps,
                classified_ngrams=classified_ngrams, entity_attributes=entity_attributes,
                project=project,
            )

        reasoning = semantic_reasoning if isinstance(semantic_reasoning, dict) else {}
        eav_rows_for_prompt = [
            row for row in (reasoning.get("verified_eav_rows", []) or [])
            if isinstance(row, dict) and row.get("is_verified")
        ]
        if not eav_rows_for_prompt and isinstance(entity_attributes, dict):
            for key, value in entity_attributes.items():
                eav_rows_for_prompt.append({
                    "entity": entity or topic,
                    "attribute": str(key),
                    "value": str(value),
                    "source_type": "entity_attribute",
                    "is_verified": False,
                    "needs_verification": True,
                })
        intent_pack = _infer_topic_focus_pack(
            topic,
            intent,
            consensus_points=(outline_signals or {}).get("consensus_points", []),
            gap_h2_candidates=(outline_signals or {}).get("gap_h2_candidates", []),
            gap_h3_candidates=(outline_signals or {}).get("gap_h3_candidates", []),
            eav_rows=eav_rows_for_prompt,
        )
        section_context_map = _build_section_context_map(
            headings,
            topic=topic,
            intent=intent,
            content_gaps=content_gaps,
            classified_ngrams=classified_ngrams,
            entity_attributes=entity_attributes,
            outline_signals=outline_signals,
            eav_rows=eav_rows_for_prompt,
            eav_quality=reasoning.get("eav_quality", {}),
        )
        prompt_packs = _build_agent3_prompt_packs(
            topic=topic,
            intent=intent,
            intent_pack=intent_pack,
            reasoning=reasoning,
            verified_rows=eav_rows_for_prompt,
            serp_data=serp_data,
            section_context_map=section_context_map,
        )

        # Agent 3 prompt contract is centralized in outline_content_prompt_catalog.
        user_content = (
            f"Chủ đề chính (H1): '{topic}'\n"
            f"Entity: '{entity}', Intent: '{intent}', Niche: '{niche}'\n"
            f"Methodology: {methodology_prompt}\n\n"
        )
        if prompt_packs.get("intent_bridge"):
            user_content += "--- PROMPT PACK 1: INTENT BRIDGE ---\n" + prompt_packs["intent_bridge"] + "\n\n"
        if prompt_packs.get("serp_bridge"):
            user_content += "--- PROMPT PACK 2: SEARCH RESULT EVIDENCE ---\n" + prompt_packs["serp_bridge"] + "\n\n"
        if prompt_packs.get("fact_pack"):
            user_content += "--- PROMPT PACK 3: CLEAN FACT PACK ---\n" + prompt_packs["fact_pack"] + "\n\n"
        if prompt_packs.get("quality_gate"):
            user_content += "--- PROMPT PACK 4: QUALITY GATE ---\n" + prompt_packs["quality_gate"] + "\n\n"
        user_content += (
            "--- DỮ LIỆU ĐẦU VÀO TỪ CÁC CỘT PHÂN TÍCH CHUYÊN SÂU ---\n"
        )
        if intent_pack:
            user_content += f"- Deep search task: {intent_pack.get('search_task', '')}\n"
            if intent_pack.get("must_cover"):
                user_content += "- Must-cover points: " + "; ".join(intent_pack.get("must_cover", [])[:6]) + "\n"
            if intent_pack.get("preferred_order"):
                user_content += "- Preferred section order: " + " -> ".join(intent_pack.get("preferred_order", [])[:7]) + "\n"
            if intent_pack.get("avoid_drift"):
                user_content += "- Off-topic exclusions: " + "; ".join(intent_pack.get("avoid_drift", [])[:5]) + "\n"
        if reasoning:
            dominant_user_task = str(reasoning.get("dominant_user_task", "")).strip()
            supporting_tasks = [str(x).strip() for x in reasoning.get("supporting_tasks", []) if str(x).strip()]
            decision_blockers = [str(x).strip() for x in reasoning.get("decision_blockers", []) if str(x).strip()]
            misinterpretation_risks = [str(x).strip() for x in reasoning.get("misinterpretation_risks", []) if str(x).strip()]
            consensus_facts = [str(x).strip() for x in reasoning.get("consensus_facts", []) if str(x).strip()]
            semantic_terms_curated = [str(x).strip() for x in reasoning.get("semantic_terms_curated", []) if str(x).strip()]
            preferred_flow = [str(x).strip() for x in reasoning.get("preferred_flow", []) if str(x).strip()]
            gap_map = reasoning.get("gap_map", {}) if isinstance(reasoning.get("gap_map", {}), dict) else {}
            user_content += "\n--- SEMANTIC REASONING LAYER (HARD CONTEXT) ---\n"
            if dominant_user_task:
                user_content += f"- Dominant user task: {dominant_user_task}\n"
            if supporting_tasks:
                user_content += "- Supporting tasks: " + "; ".join(supporting_tasks[:6]) + "\n"
            if decision_blockers:
                user_content += "- Decision blockers: " + "; ".join(decision_blockers[:5]) + "\n"
            if misinterpretation_risks:
                user_content += "- Misinterpretation risks / drift to avoid: " + "; ".join(misinterpretation_risks[:5]) + "\n"
            if consensus_facts:
                user_content += "- Consensus facts that readers expect: " + "; ".join(consensus_facts[:6]) + "\n"
            if preferred_flow:
                user_content += "- Preferred flow: " + " -> ".join(preferred_flow[:8]) + "\n"
            if semantic_terms_curated:
                user_content += "- Curated semantic support terms: " + ", ".join(semantic_terms_curated[:10]) + "\n"
            if gap_map:
                if gap_map.get("h2_worthy"):
                    user_content += "- H2-worthy gaps: " + "; ".join(gap_map.get("h2_worthy", [])[:6]) + "\n"
                if gap_map.get("supporting_detail"):
                    user_content += "- Supporting-detail gaps: " + "; ".join(gap_map.get("supporting_detail", [])[:6]) + "\n"
                if gap_map.get("topical_expansion"):
                    user_content += "- Topical expansions (only if they support the main intent): " + "; ".join(gap_map.get("topical_expansion", [])[:5]) + "\n"
                if gap_map.get("noise"):
                    user_content += "- Noise to ignore completely: " + "; ".join(gap_map.get("noise", [])[:5]) + "\n"
        if paa_questions:
            user_content += f"- Các câu hỏi FAQ/PAA đã chuẩn hóa theo project (Dùng làm FS Preceding Question, không bê nguyên PAA raw nếu lệch ngành): {', '.join(paa_questions)}\n"
        if content_gaps:
            user_content += f"- Content Gaps (Khoảng trống đối thủ thiếu sót - Cần khai thác trong Analysis): {', '.join(content_gaps)}\n"
        if classified_ngrams:
            entity_ngrams = classified_ngrams.get("entity", [])
            action_ngrams = classified_ngrams.get("action", [])
            if entity_ngrams:
                user_content += f"- Central Entity N-grams (PHẢI rải TOÀN BÀI, mỗi section ít nhất 1 lần): {', '.join(entity_ngrams[:6])}\n"
            if action_ngrams:
                user_content += f"- Macro Semantic N-grams (Chỉ rải vào section LIÊN QUAN, không ép vào mọi chỗ): {', '.join(action_ngrams[:8])}\n"

        # FIX 4: Truyền EAV reference table cho Agent 3 verbalize
        verified_rows = [row for row in eav_rows_for_prompt if isinstance(row, dict) and row.get("is_verified")]
        eav_quality = reasoning.get("eav_quality", {}) if isinstance(reasoning, dict) else {}
        if isinstance(eav_quality, dict) and eav_quality:
            user_content += (
                "\n- EAV Quality Gate: "
                f"verified_rows={int(eav_quality.get('verified_rows', 0))}; "
                f"attribute_families={int(eav_quality.get('attribute_families', 0))}; "
                f"coverage={str(eav_quality.get('coverage_status', 'weak'))}\n"
            )
            blocked_rows = eav_quality.get("blocked_numeric_rows", []) or []
            if blocked_rows:
                user_content += "- Blocked numeric rows (KHONG DUNG cho FS/Sapo/primary anchor): " + "; ".join(str(x) for x in blocked_rows[:5]) + "\n"
        if verified_rows:
            user_content += "\n- VERIFIED EAV FACTS ONLY (Duoc phep dung cho FS/Sapo/primary anchor):\n"
            for row in verified_rows[:8]:
                user_content += (
                    f"  * {str(row.get('attribute', ''))}: {str(row.get('value', ''))} "
                    f"(source={str(row.get('source_type', ''))}, confidence={str(row.get('confidence', ''))})\n"
                )
        if prompt_packs.get("section_bridge"):
            user_content += "\n--- PROMPT PACK 5: SECTION CONTEXT MAP ---\n"
            user_content += f"{prompt_packs['section_bridge']}\n"
        if reasoning:
            section_plan = reasoning.get("section_evidence_plan", {}) if isinstance(reasoning.get("section_evidence_plan"), dict) else {}
            per_heading = section_plan.get("per_heading", {}) if isinstance(section_plan.get("per_heading"), dict) else {}
            if per_heading:
                user_content += "\nSECTION EVIDENCE PLAN (MATCH DUNG THEO H2, KHONG SUY LUAN TUY TIEN):\n"
                for heading_name, meta in per_heading.items():
                    if not isinstance(meta, dict):
                        continue
                    user_content += f"- H2: {heading_name}\n"
                    user_content += f"  kind={meta.get('kind', '')}\n"
                    user_content += f"  primary_user_need={meta.get('primary_user_need', '')}\n"
                    evidence_types = meta.get("evidence_types", []) or []
                    if evidence_types:
                        user_content += "  evidence_types=" + ", ".join(str(x) for x in evidence_types[:4]) + "\n"
                    matched_eav = meta.get("matched_eav", []) or []
                    if matched_eav:
                        user_content += "  matched_eav=" + "; ".join(
                            f"{str(row.get('attribute', ''))}: {str(row.get('value', ''))}"
                            for row in matched_eav[:3] if isinstance(row, dict)
                        ) + "\n"
                    anchor_plan = meta.get("anchor_plan", []) or []
                    if anchor_plan:
                        user_content += "  anchor_plan=" + "; ".join(
                            f"{str(item.get('h3', ''))} => {str(item.get('anchor_type', ''))}: {str(item.get('anchor_text', ''))}"
                            for item in anchor_plan[:4] if isinstance(item, dict)
                        ) + "\n"
                    matched_consensus = meta.get("matched_consensus_facts", []) or []
                    if matched_consensus:
                        user_content += "  matched_consensus=" + "; ".join(str(x) for x in matched_consensus[:3]) + "\n"
                    matched_gaps = meta.get("matched_gaps", []) or []
                    if matched_gaps:
                        user_content += "  matched_gaps=" + "; ".join(
                            str(x.get("text", "")) for x in matched_gaps[:3] if isinstance(x, dict)
                        ) + "\n"
                    avoid_drift = meta.get("avoid_drift", []) or []
                    if avoid_drift:
                        user_content += "  avoid_drift=" + "; ".join(str(x) for x in avoid_drift[:3]) + "\n"
                user_content += "\n"

        user_content += (
            "\n"
            "DƯỚI ĐÂY LÀ DANH SÁCH CÁC HEADING (H2, H3, H4) ĐÃ ĐƯỢC CHỐT. BẠN PHẢI GIỮ NGUYÊN TÊN VÀ THỨ TỰ (Chỉ viết Micro-briefing object cho các H2):\n"
            f"{outline_structured_text}\n\n"
            "Hãy viết Sapo và sinh cấu trúc Micro-Briefing A-B-C-D-E (JSON Array) bám sát tuyệt đối vào danh sách mục lục trên và KẾT HỢP TRIỆT ĐỂ DỮ LIỆU ĐẦU VÀO Ở TRÊN để đạt chuẩn Semantic SEO."
        )

        logger.info("  [MICRO-BRIEFING] Gọi LLM lấy JSON chi tiết A-B-C-D-E format...")

        prompt_pack_sections = [build_writer_brief_block()]
        if prompt_packs.get("intent_bridge"):
            prompt_pack_sections.append("--- PROMPT PACK 1: INTENT BRIDGE ---\n" + prompt_packs["intent_bridge"])
        if prompt_packs.get("serp_bridge"):
            prompt_pack_sections.append("--- PROMPT PACK 2: SEARCH RESULT EVIDENCE ---\n" + prompt_packs["serp_bridge"])
        if prompt_packs.get("fact_pack"):
            prompt_pack_sections.append("--- PROMPT PACK 3: CLEAN FACT PACK ---\n" + prompt_packs["fact_pack"])
        if prompt_packs.get("quality_gate"):
            prompt_pack_sections.append("--- PROMPT PACK 4: QUALITY GATE ---\n" + prompt_packs["quality_gate"])
        if prompt_packs.get("section_bridge"):
            prompt_pack_sections.append("--- PROMPT PACK 5: SECTION CONTEXT MAP ---\n" + prompt_packs["section_bridge"])
        agent3_system, agent3_user = build_agent3_micro_brief_prompts(
            topic=topic,
            entity=entity,
            intent_label=intent,
            niche=niche,
            methodology_prompt=methodology_prompt,
            prompt_pack_text="\n\n".join(section for section in prompt_pack_sections if section),
            input_package_text=user_content,
        )
        agent3_system += (
            "\n\nCAP NHAT QUAN TRONG VE TOPIC PURITY:\n"
            "- Moi vi du domain trong prompt chi la vi du cau truc, KHONG phai noi dung bat buoc.\n"
            "- Tuyet doi khong duoc dua vao brief bat ky concept nao neu concept do khong duoc sinh ra tu query hien tai, research hien tai, EAV hien tai, consensus hien tai hoac gap hien tai.\n"
            "- Khong duoc mang semantic tu keyword truoc sang keyword nay.\n"
            "- Neu keyword hien tai khong sinh ra mot lop thong tin tu evidence hien tai thi khong tu y chen lop do vao outline hay snippet.\n"
            "- Section nao cung phai dung dung section kind va evidence type tu SECTION CONTEXT MAP; khong duoc suy luan theo mot topic mau.\n"
            "- Neu du lieu hien tai yeu, dung mo ta generic theo loai nhu cau va loai bang chung, KHONG duoc che them terms domain cu the.\n"
            "- Ban dang viet tai lieu huong dan cho writer/editor con nguoi. Khong duoc viet theo giong prompt engineering, khong dung cau kieu 'phan nay can', 'bai viet can', 'nguoi doc can'.\n"
            "- SAPO va Featured Snippet phai doc nhu mot doan content-that, tra loi truc dien query va section, khong phai ghi chu workflow.\n"
            "- Uu tien giai nghia tu nhung gi top search results thuc su dang tra loi: title, snippet, PAA va body fact da duoc loc sach.\n"
        )
        system_instruction = inject_semantic_prompt(agent3_system, agent_name="agent_3_micro")
        system_instruction = inject_source_context(system_instruction, project)
        user_content = agent3_user

        # Phase 2.3: Use llm_utils for retry + centralized settings
        from modules.llm_utils import call_llm_micro
        raw_text = call_llm_micro(
            client=client,
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        # Support both {"items": [...]} (with response_format) and raw [...]
        import re as _re
        _raw = raw_text.strip()
        if _raw.startswith("```json"):
            _raw = _raw[7:]
        elif _raw.startswith("```"):
            _raw = _raw[3:]
        if _raw.endswith("```"):
            _raw = _raw[:-3]
        _raw = _raw.strip()
        try:
            parsed_data = json.loads(_raw)
        except json.JSONDecodeError:
            _m = _re.search(r"\{[\s\S]+?\}|\[[\s\S]+?\]", _raw)
            parsed_data = json.loads(_m.group()) if _m else []

        if isinstance(parsed_data, dict) and "items" in parsed_data:
            _items = [item for item in parsed_data["items"] if isinstance(item, dict)]
            logger.info("  [MICRO-BRIEFING] Thành công tạo %d H2 templates", len(_items))
            return _items
        if isinstance(parsed_data, list):
            parsed_data = [item for item in parsed_data if isinstance(item, dict)]
            logger.info("  [MICRO-BRIEFING] Thành công tạo %d H2 templates", len(parsed_data))
            return parsed_data
        return _fallback_micro_briefing_data(
            topic, entity, intent, niche, methodology_prompt, headings,
            paa_questions=paa_questions, content_gaps=content_gaps,
            classified_ngrams=classified_ngrams, entity_attributes=entity_attributes,
            project=project,
        )
    except Exception as e:
        logger.warning(f"  [MICRO-BRIEFING] Lỗi API: {str(e)} -> Fallback...")
        return _fallback_micro_briefing_data(
            topic, entity, intent, niche, methodology_prompt, headings,
            paa_questions=paa_questions, content_gaps=content_gaps,
            classified_ngrams=classified_ngrams, entity_attributes=entity_attributes,
            project=project,
        )


def _generate_content_guidelines(
    topic: str,
    entity: str,
    intent: str,
    niche: str,
    classified_ngrams: Dict,
    headings: List[Dict] = None,
    methodology_prompt: str = "",
    micro_briefing: List = None,
) -> list:
    """
    Phase 9: Hướng dẫn viết — Smart N-grams + Dynamic E-E-A-T inline.

    - Chọn N-grams theo ngữ cảnh section (không random)
    - Inject yêu cầu E-E-A-T vào từng section
    - Thêm inline instruction cho mỗi H2
    """
    niche_eeat = NICHE_EEAT.get(niche, NICHE_EEAT["general"])
    inline_h2 = niche_eeat.get("inline_per_h2", "")

    h2_instructions = ""
    if headings:
        h2_list = [
            h["text"] for h in headings
            if h["level"] == "H2"
            and "faq" not in h["text"].lower()
            and "information gain" not in h["text"].lower()
        ]
        if h2_list:
            h2_instructions = "\n  **Hướng dẫn cho từng H2:**\n"
            # Lấy micro-briefing analysis cho từng H2 (nếu có)
            micro_map = {}
            if micro_briefing:
                for mb in micro_briefing:
                    if isinstance(mb, dict):
                        h2_name = str(mb.get("h2", ""))
                        analysis = str(mb.get("analysis", ""))
                        if h2_name and analysis and len(analysis) > 20:
                            micro_map[h2_name] = analysis
            for h2_text in h2_list:
                # Tìm matching micro-briefing analysis cho H2 này
                matched_analysis = ""
                h2_clean = h2_text.replace("[MAIN] ", "").replace("[SUPP] ", "")
                for mb_h2, mb_analysis in micro_map.items():
                    mb_clean = mb_h2.replace("[MAIN] ", "").replace("[SUPP] ", "")
                    if mb_clean.lower() in h2_clean.lower() or h2_clean.lower() in mb_clean.lower():
                        # Truncate to first 200 chars for readability
                        matched_analysis = mb_analysis[:200].rstrip() + ("..." if len(mb_analysis) > 200 else "")
                        break
                if matched_analysis:
                    h2_instructions += f"  - **{h2_text}:** {matched_analysis}\n"
                else:
                    h2_instructions += f"  - **{h2_text}:** {inline_h2}\n"

    guidelines = [
        {
            "section": "Mở bài (Introduction)",
            "guideline": (
                f"Giới thiệu ngắn gọn về {entity}. "
                "Trả lời thẳng trọng tâm title/main query ngay trong 1-2 câu đầu tiên. "
                "Brand không bắt buộc trong sapo; chỉ thêm nếu thật sự hợp source context. "
                f"💡 E-E-A-T: {niche_eeat['experience']}"
                + _smart_pick_ngrams(classified_ngrams, "intro", 3)
            ),
            "word_count": "100-150 từ",
        },
        {
            "section": "Nội dung chính (Main Content)",
            "guideline": (
                "Tuân theo Contextual Hierarchy: mỗi H2 tóm tắt H3 bên dưới. "
                "Với intent informational/how-to, ưu tiên viết H2/H3 dạng câu hỏi; chỉ dùng dạng mô tả khi câu hỏi quá dài hoặc kém tự nhiên. "
                "Duy trì Contextual Flow liền mạch giữa các section.\n\n"
                + f"📋 E-E-A-T: {niche_eeat['expertise']}"
                + (f"\n  **Methodology (Bắt buộc):** {methodology_prompt}" if methodology_prompt else "")
                + h2_instructions
                + _smart_pick_ngrams(classified_ngrams, "main", 5)
            ),
            "word_count": "800-1200 từ",
        },
        {
            "section": "FAQ (Câu hỏi thường gặp)",
            "guideline": (
                "Áp dụng Schema FAQ Markup. "
                "Tối ưu cho Featured Snippet: câu trả lời 40-60 từ. "
                f"🔗 E-E-A-T: {niche_eeat['authority']}"
                + _smart_pick_ngrams(classified_ngrams, "faq", 3)
            ),
            "word_count": "200-300 từ",
        },
        {
            "section": "Kết bài (Conclusion)",
            "guideline": (
                "Tóm tắt trừu tượng (Abstractive Summary) cho toàn bài. "
                "Đưa CTA phù hợp với Search Intent. "
                f"✅ E-E-A-T: {niche_eeat['trust']}"
                + _smart_pick_ngrams(classified_ngrams, "conclusion", 3)
            ),
            "word_count": "80-120 từ",
        },
    ]

    return guidelines


def _generate_linking_suggestions(
    related_topics: list,
    keyword_clusters: list = None,
    current_topic: str = "",
    enriched_headings: list = None,
    topical_map_csv: str = "",  # Phase 37: project-specific topical map
    niche: str = "general",      # Phase 38: industry context for filtering
) -> dict:
    """Tạo gợi ý internal linking từ keyword clusters hoặc related topics."""
    # Sử dụng module internal_linking.py có cluster-based linking (V5.3)
    try:
        from modules.internal_linking import build_internal_links
        result = build_internal_links(
            current_topic=current_topic,
            headings=enriched_headings or [],
            keyword_clusters=keyword_clusters,
            topical_map_csv=topical_map_csv,
            niche=niche,  # Phase 38: filter by industry
        )
        if result and result.get("outbound_nodes"):
            return result
    except ImportError:
        pass

    # Fallback: simple suggestions from related_topics
    outbound_nodes = []
    for topic in related_topics:
        outbound_nodes.append({
            "topic": topic,
            "target_topic": topic,
            "anchor": topic,
            "suggested_anchor": topic,
            "placement": "Trong section liên quan hoặc phần FAQ",
        })
    return {
        "role": "fallback",
        "cluster": "",
        "outbound_nodes": outbound_nodes,
        "inbound_topics": [],
        "tree_view": "",
    }


def _generate_eeat_checklist(entity: str, niche: str = "general") -> list:
    """
    Phase 9: E-E-A-T checklist theo niche (không còn generic).

    Returns:
        List of dicts: [{"criterion": str, "action": str}]
    """
    eeat = NICHE_EEAT.get(niche, NICHE_EEAT["general"])
    return [
        {
            "criterion": "Experience (Kinh nghiệm)",
            "action": eeat["experience"],
        },
        {
            "criterion": "Expertise (Chuyên môn)",
            "action": eeat["expertise"],
        },
        {
            "criterion": "Authoritativeness (Thẩm quyền)",
            "action": eeat["authority"],
        },
        {
            "criterion": "Trustworthiness (Độ tin cậy)",
            "action": eeat["trust"],
        },
    ]


def _apply_koray_micro_postprocess(brief: Dict, project=None) -> bool:
    """
    Rebuild SAPO and inject brand bridge outside the main Koray try block.
    This prevents later Koray failures from skipping source-context post-processing.
    """
    if not isinstance(brief, dict):
        return False

    micro = brief.get("micro_briefing", [])
    if isinstance(micro, dict):
        micro = micro.get("items", []) if "items" in micro else list(micro.values())
    if not isinstance(micro, list) or not micro:
        return False

    topic = str(brief.get("seed_keyword") or brief.get("topic") or "").strip()
    entity_name = str(brief.get("central_entity") or topic or "").strip()
    heading_structure = brief.get("heading_structure", []) or []
    h2_titles: List[str] = []
    for h in heading_structure:
        if isinstance(h, dict) and h.get("level") == "H2":
            raw = str(h.get("text", "")).strip()
            if raw:
                clean = raw.replace("[MAIN] ", "").replace("[SUPP] ", "").strip()
                clean = re.sub(r"\s+", " ", clean)
                h2_titles.append(clean)

    entity_attrs = brief.get("entity_attributes", {})
    changed = False

    def _word_count(text: str) -> int:
        return len([w for w in str(text).split() if w.strip()])

    def _cap_words(text: str, max_words: int) -> str:
        words = [w for w in str(text).split() if w.strip()]
        if len(words) <= max_words:
            return " ".join(words).strip()
        return " ".join(words[:max_words]).strip()

    def _build_sapo_text() -> str:
        parts: List[str] = []
        if topic:
            parts.append(
                f"{topic} cần được hiểu trong đúng ngữ cảnh của chủ đề, với phạm vi áp dụng, cấu phần chính và các điều kiện làm thay đổi cách đọc thông tin trong thực tế."
            )
        if entity_name:
            if topic and entity_name.lower() != topic.lower():
                parts.append(
                    f"Trọng tâm của bài là {entity_name}, đi từ các thuộc tính cốt lõi, cách phân loại đến những dấu hiệu giúp nhận diện đúng phạm vi áp dụng."
                )
            else:
                parts.append(
                    "Phần mở đầu cần chốt nhanh nghĩa lõi, sau đó nối sang cách đánh giá, điều kiện áp dụng và các lưu ý thực tế."
                )
        if isinstance(entity_attrs, dict) and entity_attrs:
            attr_pairs = []
            for key, value in list(entity_attrs.items())[:2]:
                value_text = str(value).strip()
                if value_text:
                    attr_pairs.append(f"{key}: {value_text}")
            if attr_pairs:
                parts.append("Các thuộc tính nổi bật gồm " + "; ".join(attr_pairs) + ".")
        if h2_titles:
            parts.append(
                "Mạch nội dung đi từ nghĩa lõi sang các thuộc tính, cách đánh giá, rủi ro và câu hỏi thường gặp để người đọc nắm toàn cảnh."
            )
        parts.append(
            "Mục tiêu là giúp người đọc chốt đúng phạm vi ứng dụng và có đủ dữ liệu để quyết định phần nào cần đào sâu tiếp theo."
        )
        text = " ".join(parts).strip()
        text = _cap_words(text, 120)
        if _word_count(text) < 80:
            text = (
                text
                + " "
                + "Nội dung tiếp theo sẽ đi sâu vào các thuộc tính kỹ thuật, cách phân loại, điểm cần so sánh và các lưu ý thực tế."
            ).strip()
            text = _cap_words(text, 120)
        return text

    sapo_snippet = str(micro[0].get("snippet", "")).strip()
    if _word_count(sapo_snippet) < 80:
        micro[0]["snippet"] = _build_sapo_text()
        changed = True

    if project:
        brand_name = getattr(project, "brand_name", "") or ""
        geo_kw = getattr(project, "geo_keywords", "") or ""
        hotline = getattr(project, "hotline", "") or ""
        if brand_name:
            last_supp_idx = -1
            for i in range(len(micro) - 1, 0, -1):
                h2_name = str(micro[i].get("h2", ""))
                if "[SUPP]" in h2_name or i == len(micro) - 1:
                    last_supp_idx = i
                    break

            if last_supp_idx > 0:
                bridge_text = str(micro[last_supp_idx].get("bridge", "")).strip()
                if brand_name.lower() not in bridge_text.lower():
                    nap_parts = [f"Để được tư vấn chọn {entity_name or topic} phù hợp, liên hệ {brand_name}"]
                    if hotline:
                        nap_parts.append(f"qua Hotline/Zalo: {hotline}")
                    if geo_kw:
                        nap_parts.append(f"(phục vụ khu vực {geo_kw.split(',')[0].strip()})")
                    nap_sentence = " ".join(nap_parts).strip() + "."
                    micro[last_supp_idx]["bridge"] = (bridge_text + "\n\n" + nap_sentence).strip()
                    changed = True

    brief["micro_briefing"] = micro
    return changed


def _rewrite_generic_heading(
    heading_text: str,
    main_keyword: str,
    intent: str,
    position: int,
) -> str:
    """
    Rewrite too-generic H2s into a more specific, question-like entity/attribute heading.
    """
    text = str(heading_text or "").strip()
    lower = text.lower()

    specific_patterns = [
        "là gì", "như thế nào", "bao nhiêu", "tại sao", "vì sao",
        "so sánh", "khác nhau", "ưu nhược", "giống nhau",
        "quy trình", "cách làm", "phân loại", "các loại",
        "rủi ro", "lợi ích", "lưu ý", "giá", "chi phí",
        "tỷ lệ", "thời gian", "điều kiện",
    ]
    if sum(1 for p in specific_patterns if p in lower) >= 2:
        return text

    main_keyword = str(main_keyword or "").strip()
    if not main_keyword:
        return text

    templates = {
        0: f"[MAIN] {main_keyword}: định nghĩa, phạm vi và bối cảnh",
        1: f"[MAIN] {main_keyword}: cơ chế hoạt động và các yếu tố chính",
        2: f"[MAIN] {main_keyword}: lợi ích, rủi ro và điều kiện áp dụng",
        3: f"[MAIN] {main_keyword}: cách đánh giá và ra quyết định",
    }
    if "faq" in lower or "câu hỏi" in lower or position >= 4:
        return f"[SUPP] FAQ: {main_keyword} và các câu hỏi thường gặp"

    return templates.get(position, text)


def _current_year() -> int:
    """Trả về năm hiện tại."""
    from datetime import datetime
    return datetime.now().year
