# -*- coding: utf-8 -*-
"""
topic_analyzer.py - Phân tích chủ đề SEO dựa trên kiến thức skill.md.

Thực hiện phân tích rule-based bao gồm:
- Search Intent classification
- Central Entity extraction
- Entity Attributes identification
- Contextual Hierarchy (heading structure) generation
- Keyword-to-Questions (K2Q) conversion
- Related Topics suggestion
"""

import logging
import re
from typing import Dict, List

# Import config cho search intent keywords
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import SEARCH_INTENT_KEYWORDS

logger = logging.getLogger(__name__)


def analyze_topic(
    topic: str,
    serp_data: dict = None,
    competitor_data: dict = None,
) -> Dict:
    """
    Phân tích một chủ đề và trả về kết quả phân tích SEO.

    Args:
        topic: Chuỗi chủ đề cần phân tích.
        serp_data: (Optional) Dữ liệu SERP từ Serper.dev.
        competitor_data: (Optional) Dữ liệu phân tích đối thủ.

    Returns:
        Dict chứa kết quả phân tích với các keys:
        - search_intent, central_entity, entity_attributes,
          heading_structure, suggested_questions, related_topics
    """
    logger.info("Đang phân tích: '%s'", topic)

    search_intent = _classify_intent(topic)
    central_entity = _extract_central_entity(topic)
    entity_attributes = _identify_attributes(topic, central_entity)

    # Dynamic Heading Construction — dùng dữ liệu thực tế nếu có
    heading_structure = _generate_heading_structure(
        topic, central_entity, search_intent,
        serp_data=serp_data,
        competitor_data=competitor_data,
    )

    # Câu hỏi từ PAA thực tế, fallback rule-based
    suggested_questions = _generate_questions(
        topic, central_entity,
        serp_data=serp_data,
    )

    related_topics = _suggest_related_topics(topic, central_entity)

    analysis = {
        "search_intent": search_intent,
        "central_entity": central_entity,
        "entity_attributes": entity_attributes,
        "heading_structure": heading_structure,
        "suggested_questions": suggested_questions,
        "related_topics": related_topics,
    }

    logger.info("  → Intent: %s | Entity: '%s'", search_intent, central_entity)
    return analysis


# ──────────────────────────────────────────────
#  PRIVATE HELPERS
# ──────────────────────────────────────────────

def _classify_intent(topic: str) -> str:
    """
    Phân loại Search Intent dựa trên từ khóa trong topic.
    Priority scoring: transactional > commercial > navigational > informational.

    Returns:
        Một trong: "informational", "commercial", "transactional", "navigational"
    """
    topic_lower = topic.lower()

    # Đếm số keyword match cho mỗi intent
    scores = {}
    for intent, keywords in SEARCH_INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in topic_lower)
        scores[intent] = score

    # Priority ordering: intent mua hàng mạnh hơn thông tin
    # Khi cùng score > 0, intent có priority cao hơn sẽ thắng
    INTENT_PRIORITY = {
        "transactional": 4,
        "commercial": 3,
        "navigational": 2,
        "informational": 1,
    }

    # Lọc intent có score > 0
    matched = {k: v for k, v in scores.items() if v > 0}

    if not matched:
        return "informational"

    # Sắp xếp theo score DESC, rồi priority DESC
    best_intent = max(
        matched,
        key=lambda k: (matched[k], INTENT_PRIORITY.get(k, 0)),
    )

    return best_intent


def _extract_central_entity(topic: str) -> str:
    """
    Trích xuất thực thể trung tâm từ topic.

    Loại bỏ các từ hỏi/modifier để lấy entity chính.
    [SPEC V5.7] Nếu là keyword so sánh (chứa 'vs', 'so sánh', 'khác nhau'),
    cố gắng tách thành 'Entity A, Entity B'.
    VD: "thép tấm là gì" → "thép tấm"
    VD: "so sánh thép cuộn và thép vằn" → "thép cuộn, thép vằn"
    """
    # 1. Detect if this is a comparison
    is_vs = False
    topic_lower = topic.lower()
    if " vs " in topic_lower or "so sánh" in topic_lower or "khác nhau" in topic_lower:
        is_vs = True

    # Danh sách patterns cần loại bỏ
    remove_patterns = [
        r"\blà gì\b", r"\blà sao\b", r"\bthế nào\b",
        r"\btại sao\b", r"\bvì sao\b", r"\bcách\b",
        r"\bhướng dẫn\b", r"\btop \d+\b", r"\bnên mua\b",
        r"\bso sánh\b", r"\bđánh giá\b", r"\breview\b",
        r"\bthông tin cơ bản về\b", r"\bthông tin về\b",
        r"\bưu điểm và ứng dụng của\b", r"\bưu điểm của\b",
        r"\bứng dụng của\b", r"\bứng dụng\b",
        r"\blựa chọn\b",
        r"\btrọng lượng\b",
        r"\bkhác nhau\b",
        r"\bcho công trình\b",
        r"\bphổ biến\b",
        r"\bloại\b",
        r"\blợp nhà\b",
        r"\bquy trình sản xuất\b",
    ]

    entity = topic.strip()
    for pattern in remove_patterns:
        entity = re.sub(pattern, "", entity, flags=re.IGNORECASE)

    # Clean up whitespace
    entity = re.sub(r"\s+", " ", entity).strip()

    # [SPEC V5.7] Logic tách entity cho bài VS
    if is_vs:
        # Thử split bằng chữ "và" hoặc "với" hoặc "vs"
        parts = re.split(r'\bvà\b|\bvs\b|\bvới\b', entity, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            return ", ".join(parts[:2])  # Trình bày dạng: "Entity A, Entity B"
        else:
            # Fallback nếu không chẻ được
            entity = re.sub(r'\bvà\b|\bvs\b|\bvới\b', ',', entity, flags=re.IGNORECASE)
            entity = re.sub(r"\s+", " ", entity).strip()

    else:
        # Nếu không phải bài so sánh, loại bỏ chữ "và"
        entity = re.sub(r'\bvà\b', "", entity, flags=re.IGNORECASE)
        entity = re.sub(r"\s+", " ", entity).strip()

    # Nếu entity rỗng sau khi clean, dùng topic gốc
    if not entity:
        entity = topic.strip()

    return entity


def _identify_attributes(topic: str, entity: str) -> Dict[str, List[str]]:
    """
    Xác định các thuộc tính của thực thể (Root, Rare, Unique).

    Returns:
        Dict với keys: root_attributes, rare_attributes, unique_attributes
    """
    entity_lower = entity.lower()

    # Root attributes - thuộc tính cơ bản luôn có cho mọi loại thép/vật liệu
    root_attrs = ["Định nghĩa", "Phân loại", "Đặc điểm kỹ thuật"]

    # Thêm root attributes tùy theo loại entity
    if any(kw in entity_lower for kw in ["thép", "sắt", "tôn", "xà gồ"]):
        root_attrs.extend(["Kích thước tiêu chuẩn", "Trọng lượng", "Giá tham khảo"])

    if "ống" in entity_lower:
        root_attrs.extend(["Đường kính", "Độ dày thành ống", "Áp lực chịu được"])

    # Rare attributes - thuộc tính chỉ có ở một số loại
    rare_attrs = []
    if "mạ kẽm" in entity_lower:
        rare_attrs.append("Quy trình mạ kẽm")
    if "chịu nhiệt" in entity_lower:
        rare_attrs.append("Ngưỡng nhiệt độ chịu được")
    if "chịu áp lực" in entity_lower:
        rare_attrs.append("Cấp độ áp lực thiết kế")
    if "cách nhiệt" in entity_lower:
        rare_attrs.append("Hệ số cách nhiệt")
    if "màu" in entity_lower:
        rare_attrs.append("Bảng màu có sẵn")
    if "lạnh" in entity_lower:
        rare_attrs.append("Quy trình cán nguội")

    # Unique attributes - thuộc tính đặc trưng
    unique_attrs = []
    if "erw" in entity_lower:
        unique_attrs.append("Công nghệ hàn điện trở (ERW)")
    if "lsaw" in entity_lower:
        unique_attrs.append("Công nghệ hàn hồ quang chìm dọc (LSAW)")
    if "bê tông cốt thép" in entity_lower:
        unique_attrs.append("Cấu tạo liên hợp bê tông - thép")

    return {
        "root_attributes": root_attrs,
        "rare_attributes": rare_attrs if rare_attrs else ["Không có thuộc tính hiếm đặc biệt"],
        "unique_attributes": unique_attrs if unique_attrs else ["Không có thuộc tính độc nhất đặc biệt"],
    }


def _generate_heading_structure(
    topic: str,
    entity: str,
    intent: str,
    serp_data: dict = None,
    competitor_data: dict = None,
) -> List[Dict]:
    """
    Dynamic Heading Construction — Xây dựng Heading từ dữ liệu thực tế.

    Algorithm:
      Bước A (Xương sống):  common_headings từ đối thủ → H2
      Bước B (Tối ưu Intent): PAA chưa có trong khung → thêm H2
      Bước C (Information Gain): rare_headings từ gaps → H3 hoặc H2 riêng

    Fallback: Nếu KHÔNG có data, trả heading tối thiểu (H1 + FAQ).

    Returns:
        List of dicts: [{"level": "H1/H2/H3", "text": "..."}]
    """
    headings = [{"level": "H1", "text": topic.strip().title()}]

    has_competitor = competitor_data and competitor_data.get("common_headings")
    has_serp = serp_data and serp_data.get("people_also_ask")

    # ═══════════════════════════════════════════
    #  DATA-DRIVEN PATH (có dữ liệu thực tế)
    # ═══════════════════════════════════════════
    if has_competitor or has_serp:
        used_texts = set()  # Theo dõi heading đã dùng (lowercase)

        # ── BƯỚC A: Xương sống từ Common Headings ──
        common = competitor_data.get("common_headings", []) if competitor_data else []
        for h_text in common:
            normalized = h_text.strip().lower()
            # Bỏ qua heading rác (navigation, footer, CTA...)
            if _is_junk_heading(normalized):
                continue
            if normalized not in used_texts:
                headings.append({"level": "H2", "text": h_text.strip().title()})
                used_texts.add(normalized)

        # ── BƯỚC B: Tối ưu Intent — Chèn PAA thành H2 ──
        paa_list = serp_data.get("people_also_ask", []) if serp_data else []
        for question in paa_list:
            q_lower = question.strip().lower()
            # Kiểm tra PAA chưa trùng với heading đã có
            if not any(q_lower in existing or existing in q_lower for existing in used_texts):
                headings.append({"level": "H2", "text": question.strip()})
                used_texts.add(q_lower)

        # ── BƯỚC C: Semantic Voids — Rare Headings làm H2/H3 trực tiếp ──
        # Phase 24: KHÔNG hardcode "Information Gain" làm tên H2.
        # Thay vào đó, rare headings được đưa thẳng vào như H2/H3 với tên thực tế.
        info_gain = (
            competitor_data.get("information_gain", {}) if competitor_data else {}
        )
        rare_headings = info_gain.get("rare_headings", [])

        # Lọc rare headings có ý nghĩa (loại rác)
        meaningful_rares = [
            rh for rh in rare_headings
            if not _is_junk_heading(rh.lower()) and len(rh) < 80
        ]

        if meaningful_rares:
            for rh in meaningful_rares[:5]:  # Giới hạn 5 rare headings
                rh_clean = rh.strip().title()
                if rh_clean.lower() not in used_texts:
                    headings.append({"level": "H2", "text": rh_clean})
                    used_texts.add(rh_clean.lower())

        # ── Luôn thêm FAQ cuối cùng ──
        headings.append({"level": "H2", "text": "Câu hỏi thường gặp (FAQ)"})

        logger.info(
            "  [HEADING] Dynamic: %d H2 + H3 (từ %d common, %d PAA, %d rare)",
            len(headings) - 1,  # trừ H1
            len(common),
            len(paa_list),
            len(meaningful_rares),
        )

    # ═══════════════════════════════════════════
    #  FALLBACK PATH (không có dữ liệu)
    # ═══════════════════════════════════════════
    else:
        logger.warning(
            "  [HEADING] Fallback: không có SERP/Competitor data → heading tối thiểu"
        )
        headings.extend([
            {"level": "H2", "text": f"Tổng quan: {entity} là gì?"},
            {"level": "H2", "text": "Các đặc điểm cấu tạo nổi bật nhất"},
            {"level": "H2", "text": "Ứng dụng thực tiễn trong đời sống và xây dựng"},
            {"level": "H2", "text": "Những lưu ý quan trọng khi chọn mua và sử dụng"},
            {"level": "H2", "text": "Câu hỏi thường gặp (FAQ)"},
        ])

    return headings


def _is_junk_heading(text: str) -> bool:
    """
    Kiểm tra heading rác (navigation, footer, CTA, quảng cáo...).

    Returns:
        True nếu heading là rác, cần loại bỏ.
    """
    junk_patterns = [
        "để lại thông tin",
        "nhận tư vấn",
        "theo dõi chúng tôi",
        "đối tác liên kết",
        "tải app",
        "hotline",
        "dịch vụ",
        "hệ thống",
        "content not available",
        "xem thêm video",
        "xem thêm bài",
        "bài viết liên quan",
        "tin tức",
        "đăng ký",
        "đăng nhập",
        "liên hệ",
        "trạm y tế",
        "medinet",
        "nên uống",
        "uống creatine",
        "uống omega",
        "uống whey",
        "uống biotin",
        "uống vitamin",
        "whey protein",
        "whey mass",
        "pre workout",
        "tongkat ali",
        "ginkgo biloba",
        "marine collagen",
        "cùng gymstore",
        # Phase 24: Navigation & CTA junk patterns
        "sản phẩm",
        "về chúng tôi",
        "trang chủ",
        "giới thiệu",
        "chính sách",
        "bảo hành",
        "thanh toán",
        "giỏ hàng",
        "menu",
        "footer",
        "header",
        "sidebar",
        "breadcrumb",
        "navigation",
        "copyright",
        "hôm nay",
        "mới nhất",
        "tin mới",
        "báo giá",
        "bảng giá",
        "khuyến mãi",
        "giảm giá",
        "mua ngay",
        "đặt hàng",
        "share",
        "chia sẻ",
        "comments",
        "bình luận",
    ]
    # Phase 24: Reject very short headings (1-2 words) likely navigation items
    words = text.strip().split()
    if len(words) <= 2 and not any(c.isdigit() for c in text):
        return True
    return any(pattern in text for pattern in junk_patterns)


def _generate_k2q_llm(topic: str, entity: str, serp_data: dict = None) -> List[str]:
    """
    Phase 24: Sinh câu hỏi K2Q (Keyword-to-Question) bằng LLM,
    dựa trên entities tìm được từ SERP. Thay thế template cứng.
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            raise ValueError("No API key")

        import openai
        client = openai.OpenAI(api_key=api_key)

        # Thu thập entities từ SERP để làm ngữ cảnh
        serp_entities = []
        if serp_data:
            ents = serp_data.get("serp_entities", {})
            serp_entities = (ents.get("primary", []) + ents.get("secondary", []))[:10]
            serp_entities += serp_data.get("serp_attributes", [])[:5]

        entities_context = ", ".join(serp_entities) if serp_entities else "không có dữ liệu SERP"

        system_prompt = (
            "Bạn là chuyên gia Semantic SEO (Koray Framework). "
            "Nhiệm vụ: Sinh CHÍNH XÁC 5 câu hỏi K2Q (Keyword-to-Question) "
            "cho chủ đề và entity dưới đây.\n\n"
            "QUY TẮC BẮT BUỘC:\n"
            "1. INQUISITIVE SEMANTICS (Ngữ nghĩa tò mò): Tạo ra một luồng câu hỏi - câu trả lời liên tục. Câu hỏi sau phải đào sâu hơn câu hỏi trước.\n"
            "2. PRECEDING QUESTION (Câu hỏi đi trước): Bắt đầu bằng câu hỏi đại diện mang tính cốt lõi (Definitional), sau đó đi vào các câu hỏi chi tiết bổ trợ (Comparative, Grouping).\n"
            "3. Câu hỏi PHẢI đặc thù cho NGÀNH/LĨNH VỰC cụ thể, KHÔNG ĐƯỢC đánh đố chung chung (generic).\n"
            "4. Câu hỏi phải bao hàm các Entities và Attributes thực tế tìm được từ SERP.\n"
            "5. KHÔNG dùng template rẻ tiền 'Có bao nhiêu loại X?' hay 'Đánh giá về X?'.\n\n"
            "OUTPUT: Trả về ĐÚNG 5 dòng, mỗi dòng là 1 câu hỏi. KHÔNG đánh số, KHÔNG bullet."
        )

        user_prompt = (
            f"Chủ đề: {topic}\n"
            f"Entity chính: {entity}\n"
            f"Entities liên quan từ SERP: {entities_context}\n\n"
            "Sinh 5 câu hỏi K2Q chuyên sâu:"
        )

        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
            max_tokens=500,
            timeout=30,
        )

        raw = response.choices[0].message.content.strip()
        questions = [
            line.strip().lstrip("0123456789.-) ").strip()
            for line in raw.split("\n")
            if line.strip() and len(line.strip()) > 10
        ]
        if questions:
            logger.info("  [K2Q] LLM sinh thành công %d câu hỏi.", len(questions))
            return questions[:7]
    except Exception as e:
        logger.warning("  [K2Q] LLM lỗi (%s) -> Dùng fallback cơ bản.", str(e))

    # Fallback cơ bản (không dùng template generic nữa)
    return [
        f"{entity} là gì? Định nghĩa và phân loại",
        f"Ứng dụng chính của {entity} trong thực tế",
        f"So sánh các loại {entity} phổ biến nhất",
        f"Tiêu chuẩn kỹ thuật khi lựa chọn {entity}",
        f"Những lưu ý an toàn khi sử dụng {entity}",
    ]


def _generate_questions(
    topic: str,
    entity: str,
    serp_data: dict = None,
) -> List[str]:
    """
    Tạo danh sách câu hỏi — ưu tiên PAA thực tế, fallback rule-based.

    Args:
        topic: Chủ đề gốc.
        entity: Thực thể trung tâm.
        serp_data: (Optional) Dữ liệu SERP chứa PAA.

    Returns:
        Danh sách 5-7 câu hỏi liên quan đến topic.
    """
    questions = []

    # Ưu tiên PAA từ Google (dữ liệu thực tế)
    if serp_data and serp_data.get("people_also_ask"):
        questions.extend(serp_data["people_also_ask"])

    # Thêm related searches nếu thiếu
    if serp_data and len(questions) < 5:
        for rs in serp_data.get("related_searches", []):
            if rs not in questions and len(questions) < 7:
                questions.append(rs)

    # ── Phase 24: K2Q LLM-based (thay thế template cứng) ──
    if not questions:
        questions = _generate_k2q_llm(topic, entity, serp_data)

    return questions[:7]


def _suggest_related_topics(topic: str, entity: str) -> List[str]:
    """
    Đề xuất chủ đề liên quan cho internal linking.

    Returns:
        Danh sách 3-5 chủ đề liên quan.
    """
    related = []
    entity_lower = entity.lower()

    # Mapping quan hệ chủ đề
    topic_relations = {
        "thép tấm": ["Thép cuộn", "Thép tấm nhám", "Trọng lượng thép tấm"],
        "thép cuộn": ["Thép tấm", "Thép cán nóng", "Thép cán nguội"],
        "thép hình": ["Thép hình I", "Thép hình U", "Thép hình H", "Thép hình V"],
        "thép tròn": ["Thép tròn trơn", "Thép thanh vằn", "Thép xây dựng"],
        "tôn": ["Tôn lạnh", "Tôn màu", "Tôn cách nhiệt", "Tôn lợp nhà"],
        "xà gồ": ["Xà gồ C", "Xà gồ Z", "Thép hình"],
        "ống thép": ["Ống thép đúc", "Ống thép ERW", "Ống thép LSAW", "Ống thép mạ kẽm"],
        "thép xây dựng": ["Thép thanh vằn", "Thép tròn", "Dầm bê tông cốt thép"],
    }

    # Tìm related topics dựa trên entity
    for key, values in topic_relations.items():
        if key in entity_lower:
            related.extend(values)
            break

    # Nếu không match, trả về list rỗng (KHÔNG TỰ BỊA)
    if not related:
        return []

    # Loại bỏ topic trùng với chính nó
    related = [r for r in related if r.lower() != entity_lower]

    return related[:5]
