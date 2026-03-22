# -*- coding: utf-8 -*-
"""
content_brief_builder.py - Tổng hợp Content Brief từ kết quả phân tích.

Phase 9: Semantic Polish & Contextualization
- Heading Enrichment (LLM hoặc rule-based)
- Smart N-grams Injection (context-aware, có lọc stopwords)
- Dynamic E-E-A-T (niche-based inline instructions)
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  STOPWORDS & N-GRAM FILTER
# ══════════════════════════════════════════════

# Từ vô nghĩa cần loại bỏ khỏi danh sách N-grams
NGRAM_STOPWORDS = {
    "tuy nhiên", "ngoài ra", "bên cạnh", "trong đó", "chẳng hạn",
    "vì vậy", "do đó", "cũng như", "hơn nữa", "mặc dù",
    "thể sử dụng", "lại lợi ích", "độ ăn",  # fragments vô nghĩa
}


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


def detect_niche(keyword: str) -> str:
    """
    Phát hiện lĩnh vực (niche) từ keyword chính.

    Returns:
        Một trong: "food_health", "tech_gadget", "construction_material",
                   "finance_law", "general"
    """
    kw_lower = keyword.lower()
    scores = {}
    for niche, patterns in NICHE_KEYWORDS.items():
        score = sum(1 for p in patterns if p in kw_lower)
        scores[niche] = score

    best_niche = max(scores, key=scores.get)
    if scores[best_niche] == 0:
        return "general"
    return best_niche


# ══════════════════════════════════════════════
#  HEADING ENRICHMENT
# ══════════════════════════════════════════════

# ══════════════════════════════════════════════
#  POST-PROCESSORS (Rule-based, after Agent 1+2)
# ══════════════════════════════════════════════

# ── P7.2: BRAND KEYWORDS (ĐÃ XÓA TRONG V4) ──
# V4 sử dụng Agent 3a (Structure Validator) để suy luận MAIN/SUPP
# thay vì dùng list brand cố định. Hàm dưới đây giữ lại tên
# để không break exception fallback trong rewrite_headings_semantic.

def _postprocess_brand_h2_reorder(
    headings: List[Dict], intent: str, main_keyword: str
) -> List[Dict]:
    """
    (Deprecated) Phase 7 hardcoded logic.
    V4 uses Agent 3a (review_structure) for this.
    Returns headings unmodified.
    """
    return headings


def _postprocess_prominence_blacklist(
    headings: List[Dict], project=None, topic: str = ""
) -> List[Dict]:
    """
    Rule-based filter: Remove H2+child H3s containing irrelevant gap terms.
    Runs AFTER Agent 1+2 output, not prompt-dependent.
    """
    # Blacklisted gap terms — these almost never have search demand in B2B context
    UNIVERSAL_BLACKLIST = [
        "tác động môi trường", "tác động đến môi trường",
        "ảnh hưởng môi trường", "carbon footprint",
    ]

    B2B_BLACKLIST = UNIVERSAL_BLACKLIST + [
        "khí thải", "tái chế", "bền vững", "xây dựng bền vững",
        "phát triển bền vững", "biến đổi khí hậu",
        "lịch sử phát minh", "lịch sử phát triển",
        # V7: Thêm terms từ output evaluation
        "lợi ích môi trường", "lợi ích cho môi trường",
        "thân thiện môi trường", "giảm thiểu khí thải",
        "quy trình sản xuất", "quy trình chế tạo", "công nghệ sản xuất",
    ]

    # Determine which blacklist to use based on source context
    is_b2b = False
    if project:
        industry = str(getattr(project, "industry", "") or "").lower()
        usp = str(getattr(project, "usp", "") or "").lower()
        # V12: Mở rộng B2B signals cho đa ngành (dược, logistics, SaaS, công nghiệp...)
        b2b_signals = [
            "phân phối", "cung cấp", "b2b", "đại lý", "nhà máy", "sản xuất",
            "thi công", "logistics", "saas", "enterprise", "wholesale", "oem",
            "nhập khẩu", "xuất khẩu", "công nghiệp", "manufacturer", "distributor",
        ]
        is_b2b = any(s in industry for s in b2b_signals) or any(s in usp for s in b2b_signals)

    # V7+V12: B2B auto-detection fallback khi project=None — dùng topic keywords (đa ngành)
    if not is_b2b and not project and topic:
        b2b_topic_signals = [
            "thép", "sắt", "xi măng", "tôn", "xà gồ", "ống",
            "vật liệu", "bê tông", "gạch", "kính", "nhôm",
            # V12: thêm multi-niche B2B keywords
            "thiết bị y tế", "dược phẩm", "hóa chất", "máy móc",
            "phần mềm doanh nghiệp", "erp", "crm", "logistics",
            "nguyên liệu", "bao bì", "đóng gói",
        ]
        is_b2b = any(s in topic.lower() for s in b2b_topic_signals)

    blacklist = B2B_BLACKLIST if is_b2b else UNIVERSAL_BLACKLIST

    # Find H2 indices to remove
    indices_to_remove = set()
    for i, h in enumerate(headings):
        if h.get("level") == "H2":
            h_text_lower = h.get("text", "").lower()
            if any(term in h_text_lower for term in blacklist):
                indices_to_remove.add(i)
                # Also remove all child H3s under this H2
                for j in range(i + 1, len(headings)):
                    if headings[j].get("level") == "H2":
                        break  # Stop at next H2
                    indices_to_remove.add(j)

    if indices_to_remove:
        removed_texts = [headings[i]["text"] for i in indices_to_remove if headings[i].get("level") == "H2"]
        logger.info("  [PROMINENCE-FILTER] Removed %d H2+H3: %s", len(indices_to_remove), removed_texts)
        headings = [h for i, h in enumerate(headings) if i not in indices_to_remove]

    return headings


def _postprocess_supp_enforcer(
    headings: List[Dict], main_keyword: str, intent: str,
    paa_questions: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Ensure [SUPP] section exists (≥20% of H2).
    If missing: tag FAQ as [SUPP], tag last H2 as [SUPP], add Antonym Ending.
    Fix V6: Also creates FAQ H2 with PAA-derived H3s when no FAQ exists.
    """
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    if not h2_indices:
        return headings

    supp_count = sum(1 for i in h2_indices if "[SUPP]" in headings[i].get("text", ""))
    total_h2 = len(h2_indices)
    min_supp = max(1, int(total_h2 * 0.2))  # At least 20%, minimum 1

    if supp_count >= min_supp:
        return headings  # Already has enough SUPP

    # Also ensure ALL H2s without prefix get [MAIN]
    for i in h2_indices:
        text = headings[i]["text"]
        if not text.startswith("[MAIN]") and not text.startswith("[SUPP]"):
            headings[i]["text"] = f"[MAIN] {text}"

    # Tag existing FAQ H2 as [SUPP] and record its index
    faq_idx = -1
    for i in h2_indices:
        text = headings[i]["text"].lower()
        if "faq" in text or "câu hỏi" in text:
            headings[i]["text"] = headings[i]["text"].replace("[MAIN] ", "[SUPP] ")
            if not headings[i]["text"].startswith("[SUPP]"):
                headings[i]["text"] = "[SUPP] " + headings[i]["text"]
            faq_idx = i
            break

    # V7: Inject PAA H3s into existing FAQ, or create new FAQ if None exists
    if faq_idx == -1:
        entity = main_keyword.strip()
        faq_heading_text = f"[SUPP] FAQ về {entity}"
        headings.append({"level": "H2", "text": faq_heading_text})
        logger.info("  [SUPP-ENFORCER] Created FAQ section: %s", faq_heading_text)
        faq_idx = len(headings) - 1

    # Add PAA questions as H3 children (max 3) IF we have them AND
    # the FAQ section doesn't already have H3 children
    if paa_questions and faq_idx != -1:
        # Check if there are already H3s right after the FAQ H2
        has_h3s = False
        if faq_idx + 1 < len(headings) and headings[faq_idx + 1].get("level") == "H3":
            has_h3s = True
            
        if not has_h3s:
            # Insert PAA H3s right after the FAQ H2
            insert_pos = faq_idx + 1
            for q in reversed(paa_questions[:3]):  # Reverse to keep original order when inserting at same pos
                q_text = str(q).strip()
                if q_text:
                    headings.insert(insert_pos, {"level": "H3", "text": q_text})
            logger.info("  [SUPP-ENFORCER] Injected %d PAA H3s into FAQ", min(3, len(paa_questions)))

    # Re-calculate h2_indices after potential addition of FAQ H2/H3s
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    supp_count = sum(1 for i in h2_indices if "[SUPP]" in headings[i].get("text", ""))

    # Tag last H2 as [SUPP] if still need more
    if supp_count < min_supp and h2_indices:
        last_h2_idx = h2_indices[-1]
        text = headings[last_h2_idx]["text"]
        if "[MAIN]" in text:
            headings[last_h2_idx]["text"] = text.replace("[MAIN] ", "[SUPP] ")

    # Add Antonym Ending if missing
    has_antonym = False
    h2_indices = [i for i, h in enumerate(headings) if h.get("level") == "H2"]
    if h2_indices:
        last_text = headings[h2_indices[-1]]["text"].lower()
        antonym_signals = ["không nên", "khi nào không", "sai lầm", "tránh", "thay thế", "giống nhau", "không phù hợp"]
        has_antonym = any(s in last_text for s in antonym_signals)

    if not has_antonym:
        # Generate contextual antonym question
        entity = main_keyword.strip()
        intent_lower = intent.lower()
        if "vs" in intent_lower:
            # Extract 2 entities from keyword
            parts = [p.strip() for p in re.split(r'\bvà\b|\bvs\b|\bvới\b|\bso sánh\b', entity, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2:
                a = parts[0]
                b = parts[1]
                # Remove trailing question words from b
                for rem in ["khác nhau thế nào", "khác nhau", "thế nào", "như thế nào"]:
                    b = b.replace(rem, "").strip()
                antonym = f"[SUPP] Khi nào {a} và {b} có thể thay thế nhau?"
            else:
                antonym = f"[SUPP] Khi nào không nên sử dụng {entity}?"
        elif "informational" in intent_lower or "what-is" in intent_lower:
            antonym = f"[SUPP] {entity}: Những trường hợp không nên sử dụng"
        else:
            antonym = f"[SUPP] Những sai lầm phổ biến khi chọn {entity}"
        headings.append({"level": "H2", "text": antonym})
        logger.info("  [SUPP-ENFORCER] Added Antonym Ending: %s", antonym)

    logger.info("  [SUPP-ENFORCER] SUPP enforcement complete. H2 count: %d", len([h for h in headings if h.get("level") == "H2"]))
    return headings


def _merge_back_h3s(new_outline: List[Dict], old_outline: List[Dict], step_name: str = "") -> List[Dict]:
    """
    DEFENSE LAYER: Nếu LLM agent vô tình xóa H3, merge H3s từ outline cũ trở lại.
    
    Logic:
    1. Đếm H3 trong new vs old.
    2. Nếu new có ít H3 hơn old đáng kể (≥50% mất) → merge lại.
    3. Merge bằng cách ghép H3 từ old vào vị trí H2 tương ứng trong new.
    """
    old_h3 = sum(1 for h in old_outline if h.get("level") == "H3")
    new_h3 = sum(1 for h in new_outline if h.get("level") == "H3")
    
    logger.info("  [H3-DEFENSE %s] H3 count: before=%d, after=%d", step_name, old_h3, new_h3)
    
    # Nếu new đã có đủ H3, hoặc old cũng không có H3 → return nguyên
    if new_h3 >= old_h3 or old_h3 == 0:
        return new_outline
    
    # Nếu bị mất ≥50% H3 → merge lại
    if new_h3 < old_h3 * 0.5:
        logger.warning("  [H3-DEFENSE %s] Detected H3 drop (%d→%d). Merging back...", step_name, old_h3, new_h3)
        
        # Xây map: H2 text → [H3 children] từ old outline
        old_h2_children = {}
        current_h2_key = None
        for h in old_outline:
            if h.get("level") == "H2":
                key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                current_h2_key = key
                if key not in old_h2_children:
                    old_h2_children[key] = []
            elif h.get("level") == "H3" and current_h2_key:
                old_h2_children[current_h2_key].append(h)
        
        # Xây set các H2 trong new outline đã có H3
        new_h2_has_h3 = set()
        for i, h in enumerate(new_outline):
            if h.get("level") == "H2":
                if i + 1 < len(new_outline) and new_outline[i + 1].get("level") == "H3":
                    key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                    new_h2_has_h3.add(key)
        
        # Phase 1: Exact-match merge
        result = []
        for h in new_outline:
            result.append(h)
            if h.get("level") == "H2":
                key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                if key not in new_h2_has_h3 and key in old_h2_children:
                    for child_h3 in old_h2_children[key]:
                        result.append(child_h3)
                    new_h2_has_h3.add(key)
                    logger.info("  [H3-DEFENSE] Restored %d H3s under '%s'",
                                len(old_h2_children[key]), h["text"][:50])
        
        # Phase 2: Fuzzy-match (word overlap) cho các H2 đã bị Agent rewrite text
        restored_h3 = sum(1 for h in result if h.get("level") == "H3")
        if restored_h3 < old_h3 * 0.5:
            logger.info("  [H3-DEFENSE] Exact match insufficient (%d). Trying fuzzy match...", restored_h3)
            
            # Collect orphan H3s (chưa được ghép)
            matched_keys = set()
            for h in result:
                if h.get("level") == "H2":
                    matched_keys.add(h["text"].lower().replace("[main]", "").replace("[supp]", "").strip())
            
            orphan_h3s = []
            for key, children in old_h2_children.items():
                if key not in matched_keys:
                    orphan_h3s.extend(children)
            
            # Ghép orphan H3s vào các H2 chưa có H3 (word overlap matching)
            if orphan_h3s:
                result2 = []
                orphan_idx = 0
                for h in result:
                    result2.append(h)
                    if h.get("level") == "H2" and orphan_idx < len(orphan_h3s):
                        h_key = h["text"].lower().replace("[main]", "").replace("[supp]", "").strip()
                        # Skip nếu H2 đã có H3 hoặc là SUPP/FAQ
                        if h_key in new_h2_has_h3 or "[supp]" in h["text"].lower() or "faq" in h["text"].lower():
                            continue
                        # Fuzzy: tính word overlap
                        h2_words = set(h_key.split())
                        best_score = 0
                        best_idx = orphan_idx
                        for oi in range(orphan_idx, min(orphan_idx + 5, len(orphan_h3s))):
                            o_words = set(orphan_h3s[oi]["text"].lower().split())
                            score = len(h2_words & o_words)
                            if score > best_score:
                                best_score = score
                                best_idx = oi
                        # Chèn orphan H3 phù hợp nhất
                        result2.append(orphan_h3s[best_idx])
                        orphan_h3s.pop(best_idx)
                        new_h2_has_h3.add(h_key)
                result = result2
        
        final_h3 = sum(1 for h in result if h.get("level") == "H3")
        logger.info("  [H3-DEFENSE %s] Final H3 count after merge: %d (was %d)", step_name, final_h3, old_h3)
        return result
    
    return new_outline


def rewrite_headings_semantic(
    raw_headings: List[Dict],
    main_keyword: str,
    niche: str,
    intent: str,
    serp_data: Optional[Dict] = None,
    competitor_data: Optional[Dict] = None,
    methodology_prompt: str = "",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35
    eav_table: str = "", # Phase 35
    network_data: Optional[Dict] = None, # Phase 35
    context_data: Optional[Dict] = None, # Phase 35
) -> List[Dict]:
    """
    Phase 19: Xây dựng Outline Toàn Diện từ mọi mảng dữ liệu.
    
    LLM path: Tổng hợp PAA, Content Gaps, Ngrams vào dàn ý.
    Fallback: Rule-based enrichment (nối ngữ cảnh keyword + niche).
    """
    # Thử LLM path trước: Tổng hợp Outline Toàn Diện
    raw_enriched = _agent_synthesize_raw_outline(
        main_keyword, niche, serp_data, competitor_data, methodology_prompt,
        intent=intent, project=project,
        macro_context=macro_context, eav_table=eav_table, network_data=network_data, # Phase 35
    )
    if raw_enriched:
        # Snapshot trước khi Agent 2 rewrite (để merge-back H3 nếu bị drop)
        pre_agent2_outline = list(raw_enriched)
        pre_agent2_h3 = sum(1 for h in pre_agent2_outline if h.get("level") == "H3")
        logger.info("  [H3-TRACE] Pre-Agent2: %d H3s", pre_agent2_h3)
        
        # Agent 2: Enforce Semantic SEO rules
        seo_enriched = _agent_enforce_semantic_seo(
            raw_enriched, main_keyword, intent, project=project,
            context_data=context_data # Phase 35
        )
        enriched = seo_enriched if seo_enriched else raw_enriched
        
        # DEFENSE: Merge back H3s nếu Agent 2 đã drop chúng
        enriched = _merge_back_h3s(enriched, pre_agent2_outline, step_name="Agent2")

        # ═══════════════════════════════════════════════════════════
        #  SPEC V4: AGENT 3 — SEMANTIC REVIEWER (MULTI-PASS)
        #  Pass 3a: Structure + Heading Rewrite (Attribute Filtration)
        #  Pass 3b: H3 Depth (5 data sources + 6 rules)
        # ═══════════════════════════════════════════════════════════
        try:
            from modules.agent_reviewer import review_structure, review_h3_depth

            # Chuẩn bị data chung cho cả 2 pass
            paa_qs = serp_data.get("people_also_ask", []) if serp_data else []
            content_gaps = []
            keyword_clusters = []
            
            # Setup data sources for H3 enforcement fallback
            h3_data_sources = []
            h3_data_sources.extend([str(q) for q in paa_qs])
            
            if competitor_data:
                info_gain = competitor_data.get("information_gain", {})
                content_gaps = [str(g.get("heading", g) if isinstance(g, dict) else g) for g in info_gain.get("rare_headings", [])]
                h3_data_sources.extend(content_gaps)
                for ch in competitor_data.get("common_headings", []):
                    h3_data_sources.append(str(ch))

            if network_data and network_data.get("clusters"):
                for c in network_data["clusters"]:
                    keyword_clusters.extend(c.get("keywords", [])[:5])

            # ── PASS 3a: Structure + Heading Rewrite (V4.2) ──
            pre_agent3a_outline = list(enriched)  # Snapshot before Agent 3a
            enriched = review_structure(
                enriched, intent,
                macro_context=macro_context,
                main_keyword=main_keyword,
                eav_table=eav_table,
                keyword_clusters=keyword_clusters,
            )
            # DEFENSE: Merge back H3s nếu Agent 3a đã drop chúng
            enriched = _merge_back_h3s(enriched, pre_agent3a_outline, step_name="Agent3a")

            # ── PASS 3b: H3 Depth from 5 Data Sources (V4.1) ──
            enriched = review_h3_depth(
                enriched,
                content_gaps=content_gaps,
                paa_questions=[str(q) for q in paa_qs],
                keyword_clusters=keyword_clusters,
                main_keyword=main_keyword,
                eav_table=eav_table,
            )

            post_3b_h3 = sum(1 for h in enriched if h.get("level") == "H3")
            logger.info("  [SPEC V4] Agent 3a + 3b completed. H3 count after 3b: %d", post_3b_h3)

        except ImportError:
            logger.warning("  [SPEC V4] agent_reviewer.py not found → fallback to rule-based.")
            
            # Setup data sources for fallback (in case try block failed before preparing them)
            paa_qs = serp_data.get("people_also_ask", []) if serp_data else []
            h3_data_sources = []
            h3_data_sources.extend([str(q) for q in paa_qs])
            if competitor_data:
                info_gain = competitor_data.get("information_gain", {})
                h3_data_sources.extend([str(g.get("heading", g) if isinstance(g, dict) else g) for g in info_gain.get("rare_headings", [])])
                for ch in competitor_data.get("common_headings", []):
                    h3_data_sources.append(str(ch))
            
            enriched = _postprocess_brand_h2_reorder(enriched, intent, main_keyword)

        # ── H3 ENFORCEMENT (Luôn luôn chạy sau khi qua Agent) ──
        enriched = _enforce_h3_ratio(enriched, main_keyword, h3_data_sources)

        # ── Deterministic post-processors (luôn chạy) ──
        enriched = _postprocess_prominence_blacklist(enriched, project)
        paa_qs = serp_data.get("people_also_ask", []) if serp_data else []
        enriched = _postprocess_supp_enforcer(enriched, main_keyword, intent, paa_questions=paa_qs)

        # Giữ lại H1 ban đầu (vì LLM chỉ build H2/H3)
        h1 = [h for h in raw_headings if h["level"] == "H1"]
        if not h1:
            h1 = [{"level": "H1", "text": main_keyword.title()}]
            
        # LỌC BỎ BẤT KỲ H1 NÀO BỊ LLM TẠO THỪA TRONG enriched
        enriched = [h for h in enriched if str(h.get("level", "")).upper() != "H1"]
        return h1 + enriched

    # Fallback: Rule-based enrichment
    logger.info("  [HEADING] Rule-based enrichment (không có LLM hoặc JSON lỗi)")
    enriched = _rule_based_heading_enrichment(raw_headings, main_keyword, niche)

    # ── POST-PROCESSOR 1: PROMINENCE BLACKLIST ──
    enriched = _postprocess_prominence_blacklist(enriched, project)

    # ── POST-PROCESSOR 2: SUPP SECTION ENFORCER ──
    paa_qs = serp_data.get("people_also_ask", []) if serp_data else []
    enriched = _postprocess_supp_enforcer(enriched, main_keyword, intent, paa_questions=paa_qs)

    # ── POST-PROCESSOR 3: BRAND H2 REORDER (P7.2) ──
    enriched = _postprocess_brand_h2_reorder(enriched, intent, main_keyword)

    h1 = [h for h in raw_headings if h["level"] == "H1"]
    if not h1:
        h1 = [{"level": "H1", "text": main_keyword.title()}]
        
    enriched = [h for h in enriched if str(h.get("level", "")).upper() != "H1"]
    return h1 + enriched


def _get_min_h2_for_intent(intent: str) -> int:
    """Số H2 tối thiểu theo intent (V17: 4 loại chuẩn)."""
    intent_lower = intent.lower()
    # Backward compat: vs → commercial
    if "vs" in intent_lower or "comparison" in intent_lower:
        intent_lower = "commercial"
    minimums = {
        "commercial": 5,
        "informational": 4,
        "transactional": 3,
        "navigational": 2,
    }
    return minimums.get(intent_lower, 3)


def _get_min_h2_for_vs_symmetry(outline: list) -> bool:
    """
    VS intent: kiểm tra H2 có symmetric không.
    Symmetric = có ít nhất 1 H2 nói về Entity A riêng VÀ 1 H2 nói về Entity B riêng
    VÀ ít nhất 1 H2 so sánh trực tiếp cả 2.
    Return True nếu OK, False nếu cần retry.
    """
    h2_headings = [h["text"].lower() for h in outline if h.get("level") == "H2"]
    has_comparison_h2 = any(
        any(sig in h for sig in ["so sánh", "khác nhau", "vs", "compare", "khác biệt"])
        for h in h2_headings
    )
    return has_comparison_h2


def _agent_synthesize_raw_outline(
    topic: str,
    niche: str,
    serp_data: Optional[Dict],
    competitor_data: Optional[Dict],
    methodology_prompt: str,
    intent: str = "informational",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35
    eav_table: str = "", # Phase 35
    network_data: Optional[Dict] = None, # Phase 35
) -> Optional[List[Dict]]:
    """
    Agent 1: The Synthesizer.
    Tổng hợp dữ liệu PAA, Content Gaps, N-grams vào chung 1 cấu trúc logic tịnh tiến.
    Trả về cấu trúc chuẩn JSON list các dict: [{"level": "H2", "text": "..."}]
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return None

        import openai
        import json
        client = openai.OpenAI(api_key=api_key)

        # ── Chuẩn bị Dữ liệu đầu vào ──
        paa = []
        if serp_data:
            paa = serp_data.get("people_also_ask", [])[:5]

        gaps = []
        ngrams = []
        comp_headings = []
        if competitor_data:
            info_gain = competitor_data.get("information_gain", {})
            raw_gaps = info_gain.get("rare_headings", [])[:10]
            # V16-2: Prominence Gate Filter (Universal)
            # Lọc bỏ heading mang tính quy trình/vận hành (procedural/operational)
            # không phù hợp cho bài định nghĩa (informational/what-is).
            # LLM Agent 1 sẽ tự điều chỉnh theo ngành dựa trên Source Context.
            PROCEDURAL_PATTERNS = [
                'quy trình', 'hướng dẫn bảo trì', 'bảo dưỡng định kỳ',
                'kiểm định', 'kiểm tra chất lượng', 'cảnh báo an toàn',
                'hướng dẫn sử dụng', 'cách xử lý sự cố', 'lịch bảo dưỡng',
                'checklist', 'biên bản nghiệm thu', 'sổ tay vận hành',
            ]
            if 'là gì' in topic.lower() or intent == 'informational':
                gaps = [
                    g for g in raw_gaps
                    if not any(p in str(g).lower() for p in PROCEDURAL_PATTERNS)
                ]
            else:
                gaps = raw_gaps
            gaps = gaps[:7]
            ngrams_2 = competitor_data.get("ngrams_2", [])[:10]
            # Convert ngrams to string list
            ngrams = [f"{n[0]} (tần suất {n[1]})" if isinstance(n, tuple) else str(n) for n in ngrams_2]
            comp_headings = competitor_data.get("common_headings", [])[:10]

        # Phase 35: Xử lý Semantic Query Network string
        network_str = ""
        if network_data and network_data.get("clusters"):
            clusters = network_data.get("clusters", [])
            lines = []
            for c in clusters[:4]: # Chỉ lấy 4 clusters top
                lines.append(f"- Cluster '{c['name']}': {', '.join(c.get('keywords', [])[:3])}")
            network_str = "\n".join(lines)

        base_system_instruction = (
            "<role>\nBạn là Agent 1 (The Synthesizer) — Chuyên gia hàng đầu về Koray Semantic SEO Framework.\n"
            "Nhiệm vụ: Tổng hợp dữ liệu đối thủ (PAA, Gaps, Headings, N-grams) thành DÀN Ý (OUTLINE) hoàn chỉnh.\n</role>\n\n"

            "<rules>\n"
            "═══ 6 QUY TẮC CỐT LÕI BẮT BUỘC ═══\n"
            "1. CONTEXTUAL FLOW: Từ Định nghĩa → Thuộc tính → Ứng dụng → FAQ. "
            "H2 sau phải nối ngữ cảnh với H2 trước.\n"
            "2. CONTEXTUAL HIERARCHY (BẮT BUỘC): Mỗi H2 phải có ≥1 H3 con (children). "
            "H3 = thu hẹp/đào sâu 1 khía cạnh cụ thể của H2 cha. "
            "Tối thiểu 50% H2 [MAIN] phải có H3.\n"
            "3. ANTI-KEYWORD STUFFING: Tối đa 20% heading chứa keyword chính. "
            "Còn lại dùng từ đồng nghĩa, N-grams, đại từ.\n"
            "4. QUESTION-FIRST FORMAT: Ưu tiên tối đa việc chuyển đổi các Heading thành dạng CÂU HỎI (Tại sao, Cái nào tốt hơn, Sự khác biệt là gì...) thay vì dùng câu trần thuật danh từ khô khan.\n"
            "5. MAIN/SUPP SPLIT: Thêm prefix [MAIN] hoặc [SUPP]. "
            "SUPP = FAQ, tips, antonym ending (20-35% tổng H2).\n"
            "6. PROMINENCE GATE: Content Gaps chỉ đưa vào nếu có Prominence/Popularity.\n"
            "</rules>\n\n"
        )

        # V17: Per-intent outline rules (4 loại chuẩn)
        intent_lower = intent.lower() if intent else "informational"
        # Backward compat: "vs" → "commercial"
        if intent_lower == "vs":
            intent_lower = "commercial"

        if intent_lower == "informational":
            base_system_instruction += (
                "═══ QUY TẮC INFORMATIONAL INTENT ═══\n"
                "Người dùng đang tìm hiểu, nghiên cứu → Tối ưu blog, guide, FAQ.\n"
                "≥4 H2 bắt buộc. Contextual Flow chuẩn:\n"
                "  H2-1: [MAIN] Định nghĩa cốt lõi (Entity là gì?)\n"
                "  H2-2: [MAIN] Đặc điểm / Phân loại / Cấu tạo\n"
                "  H2-3: [MAIN] Ứng dụng / Cách sử dụng / Lợi ích-Tác hại\n"
                "  H2-4+: [MAIN/SUPP] Mở rộng ngữ cảnh (Thuộc tính, Tiêu chuẩn, Lịch sử...)\n"
                "  Cuối: [SUPP] FAQ — Câu hỏi thường gặp\n"
                "PHONG CÁCH: Giáo dục, giải thích, trung lập. Không bán hàng.\n\n"
            )
        elif intent_lower == "commercial":
            # V20: Check if this is a VS (comparison) commercial intent
            is_vs_intent = "vs" in intent.lower() or "so sánh" in topic.lower() or "và" in topic.lower()
            
            if is_vs_intent:
                base_system_instruction += (
                    "═══ QUY TẮC COMMERCIAL INTENT (SO SÁNH - VS) ═══\n"
                    "Người dùng đang PHÂN VÂN GIỮA 2 HOẶC CÁC LỰA CHỌN TRONG TỪ KHÓA.\n"
                    "≥5 H2 bắt buộc. Contextual Flow chuẩn:\n"
                    "  H2-1: [MAIN] So sánh tổng quan (Giới thiệu nhanh các đối tượng)\n"
                    "  H2-2: [MAIN] Điểm giống nhau / Các thông số chung\n"
                    "  H2-3: [MAIN] Phân tích điểm khác biệt cốt lõi (Bảng phân tích)\n"
                    "  H2-4: [MAIN] So sánh Tiêu chí 1 (VD: Độ bền, Giá, Hiệu năng...)\n"
                    "  H2-5: [MAIN] So sánh Tiêu chí 2\n"
                    "  H2-6: [MAIN] Kết luận: Nên chọn loại nào cho mục đích gì?\n"
                    "  Cuối: [SUPP] FAQ — Câu hỏi thường gặp\n"
                    "⚠️ STRICT RULE: TUYỆT ĐỐI CHỈ so sánh các Entity có sẵn trong từ khóa. KHÔNG ĐƯỢC tự bịa thêm các thương hiệu khác (như Hòa Phát, Hoa Sen...) hoặc sản phẩm thứ 3 không liên quan.\n"
                    "⚠️ STRICT RULE: PHẢI gắn tên 2 Entity cần so sánh vào hầu hết các Heading để tránh Heading chung chung (Generic).\n"
                    "PHONG CÁCH: Phân tích, khách quan, có bảng so sánh.\n\n"
                )
            else:
                base_system_instruction += (
                    "═══ QUY TẮC COMMERCIAL INTENT ═══\n"
                    "Người dùng đang CÂN NHẮC MUA → Tạo trang đánh giá, review, bảng giá.\n"
                    "≥5 H2 bắt buộc. Contextual Flow chuẩn:\n"
                    "  H2-1: [MAIN] Tổng quan / Giới thiệu (định nghĩa ngắn + bối cảnh thị trường)\n"
                    "  H2-2: [MAIN] Tiêu chí đánh giá / Yếu tố cần xem xét\n"
                    "  H2-3: [MAIN] Review chi tiết / Đánh giá ưu nhược điểm\n"
                    "  H2-4: [MAIN] Bảng giá / Chi phí / Đầu tư\n"
                    "  H2-5: [MAIN] Kết luận — Có đáng mua không?\n"
                    "  Cuối: [SUPP] FAQ — Câu hỏi khi mua\n"
                    "PHONG CÁCH: Phân tích, khách quan, review chi tiết.\n\n"
                )
        elif intent_lower == "transactional":
            base_system_instruction += (
                "═══ QUY TẮC TRANSACTIONAL INTENT ═══\n"
                "Người dùng SẴN SÀNG MUA / ĐẶT → Tối ưu landing page, CTA mạnh.\n"
                "≥3 H2 bắt buộc. Contextual Flow chuẩn:\n"
                "  H2-1: [MAIN] Sản phẩm/Dịch vụ — Giới thiệu + USP nổi bật\n"
                "  H2-2: [MAIN] Báo giá / Gói dịch vụ / Bảng giá chi tiết\n"
                "  H2-3: [MAIN] Quy trình đặt hàng / Liên hệ / CTA\n"
                "  (Optional) [SUPP] Cam kết / Chính sách / Testimonials\n"
                "PHONG CÁCH: Trực diện, CTA rõ ràng, tập trung chuyển đổi.\n\n"
            )
        elif intent_lower == "navigational":
            base_system_instruction += (
                "═══ QUY TẮC NAVIGATIONAL INTENT ═══\n"
                "Người dùng tìm THƯƠNG HIỆU CỤ THỂ → Tối ưu brand SEO, Google My Business.\n"
                "≥2 H2 bắt buộc. Contextual Flow chuẩn:\n"
                "  H2-1: [MAIN] Giới thiệu thương hiệu / Tổ chức\n"
                "  H2-2: [MAIN] Thông tin liên hệ / Chi nhánh / Văn phòng\n"
                "  (Optional) [SUPP] Sản phẩm/Dịch vụ nổi bật\n"
                "  (Optional) [SUPP] Đánh giá / Feedback khách hàng\n"
                "PHONG CÁCH: Ngắn gọn, chính xác, NAP info đầy đủ.\n\n"
            )
        else:
            base_system_instruction += (
                f"QUY TẮC INTENT '{intent}': ≥4 H2 (Định nghĩa, Phân loại, Ứng dụng, FAQ).\n\n"
            )

        base_system_instruction += (
            f"<methodology>\n{methodology_prompt[:200] if methodology_prompt else 'General'}\n</methodology>\n\n"

            "<examples>\n"
            "═══ OUTPUT FORMAT: NESTED JSON ARRAY ═══\n"
            "Dưới đây là CẤU TRÚC CHUẨN MỰC của JSON output. H2 luôn chứa H3 con qua trường 'children'.\n"
            "[\n"
            '  {"level":"H2","text":"[MAIN] Tại sao {entity} quan trọng trong xây dựng?","children":[\n'
            '    {"level":"H3","text":"Đặc điểm chính nổi bật của {entity}"},\n'
            '    {"level":"H3","text":"Sự khác biệt giữa {entity} với các dạng truyền thống"}\n'
            "  ]},\n"
            '  {"level":"H2","text":"[MAIN] Tiêu chuẩn đánh giá chất lượng phổ biến","children":[\n'
            '    {"level":"H3","text":"Định lượng vật lý lõi"}\n'
            "  ]},\n"
            '  {"level":"H2","text":"[SUPP] FAQ Câu hỏi thường gặp","children":[]}\n'
            "]\n"
            "</examples>\n\n"

            "<constraints>\n"
            "🚫 TUYỆT ĐỐI KHÔNG trả về markdown block code (như ```json ). CHỈ trả chuỗi JSON thuần.\n"
            "🚫 TUYỆT ĐỐI KHÔNG giải thích dài dòng, chỉ in ra mảng JSON.\n"
            "</constraints>\n"
        )

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        system_instruction = inject_semantic_prompt(base_system_instruction, agent_name="agent_1_outline")
        system_instruction = inject_source_context(system_instruction, project)  # Phase 33

        # Phase 35: Chained Context injection
        mc_block = f"📍 MACRO CONTEXT TRỌNG TÂM:\n{macro_context}\n\n" if macro_context else ""
        eav_block = f"📍 EAV TABLE (THỰC THỂ & THUỘC TÍNH BẮT BUỘC COVER):\n{eav_table}\n\n" if eav_table else ""
        net_block = f"📍 SEMANTIC QUERY NETWORK (CLUSTERS):\n{network_str}\n\n" if network_str else ""

        user_content = (
            f"Tạo Dàn Ý chuẩn SEO cho chủ đề: **'{topic}'**\n\n"
            f"--- BỐI CẢNH SEMANTIC SEO YÊU CẦU ---\n"
            f"{mc_block}{eav_block}{net_block}"
            f"------------------------------------\n\n"
            f"DỮ LIỆU ĐẦU VÀO TỪ ĐỐI THỦ:\n"
            f"1. PAA Questions (Câu hỏi người dùng hay hỏi):\n- " + "\n- ".join([str(q) for q in paa]) + "\n\n"
            "2. Content Gaps (Khoảng trống đối thủ — CHỈ ĐƯA VÀO NẾU QUA PROMINENCE GATE, xem quy tắc trên):\n- " + "\n- ".join([str(g) for g in gaps]) + "\n\n"
            "3. Common Headings (Heading chung đối thủ dùng):\n- " + "\n- ".join([str(h) for h in comp_headings]) + "\n\n"
            "4. N-grams LSI (Chèn vào heading):\n- " + "\n- ".join([str(n) for n in ngrams]) + "\n"
        )

        logger.info("  [HEADING SYNTHESIS] Gọi LLM để tổng hợp Outline Toàn Diện...")
        
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            temperature=0.4,
            max_tokens=2000,
            timeout=60,
        )

        # ── Parse Output ──
        raw_text = response.choices[0].message.content.strip()
        # Clean JSON markdown blocks if any
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        outline_data = json.loads(raw_text)
        
        # V8.1: Parse both nested (children) and flat format
        validated_outline = []
        for item in outline_data:
            if isinstance(item, dict) and "level" in item and "text" in item:
                lvl = str(item["level"]).upper()
                if lvl in ["H2", "H3", "H4"]:
                    validated_outline.append({"level": lvl, "text": item["text"]})
                # V8.1: Flatten nested children into flat list
                children = item.get("children", [])
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, dict) and "text" in child:
                            child_lvl = str(child.get("level", "H3")).upper()
                            if child_lvl in ["H3", "H4"]:
                                validated_outline.append({"level": child_lvl, "text": child["text"]})
        
        logger.info("  [AGENT 1] Parsed %d headings (H2: %d, H3: %d)",
                     len(validated_outline),
                     sum(1 for h in validated_outline if h["level"] == "H2"),
                     sum(1 for h in validated_outline if h["level"] == "H3"))

        if validated_outline:
            # ── H2 MINIMUM ENFORCEMENT & SYMMETRY CHECK ──
            h2_count = sum(1 for h in validated_outline if h["level"] == "H2")
            min_required = _get_min_h2_for_intent(intent)

            retry_needed = False
            retry_reason = ""

            if h2_count < min_required:
                retry_needed = True
                retry_reason = f"Chỉ có {h2_count} H2, cần tối thiểu {min_required} cho intent '{intent}'."

            if "vs" in intent.lower() and not _get_min_h2_for_vs_symmetry(validated_outline):
                retry_needed = True
                retry_reason += " VS intent thiếu H2 so sánh trực tiếp giữa 2 entity."

            h3_count = sum(1 for h in validated_outline if h["level"] == "H3")
            if h2_count > 0 and (h3_count / h2_count) < 0.5:
                retry_needed = True
                retry_reason += f" Có {h2_count} H2 nhưng chỉ có {h3_count} H3 (Tỷ lệ < 50%)."

            if retry_needed:
                logger.warning(
                    "  [AGENT 1] Validation failed: %s. Retry...",
                    retry_reason
                )
                # Retry 1 lần với explicit penalty warning
                retry_user_content = user_content + (
                    f"\n\n⚠️ CẢNH BÁO: Outline vừa tạo bị từ chối. Lý do: {retry_reason}\n\n"
                    f"YÊU CẦU BẮT BUỘC cho lần này:\n"
                    f"- Tối thiểu {min_required} H2 headings (MAIN content)\n"
                    f"- Mỗi H2 phải cover 1 attribute/aspect riêng biệt\n"
                    f"- BẮT BUỘC: Xây dựng Contextual Hierarchy sâu bằng cách chêm thêm các node H3 mở rộng bên trong cấu trúc H2 lớn.\n"
                    f"- Với 'vs' intent: PHẢI có H2 định nghĩa Entity A, H2 định nghĩa Entity B, "
                    f"VÀ ít nhất 1 H2 so sánh trực tiếp (cả 2 entity trong cùng heading)\n"
                    f"- KHÔNG dùng H2 chỉ nói về 1 entity trong bài 'vs' (ví dụ: chỉ nói về 'quy trình sản xuất thép cuộn' mà không so sánh với thép tấm)"
                )
                try:
                    retry_response = client.chat.completions.create(
                        model=LLM_CONFIG.get("model", "gpt-4o-mini"),
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": retry_user_content}
                        ],
                        temperature=0.4,
                        max_tokens=2000,
                        timeout=60,
                    )
                    retry_raw = retry_response.choices[0].message.content.strip()
                    if retry_raw.startswith("```json"):
                        retry_raw = retry_raw[7:]
                    if retry_raw.startswith("```"):
                        retry_raw = retry_raw[3:]
                    if retry_raw.endswith("```"):
                        retry_raw = retry_raw[:-3]
                    retry_raw = retry_raw.strip()
                    retry_data = json.loads(retry_raw)
                    # V8.1: Parse nested + flat format
                    retry_outline = []
                    for item in retry_data:
                        if isinstance(item, dict) and "level" in item and "text" in item:
                            lvl = str(item["level"]).upper()
                            if lvl in ["H2", "H3", "H4"]:
                                retry_outline.append({"level": lvl, "text": item["text"]})
                            for child in item.get("children", []):
                                if isinstance(child, dict) and "text" in child:
                                    child_lvl = str(child.get("level", "H3")).upper()
                                    if child_lvl in ["H3", "H4"]:
                                        retry_outline.append({"level": child_lvl, "text": child["text"]})
                    retry_h2 = sum(1 for h in retry_outline if h["level"] == "H2")
                    if retry_h2 >= min_required:
                        logger.info("  [AGENT 1] Retry thành công: %d H2 (cần %d)", retry_h2, min_required)
                        validated_outline = retry_outline
                    else:
                        logger.warning("  [AGENT 1] Retry vẫn chỉ có %d H2. Dùng outline gốc.", retry_h2)
                except Exception as retry_err:
                    logger.warning("  [AGENT 1] Retry lỗi: %s. Dùng outline gốc.", str(retry_err))

            # ── PROGRAMMATIC H3 ENFORCER (FAIL-SAFE) ──
            h3_src = [str(g.get("heading", g) if isinstance(g, dict) else g) for g in gaps]
            h3_src += [str(h) for h in comp_headings]
            h3_src += [str(q) for q in paa]
            
            if eav_table:
                for line in eav_table.split("\n"):
                    if line.strip().startswith("|") and "---" not in line and "Entity" not in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if len(parts) >= 2:
                            attr_name = parts[1]
                            if len(attr_name) > 3:
                                # FIX 1: Clean intent modifiers from topic before inserting
                                topic_entity = topic.replace("là gì", "").replace("tổng quan về", "").strip()
                                h3_src.append(f"{attr_name} của {topic_entity} như thế nào?")
                                
            validated_outline = _enforce_h3_ratio(validated_outline, topic, h3_src)

            logger.info("  [HEADING SYNTHESIS] Cấu trúc thành công %d headings!", len(validated_outline))
            return validated_outline
        else:
            logger.warning("  [HEADING SYNTHESIS] JSON không hợp lệ. Fallback.")
            return None

    except Exception as e:
        logger.warning("  [AGENT 1] Lỗi API: %s → Fallback...", str(e))
        return None



def _agent_enforce_semantic_seo(
    headings: List[Dict],
    entity: str,
    intent: str,
    project=None,  # Phase 33: Source Context
    context_data: Optional[Dict] = None, # Phase 35: Chained Context
) -> Optional[List[Dict]]:
    """
    Agent 2: The Semantic SEO Enforcer.
    Chỉ nhận vào 1 mảng JSON outline và làm 1 việc DUY NHẤT:
    Viết lại (Rewrite) tên Heading sao cho đúng chuẩn Semantic.
    Tuyệt đối không thay đổi luồng ý hay logic của outline gốc.
    """
    try:
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return None

        import openai
        import json
        client = openai.OpenAI(api_key=api_key)

        # Phase 35: Xử lý Context Vectors string
        vectors_str = ""
        if context_data and context_data.get("vectors"):
            vectors = context_data.get("vectors", [])
            lines = []
            for v in vectors[:3]: # Lấy 3 vectors chính
                lines.append(f"- Context Vector [{v.get('type', '')}]: {v.get('direction', '')}")
            vectors_str = "\n".join(lines)

        # V8.1: Đếm H3 input để enforce trong prompt
        input_h3_count = sum(1 for h in headings if h.get("level") == "H3")
        input_h2_count = sum(1 for h in headings if h.get("level") == "H2")
        
        base_system_instruction = (
            "<role>\nBạn là Agent 2 (Semantic SEO Enforcer) — Đại diện Koray Framework.\n"
            "Nhiệm vụ DUY NHẤT: Đọc dàn ý thô và Rewrite lại ngôn từ cho từng H2/H3 đạt chuẩn Semantic Mức Cao Nhất.\n</role>\n\n"

            "<rules>\n"
            "═══ 5 QUY TẮC REWRITE ═══\n"
            "1. LINGUISTIC VARIATION: Tối đa 20% heading chứa keyword chính. "
            "Còn lại dùng từ đồng nghĩa, N-grams, đại từ thay thế.\n"
            "2. QUESTION-FIRST FORMAT: Ưu tiên tối đa việc chuyển đổi các Heading thành dạng CÂU HỎI (Tại sao, Cái nào tốt hơn, Sự khác biệt là gì...) thay vì dùng câu trần thuật danh từ khô khan.\n"
            "3. NO GENERIC: Cấm dùng 'Tổng quan', 'Kết luận' đứng một mình. Phải gắn với Entity và cụ thể hóa giá trị.\n"
            "4. HEADING HARMONY: Các H2 cùng level phải có cấu trúc ngữ pháp tương đồng.\n"
            "5. NO TEMPLATE H3: Các H3 phải mang ý nghĩa CỤ THỂ đào sâu vào H2 (VD: phân loại, thông số). CẤM tạo các H3 chứa câu lặp từ khóa vô nghĩa.\n"
            "</rules>\n\n"
        )
        
        if vectors_str:
            base_system_instruction += (
                "<semantic_vectors>\n"
                f"{vectors_str}\n"
                "</semantic_vectors>\n\n"
            )

        base_system_instruction += (
            "<examples>\n"
            "═══ FEW-SHOT EXAMPLES TƯ DUY REWRITE ═══\n"
            "Input Tồi: {\"level\":\"H2\", \"text\": \"Tổng quan về sản phẩm\"}\n"
            "Output Chuẩn: {\"level\":\"H2\", \"text\": \"[MAIN] Các đặc điểm tổng quan nổi bật nhất của thép thanh vằn là gì?\"}\n\n"
            
            "Input Tồi: {\"level\":\"H3\", \"text\": \"Định lượng thép\"}\n"
            "Output Chuẩn: {\"level\":\"H3\", \"text\": \"Công thức định lượng vật lý của kết cấu thép\"}\n"
            "</examples>\n\n"
            
            "<constraints>\n"
            "🚫 TUYỆT ĐỐI KHÔNG thêm, xóa hay gộp bất kỳ heading nào.\n"
            f"🚫 BẮT BUỘC trả về ĐÚNG {input_h2_count} H2 và ≥{input_h3_count} H3 như Dàn ý gốc truyền vào.\n"
            "🚫 TUYỆT ĐỐI KHÔNG tạo H3 lặp từ vô nghĩa: (Ví dụ cấm: 'Thép có thép không?').\n"
            "🚫 CHỈ trả về đoạn JSON array thuần ([...]), tuyệt đối KHÔNG chặn markdown block ```json hay trình bày văn bản thừa thãi.\n"
            "</constraints>"
        )

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        system_instruction = inject_semantic_prompt(base_system_instruction, agent_name="agent_2_semantic")
        system_instruction = inject_source_context(system_instruction, project)  # Phase 33

        user_content = (
            f"<bối_cảnh>\n"
            f"Thực thể chính (Central Entity): **{entity}**\n"
            f"Search Intent: **{intent}**\n"
            f"</bối_cảnh>\n\n"
            "Hãy Rewrite lại toàn bộ mảng JSON Heading gốc dưới đây sao cho Đạt Chuẩn Semantic SEO 100% VÀ GẮN CHẶT VỚI SEARCH INTENT:\n\n"
            f"{json.dumps(headings, ensure_ascii=False, indent=2)}\n"
        )

        logger.info("  [AGENT 2] Gọi LLM Semantic Enforcer để SEO-ify Outline...")
        
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            temperature=0.3,
            max_tokens=2500,
            timeout=60,
        )

        # ── Parse Output ──
        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        if raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

        outline_data = json.loads(raw_text)
        
        validated_outline = []
        for item in outline_data:
            if isinstance(item, dict) and "level" in item and "text" in item:
                lvl = str(item["level"]).upper()
                if lvl in ["H2", "H3", "H4"]:
                    validated_outline.append({"level": lvl, "text": item["text"]})

        if validated_outline:
            logger.info("  [AGENT 2] Semantic Enforcer đã rewrite thành công %d headings!", len(validated_outline))
            return validated_outline
        else:
            return None

    except Exception as e:
        logger.warning("  [AGENT 2] Lỗi API: %s", str(e))
        return None


# ── P1.3 FIX: Navigation heading blacklist ──
# Các heading này là navigation elements bị scrape nhầm từ competitor sites,
# KHÔNG phải content heading. Phải lọc bỏ.
NAVIGATION_HEADING_BLACKLIST = [
    "liên kết nhanh", "liên hệ", "chi nhánh", "đăng ký", "đăng nhập",
    "hỗ trợ trực tuyến", "hỗ trợ khách hàng", "hotline", "bản đồ",
    "về chúng tôi", "thông tin liên hệ", "danh mục", "danh mục sản phẩm",
    "tải xuống", "sản phẩm liên quan", "tin tức", "tin tức nổi bật",
    "tin tức & sự kiện", "hình ảnh công ty", "bài viết cùng chủ đề",
    "quick link", "phòng kinh doanh", "trụ sở chính", "đăng ký nhận",
    "bình luận", "để lại một bình luận", "mạ kẽm nhúng nóng",
    "phụ kiện thép", "tôn lợp", "tôn mát", "từ khóa",
    "các sự kiện liên quan", "các bài viết liên quan", "danh mục tin tức",
    "đăng ký nhận tin", "mô tả",
]


def _is_navigation_heading(text: str) -> bool:
    """Kiểm tra xem heading có phải navigation element không."""
    text_lower = text.lower().strip()
    # Exact match hoặc bắt đầu bằng blacklisted term
    for term in NAVIGATION_HEADING_BLACKLIST:
        if text_lower == term or text_lower.startswith(term):
            return True
    return False


def _enforce_h3_ratio(outline: List[Dict], main_keyword: str, h3_sources: List[str] = None) -> List[Dict]:
    """
    Đảm bảo chắc chắn dàn ý có tỷ lệ H3/H2 >= 50% (Koray Framework).
    Nếu thiếu, sẽ tự động chèn H3 bằng dữ liệu thực, sau đó dùng template ngữ cảnh.
    
    V8 FIX: 
    - Giảm ngưỡng lọc source từ 10→5 ký tự  
    - Thêm contextual question templates khi hết data thực
    - KHÔNG BAO GIỜ break sớm — luôn đạt ≥50%
    """
    if h3_sources is None:
        h3_sources = []
        
    h2_indices = [i for i, h in enumerate(outline) if h.get("level") == "H2"]
    h3_count = sum(1 for h in outline if h.get("level") == "H3")
    
    if not h2_indices:
        return outline
        
    ratio = float(h3_count) / len(h2_indices)
    if ratio >= 0.5:
        logger.info("  [ENFORCER] H3 ratio OK: %.0f%% (%d H3 / %d H2)", ratio * 100, h3_count, len(h2_indices))
        return outline
        
    logger.warning("  [ENFORCER] Dàn ý thiếu H3 (có %d H3 / %d H2 = %.0f%%). Tự động bổ sung...",
                    h3_count, len(h2_indices), ratio * 100)
    target_h3 = len(h2_indices) // 2 + (1 if len(h2_indices) % 2 != 0 else 0)
    h3_needed = target_h3 - h3_count
    
    # Tìm các H2 [MAIN] chưa có H3 ngay bên dưới
    h2_without_h3 = []
    for idx in h2_indices:
        if idx + 1 == len(outline) or outline[idx + 1].get("level") != "H3":
            text_lower = outline[idx]["text"].lower()
            if "[supp]" not in text_lower and "faq" not in text_lower:
                h2_without_h3.append(idx)
                
    # P7.1: ƯU TIÊN dùng dữ liệu thực từ Content Gaps, PAA, N-grams
    # V8: Giảm ngưỡng từ 10→5 ký tự để giữ được nhiều source hơn
    sources_to_use = []
    for s in (h3_sources or []):
        s_clean = str(s).strip()
        if len(s_clean) < 5:
            continue
        if s_clean.lower().startswith("h1") or s_clean.lower().startswith("h2"):
            continue
        # Lọc navigation junk
        if any(nav in s_clean.lower() for nav in NAVIGATION_HEADING_BLACKLIST):
            continue
        sources_to_use.append(s_clean)
    
    logger.info("  [ENFORCER] Available sources: %d (need %d H3s for %d H2s without H3)",
                len(sources_to_use), h3_needed, len(h2_without_h3))
    
    inserted = 0
    offset = 0
    for idx in h2_without_h3:
        if inserted >= h3_needed:
            break
        
        h2_text = outline[idx + offset]["text"]
        h2_text_clean = h2_text.lower().replace("[main]", "").replace("[supp]", "").strip()
            
        h3_text = None
        if sources_to_use:
            # Chọn H3 source PHÙ HỢP NHẤT với H2 cha (word overlap)
            best_match_idx = None
            best_score = 0
            for si, src in enumerate(sources_to_use):
                src_words = set(src.lower().split())
                h2_words = set(h2_text_clean.split())
                overlap = len(src_words & h2_words)
                if overlap > best_score:
                    best_score = overlap
                    best_match_idx = si
            
            # FIX 2: If best_score == 0, trigger boolean fallback instead of random pick
            if best_score > 0 and best_match_idx is not None:
                pick_idx = best_match_idx
                h3_text = sources_to_use.pop(pick_idx)
                
                # Chuẩn hóa
                h3_text = h3_text.replace("H3:", "").replace("h3:", "").strip("- *:#")
                if h3_text:
                    h3_text = h3_text[0].upper() + h3_text[1:]
                    # V11-R2: Chỉ thêm suffix nếu KHÔNG phải câu hỏi VÀ quá ngắn (1 word)
                    if "?" not in h3_text and len(h3_text.split()) <= 1:
                        if not h3_text.isupper():
                            h3_text = f"{h3_text} — điều gì cần lưu ý?"
                else:
                    h3_text = None

        if not h3_text:
            # V9 FALLBACK: Sinh H3 từ logic semantic (Boolean / Query dạng ngắn) thay vì template chung chung
            h2_core = h2_text_clean
            for stop in ["là gì", "như thế nào", "ra sao", "bao nhiêu", "tổng quan", "chi tiết"]:
                h2_core = h2_core.replace(stop, "").strip()
            
            if len(h2_core.split()) >= 2:
                # FIX 3: Clean main_keyword to avoid tautology with full keyword
                entity = main_keyword.replace("là gì", "").replace("tổng quan", "").strip().title()
                
                # V19: Strict semantic overlap check to prevent tautological H3s (e.g., A có A không?)
                h2_words = set(h2_core.lower().strip().split())
                entity_words = set(entity.lower().strip().split())
                overlap = len(h2_words & entity_words) / max(len(entity_words), 1)
                
                if overlap < 0.6 and h2_core.lower().strip() != entity.lower().strip():
                    h3_text = f"Thông số kỹ thuật và phân loại của {h2_core}?" if inserted % 2 == 0 else f"Đặc điểm đáng lưu ý của {h2_core} là gì?"
                else:
                    # Tautology detected: H2 trùng topic → dùng câu hỏi chung phù hợp mọi ngành
                    h3_text = f"Các yếu tố cốt lõi nhất của {entity} gồm những gì?"
            else:
                # Nếu H2 quá ngắn
                h3_text = f"Yếu tố nào ảnh hưởng trực tiếp đến {h2_text_clean}?"
                
            logger.info("  [ENFORCER] Generated Logical H3 for '%s': '%s'", h2_text[:40], h3_text)
                    
        # V12: Sanitize H3 — strip ?? artifacts and ensure no broken question marks
        if h3_text:
            h3_text = h3_text.replace("??", "?").rstrip("?") + "?" if "?" in h3_text else h3_text
            # Strip if H3 is already a natural question — don't double-append suffix
            natural_q_signals = ["là gì", "như thế nào", "khi nào", "tại sao", "bao nhiêu", "có nên", "ở đâu"]
            is_natural_q = any(sig in h3_text.lower() for sig in natural_q_signals) or h3_text.endswith("?")
            if is_natural_q and "điều gì cần lưu ý" in h3_text:
                h3_text = h3_text.replace(" — điều gì cần lưu ý?", "?").replace("? — điều gì cần lưu ý", "")
                
        outline.insert(idx + offset + 1, {"level": "H3", "text": h3_text})
        offset += 1
        inserted += 1
            
    final_h3 = sum(1 for h in outline if h.get("level") == "H3")
    final_h2 = sum(1 for h in outline if h.get("level") == "H2")
    logger.info("  [ENFORCER] Done: Inserted %d H3s. Final ratio: %d H3 / %d H2 = %.0f%%",
                inserted, final_h3, final_h2, (final_h3 / final_h2 * 100) if final_h2 else 0)
    return outline


def _rule_based_heading_enrichment(
    raw_headings: List[Dict],
    main_keyword: str,
    niche: str,
) -> List[Dict]:
    """
    Enrichment rule-based: giữ heading nguyên gốc, chỉ lọc navigation junk.

    P1.2 FIX: KHÔNG thêm suffix "— Lợi ích" vào heading nữa.
    P1.3 FIX: Lọc bỏ navigation headings bị scrape nhầm.
    """
    result = []
    for h in raw_headings:
        if h["level"] == "H1":
            result.append(h)
            continue

        # P1.3: Lọc bỏ navigation headings
        if _is_navigation_heading(h["text"]):
            logger.info("  [HEADING] Lọc bỏ navigation heading: '%s'", h["text"])
            continue

        # Giữ nguyên heading — KHÔNG thêm suffix
        result.append(h)

    # Enforce H3 ratio cho Fallback path
    result = _enforce_h3_ratio(result, main_keyword)
    return result


# ══════════════════════════════════════════════
#  SMART N-GRAM CLASSIFICATION
# ══════════════════════════════════════════════

def _classify_ngrams(
    ngrams_2: list,
    ngrams_3: list,
) -> Dict[str, List[str]]:
    """
    Phân loại N-grams thành entity (danh từ) và action (hành động).

    Lọc bỏ stopwords và fragments vô nghĩa.

    Returns:
        {"entity": [...], "action": [...], "all_clean": [...]}
    """
    # Danh sách action keywords (động từ, hành động)
    action_verbs = {
        "bổ sung", "chế biến", "nấu", "sử dụng", "lựa chọn",
        "kết hợp", "giảm", "tăng", "cải thiện", "phòng ngừa",
        "điều trị", "bảo quản", "chọn mua", "so sánh", "đánh giá",
        "hướng dẫn", "cách", "làm", "tạo", "xây dựng",
    }

    entity_ngrams = []
    action_ngrams = []
    all_clean = []

    import re
    # Pattern để bắt các cụm rác:
    # 1. Quá nhiều số đo/đơn vị lặp lại (mm mm mm)
    # 2. Bắt đầu/kết thúc bằng từ nối vô nghĩa
    # 3. Ký tự đặc biệt hoặc số đứng một mình
    garbage_pattern = re.compile(r'(\b(mm|cm|m|kg|g)\b\s*){3,}')
    
    # ── V4: extended_stopwords ĐÃ BỊ XÓA ──
    # Việc lọc ngữ nghĩa bây giờ do Agent 3c (review_ngram_quality) đảm nhiệm.

    for ngram_list in [ngrams_2 or [], ngrams_3 or []]:
        for ng, count in ngram_list:
            ng_clean = ng.strip().lower()

            # Lọc bỏ stopwords và fragments cơ bản
            if ng_clean in NGRAM_STOPWORDS:
                continue
            if len(ng_clean) < 4:
                continue
            
            # Lọc rác Regex
            if garbage_pattern.search(ng_clean):
                continue
                
            # Lọc fragments bị cắt dở (ví dụ "chất chống oxy" thay vì "chất chống oxy hóa")
            if ng_clean.endswith(" oxy") or ng_clean.endswith(" có") or ng_clean.endswith(" và") or ng_clean.endswith(" là") or ng_clean.startswith("và ") or ng_clean.startswith("là "):
                continue

            # Lọc ký tự trắng thừa
            ng_clean = re.sub(r'\s+', ' ', ng_clean).strip()

            all_clean.append(ng_clean)

            # Phân loại
            is_action = any(verb in ng_clean for verb in action_verbs)
            if is_action:
                action_ngrams.append(ng_clean)
            else:
                entity_ngrams.append(ng_clean)

    return {
        "entity": entity_ngrams,
        "action": action_ngrams,
        "all_clean": all_clean,
    }


def _smart_pick_ngrams(
    classified: Dict[str, List[str]],
    section_type: str,
    count: int = 4,
) -> str:
    """
    Chọn N-grams theo ngữ cảnh section (không random bừa).

    section_type: "intro", "main", "faq", "conclusion"
    """
    if not classified.get("all_clean"):
        return ""

    pool = []
    if section_type == "intro":
        # Mở bài: entity n-grams (danh từ chính)
        pool = classified.get("entity", [])[:count]
    elif section_type == "main":
        # Main content: mix entity + action, ưu tiên entity
        entities = classified.get("entity", [])
        actions = classified.get("action", [])
        pool = entities[:3] + actions[:2]
    elif section_type == "faq":
        # FAQ: action n-grams (how-to, process)
        pool = classified.get("action", []) or classified.get("entity", [])[:count]
    elif section_type == "conclusion":
        # Kết bài: entity tổng quát
        pool = classified.get("entity", [])[-count:]

    # Fallback nếu pool trống
    if not pool:
        pool = classified["all_clean"][:count]

    # Loại bỏ trùng lặp, giới hạn count
    pool = list(dict.fromkeys(pool))[:count]

    if not pool:
        return ""

    return (
        "\n  **→ Bắt buộc sử dụng các từ khóa ngữ nghĩa sau:** "
        + ", ".join(f'"{s}"' for s in pool)
        + "."
    )


# ══════════════════════════════════════════════
#  DYNAMIC E-E-A-T (Niche-based)
# ══════════════════════════════════════════════

NICHE_EEAT = {
    "food_nutrition": {
        "experience": (
            "Chia sẻ trải nghiệm thực tế khi sử dụng/chế biến. "
            "Mô tả hương vị, kết cấu, và cách nấu cụ thể."
        ),
        "expertise": (
            "Bắt buộc cung cấp hàm lượng dinh dưỡng/100g (chất lượng chính, khoáng chất, vitamin). "
            "Trích dẫn nghiên cứu hoặc khuyến cáo từ chuyên gia dinh dưỡng."
        ),
        "authority": (
            "Liên kết đến nguồn uy tín (WHO, Bộ Y tế, tạp chí khoa học). "
            "Cảnh báo dị ứng hoặc tương tác thuốc nếu có."
        ),
        "trust": (
            "Ghi rõ nguồn dữ liệu dinh dưỡng. Cập nhật theo khuyến cáo mới nhất. "
            "Thêm thông tin tác giả có chuyên môn."
        ),
        "inline_per_h2": (
            "📊 GHI RÕ: Thành phần dinh dưỡng/100g. "
            "🍳 CHIA SẺ: Cách chế biến hoặc kết hợp thực tế. "
            "⚠️ LƯU Ý: Cảnh báo tác dụng phụ hoặc dị ứng nếu có."
        ),
    },
    "tech_gadget": {
        "experience": (
            "Mô tả trải nghiệm cầm nắm, sử dụng thực tế. "
            "Chia sẻ ảnh/video hands-on nếu có."
        ),
        "expertise": (
            "Cung cấp thông số kỹ thuật chi tiết (benchmark, specs). "
            "So sánh với đối thủ cùng phân khúc."
        ),
        "authority": (
            "Trích dẫn review từ nguồn uy tín (Tom's Hardware, GSMArena). "
            "Link đến trang chính hãng."
        ),
        "trust": (
            "Ghi rõ thời điểm test, phiên bản firmware. Minh bạch về mẫu review."
        ),
        "inline_per_h2": (
            "📐 THÔNG SỐ: Specs chính (RAM, CPU, pin, camera). "
            "🆚 SO SÁNH: Với sản phẩm cùng tầm giá. "
            "⭐ ĐÁNH GIÁ: Ưu/nhược điểm thực tế."
        ),
    },
    "construction_material": {
        "experience": (
            "Chia sẻ kinh nghiệm thi công, lắp đặt thực tế. "
            "Mô tả quy trình và lưu ý an toàn."
        ),
        "expertise": (
            "Trích dẫn tiêu chuẩn kỹ thuật hiện hành của ngành. "
            "Đưa thông số: cường độ, kích thước, trọng lượng."
        ),
        "authority": (
            "Liên kết đến tiêu chuẩn quốc gia, ban ngành uy tín, nhà sản xuất chính hãng."
        ),
        "trust": (
            "Cập nhật bảng giá mới nhất. Ghi rõ nguồn báo giá."
        ),
        "inline_per_h2": (
            "📏 THÔNG SỐ: Kích thước, trọng lượng, cường độ. "
            "🔧 THI CÔNG: Hướng dẫn lắp đặt thực tế. "
            "💰 GIÁ: Tham khảo giá thị trường."
        ),
    },
    "finance_law": {
        "experience": (
            "Chia sẻ case study thực tế. "
            "Mô tả quy trình đã thực hiện."
        ),
        "expertise": (
            "Trích dẫn luật, nghị định, thông tư cụ thể. "
            "Đưa số liệu tài chính có nguồn."
        ),
        "authority": (
            "Liên kết đến Bộ Tài chính, Ngân hàng Nhà nước, VCCI."
        ),
        "trust": (
            "Cập nhật theo quy định pháp luật mới nhất. "
            "Thêm disclaimer: 'Không phải tư vấn pháp lý chính thức'."
        ),
        "inline_per_h2": (
            "📋 PHÁP LÝ: Trích dẫn điều luật liên quan. "
            "📊 SỐ LIỆU: Dữ liệu tài chính có nguồn. "
            "⚖️ CASE STUDY: Ví dụ thực tế."
        ),
    },
    "general": {
        "experience": (
            "Thêm trải nghiệm thực tế cá nhân. "
            "Sử dụng hình ảnh thực tế, case study nếu có."
        ),
        "expertise": (
            "Trích dẫn nghiên cứu hoặc số liệu có uy tín. "
            "Đưa dữ liệu cụ thể, có thể đo lường."
        ),
        "authority": (
            "Liên kết đến nguồn uy tín (nghiên cứu, tổ chức chuyên môn)."
        ),
        "trust": (
            "Cập nhật thông tin mới nhất. Minh bạch về nguồn dữ liệu."
        ),
        "inline_per_h2": (
            "📊 DỮ LIỆU: Số liệu cụ thể có nguồn. "
            "💡 THỰC TẾ: Trải nghiệm hoặc ví dụ cụ thể."
        ),
    },
}


# ══════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════

def build_brief(
    topic: str,
    analysis: Dict,
    serp_data: Optional[Dict] = None,
    competitor_data: Optional[Dict] = None,
    network_data: Optional[Dict] = None,
    context_data: Optional[Dict] = None,
    linking_data: Optional[Dict] = None,
    methodology_prompt: str = "",
    project=None,  # Phase 33: Source Context
    macro_context: str = "", # Phase 35: Chained Context
    eav_table: str = "",     # Phase 35: Chained Context
) -> Dict:
    """
    Xây dựng Content Brief hoàn chỉnh từ kết quả phân tích.

    Phase 9: Heading Enrichment + Smart N-grams + Dynamic E-E-A-T.
    Phase 35: Chained Context Flow.
    """
    entity = analysis["central_entity"]
    topic_intent = analysis["search_intent"]

    # V17: Smart Intent Merge (4 loại chuẩn)
    # Backward compat: normalize legacy "vs" → "commercial"
    if topic_intent == "vs":
        topic_intent = "commercial"
    serp_intent = serp_data.get("dominant_intent", "") if serp_data else ""
    if serp_intent:
        intent = serp_intent  # SERP wins khi có data
    else:
        intent = topic_intent

    # ── Phase 9: Detect Niche ──
    niche = detect_niche(topic)
    logger.info("  [NICHE] Detected: '%s' cho topic '%s'", niche, topic)

    # ── Phase 9: Heading Enrichment → Phase 19: Comprehensive Outline Synthesis ──
    raw_headings = analysis["heading_structure"]
    enriched_headings = rewrite_headings_semantic(
        raw_headings, topic, niche, intent,
        serp_data=serp_data,
        competitor_data=competitor_data,
        methodology_prompt=methodology_prompt,
        project=project,  # Phase 33
        macro_context=macro_context, # Phase 35
        eav_table=eav_table, # Phase 35
        network_data=network_data, # Phase 35
        context_data=context_data, # Phase 35
    )

    # ── Phase 9: Smart N-gram Classification ──
    classified_ngrams = _classify_ngrams(
        competitor_data.get("ngrams_2", []) if competitor_data else [],
        competitor_data.get("ngrams_3", []) if competitor_data else [],
    )

    # ── Phase 8 Pass 3c: Semantic Quality Gate ──
    # Lọc N-gram rác bằng LLM suy luận thay vì regex/stopwords cố định
    try:
        from modules.agent_reviewer import review_ngram_quality
        if classified_ngrams.get("all_clean"):
            clean_ngrams = review_ngram_quality(
                classified_ngrams["all_clean"],
                entity=topic,
                intent=intent,
            )
            # Cập nhật lại classified_ngrams với danh sách đã lọc
            classified_ngrams["all_clean"] = clean_ngrams
            # Lọc entity/action tương ứng
            clean_set = set(clean_ngrams)
            classified_ngrams["entity"] = [ng for ng in classified_ngrams.get("entity", []) if ng in clean_set]
            classified_ngrams["action"] = [ng for ng in classified_ngrams.get("action", []) if ng in clean_set]
            logger.info("  [PHASE 8] Agent 3c completed: %d clean N-grams.", len(clean_ngrams))
    except ImportError:
        logger.info("  [PHASE 8] agent_reviewer not available for Pass 3c → using rule-based N-grams.")

    # Lấy thêm dữ liệu PAA và Gaps để nạp cho Micro-Briefing
    paa_questions = serp_data.get("people_also_ask", [])[:5] if serp_data else []
    gaps = []
    if competitor_data:
        info_gain = competitor_data.get("information_gain", {})
        gaps = info_gain.get("rare_headings", [])[:7]

    # Build micro_briefing FIRST so guidelines can use its analysis
    micro_briefing_data = _agent_micro_briefing_writer(
        topic, entity, intent, niche, methodology_prompt, enriched_headings,
        paa_questions=paa_questions, content_gaps=gaps, classified_ngrams=classified_ngrams,
        entity_attributes=analysis.get("entity_attributes", {}),
        project=project,  # Phase 33
    )

    # Keyword clusters from competitor data to pass into internal linking (V5.3)
    # FIX: n-grams are tuples (str, int) — extract just the string portion
    keyword_clusters_raw = []
    if competitor_data:
        for ng in (competitor_data.get("ngrams_2", []) + competitor_data.get("ngrams_3", [])):
            if isinstance(ng, tuple) and len(ng) >= 1:
                keyword_clusters_raw.append(str(ng[0]))
            elif isinstance(ng, str):
                keyword_clusters_raw.append(ng)
    # Also include clusters from network_data if available
    if network_data and network_data.get("clusters"):
        for c in network_data["clusters"]:
            if isinstance(c, dict):
                for kw in c.get("keywords", [])[:3]:
                    if isinstance(kw, str) and kw not in keyword_clusters_raw:
                        keyword_clusters_raw.append(kw)
            elif isinstance(c, str) and c not in keyword_clusters_raw:
                keyword_clusters_raw.append(c)

    brief = {
        "topic": topic,
        "niche": niche,
        "title_tag": _generate_title_tag(topic, entity),
        "meta_description": _generate_meta_description(topic, entity, intent),
        "search_intent": _format_intent(intent),
        "central_entity": entity,
        "entity_attributes": analysis["entity_attributes"],
        "heading_structure": enriched_headings,
        "content_guidelines": _generate_content_guidelines(
            topic, entity, intent, niche, classified_ngrams,
            headings=enriched_headings,
            methodology_prompt=methodology_prompt,
            micro_briefing=micro_briefing_data,
        ),
        "micro_briefing": micro_briefing_data,
        "suggested_questions": analysis["suggested_questions"],
        "internal_linking": _generate_linking_suggestions(
            analysis["related_topics"],
            keyword_clusters=keyword_clusters_raw,
            current_topic=topic,
            enriched_headings=enriched_headings,
        ),
        "eeat_checklist": _generate_eeat_checklist(entity, niche),
        "methodology_prompt": methodology_prompt,
    }

    # ── Thêm SERP data nếu có ──
    if serp_data:
        brief["serp_analysis"] = {
            "top_urls_display": serp_data.get("top_urls", []),
            "people_also_ask": serp_data.get("people_also_ask", []),
            "things_to_know": serp_data.get("things_to_know", []),
            "related_searches": serp_data.get("related_searches", []),
            "serp_entities": serp_data.get("serp_entities", {}),
            "serp_attributes": serp_data.get("serp_attributes", []),
            "topic_clusters": serp_data.get("topic_clusters", []),
            "dominant_intent": serp_data.get("dominant_intent", ""),
        }
        # Merge PAA questions vào suggested_questions
        paa = serp_data.get("people_also_ask", [])
        if paa:
            existing = set(brief["suggested_questions"])
            for q in paa:
                if q not in existing:
                    brief["suggested_questions"].append(q)

    # ── Thêm Competitor data nếu có ──
    if competitor_data:
        brief["competitor_analysis"] = {
            "common_headings": competitor_data.get("common_headings", []),
            "ngrams_2": competitor_data.get("ngrams_2", []),
            "ngrams_3": competitor_data.get("ngrams_3", []),
            "information_gain": competitor_data.get("information_gain", {}),
            "competitor_count": len(competitor_data.get("competitors", [])),
            "competitors_detail": [
                {
                    "url": c.get("url", ""),
                    "headings": c.get("headings", []),
                    "word_count": c.get("word_count", 0),
                }
                for c in competitor_data.get("competitors", [])
            ],
            "competitors_summary": [
                {
                    "url": c.get("url", ""),
                    "heading_count": len(c.get("headings", [])),
                    "word_count": c.get("word_count", 0),
                }
                for c in competitor_data.get("competitors", [])
            ],
        }

    # ── Thêm Query Network data nếu có ──
    if network_data:
        brief["query_network"] = network_data

    # ── Thêm Context Builder data nếu có ──
    if context_data:
        brief["context_builder"] = context_data

    # ── Override linking tĩnh bằng linking động từ Topical Map (nếu có) ──
    if linking_data:
        brief["internal_linking"] = linking_data

    # ═══════════════════════════════════════════════════════════
    #  SPEC V4.3: AGENT 3d — ANCHOR TEXT REVIEWER
    # ═══════════════════════════════════════════════════════════
    try:
        from modules.agent_reviewer import review_anchor_quality
        link_data = brief.get("internal_linking", {})
        outbound = link_data.get("outbound_nodes", [])
        if outbound:
            reviewed_anchors = review_anchor_quality(
                outbound, central_entity=entity, intent=intent,
            )
            link_data["outbound_nodes"] = reviewed_anchors
            brief["internal_linking"] = link_data
            logger.info("  [SPEC V4] Agent 3d: Anchor review completed.")
    except ImportError:
        logger.info("  [SPEC V4] agent_reviewer not available for Anchor review.")

    # ═══════════════════════════════════════════════════════════
    #  SPEC V4.4: AGENT 4 — PER-H2 CONTEXTUAL STRUCTURE
    # ═══════════════════════════════════════════════════════════
    try:
        from modules.agent_reviewer import generate_per_h2_instructions
        per_h2 = generate_per_h2_instructions(
            outline=enriched_headings,
            main_keyword=topic,
            intent=intent,
            classified_ngrams=classified_ngrams,
            eav_table=eav_table,
        )
        if per_h2:
            brief["contextual_structure_v4"] = per_h2
            logger.info("  [SPEC V4] Agent 4: Per-H2 instructions generated.")
    except ImportError:
        logger.info("  [SPEC V4] agent_reviewer not available for Per-H2 instructions.")

    logger.info("Đã xây dựng Content Brief cho: '%s' (niche=%s)%s%s%s%s", topic,
                niche,
                " (+ SERP)" if serp_data else "",
                " (+ Network)" if network_data else "",
                " (+ Context)" if context_data else "",
                " (+ Linking)" if linking_data else "")
    return brief


# ──────────────────────────────────────────────
#  PRIVATE HELPERS
# ──────────────────────────────────────────────

def _generate_title_tag(topic: str, entity: str) -> str:
    """Tạo gợi ý Title Tag tối ưu SEO (50-60 ký tự)."""
    topic_title = topic.strip().title()
    title = f"{topic_title} | Hướng Dẫn Chi Tiết [{_current_year()}]"
    if len(title) > 60:
        title = f"{topic_title} [{_current_year()}]"
    if len(title) > 60:
        title = topic_title[:57] + "..."
    return title


def _generate_meta_description(topic: str, entity: str, intent: str) -> str:
    """Tạo gợi ý Meta Description (150-160 ký tự)."""
    templates = {
        "informational": (
            f"Tìm hiểu {topic.lower()} chi tiết: đặc điểm, phân loại, "
            f"ứng dụng và lưu ý quan trọng. Cập nhật {_current_year()}."
        ),
        "commercial": (
            f"So sánh và đánh giá {entity.lower()} chi tiết. "
            f"Hướng dẫn lựa chọn {entity.lower()} phù hợp nhất."
        ),
        "commercial investigation": (
            f"So sánh và đánh giá {entity.lower()} chi tiết. "
            f"Hướng dẫn lựa chọn {entity.lower()} phù hợp nhất."
        ),
        "transactional": (
            f"Bảng giá {entity.lower()} mới nhất {_current_year()}. "
            f"Thông tin sản phẩm, chính sách giao hàng và bảo hành."
        ),
        "navigational": (
            f"Thông tin chính thức về {entity.lower()}. "
            f"Liên hệ tư vấn và báo giá nhanh chóng."
        ),
    }
    desc = templates.get(intent, templates["informational"])
    if len(desc) > 160:
        desc = desc[:157] + "..."
    return desc


def _format_intent(intent: str) -> Dict:
    """Format thông tin Search Intent cho Content Brief."""
    intent_descriptions = {
        "informational": {
            "type": "Informational",
            "description": "Người dùng muốn TÌM HIỂU thông tin, kiến thức.",
            "content_focus": "Giải thích, hướng dẫn, cung cấp kiến thức chuyên sâu.",
        },
        "vs": {
            "type": "Comparison (VS)",
            "description": "Người dùng muốn SO SÁNH 2 hoặc nhiều đối tượng.",
            "content_focus": "Bảng so sánh chi tiết, tiêu chí kỹ thuật, ưu/nhược điểm, khi nào chọn A vs B.",
        },
        "commercial": {
            "type": "Commercial Investigation",
            "description": "Người dùng đang SO SÁNH, ĐÁNH GIÁ trước khi mua.",
            "content_focus": "So sánh, review, bảng đánh giá, tiêu chí lựa chọn.",
        },
        "commercial investigation": {
            "type": "Commercial Investigation",
            "description": "Người dùng đang SO SÁNH, ĐÁNH GIÁ trước khi mua.",
            "content_focus": "So sánh, review, bảng đánh giá, tiêu chí lựa chọn.",
        },
        "transactional": {
            "type": "Transactional",
            "description": "Người dùng muốn MUA HÀNG hoặc thực hiện giao dịch.",
            "content_focus": "Thông tin sản phẩm, giá cả, CTA rõ ràng.",
        },
        "navigational": {
            "type": "Navigational",
            "description": "Người dùng muốn TÌM ĐẾN một trang/thương hiệu cụ thể.",
            "content_focus": "Thông tin chính thức, liên hệ, thương hiệu.",
        },
    }
    return intent_descriptions.get(intent, intent_descriptions["informational"])


def _agent_micro_briefing_writer(
    topic: str,
    entity: str,
    intent: str,
    niche: str,
    methodology_prompt: str,
    headings: List[Dict],
    paa_questions: List[str] = None,
    content_gaps: List[str] = None,
    classified_ngrams: Dict = None,
    entity_attributes: Dict = None,
    project=None,  # Phase 33: Source Context
) -> List[Dict]:
    """
    Agent 3: The Micro-Brief Writer.
    Gọi LLM sinh bảng Micro-Briefing (A-B-C-D-E framework) chi tiết cho từng H2 đã chốt.
    Tuyệt đối không được phép đổi tên H2.
    """
    try:
        import json
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return []

        import openai
        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        client = openai.OpenAI(api_key=api_key)

        # V5.1: Pass both H2 and H3 to LLM so it doesn't drop H3s
        outline_structured_text = ""
        current_h2 = ""
        for h in headings:
            if h["level"] == "H2":
                current_h2 = h["text"]
                outline_structured_text += f"- H2: {current_h2}\n"
            elif h["level"] == "H3":
                outline_structured_text += f"  + H3: {h['text']}\n"
            elif h["level"] == "H4":
                outline_structured_text += f"    * H4: {h['text']}\n"

        if_no_h2 = [h["text"] for h in headings if h["level"] == "H2"]
        if not if_no_h2:
            return []

        base_system = (
            "Bạn là Agent 3 (The Micro-Briefing Writer) thuộc hệ thống AI Agentic Workflow.\n"
            "Nhiệm vụ của bạn: Nhận vào danh sách các thẻ Heading ĐÃ ĐƯỢC CHỐT HẠ (không được sửa đổi), và viết nội dung [Micro-Briefing] cực kỳ chi tiết cho TỪNG thẻ H2 đó theo 'A-B-C-D-E Framework'.\n\n"
            "TUYỆT ĐỐI KHÔNG ĐƯỢC LÀM:\n"
            "1. Không thay đổi tên H2, không sửa chính tả hay thêm bớt từ vào H2 đã cung cấp.\n"
            "2. Không thay đổi thứ tự các H2.\n"
            "3. Không tự ý xóa bỏ bất kỳ H2 nào trong danh sách được giao.\n\n"
            "CẤU TRÚC YÊu CẦU: CHO MỖI QUY TRÌNH H2, viết 5 phần sau:\n"
            "- A. Snippet Block (FS ≤40 TỪ — NGHIÊM NGẶT):\n"
            "  * BẮT ĐẦU bằng Preceding Question (K2Q format: Definitional/Comparative) — HÃY ƯU TIÊN SỬ DỤNG 'PAA Questions' TRONG DỮ LIỆU ĐẦU VÀO ĐỂ LÀM CÂU HỎI MỞ ĐẦU NẾU PHÙ HỢP.\n"
            "  * Câu trả lời FS: PHẢI ≤40 từ, PHẢI là Exact Definitive Answer\n"
            "  * TUYỆT ĐỐI KHÔNG dùng: 'có thể', 'thường', 'thường được', 'đôi khi'\n"
            "  * Phải có ít nhất 1 số liệu kỹ thuật cụ thể (%, mm, MPa, kg/m...)\n"
            "  * Format: [Định nghĩa] + [Tiêu chuẩn/Thông số] + [Ứng dụng chính]\n"
            "- B. Deep Analysis (CONTEXTUAL STRUCTURE CỤ THỂ — KHÔNG CHUNG CHUNG):\n"
            "  * PHẢI chỉ định RÕ format cho section: nếu có so sánh → ghi rõ số cột bảng, tên từng cột, thứ tự cột, đơn vị đo.\n"
            "    VD đúng: 'Bảng 3 cột: Tiêu chí | Thép tấm (đơn vị: mm, MPa) | Thép cuộn (đơn vị: mm, MPa)'\n"
            "    VD sai: 'Bảng so sánh sẽ chỉ ra các chỉ số...'\n"
            "  * TUYỆT ĐỐI CẤM dùng các từ độn vô nghĩa như: 'Chúng tôi sẽ cung cấp thông tin chi tiết về...', 'Phần này sẽ khám phá...', 'Tiếp theo là...'. VÀO THẲNG VẤN ĐỀ BẰNG DỮ LIỆU ĐỊNH LƯỢNG MẠNH MẼ NHẤT.\n"
            "  * YÊU CẦU DATA CỤ THỂ (Domain-Agnostic): Tự suy luận lĩnh vực/ngành nghề dựa vào Entity và Niche. TỪ ĐÓ, BẮT BUỘC chỉ định người viết phải chèn CÁC ĐƠN VỊ ĐO LƯỜNG, THÔNG SỐ HOẶC CHỈ SỐ KỸ THUẬT chính xác. (VD: Nếu là Vật liệu → ép dùng mm, kg/m, MPa, chuẩn JIS/TCVN; Nếu Y tế → ép dùng mg, ml, %, liều lượng; Nếu IT → ms, GB, chuẩn bảo mật).\n"
            "  * PHẢI sử dụng exact numbers từ EAV Reference Table (nếu có). NẾU KHÔNG CÓ sẵn số liệu cụ thể trong EAV, BẮT BUỘC dùng placeholder: '[CẦN ĐIỀN SỐ GIÁ TỪ DOANH NGHIỆP]'.\n"
            "  * BẮT BUỘC lồng ghép tự nhiên các N-grams ngữ nghĩa được chỉ định.\n"
            "  * CHỈ khai thác Content Gaps có Attribute Prominence (liên quan trực tiếp đến entity trong source context). Gap không liên quan → bỏ qua.\n"
            "- C. Information Gain (EAV COVERAGE BẮT BUỘC):\n"
            "  * Phải đề xuất ít nhất 1 bảng EAV cụ thể (Entity-Attribute-Value) nếu là thông số kỹ thuật.\n"
            "  * NẾU H2 CÓ CÁC H3 CON TRONG OUTLINE, MỤC NÀY BẮT BUỘC PHẢI DÙNG ĐÚNG FORMAT NÀY ĐỂ LIỆT KÊ H3: 'Các H3 trong phần này bao gồm: [Tên H3 thứ 1], [Tên H3 thứ 2].'\n"
            "    VD ĐÚNG: 'Các H3 trong phần này bao gồm: Tiêu chuẩn Việt Nam (TCVN), Tiêu chuẩn quốc tế.'\n"
            "    VD SAI: 'Phần này gồm 2 H3: Tiêu chuẩn VN và Quốc Tế'\n"
            "  * KHÔNG ĐƯỢC tự sinh template 'H3: Bảng tiêu chuẩn sẽ được cung cấp'. PHẢI TRÍCH XUẤT Y XÌ TÊN H3 TỪ MỤC LỤC BÊN DƯỚI.\n"
            "  * Ghi [CẦN XÁC MINH] cho dữ liệu cần tra cứu thêm\n"
            "- D. Contextual Bridge (SOURCE CONTEXT INTEGRATION — ĐỌC KỸ SOURCE CONTEXT Ở ĐẦU PROMPT):\n"
            "  * ĐỌC KỸ khối 'SOURCE CONTEXT' được cung cấp ở đầu system prompt. Nếu có, BẮT BUỘC:\n"
            "  * TRONG SAPO: Phải có 1 câu khai báo brand tự nhiên (VD: 'Với kinh nghiệm 15 năm, [Brand] chia sẻ...'). KHÔNG ĐƯỢC BỎ QUA.\n"
            "  * TRONG [SUPP] cuối cùng: bridge PHẢI nhắc đến brand, GEO keywords, và hotline/CTA. Chèn NAP info đầy đủ.\n"
            "  * TRONG [MAIN]: TUYỆT ĐỐI KHÔNG nhắc brand, CTA, internal link. Chỉ dữ liệu khách quan.\n"
            "  * Nếu KHÔNG có SOURCE CONTEXT → bỏ qua, viết trung lập.\n"
            "- E. Transition: Câu nối chuyển ý TỰ NHIÊN sang khối H2 tiếp theo (Semantic Bridge). TUYỆT ĐỐI CẤM câu chuyển ý rập khuôn.\n\n"
            "ĐẶC BIỆT Ở ĐẦU TIÊN (SAPO) — QUAN TRỌNG NHẤT:\n"
            "Phần tử đầu tiên của JSON PHẢI LÀ mục hướng dẫn viết [SAPO/INTRODUCTION].\n"
            "⚠️ SAPO BẮT BUỘC từ 80 đến 120 từ. < 80 từ = BỊ TỪ CHỐI. Đếm kỹ trước khi trả lời.\n"
            "Sapo BẮT BUỘC có 3 yếu tố:\n"
            "1. Một câu định nghĩa chính xác Main Entity.\n"
            "2. Khai báo rõ Source Context (Chuyên gia/Doanh nghiệp góc nhìn B2B hay B2C).\n"
            "3. Liệt kê 3-4 LỢI ÍCH độc giả sẽ nhận được sau khi đọc bài.\n"
            "   KHÔNG copy nguyên tên H2. Diễn đạt bằng kết quả/giá trị.\n"
            "   VD: 'Sau bài này bạn nắm được: tiêu chuẩn kỹ thuật, cách chọn đúng đường kính, và bảng trọng lượng tra cứu nhanh.'\n\n"
            "OUTPUT TRẢ VỀ CHUẨN JSON LÀ MỘT MẢNG OBJECT NHƯ SAU:\n"
            "[\n"
            "  {\n"
            "    \"h2\": \"SAPO (Đoạn mở đầu)\",\n"
            "    \"intent\": \"Giới thiệu tổng quan...\",\n"
            "    \"snippet\": \"Nội dung Sapo (Định nghĩa, Source Context, 3-4 lợi ích giá trị — KHÔNG copy tên H2)...\",\n"
            "    \"analysis\": \"...\",\n"
            "    \"entities\": \"Entity1, Entity2, Entity3\",\n"
            "    \"info_gain\": \"...\",\n"
            "    \"bridge\": \"...\",\n"
            "    \"transition\": \"...\"\n"
            "  },\n"
            "  {\n"
            "    \"h2\": \"[Tên H2 thực tế]\",\n"
            "    \"intent\": \"Mục đích của H2 này (VÍ DỤ: Definitional, Pain Point...)\",\n"
            "    \"snippet\": \"Nội dung mong muốn của A. Preceding Question và Câu trả lời trực diện (≤40 từ)...\",\n"
            "    \"analysis\": \"Nội dung mong muốn của B. Phân tích chi tiết...\",\n"
            "    \"entities\": \"Các Entities/thuật ngữ BẮT BUỘC phải xuất hiện trong section này\",\n"
            "    \"info_gain\": \"Nội dung mong muốn của C. Góc nhìn vượt trội. Lưu ý NẾU MỤC NÀY CÓ H3 THÌ PHẢI DÙNG FORMAT: 'Các H3 trong phần này bao gồm: [Tên H3 1], [Tên H3 2].'\",\n"
            "    \"bridge\": \"Nội dung mong muốn của D. Lồng ghép giải pháp...\",\n"
            "    \"transition\": \"Nội dung mong muốn của E. Câu nối mượt mà (Semantic Bridge)...\"\n"
            "  }\n"
            "]\n"
            "CHỈ OUTPUT JSON RAW, KHÔNG TEXT DƯ THỪA HAY CODE BLOCK (```json)."
        )
        system_instruction = inject_semantic_prompt(base_system, agent_name="agent_3_micro")
        system_instruction = inject_source_context(system_instruction, project)  # Phase 33

        user_content = (
            f"Chủ đề chính (H1): '{topic}'\n"
            f"Entity: '{entity}', Intent: '{intent}', Niche: '{niche}'\n"
            f"Methodology: {methodology_prompt}\n\n"
            "--- DỮ LIỆU ĐẦU VÀO TỪ CÁC CỘT PHÂN TÍCH CHUYÊN SÂU ---\n"
        )
        if paa_questions:
            user_content += f"- Các câu hỏi PAA (Dùng làm FS Preceding Question): {', '.join(paa_questions)}\n"
        if content_gaps:
            user_content += f"- Content Gaps (Khoảng trống đối thủ thiếu sót - Cần khai thác trong Analysis): {', '.join(content_gaps)}\n"
        if classified_ngrams:
            entity_ngrams = classified_ngrams.get("entity", [])
            action_ngrams = classified_ngrams.get("action", [])
            if entity_ngrams:
                user_content += f"- Central Entity N-grams (PHẢI rải TOÀN BÀI, mỗi section ít nhất 1 lần): {', '.join(entity_ngrams[:6])}\n"
            if action_ngrams:
                user_content += f"- Macro Semantic N-grams (Chỉ rải vào section LIÊN QUAN, không ép vào mọi chỗ): {', '.join(action_ngrams[:8])}\n"

        # FIX 4: Truyền EAV reference table cho Agent 3 verbalize
        eav_data = entity_attributes if entity_attributes else {}
        if eav_data:
            user_content += f"\n- EAV Reference Table (Dùng EXACT numbers này, KHÔNG tự bịa):\n{eav_data}\n"

        user_content += (
            "\n"
            "DƯỚI ĐÂY LÀ DANH SÁCH CÁC HEADING (H2, H3, H4) ĐÃ ĐƯỢC CHỐT. BẠN PHẢI GIỮ NGUYÊN TÊN VÀ THỨ TỰ (Chỉ viết Micro-briefing object cho các H2):\n"
            f"{outline_structured_text}\n\n"
            "Hãy viết Sapo và sinh cấu trúc Micro-Briefing A-B-C-D-E (JSON Array) bám sát tuyệt đối vào danh sách mục lục trên và KẾT HỢP TRIỆT ĐỂ DỮ LIỆU ĐẦU VÀO Ở TRÊN để đạt chuẩn Semantic SEO."
        )

        logger.info("  [MICRO-BRIEFING] Gọi LLM lấy JSON chi tiết A-B-C-D-E format...")
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content}
            ],
            temperature=0.4,
            max_tokens=4000,
            timeout=120,
        )

        raw_text = response.choices[0].message.content.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        parsed_data = json.loads(raw_text.strip())
        if isinstance(parsed_data, list):
            logger.info("  [MICRO-BRIEFING] Thành công tạo %d H2 templates", len(parsed_data))
            return parsed_data
        
        return []
    except Exception as e:
        logger.warning(f"  [MICRO-BRIEFING] Lỗi API: {str(e)} -> Fallback...")
        return []


def _generate_content_guidelines(
    topic: str,
    entity: str,
    intent: str,
    niche: str,
    classified_ngrams: Dict,
    headings: List[Dict] = None,
    methodology_prompt: str = "",
    micro_briefing: List = None,
) -> list:
    """
    Phase 9: Hướng dẫn viết — Smart N-grams + Dynamic E-E-A-T inline.

    - Chọn N-grams theo ngữ cảnh section (không random)
    - Inject yêu cầu E-E-A-T vào từng section
    - Thêm inline instruction cho mỗi H2
    """
    niche_eeat = NICHE_EEAT.get(niche, NICHE_EEAT["general"])
    inline_h2 = niche_eeat.get("inline_per_h2", "")

    h2_instructions = ""
    if headings:
        h2_list = [
            h["text"] for h in headings
            if h["level"] == "H2"
            and "faq" not in h["text"].lower()
            and "information gain" not in h["text"].lower()
        ]
        if h2_list:
            h2_instructions = "\n  **Hướng dẫn cho từng H2:**\n"
            # Lấy micro-briefing analysis cho từng H2 (nếu có)
            micro_map = {}
            if micro_briefing:
                for mb in micro_briefing:
                    if isinstance(mb, dict):
                        h2_name = str(mb.get("h2", ""))
                        analysis = str(mb.get("analysis", ""))
                        if h2_name and analysis and len(analysis) > 20:
                            micro_map[h2_name] = analysis
            for h2_text in h2_list:
                # Tìm matching micro-briefing analysis cho H2 này
                matched_analysis = ""
                h2_clean = h2_text.replace("[MAIN] ", "").replace("[SUPP] ", "")
                for mb_h2, mb_analysis in micro_map.items():
                    mb_clean = mb_h2.replace("[MAIN] ", "").replace("[SUPP] ", "")
                    if mb_clean.lower() in h2_clean.lower() or h2_clean.lower() in mb_clean.lower():
                        # Truncate to first 200 chars for readability
                        matched_analysis = mb_analysis[:200].rstrip() + ("..." if len(mb_analysis) > 200 else "")
                        break
                if matched_analysis:
                    h2_instructions += f"  - **{h2_text}:** {matched_analysis}\n"
                else:
                    h2_instructions += f"  - **{h2_text}:** {inline_h2}\n"

    guidelines = [
        {
            "section": "Mở bài (Introduction)",
            "guideline": (
                f"Giới thiệu ngắn gọn về {entity}. "
                "Trả lời câu hỏi chính ngay trong 2-3 câu đầu tiên. "
                f"💡 E-E-A-T: {niche_eeat['experience']}"
                + _smart_pick_ngrams(classified_ngrams, "intro", 3)
            ),
            "word_count": "100-150 từ",
        },
        {
            "section": "Nội dung chính (Main Content)",
            "guideline": (
                "Tuân theo Contextual Hierarchy: mỗi H2 tóm tắt H3 bên dưới. "
                "Duy trì Contextual Flow liền mạch giữa các section.\n\n"
                + f"📋 E-E-A-T: {niche_eeat['expertise']}"
                + (f"\n  **Methodology (Bắt buộc):** {methodology_prompt}" if methodology_prompt else "")
                + h2_instructions
                + _smart_pick_ngrams(classified_ngrams, "main", 5)
            ),
            "word_count": "800-1200 từ",
        },
        {
            "section": "FAQ (Câu hỏi thường gặp)",
            "guideline": (
                "Áp dụng Schema FAQ Markup. "
                "Tối ưu cho Featured Snippet: câu trả lời 40-60 từ. "
                f"🔗 E-E-A-T: {niche_eeat['authority']}"
                + _smart_pick_ngrams(classified_ngrams, "faq", 3)
            ),
            "word_count": "200-300 từ",
        },
        {
            "section": "Kết bài (Conclusion)",
            "guideline": (
                "Tóm tắt trừu tượng (Abstractive Summary) cho toàn bài. "
                "Đưa CTA phù hợp với Search Intent. "
                f"✅ E-E-A-T: {niche_eeat['trust']}"
                + _smart_pick_ngrams(classified_ngrams, "conclusion", 3)
            ),
            "word_count": "80-120 từ",
        },
    ]

    return guidelines


def _generate_linking_suggestions(
    related_topics: list,
    keyword_clusters: list = None,
    current_topic: str = "",
    enriched_headings: list = None,
) -> list:
    """Tạo gợi ý internal linking từ keyword clusters hoặc related topics."""
    
    # Sử dụng module internal_linking.py có cluster-based linking (V5.3)
    try:
        from modules.internal_linking import build_internal_links
        result = build_internal_links(
            current_topic=current_topic,
            headings=enriched_headings or [],
            keyword_clusters=keyword_clusters,
        )
        if result and result.get("outbound_nodes"):
            return result
    except ImportError:
        pass

    # Fallback: simple suggestions from related_topics
    suggestions = []
    for topic in related_topics:
        suggestions.append({
            "target_topic": topic,
            "anchor_text_suggestion": topic,
            "placement": "Trong section liên quan hoặc phần FAQ",
        })
    return suggestions


def _generate_eeat_checklist(entity: str, niche: str = "general") -> list:
    """
    Phase 9: E-E-A-T checklist theo niche (không còn generic).

    Returns:
        List of dicts: [{"criterion": str, "action": str}]
    """
    eeat = NICHE_EEAT.get(niche, NICHE_EEAT["general"])
    return [
        {
            "criterion": "Experience (Kinh nghiệm)",
            "action": eeat["experience"],
        },
        {
            "criterion": "Expertise (Chuyên môn)",
            "action": eeat["expertise"],
        },
        {
            "criterion": "Authoritativeness (Thẩm quyền)",
            "action": eeat["authority"],
        },
        {
            "criterion": "Trustworthiness (Độ tin cậy)",
            "action": eeat["trust"],
        },
    ]


def _current_year() -> int:
    """Trả về năm hiện tại."""
    from datetime import datetime
    return datetime.now().year
