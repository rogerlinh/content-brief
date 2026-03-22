# -*- coding: utf-8 -*-
"""
query_network.py - Mở rộng từ khóa và phân cụm bằng LLM (Semantic Keyword Network).

Mục tiêu:
1. Sinh Query Templates để mở rộng các ngữ cảnh xung quanh Central Entity.
2. Fetch các từ khóa liên quan (giả lập SEO API thông qua Google Autocomplete).
3. Sử dụng LLM để cluster (phân nhóm) các từ khóa có cùng Search Intent và
   Ngữ cảnh, nhằm giải quyết tình trạng Keyword Cannibalization (ăn thịt từ khóa).

Usage:
    from modules.query_network import analyze_query_network

    network_data = analyze_query_network("thép tấm")
"""

import json
import logging
import random
import time
from typing import Dict, List
import requests
from config import LLM_CONFIG

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────
GOOGLE_AUTOCOMPLETE_URL = "http://suggestqueries.google.com/complete/search"

# Các template mở rộng ngữ cảnh
QUERY_TEMPLATES = [
    "{entity}",
    "{entity} là gì",
    "có nên mua {entity}",
    "{entity} cho",      # Mở rộng đối tượng/ứng dụng (cho xe hơi, cho xây dựng...)
    "{entity} ở",       # Mở rộng địa điểm
    "{entity} tại",     # Mở rộng địa điểm
    "{entity} với",     # Mở rộng chất liệu/kết hợp
    "{entity} loại",    # Mở rộng phân loại
    "giá {entity}",      # Intent mua bán
    "mua {entity}",
    "cách chọn {entity}"
]


# ══════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════

def analyze_query_network(entity: str) -> Dict:
    """
    Thực hiện đầy đủ quy trình mở rộng và phân nhóm keyword.

    Args:
        entity: Thực thể trung tâm (VD: "thép tấm").

    Returns:
        Dict chứa:
        - raw_keywords: Danh sách tất cả từ khóa thu thập được.
        - total_fetched: Tổng số lượng keyword.
        - clusters: Dict chứa cấu trúc phân cụm từ LLM.
    """
    logger.info("  [NETWORK] Bắt đầu phân tích Query Network cho: '%s'", entity)

    # 1. Sinh Query Templates
    templates = _generate_query_templates(entity)
    logger.info("  [NETWORK] Đã tạo %d query templates", len(templates))

    # 2. Fetch từ khóa từ mỗi template
    all_keywords = set()
    for raw_query in templates:
        kws = _fetch_autocomplete_keywords(raw_query)
        all_keywords.update(kws)
        # Nghỉ chút để tránh rate limit
        time.sleep(0.2)

    all_keywords_list = sorted(list(all_keywords))
    logger.info("  [NETWORK] Đã thu thập %d từ khóa liên quan (unique)", len(all_keywords_list))

    # Giới hạn số lượng keyword gửi lên LLM để tiết kiệm token/thời gian
    # Nếu list quá dài, lấy random sample
    max_kws_for_llm = 80
    if len(all_keywords_list) > max_kws_for_llm:
        # Giữ lại keyword chứa entity chính xác và sample phần còn lại
        prioritized = [k for k in all_keywords_list if entity.lower() in k.lower()]
        others = [k for k in all_keywords_list if k not in prioritized]

        if len(prioritized) > max_kws_for_llm:
            chosen_keywords = random.sample(prioritized, max_kws_for_llm)
        else:
            needed = max_kws_for_llm - len(prioritized)
            sampled_others = random.sample(others, needed) if len(others) >= needed else others
            chosen_keywords = prioritized + sampled_others
    else:
        chosen_keywords = all_keywords_list

    # 3. Cluster với LLM
    clusters = _cluster_keywords_with_llm(chosen_keywords, entity)

    result = {
        "raw_keywords": all_keywords_list,
        "total_fetched": len(all_keywords_list),
        "clustered_kws_count": len(chosen_keywords),
        "clusters": clusters
    }

    num_clusters = len(clusters.get("clusters", [])) if "error" not in clusters else 0
    logger.info("  [NETWORK] Hoàn tất clustering: %d cụm", num_clusters)

    return result


# ══════════════════════════════════════════════
#  PRIVATE HELPERS
# ══════════════════════════════════════════════

def _generate_query_templates(entity: str) -> List[str]:
    """Sử dụng rule-base để nối thực thể với các template (modifier)."""
    return [tmpl.format(entity=entity) for tmpl in QUERY_TEMPLATES]


def _fetch_autocomplete_keywords(query: str) -> List[str]:
    """
    Lấy danh sách từ khóa gợi ý từ Google Autocomplete.

    (Giả lập việc sử dụng API SEO như Ahrefs/Semrush)
    """
    params = {
        "client": "chrome",
        "hl": "vi",
        "q": query
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(GOOGLE_AUTOCOMPLETE_URL, params=params, headers=headers, timeout=5)
        if response.status_code == 200:
            # Response format: ["query", ["kw1", "kw2", ...]]
            data = response.json()
            if len(data) > 1 and isinstance(data[1], list):
                # Clean up keywords
                kws = [kw.lower().strip() for kw in data[1]]
                return [k for k in kws if len(k) > 3]
    except Exception as e:
        logger.debug("  [NETWORK] Error fetching autocomplete cho '%s': %s", query, str(e))

    return []


def _cluster_keywords_with_llm(keywords: List[str], entity: str) -> Dict:
    """
    Gửi danh sách từ khóa lên LLM để phân cụm theo Ngữ cảnh và Ý định (Intent).
    Giải quyết vấn đề Keyword Cannibalization bằng cách xác định các biến thể.
    """
    if not OpenAI:
        logger.warning("  [NETWORK] Thiếu thư viện 'openai'. Bỏ qua LLM clustering.")
        return {"error": "Missing openai library"}

    api_key = LLM_CONFIG.get("api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.warning("  [NETWORK] OPENAI_API_KEY chưa được cấu hình. Bỏ qua LLM clustering.")
        return {"error": "Missing OpenAI API Key"}

    client = OpenAI(
        api_key=api_key,
        base_url=LLM_CONFIG.get("base_url") if LLM_CONFIG.get("base_url") else None
    )

    kw_list_str = "\n".join([f"- {kw}" for kw in keywords])

    system_prompt = (
        "Bạn là một chuyên gia Semantic SEO (Koray Framework).\n"
        "Mục tiêu của bạn là phân nhóm (cluster) một danh sách từ khóa để tối ưu Semantic Keyword Network và ngăn Keyword Cannibalization.\n"
        "Quy tắc phân nhóm BẮT BUỘC:\n"
        "1. Nhóm từ khóa theo LỘ TRÌNH TÌM KIẾM (Query Path) và TRUY VẤN TUẦN TỰ (Sequential Queries): Các từ khóa mà người dùng thường tìm kiếm nối tiếp nhau trong cùng 1 hành trình (Ví dụ: tìm 'thép tấm là gì' xong sẽ tìm 'kích thước thép tấm') phải được phân tách rõ ràng theo intent.\n"
        "2. Từ khóa có cùng Ngữ cảnh (Context) và Ý định (Search Intent) GẦN NHƯ TUYỆT ĐỐI mới được gom chung thành 1 cụm (để tập trung giải quyết 1 Micro-context).\n"
        "3. Xét XÁC SUẤT ĐỒNG XUẤT HIỆN (Correlative Queries): Nhóm những từ có xác suất cao được tìm kiếm cùng nhau.\n"
        "4. Tên Cluster phải phản ánh rõ Ý định (VD: 'Bảng giá [Topic] MỚI NHẤT', 'Hướng dẫn kỹ thuật [Topic]').\n"
        "5. Phân tích rõ Search Intent của cụm đó (Informational, Transactional, Commercial, Navigational).\n"
        "\n"
        "Phản hồi của bạn PHẢI LUÔN LÀ một chuỗi JSON hợp lệ với cấu trúc sau (KHÔNG thêm markdown hay text bên ngoài):\n"
        "{\n"
        '  "clusters": [\n'
        "    {\n"
        '      "cluster_name": "Tên nhóm chủ đề",\n'
        '      "intent": "Loại intent",\n'
        '      "primary_keyword": "Từ khóa tốt nhất đại diện",\n'
        '      "variants": ["biến thể 1", "biến thể 2", ...]\n'
        "    }\n"
        "  ]\n"
        "}"
    )

    user_prompt = f"Thực thể trung tâm: '{entity}'.\n\nHãy phân nhóm các từ khóa sau:\n{kw_list_str}"

    try:
        logger.info("  [NETWORK] Đang gửi %d keywords tới LLM (%s)...", len(keywords), LLM_CONFIG.get("model"))
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2, # Low temperature cho kết quả phân loại ổn định
            response_format={"type": "json_object"},
            timeout=60,  # Phase 16: tránh treo mãi mãi
        )

        content = response.choices[0].message.content
        clusters = json.loads(content)
        return clusters

    except Exception as e:
        logger.error("  [NETWORK] LLM Clustering error: %s", str(e))
        return {"error": f"LLM Error: {str(e)}"}
