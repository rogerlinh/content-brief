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
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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

        "═══ NGUYÊN TẮC 2: CONTEXTUAL FLOW ═══\n"
        "H2 đầu tiên PHẢI trả lời trực tiếp Search Intent:\n"
        "  Informational/What-is → H2#1 = Định nghĩa entity + phân loại.\n"
        "  Comparison/VS → H2#1 = Tiêu chí so sánh tổng quan hoặc định nghĩa 2 đối tượng.\n"
        "  How-to → H2#1 = Tổng quan quy trình.\n"
        "  Commercial → H2#1 = Tiêu chí lựa chọn.\n\n"

        "═══ NGUYÊN TẮC 3: MAIN vs SUPPLEMENT (Suy luận, KHÔNG dùng danh sách cố định) ═══\n"
        "  [MAIN]: H2 TRỰC TIẾP trả lời Search Intent gốc.\n"
        "  [SUPP]: Thông tin phụ trợ (brand giới thiệu, FAQ, CTA, bảng giá riêng 1 brand).\n"
        "  Test: 'H2 này trả lời câu hỏi gốc, hay chỉ quảng bá/bổ sung?'\n\n"

        "═══ NGUYÊN TẮC 4: VIẾT LẠI TÊN HEADING (BẮT BUỘC) ═══\n"
        "Pattern: [Entity Name hoặc Attribute noun] + [Context qualifier]\n"
        "Dùng colon (Koray Lecture 57): '[Attribute]: [Context]' để tăng embedding weight.\n\n"
        "VALIDATE: Mỗi H2 PHẢI chứa ≥1 NOUN cụ thể (entity name HOẶC attribute noun).\n"
        "Test: 'Heading này có thể dùng nguyên cho bài về ngành khác không?'\n"
        "→ Nếu CÓ (quá generic) → VIẾT LẠI bắt buộc.\n\n"

        "❌ SAI: 'Tổng quan', 'Đặc điểm', 'Ứng dụng', 'Lưu ý quan trọng' (adjective đơn thuần)\n"
        "✅ ĐÚNG: 'Độ bền kéo và khả năng chịu uốn: Thép cuộn vs Thép vằn theo TCVN'\n"
        "✅ ĐÚNG: 'Ứng dụng trong kết cấu bê tông: Khi nào dùng thép cuộn, khi nào thép vằn?'\n\n"

        "PATTERN THEO INTENT TYPE:\n"
        "  Informational: [Entity]: [Attribute định nghĩa + Context]\n"
        "  How-to: Quy trình [Verb] [Entity]: [Standard/Context]\n"
        "  Comparison/VS (BẮT BUỘC TUÂN THỦ TUYỆT ĐỐI): Cấm dùng 'Đặc điểm của A và B' hoặc 'Ứng dụng của A và B'. "
        "PHẢI DÙNG PATTERN: '[Attribute]: [Entity A] vs [Entity B]'. VD: 'Khả năng chịu lực: Thép cuộn vs Thép vằn'.\n"
        "  Transactional: Bảng [Attribute] [Entity]: [Thương hiệu/Tháng/Năm]\n"
        "  SUPP: Khi nào KHÔNG [Action] [Entity]: [Condition]\n\n"

        "OUTPUT: JSON array [{\"level\":\"H2\", \"text\":\"[MAIN] hoặc [SUPP] + heading ĐÃ VIẾT LẠI\"}].\n"
        "BẮT BUỘC viết lại heading. KHÔNG giữ nguyên nếu heading quá generic.\n"
        "KHÔNG thêm/xóa H2. KHÔNG trả lời gì ngoài JSON array."
    )

    user_content = (
        f"Search Intent: {intent}\n"
        f"Central Entity: {main_keyword}\n"
    )
    if macro_context:
        user_content += f"Macro Context: {macro_context}\n"
    if eav_table:
        user_content += f"\nEAV Table (Entity-Attribute-Value):\n{eav_table[:1500]}\n"
    if keyword_clusters:
        user_content += f"\nKeyword Clusters (cho Popularity scoring): {', '.join(keyword_clusters[:15])}\n"
    user_content += (
        f"\nDanh sách H2 hiện tại (cần đánh giá, sắp xếp, và VIẾT LẠI):\n"
        f"{json.dumps(h2_only, ensure_ascii=False, indent=2)}"
    )

    logger.info("  [AGENT 3a V4] Structure + Heading Rewrite: %d H2s...", len(h2_only))
    raw = _call_llm(system_prompt, user_content, max_tokens=2500)

    if not raw:
        logger.warning("  [AGENT 3a] LLM failed → giữ outline gốc.")
        return outline

    try:
        reviewed_h2s = json.loads(raw)
        if not isinstance(reviewed_h2s, list) or not reviewed_h2s:
            return outline

        valid_h2s = [h for h in reviewed_h2s if isinstance(h, dict) and "level" in h and "text" in h]
        if len(valid_h2s) != len(h2_only):
            logger.warning("  [AGENT 3a] H2 count mismatch (%d vs %d) → giữ gốc.", len(valid_h2s), len(h2_only))
            return outline

        # Rebuild outline với H3 children
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

        result = []
        for new_h2 in valid_h2s:
            new_text = new_h2["text"]
            result.append({"level": "H2", "text": new_text})

            # Match children: strip prefix, fuzzy match
            clean_new = re.sub(r'\[MAIN\]\s*|\[SUPP\]\s*', '', new_text).strip().lower()
            matched = None
            for orig_text in h2_order:
                clean_orig = re.sub(r'\[MAIN\]\s*|\[SUPP\]\s*', '', orig_text).strip().lower()
                # Exact or substring match
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

        logger.info("  [AGENT 3a V4] Structure validated + headings rewritten: %d items.", len(result))
        return result

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 3a] Parse error: %s → giữ gốc.", str(e))
        return outline


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
        "RULE H3-2: Mỗi H3 = [Entity/Attribute cụ thể] + [Context]. KHÔNG adjective phrase đơn thuần.\n"
        "RULE H3-3: H3 thu hẹp context H2 cha — KHÔNG mở rộng sang attribute khác.\n"
        "RULE H3-4: Mỗi H2 tối đa 3 H3 (tránh over-segmentation).\n"
        "RULE H3-5: H3 phải XUẤT HIỆN trong outline — KHÔNG chỉ trong body.\n"
        "RULE H3-6: Boolean H3/H4 → đặt CUỐI H2 section. KHÔNG đầu H2.\n\n"

        "═══ 5 NGUỒN SINH H3 (theo thứ tự ưu tiên) ═══\n"
        "1. PAA Questions → mỗi PAA = 1 candidate H3\n"
        "2. Keyword Clusters (biến thể size/spec: d10, d12, phi 10...) → H3 dạng technical spec\n"
        "3. Semantic Voids (heading chỉ 1 đối thủ có) → H3 thay vì H2 để tránh over-segmentation\n"
        "4. EAV Table Attributes → derived attributes → H3 dưới H2 chứa parent attribute\n"
        "5. Boolean Questions → H3 hoặc H4 cuối section\n\n"

        "❌ TUYỆT ĐỐI CẤM:\n"
        "  'Chi tiết về X như thế nào?' (template formula)\n"
        "  'Ứng dụng thực tế phổ biến nhất là gì?' (generic)\n"
        "✅ ĐÚNG:\n"
        "  'Thép vằn phi 10-32: Bảng trọng lượng theo TCVN 1651-2018' (từ Clusters)\n"
        "  'Cường độ chảy (Fy) vs cường độ kéo (Fu): CB300-V vs GR40' (từ EAV)\n"
        "  'Thép cán nguội có chịu được môi trường biển không?' (Boolean)\n\n"

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

    try:
        reviewed = json.loads(raw)
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

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 3b] Parse error: %s → giữ gốc.", str(e))
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
        "Bạn là chuyên gia ngôn ngữ học tiếng Việt và Semantic SEO.\n"
        "Nhiệm vụ: Lọc N-grams theo 5-STEP PIPELINE.\n\n"

        "STEP 1 — COMPLETENESS CHECK: N-gram có ≥1 NOUN (danh từ) không?\n"
        "  → Nếu KHÔNG (chỉ adjective/verb/unit) → LOẠI\n\n"
        "STEP 2 — DUPLICATE UNIT CHECK: Có đơn vị đo lặp lại không? (mm mm, kg kg, MPa MPa)\n"
        "  → artifact từ table extraction → LOẠI\n\n"
        "STEP 3 — FRAGMENT CHECK: N-gram đứng độc lập có nghĩa không?\n"
        "  Test: 'Chúng tôi cung cấp [n-gram]' — câu có nghĩa không? → Nếu KHÔNG → LOẠI\n"
        "  Ví dụ LOẠI: 'toán khác quy', 'dụng thép thanh', 'khối lượng chiều'\n\n"
        "STEP 4 — USABILITY LIMIT: Giữ tối đa 10 meaningful phrases.\n"
        "  Nếu pass filter >10 → chọn 10 terms liên quan nhất đến entity.\n\n"
        "STEP 5 — BRAND EXPANSION: Fragment brand → expand thành full phrase.\n"
        "  'vằn hòa' → 'thép thanh vằn Hòa Phát'. 'phát pomina' → 'Hòa Phát và Pomina'.\n\n"

        "OUTPUT: JSON array of strings — CHỈ N-grams ĐẠT (tối đa 10).\n"
        "KHÔNG trả lời gì ngoài JSON array."
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

    try:
        clean = json.loads(raw)
        if isinstance(clean, list) and clean:
            clean = [str(ng) for ng in clean if isinstance(ng, str) and len(ng) >= 3]
            logger.info("  [AGENT 3c V4] Filtered: %d → %d.", len(ngrams), len(clean))
            return clean if clean else ngrams
        return ngrams
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 3c] Parse error: %s → giữ gốc.", str(e))
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

        "═══ 6 RULES ANCHOR TEXT ═══\n"
        "RULE 1: Primary anchor = target keyword hoặc biến thể H1 trang đích.\n"
        "  → Anchor phải chứa ≥1 NOUN (entity name hoặc attribute noun).\n"
        "RULE 2: Anchor variant phải là natural language phrase — người dùng có thể tìm kiếm.\n"
        "  → Test: Paste anchor vào Google → kết quả relate đến trang đích?\n"
        "RULE 3: Anchor KHÔNG ĐƯỢC là adjective phrase đứng một mình.\n"
        "  → Banned: 'lưu ý', 'tổng quan', 'chi tiết', 'hướng dẫn' (không có entity).\n"
        "RULE 4: KHÔNG có duplicate word trong anchor (đã pre-fix ở bước trước).\n"
        "RULE 5: Anchor quan trọng nhất ở MAIN content, số lớn ở SUPP.\n"
        "RULE 6: SUPP anchor nên dùng question format.\n"
        "  → 'thép vằn có chịu được môi trường biển không?' thay vì 'thép vằn môi trường biển'.\n\n"

        "❌ SAI: 'lưu ý quan trọng', 'tổng quan', 'xem thêm', 'tìm hiểu thêm'\n"
        "✅ ĐÚNG: 'cường độ chảy thép thanh vằn theo TCVN 1651', 'so sánh thép cuộn và thép vằn'\n\n"

        "OUTPUT: JSON array of objects [{\"topic\":str, \"anchor\":str, \"all_anchors\":{\"exact\":str, \"semantic\":str, \"question\":str}}].\n"
        "SỬA anchor nếu vi phạm rules. GIỮ NGUYÊN nếu đã tốt.\n"
        "KHÔNG trả lời gì ngoài JSON array."
    )

    user_content = (
        f"Central Entity: {central_entity}\n"
        f"Search Intent: {intent}\n\n"
        f"Anchor nodes cần review:\n"
        f"{json.dumps(nodes_for_review, ensure_ascii=False, indent=2)}"
    )

    logger.info("  [AGENT 3d V4] Anchor Quality: reviewing %d nodes...", len(nodes_for_review))
    raw = _call_llm(system_prompt, user_content, max_tokens=1500)

    if not raw:
        logger.warning("  [AGENT 3d] LLM failed → giữ anchors gốc (đã fix duplicates).")
        return outbound_nodes

    try:
        reviewed = json.loads(raw)
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

    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 3d] Parse error: %s → giữ gốc.", str(e))
        return outbound_nodes


# ══════════════════════════════════════════════
#  PASS 4: PER-H2 CONTEXTUAL STRUCTURE
#  (V4.4 — 8 Thành phần Koray Lecture 21/39)
# ══════════════════════════════════════════════

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
        "② First Sentence Pattern: [Entity] + [Attribute verb] + [Value] + [Qualifier]\n"
        "③ Micro Context Terms BẮT BUỘC (≤5 terms chỉ dùng trong section này, không lan sang section khác)\n"
        "④ Sentence Before List/Table: 'Có X [items] [attribute] [entity], bao gồm:'\n"
        "⑤ Preceding Question (Inquisitive Semantics): câu hỏi tiếp theo sau khi trả lời\n"
        "⑥ Contextual Bridge: 2-3 từ bridge sang H2 tiếp theo\n"
        "⑦ Boolean H3 nếu phù hợp: '[Entity] có [attribute] không?'\n"
        "⑧ Tonality: predicates phù hợp (technical B2B: 'đạt', 'đáp ứng'; health: 'cải thiện', 'giảm')\n"
        "⑨ Word Count Target: số từ cần viết cho section này (VD: '200-300 từ' cho MAIN Definition, '300-400 từ' cho Technical, '100-150 từ' cho SUPP)\n"
        "⑩ Section Predicates: 3-5 động từ/vị ngữ đặc thù cho section (VD: H2 Độ bền → ['đạt','chịu','chống'], H2 Ứng dụng → ['sử dụng','áp dụng','phù hợp'])\n\n"

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
        return {}

    try:
        result = json.loads(raw)
        if isinstance(result, dict) and "per_h2" in result:
            logger.info("  [AGENT 4 V4] Generated per-H2 instructions for %d H2s.", len(result.get("per_h2", {})))
            return result
        return {}
    except (json.JSONDecodeError, Exception) as e:
        logger.warning("  [AGENT 4] Parse error: %s → empty.", str(e))
        return {}
