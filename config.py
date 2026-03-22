# -*- coding: utf-8 -*-
"""
config.py - Cấu hình chung cho Content Brief Generator.

Chứa các đường dẫn, template, và cấu hình logging
cho toàn bộ pipeline.

API Keys được đọc từ file .env (cùng thư mục).
Sửa file .env để thay đổi key mà KHÔNG cần sửa code.
"""

import os
import logging

# ── Load .env file (nếu có) ──
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
except ImportError:
    pass  # python-dotenv chưa cài → dùng os.environ trực tiếp

# ──────────────────────────────────────────────
#  PATHS
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOPICS_CSV = os.path.join(BASE_DIR, "topics.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SKILL_FILE = os.path.join(BASE_DIR, "skill.md")

# ──────────────────────────────────────────────
#  CONTENT BRIEF TEMPLATE SECTIONS
# ──────────────────────────────────────────────
BRIEF_SECTIONS = [
    "title_tag",
    "meta_description",
    "search_intent",
    "central_entity",
    "entity_attributes",
    "heading_structure",
    "content_guidelines",
    "suggested_questions",
    "internal_linking",
    "eeat_checklist",
]

# Mapping ý định tìm kiếm (Search Intent) — 4 loại chuẩn
# Priority scoring: transactional > commercial > navigational > informational
SEARCH_INTENT_KEYWORDS = {
    "informational": [
        # Người dùng tìm hiểu, nghiên cứu → Tối ưu blog, guide, FAQ
        "là gì", "là sao", "thế nào", "tại sao", "vì sao",
        "cách", "hướng dẫn", "thông tin", "tìm hiểu", "kiến thức",
        "ý nghĩa", "khái niệm", "định nghĩa", "tổng quan",
        "nguyên nhân", "tác dụng", "lịch sử", "đặc điểm",
        "phân loại", "cấu tạo", "nguyên lý", "quy trình",
        "ưu nhược điểm", "lợi ích", "tác hại",
        "bao lâu", "khi nào", "ở đâu",
    ],
    "commercial": [
        # Người dùng đang cân nhắc mua → Tạo trang so sánh, review, bảng giá
        # (Bao gồm cả intent "vs/comparison" — đây là Commercial Investigation)
        "top", "tốt nhất", "đánh giá", "review",
        "nên mua", "lựa chọn", "phổ biến", "ưu điểm", "nhược điểm",
        "so sánh", "khác nhau", "khác gì", "giống nhau", "khác biệt",
        "phân biệt", "nên chọn", "tốt hơn", "so với",
        "hay là", "hoặc là", "vs",
        "bảng giá", "chi phí", "giá bao nhiêu",
        "loại nào tốt", "hãng nào", "thương hiệu nào",
        "kinh nghiệm", "chia sẻ", "feedback",
    ],
    "transactional": [
        # Người dùng sẵn sàng mua / đặt → Tối ưu landing page, CTA mạnh
        "mua", "giá", "báo giá", "đặt hàng", "order",
        "bán", "cung cấp", "phân phối",
        "đặt mua", "liên hệ", "tư vấn", "dịch vụ",
        "thuê", "tải", "đăng ký", "đặt lịch",
        "khuyến mãi", "giảm giá", "voucher", "coupon",
        "freeship", "giao hàng", "thanh toán",
    ],
    "navigational": [
        # Tìm thương hiệu cụ thể → Tối ưu brand SEO, Google My Business
        "website", "trang chủ", "địa chỉ",
        "thương hiệu", "chi nhánh", "showroom",
        "cửa hàng", "đại lý", "hotline",
        "fanpage", "facebook", "zalo",
        "app", "ứng dụng", "phần mềm",
    ],
}

# ──────────────────────────────────────────────
#  SERP ANALYSIS CONFIG
# ──────────────────────────────────────────────
SERP_ANALYSIS_DIR = os.path.join(BASE_DIR, "serp_cache")

# Serper.dev API Key — đọc từ .env (KHÔNG hardcode)
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

SERP_CONFIG = {
    "max_competitors": 4,           # Số đối thủ tối đa để phân tích
    "search_delay_seconds": 3,      # Delay giữa các request (tránh rate-limit)
    "locale": "vi-VN",              # Locale cho Google Search
    "search_params": "hl=vi&gl=vn", # Google Search params
    "headless": True,               # Chạy browser ẩn (cho competitor scraping)
    "page_timeout_ms": 30000,       # Timeout cho mỗi page load
}

# ──────────────────────────────────────────────
#  LLM CONFIG (cho Query Network)
# ──────────────────────────────────────────────
LLM_CONFIG = {
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "model": "gpt-4o-mini",
    # "base_url": "https://api.openai.com/v1",  # URL tuỳ chỉnh cho proxy/liteLLM
}

# ---------------------------------------------------------
# CẤU HÌNH INTERNAL LINKING (PHASE 5)
# ---------------------------------------------------------

TOPICAL_MAP_CSV = os.path.join(BASE_DIR, "topical_map.csv")


# ---------------------------------------------------------
# THIẾT LẬP LOGGING
# ---------------------------------------------------------
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Thiết lập logging cho toàn bộ pipeline."""
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler()],
    )
