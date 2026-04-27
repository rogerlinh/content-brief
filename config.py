# -*- coding: utf-8 -*-
"""
Shared configuration for the Content Brief Generator pipeline.
"""

import logging
import os

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)
except ImportError:
    pass


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOPICS_CSV = os.path.join(BASE_DIR, "topics.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
SKILL_FILE = os.path.join(BASE_DIR, "skill.md")

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

SEARCH_INTENT_KEYWORDS = {
    "informational": [
        "là gì",
        "là sao",
        "thế nào",
        "tại sao",
        "vì sao",
        "cách",
        "hướng dẫn",
        "thông tin",
        "tìm hiểu",
        "kiến thức",
        "ý nghĩa",
        "khái niệm",
        "định nghĩa",
        "tổng quan",
        "nguyên nhân",
        "tác dụng",
        "lịch sử",
        "đặc điểm",
        "phân loại",
        "cấu tạo",
        "nguyên lý",
        "quy trình",
        "ưu nhược điểm",
        "lợi ích",
        "tác hại",
        "bao lâu",
        "khi nào",
        "ở đâu",
    ],
    "commercial": [
        "top",
        "tốt nhất",
        "đánh giá",
        "review",
        "nên mua",
        "lựa chọn",
        "phổ biến",
        "ưu điểm",
        "nhược điểm",
        "so sánh",
        "khác nhau",
        "khác gì",
        "giống nhau",
        "khác biệt",
        "phân biệt",
        "nên chọn",
        "tốt hơn",
        "so với",
        "hay là",
        "hoặc là",
        "vs",
        "bảng giá",
        "chi phí",
        "giá bao nhiêu",
        "loại nào tốt",
        "hãng nào",
        "thương hiệu nào",
        "kinh nghiệm",
        "chia sẻ",
        "feedback",
    ],
    "transactional": [
        "mua",
        "giá",
        "báo giá",
        "đặt hàng",
        "order",
        "bán",
        "cung cấp",
        "phân phối",
        "đặt mua",
        "liên hệ",
        "tư vấn",
        "dịch vụ",
        "thuê",
        "tải",
        "đăng ký",
        "đặt lịch",
        "khuyến mãi",
        "giảm giá",
        "voucher",
        "coupon",
        "freeship",
        "giao hàng",
        "thanh toán",
    ],
    "navigational": [
        "website",
        "trang chủ",
        "địa chỉ",
        "thương hiệu",
        "chi nhánh",
        "showroom",
        "cửa hàng",
        "đại lý",
        "hotline",
        "fanpage",
        "facebook",
        "zalo",
        "app",
        "ứng dụng",
        "phần mềm",
    ],
}

SERP_ANALYSIS_DIR = os.path.join(BASE_DIR, "serp_cache")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")

SERP_CONFIG = {
    "max_competitors": 4,
    "search_delay_seconds": 3,
    "locale": "vi-VN",
    "search_params": "hl=vi&gl=vn",
    "headless": True,
    "page_timeout_ms": 30000,
}

LLM_CONFIG = {
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "model": "gpt-4o-mini",
}

TOPICAL_MAP_CSV = os.path.join(BASE_DIR, "topical_map.csv")

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=[logging.StreamHandler()],
    )
