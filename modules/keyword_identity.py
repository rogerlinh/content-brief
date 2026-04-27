# -*- coding: utf-8 -*-
"""
modules/keyword_identity.py

Rule engine để phân loại quan hệ giữa 2 keyword:
- alias: biến thể ngôn ngữ của cùng intent
- same_root: cùng root/topic, nhưng chưa đủ điều kiện gom alias cứng
- sibling: cùng topical border nhưng khác intent, nên tách node/page
- reject: lệch topical border hoặc SERP không đồng thuận

Thiết kế này dùng cho:
- audit keyword mapping
- canonicalization trước khi build topical map
- kiểm tra nghi ngờ bằng SERP overlap
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import re
import unicodedata


INTENT_MODIFIER_GROUPS = {
    "definition": {
        "là gì", "la gi", "what is", "definition", "khái niệm", "dinh nghia",
    },
    "how_to": {
        "cách", "how to", "làm sao", "lam sao", "hướng dẫn", "quy trình",
    },
    "comparison": {
        "so sánh", "so sanh", "khác gì", "khac gi", "vs", "với", "voi",
    },
    "price": {
        "giá", "gia", "bảng giá", "bang gia", "chi phí", "chi phi", "bao nhiêu", "bao nhieu",
    },
    "risk": {
        "rủi ro", "rui ro", "an toàn", "an toan", "hợp pháp", "hop phap", "có nên", "co nen",
    },
    "navigational": {
        "login", "đăng nhập", "dang nhap", "website", "trang chủ", "trang chu", "liên hệ", "lien he",
    },
    "review": {
        "review", "đánh giá", "danh gia", "kinh nghiệm", "kinh nghiem", "feedback",
    },
}

DEFAULT_STOPWORDS = {
    "là", "la", "gì", "gi", "cái", "cai", "nào", "nao", "có", "co", "không", "khong",
    "và", "va", "cho", "trong", "của", "cua", "the", "and", "of", "to", "for", "with",
}


def load_topical_keywords(topical_map_csv: str) -> List[str]:
    """Load cột Keyword đầu tiên từ topical map CSV."""
    if not topical_map_csv or not os.path.exists(topical_map_csv):
        return []

    topics: List[str] = []
    try:
        with open(topical_map_csv, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            _ = next(reader, None)
            for row in reader:
                if row and row[0].strip():
                    topics.append(row[0].strip())
    except Exception:
        return []

    deduped: List[str] = []
    seen = set()
    for topic in topics:
        key = normalize_text(topic)
        if key and key not in seen:
            seen.add(key)
            deduped.append(topic)
    return deduped


def build_scope_terms(project) -> List[str]:
    """Tạo vocabulary scope từ source context của project."""
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
        if not field:
            continue
        for chunk in re.split(r"[,;/\n|]+", str(field)):
            cleaned = chunk.strip()
            if cleaned:
                terms.append(cleaned)

    topical_map_csv = getattr(project, "topical_map_csv", "") or ""
    terms.extend(load_topical_keywords(topical_map_csv))

    deduped: List[str] = []
    seen = set()
    for term in terms:
        key = normalize_text(term)
        if not key or len(key) < 3 or key in seen:
            continue
        seen.add(key)
        deduped.append(term)
    return deduped


@dataclass
class KeywordIdentityDecision:
    relation: str
    score: int
    query_a: str
    query_b: str
    modifier_a: str
    modifier_b: str
    root_a: str
    root_b: str
    top10_overlap: int = 0
    top3_overlap: int = 0
    shared_domains: int = 0
    lexical_similarity: float = 0.0
    reasons: List[str] = field(default_factory=list)

    @property
    def needs_serp_review(self) -> bool:
        return self.relation in {"same_root", "sibling"} and self.top10_overlap < 5


def normalize_text(text: str) -> str:
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


def _tokenize(text: str) -> List[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    return [t for t in normalized.split() if t and t not in DEFAULT_STOPWORDS]


def extract_intent_modifier(query: str) -> str:
    """
    Trả về nhóm intent modifier lớn nhất khớp với query.
    Nếu không khớp rõ, trả về 'generic'.
    """
    normalized = normalize_text(query)
    for group, tokens in INTENT_MODIFIER_GROUPS.items():
        if any(token in normalized for token in tokens):
            return group
    return "generic"


def _strip_modifier_tokens(query: str) -> str:
    normalized = normalize_text(query)
    for tokens in INTENT_MODIFIER_GROUPS.values():
        for token in tokens:
            normalized = normalized.replace(token, " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def extract_root_signature(query: str) -> str:
    """
    Tạo chữ ký root bằng cách bỏ intent modifiers và stopwords.
    Đây không phải canonical topic cuối cùng, chỉ là heuristic để so khớp.
    """
    stripped = _strip_modifier_tokens(query)
    tokens = [t for t in stripped.split() if t and t not in DEFAULT_STOPWORDS]
    return " ".join(tokens)


def lexical_similarity(query_a: str, query_b: str) -> float:
    tokens_a = set(_tokenize(query_a))
    tokens_b = set(_tokenize(query_b))
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower().strip()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def compare_serp_urls(urls_a: Sequence[str], urls_b: Sequence[str]) -> Dict[str, object]:
    """
    So sánh 2 tập URL SERP.
    """
    list_a = [u for u in (urls_a or []) if u]
    list_b = [u for u in (urls_b or []) if u]
    set_a = set(list_a[:10])
    set_b = set(list_b[:10])
    shared_urls = list(set_a & set_b)
    shared_top3 = len(set(list_a[:3]) & set(list_b[:3]))
    shared_domains = len({_domain_from_url(u) for u in shared_urls if _domain_from_url(u)})
    return {
        "top10_overlap": len(shared_urls),
        "top3_overlap": shared_top3,
        "shared_domains": shared_domains,
        "shared_urls": shared_urls,
    }


def _count_modifier_hits(query_a: str, query_b: str) -> Tuple[str, str]:
    return extract_intent_modifier(query_a), extract_intent_modifier(query_b)


def classify_keyword_relation(
    query_a: str,
    query_b: str,
    urls_a: Optional[Sequence[str]] = None,
    urls_b: Optional[Sequence[str]] = None,
    scope_terms: Optional[Sequence[str]] = None,
    blocked_terms: Optional[Sequence[str]] = None,
) -> KeywordIdentityDecision:
    """
    Phân loại quan hệ giữa 2 keyword.

    Rule ưu tiên:
    1. reject nếu lệch topical border hoặc contamination rõ
    2. alias khi cùng intent + SERP overlap mạnh
    3. same_root khi cùng root/entity nhưng chưa đủ điều kiện alias cứng
    4. sibling khi cùng topical border nhưng khác intent
    """
    qa = str(query_a or "").strip()
    qb = str(query_b or "").strip()

    modifier_a, modifier_b = _count_modifier_hits(qa, qb)
    root_a = extract_root_signature(qa)
    root_b = extract_root_signature(qb)
    lexical = lexical_similarity(qa, qb)
    root_similarity = lexical_similarity(root_a, root_b)
    serp = compare_serp_urls(urls_a or [], urls_b or [])
    top10_overlap = int(serp["top10_overlap"])
    top3_overlap = int(serp["top3_overlap"])
    shared_domains = int(serp["shared_domains"])

    reasons: List[str] = []
    score = 0

    if blocked_terms:
        norm_a = normalize_text(qa)
        norm_b = normalize_text(qb)
        hits = [
            term for term in blocked_terms
            if normalize_text(term) and (normalize_text(term) in norm_a or normalize_text(term) in norm_b)
        ]
        if hits:
            return KeywordIdentityDecision(
                relation="reject",
                score=0,
                query_a=qa,
                query_b=qb,
                modifier_a=modifier_a,
                modifier_b=modifier_b,
                root_a=root_a,
                root_b=root_b,
                top10_overlap=top10_overlap,
                top3_overlap=top3_overlap,
                shared_domains=shared_domains,
                lexical_similarity=lexical,
                reasons=[f"blocked_terms: {', '.join(hits)}"],
            )

    if scope_terms:
        norm_a = normalize_text(qa)
        norm_b = normalize_text(qb)
        scope_hits_a = any(normalize_text(t) in norm_a for t in scope_terms if normalize_text(t))
        scope_hits_b = any(normalize_text(t) in norm_b for t in scope_terms if normalize_text(t))
        if not scope_hits_a and not scope_hits_b:
            reasons.append("no_scope_match")
            return KeywordIdentityDecision(
                relation="reject",
                score=10,
                query_a=qa,
                query_b=qb,
                modifier_a=modifier_a,
                modifier_b=modifier_b,
                root_a=root_a,
                root_b=root_b,
                top10_overlap=top10_overlap,
                top3_overlap=top3_overlap,
                shared_domains=shared_domains,
                lexical_similarity=lexical,
                reasons=reasons,
            )

    same_modifier = modifier_a == modifier_b
    generic_definition_pair = {
        modifier_a, modifier_b
    } <= {"generic", "definition"}
    same_root = bool(root_a and root_b and root_a == root_b)
    root_close = root_similarity >= 0.7

    if same_modifier or generic_definition_pair:
        score += 25
        reasons.append(
            "generic_definition_pair" if generic_definition_pair else f"same_modifier:{modifier_a}"
        )
    else:
        score -= 10
        reasons.append(f"modifier_conflict:{modifier_a}|{modifier_b}")

    if same_root:
        score += 30
        reasons.append("same_root_exact")
    elif root_close:
        score += 18
        reasons.append(f"root_similarity:{root_similarity:.2f}")

    if top10_overlap >= 5:
        score += 30
        reasons.append(f"top10_overlap:{top10_overlap}")
    elif top10_overlap >= 3:
        score += 18
        reasons.append(f"top10_overlap:{top10_overlap}")
    elif top10_overlap >= 1:
        score += 8
        reasons.append(f"top10_overlap:{top10_overlap}")

    if top3_overlap >= 2:
        score += 15
        reasons.append(f"top3_overlap:{top3_overlap}")
    elif top3_overlap == 1:
        score += 7
        reasons.append("top3_overlap:1")

    if shared_domains >= 2:
        score += 10
        reasons.append(f"shared_domains:{shared_domains}")

    score += int(round(lexical * 10))

    # Classification gates
    if top10_overlap >= 5 and top3_overlap >= 2 and root_close and (same_modifier or generic_definition_pair):
        relation = "alias"
    elif top10_overlap >= 5 and same_root:
        relation = "same_root"
    elif top10_overlap >= 3 and root_close:
        relation = "sibling"
    elif top10_overlap >= 2 and same_modifier:
        relation = "same_root"
    elif score < 35:
        relation = "reject"
    else:
        relation = "sibling"

    # Safety override: modifier conflict + weak SERP agreement should never be alias
    if relation == "alias" and modifier_a != modifier_b and not generic_definition_pair and top10_overlap < 6:
        relation = "same_root"
        reasons.append("alias_demoted_to_same_root_due_to_modifier_conflict")

    score = max(0, min(100, score))

    return KeywordIdentityDecision(
        relation=relation,
        score=score,
        query_a=qa,
        query_b=qb,
        modifier_a=modifier_a,
        modifier_b=modifier_b,
        root_a=root_a,
        root_b=root_b,
        top10_overlap=top10_overlap,
        top3_overlap=top3_overlap,
        shared_domains=shared_domains,
        lexical_similarity=lexical,
        reasons=reasons,
    )


def classify_keywords_against_root(
    root_query: str,
    candidates: Sequence[str],
    serp_map: Optional[Dict[str, Sequence[str]]] = None,
    scope_terms: Optional[Sequence[str]] = None,
) -> List[KeywordIdentityDecision]:
    """
    So sánh một root với nhiều candidate keywords.
    serp_map: {"keyword": ["url1", "url2", ...]}
    """
    results: List[KeywordIdentityDecision] = []
    serp_map = serp_map or {}
    for candidate in candidates:
        decision = classify_keyword_relation(
            root_query,
            candidate,
            urls_a=serp_map.get(root_query, []),
            urls_b=serp_map.get(candidate, []),
            scope_terms=scope_terms,
        )
        results.append(decision)
    return results


def review_keyword_identity(
    query: str,
    project=None,
    current_urls: Optional[Sequence[str]] = None,
    search_fn=None,
    blocked_terms: Optional[Sequence[str]] = None,
    max_candidates: int = 8,
    min_lexical: float = 0.25,
) -> Dict[str, object]:
    """
    Review keyword identity against project topical map.

    search_fn: callable(keyword) -> serp_result dict with top_urls.
    """
    topic = str(query or "").strip()
    topical_map_csv = getattr(project, "topical_map_csv", "") if project else ""
    candidates = load_topical_keywords(topical_map_csv)
    scope_terms = build_scope_terms(project)

    current_urls = list(current_urls or [])
    scored = []
    for candidate in candidates:
        if normalize_text(candidate) == normalize_text(topic):
            continue
        base = classify_keyword_relation(
            topic,
            candidate,
            urls_a=current_urls,
            urls_b=[],
            scope_terms=scope_terms,
            blocked_terms=blocked_terms,
        )
        if base.lexical_similarity >= min_lexical or base.relation in {"same_root", "sibling"}:
            scored.append(base)

    # Keep only the most suspicious candidates
    scored.sort(key=lambda d: (d.score, d.lexical_similarity, d.top10_overlap, d.top3_overlap), reverse=True)
    reviewed = []
    best = None

    for decision in scored[:max_candidates]:
        candidate = decision.query_b
        candidate_urls = []
        if callable(search_fn):
            try:
                serp = search_fn(candidate)
                if isinstance(serp, dict):
                    candidate_urls = serp.get("top_urls", []) or serp.get("organic_results", [])
                    if candidate_urls and isinstance(candidate_urls[0], dict):
                        candidate_urls = [item.get("url", "") for item in candidate_urls if isinstance(item, dict)]
            except Exception:
                candidate_urls = []

        refined = classify_keyword_relation(
            topic,
            candidate,
            urls_a=current_urls,
            urls_b=candidate_urls,
            scope_terms=scope_terms,
            blocked_terms=blocked_terms,
        )
        reviewed.append(
            {
                "candidate": candidate,
                "relation": refined.relation,
                "score": refined.score,
                "top10_overlap": refined.top10_overlap,
                "top3_overlap": refined.top3_overlap,
                "lexical_similarity": refined.lexical_similarity,
                "modifier_a": refined.modifier_a,
                "modifier_b": refined.modifier_b,
                "root_a": refined.root_a,
                "root_b": refined.root_b,
                "reasons": refined.reasons,
            }
        )

        if best is None:
            best = refined
        else:
            best_rank = (0 if best.relation == "alias" else 1 if best.relation == "same_root" else 2 if best.relation == "sibling" else 3, -best.score)
            new_rank = (0 if refined.relation == "alias" else 1 if refined.relation == "same_root" else 2 if refined.relation == "sibling" else 3, -refined.score)
            if new_rank < best_rank:
                best = refined

    if best is None:
        best = classify_keyword_relation(topic, topic, urls_a=current_urls, urls_b=current_urls, scope_terms=scope_terms, blocked_terms=blocked_terms)

    semantic_candidates = [
        item["candidate"]
        for item in reviewed
        if item.get("relation") in {"alias", "same_root", "sibling"} and item.get("candidate")
    ]
    semantic_expansion_keywords: List[str] = []
    seen_semantic = set()
    for candidate in semantic_candidates:
        key = normalize_text(candidate)
        if not key or key in seen_semantic or key == normalize_text(topic):
            continue
        seen_semantic.add(key)
        semantic_expansion_keywords.append(candidate)

    semantic_anchor = best.query_b if best.query_b and best.query_b != topic else (best.root_b or best.root_a or topic)
    cluster_mode = "seed_expansion" if best.relation in {"sibling", "reject"} or best.top10_overlap < 5 else "cluster_anchor"

    return {
        "query": topic,
        "relation": best.relation,
        "score": best.score,
        "canonical_root": semantic_anchor,
        "semantic_anchor": semantic_anchor,
        "cluster_mode": cluster_mode,
        "best_match": best.query_b if best.query_b != topic else topic,
        "modifier": best.modifier_b if best.query_b != topic else best.modifier_a,
        "top10_overlap": best.top10_overlap,
        "top3_overlap": best.top3_overlap,
        "lexical_similarity": best.lexical_similarity,
        "needs_serp_review": any(item["relation"] in {"same_root", "sibling"} and item["top10_overlap"] < 5 for item in reviewed),
        "reviewed_candidates": reviewed,
        "semantic_expansion_keywords": semantic_expansion_keywords[:8],
        "scope_terms": scope_terms[:12],
        "topical_map_csv": topical_map_csv,
    }
