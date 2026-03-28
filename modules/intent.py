# -*- coding: utf-8 -*-
"""
modules/intent.py — Phase 2.2

Single source of truth cho Intent detection và normalization.
Trước đây intent strings được xử lý không nhất quán ở 4 file khác nhau:
  - config.py (SEARCH_INTENT_KEYWORDS dict)
  - content_brief_builder.py (intent merge logic)
  - koray_analyzer.py (INTENT_H2_MINIMUMS)
  - main_generator.py (auto_detect_methodology)

Bây giờ tất cả dùng chung 3 functions:
  - detect_intent(topic: str) -> str
  - normalize_intent(intent_str: str) -> str
  - get_h2_minimum(intent: str) -> int
"""

from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────────────────
#  INTENT KEYWORD DICTIONARIES
# ──────────────────────────────────────────────────────────────────────────
_COMMERCIAL_KW = frozenset({
    "mua", "bán", "giá", "bao nhiêu", "báo giá", "bảng giá",
    "địa chỉ bán", "nơi bán", "shop", "store", "order", "đặt hàng",
    "cửa hàng", "đại lý", "nhà phân phối", "chi phí", "hải quan",
    "thuế nhập khẩu", "báo giá nhôm", "báo giá thép",
})
_INFORMATIONAL_KW = frozenset({
    "là gì", "thế nào", "như thế nào", "cách", "hướng dẫn",
    "so sánh", "đánh giá", "review", "tại sao", "vì sao",
    "khi nào", "ở đâu", "ra sao", "khác gì", "khác nhau",
    "phân biệt", "ưu điểm", "nhược điểm", "tính năng",
    "cấu tạo", "thành phần", "quy trình", "công nghệ",
})
_TRANSACTIONAL_KW = frozenset({
    "mua ở đâu", "đặt mua", "order", "mua online", "ship",
    "giao hàng", "thanh toán", "trả góp", "mua ngay",
    "thuê", "cho thuê", "bán", "thanh lý",
})
_NAVIGATIONAL_KW = frozenset({
    "website", "trang chủ", "đăng nhập", "liên hệ",
    "thep", "inox", "website", "trang",
})


def detect_intent(topic: str) -> str:
    """
    Phat hien search intent tu topic string.

    Args:
        topic: Chuoi keyword can phan tich

    Returns:
        Mot trong: "informational" | "commercial" | "transactional" | "navigational"
    """
    # Phase 36: Guard None/empty input -> default informational
    if not topic or not str(topic).strip():
        return "informational"

    t = topic.lower().strip()

    # "vs" / so sanh -> commercial (needs comparison outline)
    if re.search(r"\bvs\b|\bvới\b|\bso sánh\b|\bvs\s+\w", t):
        return "commercial"

    # Navigational (check first)
    if any(kw in t for kw in _NAVIGATIONAL_KW):
        if any(kw in t for kw in _COMMERCIAL_KW):
            return "commercial"
        return "navigational"

    # Transactional
    if any(kw in t for kw in _TRANSACTIONAL_KW):
        return "transactional"

    # Commercial (giá/bao giá)
    if any(kw in t for kw in _COMMERCIAL_KW):
        return "commercial"

    # Default: informational
    if any(kw in t for kw in _INFORMATIONAL_KW):
        return "informational"

    return "informational"


def normalize_intent(intent_str: str) -> str:
    """
    Chuan hoa intent string ve canonical form.
    Xu ly cac variants: "vs", "comparison", "informational", etc.

    Args:
        intent_str: Raw intent string (tu SERP analysis, user input, etc.)

    Returns:
        Canonical form: "commercial", "informational", "transactional", "navigational"
    """
    if not intent_str:
        return "informational"

    s = str(intent_str).lower().strip()

    _intent_map = {
        "vs": "commercial",
        "comparison": "commercial",
        "commercial": "commercial",
        "giao dich": "transactional",
        "transaction": "transactional",
        "transactional": "transactional",
        "thông tin": "informational",
        "informational": "informational",
        "hướng dẫn": "informational",
        "điều hướng": "navigational",
        "navigational": "navigational",
        "navigation": "navigational",
    }

    for key, canonical in _intent_map.items():
        if key in s:
            return canonical

    return "informational"


def get_h2_minimum(intent: str) -> int:
    """
    Tra ve so H2 toi thieu can co theo intent type.

    Args:
        intent: Canonical intent string

    Returns:
        Minimum H2 count (int)
    """
    _min_map = {
        "commercial": 5,
        "informational": 4,
        "transactional": 3,
        "navigational": 2,
    }
    return _min_map.get(normalize_intent(intent), 4)


def intent_to_methodology(intent: str, topic: str = "") -> str:
    """
    Map intent to recommended writing methodology.

    Args:
        intent: Canonical intent string
        topic: Full topic string (optional)

    Returns:
        Methodology key: "evidence_based", "product_review", "step_by_step", "comparative", "general"
    """
    norm = normalize_intent(intent)

    if norm == "commercial":
        if topic and re.search(r"\bvs\b|\bso sánh\b", topic.lower()):
            return "comparative"
        return "product_review"

    if norm == "transactional":
        return "step_by_step"

    if norm == "informational":
        if topic and re.search(r"\bcách\b|\bhướng dẫn\b|\bquy trình\b", topic.lower()):
            return "step_by_step"
        if topic and re.search(r"\bđánh giá\b|\breview\b", topic.lower()):
            return "evidence_based"
        return "evidence_based"

    return "general"
