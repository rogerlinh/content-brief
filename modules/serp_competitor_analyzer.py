# -*- coding: utf-8 -*-
"""
serp_competitor_analyzer.py - Phân tích SERP Google và đối thủ cạnh tranh.

Sử dụng Playwright để:
1. Scrape Google SERP: organic results, PAA, Things to Know, Related Searches
2. Truy cập top 10 đối thủ: heading structure, n-grams, Information Gain

Usage:
    from modules.serp_competitor_analyzer import analyze_serp, analyze_competitors

    serp_data = analyze_serp("keyword chính là gì")
    competitor_data = analyze_competitors(serp_data["top_urls"], "keyword chính là gì")
"""

import asyncio
import logging
import math
import os
import re
import requests
import unicodedata
from urllib.parse import parse_qs, urlparse, unquote
from collections import Counter
from typing import Any, Dict, List, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────
GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}&hl=vi&gl=vn"
SERPER_API_URL = "https://google.serper.dev/search"
MAX_COMPETITORS = 10
REQUEST_DELAY_SECONDS = 3
PAGE_TIMEOUT_MS = 30000
HEADLESS = True

# Import config module để đọc key động, tránh stale import khi UI cập nhật sau khi module đã load
try:
    import config as _config
except ImportError:
    _config = None


def _get_serper_api_key() -> str:
    """Read latest SERPER_API_KEY from env/config at call time."""
    env_key = os.environ.get("SERPER_API_KEY", "").strip()
    if env_key:
        return env_key
    if _config is not None:
        return getattr(_config, "SERPER_API_KEY", "").strip()
    return ""

# Stopwords tiếng Việt phổ biến (dùng cho n-gram filtering)
VIETNAMESE_STOPWORDS = {
    "là", "và", "của", "có", "được", "các", "cho", "này", "với", "từ",
    "không", "đến", "trong", "một", "những", "khi", "để", "theo", "hay",
    "hoặc", "về", "như", "đã", "sẽ", "bị", "cũng", "nhất", "rất", "tại",
    "nên", "làm", "ra", "nào", "lên", "còn", "sau", "trước", "vào",
    "bằng", "thì", "mà", "đó", "nhiều", "do", "qua", "giữa",
    "nếu", "vì", "hơn", "dù", "luôn", "đều", "thường", "gì",
    "the", "and", "of", "is", "in", "to", "for", "on", "with", "that",
}

CONTENT_ROOT_SELECTORS = [
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".entry-content",
    ".article-content",
    ".content",
    "#content",
    ".post-body",
    ".article-body",
    ".single-content",
]

NOISY_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    ".sidebar",
    ".navigation",
    ".menu",
    ".comment",
    ".comments",
    ".comment-list",
    ".related-posts",
    ".related",
    ".advertisement",
    ".ads",
    ".ad-container",
    ".breadcrumb",
    ".breadcrumbs",
    ".social-share",
    ".share-buttons",
    ".toc",
    ".table-of-contents",
    ".newsletter",
    ".popup",
    ".banner",
]


def _normalize_text_block(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


SERP_TOPIC_STOPWORDS = {
    "la", "gi", "the", "nao", "bao", "nhieu", "cho", "voi", "cua", "va",
    "tren", "tai", "tu", "nhung", "cac", "mot", "co", "khong", "nen",
    "lam", "sao", "huong", "dan", "so", "sanh", "vs",
}

INTENT_BUCKETS = (
    "informational",
    "commercial investigation",
    "transactional",
    "navigational",
)

INTENT_QUERY_MARKERS = {
    "informational": (
        "la gi", "khai niem", "dinh nghia", "tong quan", "huong dan",
        "cach", "tai sao", "vi sao", "kien thuc", "giai dap",
    ),
    "commercial investigation": (
        "so sanh", "vs", "khac nhau", "phan biet", "review", "danh gia",
        "top ", "tot nhat", "nen chon", "gia ", "bao nhieu", "uu diem", "nhuoc diem",
    ),
    "transactional": (
        "mua", "dat mua", "mua ngay", "dang ky", "bao gia", "bang gia",
        "lien he", "san pham", "dich vu", "mo tai khoan", "dat lich",
    ),
    "navigational": (
        "dang nhap", "login", "trang chu", "website", "official", "chinh thuc",
        "contact", "docs", "tai lieu",
    ),
}

INTENT_RESULT_MARKERS = {
    "informational": (
        "la gi", "khai niem", "dinh nghia", "tong quan", "huong dan",
        "cach", "tim hieu", "kien thuc", "giai dap", "overview", "guide",
    ),
    "commercial investigation": (
        "so sanh", "vs", "khac nhau", "phan biet", "review", "danh gia",
        "top ", "tot nhat", "nen chon", "uu diem", "nhuoc diem", "benchmark",
        "bang xep hang", "co nen",
    ),
    "transactional": (
        "mua", "dat mua", "mua ngay", "dat hang", "dang ky", "bao gia",
        "bang gia", "lien he", "san pham", "dich vu", "khuyen mai", "order",
        "pricing", "price", "quote",
    ),
    "navigational": (
        "dang nhap", "login", "sign in", "trang chu", "homepage", "contact",
        "lien he", "chinh thuc", "official site", "official website",
    ),
}

COMPARISON_MARKERS = ("so sanh", "vs", "khac nhau", "phan biet", "nen chon")
REVIEW_MARKERS = ("review", "danh gia", "tot nhat", "top ", "nen mua")
PRICING_MARKERS = ("gia ", "bao gia", "bang gia", "price", "pricing", "chi phi")
TRANSACTIONAL_URL_MARKERS = (
    "/product", "/san-pham", "/category", "/danh-muc", "/pricing",
    "/bao-gia", "/bang-gia", "/service", "/dich-vu", "/contact", "/lien-he",
)
NAVIGATIONAL_URL_MARKERS = (
    "/login", "/dang-nhap", "/trang-chu", "/home", "/contact", "/lien-he",
    "/about", "/gioi-thieu", "/docs", "/tai-lieu",
)
DOMAIN_STOPWORDS = {"www", "com", "vn", "net", "org", "info", "co", "app", "io"}


def _normalize_topic_text(text: str) -> str:
    raw = str(text or "").lower().strip()
    raw = unquote(raw)
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^0-9a-zA-Z\s]", " ", raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _topic_terms(text: str) -> List[str]:
    norm = _normalize_topic_text(text)
    tokens = []
    for token in norm.split():
        clean = token.strip()
        if len(clean) < 3:
            continue
        if clean in SERP_TOPIC_STOPWORDS:
            continue
        tokens.append(clean)
    deduped: List[str] = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _topic_protected_phrases(topic: str) -> List[str]:
    terms = _topic_terms(topic)
    phrases: List[str] = []
    if len(terms) >= 2:
        phrases.append(" ".join(terms[:2]))
    if len(terms) >= 3:
        phrases.append(" ".join(terms[:3]))
    return [phrase for phrase in phrases if phrase]


def _serp_result_matches_topic(result: Dict, topic: str) -> bool:
    if not isinstance(result, dict):
        return False
    terms = _topic_terms(topic)
    if not terms:
        return True

    haystack = " ".join([
        str(result.get("title", "")),
        str(result.get("snippet", "")),
        str(result.get("url", "")),
    ])
    norm = _normalize_topic_text(haystack)
    if not norm:
        return False

    haystack_tokens = set(norm.split())
    overlap = sum(1 for term in terms if term in haystack_tokens)
    overlap_ratio = overlap / max(1, len(terms))
    protected_hits = sum(1 for phrase in _topic_protected_phrases(topic) if phrase in norm)

    if protected_hits >= 1 and overlap_ratio >= 0.4:
        return True
    if len(terms) <= 2 and overlap_ratio >= 0.5:
        return True
    if len(terms) >= 3 and overlap_ratio >= 0.6:
        return True
    return False


def _filter_serp_results_by_topic(organic_results: List[Dict], topic: str) -> List[Dict]:
    if not organic_results:
        return organic_results
    filtered = [item for item in organic_results if _serp_result_matches_topic(item, topic)]
    min_keep = 2 if len(organic_results) >= 3 else 1
    if len(filtered) >= min_keep and (len(filtered) / max(1, len(organic_results))) >= 0.4:
        removed = len(organic_results) - len(filtered)
        if removed > 0:
            logger.info("  [SERP-PURITY] Filtered %d off-topic organic results for '%s'.", removed, topic)
        return filtered
    return organic_results


def _remove_noisy_elements(soup: BeautifulSoup) -> None:
    for selector in NOISY_SELECTORS:
        try:
            for node in soup.select(selector):
                node.decompose()
        except Exception:
            continue


def _select_best_content_root(soup: BeautifulSoup):
    best_root = None
    best_score = 0
    for selector in CONTENT_ROOT_SELECTORS:
        try:
            candidates = soup.select(selector)
        except Exception:
            continue
        for candidate in candidates:
            text = _normalize_text_block(candidate.get_text(" ", strip=True))
            word_count = len(text.split())
            if word_count < 80:
                continue
            score = word_count
            score += len(candidate.find_all(["h1", "h2", "h3"])) * 10
            score += len(candidate.find_all(["p", "li"])) * 2
            if score > best_score:
                best_root = candidate
                best_score = score
    return best_root or soup.body or soup


def _extract_text_blocks(root, limit: int = 160) -> List[str]:
    blocks = []
    seen = set()
    for tag in root.find_all(["p", "li", "blockquote", "dd", "td", "th"]):
        text = _normalize_text_block(tag.get_text(" ", strip=True))
        if not text:
            continue
        wc = len(text.split())
        if wc < 6 or wc > 80:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        blocks.append(text)
        if len(blocks) >= limit:
            break
    return blocks


def _extract_headings_from_root(root) -> List[Dict]:
    headings = []
    seen = set()
    for tag in root.find_all(["h1", "h2", "h3"]):
        text = _normalize_text_block(tag.get_text(" ", strip=True))
        if not text:
            continue
        key = (tag.name.upper(), text.lower())
        if key in seen:
            continue
        seen.add(key)
        headings.append({
            "level": tag.name.upper(),
            "text": text,
        })
    return headings


def _extract_clean_competitor_content(html: str) -> Tuple[List[Dict], str, List[str]]:
    soup = BeautifulSoup(html, "html.parser")
    _remove_noisy_elements(soup)
    root = _select_best_content_root(soup)
    headings = _extract_headings_from_root(root)
    text_blocks = _extract_text_blocks(root)

    if text_blocks:
        body_text = " ".join(text_blocks)
    else:
        body_text = _normalize_text_block(root.get_text(" ", strip=True))

    if len(body_text.split()) < 80 and root is not (soup.body or soup):
        fallback_root = soup.body or soup
        fallback_blocks = _extract_text_blocks(fallback_root)
        fallback_text = (
            " ".join(fallback_blocks)
            if fallback_blocks
            else _normalize_text_block(fallback_root.get_text(" ", strip=True))
        )
        if len(fallback_text.split()) > len(body_text.split()):
            if not headings:
                headings = _extract_headings_from_root(fallback_root)
            if fallback_blocks:
                text_blocks = fallback_blocks
            body_text = fallback_text

    return headings, body_text, text_blocks


# ══════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════

def analyze_serp(topic: str, headless: bool = HEADLESS) -> Dict:
    """
    Phân tích trang kết quả tìm kiếm Google (SERP) cho một chủ đề.

    Args:
        topic: Chủ đề cần tìm kiếm.
        headless: Chạy browser ẩn (True) hoặc hiện (False).

    Returns:
        Dict chứa:
        - organic_results: List[dict] (title, url, snippet)
        - people_also_ask: List[str]
        - things_to_know: List[str]
        - related_searches: List[str]
        - top_urls: List[str] (top 10 URLs cho competitor analysis)
        - serp_entities: Dict (primary, secondary entities)
        - serp_attributes: List[str]
        - topic_clusters: List[str]
        - dominant_intent: str
        - featured_snippet: Dict
        - knowledge_panel: Dict
        - serp_features: List[str]
        - result_format_counts: Dict[str, int]
        - dominant_format: str
        - serp_source: str
        - intent_distribution: Dict[str, Dict]
        - intent_decision: Dict
        - result_intents: List[Dict]
    """
    logger.info("  [SERP] Bắt đầu phân tích SERP cho: '%s'", topic)
    raw_serp = asyncio.run(_scrape_google_serp(topic, headless))
    raw_serp["organic_results"] = _filter_serp_results_by_topic(raw_serp.get("organic_results", []), topic)

    # Phân tích dữ liệu từ SERP
    entities = _extract_entities_from_serp(raw_serp, topic)
    attributes = _extract_attributes_from_serp(raw_serp)
    clusters = _extract_topic_clusters(raw_serp)
    intent_profile = _analyze_serp_intent_mix(raw_serp, topic=topic)
    legacy_intent = str(intent_profile.get("selected_intent_legacy", "")).strip()
    result_format_counts = _count_serp_result_formats(raw_serp.get("organic_results", []))
    dominant_format = _dominant_serp_format(raw_serp.get("organic_results", []))

    # Lấy top URLs để crawl sâu đối thủ. Intent mix vẫn đọc trên toàn bộ top organic results.
    top_urls = _filter_competitor_urls(raw_serp.get("organic_results", []))

    result = {
        "organic_results": raw_serp.get("organic_results", []),
        "people_also_ask": raw_serp.get("people_also_ask", []),
        "things_to_know": raw_serp.get("things_to_know", []),
        "related_searches": raw_serp.get("related_searches", []),
        "top_urls": top_urls[:MAX_COMPETITORS],
        "serp_entities": entities,
        "serp_attributes": attributes,
        "topic_clusters": clusters,
        "dominant_intent": legacy_intent,
        "featured_snippet": raw_serp.get("featured_snippet", {}),
        "knowledge_panel": raw_serp.get("knowledge_panel", {}),
        "serp_features": raw_serp.get("serp_features", []),
        "result_format_counts": result_format_counts,
        "dominant_format": dominant_format,
        "serp_source": raw_serp.get("serp_source", ""),
        "intent_distribution": intent_profile.get("distribution", {}),
        "intent_decision": {
            "selected_intent": intent_profile.get("selected_intent", "informational"),
            "selected_intent_legacy": legacy_intent,
            "secondary_intent": intent_profile.get("secondary_intent", ""),
            "dominance_share": intent_profile.get("dominance_share", 0.0),
            "lead_margin": intent_profile.get("lead_margin", 0.0),
            "is_mixed": intent_profile.get("is_mixed", False),
            "source": intent_profile.get("source", raw_serp.get("serp_source", "")),
            "source_confidence": intent_profile.get("source_confidence", "medium"),
            "rationale": intent_profile.get("rationale", ""),
        },
        "result_intents": intent_profile.get("result_labels", []),
    }

    logger.info("  [SERP] Hoàn tất: %d results, %d PAA, %d competitors",
                len(result["organic_results"]),
                len(result["people_also_ask"]),
                len(result["top_urls"]))
    return result


def analyze_competitors(
    urls: List[str],
    topic: str,
    headless: bool = HEADLESS,
) -> Dict:
    """
    Phân tích top đối thủ cạnh tranh từ SERP.

    Args:
        urls: Danh sách URLs đối thủ (tối đa 10).
        topic: Chủ đề gốc (để tính Information Gain).
        headless: Chạy browser ẩn (True) hoặc hiện (False).

    Returns:
        Dict chứa:
        - competitors: List[dict] — dữ liệu từng đối thủ
        - common_headings: List[str] — heading patterns lặp lại
        - ngrams_2: List[tuple] — top 2-grams phổ biến
        - ngrams_3: List[tuple] — top 3-grams phổ biến
        - information_gain: Dict — khoảng trống nội dung
        - heading_frequency_matrix: Dict — tần suất H2 theo từng đối thủ
    """
    logger.info("  [COMPETITOR] Bắt đầu phân tích %d đối thủ...", len(urls))

    competitors_data = asyncio.run(_scrape_competitors(urls, headless))
    enriched_competitors = []
    for index, competitor in enumerate(competitors_data, start=1):
        row = dict(competitor or {})
        row["serp_position"] = int(row.get("serp_position") or index)
        content_intent = _classify_competitor_content_intent(row, topic=topic)
        row["content_intent"] = content_intent.get("intent", "informational")
        row["content_intent_subtype"] = content_intent.get("subtype", "")
        row["content_intent_confidence"] = content_intent.get("confidence", 0.0)
        row["content_intent_scores"] = content_intent.get("scores", {})
        row["content_intent_reasons"] = content_intent.get("reasons", [])
        row["content_intent_format"] = content_intent.get("format", "")
        archetype = _classify_competitor_content_archetype(row, topic=topic)
        row["content_archetype"] = archetype.get("archetype", "explainer")
        row["content_archetype_confidence"] = archetype.get("confidence", 0.0)
        row["content_archetype_scores"] = archetype.get("scores", {})
        row["content_archetype_reasons"] = archetype.get("reasons", [])
        enriched_competitors.append(row)
    competitors_data = enriched_competitors

    # Tổng hợp phân tích cross-competitor
    common_headings = _find_common_headings(competitors_data)
    ngrams_2 = _compute_cross_ngrams(competitors_data, n=2)
    ngrams_3 = _compute_cross_ngrams(competitors_data, n=3)
    info_gain = _compute_information_gain(competitors_data, topic)
    heading_frequency_matrix = _build_heading_frequency_matrix(competitors_data)
    intent_profile = _analyze_competitor_intent_mix(competitors_data, topic=topic)
    archetype_profile = _analyze_competitor_archetype_mix(competitors_data)

    result = {
        "competitors": competitors_data,
        "common_headings": common_headings,
        "ngrams_2": ngrams_2,
        "ngrams_3": ngrams_3,
        "information_gain": info_gain,
        "heading_frequency_matrix": heading_frequency_matrix,
        "intent_distribution": intent_profile.get("distribution", {}),
        "intent_decision": {
            "selected_intent": intent_profile.get("selected_intent", "informational"),
            "secondary_intent": intent_profile.get("secondary_intent", ""),
            "dominance_share": intent_profile.get("dominance_share", 0.0),
            "lead_margin": intent_profile.get("lead_margin", 0.0),
            "is_mixed": intent_profile.get("is_mixed", False),
            "source": intent_profile.get("source", "competitor_full_body"),
            "source_confidence": intent_profile.get("source_confidence", "medium"),
            "rationale": intent_profile.get("rationale", ""),
        },
        "content_intents": intent_profile.get("result_labels", []),
        "content_archetypes": archetype_profile.get("result_labels", []),
        "archetype_summary": {
            "selected_archetype": archetype_profile.get("selected_archetype", "explainer"),
            "top_archetypes": archetype_profile.get("top_archetypes", []),
            "rationale": archetype_profile.get("rationale", ""),
        },
    }

    logger.info("  [COMPETITOR] Hoàn tất: %d đối thủ, %d common headings, "
                "%d info gaps",
                len(competitors_data), len(common_headings),
                len(info_gain.get("content_gaps", [])))
    return result


# ══════════════════════════════════════════════
#  ASYNC SCRAPING (Playwright)
# ══════════════════════════════════════════════

async def _scrape_google_serp(topic: str, headless: bool) -> Dict:
    """
    Lấy dữ liệu SERP từ Serper.dev API (thay thế Playwright).

    Serper.dev trả JSON có sẵn: organic, peopleAlsoAsk, relatedSearches.
    Không cần browser → không bị Google CAPTCHA.

    Returns:
        Raw SERP data dict.
    """
    serper_api_key = _get_serper_api_key()
    globals()["SERPER_API_KEY"] = serper_api_key
    if not serper_api_key:
        logger.warning("  [SERP] SERPER_API_KEY not configured. Using Google HTML fallback.")
        return await _scrape_google_serp_fallback(topic)

    if not SERPER_API_KEY:
        logger.error("  [SERP] SERPER_API_KEY chưa được cấu hình! Kiểm tra config.py")
        return {
            "organic_results": [],
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": [],
            "featured_snippet": {},
            "knowledge_panel": {},
            "serp_features": [],
            "serp_source": "serper_unavailable",
        }

    logger.info("  [SERP] Gọi Serper.dev API cho: '%s' (key=%s...)", topic, SERPER_API_KEY[:8] if SERPER_API_KEY else "(empty)")

    # Cấu trúc rỗng mặc định – trả về nếu bất kỳ lỗi nào xảy ra
    EMPTY_SERP = await _scrape_google_serp_fallback(topic)

    data = {}
    try:
        response = requests.post(
            SERPER_API_URL,
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "q": topic,
                "gl": "vn",
                "hl": "vi",
                "num": 10,
            },
            timeout=15,
        )
        response.raise_for_status()

        # ── Bước 1: Cố gắng parse JSON ──
        try:
            data = response.json()
        except Exception:
            # Nếu .json() lỗi, lấy text thô để debug
            raw_text = response.text[:500] if response.text else "(empty)"
            logger.error("  [SERP] ⚠️ API ERROR RAW (json parse fail): %s", raw_text)
            return EMPTY_SERP

        # ── Bước 2: Kiểm tra kiểu dữ liệu ──
        if isinstance(data, str):
            logger.warning("  [SERP] ⚠️ API trả về STRING thay vì Dict: %s", data[:300])
            try:
                import json as _json
                data = _json.loads(data)
            except Exception:
                logger.error("  [SERP] Không thể parse string thành Dict. Bỏ qua.")
                return EMPTY_SERP

        if not isinstance(data, dict):
            logger.error("  [SERP] Data trả về không phải Dict. Type=%s, Value=%s",
                         type(data).__name__, str(data)[:300])
            return EMPTY_SERP

    except requests.exceptions.RequestException as e:
        logger.error("  [SERP] Lỗi gọi Serper.dev API: %s", str(e))
        return EMPTY_SERP
    except Exception as e:
        # Bắt MỌI lỗi còn lại – KHÔNG BAO GIỜ CRASH
        logger.error("  [SERP] Lỗi không xác định khi gọi API: %s", str(e))
        return EMPTY_SERP

    # ── Parse organic results ──
    organic = []
    for i, item in enumerate(data.get("organic", [])[:10], 1):
        organic.append({
            "position": i,
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })

    # ── Parse People Also Ask ──
    paa = []
    for item in data.get("peopleAlsoAsk", []):
        q = item.get("question", "")
        if q:
            paa.append(q)

    # ── Parse Related Searches ──
    related = []
    for item in data.get("relatedSearches", []):
        q = item.get("query", "")
        if q:
            related.append(q)

    # ── Parse Knowledge Graph (→ Things to Know) ──
    things = []
    kg = data.get("knowledgeGraph", {})
    if kg:
        # Trích xuất description từ Knowledge Graph
        desc = kg.get("description", "")
        if desc and len(desc) > 10:
            things.append(desc)
        # Trích xuất attributes
        for key, val in kg.get("attributes", {}).items():
            things.append(f"{key}: {val}")

    featured_snippet = _extract_featured_snippet(data)
    knowledge_panel = _extract_knowledge_panel(kg)
    serp_features = _detect_serp_features(data, organic)

    logger.info("  [SERP] Serper.dev → %d organic, %d PAA, %d related, %d TTK",
                len(organic), len(paa), len(related), len(things))

    return {
        "organic_results": organic,
        "people_also_ask": paa,
        "things_to_know": things,
        "related_searches": related,
        "featured_snippet": featured_snippet,
        "knowledge_panel": knowledge_panel,
        "serp_features": serp_features,
        "serp_source": "serper_google",
    }


async def _scrape_google_serp_fallback(topic: str) -> Dict:
    """
    Best-effort Google HTML fallback when Serper is unavailable.

    The goal is not perfect parity with Serper, only enough organic result data
    to keep downstream competitor/context builders from collapsing to empty.
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(
            GOOGLE_SEARCH_URL.format(query=requests.utils.quote(topic)),
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        organic = []
        seen_urls = set()
        for h3 in soup.select("#rso h3"):
            title = h3.get_text(" ", strip=True)
            if not title:
                continue
            anchor = h3.find_parent("a")
            if not anchor:
                continue
            url = anchor.get("href", "")
            if not url or "google.com/search" in url or url in seen_urls:
                continue
            seen_urls.add(url)

            snippet = ""
            container = h3.parent
            while container and not snippet:
                texts = [
                    t.get_text(" ", strip=True)
                    for t in container.find_all(["span", "div"], recursive=True)
                ]
                texts = [t for t in texts if t and t != title and len(t) > 50]
                if texts:
                    snippet = texts[0][:300]
                    break
                container = container.parent

            organic.append({
                "position": len(organic) + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
            })
            if len(organic) >= 10:
                break

        related = []
        for anchor in soup.select("#botstuff a, a.ngTNl"):
            text = anchor.get_text(" ", strip=True)
            if text and 2 < len(text) < 100:
                related.append(text)
        related = list(dict.fromkeys(related))[:8]

        logger.info(
            "  [SERP] Google HTML fallback -> %d organic, %d related",
            len(organic),
            len(related),
        )
        if organic:
            return {
                "organic_results": organic,
                "people_also_ask": [],
                "things_to_know": [],
                "related_searches": related,
                "featured_snippet": {},
                "knowledge_panel": {},
                "serp_features": [],
                "serp_source": "google_html",
            }

        logger.warning("  [SERP] Google HTML fallback returned no organic results. Trying DuckDuckGo.")
        ddg_serp = await _scrape_duckduckgo_serp_fallback(topic)
        if ddg_serp.get("organic_results"):
            return ddg_serp
        return {
            "organic_results": organic,
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": related,
            "featured_snippet": {},
            "knowledge_panel": {},
            "serp_features": [],
            "serp_source": "google_html_empty",
        }
    except Exception as exc:
        logger.warning("  [SERP] Google HTML fallback failed: %s", exc)
        ddg_serp = await _scrape_duckduckgo_serp_fallback(topic)
        if ddg_serp.get("organic_results"):
            return ddg_serp
        return {
            "organic_results": [],
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": [],
            "featured_snippet": {},
            "knowledge_panel": {},
            "serp_features": [],
            "serp_source": "google_html_failed",
        }


async def _scrape_duckduckgo_serp_fallback(topic: str) -> Dict:
    """Best-effort DuckDuckGo HTML fallback when Google HTML fails or is empty."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": topic},
            headers=headers,
            timeout=15,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        organic = []
        seen_urls = set()
        for anchor in soup.select("a.result__a, a[data-testid='result-title-a']"):
            title = anchor.get_text(" ", strip=True)
            if not title:
                continue
            href = anchor.get("href", "")
            if not href:
                continue
            url = href
            parsed = urlparse(href)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                query = parse_qs(parsed.query)
                url = query.get("uddg", [href])[0]
                url = unquote(url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            snippet = ""
            container = anchor.find_parent("div", class_="result")
            if container:
                snippet_el = container.select_one(".result__snippet")
                if snippet_el:
                    snippet = snippet_el.get_text(" ", strip=True)[:300]

            organic.append({
                "position": len(organic) + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
            })
            if len(organic) >= 10:
                break

        related = []
        for anchor in soup.select(".related-searches a, .related-searches__item a"):
            text = anchor.get_text(" ", strip=True)
            if text and 2 < len(text) < 100:
                related.append(text)
        related = list(dict.fromkeys(related))[:8]

        logger.info(
            "  [SERP] DuckDuckGo HTML fallback -> %d organic, %d related",
            len(organic),
            len(related),
        )
        return {
            "organic_results": organic,
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": related,
            "featured_snippet": {},
            "knowledge_panel": {},
            "serp_features": [],
            "serp_source": "duckduckgo_html",
        }
    except Exception as exc:
        logger.warning("  [SERP] DuckDuckGo HTML fallback failed: %s", exc)
        return {
            "organic_results": [],
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": [],
            "featured_snippet": {},
            "knowledge_panel": {},
            "serp_features": [],
            "serp_source": "duckduckgo_failed",
        }


# Giữ lại cho trường hợp cần xử lý consent khi scrape competitor pages
async def _handle_google_consent(page) -> None:
    """Xử lý dialog đồng ý cookie của Google nếu xuất hiện."""
    try:
        consent_btn = page.locator(
            'button:has-text("Chấp nhận tất cả"), '
            'button:has-text("Accept all"), '
            'button:has-text("Đồng ý"), '
            'button[id="L2AGLb"]'
        )
        if await consent_btn.count() > 0:
            await consent_btn.first.click()
            await page.wait_for_timeout(1000)
            logger.info("  [SERP] Đã xử lý consent dialog")
    except Exception:
        pass  # Bỏ qua nếu không có consent dialog


async def _extract_organic_results(page) -> List[Dict]:
    """Trích xuất kết quả tìm kiếm organic (top 10)."""
    results = []
    try:
        # Google VN 2026: class .g đã bị loại bỏ.
        # Strategy: Tìm tất cả h3 trong #rso, rồi traverse lên parent để lấy URL.
        organic_items = await page.evaluate("""
            () => {
                const results = [];
                // Tìm tất cả h3 trong vùng search results
                const headings = document.querySelectorAll('#rso h3');
                headings.forEach((h3, idx) => {
                    if (idx >= 10) return;
                    const title = h3.textContent.trim();
                    if (!title) return;

                    // Traverse lên để tìm link cha chứa href
                    let link = h3.closest('a');
                    if (!link) {
                        // Thử tìm trong parent
                        let parent = h3.parentElement;
                        for (let i = 0; i < 5 && parent; i++) {
                            link = parent.querySelector('a[href^="http"]');
                            if (link) break;
                            parent = parent.parentElement;
                        }
                    }
                    const url = link ? link.href : '';
                    if (!url || url.includes('google.com/search')) return;

                    // Tìm snippet (đoạn mô tả) gần h3
                    let snippet = '';
                    let container = h3.parentElement;
                    for (let i = 0; i < 5 && container; i++) {
                        const spans = container.querySelectorAll('span, div');
                        for (const span of spans) {
                            const txt = span.textContent.trim();
                            if (txt.length > 50 && txt !== title && !txt.includes(url)) {
                                snippet = txt.substring(0, 300);
                                break;
                            }
                        }
                        if (snippet) break;
                        container = container.parentElement;
                    }

                    results.push({
                        position: results.length + 1,
                        title: title,
                        url: url,
                        snippet: snippet
                    });
                });
                return results;
            }
        """)

        results = organic_items or []

    except Exception as e:
        logger.warning("  [SERP] Lỗi trích xuất organic results: %s", str(e))

    logger.info("  [SERP] Tìm thấy %d organic results", len(results))
    return results


async def _extract_people_also_ask(page) -> List[str]:
    """Trích xuất câu hỏi 'Mọi người cũng hỏi' (People Also Ask)."""
    questions = []
    try:
        # Google VN 2026: PAA questions nằm trong div[data-q] hoặc
        # các element có role="heading" trong container PAA
        paa_data = await page.evaluate("""
            () => {
                const qs = [];
                // Method 1: data-q attribute (chứa text câu hỏi)
                document.querySelectorAll('div[data-q]').forEach(el => {
                    const q = el.getAttribute('data-q');
                    if (q && q.trim()) qs.push(q.trim());
                });
                // Method 2: Fallback - role="heading" trong PAA container
                if (qs.length === 0) {
                    document.querySelectorAll('[data-sgrd] [role="heading"], .related-question-pair [role="heading"]').forEach(el => {
                        const t = el.textContent.trim();
                        if (t && t.length > 5) qs.push(t);
                    });
                }
                return qs;
            }
        """)

        questions = paa_data or []

    except Exception as e:
        logger.warning("  [SERP] Lỗi trích xuất PAA: %s", str(e))

    logger.info("  [SERP] Tìm thấy %d PAA questions", len(questions))
    return questions


async def _extract_things_to_know(page) -> List[str]:
    """Trích xuất 'Những điều cần biết' (Things to Know)."""
    items = []
    try:
        # Things to Know thường nằm trong card đặc biệt
        ttk_selectors = [
            '[data-attrid="kc:/"] span',
            '.V82bz',  # Things to know container
            '[data-ved] .mod .mCljob',
        ]

        for selector in ttk_selectors:
            elements = page.locator(selector)
            count = await elements.count()
            for i in range(count):
                text = await elements.nth(i).text_content()
                if text and len(text.strip()) > 10:
                    items.append(text.strip())

        # De-duplicate
        items = list(dict.fromkeys(items))

    except Exception as e:
        logger.warning("  [SERP] Lỗi trích xuất Things to Know: %s", str(e))

    logger.info("  [SERP] Tìm thấy %d Things to Know items", len(items))
    return items


async def _extract_related_searches(page) -> List[str]:
    """Trích xuất 'Tìm kiếm liên quan' (Related Searches)."""
    searches = []
    try:
        related_data = await page.evaluate("""
            () => {
                const items = [];
                // Method 1: Link-based selectors
                const selectors = [
                    '#botstuff a',
                    'a.ngTNl',
                    '.k8XOCe .s75CSd',
                    '.AJLUJb a',
                ];
                for (const sel of selectors) {
                    document.querySelectorAll(sel).forEach(el => {
                        const text = el.textContent.trim();
                        if (text && text.length > 2 && text.length < 100) {
                            items.push(text);
                        }
                    });
                    if (items.length > 0) break;
                }
                // De-duplicate
                return [...new Set(items)].slice(0, 8);
            }
        """)

        searches = related_data or []

    except Exception as e:
        logger.warning("  [SERP] Lỗi trích xuất Related Searches: %s", str(e))

    logger.info("  [SERP] Tìm thấy %d Related Searches", len(searches))
    return searches


async def _scrape_competitors(urls: List[str], headless: bool) -> List[Dict]:
    """
    Scrape noi dung tu top doi thu.

    Streamlit Cloud khong co browser/Playwright san, nen dung fallback nhe
    de giu pipeline on dinh va de deploy.
    """
    return _scrape_competitors_with_requests(urls)


def _scrape_competitors_with_requests(urls: List[str]) -> List[Dict]:
    """Fallback scrape cho moi truong cloud khi khong co Playwright/browser."""
    competitors = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }

    for i, url in enumerate(urls[:MAX_COMPETITORS]):
        logger.info("  [COMPETITOR-FALLBACK %d/%d] Truy cap: %s",
                    i + 1, len(urls), url[:80])
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            headings, body_text, text_blocks = _extract_clean_competitor_content(
                response.text
            )
            ngrams_2 = _compute_ngrams(body_text, n=2)
            ngrams_3 = _compute_ngrams(body_text, n=3)

            competitors.append({
                "url": url,
                "headings": headings,
                "body_text": body_text,
                "content_blocks": text_blocks[:80],
                "word_count": len(body_text.split()),
                "ngrams_2": ngrams_2[:20],
                "ngrams_3": ngrams_3[:20],
                "source": "requests_fallback",
            })
        except Exception as e:
            logger.warning("  [COMPETITOR-FALLBACK %d/%d] Loi: %s",
                           i + 1, len(urls), str(e))
            competitors.append({
                "url": url,
                "headings": [],
                "body_text": "",
                "content_blocks": [],
                "word_count": 0,
                "ngrams_2": [],
                "ngrams_3": [],
                "error": str(e),
                "source": "requests_fallback",
            })

    return competitors


async def _extract_page_headings(page) -> List[Dict]:
    """
    Trích xuất toàn bộ thẻ heading (H1, H2, H3) từ trang đối thủ.

    Returns:
        List[dict]: [{"level": "H1/H2/H3", "text": "..."}]
    """
    headings = []
    try:
        heading_els = page.locator("h1, h2, h3")
        count = await heading_els.count()

        for i in range(count):
            el = heading_els.nth(i)
            tag = await el.evaluate("el => el.tagName")
            text = await el.text_content()

            if text and text.strip():
                headings.append({
                    "level": tag.upper(),
                    "text": text.strip(),
                })

    except Exception as e:
        logger.warning("  Lỗi trích xuất headings: %s", str(e))

    return headings


async def _extract_body_text(page) -> str:
    """
    Trích xuất nội dung văn bản chính từ trang (loại bỏ nav, sidebar, footer).

    Returns:
        Chuỗi text sạch.
    """
    try:
        # Loại bỏ các phần không cần thiết
        selectors_js = ", ".join(f"'{selector}'" for selector in NOISY_SELECTORS)
        await page.evaluate(f"""
            () => {{
                const selectors = [{selectors_js}];
                selectors.forEach(sel => {{
                    document.querySelectorAll(sel).forEach(el => el.remove());
                }});
            }}
        """)

        # Trích xuất text từ main content area
        content_selectors = CONTENT_ROOT_SELECTORS

        body_text = ""
        for selector in content_selectors:
            el = page.locator(selector).first
            if await el.count() > 0:
                body_text = await el.text_content()
                if body_text and len(body_text.strip()) > 100:
                    break

        # Fallback: lấy body nếu không tìm thấy content area
        if not body_text or len(body_text.strip()) < 100:
            body_text = await page.locator("body").text_content()

        # Clean text
        body_text = re.sub(r"\s+", " ", body_text or "").strip()

        return body_text

    except Exception as e:
        logger.warning("  Lỗi trích xuất body text: %s", str(e))
        return ""


# ══════════════════════════════════════════════
#  ANALYSIS HELPERS
# ══════════════════════════════════════════════

def _extract_featured_snippet(data: Dict) -> Dict:
    answer_box = data.get("answerBox", {}) if isinstance(data, dict) else {}
    if not isinstance(answer_box, dict):
        return {}

    answer = answer_box.get("answer") or answer_box.get("snippet") or answer_box.get("title")
    highlighted = answer_box.get("snippetHighlighted")
    if not answer and isinstance(highlighted, list):
        answer = " ".join(str(item).strip() for item in highlighted if str(item).strip())
    if not answer:
        return {}

    return {
        "title": answer_box.get("title", ""),
        "answer": str(answer).strip(),
        "url": answer_box.get("link", "") or answer_box.get("source", ""),
    }


def _extract_knowledge_panel(kg: Dict) -> Dict:
    if not isinstance(kg, dict) or not kg:
        return {}
    attributes = kg.get("attributes", {})
    return {
        "title": kg.get("title", ""),
        "type": kg.get("type", ""),
        "description": kg.get("description", ""),
        "attributes": attributes if isinstance(attributes, dict) else {},
    }


def _detect_serp_features(data: Dict, organic_results: List[Dict]) -> List[str]:
    features = []
    if data.get("answerBox"):
        features.append("Featured Snippet")
    if data.get("peopleAlsoAsk"):
        features.append("People Also Ask")
    if data.get("knowledgeGraph"):
        features.append("Knowledge Panel")
    if data.get("images"):
        features.append("Image Pack")
    if data.get("videos"):
        features.append("Video")
    if data.get("places"):
        features.append("Local Pack")
    if data.get("shopping"):
        features.append("Shopping")
    if data.get("topStories") or data.get("news"):
        features.append("News")
    if data.get("relatedSearches"):
        features.append("Related Searches")

    if any("youtube.com" in str(item.get("url", "")).lower() for item in organic_results if isinstance(item, dict)):
        features.append("Video")

    deduped = []
    seen = set()
    for feature in features:
        key = str(feature).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(str(feature).strip())
    return deduped


def _classify_serp_result_format(url: str, title: str, snippet: str) -> str:
    haystack = f"{url} {title} {snippet}".lower()
    if any(marker in haystack for marker in ["youtube.com", "youtu.be", "reddit.com", "forum", "watch?v="]):
        return "Video/Forum/Other"
    if any(marker in haystack for marker in ["/product", "/san-pham", "/category", "/danh-muc", "bao gia", "gia ", "mua ", "price"]):
        return "Product/Category"
    if any(marker in haystack for marker in ["/landing", "/service", "/dich-vu", "landing page"]):
        return "Landing page"
    return "Blog/Article"


def _count_serp_result_formats(organic_results: List[Dict]) -> Dict[str, int]:
    counts = {
        "Blog/Article": 0,
        "Product/Category": 0,
        "Landing page": 0,
        "Video/Forum/Other": 0,
    }
    for item in organic_results:
        if not isinstance(item, dict):
            continue
        kind = _classify_serp_result_format(
            str(item.get("url", "")),
            str(item.get("title", "")),
            str(item.get("snippet", "")),
        )
        counts[kind] += 1
    return counts


def _dominant_serp_format(organic_results: List[Dict]) -> str:
    counts = _count_serp_result_formats(organic_results)
    if not any(counts.values()):
        return "Mixed"
    top_kind, top_count = max(counts.items(), key=lambda pair: pair[1])
    return top_kind if top_count >= 3 else "Mixed"


def _normalize_heading_key(text: str) -> str:
    cleaned = str(text or "").lower().strip()
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned)
    cleaned = re.sub(r"^\[[A-Z]+\]\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _build_heading_frequency_matrix(competitors: List[Dict]) -> Dict:
    competitor_urls = [str(comp.get("url", "")).strip() for comp in competitors if str(comp.get("url", "")).strip()]
    if not competitors:
        return {"competitor_urls": [], "rows": []}

    topic_labels: Dict[str, str] = {}
    per_competitor_topics: List[set] = []
    for comp in competitors:
        current_topics = set()
        for heading in comp.get("headings", []):
            if not isinstance(heading, dict) or str(heading.get("level", "")).upper() != "H2":
                continue
            label = str(heading.get("text", "")).strip()
            key = _normalize_heading_key(label)
            if not key:
                continue
            topic_labels.setdefault(key, label)
            current_topics.add(key)
        per_competitor_topics.append(current_topics)

    denom = max(1, len(per_competitor_topics))
    rows = []
    for key, label in topic_labels.items():
        hits = [key in topic_set for topic_set in per_competitor_topics]
        total = sum(1 for hit in hits if hit)
        rows.append(
            {
                "topic": label,
                "hits": hits,
                "frequency": f"{total}/{denom}",
                "classification": _classify_frequency_bucket(total, denom),
            }
        )

    rows.sort(key=lambda row: (-sum(1 for hit in row["hits"] if hit), row["topic"].lower()))
    return {"competitor_urls": competitor_urls, "rows": rows[:20]}


def _classify_frequency_bucket(total: int, denom: int) -> str:
    if denom <= 0:
        return "could_have"
    must_threshold = max(2, math.ceil((2 * denom) / 3)) if denom >= 3 else denom
    should_threshold = max(1, math.ceil(denom / 3))
    if total >= must_threshold:
        return "must_have"
    if total >= should_threshold:
        return "should_have"
    return "could_have"


def _normalize_semantic_voids(void_items: List) -> List[Dict]:
    normalized = []
    for item in void_items:
        if isinstance(item, dict):
            heading = str(item.get("heading") or item.get("void") or "").strip()
            if not heading:
                continue
            normalized.append(
                {
                    "heading": heading,
                    "rationale": str(item.get("rationale", "")).strip(),
                    "attribute_type": str(item.get("attribute_type", "")).strip(),
                    "prominence_score": item.get("prominence_score", 0),
                }
            )
        elif isinstance(item, str):
            text = item.strip()
            if text:
                normalized.append(
                    {
                        "heading": text,
                        "rationale": "",
                        "attribute_type": "",
                        "prominence_score": 0,
                    }
                )
    return normalized


def _filter_competitor_urls(organic_results: List[Dict]) -> List[str]:
    """
    Lọc URLs đối thủ, loại bỏ các trang không phải bài viết nội dung.

    Loại bỏ: YouTube, Wikipedia, trang chủ, social media, Google.
    """
    skip_domains = [
        "youtube.com", "youtu.be", "facebook.com", "twitter.com",
        "instagram.com", "tiktok.com", "pinterest.com",
        "google.com", "maps.google",
    ]

    urls = []
    for result in organic_results:
        url = result.get("url", "")
        if not url:
            continue

        # Bỏ qua các domain không phù hợp
        if any(domain in url.lower() for domain in skip_domains):
            continue

        urls.append(url)

    return urls


def _extract_entities_from_serp(serp_data: Dict, topic: str) -> Dict:
    """
    Trích xuất thực thể chính và phụ từ titles + snippets trên SERP.

    Returns:
        {"primary": List[str], "secondary": List[str]}
    """
    all_text = []

    # Thu thập text từ organic results
    for result in serp_data.get("organic_results", []):
        all_text.append(result.get("title", ""))
        all_text.append(result.get("snippet", ""))

    # Thu thập text từ PAA
    all_text.extend(serp_data.get("people_also_ask", []))

    # Thu thập text từ Things to Know
    all_text.extend(serp_data.get("things_to_know", []))

    combined = " ".join(all_text).lower()

    # Trích xuất danh từ/cụm từ xuất hiện nhiều (2-grams)
    ngrams = _compute_ngrams(combined, n=2, top_k=30)

    # Phân loại: primary = liên quan trực tiếp đến topic
    topic_words = set(topic.lower().split())
    primary = []
    secondary = []

    for ngram, count in ngrams:
        ngram_words = set(ngram.split())
        if ngram_words & topic_words:
            primary.append(ngram)
        else:
            secondary.append(ngram)

    return {
        "primary": primary[:10],
        "secondary": secondary[:10],
    }


def _extract_attributes_from_serp(serp_data: Dict) -> List[str]:
    """
    Trích xuất thuộc tính quan trọng từ PAA và Things to Know.

    Đây là những thuộc tính mà Google coi là quan trọng nhất.
    """
    attributes = []

    # PAA questions → attributes
    for q in serp_data.get("people_also_ask", []):
        # Rút trích keyword chính từ câu hỏi
        cleaned = re.sub(r"^(là gì|thế nào|tại sao|vì sao|cách)\s*", "", q.lower())
        cleaned = re.sub(r"\?$", "", cleaned).strip()
        if cleaned and len(cleaned) > 3:
            attributes.append(cleaned)

    # Things to Know → attributes
    for item in serp_data.get("things_to_know", []):
        if len(item) < 100:  # Chỉ lấy items ngắn gọn
            attributes.append(item)

    return list(dict.fromkeys(attributes))[:15]


def _extract_topic_clusters(serp_data: Dict) -> List[str]:
    """
    Xác định cụm chủ đề liên quan từ Related Searches và PAA.
    """
    clusters = []

    # Related Searches chính là topic clusters
    clusters.extend(serp_data.get("related_searches", []))

    # Thêm một số PAA questions có thể là sub-topics
    for q in serp_data.get("people_also_ask", []):
        if len(q) < 60:  # Câu hỏi ngắn có khả năng là sub-topic
            clusters.append(q)

    return list(dict.fromkeys(clusters))[:12]


def _new_intent_scorecard() -> Dict[str, float]:
    return {bucket: 0.0 for bucket in INTENT_BUCKETS}


def _intent_label(intent: str) -> str:
    labels = {
        "informational": "Informational",
        "commercial investigation": "Commercial Investigation",
        "transactional": "Transactional",
        "navigational": "Navigational",
        "vs": "Comparison (VS)",
    }
    return labels.get(str(intent or "").strip().lower(), "Informational")


def _select_top_intent(scores: Dict[str, float]) -> Tuple[str, float, str, float]:
    ranked = sorted(
        ((bucket, float(scores.get(bucket, 0.0))) for bucket in INTENT_BUCKETS),
        key=lambda item: item[1],
        reverse=True,
    )
    top_bucket, top_score = ranked[0] if ranked else ("informational", 0.0)
    second_bucket, second_score = ranked[1] if len(ranked) > 1 else ("", 0.0)
    return top_bucket, top_score, second_bucket, second_score


def _rank_weight(position: Any) -> float:
    try:
        pos = max(1, int(position or 1))
    except Exception:
        pos = 1
    return round(1.0 / math.sqrt(pos), 4)


def _score_markers(
    haystack: str,
    markers: Tuple[str, ...],
    weight: float,
    scores: Dict[str, float],
    bucket: str,
    reasons: List[str],
    reason_label: str,
) -> int:
    hits = 0
    for marker in markers:
        if marker and marker in haystack:
            scores[bucket] += weight
            hits += 1
    if hits:
        reasons.append(f"{reason_label} x{hits}")
    return hits


def _topic_intent_hints(topic: str) -> Dict[str, float]:
    topic_norm = _normalize_topic_text(topic)
    scores = _new_intent_scorecard()
    if not topic_norm:
        return scores

    for bucket, markers in INTENT_QUERY_MARKERS.items():
        for marker in markers:
            if marker and marker in topic_norm:
                scores[bucket] += 1.0
    return scores


def _classify_serp_result_intent(result: Dict, topic: str = "") -> Dict[str, Any]:
    title = str(result.get("title", "") or "")
    snippet = str(result.get("snippet", "") or "")
    url = str(result.get("url", "") or "")
    title_norm = _normalize_topic_text(title)
    snippet_norm = _normalize_topic_text(snippet)
    url_norm = _normalize_topic_text(url)
    haystack = " ".join(part for part in [title_norm, snippet_norm, url_norm] if part).strip()
    format_label = _classify_serp_result_format(url, title, snippet)

    scores = _new_intent_scorecard()
    reasons: List[str] = []

    topic_hints = _topic_intent_hints(topic)
    for bucket, hint_score in topic_hints.items():
        if hint_score > 0:
            scores[bucket] += min(0.45, hint_score * 0.18)

    _score_markers(
        haystack,
        INTENT_RESULT_MARKERS["informational"],
        1.15,
        scores,
        "informational",
        reasons,
        "info signals",
    )
    _score_markers(
        haystack,
        INTENT_RESULT_MARKERS["commercial investigation"],
        1.3,
        scores,
        "commercial investigation",
        reasons,
        "commercial signals",
    )
    _score_markers(
        haystack,
        INTENT_RESULT_MARKERS["transactional"],
        1.45,
        scores,
        "transactional",
        reasons,
        "transaction signals",
    )
    _score_markers(
        haystack,
        INTENT_RESULT_MARKERS["navigational"],
        1.6,
        scores,
        "navigational",
        reasons,
        "navigation signals",
    )

    if any(marker in haystack for marker in PRICING_MARKERS):
        scores["commercial investigation"] += 0.9
        if format_label in {"Product/Category", "Landing page"}:
            scores["transactional"] += 0.8
        reasons.append("pricing signals")

    if format_label == "Product/Category":
        scores["transactional"] += 2.2
        scores["commercial investigation"] += 0.7
        reasons.append("product/category format")
    elif format_label == "Landing page":
        scores["transactional"] += 2.0
        scores["commercial investigation"] += 0.4
        reasons.append("landing/service format")
    elif format_label == "Blog/Article":
        scores["informational"] += 0.25
    else:
        scores["informational"] += 0.15

    parsed = urlparse(url)
    path_norm = _normalize_topic_text(parsed.path)
    host_tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", _normalize_topic_text(parsed.netloc))
        if token and token not in DOMAIN_STOPWORDS
    ]
    root_like = parsed.path in {"", "/"} or path_norm in {"", "home", "trang chu"}
    if any(marker in parsed.path.lower() for marker in NAVIGATIONAL_URL_MARKERS):
        scores["navigational"] += 1.8
        reasons.append("navigation path")
    if any(marker in parsed.path.lower() for marker in TRANSACTIONAL_URL_MARKERS):
        scores["transactional"] += 1.5
        reasons.append("transactional path")
    if root_like and any(token in title_norm for token in host_tokens[:2]):
        scores["navigational"] += 1.1
        reasons.append("brand/root page")

    top_intent, top_score, _, _ = _select_top_intent(scores)
    if top_score <= 0:
        top_intent = "informational"
        scores[top_intent] = 1.0
        reasons.append("default informational fallback")

    subtype = ""
    if top_intent == "commercial investigation":
        if any(marker in haystack for marker in COMPARISON_MARKERS):
            subtype = "comparison"
        elif any(marker in haystack for marker in REVIEW_MARKERS):
            subtype = "review"
        elif any(marker in haystack for marker in PRICING_MARKERS):
            subtype = "pricing"
    elif top_intent == "transactional":
        if any(marker in haystack for marker in ("dang ky", "bao gia", "lien he", "dat lich")):
            subtype = "lead-gen"
        elif any(marker in haystack for marker in ("mua", "dat mua", "mua ngay", "order")):
            subtype = "purchase"
    elif top_intent == "navigational":
        subtype = "brand"

    score_total = sum(scores.values())
    confidence = round(top_score / max(score_total, 1.0), 3)
    return {
        "intent": top_intent,
        "subtype": subtype,
        "scores": {bucket: round(value, 3) for bucket, value in scores.items()},
        "confidence": confidence,
        "format": format_label,
        "reasons": reasons[:4],
    }


def _joined_competitor_headings(headings: Any) -> str:
    if not isinstance(headings, list):
        return ""
    parts = []
    for item in headings:
        if isinstance(item, dict):
            text = str(item.get("text", "") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts[:24])


def _classify_competitor_content_intent(competitor: Dict, topic: str = "") -> Dict[str, Any]:
    headings = competitor.get("headings", []) if isinstance(competitor, dict) else []
    body_text = str(competitor.get("body_text", "") or "") if isinstance(competitor, dict) else ""
    content_blocks = competitor.get("content_blocks", []) if isinstance(competitor, dict) else []
    url = str(competitor.get("url", "") or "") if isinstance(competitor, dict) else ""
    heading_text = _joined_competitor_headings(headings)
    title_hint = heading_text.split("  ")[0] if "  " in heading_text else heading_text
    body_excerpt = " ".join(str(item or "") for item in content_blocks[:20]) or body_text[:4000]
    heading_norm = _normalize_topic_text(heading_text)
    body_norm = _normalize_topic_text(body_excerpt)
    url_norm = _normalize_topic_text(url)
    scores = _new_intent_scorecard()
    reasons: List[str] = []

    topic_hints = _topic_intent_hints(topic)
    for bucket, hint_score in topic_hints.items():
        if hint_score > 0:
            scores[bucket] += min(0.55, hint_score * 0.2)

    for bucket, markers in INTENT_RESULT_MARKERS.items():
        _score_markers(
            heading_norm,
            markers,
            1.45 if bucket != "navigational" else 1.7,
            scores,
            bucket,
            reasons,
            f"{bucket} heading signals",
        )
        _score_markers(
            body_norm,
            markers,
            0.55 if bucket == "informational" else 0.7,
            scores,
            bucket,
            reasons,
            f"{bucket} body signals",
        )

    if any(marker in body_norm for marker in PRICING_MARKERS):
        scores["commercial investigation"] += 0.9
        reasons.append("body pricing signals")
    if any(marker in body_norm for marker in COMPARISON_MARKERS):
        scores["commercial investigation"] += 0.8
        reasons.append("body comparison signals")
    if any(marker in body_norm for marker in ("mua", "dang ky", "bao gia", "lien he", "dat lich", "order")):
        scores["transactional"] += 0.9
        reasons.append("body conversion signals")

    if any(marker in url.lower() for marker in NAVIGATIONAL_URL_MARKERS):
        scores["navigational"] += 1.6
        reasons.append("navigation path")
    if any(marker in url.lower() for marker in TRANSACTIONAL_URL_MARKERS):
        scores["transactional"] += 1.4
        reasons.append("transactional path")

    format_label = _classify_serp_result_format(url, title_hint, body_excerpt[:240])
    if format_label == "Product/Category":
        scores["transactional"] += 1.7
        scores["commercial investigation"] += 0.5
        reasons.append("product/category content format")
    elif format_label == "Landing page":
        scores["transactional"] += 1.6
        scores["commercial investigation"] += 0.3
        reasons.append("landing/service content format")
    else:
        scores["informational"] += 0.35

    word_count = 0
    try:
        word_count = int(competitor.get("word_count", 0) or 0)
    except Exception:
        word_count = 0
    if word_count >= 600 and format_label == "Blog/Article":
        scores["informational"] += 0.45
        reasons.append("long-form explainer body")
    elif word_count <= 120 and format_label in {"Product/Category", "Landing page"}:
        scores["transactional"] += 0.3

    top_intent, top_score, _, _ = _select_top_intent(scores)
    if top_score <= 0:
        top_intent = "informational"
        scores[top_intent] = 1.0
        reasons.append("default informational fallback")

    subtype = ""
    if top_intent == "commercial investigation":
        if any(marker in body_norm or marker in heading_norm for marker in COMPARISON_MARKERS):
            subtype = "comparison"
        elif any(marker in body_norm or marker in heading_norm for marker in REVIEW_MARKERS):
            subtype = "review"
        elif any(marker in body_norm or marker in heading_norm for marker in PRICING_MARKERS):
            subtype = "pricing"
    elif top_intent == "transactional":
        if any(marker in body_norm for marker in ("dang ky", "bao gia", "lien he", "dat lich")):
            subtype = "lead-gen"
        elif any(marker in body_norm for marker in ("mua", "dat mua", "mua ngay", "order")):
            subtype = "purchase"
    elif top_intent == "navigational":
        subtype = "brand"

    score_total = sum(scores.values())
    confidence = round(top_score / max(score_total, 1.0), 3)
    return {
        "intent": top_intent,
        "subtype": subtype,
        "scores": {bucket: round(value, 3) for bucket, value in scores.items()},
        "confidence": confidence,
        "format": format_label,
        "reasons": reasons[:6],
    }


def _competitor_intent_source_confidence(competitors: List[Dict[str, Any]]) -> str:
    strong_pages = 0
    for item in competitors:
        try:
            word_count = int(item.get("word_count", 0) or 0)
        except Exception:
            word_count = 0
        if word_count >= 180 and item.get("body_text"):
            strong_pages += 1
    if strong_pages >= 5:
        return "high"
    if strong_pages >= 3:
        return "medium"
    return "low"


def _analyze_competitor_intent_mix(competitors: List[Dict[str, Any]], topic: str = "") -> Dict[str, Any]:
    weighted = _new_intent_scorecard()
    raw_counts = {bucket: 0 for bucket in INTENT_BUCKETS}
    result_labels: List[Dict[str, Any]] = []
    subtype_counter = Counter()

    for index, competitor in enumerate(competitors, start=1):
        if not isinstance(competitor, dict):
            continue
        intent = str(competitor.get("content_intent", "") or "").strip().lower() or "informational"
        subtype = str(competitor.get("content_intent_subtype", "") or "").strip().lower()
        position = competitor.get("serp_position", index)
        weight = _rank_weight(position)
        try:
            word_count = int(competitor.get("word_count", 0) or 0)
        except Exception:
            word_count = 0
        depth_multiplier = min(1.2, max(0.75, word_count / 700.0)) if word_count else 0.75
        weighted[intent] += round(weight * depth_multiplier, 4)
        raw_counts[intent] += 1
        if subtype:
            subtype_counter[subtype] += 1
        result_labels.append(
            {
                "position": position,
                "url": str(competitor.get("url", "") or ""),
                "intent": intent,
                "subtype": subtype,
                "confidence": float(competitor.get("content_intent_confidence", 0.0) or 0.0),
                "weight": round(weight * depth_multiplier, 4),
                "format": str(competitor.get("content_intent_format", "") or ""),
                "reasons": list(competitor.get("content_intent_reasons", []) or [])[:4],
            }
        )

    topic_hints = _topic_intent_hints(topic)
    hint_bucket, hint_score, _, _ = _select_top_intent(topic_hints)
    adjusted = dict(weighted)
    feature_notes: List[str] = []
    if hint_score > 0:
        adjusted[hint_bucket] += min(0.45, hint_score * 0.18)
        feature_notes.append(f"query hint: {_intent_label(hint_bucket)}")
    if subtype_counter.get("comparison", 0) >= max(2, len(competitors) // 3):
        adjusted["commercial investigation"] += 0.35
        feature_notes.append("comparison-heavy bodies")

    top_intent, top_score, second_intent, _ = _select_top_intent(adjusted)
    if top_score <= 0:
        top_intent = hint_bucket if hint_score > 0 else "informational"
        adjusted[top_intent] = 1.0

    weighted_total = sum(adjusted.values()) or 1.0
    distribution: Dict[str, Dict[str, float]] = {}
    for bucket in INTENT_BUCKETS:
        weighted_count = float(adjusted.get(bucket, 0.0))
        share = weighted_count / weighted_total
        distribution[bucket] = {
            "raw_count": int(raw_counts.get(bucket, 0)),
            "weighted_count": round(weighted_count, 4),
            "share": round(share, 4),
            "percentage": round(share * 100, 1),
        }

    dominance_share = distribution[top_intent]["share"]
    secondary_share = distribution.get(second_intent, {}).get("share", 0.0) if second_intent else 0.0
    lead_margin = round(dominance_share - secondary_share, 4)
    is_mixed = dominance_share < 0.58 and lead_margin < 0.12
    source_confidence = _competitor_intent_source_confidence(competitors)
    parts = [f"{_intent_label(top_intent)} owns {distribution[top_intent]['percentage']}% of weighted competitor body share"]
    if second_intent and distribution.get(second_intent, {}).get("weighted_count", 0) > 0:
        parts.append(f"{_intent_label(second_intent)} is secondary at {distribution[second_intent]['percentage']}%")
    if feature_notes:
        parts.append("Body support: " + ", ".join(feature_notes[:3]))
    parts.append(f"based on {len(result_labels)} crawled competitor bodies")

    return {
        "selected_intent": top_intent,
        "secondary_intent": second_intent,
        "dominance_share": round(dominance_share, 4),
        "lead_margin": lead_margin,
        "is_mixed": is_mixed,
        "source": "competitor_full_body",
        "source_confidence": source_confidence,
        "distribution": distribution,
        "raw_counts": raw_counts,
        "weighted_counts": {bucket: round(value, 4) for bucket, value in adjusted.items()},
        "result_labels": result_labels,
        "rationale": ". ".join(parts),
    }


def _classify_competitor_content_archetype(competitor: Dict, topic: str = "") -> Dict[str, Any]:
    headings = _joined_competitor_headings(competitor.get("headings", []) if isinstance(competitor, dict) else [])
    body_text = str(competitor.get("body_text", "") or "") if isinstance(competitor, dict) else ""
    content_blocks = competitor.get("content_blocks", []) if isinstance(competitor, dict) else []
    body_excerpt = " ".join(str(item or "") for item in content_blocks[:24]) or body_text[:5000]
    body_norm = _normalize_topic_text(body_excerpt)
    heading_norm = _normalize_topic_text(headings)
    topic_norm = _normalize_topic_text(topic)
    intent = str(competitor.get("content_intent", "") or "").strip().lower()
    format_label = str(competitor.get("content_intent_format", "") or "").strip()

    archetype_scores = {
        "explainer": 0.0,
        "how_it_works": 0.0,
        "comparison": 0.0,
        "pricing": 0.0,
        "risk": 0.0,
        "faq": 0.0,
        "landing": 0.0,
        "listicle": 0.0,
    }
    reasons: List[str] = []

    def _score(archetype: str, haystack: str, markers: tuple[str, ...], weight: float, reason: str) -> None:
        hits = 0
        for marker in markers:
            if marker and marker in haystack:
                archetype_scores[archetype] += weight
                hits += 1
        if hits:
            reasons.append(f"{reason} x{hits}")

    _score("explainer", heading_norm, ("la gi", "khai niem", "dinh nghia", "tong quan", "overview"), 1.7, "explainer headings")
    _score("explainer", body_norm, ("la gi", "khai niem", "dinh nghia", "tong quan", "ban chat"), 0.8, "explainer body")
    _score("how_it_works", heading_norm, ("co che", "hoat dong", "quy trinh", "cac buoc", "how it works"), 1.7, "process headings")
    _score("how_it_works", body_norm, ("co che", "quy trinh", "buoc", "thanh toan", "van hanh"), 0.75, "process body")
    _score("comparison", heading_norm, COMPARISON_MARKERS + REVIEW_MARKERS, 1.8, "comparison headings")
    _score("comparison", body_norm, COMPARISON_MARKERS + REVIEW_MARKERS, 0.85, "comparison body")
    _score("pricing", heading_norm, PRICING_MARKERS + ("chi phi", "phi", "muc phi"), 1.85, "pricing headings")
    _score("pricing", body_norm, PRICING_MARKERS + ("chi phi", "phi", "muc phi"), 0.95, "pricing body")
    _score("risk", heading_norm, ("rui ro", "luu y", "canh bao", "sai lam", "gioi han"), 1.9, "risk headings")
    _score("risk", body_norm, ("rui ro", "canh bao", "luu y", "mat phi", "hidden cost", "gioi han"), 0.8, "risk body")
    _score("faq", heading_norm, ("faq", "cau hoi", "question", "hoi dap"), 1.9, "faq headings")
    _score("faq", body_norm, ("cau hoi thuong gap", "hoi dap"), 0.6, "faq body")
    _score("listicle", heading_norm, ("top ", "best", "tot nhat", "danh sach", "cac loai"), 1.6, "listicle headings")
    _score("listicle", body_norm, ("top ", "tot nhat", "xep hang", "danh sach"), 0.65, "listicle body")

    if format_label == "Landing page":
        archetype_scores["landing"] += 2.0
        reasons.append("landing page format")
    elif format_label == "Product/Category":
        archetype_scores["pricing"] += 0.75
        archetype_scores["landing"] += 0.9
        reasons.append("product/category format")
    else:
        archetype_scores["explainer"] += 0.25

    if intent == "informational":
        archetype_scores["explainer"] += 0.45
    elif intent == "commercial investigation":
        archetype_scores["comparison"] += 0.55
    elif intent == "transactional":
        archetype_scores["landing"] += 0.7
        archetype_scores["pricing"] += 0.4

    if topic_norm and any(marker in topic_norm for marker in ("la gi", "khai niem", "dinh nghia")):
        archetype_scores["explainer"] += 0.45

    ranked = sorted(archetype_scores.items(), key=lambda item: item[1], reverse=True)
    selected, top_score = ranked[0] if ranked else ("explainer", 0.0)
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    total = sum(archetype_scores.values()) or 1.0
    confidence = round(top_score / total, 3)
    return {
        "archetype": selected if top_score > 0 else "explainer",
        "confidence": confidence,
        "scores": {key: round(value, 3) for key, value in archetype_scores.items()},
        "runner_up": ranked[1][0] if len(ranked) > 1 and second_score > 0 else "",
        "reasons": reasons[:5],
    }


def _analyze_competitor_archetype_mix(competitors: List[Dict[str, Any]]) -> Dict[str, Any]:
    weighted: Dict[str, float] = {}
    raw_counts: Dict[str, int] = {}
    result_labels: List[Dict[str, Any]] = []
    for index, competitor in enumerate(competitors, start=1):
        if not isinstance(competitor, dict):
            continue
        archetype = str(competitor.get("content_archetype", "") or "").strip().lower() or "explainer"
        position = competitor.get("serp_position", index)
        weight = _rank_weight(position)
        try:
            word_count = int(competitor.get("word_count", 0) or 0)
        except Exception:
            word_count = 0
        depth_multiplier = min(1.2, max(0.8, word_count / 850.0)) if word_count else 0.8
        weighted[archetype] = round(weighted.get(archetype, 0.0) + (weight * depth_multiplier), 4)
        raw_counts[archetype] = int(raw_counts.get(archetype, 0)) + 1
        result_labels.append(
            {
                "position": position,
                "url": str(competitor.get("url", "") or ""),
                "archetype": archetype,
                "confidence": float(competitor.get("content_archetype_confidence", 0.0) or 0.0),
                "reasons": list(competitor.get("content_archetype_reasons", []) or [])[:4],
            }
        )

    total = sum(weighted.values()) or 1.0
    ranked = sorted(weighted.items(), key=lambda item: item[1], reverse=True)
    top_archetypes = []
    for archetype, score in ranked[:4]:
        share = score / total
        top_archetypes.append(
            {
                "archetype": archetype,
                "weighted_count": round(score, 4),
                "share": round(share, 4),
                "percentage": round(share * 100, 1),
                "raw_count": int(raw_counts.get(archetype, 0)),
            }
        )
    selected = top_archetypes[0]["archetype"] if top_archetypes else "explainer"
    return {
        "selected_archetype": selected,
        "top_archetypes": top_archetypes,
        "result_labels": result_labels,
        "rationale": (
            f"Top competitor bodies skew toward {selected}."
            if top_archetypes
            else "No competitor archetype signal available."
        ),
    }


def _serp_source_confidence(source: str) -> str:
    source_norm = str(source or "").strip().lower()
    if "duckduckgo" in source_norm:
        return "low"
    if "google_html" in source_norm:
        return "medium"
    if "serper" in source_norm or "google" in source_norm:
        return "high"
    return "medium"


def _serp_source_label(source: str) -> str:
    source_norm = str(source or "").strip().lower()
    if source_norm == "serper_google":
        return "Google via Serper.dev"
    if source_norm.startswith("google_html"):
        return "Google HTML fallback"
    if source_norm.startswith("duckduckgo"):
        return "DuckDuckGo fallback"
    return source or "unknown"


def _analyze_serp_intent_mix(serp_data: Dict, topic: str = "") -> Dict[str, Any]:
    organic = serp_data.get("organic_results", []) or []
    source = str(serp_data.get("serp_source", "") or "")
    weighted = _new_intent_scorecard()
    raw_counts = {bucket: 0 for bucket in INTENT_BUCKETS}
    result_labels: List[Dict[str, Any]] = []
    subtype_counter = Counter()

    for index, result in enumerate(organic, start=1):
        if not isinstance(result, dict):
            continue
        classification = _classify_serp_result_intent(result, topic=topic)
        intent = classification["intent"]
        subtype = classification.get("subtype", "")
        position = result.get("position", index)
        weight = _rank_weight(position)
        raw_counts[intent] += 1
        weighted[intent] += weight
        if subtype:
            subtype_counter[subtype] += 1
        result_labels.append(
            {
                "position": position,
                "title": str(result.get("title", "") or ""),
                "url": str(result.get("url", "") or ""),
                "intent": intent,
                "subtype": subtype,
                "confidence": classification.get("confidence", 0.0),
                "weight": weight,
                "format": classification.get("format", ""),
                "reasons": classification.get("reasons", []),
            }
        )

    adjusted = dict(weighted)
    feature_notes: List[str] = []
    paa_count = len(serp_data.get("people_also_ask", []) or [])
    ttk_count = len(serp_data.get("things_to_know", []) or [])
    if paa_count >= 2:
        boost = min(0.9, 0.18 * paa_count)
        adjusted["informational"] += boost
        feature_notes.append(f"PAA x{paa_count}")
    if ttk_count > 0:
        boost = min(0.6, 0.12 * ttk_count)
        adjusted["informational"] += boost
        feature_notes.append(f"Things to know x{ttk_count}")
    if serp_data.get("featured_snippet"):
        adjusted["informational"] += 0.35
        feature_notes.append("Featured snippet")

    result_format_counts = _count_serp_result_formats(organic)
    product_like = (
        result_format_counts.get("Product/Category", 0)
        + result_format_counts.get("Landing page", 0)
    )
    article_like = result_format_counts.get("Blog/Article", 0)
    if product_like > article_like:
        adjusted["transactional"] += 0.45
        feature_notes.append("SERP skews product/landing")
    if subtype_counter.get("comparison", 0) >= max(2, len(organic) // 3):
        adjusted["commercial investigation"] += 0.4
        feature_notes.append("comparison-heavy titles")

    topic_hints = _topic_intent_hints(topic)
    hint_bucket, hint_score, _, _ = _select_top_intent(topic_hints)
    topic_norm = _normalize_topic_text(topic)
    if any(marker in topic_norm for marker in ("la gi", "khai niem", "dinh nghia", "tong quan")):
        adjusted["informational"] += 1.0
        feature_notes.append("hard informational query")
    if any(marker in topic_norm for marker in COMPARISON_MARKERS):
        adjusted["commercial investigation"] += 0.9
        feature_notes.append("hard comparison query")
    if any(marker in topic_norm for marker in ("mua", "dat mua", "dang ky", "bao gia", "bang gia", "lien he", "mo tai khoan")):
        adjusted["transactional"] += 1.0
        feature_notes.append("hard transactional query")
    if any(marker in topic_norm for marker in ("dang nhap", "login", "trang chu", "website", "chinh thuc")):
        adjusted["navigational"] += 1.0
        feature_notes.append("hard navigational query")
    if hint_score > 0:
        adjusted[hint_bucket] += min(0.55, hint_score * 0.2)
        feature_notes.append(f"query hint: {_intent_label(hint_bucket)}")

    top_intent, top_score, second_intent, second_score = _select_top_intent(adjusted)
    if top_score <= 0:
        top_intent = hint_bucket if hint_score > 0 else "informational"
        top_score = 1.0
        adjusted[top_intent] = top_score

    weighted_total = sum(adjusted.values())
    if weighted_total <= 0:
        weighted_total = 1.0

    distribution: Dict[str, Dict[str, float]] = {}
    for bucket in INTENT_BUCKETS:
        weighted_count = float(adjusted.get(bucket, 0.0))
        share = weighted_count / weighted_total
        distribution[bucket] = {
            "raw_count": int(raw_counts.get(bucket, 0)),
            "weighted_count": round(weighted_count, 4),
            "share": round(share, 4),
            "percentage": round(share * 100, 1),
        }

    dominance_share = distribution[top_intent]["share"]
    secondary_share = distribution.get(second_intent, {}).get("share", 0.0) if second_intent else 0.0
    lead_margin = round(dominance_share - secondary_share, 4)
    is_mixed = dominance_share < 0.58 and lead_margin < 0.12
    override_reason = ""

    if any(marker in topic_norm for marker in ("la gi", "khai niem", "dinh nghia", "tong quan")):
        if top_intent in {"transactional", "commercial investigation"} and (is_mixed or len(organic) <= 2 or dominance_share < 0.62):
            top_intent = "informational"
            override_reason = "explicit informational query marker overrides a mixed SERP"
    elif any(marker in topic_norm for marker in COMPARISON_MARKERS):
        if top_intent == "informational" and (is_mixed or len(organic) <= 2 or dominance_share < 0.62):
            top_intent = "commercial investigation"
            override_reason = "explicit comparison query marker overrides a mixed SERP"
    elif any(marker in topic_norm for marker in ("mua", "dat mua", "dang ky", "bao gia", "bang gia", "lien he", "mo tai khoan")):
        if top_intent in {"informational", "commercial investigation"} and (is_mixed or len(organic) <= 2 or dominance_share < 0.62):
            top_intent = "transactional"
            override_reason = "explicit transactional query marker overrides a mixed SERP"
    elif any(marker in topic_norm for marker in ("dang nhap", "login", "trang chu", "website", "chinh thuc")):
        if top_intent != "navigational" and (is_mixed or len(organic) <= 2 or dominance_share < 0.62):
            top_intent = "navigational"
            override_reason = "explicit navigational query marker overrides a mixed SERP"

    if second_intent == top_intent or not second_intent:
        candidates = [
            (bucket, distribution.get(bucket, {}).get("share", 0.0))
            for bucket in INTENT_BUCKETS
            if bucket != top_intent
        ]
        candidates.sort(key=lambda item: item[1], reverse=True)
        second_intent = candidates[0][0] if candidates and candidates[0][1] > 0 else ""
    dominance_share = distribution.get(top_intent, {}).get("share", 0.0)
    secondary_share = distribution.get(second_intent, {}).get("share", 0.0) if second_intent else 0.0
    lead_margin = round(dominance_share - secondary_share, 4)
    if override_reason:
        is_mixed = True

    selected_legacy = top_intent
    if top_intent == "commercial investigation":
        comparison_heavy = subtype_counter.get("comparison", 0) >= max(2, math.ceil(max(len(organic), 1) * 0.3))
        query_is_comparison = bool(topic and any(marker in _normalize_topic_text(topic) for marker in COMPARISON_MARKERS))
        if comparison_heavy or query_is_comparison:
            selected_legacy = "vs"

    source_confidence = _serp_source_confidence(source)
    if override_reason and second_intent:
        parts = [
            (
                f"{_intent_label(top_intent)} is selected at {distribution[top_intent]['percentage']}% weighted share "
                f"while {_intent_label(second_intent)} leads the raw mix at {distribution[second_intent]['percentage']}%"
            )
        ]
    else:
        parts = [
            f"{_intent_label(top_intent)} owns {distribution[top_intent]['percentage']}% of weighted top-result share"
        ]
    if second_intent and distribution.get(second_intent, {}).get("weighted_count", 0) > 0 and not override_reason:
        parts.append(
            f"{_intent_label(second_intent)} is secondary at {distribution[second_intent]['percentage']}%"
        )
    if override_reason:
        parts.append(override_reason)
    if feature_notes:
        parts.append("SERP support: " + ", ".join(feature_notes[:4]))
    if source_confidence == "low":
        parts.append("source confidence is low because Google fell back to DuckDuckGo results")
    parts.append(f"recommended brief direction: {_intent_label(top_intent)}")

    return {
        "selected_intent": top_intent,
        "selected_intent_legacy": selected_legacy,
        "secondary_intent": second_intent,
        "dominance_share": round(dominance_share, 4),
        "lead_margin": lead_margin,
        "is_mixed": is_mixed,
        "source": source,
        "source_label": _serp_source_label(source),
        "source_confidence": source_confidence,
        "distribution": distribution,
        "raw_counts": raw_counts,
        "weighted_counts": {bucket: round(value, 4) for bucket, value in adjusted.items()},
        "result_labels": result_labels,
        "rationale": ". ".join(parts),
    }


def _classify_serp_intent(serp_data: Dict, topic: str = "") -> str:
    """
    Backward-compatible dominant intent classifier.

    Intent mix chi tiết giờ nằm ở:
    - intent_distribution
    - intent_decision
    - result_intents
    """
    profile = _analyze_serp_intent_mix(serp_data, topic=topic)
    return str(profile.get("selected_intent_legacy", "informational") or "informational")


# ══════════════════════════════════════════════
#  N-GRAM COMPUTATION
# ══════════════════════════════════════════════

def _tokenize_vietnamese(text: str) -> List[str]:
    """
    Tokenize text tiếng Việt cơ bản (word-level).

    Loại bỏ dấu câu, số, và stopwords.
    """
    # Lowercase và loại bỏ ký tự đặc biệt
    text = text.lower()
    text = re.sub(r"[^\w\sàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", " ", text)
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    words = text.split()

    # Loại bỏ stopwords và từ quá ngắn
    words = [w for w in words if w not in VIETNAMESE_STOPWORDS and len(w) > 1]

    return words


def _compute_ngrams(text: str, n: int = 2, top_k: int = 20) -> List[Tuple[str, int]]:
    """
    Tính n-grams từ text.

    Args:
        text: Văn bản đầu vào.
        n: Kích thước n-gram (2 hoặc 3).
        top_k: Số lượng n-grams trả về.

    Returns:
        List[(ngram_string, count)] sắp xếp giảm dần.
    """
    words = _tokenize_vietnamese(text)

    if len(words) < n:
        return []

    ngram_list = []
    for i in range(len(words) - n + 1):
        ngram = " ".join(words[i:i + n])
        ngram_list.append(ngram)

    counter = Counter(ngram_list)
    # Chỉ lấy n-grams xuất hiện ít nhất 2 lần
    filtered = [(ng, cnt) for ng, cnt in counter.most_common(top_k * 2) if cnt >= 2]

    return filtered[:top_k]


def _compute_cross_ngrams(
    competitors: List[Dict],
    n: int = 2,
    top_k: int = 20,
) -> List[Tuple[str, int]]:
    """
    Tính n-grams phổ biến CHUNG giữa nhiều đối thủ.

    N-grams xuất hiện ở nhiều đối thủ hơn sẽ được xếp hạng cao hơn.

    Returns:
        List[(ngram_string, competitor_count)] sắp xếp giảm dần.
    """
    # Đếm mỗi n-gram xuất hiện ở bao nhiêu competitors
    ngram_presence = Counter()

    for comp in competitors:
        body = comp.get("body_text", "")
        if not body:
            continue

        # Lấy unique n-grams cho competitor này
        ngrams = _compute_ngrams(body, n=n, top_k=50)
        unique_ngrams = set(ng for ng, _ in ngrams)

        for ng in unique_ngrams:
            ngram_presence[ng] += 1

    # Chỉ lấy n-grams xuất hiện ở ít nhất 2 competitors
    cross = [(ng, cnt) for ng, cnt in ngram_presence.most_common(top_k * 2) if cnt >= 2]

    return cross[:top_k]


# ══════════════════════════════════════════════
#  INFORMATION GAIN ANALYSIS
# ══════════════════════════════════════════════

def _find_common_headings(competitors: List[Dict]) -> List[str]:
    """
    Tìm heading patterns lặp lại ở nhiều đối thủ.

    Returns:
        Danh sách heading texts xuất hiện ở >= 2 đối thủ.
    """
    heading_counter = Counter()

    for comp in competitors:
        # Normalize headings cho comparison
        seen = set()
        for h in comp.get("headings", []):
            normalized = h["text"].lower().strip()
            # Loại bỏ số thứ tự đầu heading
            normalized = re.sub(r"^\d+[\.\)]\s*", "", normalized)
            if normalized and normalized not in seen:
                seen.add(normalized)
                heading_counter[normalized] += 1

    # Chỉ lấy headings xuất hiện ở >= 2 đối thủ
    common = [h for h, cnt in heading_counter.most_common(30) if cnt >= 2]
    return common


def _compute_semantic_voids_llm(competitors: List[Dict], topic: str) -> List[str]:
    """Sử dụng LLM để tìm Semantic Voids (Khoảng trống ngữ nghĩa) theo framework của Koray."""
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return []

        import openai
        import json
        from modules.semantic_knowledge import inject_semantic_prompt
        client = openai.OpenAI(api_key=api_key)

        # Lấy heading của top 10 đối thủ
        comp_text = ""
        for i, comp in enumerate(competitors[:MAX_COMPETITORS]):
            headings = [h["text"] for h in comp.get("headings", []) if h["level"] in ["H2", "H3"]]
            if headings:
                comp_text += f"\n-- Đối thủ {i+1} ({comp.get('url', 'Unknown')}):\n- " + "\n- ".join(headings)

        if not comp_text:
            return []

        base_system_instruction = (
            "Bạn là một Senior SEO Specialist & Topical Authority Expert (Koray Framework).\n"
            "Nhiệm vụ: Tìm ra [Semantic Voids] (Khoảng trống ngữ nghĩa) hay Information Gap của 1 chủ đề.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. Semantic Void/Information Gap KHÔNG PHẢI là bịa ra các chủ đề rác. Nó là những [Attribute Prominence] (thuộc tính sống còn) hoặc [Attribute Popularity] (thuộc tính được tìm kiếm nhiều) mà TẤT CẢ đối thủ hiện tại trên SERP đều THIẾU hoặc đề cập rất hời hợt.\n"
            "2. Mục tiêu là thoả mãn toàn diện Search Intent và đóng góp vào Information Gain (Giá trị thông tin mới).\n"
            "3. Gap phải sâu sắc, mang tính chuyên gia và bắt nguồn từ attribute thực của SERP/source context. KHÔNG dùng các Gap hời hợt như 'Kết luận', 'Tổng quan'.\n\n"
            "QUY TẮC CHI TIẾT:\n"
            "1. PROMINENCE GATE: Void phải pass — 'Entity có tồn tại mà KHÔNG cần attribute này không?' → Nếu CÓ thể tách → LOẠI.\n"
            "2. COVERAGE: Void phải cover Unique → Root → Rare attributes.\n"
            "3. INFORMATION GAIN: Void = attribute sau ma tat ca doi thu thieu. Dung attribute cu the co the kiem chung tu du lieu keyword hien tai.\n\n"
            "TRẢ VỀ JSON OBJECT theo format:\n"
            "{\"semantic_voids\": [{\"void\": \"tên void (≤8 từ)\", \"rationale\": \"tại sao đối thủ thiếu\", \"attribute_type\": \"root|rare|unique\", \"prominence_score\": 1-10}]}.\n"
            "CHỈ OUTPUT RA JSON OBJECT với format: {\"semantic_voids\": [{\"void\": \"...\", \"rationale\": \"...\", \"attribute_type\": \"root|rare|unique\", \"prominence_score\": 1-10}]}."
        )
        system_instruction = inject_semantic_prompt(base_system_instruction)

        user_content = (
            f"Chủ đề: '{topic}'\n\n"
            "Dưới đây là dàn ý bài viết của các đối thủ top đầu trên SERP:\n"
            f"{comp_text}\n\n"
            "Hãy phân tích và chỉ ra 3-5 Semantic Voids mà họ đang bỏ sót."
        )

        logger.info("  [INFORMATION GAIN] Gọi LLM để tìm Semantic Voids...")
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            temperature=0.4,
            max_tokens=500,
            timeout=60,
        )

        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        try:
            gaps_data = json.loads(raw_text.strip())
            gaps = gaps_data.get("semantic_voids", []) if isinstance(gaps_data, dict) else (gaps_data if isinstance(gaps_data, list) else [])
        except (json.JSONDecodeError, Exception):
            gaps = []
        if isinstance(gaps, list) and len(gaps) > 0:
            logger.info("  [INFORMATION GAIN] Đã tìm thấy %d Semantic Voids!", len(gaps))
            return gaps
        return []
    except Exception as e:
        logger.warning("  [INFORMATION GAIN] LLM lỗi (%s) -> Dùng Fallback.", str(e))
        return []


def _compute_information_gain(competitors: List[Dict], topic: str) -> Dict:
    """
    Tính toán Information Gain / Semantic Voids.

    Phase 20:
    - Ưu tiên LLM tìm Semantic Voids.
    - Fallback: Rare headings + content gaps tự tính toán.
    """
    # ── 1. Thử gọi LLM tìm Semantic Voids trước ──
    semantic_voids = _compute_semantic_voids_llm(competitors, topic)
    semantic_void_details = _normalize_semantic_voids(semantic_voids)

    # ── 2. Rare headings / Rule-based gaps (Fallback & bổ sung) ──
    heading_counter = Counter()
    for comp in competitors:
        for h in comp.get("headings", []):
            normalized = h["text"].lower().strip()
            normalized = re.sub(r"^\d+[\.\)]\s*", "", normalized)
            if normalized:
                heading_counter[normalized] += 1

    common_headings = {h for h, c in heading_counter.items() if c >= 2}
    rare_headings = {h for h, c in heading_counter.items() if c == 1}

    # Nếu LLM thành công, gán Semantic Voids vào rare_headings để content builder xài
    semantic_gap_labels = [item["heading"] for item in semantic_void_details if item.get("heading")]
    final_gaps = semantic_gap_labels if semantic_gap_labels else list(rare_headings)[:15]

    # ── 3. Unique n-grams (chỉ 1 đối thủ sử dụng) ──
    ngram_per_comp = {}
    for comp in competitors:
        body = comp.get("body_text", "")
        if body:
            ngrams = _compute_ngrams(body, n=2, top_k=30)
            ngram_per_comp[comp.get("url", "")] = set(ng for ng, _ in ngrams)

    all_ngrams_counter = Counter()
    for ng_set in ngram_per_comp.values():
        for ng in ng_set:
            all_ngrams_counter[ng] += 1

    unique_ngrams = [ng for ng, cnt in all_ngrams_counter.items() if cnt == 1]

    # ── 4. Content gaps (Missing common topics) ──
    content_gaps = []
    if common_headings:
        for comp in competitors:
            comp_headings = {
                re.sub(r"^\d+[\.\)]\s*", "", h["text"].lower().strip())
                for h in comp.get("headings", [])
            }
            missing = common_headings - comp_headings
            if missing:
                content_gaps.append({
                    "url": comp.get("url", ""),
                    "missing_topics": list(missing)[:5],
                })

    # ── 5. Coverage matrix ──
    coverage = {}
    for comp in competitors:
        url = comp.get("url", "")
        coverage[url] = {
            "heading_count": len(comp.get("headings", [])),
            "word_count": comp.get("word_count", 0),
            "h2_count": sum(1 for h in comp.get("headings", []) if h["level"] == "H2"),
            "h3_count": sum(1 for h in comp.get("headings", []) if h["level"] == "H3"),
        }

    return {
        "content_gaps": content_gaps,
        "rare_headings": final_gaps,  # Dùng tên key cũ để không break API
        "semantic_voids": semantic_void_details,
        "unique_ngrams": unique_ngrams[:15],
        "coverage_matrix": coverage,
    }
