# -*- coding: utf-8 -*-
"""
agent_reviewer.py - Agent 3 & 4: Semantic Review Agents (Multi-Pass)

SPEC FIX V4: Koray Tuğberk Gürbüz Framework (Lectures 14-67)
Tất cả logic dựa trên NGUYÊN TẮC Semantic SEO, industry-agnostic.

Pipeline:
  Pass 3a: review_structure()             — H2 reorder + heading rewrite (entity+attribute)
  Pass 3b: review_h3_depth()              — H3 data-driven từ 5 nguồn
  Pass 3c: review_ngram_quality()         — N-gram 5-step filter pipeline
  Pass 3d: review_anchor_quality()        — Anchor entity+attribute + 6 rules
  Pass 4:  generate_per_h2_instructions() — Contextual Structure per-H2 (8 thành phần Koray)
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _normalize_plain_text(text: str) -> str:
    value = str(text or "").lower()
    value = re.sub(r"[^a-z0-9\s]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _call_llm(system_prompt: str, user_content: str, max_tokens: int = 2000) -> Optional[str]:
    """Helper: Gọi LLM 1 lần, trả về raw text. Nếu lỗi → None (graceful fallback)."""
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return None

        import openai
        client = openai.OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=60,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return raw.strip()

    except Exception as e:
        logger.warning("  [AGENT] LLM call failed: %s", str(e))
        return None


def _extract_json_payload(raw: str, expect: str = "array") -> Optional[Any]:
    """Recover the first JSON array/object from a noisy LLM response."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    open_char = "[" if expect == "array" else "{"
    close_char = "]" if expect == "array" else "}"
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start < 0 or end < start:
        return None
    candidate = text[start:end + 1].strip()
    try:
        return json.loads(candidate)
    except Exception:
        return None


# ══════════════════════════════════════════════
#  PASS 3a: STRUCTURE VALIDATOR + HEADING REWRITE
#  (V4.2 — Attribute Filtration + Entity+Attribute Pattern)
# ══════════════════════════════════════════════

def review_structure(
    outline: List[Dict],
    intent: str,
    macro_context: str = "",
    main_keyword: str = "",
    eav_table: str = "",
    keyword_clusters: List[str] = None,
    paa_questions: List[str] = None,      # Phase 38: PAA questions cho heading bám sát search intent
    content_gaps_list: List[str] = None,  # Phase 38: Content gaps cho heading có information gain
    consensus_points: List[str] = None,
    gap_h2_candidates: List[str] = None,
) -> List[Dict]:
    """
    Pass 3a (V4): Đánh giá + REWRITE heading dựa trên Attribute Filtration Trinity
    và enforce pattern [Entity]+[Attribute]+[Context].

    Koray Lecture 16: "The entire anatomy of a content brief stems from the query terms.
    We must process/filter the attributes to increase important attributes overall
    relevance in the contextual vectors."
    """
    if not outline:
        return outline

    h2_only = [h for h in outline if h.get("level") == "H2"]
    if len(h2_only) < 2:
        return outline

    system_prompt = (
        "Bạn là chuyên gia Semantic SEO Reviewer (Koray Tuğberk GÜBÜR Framework).\n"
        "Nhiệm vụ: ĐÁNH GIÁ, SẮP XẾP, và VIẾT LẠI tên H2 headings.\n\n"

        "═══ NGUYÊN TẮC 1: ATTRIBUTE FILTRATION TRINITY ═══\n"
        "Sắp xếp H2 theo 3 tiêu chí (ưu tiên giảm dần):\n"
        "① PROMINENCE: Attribute KHÔNG THỂ tách khỏi định nghĩa entity → đặt H2 sớm nhất.\n"
        "   Test: 'Có thể định nghĩa entity mà KHÔNG đề cập attribute này không?' → Nếu KHÔNG → Prominent.\n"
        "② POPULARITY: Attribute có nhiều search query variants → đặt H2 sớm.\n"
        "   Test: Attribute này có bao nhiêu biến thể trong keyword clusters?\n"
        "③ RELEVANCE: Attribute liên quan trực tiếp đến Source Context → đặt H2.\n"
        "   Test: Attribute có tạo lợi thế cạnh tranh cho brand không?\n\n"

        "═══ NGUYÊN TẮC 2: FIRST H2 BẮT BUỘC BÁM VÀO MAIN PAA QUESTION ═══\n"
        "H2#1 PHẢI lấy TRỰC TIẾP nội dung từ câu hỏi PAA đầu tiên (đã cung cấp ở trên).\n"
        "Pattern ưu tiên: '[Entity] + [câu hỏi chính]'. Với informational/how-to, hãy ưu tiên H2/H3 dạng câu hỏi.\n"
        "Chỉ dùng dạng mô tả khi câu hỏi quá dài hoặc làm heading trở nên gượng.\n"
        "❌ SAI: '[MAIN] Tổng quan' hoặc '[MAIN] Lợi ích' (không nói rõ entity/attribute)\n"
        "✅ ĐÚNG: '[MAIN] [Entity] là gì? Phạm vi, nhóm chính và điều kiện áp dụng?'\n"
        "✅ ĐÚNG: '[MAIN] [Entity]: Cơ chế hoạt động và tiêu chí đánh giá trong bối cảnh hiện tại?'\n"
        "H2#1 phải chứa ≥3 từ khóa trọng số cao từ main PAA question.\n\n"

        "═══ NGUYÊN TẮC 3: CONTEXTUAL FLOW ═══\n"
        "H2 đầu tiên PHẢI trả lời trực tiếp Search Intent:\n"
        "  Informational/What-is → H2#1 = Định nghĩa entity + phân loại (bám PAA).\n"
        "  Comparison/VS → H2#1 = Tiêu chí so sánh tổng quan hoặc định nghĩa 2 đối tượng.\n"
        "  How-to → H2#1 = Tổng quan quy trình.\n"
        "  Commercial → H2#1 = Tiêu chí lựa chọn.\n\n"

        "═══ NGUYÊN TẮC 3: MAIN vs SUPPLEMENT (Suy luận, KHÔNG dùng danh sách cố định) ═══\n"
        "  [MAIN]: H2 TRỰC TIẾP trả lời Search Intent gốc. Với informational/how-to, ưu tiên câu hỏi hóa heading.\n"
        "  [SUPP]: Thông tin phụ trợ (brand giới thiệu, FAQ, CTA, bảng giá riêng 1 brand).\n"
        "  Test: 'H2 này trả lời câu hỏi gốc, hay chỉ quảng bá/bổ sung?'\n\n"

        "═══ NGUYÊN TẮC 4: VIẾT LẠI TÊN HEADING (BẮT BUỘC) ═══\n"
        "Pattern: [Entity Name hoặc Attribute noun] + [Context qualifier]\n"
        "Dùng colon (Koray Lecture 57): '[Attribute]: [Context]' để tăng embedding weight.\n\n"
        "VALIDATE: Mỗi H2 PHẢI chứa ≥1 NOUN cụ thể (entity name HOẶC attribute noun).\n"
        "Test: 'Heading này có thể dùng nguyên cho bài về ngành khác không?'\n"
        "→ Nếu CÓ (quá generic) → VIẾT LẠI bắt buộc.\n\n"

        "❌ SAI: 'Tổng quan', 'Đặc điểm', 'Ứng dụng', 'Lưu ý quan trọng' (adjective đơn thuần)\n"
        "✅ ĐÚNG: Heading phải ghép entity/attribute thực từ dữ liệu đầu vào, không copy ví dụ ngành.\n\n"

        "PATTERN THEO INTENT TYPE:\n"
        "  Informational: ưu tiên [Entity] + [câu hỏi định nghĩa/thuộc tính] hoặc [Entity]: [Attribute + Context]\n"
        "  How-to: ưu tiên [Cách/Quy trình] [Verb] [Entity]?; nếu không tự nhiên mới dùng mô tả.\n"
        "  Comparison/VS (BẮT BUỘC TUÂN THỦ TUYỆT ĐỐI): Cấm dùng 'Đặc điểm của A và B' hoặc 'Ứng dụng của A và B'. "
        "PHẢI DÙNG PATTERN: '[Attribute]: [Entity A] vs [Entity B]' với entity/attribute sinh từ query hiện tại.\n"
        "  Transactional: Bảng [Attribute] [Entity]: [Thương hiệu/Tháng/Năm]\n"
        "  SUPP: Khi nào KHÔNG [Action] [Entity]? hoặc FAQ [Entity]...\n\n"

        "OUTPUT: JSON array [{\"level\":\"H2\", \"text\":\"[MAIN] hoặc [SUPP] + heading ĐÃ VIẾT LẠI\"}].\n"
        "BẮT BUỘC viết lại heading. KHÔNG giữ nguyên nếu heading quá generic.\n"
                "5. CONTEXTUAL DILUTION CHECK: Không được có 2 H2 [MAIN] cùng attribute type liền nhau.\n"
        "   VD SAI: H2#1 (Definitional) + H2#2 (Definitional) → dilution → trừ điểm.\n"
        "   GIẢI PHÁP: SAPO giữa 2 H2 cùng type → câu nối từ Attribute A → Attribute B.\n\n"
        "6. SOURCE CONTEXT + CENTRAL SEARCH INTENT (Koray G1 — BẮT BUỘC):\n"
        "   Input sẽ có 'Source Context' và 'Central Search Intent' — dùng để đánh giá ATTRIBUTE RELEVANCE.\n"
        "   Attribute không phù hợp Source Context → đánh điểm RELEVANCE thấp → loại.\n"

    )
    # Phase 38 Fix: PAA + Content Gaps được truyền trực tiếp từ content_brief_builder
    user_content = (
        f"Search Intent: {intent}\n"
        f"Central Entity: {main_keyword}\n"
        f"Central Search Intent: {intent}\n"
        f"Source Context: Macro Context={macro_context[:300] if macro_context else 'N/A'}\n"
    )
    if macro_context:
        user_content += f"Macro Context: {macro_context}\n"
    if eav_table:
        user_content += f"\nEAV Table (Entity-Attribute-Value) — đây là các thuộc tính kỹ thuật THỰC TẾ:\n{eav_table[:1500]}\n"
    # Phase 38: Inject PAA questions để LLM viết heading bám sát user queries
    _paa = paa_questions if paa_questions else []
    if _paa:
        user_content += f"\nPAA Questions (Câu hỏi người dùng THỰC SỰ hỏi trên Google) — DÙNG TRỰC TIẾP để viết H2:\n"
        for q in _paa[:7]:
            user_content += f"  - {q}\n"
    _gaps = content_gaps_list if content_gaps_list else []
    if _gaps:
        user_content += f"\nContent Gaps (Khoảng trống đối thủ — cơ hội tạo Information Gain):\n"
        for g in _gaps[:7]:
            user_content += f"  - {g}\n"
    _consensus = consensus_points if consensus_points else []
    if _consensus:
        user_content += "\nConsensus Information (consensus anchors for H2):\n"
        for c in _consensus[:6]:
            user_content += f"  - {c}\n"
    _gap_h2 = gap_h2_candidates if gap_h2_candidates else []
    if _gap_h2:
        user_content += "\nBroad Gap Topics (can be promoted to H2):\n"
        for g in _gap_h2[:5]:
            user_content += f"  - {g}\n"
    if keyword_clusters:
        user_content += f"\nTop Keyword Clusters (biến thể từ khóa phổ biến):\n"
        user_content += f"{', '.join([str(k) for k in keyword_clusters[:15]])}\n"
    user_content += (
        f"\nDanh sách H2 hiện tại (QUÁ GENERIC — VIẾT LẠI bắt buộc):\n"
        f"{json.dumps(h2_only, ensure_ascii=False, indent=2)}\n"
        "\nYÊU CẦU: MỖI H2 PHẢI bám vào CÂU HỎI PAA hoặc ATTRIBUTE THỰC TẾ từ EAV. "
        "Không dùng heading dạng 'Tổng quan', 'Đặc điểm' đứng một mình."
    )

    logger.info("  [AGENT 3a V4] Structure + Heading Rewrite: %d H2s...", len(h2_only))
    raw = _call_llm(system_prompt, user_content, max_tokens=2500)

    if not raw:
        logger.warning("  [AGENT 3a] LLM failed → giữ outline gốc.")
        return outline

    reviewed_h2s = _extract_json_payload(raw, expect="array")
    if reviewed_h2s is None:
        logger.warning("  [AGENT 3a] JSON parse failed: unable to recover JSON array.")
        return outline
    if not isinstance(reviewed_h2s, list) or not reviewed_h2s:
        return outline

    valid_h2s = [h for h in reviewed_h2s if isinstance(h, dict) and "level" in h and "text" in h]

    # DEFECT FIX Phase 41: H2 count mismatch → VẪN proceed với merge H3
    # (trước đây: return outline → dead code ở dưới → H3 bị DROP + H2 không được viết lại)
    if len(valid_h2s) != len(h2_only):
        logger.warning(
            "  [AGENT 3a] H2 count mismatch (%d vs %d) → vẫn proceed để merge H3.",
            len(valid_h2s), len(h2_only)
        )

    # Build H3 children map từ original outline
    # Build H3 children map from original outline. Do not rewrite H2s with canned fallback templates.
    h2_to_children = {}
    current_h2_idx = -1
    h2_order = []
    for h in outline:
        if h.get("level") == "H2":
            h2_order.append(h["text"])
            h2_to_children[h["text"]] = []
            current_h2_idx = len(h2_order) - 1
        elif current_h2_idx >= 0:
            h2_to_children[h2_order[current_h2_idx]].append(h)

    # Rebuild outline: new H2s + merged H3 children
    result = []
    for new_h2 in valid_h2s:
        new_text = new_h2["text"]
        result.append({"level": "H2", "text": new_text})

        # Match children: strip prefix, fuzzy match
        clean_new = re.sub(r'\[MAIN\]\s*|\[SUPP\]\s*', '', new_text).strip().lower()
        matched = None
        for orig_text in h2_order:
            clean_orig = re.sub(r'\[MAIN\]\s*|\[SUPP\]\s*', '', orig_text).strip().lower()
            if clean_orig == clean_new or clean_orig in clean_new or clean_new in clean_orig:
                matched = h2_to_children.get(orig_text, [])
                break

        # Fallback: positional match
        if matched is None:
            idx = valid_h2s.index(new_h2)
            if idx < len(h2_order):
                matched = h2_to_children.get(h2_order[idx], [])

        if matched:
            result.extend(matched)

    # Nếu valid_h2s rỗng (LLM return rác) → fallback về original outline
    if not valid_h2s:
        logger.warning("  [AGENT 3a] No valid H2s from LLM → giữ original outline.")
        return outline

    logger.info("  [AGENT 3a V4] Structure validated + headings rewritten: %d items (%d H3s merged).",
                len(result), len([h for h in result if h.get("level") == "H3"]))
    return result


# ══════════════════════════════════════════════
#  PASS 3b: H3 DEPTH REVIEWER
#  (V4.1 — 5 Nguồn Data + 6 Rules H3)
# ══════════════════════════════════════════════

def review_h3_depth(
    outline: List[Dict],
    content_gaps: List[str],
    paa_questions: List[str],
    keyword_clusters: List[str],
    main_keyword: str = "",
    eav_table: str = "",
) -> List[Dict]:
    """
    Pass 3b (V4): Kiểm tra + bổ sung H3 từ 5 nguồn data theo ưu tiên.

    Koray Lecture 47: "H2s act as sub-articles and summaries of the H3s.
    H3s get their context from the root question in the H2."
    """
    if not outline:
        return outline

    # Chuẩn bị 5 data sources theo ưu tiên
    data_sources = ""
    if paa_questions:
        data_sources += "NGUỒN 1 (Ưu tiên cao nhất) — PAA Questions:\n"
        for q in paa_questions[:5]:
            data_sources += f"  - {q}\n"
    if keyword_clusters:
        data_sources += "\nNGUỒN 2 (Ưu tiên cao) — Keyword Clusters (biến thể size/spec):\n"
        for k in keyword_clusters[:10]:
            data_sources += f"  - {k}\n"
    if content_gaps:
        data_sources += "\nNGUỒN 3 (Ưu tiên TB) — Semantic Voids (đối thủ chưa cover):\n"
        for g in content_gaps[:7]:
            data_sources += f"  - {g}\n"
    if eav_table:
        data_sources += f"\nNGUỒN 4 (Ưu tiên TB) — EAV Table Attributes:\n{eav_table[:800]}\n"
    data_sources += (
        "\nNGUỒN 5 (Vị trí đặc biệt) — Boolean Questions:\n"
        "  Tự sinh từ pattern: '[Entity] có [attribute] không?' hoặc 'Có thể [action] [entity] không?'\n"
        "  Đặt ở H3 CUỐI CÙNG của H2 hoặc H4.\n"
    )

    if not data_sources.strip():
        logger.info("  [AGENT 3b] Không có data sources → skip.")
        return outline

    system_prompt = (
        "Bạn là chuyên gia Semantic SEO Reviewer (Koray Framework, Lecture 47).\n"
        "Nhiệm vụ DUY NHẤT: Kiểm tra và bổ sung H3 cho các H2 [MAIN].\n\n"

        "═══ LÝ THUYẾT NỀN TẢNG ═══\n"
        "H2 = sub-article, SUMMARY của các H3 bên dưới.\n"
        "H3 = contextual depth, thu hẹp và đào sâu attribute của H2 cha.\n"
        "H4 = micro context, boolean questions, voice search triggers.\n"
        "Khi KHÔNG có H3 → Google chỉ thấy flat document → mất Contextual Consolidation.\n\n"

        "═══ 6 RULES BẮT BUỘC ═══\n"
        "RULE H3-1: Tối thiểu 50% H2 [MAIN] phải có ≥1 H3.\n"
        "RULE H3-2: Mỗi H3 = [Entity/Attribute cụ thể] + [Context]. Ưu tiên câu hỏi ngắn nếu đó là FAQ/answer block. KHÔNG adjective phrase đơn thuần.\n"
        "RULE H3-3: H3 thu hẹp context H2 cha — KHÔNG mở rộng sang attribute khác.\n"
        "RULE H3-4: Mỗi H2 tối đa 3 H3 (tránh over-segmentation).\n"
        "RULE H3-5: H3 phải XUẤT HIỆN trong outline — KHÔNG chỉ trong body.\n"
        "RULE H3-6: Boolean H3/H4 → đặt CUỐI H2 section. KHÔNG đầu H2.\n\n"

        "RULE H3-7: TRANSITION HINT (Koray Lecture 47): H3 CUÐI của mỗi H2 [MAIN] PHẢI chứa contextual hint dẫn vào H2 tiếp theo.\n"
        "   Công thức: '[Attribute/Entity hiện tại] → chuẩn bị cho [Attribute của H2 sau]'\n"
        "   H3 cuối phải dùng attribute thực của section hiện tại để mở đường sang section sau.\n"
        "   TEST: Đọc H3 cuối → người đọc có MUỐN chuyển sang section tiếp theo không?\n"

        "═══ 5 NGUỒN SINH H3 (theo thứ tự ưu tiên) ═══\n"
        "1. PAA Questions → mỗi PAA = 1 candidate H3, giữ dạng câu hỏi nếu tự nhiên\n"
        "2. Keyword Clusters -> H3 only when clusters from this request justify a specific subtopic\\n"
        "3. Semantic Voids (heading chỉ 1 đối thủ có) → H3 thay vì H2 để tránh over-segmentation\n"
        "4. EAV Table Attributes → derived attributes → H3 dưới H2 chứa parent attribute\n"
        "5. Boolean Questions → H3 hoặc H4 cuối section\n\n"

        "❌ TUYỆT ĐỐI CẤM:\n"
        "  'Chi tiết về X như thế nào?' (template formula)\n"
        "  'Ứng dụng thực tế phổ biến nhất là gì?' (generic)\n"
        "Use only PAA, keyword clusters, semantic voids, and EAV facts from this request. Do not copy examples or invent domain-specific specs.\n\n"
        "OUTPUT: TOÀN BỘ outline JSON (H2+H3+H4), đã bổ sung/sửa.\n"
        "KHÔNG thêm/xóa H2. KHÔNG trả lời gì ngoài JSON array."
    )

    user_content = (
        f"Central Entity: {main_keyword}\n\n"
        f"DỮ LIỆU ĐỂ SINH H3:\n{data_sources}\n\n"
        f"Outline hiện tại (cần review H3):\n"
        f"{json.dumps(outline, ensure_ascii=False, indent=2)}"
    )

    logger.info("  [AGENT 3b V4] H3 Depth Reviewer: reviewing...")
    raw = _call_llm(system_prompt, user_content, max_tokens=3000)

    if not raw:
        logger.warning("  [AGENT 3b] LLM failed → giữ outline gốc.")
        return outline

    reviewed = _extract_json_payload(raw, expect="array")
    if reviewed is None:
        logger.warning("  [AGENT 3b] JSON parse failed: unable to recover JSON array.")
        return outline
    if not isinstance(reviewed, list) or not reviewed:
        return outline

    orig_h2_count = sum(1 for h in outline if h.get("level") == "H2")
    new_h2_count = sum(1 for h in reviewed if isinstance(h, dict) and h.get("level") == "H2")
    if new_h2_count != orig_h2_count:
        logger.warning("  [AGENT 3b] H2 count mismatch (%d→%d) → giữ gốc.", orig_h2_count, new_h2_count)
        return outline

    valid = []
    for item in reviewed:
        if isinstance(item, dict) and "level" in item and "text" in item:
            lvl = str(item["level"]).upper()
            if lvl in ["H2", "H3", "H4"]:
                valid.append({"level": lvl, "text": item["text"]})

    if valid:
        new_h3 = sum(1 for h in valid if h["level"] == "H3")
        logger.info("  [AGENT 3b V4] Done: %d items, %d H3s.", len(valid), new_h3)
        return valid
    return outline


# ══════════════════════════════════════════════
#  PASS 3c: N-GRAM SEMANTIC QUALITY GATE
#  (V4.5 — 5-Step Filter Pipeline)
# ══════════════════════════════════════════════

def review_ngram_quality(
    ngrams: List[str],
    entity: str,
    intent: str = "",
) -> List[str]:
    """
    Pass 3c (V4): Lọc N-gram theo 5-step pipeline từ SPEC V4.
    """
    if not ngrams or len(ngrams) <= 2:
        return ngrams

    system_prompt = (
        "Ban la chuyen gia ngon ngu hoc tieng Viet va Semantic SEO.\n"
        "Nhiem vu: Loc N-grams theo 5-STEP PIPELINE.\n\n"

        "KORAY THRESHOLDS (Bat buoc ap dung):\n"
        "1. co_occurrence_threshold: term phai xuat hien trong >=3 bai top SERP.\n"
        "   -> Neu <3 -> LOAI (khong du bang chung).\n"
        "2. proximity_window: term cach keyword chinh <=5 tu trong cau.\n"
        "   -> Neu >5 -> LOAI (qua xa de semantic lien quan).\n"
        "3. entity_presence: N-gram phai chua >=1 NOUN cu the.\n"
        "   -> Neu chi co adjective/verb/unit -> LOAI.\n"
        "4. brand_ngram: brand name trong N-gram -> GIU NGUYEN, khong loai bo.\n"
        "5. min_fragment_length: >=3 tu hoac >=8 ky tu -> moi duoc giu.\n\n"

        "5-STEP PIPELINE:\n"
        "STEP 1 — COMPLETENESS: N-gram co >=1 NOUN cu the khong?\n"
        "   -> Khong (chi adjective/verb/unit) -> LOAI.\n\n"
        "STEP 2 — DUPLICATE UNIT: Co don vi do lap lai? (mm mm, kg kg, MPa MPa)\n"
        "   -> artifact tu table extraction -> LOAI.\n\n"
        "STEP 3 — FRAGMENT: N-gram dung doc lap co nghia khong?\n"
        "   Test: 'Chung toi cung cap [n-gram]' -> co nghia? -> Khong -> LOAI.\n"
        "   Vi du LOAI: 'toan khac quy', 'dung thuc the', 'khoi luong chieu'.\n\n"
        "STEP 4 — THRESHOLD FILTER: Loc theo 5 Koray thresholds tren.\n\n"
        "STEP 5 — BRAND EXPANSION: Fragment brand -> expand thanh full phrase.\n"
        "   Neu fragment la brand, chi expand khi source context hien tai co day du brand + entity.\n\n"

        "OUTPUT: JSON array of strings — CHI N-grams DAT (toi da 10).\n"
        "KHONG tra loi gi ngoai JSON array."
    )

    user_content = (
        f"Entity chính: {entity}\n"
        f"Search Intent: {intent}\n\n"
        f"Danh sách N-grams cần đánh giá:\n"
        f"{json.dumps(ngrams, ensure_ascii=False)}"
    )

    logger.info("  [AGENT 3c V4] N-gram Quality Gate: %d items...", len(ngrams))
    raw = _call_llm(system_prompt, user_content, max_tokens=500)

    if not raw:
        logger.warning("  [AGENT 3c] LLM failed → giữ gốc.")
        return ngrams

    clean = _extract_json_payload(raw, expect="array")
    if isinstance(clean, list) and clean:
        clean = [str(ng) for ng in clean if isinstance(ng, str) and len(ng) >= 3]
        logger.info("  [AGENT 3c V4] Filtered: %d → %d.", len(ngrams), len(clean))
        return clean if clean else ngrams
    logger.warning("  [AGENT 3c] Parse error → giữ gốc.")
    return ngrams


# ══════════════════════════════════════════════
#  PASS 3d: ANCHOR TEXT REVIEWER
#  (V4.3 — 6 Rules Anchor + Duplicate Detection)
# ══════════════════════════════════════════════

def review_anchor_quality(
    outbound_nodes: List[Dict],
    central_entity: str,
    intent: str = "",
) -> List[Dict]:
    """
    Pass 3d (V4): Kiểm tra và sửa anchor text theo 6 rules Koray.

    Koray Lecture 53: "Utilising the phrase in the heading that we are going to use
    in our anchor text allows for greater justification of relevance."
    Lecture 38: "Whatever entity used inside the internal link is mentioned in a
    synonym phrase in the corresponding heading."
    """
    if not outbound_nodes:
        return outbound_nodes

    # Pre-check: duplicate word detection (rule-based, trước LLM)
    for node in outbound_nodes:
        anchor = node.get("anchor", "")
        words = anchor.lower().split()
        # Detect consecutive duplicate words
        for i in range(len(words) - 1):
            if words[i] == words[i + 1] and len(words[i]) > 2:
                logger.warning("  [ANCHOR] Duplicate word detected: '%s' in '%s'", words[i], anchor)
                # Remove duplicate
                fixed = []
                prev = None
                for w in words:
                    if w != prev or len(w) <= 2:
                        fixed.append(w)
                    prev = w
                node["anchor"] = " ".join(fixed)
                break

    # [SPEC V5.8] Pre-check: Anchor contains ONLY adjectives/verbs (No Noun)
    adjective_only_patterns = [
        r"^lưu ý(\s+quan trọng)?$",
        r"^tổng quan$",
        r"^chi tiết$",
        r"^tìm hiểu(\s+thêm)?$",
        r"^xem(\s+thêm)?$",
        r"^(những\s+)?điều(\s+cần\s+biết)?$",
        r"^hướng dẫn$",
        r"^đặc điểm$",
        r"^ứng dụng$",
    ]

    for node in outbound_nodes:
        # Check primary anchor
        anchor_lower = node.get("anchor", "").lower().strip()
        is_adjective_only = any(re.match(pattern, anchor_lower) for pattern in adjective_only_patterns)

        if is_adjective_only and central_entity:
            # Append entity name to make it a valid anchor
            new_anchor = f"{node.get('anchor', '').strip()} về {central_entity}"
            logger.info("  [ANCHOR V5.8] Fixed adjective-only anchor: '%s' -> '%s'", node.get("anchor"), new_anchor)
            node["anchor"] = new_anchor

        # Also check all_anchors variants
        all_anchors = node.get("all_anchors", {})
        for key in list(all_anchors.keys()):
            txt = all_anchors[key]
            if isinstance(txt, str):
                txt_lower = txt.lower().strip()
                if any(re.match(pattern, txt_lower) for pattern in adjective_only_patterns):
                    new_txt = f"{txt.strip()} về {central_entity}"
                    logger.info("  [ANCHOR V5.8] Fixed adjective-only variant (%s): '%s' -> '%s'", key, txt, new_txt)
                    all_anchors[key] = new_txt

    # Also fix all_anchors variants for duplicate words
    for node in outbound_nodes:
        all_anchors = node.get("all_anchors", {})
        for key in all_anchors:
            txt = all_anchors[key]
            if isinstance(txt, str):
                words = txt.split()
                fixed = []
                prev = None
                for w in words:
                    if w.lower() != (prev.lower() if prev else "") or len(w) <= 2:
                        fixed.append(w)
                    prev = w
                all_anchors[key] = " ".join(fixed)

    # LLM review for semantic quality
    nodes_for_review = []
    for n in outbound_nodes[:8]:
        nodes_for_review.append({
            "topic": n.get("topic", ""),
            "anchor": n.get("anchor", ""),
            "all_anchors": n.get("all_anchors", {}),
        })

    system_prompt = (
        "Bạn là chuyên gia Semantic SEO Reviewer (Koray Framework).\n"
        "Nhiệm vụ: Kiểm tra và SỬA anchor text theo 6 rules.\n\n"

        "═══ 7 RULES ANCHOR TEXT (Koray G1) ═══\n"
        "RULE 1: Primary anchor = target keyword hoặc biến thể H1 trang đích.\n"
        "  → Anchor phải chứa ≥1 NOUN (entity name hoặc attribute noun).\n"
        "RULE 2: Anchor variant phải là natural language phrase — người dùng có thể tìm kiếm.\n"
        "  → Test: Paste anchor vào Google → kết quả relate đến trang đích?\n"
        "RULE 3: Anchor KHÔNG ĐƯỢC là adjective phrase đứng một mình.\n"
        "  → Banned: 'lưu ý', 'tổng quan', 'chi tiết', 'hướng dẫn' (không có entity).\n"
        "RULE 4: KHÔNG có duplicate word trong anchor (đã pre-fix ở bước trước).\n"
        "RULE 5: Anchor quan trọng nhất ở MAIN content, số lớn ở SUPP.\n"
        "RULE 6: SUPP anchor nên dùng question format.\n"
        "  → '[Entity] có phù hợp với [bối cảnh] không?' thay vì '[Entity] [bối cảnh]'.\n"
        "RULE 7 — TERM PRECEDING (Koray Lecture 23): NHẮC term dùng làm anchor 1-5 LẦN TRƯỚC vị trí đặt link.\n"
        "  → Ghi chú VỊ TRÍ trong output: justification_position.\n"
        "  → Test: Đọc paragraph trước link → có nhắc term 1-5 lần với thông tin ĐỘC QUYỀN không?\n"
        "  → Không → XÓA link hoặc THÊM context.\n\n"

        "❌ SAI: 'lưu ý quan trọng', 'tổng quan', 'xem thêm', 'tìm hiểu thêm'\n"
        "✅ ĐÚNG: anchor chứa entity + attribute thực từ source context, SERP hoặc EAV của keyword hiện tại.\n\n"

        "OUTPUT: JSON array of objects:\n"
        "[{\"topic\":str, \"anchor\":str, \"justification_position\":\"section X, paragraph Y — N lần trước link\", \"all_anchors\":{\"exact\":str, \"semantic\":str, \"question\":str}}].\n"
        "SỬA anchor nếu vi phạm rules. GIỮ NGUYÊN nếu đã tốt.\n"
        "KHÔNG trả lời gì ngoài JSON array."
    )

    user_content = (
        f"Central Entity: {central_entity}\n"
        f"Search Intent: {intent}\n\n"
        f"Anchor nodes can be review:\n"
        f"{json.dumps(nodes_for_review, ensure_ascii=False, indent=2)}\n\n"
        f"Koray G1: Neu co Source Context thi dung de uu tien anchor topic gan nhat voi Source Context."
    )

    logger.info("  [AGENT 3d V4] Anchor Quality: reviewing %d nodes...", len(nodes_for_review))
    raw = _call_llm(system_prompt, user_content, max_tokens=1500)

    if not raw:
        logger.warning("  [AGENT 3d] LLM failed → giữ anchors gốc (đã fix duplicates).")
        return outbound_nodes

    try:
        reviewed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("  [AGENT 3d] JSON parse failed: %s", exc)
        return outbound_nodes
    if not isinstance(reviewed, list):
        return outbound_nodes

    # Merge reviewed anchors back into outbound_nodes
    for i, node in enumerate(outbound_nodes):
        if i < len(reviewed) and isinstance(reviewed[i], dict):
            r = reviewed[i]
            if r.get("anchor"):
                node["anchor"] = r["anchor"]
            if r.get("all_anchors") and isinstance(r["all_anchors"], dict):
                node["all_anchors"] = r["all_anchors"]

    logger.info("  [AGENT 3d V4] Anchor review complete.")
    return outbound_nodes


# ══════════════════════════════════════════════
#  PASS 4: PER-H2 CONTEXTUAL STRUCTURE
#  (V4.4 — 8 Thành phần Koray Lecture 21/39)
# ══════════════════════════════════════════════

def _fallback_per_h2_instructions(
    outline: List[Dict],
    main_keyword: str,
    intent: str,
    classified_ngrams: Dict = None,
    eav_table: str = "",
) -> Dict:
    """Fallback per-H2 contextual instructions."""
    classified_ngrams = classified_ngrams or {}
    h2_texts = [h["text"] for h in outline if isinstance(h, dict) and h.get("level") == "H2"]
    if not h2_texts:
        return {}

    entity_terms = []
    if classified_ngrams.get("entity"):
        entity_terms = [str(x).strip() for x in classified_ngrams.get("entity", [])[:5] if str(x).strip()]
    if not entity_terms:
        entity_terms = [main_keyword]

    def _format_for_heading(text: str) -> str:
        lower = _normalize_plain_text(text)
        if any(sig in lower for sig in ["so sanh", "khac nhau", "vs"]):
            return "Bang so sanh 3 cot"
        if any(sig in lower for sig in ["quy trinh", "cach", "huong dan", "lam sao"]):
            return "List 3-5 buoc"
        if any(sig in lower for sig in ["faq", "cau hoi", "luu y", "rui ro"]):
            return "Paragraph + bullet list"
        return "Paragraph"

    def _heading_terms(text: str, limit: int = 5) -> List[str]:
        tokens = []
        for token in re.split(r"[^0-9A-Za-zÀ-ỹ]+", text or ""):
            token = token.strip()
            if len(token) >= 4:
                tokens.append(token)
        dedup = []
        seen = set()
        for token in tokens:
            norm = _normalize_plain_text(token)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            dedup.append(token)
        return dedup[:limit]

    per_h2 = {}
    for idx, h2 in enumerate(h2_texts[:8]):
        clean = re.sub(r"\[MAIN\]|\[SUPP\]", "", h2).strip()
        lower = _normalize_plain_text(clean)
        content_format = _format_for_heading(clean)
        h2_terms = _heading_terms(clean, limit=5)
        micro_terms = (entity_terms[:3] + [t for t in h2_terms if t not in entity_terms])[:5]
        if "quy trinh" in lower or "cach" in lower:
            sentence_before = f"Có 3-5 bước chính liên quan đến {clean.lower()}, bắt đầu từ điều kiện đầu vào đến kết quả đầu ra:"
            preceding_question = f"{clean} được thực hiện như thế nào?"
            boolean_h3 = None
        elif any(sig in lower for sig in ["so sanh", "khac nhau", "vs"]):
            sentence_before = f"Bảng so sánh giúp làm rõ {clean.lower()} giữa các góc nhìn, mức phí và điều kiện áp dụng:"
            preceding_question = f"{clean} khác nhau như thế nào?"
            boolean_h3 = None
        elif any(sig in lower for sig in ["rui ro", "luu y", "cau hoi", "faq"]):
            sentence_before = f"Phần này tổng hợp các lưu ý, rủi ro và điều kiện cần kiểm tra trước khi áp dụng {clean.lower()}:"
            preceding_question = f"Cần lưu ý điều gì khi tìm hiểu {clean}?"
            boolean_h3 = f"{clean} có rủi ro không?"
        else:
            sentence_before = f"Phần này mở rộng thêm các thuộc tính, định nghĩa và ngữ cảnh của {clean.lower()}:"
            preceding_question = f"{clean} là gì?"
            boolean_h3 = None

        per_h2[h2] = {
            "content_format": content_format,
            "first_sentence": f"{clean} cần được trình bày theo đúng trọng tâm của heading này.",
            "micro_terms": micro_terms,
            "sentence_before": sentence_before,
            "preceding_question": preceding_question,
            "contextual_bridge": f"Ket noi sang phan tiep theo cua {main_keyword}.",
            "boolean_h3": boolean_h3,
            "word_count_target": "200-300 tu" if idx == 0 else "120-180 tu",
            "guidance": f"[{content_format}] Tập trung vào: {', '.join(micro_terms[:5])}. Trả lời trực tiếp '{preceding_question}'.",
            "section_predicates": ["tra loi", "phan tich", "lam ro"],
        }

    return {
        "macro_rules": {
            "central_entity_term": main_keyword,
            "predicate_cluster": ["tra loi", "phan loai", "phat trien", "luu y"],
            "tonality": "informational",
        },
        "per_h2": per_h2,
    }


def generate_per_h2_instructions(
    outline: List[Dict],
    main_keyword: str,
    intent: str,
    classified_ngrams: Dict = None,
    eav_table: str = "",
) -> Dict:
    """
    Pass 4 (V4): Tạo per-H2 contextual instructions theo 8 thành phần Koray.

    Koray Lecture 21: "Contextual Structure tells authors what they should write
    and in what format... for each INDIVIDUAL heading in the contextual vector."

    Returns:
        {
            "macro_rules": {...},
            "per_h2": {
                "H2 text": {
                    "content_format": str,
                    "first_sentence": str,
                    "micro_terms": [str],
                    "sentence_before": str,
                    "preceding_question": str,
                    "contextual_bridge": str,
                    "boolean_h3": str | None
                }
            }
        }
    """
    if not outline:
        return {}

    h2_texts = [h["text"] for h in outline if h.get("level") == "H2"]
    if not h2_texts:
        return {}

    # Chỉ xử lý tối đa 8 H2 để tránh token overflow
    h2_for_review = h2_texts[:8]

    entity_ngrams = []
    if classified_ngrams and classified_ngrams.get("entity"):
        entity_ngrams = classified_ngrams["entity"][:10]

    system_prompt = (
        "Bạn là chuyên gia Semantic SEO Content Strategist (Koray Framework, Lecture 21/39).\n"
        "Nhiệm vụ: Tạo PER-H2 CONTEXTUAL INSTRUCTIONS cho writer.\n\n"

        "═══ 8 THÀNH PHẦN BẮT BUỘC CHO MỖI H2 ═══\n"
        "① Content Format: Table (X cột: [tên cột]) / List (X items) / FS Block (≤40 từ) / Paragraph\n"
        "â'¡ First Sentence Pattern: [Entity] + [Attribute verb] + [Value] + [Qualifier]\n"
        "③ Micro Context Terms BẮT BUỘC (≤5 terms chỉ dùng trong section này, không lan sang section khác)\n"
        "④ Sentence Before List/Table: 'Có X [items] [attribute] [entity], bao gồm:'\n"
        "⑤ Preceding Question (Inquisitive Semantics): câu hỏi tiếp theo sau khi trả lời\n"
        "⑥ Contextual Bridge: 2-3 từ bridge sang H2 tiếp theo\n"
        "⑦ Boolean H3 nếu phù hợp: '[Entity] có [attribute] không?'\n"
        "⑧ Tonality: predicates phù hợp với ngành, intent và source context hiện tại\n"
        "⑨ Word Count Target: số từ cần viết cho section này (VD: '200-300 từ' cho MAIN Definition, '300-400 từ' cho Technical, '100-150 từ' cho SUPP)\n"
        "⑩ Section Predicates: 3-5 động từ/vị ngữ đặc thù cho section (VD: H2 Độ bền → ['đạt','chịu','chống'], H2 Ứng dụng → ['sử dụng','áp dụng','phù hợp'])\n\n"

            "⑪ CONTEXTUAL HINT (Koray Lecture 47): 1-2 từ SIGNAL cho section TIẾP THEO, đặt ở CÂU CUỞI section.\n"
            "   Công thức: '[Thuộc tính/Hành động hiện tại] → chuẩn bị cho [chủ đề section sau]'\n"
            "   Câu cuối phải dùng attribute thực của section hiện tại để báo hiệu section tiếp theo.\n"
            "   TEST: Đọc câu cuối → người đọc có biết section sau nói gì không?\n\n"
        "═══ MACRO RULES (ÁP DỤNG TOÀN BÀI) ═══\n"
        "- Central entity term phải xuất hiện mỗi H2 section ≥1 lần\n"
        "- KHÔNG đặt micro context term section X vào section Y\n"
        "- Predicate cluster nhất quán với tone H1\n\n"

        "OUTPUT FORMAT (JSON):\n"
        "{\n"
        "  \"macro_rules\": {\n"
        "    \"central_entity_term\": str,\n"
        "    \"predicate_cluster\": [str list of verbs],\n"
        "    \"tonality\": str\n"
        "  },\n"
        "  \"per_h2\": {\n"
        "    \"[H2 text]\": {\n"
        "      \"content_format\": str,\n"
        "      \"first_sentence\": str,\n"
        "      \"micro_terms\": [str ≤5],\n"
        "      \"sentence_before\": str,\n"
        "      \"preceding_question\": str,\n"
        "      \"contextual_bridge\": str,\n"
        "      \"boolean_h3\": str or null,\n"
        "      \"word_count_target\": str,\n"
        "      \"section_predicates\": [str list of 3-5 verbs]\n"
        "    }\n"
        "  }\n"
        "}\n"
        "KHÔNG trả lời gì ngoài JSON."
    )

    user_content = (
        f"Central Entity: {main_keyword}\n"
        f"Search Intent: {intent}\n"
    )
    if entity_ngrams:
        user_content += f"Entity N-grams (dùng làm micro context terms): {', '.join(entity_ngrams)}\n"
    if eav_table:
        user_content += f"\nEAV Table:\n{eav_table[:800]}\n"
    user_content += (
        "\nDanh sách H2 (cần tạo per-H2 instructions):\n"
        + "\n".join(f"  {i+1}. {h}" for i, h in enumerate(h2_for_review))
    )

    logger.info("  [AGENT 4 V4] Per-H2 Contextual Structure: %d H2s...", len(h2_for_review))
    raw = _call_llm(system_prompt, user_content, max_tokens=3000)

    if not raw:
        logger.warning("  [AGENT 4] LLM failed → trả về empty.")
        return _fallback_per_h2_instructions(outline, main_keyword, intent, classified_ngrams, eav_table)

    try:
        result = json.loads(raw)
        if isinstance(result, dict) and "per_h2" in result:
            logger.info("  [AGENT 4 V4] Generated per-H2 instructions for %d H2s.", len(result.get("per_h2", {})))
            return result
        return _fallback_per_h2_instructions(outline, main_keyword, intent, classified_ngrams, eav_table)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 4] Parse error: %s → empty.", str(e))
        return _fallback_per_h2_instructions(outline, main_keyword, intent, classified_ngrams, eav_table)
