# -*- coding: utf-8 -*-
"""
serp_competitor_analyzer.py - Phân tích SERP Google và đối thủ cạnh tranh.

Sử dụng Playwright để:
1. Scrape Google SERP: organic results, PAA, Things to Know, Related Searches
2. Truy cập top 4 đối thủ: heading structure, n-grams, Information Gain

Usage:
    from modules.serp_competitor_analyzer import analyze_serp, analyze_competitors

    serp_data = analyze_serp("thép tấm là gì")
    competitor_data = analyze_competitors(serp_data["top_urls"], "thép tấm là gì")
"""

import asyncio
import logging
import re
import requests
from collections import Counter
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────
GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}&hl=vi&gl=vn"
SERPER_API_URL = "https://google.serper.dev/search"
MAX_COMPETITORS = 5
REQUEST_DELAY_SECONDS = 3
PAGE_TIMEOUT_MS = 30000
HEADLESS = True

# Import API key từ config
try:
    from config import SERPER_API_KEY
except ImportError:
    SERPER_API_KEY = ""

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
        - top_urls: List[str] (top 4 URLs cho competitor analysis)
        - serp_entities: Dict (primary, secondary entities)
        - serp_attributes: List[str]
        - topic_clusters: List[str]
        - dominant_intent: str
    """
    logger.info("  [SERP] Bắt đầu phân tích SERP cho: '%s'", topic)
    raw_serp = asyncio.run(_scrape_google_serp(topic, headless))

    # Phân tích dữ liệu từ SERP
    entities = _extract_entities_from_serp(raw_serp, topic)
    attributes = _extract_attributes_from_serp(raw_serp)
    clusters = _extract_topic_clusters(raw_serp)
    intent = _classify_serp_intent(raw_serp)

    # Lấy top URLs (loại bỏ các trang không phải bài viết)
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
        "dominant_intent": intent,
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
        urls: Danh sách URLs đối thủ (tối đa 4).
        topic: Chủ đề gốc (để tính Information Gain).
        headless: Chạy browser ẩn (True) hoặc hiện (False).

    Returns:
        Dict chứa:
        - competitors: List[dict] — dữ liệu từng đối thủ
        - common_headings: List[str] — heading patterns lặp lại
        - ngrams_2: List[tuple] — top 2-grams phổ biến
        - ngrams_3: List[tuple] — top 3-grams phổ biến
        - information_gain: Dict — khoảng trống nội dung
    """
    logger.info("  [COMPETITOR] Bắt đầu phân tích %d đối thủ...", len(urls))

    competitors_data = asyncio.run(_scrape_competitors(urls, headless))

    # Tổng hợp phân tích cross-competitor
    common_headings = _find_common_headings(competitors_data)
    ngrams_2 = _compute_cross_ngrams(competitors_data, n=2)
    ngrams_3 = _compute_cross_ngrams(competitors_data, n=3)
    info_gain = _compute_information_gain(competitors_data, topic)

    result = {
        "competitors": competitors_data,
        "common_headings": common_headings,
        "ngrams_2": ngrams_2,
        "ngrams_3": ngrams_3,
        "information_gain": info_gain,
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
    if not SERPER_API_KEY:
        logger.error("  [SERP] SERPER_API_KEY chưa được cấu hình! Kiểm tra config.py")
        return {
            "organic_results": [],
            "people_also_ask": [],
            "things_to_know": [],
            "related_searches": [],
        }

    logger.info("  [SERP] Gọi Serper.dev API cho: '%s'", topic)

    # Cấu trúc rỗng mặc định – trả về nếu bất kỳ lỗi nào xảy ra
    EMPTY_SERP = {
        "organic_results": [],
        "people_also_ask": [],
        "things_to_know": [],
        "related_searches": [],
    }

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

    logger.info("  [SERP] Serper.dev → %d organic, %d PAA, %d related, %d TTK",
                len(organic), len(paa), len(related), len(things))

    return {
        "organic_results": organic,
        "people_also_ask": paa,
        "things_to_know": things,
        "related_searches": related,
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
    Scrape nội dung từ top đối thủ bằng Playwright (async).

    Returns:
        List of competitor data dicts.
    """
    from playwright.async_api import async_playwright

    competitors = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )

        for i, url in enumerate(urls[:MAX_COMPETITORS]):
            logger.info("  [COMPETITOR %d/%d] Truy cập: %s",
                        i + 1, len(urls), url[:80])
            try:
                page = await context.new_page()
                await page.goto(url, timeout=PAGE_TIMEOUT_MS,
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Trích xuất headings
                headings = await _extract_page_headings(page)

                # Trích xuất body text
                body_text = await _extract_body_text(page)

                # Tính n-grams cho competitor này
                ngrams_2 = _compute_ngrams(body_text, n=2)
                ngrams_3 = _compute_ngrams(body_text, n=3)

                competitors.append({
                    "url": url,
                    "headings": headings,
                    "body_text": body_text,
                    "word_count": len(body_text.split()),
                    "ngrams_2": ngrams_2[:20],
                    "ngrams_3": ngrams_3[:20],
                })

                logger.info("  [COMPETITOR %d/%d] → %d headings, %d words",
                            i + 1, len(urls), len(headings),
                            len(body_text.split()))

                await page.close()

                # Delay giữa các request
                if i < len(urls) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

            except Exception as e:
                logger.warning("  [COMPETITOR %d/%d] Lỗi: %s",
                               i + 1, len(urls), str(e))
                competitors.append({
                    "url": url,
                    "headings": [],
                    "body_text": "",
                    "word_count": 0,
                    "ngrams_2": [],
                    "ngrams_3": [],
                    "error": str(e),
                })

        await browser.close()

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
        await page.evaluate("""
            () => {
                const selectors = [
                    'nav', 'header', 'footer', 'aside',
                    '.sidebar', '.navigation', '.menu',
                    '.comment', '.comments', '.related-posts',
                    'script', 'style', 'noscript', 'iframe',
                    '.advertisement', '.ads', '.ad-container',
                ];
                selectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });
            }
        """)

        # Trích xuất text từ main content area
        content_selectors = [
            "article",
            "main",
            "[role='main']",
            ".post-content",
            ".entry-content",
            ".article-content",
            ".content",
            "#content",
        ]

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


def _classify_serp_intent(serp_data: Dict) -> str:
    """
    Phân loại dominant intent từ SERP features và organic results.

    Logic:
    - Nhiều titles/snippets có "so sánh", "khác nhau" → VS
    - Nhiều PAA + Things to Know → Informational
    - Nhiều product listings, reviews → Commercial
    """
    organic = serp_data.get("organic_results", [])
    paa_count = len(serp_data.get("people_also_ask", []))
    ttk_count = len(serp_data.get("things_to_know", []))

    # Đếm signals từ titles/snippets
    commercial_signals = 0
    informational_signals = 0
    vs_signals = 0

    commercial_keywords = ["giá", "mua", "bán", "top", "tốt nhất", "review", "đánh giá"]
    informational_keywords = ["là gì", "hướng dẫn", "cách", "thông tin", "tìm hiểu"]
    vs_keywords = ["so sánh", "khác nhau", "vs", "khác gì", "hay là", "khác biệt",
                    "nên chọn", "so với", "phân biệt"]

    for result in organic:
        text = (result.get("title", "") + " " + result.get("snippet", "")).lower()
        commercial_signals += sum(1 for kw in commercial_keywords if kw in text)
        informational_signals += sum(1 for kw in informational_keywords if kw in text)
        vs_signals += sum(1 for kw in vs_keywords if kw in text)

    # PAA và Things to Know là strong signals cho informational
    informational_signals += paa_count * 2 + ttk_count * 2

    # VS wins nếu nhiều organic results chứa comparison keywords
    if vs_signals >= 3:
        return "vs"
    elif commercial_signals > informational_signals:
        return "commercial investigation"
    else:
        return "informational"


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

        # Lấy heading của top 5 đối thủ
        comp_text = ""
        for i, comp in enumerate(competitors[:5]):
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
            "3. Gap phải sâu sắc, mang tính chuyên gia (Ví dụ: 'Bảng dung sai kích thước', 'Quy trình cắt xả băng', 'Cảnh báo an toàn thi công'). KHÔNG dùng các Gap hời hợt như 'Kết luận', 'Tổng quan'.\n\n"
            "TRẢ VỀ JSON ARRAY chứa các chuỗi (tối đa 5-7 từ/chuỗi) mô tả các Semantic Voids.\n"
            "Ví dụ: [\"Bảng dung sai kích thước\", \"Quy trình cắt xả băng\", \"Cảnh báo an toàn thi công\"]\n"
            "CHỈ OUTPUT RA ARRAY JSON NGUYÊN THỦY (Không có ```json)."
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
        
        gaps = json.loads(raw_text.strip())
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
    final_gaps = semantic_voids if semantic_voids else list(rare_headings)[:15]

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
        "unique_ngrams": unique_ngrams[:15],
        "coverage_matrix": coverage,
    }
