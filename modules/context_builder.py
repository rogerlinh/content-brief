# -*- coding: utf-8 -*-
"""
context_builder.py - Biến đổi Competitor Headings thành Context Vectors & Guidelines bằng LLM (OpenAI/Gemini).

Mục tiêu chính (Yêu cầu nghiêm ngặt):
1. Nhận cụm Headings H2/H3 của top 4 đối thủ.
2. Dùng LLM prompt để:
   a. Chuyển đổi headings thành các CÂU HỎI TRỰC TIẾP (Context Vectors).
   b. Sắp xếp câu hỏi theo luồng logic (Từ cơ bản đến chuyên sâu).
   c. Tạo Guidelines (Contextual Structure) ép buộc: 
      - Trả lời trực tiếp ngay dòng đầu (No fluff).
      - Xưng hô "Tôi/Chúng tôi" để tăng E-E-A-T.
      - Tối ưu Micro-semantics (đưa thực thể lên trước).

Usage:
    from modules.context_builder import build_prompt_context
    context = build_prompt_context("thép tấm", competitor_data)
"""

import json
import logging
from typing import Dict, Optional
from config import LLM_CONFIG

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)


def build_prompt_context(topic: str, competitor_data: dict) -> Optional[Dict]:
    """
    Sử dụng LLM để sinh Context Vectors và Contextual Structure Guidelines.

    Args:
        topic: Chủ đề bài viết.
        competitor_data: Dữ liệu trả về từ serp_competitor_analyzer (có chứa headings).

    Returns:
        Dict gồm context_vectors (list câu hỏi) và contextual_structure (list guidelines).
        Nếu lỗi hoặc không có OpenAI key, trả về None hoặc Dict chứa message lỗi.
    """
    logger.info("  [CONTEXT] Bắt đầu xây dựng Context Vectors cho: '%s'", topic)

    if not OpenAI:
        logger.warning("  [CONTEXT] Thiếu thư viện 'openai'. Bỏ qua Context Builder.")
        return {"error": "Missing openai library"}

    api_key = LLM_CONFIG.get("api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.warning("  [CONTEXT] OPENAI_API_KEY chưa cấu hình. Bỏ qua Context Builder.")
        return {"error": "Missing API Key"}

    client = OpenAI(
        api_key=api_key,
        base_url=LLM_CONFIG.get("base_url") if LLM_CONFIG.get("base_url") else None
    )

    # Trích xuất headings từ đối thủ
    competitors = competitor_data.get("competitors", [])
    if not competitors:
        logger.warning("  [CONTEXT] Không có dữ liệu đối thủ. Bỏ qua.")
        return {"error": "No competitor data given"}

    # Lấy H2/H3 từ Top 3 hoặc Top 4 đối thủ
    all_headings = []
    for comp in competitors[:4]:
        for h in comp.get("headings", []):
            # Support both dict format {"level": "H2", "text": "..."} and tuple format ("h2", "...")
            if isinstance(h, dict):
                h_type = h.get("level", "").lower()
                text = h.get("text", "")
            elif isinstance(h, (list, tuple)) and len(h) >= 2:
                h_type, text = h[0].lower(), h[1]
            else:
                continue
            if h_type in ["h2", "h3"] and text.strip():
                all_headings.append(f"[{h_type.upper()}] {text.strip()}")

    if not all_headings:
        logger.warning("  [CONTEXT] Không tìm thấy headings H2/H3 nào từ đối thủ.")
        return {"error": "No competitor headings found"}

    # Giới hạn số lượng heading gửi cho LLM để không vỡ token (khoảng 100 headings)
    headings_str = "\n".join(all_headings[:80])

    system_prompt = (
        "Bạn là một chuyên gia Semantic SEO (Koray Framework) và Content Strategist cấp cao.\n"
        "Nhiệm vụ của bạn là phân tích Headings của đối thủ để thiết kế 'Context Vectors' và 'Contextual Structure'.\n"
        "\nYêu cầu NGHIÊM NGẶT THEO KORAY SEO:\n"
        "1. XÂY DỰNG NGỮ CẢNH: Bắt buộc chuyển đổi ý chính của đối thủ thành CÂU HỎI TRỰC TIẾP (Context Vectors).\n"
        "2. Về Context Vectors (Cấu trúc câu hỏi):\n"
        "   - Sắp xếp các câu hỏi theo CONTEXTUAL FLOW (Dòng chảy ngữ cảnh tuyến tính): từ định nghĩa cơ bản -> chuyên sâu -> mở rộng -> hành động.\n"
        "3. Về Contextual Structure (Hướng dẫn viết - Guideline):\n"
        "   - Bắt buộc Copywriter phải viết SUBORDINATE TEXT ngay dưới mỗi Heading: Câu đầu tiên ngay sau Heading H2/H3 PHẢI trả lời trực tiếp nội dung Heading đó (No fluff).\n"
        "   - Yêu cầu ứng dụng INFOMATION RESPONSIVENESS (Độ phản hồi thông tin): Trả lời nhanh gọn, đi thẳng vào vấn đề.\n"
        "   - Bắt buộc xưng hô 'Tôi' hoặc 'Chúng tôi' theo SOURCE CONTEXT để tăng E-E-A-T.\n"
        "   - Bắt buộc tối ưu MICROSEMANTICS: Cấu trúc câu chủ động (Proper Word Sequence), đưa thực thể/keyword mục tiêu lên đầu câu.\n"
        "\n"
        "Bạn PHẢI trả lời hoàn toàn bằng JSON hợp lệ với format chính xác sau:\n"
        "{\n"
        '  "context_vectors": [\n'
        '    {"question": "Câu hỏi cơ bản 1?", "intent": "Mục đích tìm kiếm"}, \n'
        '    {"question": "Câu hỏi chuyên sâu 2?", "intent": "Mục đích tìm kiếm"}\n'
        "  ],\n"
        '  "contextual_structure": [\n'
        '    "Nguyên tắc 1: ...",\n'
        '    "Nguyên tắc 2: ...",\n'
        '    "Nguyên tắc 3: ..."\n'
        "  ]\n"
        "}"
    )

    user_prompt = f"Chủ đề gốc: '{topic}'.\n\nĐây là headings thu thập được từ các bài Top đối thủ (Hãy chắt lọc các ý chính và chuyển đổi thành câu hỏi logic):\n\n{headings_str}"

    try:
        logger.info("  [CONTEXT] Đang gửi %d headings tới LLM (%s)...", min(len(all_headings), 80), LLM_CONFIG.get("model"))
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3, # Temperature thấp cho JSON ổn định + focus vào rule
            response_format={"type": "json_object"},
            timeout=60,  # Phase 16: tránh treo mãi mãi
        )

        content = response.choices[0].message.content
        context_data = json.loads(content)
        
        # Đảm bảo format chuẩn
        if "context_vectors" not in context_data:
            context_data["context_vectors"] = []
        if "contextual_structure" not in context_data:
            context_data["contextual_structure"] = []

        logger.info("  [CONTEXT] Hoàn tất: %d vectors, %d guidelines", 
                    len(context_data["context_vectors"]), 
                    len(context_data["contextual_structure"]))
        return context_data

    except Exception as e:
        logger.error("  [CONTEXT] LLM Error: %s", str(e))
        return {"error": f"LLM Error: {str(e)}"}
