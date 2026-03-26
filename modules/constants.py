# -*- coding: utf-8 -*-
"""
constants.py — Shared constants across all modules.

Hợp nhất tất cả magic numbers, stopwords, blacklists,
và hardcoded thresholds vào một chỗ để dễ bảo trì.

P2c REFACTOR: Tách khỏi content_brief_builder.py
"""

# ══════════════════════════════════════════════
#  STOPWORDS
# ══════════════════════════════════════════════

# Vietnamese + English stopwords dùng trong N-gram tokenization
VIETNAMESE_STOPWORDS = frozenset({
    "là", "và", "của", "có", "được", "các", "cho", "này", "với", "từ",
    "không", "đến", "trong", "một", "những", "khi", "để", "theo", "hay",
    "hoặc", "về", "như", "đã", "sẽ", "bị", "cũng", "nhất", "rất", "tại",
    "nên", "làm", "ra", "nào", "lên", "còn", "sau", "trước", "vào",
    "bằng", "thì", "mà", "đó", "nhiều", "do", "qua", "giữa",
    "nếu", "vì", "hơn", "dù", "luôn", "đều", "thường", "gì",
    "the", "and", "of", "is", "in", "to", "for", "on", "with", "that",
})

# Phrase-level stopwords (dùng trong N-gram classification — loại bỏ fragments vô nghĩa)
NGRAM_STOPWORDS = frozenset({
    "tuy nhiên", "ngoài ra", "bên cạnh", "trong đó", "chẳng hạn",
    "vì vậy", "do đó", "cũng như", "hơn nữa", "mặc dù",
    "thể sử dụng", "lại lợi ích", "độ ăn",  # fragments vô nghĩa
})

# ══════════════════════════════════════════════
#  BLACKLISTS
# ══════════════════════════════════════════════

# Navigation junk headings — bị scrape nhầm từ competitor sites
NAVIGATION_HEADING_BLACKLIST = frozenset({
    "liên kết nhanh", "liên hệ", "chi nhánh", "đăng ký", "đăng nhập",
    "hỗ trợ trực tuyến", "hỗ trợ khách hàng", "hotline", "bản đồ",
    "về chúng tôi", "thông tin liên hệ", "danh mục", "danh mục sản phẩm",
    "tải xuống", "sản phẩm liên quan", "tin tức", "tin tức nổi bật",
    "tin tức & sự kiện", "hình ảnh công ty", "bài viết cùng chủ đề",
    "quick link", "phòng kinh doanh", "trụ sở chính", "đăng ký nhận",
    "bình luận", "để lại một bình luận", "mạ kẽm nhúng nóng",
    # Additional from content_brief_builder.py:
    "phụ kiện thép", "tôn lợp", "tôn mát", "từ khóa",
    "các sự kiện liên quan", "các bài viết liên quan", "danh mục tin tức",
    "đăng ký nhận tin", "mô tả",
})

# Procedural/operational patterns — không phù hợp cho informational intent
PROCEDURAL_PATTERNS = (
    "quy trình", "hướng dẫn bảo trì", "bảo dưỡng định kỳ",
    "kiểm định", "kiểm tra chất lượng", "cảnh báo an toàn",
    "hướng dẫn sử dụng", "cách xử lý sự cố", "lịch bảo dưỡng",
    "checklist", "biên bản nghiệm thu", "sổ tay vận hành",
)

# B2B junk topics — generic content không phù hợp cho site thương mại
# Dùng trong _postprocess_prominence_blacklist
B2B_JUNK_TERMS = frozenset({
    "tác động môi trường", "tác động đến môi trường",
    "ảnh hưởng môi trường", "carbon footprint",
    "khí thải", "tái chế", "bền vững", "xây dựng bền vững",
    "phát triển bền vững", "biến đổi khí hậu",
    "lịch sử phát minh", "lịch sử phát triển",
    "lợi ích môi trường", "lợi ích cho môi trường",
    "thân thiện môi trường", "giảm thiểu khí thải",
    "quy trình sản xuất", "quy trình chế tạo", "công nghệ sản xuất",
})

# Universal junk terms (dùng cho cả B2C và B2B)
UNIVERSAL_JUNK_TERMS = frozenset({
    "tác động môi trường", "tác động đến môi trường",
    "ảnh hưởng môi trường", "carbon footprint",
})

# B2B topic signals for auto-detection (khi project=None)
B2B_TOPIC_SIGNALS = frozenset({
    "thép", "sắt", "xi măng", "tôn", "xà gồ", "ống",
    "vật liệu", "bê tông", "gạch", "kính", "nhôm",
    "thiết bị y tế", "dược phẩm", "hóa chất", "máy móc",
    "phần mềm doanh nghiệp", "erp", "crm", "logistics",
    "nguyên liệu", "bao bì", "đóng gói",
})

# B2B industry signals for Source Context detection
B2B_INDUSTRY_SIGNALS = frozenset({
    "phân phối", "cung cấp", "b2b", "đại lý", "nhà máy", "sản xuất",
    "thi công", "logistics", "saas", "enterprise", "wholesale", "oem",
    "nhập khẩu", "xuất khẩu", "công nghiệp", "manufacturer", "distributor",
})


# ══════════════════════════════════════════════
#  N-GRAM HELPERS
# ══════════════════════════════════════════════

# Action verbs — N-grams chứa verbs này → classified là "action"
ACTION_VERBS = frozenset({
    "bổ sung", "chế biến", "nấu", "sử dụng", "lựa chọn",
    "kết hợp", "giảm", "tăng", "cải thiện", "phòng ngừa",
    "điều trị", "bảo quản", "chọn mua", "so sánh", "đánh giá",
    "hướng dẫn", "cách", "làm", "tạo", "xây dựng",
})

# Invalid N-gram suffixes (fragments không mang nghĩa)
NGRAM_INVALID_SUFFIXES = frozenset({
    " oxy", " ên", " năng", " ăng", " ử", " ờ", " ng", " tr",
    " ộ", " hà", " tiế", " giớ", " ủy",
})


# ══════════════════════════════════════════════
#  NICHE DETECTION
# ══════════════════════════════════════════════

NICHE_KEYWORDS = {
    "food_health": [
        "protein", "dinh dưỡng", "thực phẩm", "ăn", "uống", "chay",
        "vitamin", "khoáng chất", "calo", "béo", "gầy", "giảm cân",
        "sức khỏe", "bệnh", "thuốc", "y tế", "bác sĩ", "triệu chứng",
        "điều trị", "dược", "thảo dược", "đau", "viêm", "ung thư",
        "tiểu đường", "huyết áp", "cholesterol", "tim mạch",
        "nấu", "chế biến", "món ăn", "công thức", "nguyên liệu",
    ],
    "tech_gadget": [
        "laptop", "điện thoại", "máy tính", "phần mềm", "app",
        "chip", "ram", "ssd", "gpu", "cpu", "pin", "camera",
        "review", "đánh giá", "test", "benchmark", "hiệu năng",
        "5g", "wifi", "bluetooth", "ios", "android", "windows",
    ],
    "construction_material": [
        "thép", "tôn", "sắt", "bê tông", "xi măng", "xây dựng",
        "vật liệu", "công trình", "kết cấu", "ống", "thanh", "tấm",
        "hàn", "cắt", "uốn", "mạ", "inox", "nhôm", "đồng",
    ],
    "finance_law": [
        "đầu tư", "chứng khoán", "lãi suất", "ngân hàng", "vay",
        "thuế", "bảo hiểm", "hợp đồng", "luật", "pháp lý",
        "kinh doanh", "doanh nghiệp", "tài chính", "kế toán",
    ],
}

# Procedural/operational patterns — không phù hợp cho informational intent
PROCEDURAL_PATTERNS = (
    "quy trình", "hướng dẫn bảo trì", "bảo dưỡng định kỳ",
    "kiểm định", "kiểm tra chất lượng", "cảnh báo an toàn",
    "hướng dẫn sử dụng", "cách xử lý sự cố", "lịch bảo dưỡng",
    "checklist", "biên bản nghiệm thu", "sổ tay vận hành",
)

# B2B junk topics — generic content không phù hợp cho site thương mại
B2B_JUNK_KEYWORDS = frozenset({
    "tác động môi trường", "phát triển bền vững", "trách nhiệm xã hội",
})

# ══════════════════════════════════════════════
#  THRESHOLDS & LIMITS
# ══════════════════════════════════════════════

# ── H3 / Outline ──
H3_RATIO_GATE: float = 0.5        # H3 phải đạt ≥50% của H2 count
H3_MERGE_RECOVERY_GATE: float = 0.5  # Trigger H3 merge-back khi mất >50%
NGRAM_MIN_CHARS: int = 4          # N-gram phải ≥4 chars mới được dùng

# ── SUPP Section ──
SUPP_MIN_PCT: float = 0.2         # SUPP ≥20% của tổng H2
SUPP_MAX_PCT: float = 0.35        # SUPP ≤35% (warn nếu vượt quá)

# ── Intent H2 Minimums ──
H2_MIN_FOR_INTENT = {
    "commercial":    5,
    "informational": 4,
    "transactional": 3,
    "navigational":   2,
    "vs":            5,  # so sánh = commercial
}

# ── N-gram / Content Limits ──
MAX_CONTENT_GAPS: int = 7          # Giới hạn content gaps đưa vào outline
MAX_NGRAM_DISPLAY: int = 10        # Số N-gram hiển thị
MAX_COMPETITOR_HEADINGS: int = 10  # Số heading đối thủ dùng
MAX_NETWORK_CLUSTERS: int = 4      # Số cluster dùng trong prompt
MAX_KEYWORDS_PER_CLUSTER: int = 3  # Keywords mỗi cluster
MAX_PAA_INJECT: int = 3            # Số PAA question đưa vào FAQ H3
MAX_OUTBOUND_LINKS: int = 5       # Giới hạn outbound internal links
MIN_OUTBOUND_LINKS: int = 3       # Tối thiểu outbound internal links

# ── Title / Meta ──
TITLE_MAX_CHARS: int = 60
META_DESC_MAX_CHARS: int = 160

# ── Semantic Similarity Thresholds ──
SELF_REF_THRESHOLD_DEFAULT: float = 0.80   # Fuzzy match self-reference (internal linking)
SELF_REF_THRESHOLD_STRICT: float = 0.92    # Strict self-reference (CSV topical map)
SELF_REF_THRESHOLD_SOFT: float = 0.70      # Soft self-reference (cluster linking)
TAUTOLOGY_OVERLAP_THRESHOLD: float = 0.60  # Entity word overlap cho tautology check

# ── LLM Settings ──
LLM_TEMPERATURE_OUTLINE: float = 0.4  # Agent 1 (Synthesizer)
LLM_TEMPERATURE_SEO: float = 0.3      # Agent 2 (Semantic Enforcer)
LLM_TEMPERATURE_MICRO: float = 0.4    # Agent 3 (Micro-Briefing)
LLM_MAX_TOKENS_OUTLINE: int = 2000
LLM_MAX_TOKENS_SEO: int = 2500
LLM_MAX_TOKENS_MICRO: int = 4000
LLM_TIMEOUT: int = 60

# ── SAPO / Content Word Counts ──
SAPO_FULL_SCORE_MIN: int = 56
SAPO_FULL_SCORE_MAX: int = 156
WORD_COUNT_TARGET_FULL_SCORE_MIN: int = 800
WORD_COUNT_TARGET_FULL_SCORE_MAX: int = 1200

# ── Koray Quality Thresholds ──
FS_WORD_COUNT_MAX: int = 60
EAV_MIN_FOR_FULL_SCORE: int = 3
PAA_MIN_FOR_FULL_SCORE: int = 3
ANCHOR_MIN_WORDS: int = 2
H2_COUNT_RANGE_MIN: int = 5
H2_COUNT_RANGE_MAX: int = 12
TEMPLATE_H3_PENALTY_THRESHOLD: float = 0.3  # >30% template H3s → -8 penalty
