# -*- coding: utf-8 -*-
"""
article_writer.py - Phase 15.5: Article Methodology Integration.

Cung cấp thư viện Methodology (Phong cách viết) và logic chọn tự động
dựa trên Search Intent. Methodology được inject vào System Prompt
khi gọi AI sinh bài viết.

Usage:
    from modules.article_writer import METHODOLOGIES, auto_detect_methodology
    
    method_key = auto_detect_methodology(intent)
    system_prompt = METHODOLOGIES[method_key]
"""

import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  METHODOLOGY LIBRARY
# ══════════════════════════════════════════════

METHODOLOGIES = {
    "evidence_based": {
        "label": "Evidence-Based (Sức khỏe/Luật)",
        "system_prompt": (
            "Bạn là một chuyên gia nghiên cứu với phong cách viết Evidence-Based.\n"
            "Quy tắc viết BẮT BUỘC:\n"
            "1. KHÔNG dùng tính từ cảm xúc (tuyệt vời, rất tốt, siêu hiệu quả). "
            "Thay vào đó, hãy dùng SỐ LIỆU CỤ THỂ (%, mg, nghiên cứu năm nào).\n"
            "2. Cấu trúc mỗi đoạn văn: Luận điểm → Bằng chứng (Nghiên cứu/Số liệu) "
            "→ Giải thích → Kết luận ngắn.\n"
            "3. Nếu đưa ra lời khuyên sức khỏe, BẮT BUỘC có đoạn "
            "'⚠️ Lưu ý an toàn' hoặc 'Cảnh báo' ở cuối section.\n"
            "4. Trích dẫn nguồn nếu có: '(Theo nghiên cứu trên Journal X, 2024)'.\n"
            "5. Xưng hô 'Chúng tôi' để tăng E-E-A-T.\n"
        ),
    },
    "product_review": {
        "label": "Product Review (Thương mại)",
        "system_prompt": (
            "Bạn là một Reviewer khó tính, trung thực và có kinh nghiệm thực tế.\n"
            "Quy tắc viết BẮT BUỘC:\n"
            "1. Luôn bắt đầu bằng TRẢI NGHIỆM THỰC TẾ (cảm giác cầm nắm, mùi vị, "
            "thao tác thực tế) — không viết lý thuyết suông.\n"
            "2. Mỗi sản phẩm/mục PHẢI có bảng so sánh Ưu điểm / Nhược điểm.\n"
            "3. PHẢI chỉ ra ai KHÔNG NÊN mua/dùng sản phẩm này.\n"
            "4. Đưa ra đánh giá điểm số (X/10) cho từng tiêu chí nếu thích hợp.\n"
            "5. Xưng hô 'Tôi' (trải nghiệm cá nhân) để tăng tính đáng tin.\n"
        ),
    },
    "step_by_step": {
        "label": "Step-by-Step Guide (Hướng dẫn)",
        "system_prompt": (
            "Bạn là một người hướng dẫn tận tâm, kiên nhẫn và chi tiết.\n"
            "Quy tắc viết BẮT BUỘC:\n"
            "1. Dùng ĐỘNG TỪ MẠNH ở đầu mỗi bước (Xác định, Chuẩn bị, Thực hiện, Kiểm tra, Hoàn thiện...).\n"
            "2. Sau mỗi bước, thêm '💡 Mẹo:' hoặc '⚠️ Lỗi thường gặp:' nếu cần.\n"
            "3. Văn phong ngắn gọn, trực diện. Không lan man giải thích lý thuyết.\n"
            "4. Đánh số thứ tự rõ ràng cho từng bước.\n"
            "5. Nếu cần vật dụng/nguyên liệu, liệt kê trước khi bắt đầu hướng dẫn.\n"
        ),
    },
    "comparative": {
        "label": "Comparative Analysis (So sánh)",
        "system_prompt": (
            "Bạn là một chuyên gia phân tích khách quan và chi tiết.\n"
            "Quy tắc viết BẮT BUỘC:\n"
            "1. Sử dụng BẢNG SO SÁNH (table) cho mọi tiêu chí kỹ thuật.\n"
            "2. Phân tích Ưu điểm / Nhược điểm (Pros/Cons) cho từng đối tượng so sánh.\n"
            "3. Cung cấp SỐ LIỆU KỸ THUẬT cụ thể theo ngành (đơn vị đo, thông số, chỉ số hiệu suất...).\n"
            "4. KHÔNG đưa ra ý kiến chủ quan, chỉ nêu dữ liệu để người đọc tự kết luận.\n"
            "5. Kết luận bằng 'Nên chọn A khi..., Nên chọn B khi...' (theo tình huống).\n"
            "6. Xưng hô 'Chúng tôi' để tăng tính chuyên môn.\n"
        ),
    },
    "general": {
        "label": "General (Tổng quát)",
        "system_prompt": (
            "Bạn là một Content Writer chuyên nghiệp.\n"
            "Quy tắc viết:\n"
            "1. Trả lời câu hỏi chính NGAY dòng đầu tiên (No fluff).\n"
            "2. Xưng hô 'Chúng tôi' hoặc 'Tôi'.\n"
            "3. Ưu tiên thông tin thực tế, tránh viết dài dòng.\n"
            "4. Chèn ví dụ cụ thể khi giải thích khái niệm.\n"
        ),
    },
}

# Danh sách keys để UI hiển thị (bao gồm Auto-Detect)
METHODOLOGY_OPTIONS = ["auto"] + list(METHODOLOGIES.keys())

# Labels cho UI selectbox
METHODOLOGY_LABELS = {
    "auto": "🤖 Auto-Detect (Tự động theo Intent)",
    "evidence_based": "🔬 Evidence-Based (Sức khỏe/Luật)",
    "product_review": "⭐ Product Review (Thương mại)",
    "step_by_step": "📋 Step-by-Step Guide (Hướng dẫn)",
    "comparative": "📊 Comparative Analysis (So sánh)",
    "general": "📝 General (Tổng quát)",
}


# ══════════════════════════════════════════════
#  AUTO-DETECT LOGIC
# ══════════════════════════════════════════════

def auto_detect_methodology(intent: str, keyword: str = "") -> str:
    """
    Tự động chọn Methodology dựa trên Search Intent + keyword.

    Args:
        intent: Search Intent đã phân tích (informational, commercial, etc.)
        keyword: Từ khóa gốc (dùng để detect niche).

    Returns:
        Key của METHODOLOGIES (ví dụ: 'evidence_based', 'product_review').
    """
    # Phase 2.2: Use centralized normalize_intent from modules/intent.py
    from modules.intent import normalize_intent
    intent_lower = normalize_intent(intent)
    kw_lower = keyword.lower()
    
    # Detect theo keyword trước (ưu tiên cao)
    health_keywords = [
        "protein", "vitamin", "dinh dưỡng", "sức khỏe", "bệnh", "thuốc",
        "triệu chứng", "điều trị", "y tế", "y khoa", "luật", "pháp lý",
        "nghị định", "thông tư", "quy định",
    ]
    # Phase 25: Comparative keywords route to comparative methodology
    comparative_keywords = [
        "so sánh", "khác nhau", "khác biệt", "vs", "hay", "nên chọn",
        "giống nhau", "phân biệt",
    ]
    review_keywords = [
        "review", "đánh giá", "nên mua", "tốt nhất", "top",
        "giá", "mua ở đâu", "whey", "supplement",
    ]
    guide_keywords = [
        "cách", "hướng dẫn", "làm sao", "thế nào", "bước", "quy trình",
        "cài đặt", "cấu hình", "setup",
    ]

    if any(kw in kw_lower for kw in health_keywords):
        logger.info("  [METHODOLOGY] Auto-detect: evidence_based (keyword match)")
        return "evidence_based"

    if any(kw in kw_lower for kw in comparative_keywords):
        logger.info("  [METHODOLOGY] Auto-detect: comparative (keyword match)")
        return "comparative"

    if any(kw in kw_lower for kw in review_keywords):
        logger.info("  [METHODOLOGY] Auto-detect: product_review (keyword match)")
        return "product_review"

    if any(kw in kw_lower for kw in guide_keywords):
        logger.info("  [METHODOLOGY] Auto-detect: step_by_step (keyword match)")
        return "step_by_step"
    
    # Fallback theo intent (4 loại chuẩn V17)
    intent_mapping = {
        "informational": "general",
        "commercial": "product_review",
        "transactional": "product_review",
        "navigational": "general",
        # Backward compat
        "vs": "comparative",
    }
    
    result = intent_mapping.get(intent_lower, "general")
    logger.info("  [METHODOLOGY] Auto-detect: %s (intent=%s)", result, intent_lower)
    return result


def get_methodology_prompt(method_key: str) -> str:
    """Lấy system prompt từ key. Fallback sang 'general' nếu key không hợp lệ."""
    method = METHODOLOGIES.get(method_key, METHODOLOGIES["general"])
    return method["system_prompt"]
