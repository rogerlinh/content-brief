from __future__ import annotations

import json
import math
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

try:
    from modules.query_network import get_network_clusters
except Exception:  # pragma: no cover - defensive fallback
    def get_network_clusters(network_data: Any) -> List[Dict]:
        return []


def build_outline_content_framework(brief: Dict[str, Any], project=None) -> Dict[str, Any]:
    topic = _clean_text(
        brief.get("seed_keyword")
        or brief.get("topic")
        or brief.get("central_entity")
    )
    if not topic:
        return {}

    sections = _extract_sections(brief.get("heading_structure", []) or [])
    serp = _build_serp_summary(brief)
    matrix = _build_heading_matrix(brief, sections, project=project)
    entities = _build_entity_map(brief, sections)
    keyword_map = _build_keyword_map(brief, sections, serp, project=project)
    outline_pack = _build_outline_package(brief, sections, serp)
    meta_pack = _build_meta_package(brief, project)
    writer_brief = _build_writer_briefing(
        brief=brief,
        project=project,
        serp=serp,
        matrix=matrix,
        entities=entities,
        keyword_map=keyword_map,
        outline_pack=outline_pack,
        meta_pack=meta_pack,
    )

    payload = {
        "input_mode": "single",
        "article_language": _infer_language(topic),
        "page_type": _infer_page_type(brief, project=project),
        "serp_analysis_summary": serp,
        "heading_frequency_matrix": matrix,
        "entity_map": entities,
        "keyword_map": keyword_map,
        "outline_package": outline_pack,
        "meta_schema_package": meta_pack,
        "writer_briefing_markdown": writer_brief,
    }
    payload["appendix_markdown"] = _render_appendix(payload)
    return payload


def _clean_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _normalize_ascii(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D")
    text = re.sub(r"\[[A-Z]+\]\s*", "", text)
    text = re.sub(r"^\d+[\.\)]\s*", "", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().lower()


def _token_set(value: Any) -> set[str]:
    return {
        token
        for token in _normalize_ascii(value).split()
        if len(token) >= 3 and token not in {"the", "and", "hay", "la", "gi", "cho", "voi"}
    }


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _is_contiguous_topic_phrase(text: Any, topic: Any) -> bool:
    phrase_tokens = _normalize_ascii(text).split()
    topic_tokens = _normalize_ascii(topic).split()
    if not phrase_tokens or not topic_tokens:
        return False
    width = len(phrase_tokens)
    for idx in range(0, max(0, len(topic_tokens) - width + 1)):
        if topic_tokens[idx:idx + width] == phrase_tokens:
            return True
    return False


def _is_quality_phrase(text: Any, topic: Any = "") -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return False
    tokens = _normalize_ascii(cleaned).split()
    if not tokens:
        return False
    if any(len(token) < 3 for token in tokens):
        return False
    if len(tokens) == 1 and len(tokens[0]) < 4:
        return False
    broken_ngrams = {
        "chinh gia", "gia cat", "cat loi",
    }
    normalized = _normalize_ascii(cleaned)
    if normalized in broken_ngrams:
        return False
    if len(tokens) >= 2 and topic:
        topic_token_set = set(_normalize_ascii(topic).split())
        if topic_token_set and all(token in topic_token_set for token in tokens):
            return _is_contiguous_topic_phrase(cleaned, topic)
    return True


def _is_financial_context(brief: Dict[str, Any], project=None) -> bool:
    return False

def _dedupe(items: List[str], limit: int = 999) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _normalize_intent(brief: Dict[str, Any]) -> str:
    intent = brief.get("search_intent", "")
    if isinstance(intent, dict):
        intent = intent.get("type", "")
    return _intent_bucket_label(intent)


def _intent_bucket_label(intent: Any) -> str:
    normalized = _normalize_ascii(intent)
    if "transaction" in normalized:
        return "Transactional"
    if "navig" in normalized:
        return "Navigational"
    if "commercial" in normalized or normalized == "vs":
        return "Commercial Investigation"
    return "Informational"


def _serp_source_label(source: Any) -> str:
    normalized = _normalize_ascii(source)
    if normalized == "serper_google":
        return "Google via Serper.dev"
    if normalized.startswith("google_html"):
        return "Google HTML fallback"
    if normalized.startswith("duckduckgo"):
        return "DuckDuckGo fallback"
    if normalized == "serper_unavailable":
        return "Serper unavailable"
    return _clean_text(source)


def _intent_mix_summary(distribution: Any) -> str:
    if not isinstance(distribution, dict):
        return ""
    parts: List[str] = []
    for bucket in (
        "informational",
        "commercial investigation",
        "transactional",
        "navigational",
    ):
        item = distribution.get(bucket, {})
        if not isinstance(item, dict):
            continue
        percentage = item.get("percentage")
        try:
            pct_value = float(percentage)
        except Exception:
            continue
        if pct_value <= 0:
            continue
        parts.append(f"{_intent_bucket_label(bucket)} {pct_value:.1f}%")
    return ", ".join(parts)


def _infer_page_type(brief: Dict[str, Any], project=None) -> str:
    intent = _normalize_intent(brief)
    if _is_financial_context(brief, project=project):
        serp = brief.get("serp_analysis", {}) if isinstance(brief.get("serp_analysis"), dict) else {}
        dominant_format = _clean_text(serp.get("dominant_format"))
        if dominant_format not in {"Product/Category", "Landing page"}:
            return "Blog informational"
    if intent == "Transactional":
        return "Product / Landing page"
    if intent == "Commercial Investigation":
        return "Comparison / review page"
    return "Blog informational"


def _infer_language(topic: str) -> str:
    if re.search(r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", topic):
        return "Vietnamese"
    return "English / other"


def _extract_sections(headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for item in headings:
        if not isinstance(item, dict):
            continue
        level = _clean_text(item.get("level")).upper()
        text = _clean_heading(item.get("text"))
        if not text:
            continue
        if level == "H2":
            current = {"h2": text, "h3": []}
            sections.append(current)
        elif level == "H3" and current is not None:
            current["h3"].append(text)
    return sections


def _clean_heading(value: Any) -> str:
    text = _clean_text(value)
    text = re.sub(r"^\[[A-Z]+\]\s*", "", text)
    return text.strip(" -:")


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _build_serp_summary(brief: Dict[str, Any]) -> Dict[str, Any]:
    serp = brief.get("serp_analysis", {}) if isinstance(brief.get("serp_analysis"), dict) else {}
    competitor = brief.get("competitor_analysis", {}) if isinstance(brief.get("competitor_analysis"), dict) else {}
    organic_results = _safe_list(serp.get("organic_results"))
    intent_decision = serp.get("final_intent_decision", {}) if isinstance(serp.get("final_intent_decision"), dict) else {}
    if not intent_decision:
        intent_decision = serp.get("intent_decision", {}) if isinstance(serp.get("intent_decision"), dict) else {}
    intent_distribution = serp.get("intent_distribution", {}) if isinstance(serp.get("intent_distribution"), dict) else {}
    competitor_body_distribution = (
        serp.get("competitor_body_intent_distribution", {})
        if isinstance(serp.get("competitor_body_intent_distribution"), dict)
        else {}
    )
    competitor_body_decision = (
        serp.get("competitor_body_intent_decision", {})
        if isinstance(serp.get("competitor_body_intent_decision"), dict)
        else {}
    )
    archetype_summary = competitor.get("archetype_summary", {}) if isinstance(competitor.get("archetype_summary"), dict) else {}
    top_archetypes = archetype_summary.get("top_archetypes", []) if isinstance(archetype_summary.get("top_archetypes", []), list) else []
    top_competitors = []
    for item in organic_results[:10]:
        if not isinstance(item, dict):
            continue
        top_competitors.append(
            {
                "url": _clean_text(item.get("url")),
                "title": _clean_text(item.get("title")),
                "snippet": _clean_text(item.get("snippet")),
            }
        )

    result_format_counts = serp.get("result_format_counts", {}) if isinstance(serp.get("result_format_counts"), dict) else {}
    dominant_format = _clean_text(serp.get("dominant_format"))
    if not dominant_format:
        dominant_format = _infer_dominant_format_from_results(organic_results)

    serp_features = _dedupe(_safe_list(serp.get("serp_features")), limit=12)
    paa_questions = _dedupe(
        _safe_list(serp.get("people_also_ask")) or _safe_list(brief.get("faq_questions")),
        limit=10,
    )
    related = _dedupe(_safe_list(serp.get("related_searches")), limit=10)
    selected_intent = _intent_bucket_label(intent_decision.get("selected_intent") or brief.get("search_intent", ""))
    intent_mix_summary = _intent_mix_summary(intent_distribution)
    secondary_intent = _clean_text(intent_decision.get("secondary_intent"))

    return {
        "dominant_format": dominant_format or "Mixed",
        "search_intent": selected_intent or _normalize_intent(brief),
        "serp_features": serp_features,
        "result_format_counts": result_format_counts,
        "top_competitors": top_competitors,
        "paa_questions": paa_questions,
        "related_searches": related,
        "intent_distribution": intent_distribution,
        "intent_mix_summary": intent_mix_summary,
        "intent_rationale": _clean_text(intent_decision.get("rationale")),
        "secondary_intent": _intent_bucket_label(secondary_intent) if secondary_intent else "",
        "competitor_body_intent_mix_summary": _intent_mix_summary(competitor_body_distribution),
        "competitor_body_selected_intent": _intent_bucket_label(competitor_body_decision.get("selected_intent")),
        "competitor_body_rationale": _clean_text(competitor_body_decision.get("rationale")),
        "competitor_top_archetypes": [
            f"{_clean_text(item.get('archetype'))} {float(item.get('percentage', 0.0)):.1f}%"
            for item in top_archetypes[:4]
            if isinstance(item, dict) and _clean_text(item.get("archetype"))
        ],
        "source_confidence": _clean_text(intent_decision.get("source_confidence")),
        "serp_source": _serp_source_label(serp.get("serp_source")),
        "intent_source": _clean_text(intent_decision.get("source")),
        "featured_snippet": serp.get("featured_snippet", {}) if isinstance(serp.get("featured_snippet"), dict) else {},
        "knowledge_panel": serp.get("knowledge_panel", {}) if isinstance(serp.get("knowledge_panel"), dict) else {},
    }


def _infer_dominant_format_from_results(organic_results: List[Any]) -> str:
    counts = {"Blog/Article": 0, "Product/Category": 0, "Landing page": 0, "Video/Forum/Other": 0}
    for item in organic_results:
        if not isinstance(item, dict):
            continue
        url = _clean_text(item.get("url"))
        title = _clean_text(item.get("title"))
        snippet = _clean_text(item.get("snippet"))
        counts[_classify_result_format(url, title, snippet)] += 1
    if not any(counts.values()):
        return "Mixed"
    top_format, top_count = max(counts.items(), key=lambda pair: pair[1])
    return top_format if top_count >= 3 else "Mixed"


def _classify_result_format(url: str, title: str, snippet: str) -> str:
    haystack = f"{url} {title} {snippet}".lower()
    if any(marker in haystack for marker in ["youtube.com", "youtu.be", "reddit.com", "forum", "video", "watch?v="]):
        return "Video/Forum/Other"
    if any(marker in haystack for marker in ["/product", "/san-pham", "/category", "/danh-muc", "bao gia", "gia ", "mua ", "price"]):
        return "Product/Category"
    if any(marker in haystack for marker in ["/landing", "/service", "/dich-vu", "landing page"]):
        return "Landing page"
    return "Blog/Article"


def _build_heading_matrix(brief: Dict[str, Any], sections: List[Dict[str, Any]], project=None) -> Dict[str, Any]:
    competitor = brief.get("competitor_analysis", {}) if isinstance(brief.get("competitor_analysis"), dict) else {}
    matrix = competitor.get("heading_frequency_matrix", {}) if isinstance(competitor.get("heading_frequency_matrix"), dict) else {}
    rows = _safe_list(matrix.get("rows"))
    competitor_urls = _safe_list(matrix.get("competitor_urls"))
    if not rows:
        rows, competitor_urls = _fallback_heading_matrix(competitor)

    could_have = []
    outline_signals = brief.get("outline_signals", {}) if isinstance(brief.get("outline_signals"), dict) else {}
    for item in _safe_list(outline_signals.get("gap_h2_candidates")) + _safe_list(outline_signals.get("gap_h3_candidates")):
        could_have.append(_clean_text(item))
    serp = brief.get("serp_analysis", {}) if isinstance(brief.get("serp_analysis"), dict) else {}
    could_have.extend(item for item in _safe_list(serp.get("related_searches")))
    could_have.extend(item for item in _safe_list(serp.get("people_also_ask")))

    return {
        "competitor_urls": competitor_urls,
        "rows": rows[:12],
        "could_have": _dedupe(could_have, limit=8),
        "mandatory_topics": [row["topic"] for row in rows if str(row.get("classification", "")).lower() == "must_have"][:8],
        "recommended_topics": [row["topic"] for row in rows if str(row.get("classification", "")).lower() == "should_have"][:8],
        "outline_topics": [section["h2"] for section in sections],
    }


def _fallback_heading_matrix(competitor: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    details = _safe_list(competitor.get("competitors_detail"))
    competitor_urls = [_clean_text(item.get("url")) for item in details if isinstance(item, dict) and _clean_text(item.get("url"))]
    per_url_topics: List[set[str]] = []
    topic_labels: Dict[str, str] = {}
    for item in details:
        if not isinstance(item, dict):
            continue
        current_topics = set()
        for heading in _safe_list(item.get("headings")):
            if not isinstance(heading, dict) or _clean_text(heading.get("level")).upper() != "H2":
                continue
            text = _clean_heading(heading.get("text"))
            key = _normalize_ascii(text)
            if not key:
                continue
            current_topics.add(key)
            topic_labels.setdefault(key, text)
        per_url_topics.append(current_topics)

    rows: List[Dict[str, Any]] = []
    for topic_key, topic_label in topic_labels.items():
        hits = [topic_key in topic_set for topic_set in per_url_topics]
        total = sum(1 for hit in hits if hit)
        denom = max(1, len(per_url_topics))
        rows.append(
            {
                "topic": topic_label,
                "hits": hits,
                "frequency": f"{total}/{denom}",
                "classification": _classify_frequency(total, denom),
            }
        )
    rows.sort(key=lambda row: (-sum(1 for hit in row["hits"] if hit), row["topic"].lower()))
    return rows, competitor_urls


def _classify_frequency(total: int, denom: int) -> str:
    if denom <= 0:
        return "could_have"
    must_threshold = max(2, math.ceil((2 * denom) / 3)) if denom >= 3 else denom
    should_threshold = max(1, math.ceil(denom / 3))
    if total >= must_threshold:
        return "must_have"
    if total >= should_threshold:
        return "should_have"
    return "could_have"


def _build_entity_map(brief: Dict[str, Any], sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    serp = brief.get("serp_analysis", {}) if isinstance(brief.get("serp_analysis"), dict) else {}
    entity_bucket = serp.get("serp_entities", {}) if isinstance(serp.get("serp_entities"), dict) else {}
    knowledge_panel = serp.get("knowledge_panel", {}) if isinstance(serp.get("knowledge_panel"), dict) else {}
    central_entity = _clean_text(brief.get("central_entity") or brief.get("topic") or brief.get("seed_keyword"))

    candidates: List[Tuple[str, str, str, str, str]] = []
    if central_entity:
        candidates.append(
            (
                central_entity,
                _clean_text(knowledge_panel.get("type")) or "Thing",
                "High",
                _clean_text(knowledge_panel.get("description")),
                "central_entity",
            )
        )

    for item in _safe_list(entity_bucket.get("primary"))[:6]:
        candidates.append((_clean_text(item), _clean_text(knowledge_panel.get("type")) or "Thing", "High", "", "serp_primary"))
    for item in _safe_list(entity_bucket.get("secondary"))[:6]:
        candidates.append((_clean_text(item), "Thing", "Medium", "", "serp_secondary"))

    entities: List[Dict[str, Any]] = []
    seen = set()
    for name, entity_type, relevance, description, source in candidates:
        if not name:
            continue
        if not _is_quality_phrase(name, central_entity):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "entity": name,
                "type": entity_type or "Thing",
                "relevance": relevance,
                "description": description,
                "suggested_placement": _suggest_placement(name, sections),
                "source": source,
            }
        )
    return entities[:10]


def _build_keyword_map(
    brief: Dict[str, Any],
    sections: List[Dict[str, Any]],
    serp: Dict[str, Any],
    project=None,
) -> Dict[str, Any]:
    primary_keyword = _clean_text(brief.get("seed_keyword") or brief.get("topic") or brief.get("central_entity"))
    semantic_reasoning = brief.get("semantic_reasoning", {}) if isinstance(brief.get("semantic_reasoning"), dict) else {}
    competitor = brief.get("competitor_analysis", {}) if isinstance(brief.get("competitor_analysis"), dict) else {}
    query_network = brief.get("query_network", {}) if isinstance(brief.get("query_network"), dict) else {}

    network_clusters = get_network_clusters(query_network)
    secondary: List[Tuple[str, str]] = []
    for cluster in network_clusters[:8]:
        if not isinstance(cluster, dict):
            continue
        keyword = _clean_text(cluster.get("primary_keyword") or cluster.get("keyword"))
        if keyword and _normalize_ascii(keyword) != _normalize_ascii(primary_keyword):
            secondary.append((keyword, _clean_text(cluster.get("intent")) or _infer_keyword_intent(keyword)))

    for query in serp.get("related_searches", []):
        if _normalize_ascii(query) != _normalize_ascii(primary_keyword):
            secondary.append((_clean_text(query), _infer_keyword_intent(query)))

    semantic_terms = []
    semantic_terms.extend(_safe_list(semantic_reasoning.get("semantic_terms_curated")))
    for group in ("ngrams_2", "ngrams_3"):
        for item in _safe_list(competitor.get(group))[:8]:
            if isinstance(item, (list, tuple)) and item:
                semantic_terms.append(str(item[0]))
            elif isinstance(item, str):
                semantic_terms.append(item)
    semantic_terms.extend(_safe_list(serp.get("serp_attributes")))

    long_tail = []
    for question in serp.get("paa_questions", []):
        long_tail.append((_clean_text(question), "Informational"))
    for cluster in network_clusters[:8]:
        if not isinstance(cluster, dict):
            continue
        for variant in _safe_list(cluster.get("keywords"))[:4]:
            text = _clean_text(variant)
            if text and len(text.split()) >= 3:
                long_tail.append((text, _clean_text(cluster.get("intent")) or _infer_keyword_intent(text)))

    secondary_entries = _keyword_entries(secondary, sections, source="query_network / related_searches", limit=10, topic=primary_keyword)
    semantic_entries = _keyword_entries([(term, _infer_keyword_intent(term)) for term in semantic_terms], sections, source="semantic reasoning / competitor n-grams", limit=12, topic=primary_keyword)
    long_tail_entries = _keyword_entries(long_tail, sections, source="PAA / query network", limit=10, topic=primary_keyword)

    primary_entry = {
        "keyword": primary_keyword,
        "intent": serp.get("search_intent") or _normalize_intent(brief),
        "placement": "H1 + opening sentence",
        "search_volume": None,
        "keyword_difficulty": None,
        "cpc": None,
        "source": "seed keyword",
    }

    keyword_rows = _build_keyword_rows(primary_keyword, sections, secondary_entries, semantic_entries)
    return {
        "metrics_available": False,
        "metrics_note": _tool_only_metrics_note(),
        "primary_keyword": primary_entry,
        "secondary_keywords": secondary_entries,
        "semantic_keywords": semantic_entries,
        "long_tail_keywords": long_tail_entries,
        "table_rows": keyword_rows,
    }


def _keyword_entries(
    pairs: List[Tuple[str, str]],
    sections: List[Dict[str, Any]],
    source: str,
    limit: int,
    topic: str = "",
) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for keyword, intent in pairs:
        text = _clean_text(keyword)
        if not text:
            continue
        if not _is_quality_phrase(text, topic):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "keyword": text,
                "intent": intent or _infer_keyword_intent(text),
                "placement": _suggest_placement(text, sections),
                "search_volume": None,
                "keyword_difficulty": None,
                "cpc": None,
                "source": source,
            }
        )
        if len(deduped) >= limit:
            break
    return deduped


def _tool_only_metrics_note() -> str:
    return (
        "Tool-only mode: volume/KD are intentionally skipped. "
        "The outline follows the GitHub outline-content workflow using SERP, PAA, related searches, "
        "entity mapping, and competitor heading frequency instead of external keyword providers."
    )


def _format_metric_value(value: Any) -> str:
    if value in (None, ""):
        return "N/A"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return _clean_text(value) or "N/A"


def _source_with_metrics(item: Dict[str, Any]) -> str:
    return _clean_text(item.get("source"))


def _infer_keyword_intent(keyword: str) -> str:
    normalized = _normalize_ascii(keyword)
    if "gia" in normalized or "bao nhieu" in normalized or "price" in normalized:
        return "Commercial Investigation"
    if any(token in normalized for token in ["mua", "dang ky", "dat hang", "buy"]):
        return "Transactional"
    if any(token in normalized for token in ["vs", "so sanh", "khac nhau", "review", "tot nhat"]):
        return "Commercial Investigation"
    return "Informational"


def _suggest_placement(text: str, sections: List[Dict[str, Any]]) -> str:
    if not sections:
        return "H1"
    best_label = f'H2 "{sections[0]["h2"]}"'
    best_score = 0.0
    for section in sections:
        score = _token_overlap(text, section["h2"])
        if score > best_score:
            best_score = score
            best_label = f'H2 "{section["h2"]}"'
        for h3 in section["h3"]:
            h3_score = _token_overlap(text, h3)
            if h3_score > best_score:
                best_score = h3_score
                best_label = f'H3 "{h3}"'
    return best_label if best_score >= 0.2 else best_label


def _build_keyword_rows(
    primary_keyword: str,
    sections: List[Dict[str, Any]],
    secondary_entries: List[Dict[str, Any]],
    semantic_entries: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    rows = [
        {
            "section": "H1",
            "primary_keyword": primary_keyword,
            "secondary": ", ".join(entry["keyword"] for entry in secondary_entries[:2]),
            "lsi": ", ".join(entry["keyword"] for entry in semantic_entries[:3]),
        },
        {
            "section": "Intro",
            "primary_keyword": primary_keyword,
            "secondary": ", ".join(entry["keyword"] for entry in secondary_entries[:3]),
            "lsi": ", ".join(entry["keyword"] for entry in semantic_entries[:2]),
        },
    ]

    for section in sections[:8]:
        matched_secondary = [
            entry["keyword"]
            for entry in secondary_entries
            if _token_overlap(entry["keyword"], section["h2"]) >= 0.2
        ]
        matched_lsi = [
            entry["keyword"]
            for entry in semantic_entries
            if _token_overlap(entry["keyword"], section["h2"]) >= 0.15
        ]
        rows.append(
            {
                "section": section["h2"],
                "primary_keyword": primary_keyword if _token_overlap(primary_keyword, section["h2"]) >= 0.2 else "",
                "secondary": ", ".join(matched_secondary[:3]),
                "lsi": ", ".join(matched_lsi[:3]),
            }
        )
    return rows


def _build_outline_package(brief: Dict[str, Any], sections: List[Dict[str, Any]], serp: Dict[str, Any]) -> Dict[str, Any]:
    micro = _safe_list(brief.get("micro_briefing"))
    intro_brief = _clean_text(micro[0].get("snippet")) if micro and isinstance(micro[0], dict) else ""
    top_competitor_wc = 0
    competitor = brief.get("competitor_analysis", {}) if isinstance(brief.get("competitor_analysis"), dict) else {}
    info_gain = competitor.get("information_gain", {}) if isinstance(competitor.get("information_gain"), dict) else {}
    coverage = info_gain.get("coverage_matrix", {}) if isinstance(info_gain.get("coverage_matrix"), dict) else {}
    if coverage:
        top_competitor_wc = max(int(_safe_number(item.get("word_count"))) for item in coverage.values() if isinstance(item, dict))

    section_rows = []
    total_h3 = 0
    macro_count = 0
    for section in sections:
        h3_list = section["h3"]
        total_h3 += len(h3_list)
        kind = "MACRO" if len(h3_list) >= 2 or _looks_macro(section["h2"]) else "MICRO"
        if kind == "MACRO":
            macro_count += 1
        word_budget = 350 if kind == "MACRO" else 180
        word_budget += len(h3_list) * (110 if kind == "MACRO" else 70)
        section_rows.append(
            {
                "h2": section["h2"],
                "kind": kind,
                "suggested_words": word_budget,
                "h3": h3_list,
            }
        )

    estimated_word_count = len(sections) * 200 + total_h3 * 100 + 180
    target_word_count = max(estimated_word_count, int(top_competitor_wc * 0.8) if top_competitor_wc else 0)
    if not target_word_count:
        target_word_count = estimated_word_count

    outline_lines = [f"H1: {_clean_text(brief.get('title_tag')) or _clean_text(brief.get('topic'))}"]
    if intro_brief:
        outline_lines.append("")
        outline_lines.append(f"Intro: {intro_brief}")
    for row in section_rows:
        outline_lines.append("")
        outline_lines.append(f"- H2 ({row['kind']}, ~{row['suggested_words']} words): {row['h2']}")
        for h3 in row["h3"]:
            outline_lines.append(f"  - H3: {h3}")
    conclusion = _build_conclusion_brief(brief, serp)
    if conclusion:
        outline_lines.append("")
        outline_lines.append(f"Conclusion / CTA: {conclusion}")

    macro_ratio = round((macro_count / len(section_rows)) * 100, 1) if section_rows else 0.0
    return {
        "h1": _clean_text(brief.get("title_tag")) or _clean_text(brief.get("topic")),
        "intro_brief": intro_brief,
        "sections": section_rows,
        "conclusion_brief": conclusion,
        "estimated_word_count": estimated_word_count,
        "target_word_count": target_word_count,
        "macro_ratio": macro_ratio,
        "faq_questions": serp.get("paa_questions", []),
        "rendered_outline_markdown": "\n".join(outline_lines).strip(),
    }


def _safe_number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _looks_macro(heading: str) -> bool:
    normalized = _normalize_ascii(heading)
    macro_markers = [
        "la gi", "dinh nghia", "phan loai", "huong dan", "so sanh",
        "quy trinh", "cach", "loi ich", "rui ro",
    ]
    return any(marker in normalized for marker in macro_markers)


def _build_conclusion_brief(brief: Dict[str, Any], serp: Dict[str, Any]) -> str:
    internal = brief.get("internal_linking", {})
    outbound = []
    if isinstance(internal, dict):
        outbound = _safe_list(internal.get("outbound_nodes"))
    anchors = []
    for item in outbound[:3]:
        if not isinstance(item, dict):
            continue
        topic = _clean_text(item.get("topic") or item.get("target_topic"))
        anchor = _clean_text(item.get("anchor") or item.get("anchor_text_suggestion"))
        if topic or anchor:
            anchors.append(anchor or topic)
    if anchors:
        return "Summarize the key takeaways, then bridge naturally to internal links such as " + ", ".join(anchors) + "."
    if serp.get("paa_questions"):
        return "Summarize the key takeaways and close with a concise CTA that points readers to the next practical question or comparison."
    return "Summarize the key takeaways and close with a concise CTA aligned with the page intent."


def _build_meta_package(brief: Dict[str, Any], project=None) -> Dict[str, Any]:
    topic = _clean_text(brief.get("seed_keyword") or brief.get("topic") or brief.get("central_entity"))
    intent = _normalize_intent(brief)
    brand = _clean_text(getattr(project, "brand_name", "")) if project else ""
    page_type = _infer_page_type(brief, project=project)
    title_options = _title_options(topic, brand, intent, page_type=page_type, brief=brief, project=project)
    description_options = _description_options(topic, brand, intent, page_type=page_type, brief=brief, project=project)
    schema_skeletons = _schema_skeletons(brief, project, title_options[0] if title_options else topic)
    schema_type = " + ".join(item["label"] for item in schema_skeletons) if schema_skeletons else "Article"
    return {
        "meta_title_options": title_options,
        "meta_description_options": description_options,
        "schema_type": schema_type,
        "schema_skeletons": schema_skeletons,
    }


def _title_options(topic: str, brand: str, intent: str, page_type: str = "", brief: Dict[str, Any] | None = None, project=None) -> List[str]:
    year = "2026"
    is_financial_article = bool(brief and _is_financial_context(brief, project=project)) and page_type == "Blog informational"
    options = [
        _fit_title(f"{topic.title()} | Huong dan chi tiet {year}", brand),
        _fit_title(f"{topic.title()} {year}: Tong hop can biet", brand),
        _fit_title(f"{topic.title()} la gi? Giai thich de hieu", brand),
    ]
    if intent == "Commercial Investigation":
        options[1] = _fit_title(f"So sanh {topic.lower()} chi tiet {year}", brand)
    if intent == "Transactional" and not is_financial_article:
        options[2] = _fit_title(f"Gia {topic.lower()} moi nhat {year}", brand)
    return _dedupe(options, limit=3)


def _fit_title(base: str, brand: str) -> str:
    title = _clean_text(base)
    if brand:
        with_brand = f"{title} | {brand}"
        if len(with_brand) <= 60:
            title = with_brand
    if len(title) <= 60:
        return title
    shortened = title[:57].rstrip(" -|") + "..."
    return shortened


def _description_options(topic: str, brand: str, intent: str, page_type: str = "", brief: Dict[str, Any] | None = None, project=None) -> List[str]:
    is_financial_article = bool(brief and _is_financial_context(brief, project=project)) and page_type == "Blog informational"
    base_options = [
        f"Tim hieu {topic.lower()} ro rang: khai niem, cach hoat dong, loi ich, rui ro va cac dieu kien can biet truoc khi ap dung.",
        f"Huong dan {topic.lower()} theo dung ngu canh tim kiem: ban chat, cau truc, vi du thuc te va nhung luu y quan trong.",
    ]
    if intent == "Commercial Investigation" and not is_financial_article:
        base_options[0] = f"So sanh {topic.lower()} theo intent, heading doi thu, keyword map va diem can co trong outline de chot huong noi dung."
    if brand:
        base_options[1] = base_options[1].rstrip(".") + f" Phu hop ngu canh thuong hieu {brand}."
    results = []
    for option in base_options:
        text = _clean_text(option)
        if len(text) > 160:
            text = text[:157].rstrip() + "..."
        results.append(text)
    return _dedupe(results, limit=2)


def _schema_skeletons(brief: Dict[str, Any], project, headline: str) -> List[Dict[str, Any]]:
    topic = _clean_text(brief.get("seed_keyword") or brief.get("topic") or brief.get("central_entity"))
    intent = _normalize_intent(brief)
    page_type = _infer_page_type(brief, project=project)
    faq_questions = _safe_list(brief.get("faq_questions"))
    schemas: List[Dict[str, Any]] = [
        {
            "label": "Article",
            "schema": {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": headline,
                "author": {"@type": "Organization" if project else "Person", "name": _clean_text(getattr(project, "brand_name", "")) if project else ""},
                "datePublished": "",
                "dateModified": "",
                "mainEntityOfPage": "",
                "about": topic,
            },
        }
    ]
    if faq_questions:
        schemas.append(
            {
                "label": "FAQPage",
                "schema": {
                    "@context": "https://schema.org",
                    "@type": "FAQPage",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": question,
                            "acceptedAnswer": {"@type": "Answer", "text": ""},
                        }
                        for question in faq_questions[:3]
                    ],
                },
            }
        )
    if page_type == "Product / Landing page" and intent in {"Commercial Investigation", "Transactional"}:
        schemas.append(
            {
                "label": "Product",
                "schema": {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": topic,
                    "description": _clean_text(brief.get("meta_description")),
                    "brand": {"@type": "Brand", "name": _clean_text(getattr(project, "brand_name", "")) if project else ""},
                },
            }
        )
    if project and _clean_text(getattr(project, "domain", "")):
        domain = _clean_text(getattr(project, "domain", ""))
        schemas.append(
            {
                "label": "Organization",
                "schema": {
                    "@context": "https://schema.org",
                    "@type": "Organization",
                    "name": _clean_text(getattr(project, "brand_name", "")),
                    "url": f"https://{domain.strip('/')}/",
                    "telephone": _clean_text(getattr(project, "hotline", "")),
                    "areaServed": _clean_text(getattr(project, "geo_keywords", "")),
                },
            }
        )
    return schemas


def _build_writer_briefing(
    *,
    brief: Dict[str, Any],
    project,
    serp: Dict[str, Any],
    matrix: Dict[str, Any],
    entities: List[Dict[str, Any]],
    keyword_map: Dict[str, Any],
    outline_pack: Dict[str, Any],
    meta_pack: Dict[str, Any],
) -> str:
    topic = _clean_text(brief.get("seed_keyword") or brief.get("topic") or brief.get("central_entity"))
    primary = keyword_map.get("primary_keyword", {})
    internal = brief.get("internal_linking", {})
    outbound = _safe_list(internal.get("outbound_nodes")) if isinstance(internal, dict) else []
    persona = _clean_text(getattr(project, "target_customers", "")) if project else ""
    tone = _clean_text(getattr(project, "tone", "")) if project else ""

    lines = [f"# BRIEF: {topic}", ""]
    lines.extend(
        [
            "## 1. Basic Info",
            f"- Focus Keyword: {topic}",
            f"- Search Volume: {_format_metric_value(primary.get('search_volume'))} (tool-only mode)",
            f"- KD: {_format_metric_value(primary.get('keyword_difficulty'))} (tool-only mode)",
            f"- Search Intent: {serp.get('search_intent', 'Informational')}",
            f"- SERP Intent Mix: {serp.get('intent_mix_summary') or 'N/A'}",
            f"- Target Word Count: ~{outline_pack.get('target_word_count', 0)} words",
            f"- Page Type: {_infer_page_type(brief)}",
            f"- Metrics Note: {keyword_map.get('metrics_note', '')}",
            "",
            "## 2. SERP Context",
            f"- Dominant format: {serp.get('dominant_format', 'Mixed')}",
            f"- SERP source: {serp.get('serp_source') or 'N/A'} ({serp.get('source_confidence') or 'unknown'} confidence)",
            f"- Intent decision rationale: {serp.get('intent_rationale') or 'Use the dominant weighted SERP intent.'}",
            f"- SERP Features to target: {', '.join(serp.get('serp_features', [])) or 'Organic results only'}",
        ]
    )
    for idx, comp in enumerate(serp.get("top_competitors", []), start=1):
        lines.append(f"- Top {idx} competitor: {comp.get('url', '')}")

    lines.extend(
        [
            "",
            "## 3. Tone of Voice",
            f"- Target persona: {persona or 'General searcher researching the topic'}",
            f"- Tone: {tone or 'authoritative, concise, helpful'}",
            "- POV: third person / second person where useful",
            f"- Good sample sentence: {_good_sample_sentence(topic)}",
            f"- Bad sample sentence: {_bad_sample_sentence(topic)}",
            "",
            "## 4. Complete Outline",
            outline_pack.get("rendered_outline_markdown", ""),
            "",
            "## 5. Keyword Map",
            "| Section | Primary KW | Secondary | LSI |",
            "|---------|------------|-----------|-----|",
        ]
    )
    for row in keyword_map.get("table_rows", [])[:10]:
        lines.append(
            f"| {_pipe(row.get('section'))} | {_pipe(row.get('primary_keyword'))} | "
            f"{_pipe(row.get('secondary'))} | {_pipe(row.get('lsi'))} |"
        )

    lines.extend(
        [
            "",
            "## 6. Meta",
            f"- Title options: {' | '.join(meta_pack.get('meta_title_options', []))}",
            f"- Description options: {' | '.join(meta_pack.get('meta_description_options', []))}",
            f"- Schema @type: {meta_pack.get('schema_type', 'Article')}",
            "",
            "## 7. Internal Link Suggestions",
        ]
    )
    if outbound:
        for item in outbound[:5]:
            if not isinstance(item, dict):
                continue
            target = _clean_text(item.get("topic") or item.get("target_topic"))
            anchor = _clean_text(item.get("anchor") or item.get("anchor_text_suggestion"))
            lines.append(f"- Link to: {target or '[to be mapped]'} — suggested anchor: \"{anchor or target}\"")
    else:
        lines.append("- Link to: [to be mapped from topical map] — suggested anchor: use the closest semantic variant in the target cluster")

    lines.extend(
        [
            "",
            "## 8. External Sources (citations)",
            "- Numeric claims or standards in EAV rows should cite official standards, brand docs, or regulator sources.",
            f"- Entities to cite first: {', '.join(item['entity'] for item in entities[:3]) or topic}.",
            "",
            "## 9. Must-Have Elements",
            f"- [{'x' if primary.get('keyword') else ' '}] Primary keyword in H1",
            f"- [{'x' if outline_pack.get('intro_brief') else ' '}] Primary keyword in opening sentence",
            f"- [{'x' if len(serp.get('paa_questions', [])) >= 3 else ' '}] FAQ section with 5-7 questions from PAA",
            f"- [{'x' if outline_pack.get('conclusion_brief') else ' '}] CTA or next-step bridge at the end",
            f"- [{'x' if meta_pack.get('schema_skeletons') else ' '}] Schema markup with correct @type",
        ]
    )
    return "\n".join(lines).strip()


def _good_sample_sentence(topic: str) -> str:
    return f"{topic} should be explained immediately, then expanded with the specific attributes that change the reader's decision."


def _bad_sample_sentence(topic: str) -> str:
    return f"{topic} is an interesting topic and this section will provide useful information about many related aspects."


def _pipe(value: Any) -> str:
    return _clean_text(value).replace("|", "\\|")


def _render_appendix(payload: Dict[str, Any]) -> str:
    serp = payload.get("serp_analysis_summary", {})
    matrix = payload.get("heading_frequency_matrix", {})
    entities = payload.get("entity_map", [])
    keyword_map = payload.get("keyword_map", {})
    outline_pack = payload.get("outline_package", {})
    meta_pack = payload.get("meta_schema_package", {})
    writer_brief = _clean_text(payload.get("writer_briefing_markdown"))

    lines = ["## 7. Outline-Content Framework Pack", ""]
    lines.extend(
        [
            "### 7.1 SERP Analysis Summary",
            f"- Dominant Format: {serp.get('dominant_format', 'Mixed')}",
            f"- Search Intent: {serp.get('search_intent', 'Informational')}",
            f"- Intent Mix: {serp.get('intent_mix_summary') or 'N/A'}",
            f"- SERP Source: {serp.get('serp_source') or 'N/A'} ({serp.get('source_confidence') or 'unknown'} confidence)",
            f"- Intent Decision: {serp.get('intent_rationale') or 'Use dominant weighted SERP intent.'}",
            f"- SERP Features: {', '.join(serp.get('serp_features', [])) or 'Organic only'}",
            f"- Top 10 Competitors: {', '.join(item.get('url', '') for item in serp.get('top_competitors', [])[:10]) or 'N/A'}",
            f"- PAA Questions: {', '.join(serp.get('paa_questions', [])[:10]) or 'N/A'}",
            f"- Related Searches: {', '.join(serp.get('related_searches', [])[:10]) or 'N/A'}",
            "",
        ]
    )

    lines.append("### 7.2 Heading Frequency Matrix")
    competitor_urls = matrix.get("competitor_urls", [])
    if matrix.get("rows"):
        competitor_count = len(competitor_urls)
        if not competitor_count and matrix["rows"]:
            competitor_count = len(matrix["rows"][0].get("hits", []))
        if competitor_count > 0:
            header = "| H2 Topic | " + " | ".join(f"C{i+1}" for i in range(competitor_count)) + " | Frequency | Class |"
            divider = "|----------|" + "|".join(["----" for _ in range(competitor_count)]) + "|-----------|-------|"
        else:
            header = "| H2 Topic | Frequency | Class |"
            divider = "|----------|-----------|-------|"
        lines.extend([header, divider])
        for row in matrix["rows"]:
            hits = row.get("hits", [])
            if competitor_count > 0:
                hit_cells = ["Y" if hit else "" for hit in hits]
                lines.append(
                    f"| {_pipe(row.get('topic'))} | "
                    + " | ".join(hit_cells)
                    + f" | {_pipe(row.get('frequency'))} | {_pipe(row.get('classification'))} |"
                )
            else:
                lines.append(f"| {_pipe(row.get('topic'))} | {_pipe(row.get('frequency'))} | {_pipe(row.get('classification'))} |")
        if competitor_urls:
            lines.append("")
            for idx, url in enumerate(competitor_urls, start=1):
                lines.append(f"- C{idx}: {url}")
    else:
        lines.append("- No competitor heading matrix available.")
    if matrix.get("could_have"):
        lines.append(f"- Could-have differentiators: {', '.join(matrix.get('could_have', [])[:8])}")
    lines.append("")

    lines.append("### 7.3 Entity Map")
    if entities:
        lines.extend(
            [
                "| Entity | Type | Relevance | Suggested placement | Source |",
                "|--------|------|-----------|---------------------|--------|",
            ]
        )
        for item in entities[:10]:
            lines.append(
                f"| {_pipe(item.get('entity'))} | {_pipe(item.get('type'))} | {_pipe(item.get('relevance'))} | "
                f"{_pipe(item.get('suggested_placement'))} | {_pipe(item.get('source'))} |"
            )
    else:
        lines.append("- No entity mapping available.")
    lines.append("")

    lines.append("### 7.4 Keyword Map")
    lines.append(f"- Metrics note: {keyword_map.get('metrics_note', '')}")
    lines.extend(
        [
            "| Group | Keyword | Intent | Placement | Volume | KD | Source |",
            "|-------|---------|--------|-----------|--------|----|--------|",
        ]
    )
    primary = keyword_map.get("primary_keyword", {})
    if primary:
        lines.append(
            f"| Primary | {_pipe(primary.get('keyword'))} | {_pipe(primary.get('intent'))} | "
            f"{_pipe(primary.get('placement'))} | {_pipe(_format_metric_value(primary.get('search_volume')))} | "
            f"{_pipe(_format_metric_value(primary.get('keyword_difficulty')))} | {_pipe(_source_with_metrics(primary))} |"
        )
    for label, items in (
        ("Secondary", keyword_map.get("secondary_keywords", [])),
        ("Semantic", keyword_map.get("semantic_keywords", [])),
        ("Long-tail", keyword_map.get("long_tail_keywords", [])),
    ):
        for item in items[:6]:
            lines.append(
                f"| {label} | {_pipe(item.get('keyword'))} | {_pipe(item.get('intent'))} | "
                f"{_pipe(item.get('placement'))} | {_pipe(_format_metric_value(item.get('search_volume')))} | "
                f"{_pipe(_format_metric_value(item.get('keyword_difficulty')))} | {_pipe(_source_with_metrics(item))} |"
            )
    lines.append("")

    lines.extend(
        [
            "### 7.5 Outline Construction Summary",
            f"- Target Word Count: ~{outline_pack.get('target_word_count', 0)} words",
            f"- Estimated Word Count: ~{outline_pack.get('estimated_word_count', 0)} words",
            f"- Macro Ratio: {outline_pack.get('macro_ratio', 0)}%",
            "",
            outline_pack.get("rendered_outline_markdown", ""),
            "",
            "### 7.6 Meta & Schema",
            "- Meta Title options:",
        ]
    )
    for option in meta_pack.get("meta_title_options", []):
        lines.append(f"  - {option}")
    lines.append("- Meta Description options:")
    for option in meta_pack.get("meta_description_options", []):
        lines.append(f"  - {option}")
    for schema in meta_pack.get("schema_skeletons", []):
        lines.append("")
        lines.append(f"#### {schema.get('label')}")
        lines.append("```json")
        lines.append(json.dumps(schema.get("schema", {}), ensure_ascii=False, indent=2))
        lines.append("```")
    lines.append("")
    lines.append("### 7.7 Writer Briefing")
    lines.append(writer_brief or "Writer briefing unavailable.")
    lines.append("")
    return "\n".join(lines).strip()
