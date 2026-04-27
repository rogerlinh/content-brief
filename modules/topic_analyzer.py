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
from modules.outline_content_prompt_catalog import build_k2q_prompts

logger = logging.getLogger(__name__)


def _normalize_question_items(raw_questions) -> List[str]:
    """Normalize PAA/question payloads into a clean list of strings."""
    if raw_questions is None:
        return []

    if isinstance(raw_questions, dict):
        raw_questions = (
            raw_questions.get("questions")
            or raw_questions.get("paa_questions")
            or raw_questions.get("items")
            or []
        )

    if isinstance(raw_questions, str):
        text = raw_questions.strip()
        if not text:
            return []
        try:
            import json as _json
            parsed = _json.loads(text)
            return _normalize_question_items(parsed)
        except Exception:
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if len(lines) > 1:
                raw_questions = lines
            else:
                raw_questions = [text]

    if not isinstance(raw_questions, (list, tuple, set)):
        raw_questions = [raw_questions]

    questions = []
    for item in raw_questions:
        if item is None:
            continue
        if isinstance(item, dict):
            nested = (
                item.get("questions")
                or item.get("paa_questions")
                or item.get("items")
            )
            if nested:
                questions.extend(_normalize_question_items(nested))
                continue
            value = (
                item.get("question")
                or item.get("text")
                or item.get("title")
                or item.get("value")
                or ""
            )
        else:
            value = str(item)

        value = str(value).strip()
        if not value:
            continue

        if value.startswith("{") and value.endswith("}"):
            try:
                import json as _json
                parsed = _json.loads(value)
                nested = _normalize_question_items(parsed)
                if nested:
                    questions.extend(nested)
                    continue
            except Exception:
                pass

        value = value.replace("\r", "\n").strip()
        if "\n" in value and len(value.splitlines()) > 1:
            for line in value.splitlines():
                line = line.strip().lstrip("-•* ").strip()
                if line and len(line) > 4:
                    questions.append(line)
            continue

        cleaned = value.lstrip("0123456789.-) \t").strip()
        if cleaned:
            questions.append(cleaned)

    deduped = []
    seen = set()
    for q in questions:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(q)
    return deduped


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

    intent_result = _classify_intent(topic)
    # G3 Fix: _classify_intent now returns dict {type, buyer_journey_stage}
    if isinstance(intent_result, dict):
        search_intent = intent_result.get("type", "informational")
        buyer_journey_stage = intent_result.get("buyer_journey_stage", "awareness")
    else:
        search_intent = str(intent_result)
        buyer_journey_stage = "awareness"
    central_entity = _extract_central_entity(topic)
    entity_attributes = _identify_attributes(topic, central_entity)

    # Dynamic Heading Construction — dùng dữ liệu thực tế nếu có
    heading_structure = _generate_heading_structure(
        topic, central_entity, search_intent,
        serp_data=serp_data,
        competitor_data=competitor_data,
    )

    # Câu hỏi từ PAA thực tế, fallback rule-based
    suggested_questions = _normalize_question_items(_generate_questions(
        topic, central_entity,
        serp_data=serp_data,
    ))

    related_topics = _suggest_related_topics(topic, central_entity)

    analysis = {
        "search_intent": search_intent,
        "buyer_journey_stage": buyer_journey_stage,  # G3 Fix: for CTA aggressiveness in Micro-Briefing
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

def _classify_intent(topic: str) -> dict:
    """
    Phân loại Search Intent dựa trên từ khóa trong topic.
    Priority scoring: transactional > commercial > navigational > informational.

    Returns:
        Dict: {"type": str, "buyer_journey_stage": str}
        type: Một trong: "informational", "commercial", "transactional", "navigational", "vs"
        buyer_journey_stage: "awareness" | "consideration" | "decision"
            (Koray: dùng để quyết định độ aggressive của CTA trong Contextual Bridge)
    """
    topic_lower = topic.lower()

    # 1. SO SÁNH / VS — kiểm tra TRƯỚC, không qua scoring
    # (các từ này nằm trong commercial keywords nên sẽ sai nếu để scoring xử lý)
    VS_INDICATORS = [" vs ", "so sánh", "khác nhau", "khác gì", "so với", " hay là "]
    if any(ind in topic_lower for ind in VS_INDICATORS):
        # G3 Fix: buyer_journey_stage for VS → "decision"
        return {"type": "vs", "buyer_journey_stage": "decision"}

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
        return {"type": "informational", "buyer_journey_stage": "awareness"}

    # Sắp xếp theo score DESC, rồi priority DESC
    best_intent = max(
        matched,
        key=lambda k: (matched[k], INTENT_PRIORITY.get(k, 0)),
    )

    # G3 Fix: buyer_journey_stage mapping
    # Koray: Dùng buyer_journey_stage để quyết định độ aggressive của CTA
    if best_intent in ["transactional", "vs"]:
        buyer_stage = "decision"
    elif best_intent == "commercial":
        buyer_stage = "consideration"
    else:
        buyer_stage = "awareness"

    return {"type": best_intent, "buyer_journey_stage": buyer_stage}


def _extract_central_entity(topic: str) -> str:
    """
    Trích xuất thực thể trung tâm từ topic.

    Loại bỏ các từ hỏi/modifier để lấy entity chính.
    [SPEC V5.7] Nếu là keyword so sánh (chứa 'vs', 'so sánh', 'khác nhau'),
    cố gắng tách thành 'Entity A, Entity B'.
    VD: "entity A là gì" → "entity A"
    VD: "so sánh A và B" → "A, B"
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

    # Root attributes dùng được cho mọi ngành; dữ liệu SERP/EAV sẽ bổ sung chi tiết ngành.
    root_attrs = ["Định nghĩa", "Phân loại", "Thuộc tính cốt lõi", "Bối cảnh áp dụng"]

    # Rare/unique attributes chỉ lấy từ dấu hiệu có trong chính keyword, tránh hardcode ngành.
    rare_attrs = []
    if any(sig in entity_lower for sig in ["giá", "chi phí", "phí", "cost", "price"]):
        rare_attrs.append("Yếu tố làm thay đổi chi phí")
    if any(sig in entity_lower for sig in ["so sánh", "khác nhau", "vs", "phân biệt"]):
        rare_attrs.append("Tiêu chí so sánh")
    if any(sig in entity_lower for sig in ["quy trình", "cách", "hướng dẫn", "how"]):
        rare_attrs.append("Điều kiện và bước thực hiện")
    if any(sig in entity_lower for sig in ["rủi ro", "lưu ý", "cảnh báo", "sai lầm"]):
        rare_attrs.append("Rủi ro và điều kiện kiểm chứng")

    unique_attrs = []
    if any(sig in entity_lower for sig in ["2025", "2026", "mới nhất", "cập nhật"]):
        unique_attrs.append("Mốc thời gian hoặc phiên bản áp dụng")
    if any(sig in entity_lower for sig in ["việt nam", "hà nội", "tp hcm", "địa phương"]):
        unique_attrs.append("Bối cảnh địa lý hoặc thị trường áp dụng")

    return {
        "root_attributes": root_attrs,
        "rare_attributes": rare_attrs if rare_attrs else ["Cần lấy từ PAA, SERP, EAV hoặc source context"],
        "unique_attributes": unique_attrs if unique_attrs else ["Cần xác minh từ dữ liệu đầu vào hiện tại"],
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
        entity_label = (entity or topic or "chủ đề này").strip()
        intent_lower = (intent or "informational").lower()

        if intent_lower in {"commercial", "vs", "comparison"}:
            fallback_h2s = [
                f"So sánh {entity_label}: định nghĩa và tiêu chí đối chiếu cốt lõi",
                f"Các nhóm thuộc tính chính cần dùng để đánh giá {entity_label}",
                f"{entity_label} khác nhau như thế nào ở cơ chế, chi phí và điều kiện áp dụng?",
                f"Khi nào nên ưu tiên từng lựa chọn liên quan đến {entity_label}?",
                f"Rủi ro, sai lầm thường gặp và các điểm cần lưu ý khi chọn {entity_label}",
                f"Câu hỏi thường gặp về {entity_label}",
            ]
        elif intent_lower in {"how-to", "transactional"}:
            fallback_h2s = [
                f"{entity_label} là gì và cần chuẩn bị gì trước khi bắt đầu?",
                f"Quy trình hoặc các bước triển khai {entity_label} trong thực tế",
                f"Các điều kiện, chi phí và mốc cần kiểm tra khi áp dụng {entity_label}",
                f"Những lỗi thường gặp và cách tránh khi triển khai {entity_label}",
                f"Khi nào không nên áp dụng {entity_label}?",
                f"Câu hỏi thường gặp về {entity_label}",
            ]
        else:
            fallback_h2s = [
                f"{entity_label} là gì? Định nghĩa và phạm vi áp dụng",
                f"Các loại hình, cấu trúc hoặc thành phần chính của {entity_label}",
                f"{entity_label} hoạt động như thế nào? Cơ chế và quy trình thực tế",
                f"Lợi ích, rủi ro và các điều kiện áp dụng {entity_label}",
                f"Chi phí, tiêu chí đánh giá hoặc các lưu ý quan trọng về {entity_label}",
                f"Câu hỏi thường gặp về {entity_label}",
            ]

        headings.extend([{"level": "H2", "text": text} for text in fallback_h2s])

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
        "trang hỗ trợ",
        "cổng thông tin",
        "nội dung quảng cáo",
        "bài pr",
        "mã khuyến mãi",
        "đặt lịch",
        "đăng ký tư vấn",
        "tải tài liệu",
        "xem bảng giá",
        "mẫu biểu",
        "form liên hệ",
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


def _call_llm_k2q(client, model: str, system: str, user: str) -> str:
    """Helper goi LLM cho K2Q voi JSON output, retry built-in."""
    try:
        from modules.llm_utils import call_llm_with_retry, LLM_DEFAULTS
        return call_llm_with_retry(
            client=client,
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.5,
            max_tokens=600,
            timeout=LLM_DEFAULTS["timeout"],
            response_format={"type": "json_object"},
        )
    except Exception:
        return ""


def _generate_k2q_llm(topic: str, entity: str, serp_data: dict = None) -> List[str]:
    """
    Phase 24: Sinh cau hoi K2Q (Keyword-to-Question) bang LLM.
    Uu tien 1: line-by-line (hoat dong nhu ban cu).
    Uu tien 2: JSON parse (neu LLM tra dung format).
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            raise ValueError("No API key")

        import openai
        client = openai.OpenAI(api_key=api_key)

        serp_entities = []
        if serp_data:
            ents = serp_data.get("serp_entities", {})
            serp_entities = (ents.get("primary", []) + ents.get("secondary", []))[:10]
            serp_entities += serp_data.get("serp_attributes", [])[:5]

        entities_context = ", ".join(serp_entities) if serp_entities else "khong co SERP"

        system_prompt, user_prompt = build_k2q_prompts(
            topic=topic,
            entity=entity,
            serp_entities_context=entities_context,
        )

        raw = _call_llm_k2q(client, LLM_CONFIG.get("model", "gpt-4o-mini"), system_prompt, user_prompt)

        # Uu tien 1: Line-splitting (hoat dong nhu ban cu)
        questions = []
        if raw:
            questions = [
                line.strip().lstrip("0123456789.-) ").strip()
                for line in raw.split("\n")
                if line.strip() and len(line.strip()) > 10
            ]

        # Uu tien 2: JSON parse (neu raw chua JSON)
        if not questions and raw:
            import json as _json
            try:
                data = _json.loads(raw)
                if isinstance(data, dict) and "questions" in data:
                    questions = data["questions"]
            except (_json.JSONDecodeError, TypeError, AttributeError):
                pass

        if questions:
            logger.info("  [K2Q] LLM sinh thanh cong %d cau hoi.", len(questions))
            return questions[:7]

        logger.warning("  [K2Q] Khong the parse K2Q, dung fallback template.")
    except Exception as e:
        logger.warning("  [K2Q] LLM loi (%s) -> Dung fallback.", str(e))

    return [
        f"{entity} la gi? Dinh nghia va phan loai",
        f"Ung dung chinh cua {entity} trong thuc te",
        f"So sanh cac loai {entity} pho bien nhat",
        f"Tieu chuan ky thuat khi lua chon {entity}",
        f"Nhung luu y an toan khi su dung {entity}",
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
        questions.extend(_normalize_question_items(serp_data["people_also_ask"]))

    # Thêm related searches nếu thiếu
    if serp_data and len(questions) < 5:
        for rs in serp_data.get("related_searches", []):
            if rs not in questions and len(questions) < 7:
                questions.append(rs)

    # ── Phase 24: K2Q LLM-based (thay thế template cứng) ──
    if not questions:
        questions = _normalize_question_items(_generate_k2q_llm(topic, entity, serp_data))

    return _normalize_question_items(questions)[:7]


def _suggest_related_topics(topic: str, entity: str) -> List[str]:
    """
    Đề xuất chủ đề liên quan cho internal linking.

    Returns:
        Danh sách 3-5 chủ đề liên quan.
    """
    # Không tự bịa related topics theo một ngành cố định.
    return []
