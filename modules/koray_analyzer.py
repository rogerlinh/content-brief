# -*- coding: utf-8 -*-
"""
modules/koray_analyzer.py - Phase 33: 7 Koray SEO Columns (L→R).

Sinh nội dung cho 7 cột Koray Semantic SEO mới:
  L: Macro Context & Central Entity    (LLM)
  M: EAV Table                         (LLM)
  N: Attribute Filtration & Order      (LLM)
  O: FS/PAA Map                        (LLM)
  P: Main vs Supplementary Split       (rule-based)
  Q: Source Context Alignment          (rule-based)
  R: Koray Quality Score               (rule-based)
"""

import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  RULE-BASED FUNCTIONS (luôn chạy, không cần LLM)
# ══════════════════════════════════════════════

def extract_main_supp_split(headings: List[Dict]) -> str:
    """
    Phân tích heading_structure, tách ra [MAIN] và [SUPP] sections.
    Detect dựa trên prefix '[MAIN]' và '[SUPP]' do Agent1 đánh dấu.

    Args:
        headings: List of {"level": "H2"|"H3", "text": "..."}

    Returns:
        Markdown text với 2 section rõ ràng.
    """
    main_list = []
    supp_list = []

    for h in headings:
        text = h.get("text", "")
        level = h.get("level", "H2")
        if "[MAIN]" in text:
            clean = text.replace("[MAIN]", "").strip()
            main_list.append(f"- **{level}**: {clean}")
        elif "[SUPP]" in text:
            clean = text.replace("[SUPP]", "").strip()
            supp_list.append(f"- **{level}**: {clean}")
        else:
            # Không có prefix → phân loại theo vị trí (trước/sau SUPP)
            if supp_list:
                supp_list.append(f"- **{level}**: {text}")
            else:
                main_list.append(f"- **{level}**: {text}")

    lines = ["## 📦 MAIN CONTENT\n"]
    if main_list:
        lines.extend(main_list)
    else:
        lines.append("_(Không phát hiện [MAIN] heading)_")

    lines.append("\n\n## 🔗 SUPPLEMENT CONTENT\n")
    if supp_list:
        lines.extend(supp_list)
    else:
        lines.append("_(Không phát hiện [SUPP] heading)_")

    # Bug 2 fix: Đếm riêng H2 và tổng headings
    main_h2 = sum(1 for h in main_list if "**H2**" in h)
    supp_h2 = sum(1 for h in supp_list if "**H2**" in h)
    main_count = len(main_list)
    supp_count = len(supp_list)
    total = main_count + supp_count
    supp_pct = round(supp_count / total * 100) if total > 0 else 0

    lines.append(f"\n\n**Tỉ lệ:** Main={main_h2} H2 ({main_count} headings) | Supp={supp_h2} H2 ({supp_count} headings) — {supp_pct}% supplement")
    if supp_pct < 20:
        lines.append("⚠️ CẢNH BÁO: Supplement Content < 20%. Xem xét thêm [SUPP] headings.")
    elif supp_pct > 35:
        lines.append("⚠️ CẢNH BÁO: Supplement Content > 35%. Có thể quá nhiều.")
    else:
        lines.append("✅ Tỉ lệ Main/Supp đạt chuẩn (20-35% Supp).")

    return "\n".join(lines)


def generate_source_context_alignment(brief: Dict, project=None) -> str:
    """
    Auto-check xem brief có align với Source Context không.
    Kiểm tra: brand mention, GEO keywords, CTA, NAP, Schema.

    Returns:
        Checklist ✅/❌ markdown.
    """
    lines = ["## 🎯 SOURCE CONTEXT ALIGNMENT CHECKLIST\n"]

    if not project:
        lines.append("_(Không có Project/Source Context để kiểm tra)_")
        return "\n".join(lines)

    # Tổng hợp toàn bộ text để kiểm tra
    all_text = ""
    headings = brief.get("heading_structure", [])
    for h in headings:
        all_text += " " + h.get("text", "")
    micro_briefings = brief.get("micro_briefing", [])
    for mb in micro_briefings:
        if isinstance(mb, dict):
            all_text += " " + str(mb.get("snippet", ""))
            all_text += " " + str(mb.get("bridge", ""))
    all_text = all_text.lower()

    # 1. Brand mention
    brand_lower = project.brand_name.lower()
    brand_ok = brand_lower in all_text
    lines.append(f"{'✅' if brand_ok else '❌'} **Brand mention**: '{project.brand_name}' {'có' if brand_ok else 'KHÔNG'} xuất hiện trong brief")

    # 2. GEO Keywords
    geo_keywords = [g.strip().lower() for g in (project.geo_keywords or "").split(",") if g.strip()]
    geo_found = any(geo in all_text for geo in geo_keywords) if geo_keywords else False
    lines.append(f"{'✅' if geo_found else '⚠️'} **GEO Keywords**: {'Tìm thấy' if geo_found else 'KHÔNG tìm thấy'} ({', '.join(project.geo_keywords.split(',')[:3]) if project.geo_keywords else 'N/A'})")

    # 3. SUPP section có NAP
    has_supp = any("[SUPP]" in h.get("text", "") for h in headings)
    lines.append(f"{'✅' if has_supp else '⚠️'} **Supplement Section**: {'Có [SUPP] heading' if has_supp else 'KHÔNG tìm thấy [SUPP] heading (cần có NAP ở Supp)'}")

    # 4. Hotline/Contact
    hotline_clean = re.sub(r'\D', '', project.hotline or "")
    hotline_found = hotline_clean in re.sub(r'\D', '', all_text) if hotline_clean else False
    lines.append(f"{'✅' if hotline_found else '⚠️'} **NAP Hotline**: {'Có' if hotline_found else 'KHÔNG'} tìm thấy hotline '{project.hotline}' trong brief")

    # 5. Competitor brands không xuất hiện dạng H2 độc lập
    competitor_brands_raw = project.competitor_brands or ""
    comp_list = [c.strip().lower() for c in competitor_brands_raw.split(",") if c.strip()]
    h2_texts = [h.get("text", "").lower() for h in headings if h.get("level") == "H2"]
    competitor_violation = any(
        any(comp in h2 for comp in comp_list)
        for h2 in h2_texts
    )
    lines.append(f"{'✅' if not competitor_violation else '❌'} **Competitor Brand Rule**: {'Không vi phạm' if not competitor_violation else 'VI PHẠM — brand đối thủ xuất hiện dạng H2 độc lập!'}")

    # Tổng điểm
    checks = [brand_ok, geo_found, has_supp, not competitor_violation]
    score = sum(checks)
    lines.append(f"\n**Điểm Alignment: {score}/{len(checks)}** ({'Tốt' if score >= 3 else 'Cần cải thiện'})")

    return "\n".join(lines)


# ── Phase 36: CONSTANTS for quality scoring ───────────────────────────────────
# Structural cap: điểm tối đa dựa trên số lượng H2 thực tế
# < 3 H2 → yếu, 3 H2 → OK, 4 H2 → tốt, ≥5 H2 → không bị cap
STRUCTURAL_CAPS = {
    0: 0, 1: 10, 2: 25, 3: 60, 4: 80, 5: 100
}


def calculate_quality_score(brief: Dict, headings: List[Dict], project=None) -> str:
    """
    Tính điểm Koray Quality /100 dựa trên 10 tiêu chí rule-based.

    Returns:
        Bảng markdown điểm + danh sách lỗi phát hiện.
    """
    scores = {}
    issues = []
    strict_penalties = 0

    # 1. Contextual Vector (h2 không generic & đủ số lượng tối thiểu)
    h2_texts = [h.get("text", "") for h in headings if h.get("level") == "H2"]
    generic_patterns = ["tổng quan", "kết luận", "giới thiệu", "đặc điểm", "ứng dụng"]
    # FIX 6: Tăng threshold từ 30 lên 50 ký tự để không bỏ lọt các H2 template dài
    generic_count = sum(1 for h in h2_texts if any(p in h.lower() for p in generic_patterns) and len(h) < 50)
    
    h2_count = len(h2_texts)
    # Phạt nặng nếu quá ít H2 (1-2 H2 không thể tạo thành vector ngữ cảnh)
    if h2_count < 3:
        s1 = 0
        issues.append(f"❌ Cấu trúc thiếu H2 nghiêm trọng ({h2_count} H2). Cần tối thiểu 3 H2.")
    else:
        s1 = max(0, 10 - generic_count * 5)
        if generic_count > 0:
            issues.append(f"❌ {generic_count} heading generic không đủ cụ thể")
    scores["1. Contextual Vector"] = s1

    # 2. Contextual Hierarchy (có H3 dưới ít nhất 50% H2)
    h3_count = sum(1 for h in headings if h.get("level") == "H3")
    h3_ratio = h3_count / h2_count if h2_count > 0 else 0
    
    if h2_count < 3:
        s2 = 0 # Không có hierarchy nếu chỉ có 1-2 H2
        issues.append("❌ Điểm Hierarchy bằng 0 do cấu trúc H2 không đủ (cần ≥3 H2).")
    else:
        s2 = 10 if h3_ratio >= 1.0 else (7 if h3_ratio >= 0.5 else 3)
        if h3_ratio < 0.5:
            issues.append(f"⚠️ Cấu trúc nông: Chỉ {h3_ratio*100:.0f}% H2 có triển khai H3 (khuyến nghị ≥50% tùy chủ đề).")
    scores["2. Contextual Hierarchy (H3)"] = s2

    # V11-R1: H3 TEMPLATE QUALITY DETECTION
    # Detect H3 headings that are template-generated (contain '??' or '[' brackets)
    # Phase 36: Removed redundant `import re` — already at module top
    def _is_template_h3(t: str) -> bool:
        if "??" in t or t.endswith("??"):
            return True
        if "[[" in t:
            return True
        if t.strip().startswith("["):
            # Allow standard codes: [SS400], [TCVN 5709], [JIS G3101], [ASTM A36], etc.
            if re.match(r'^\[[A-Z0-9\-\/ ]+\]', t.strip()):
                return False
            return True
        return False

    h3_texts = [h.get("text", "") for h in headings if h.get("level") == "H3"]
    if h3_texts:
        template_h3_count = sum(1 for t in h3_texts if _is_template_h3(t))
        template_ratio = template_h3_count / len(h3_texts)
        if template_ratio > 0.3:
            issues.append(
                f"❌ STRICT PENALTY: {template_h3_count}/{len(h3_texts)} H3 "
                f"({template_ratio*100:.0f}%) là template chất lượng thấp (chứa '??' hoặc '['). Trừ 8 điểm."
            )
            strict_penalties += 8

    # 3. FS Block (micro_briefing có snippet ngắn)
    micro = brief.get("micro_briefing", [])
    valid_fs = 0
    long_fs = 0
    for mb in micro:
        snippet = str(mb.get("snippet", ""))
        word_count = len(snippet.split())
        if 10 < word_count <= 60:
            valid_fs += 1
        elif word_count > 60:
            long_fs += 1
            
    s3 = 10 if valid_fs >= max(1, h2_count - 1) else (5 if valid_fs > 0 else 0)
    scores["3. FS Blocks (≤60 từ)"] = s3
    if valid_fs < max(1, h2_count - 1):
        issues.append(f"⚠️ Chỉ {valid_fs}/{h2_count} H2 có FS snippet độ dài lý tưởng (10-60 từ).")
    if long_fs > 0:
        issues.append(f"⚠️ Có {long_fs} FS snippet khá dài (> 60 từ). Cân nhắc rút gọn để tối ưu Featured Snippet.")

    # 4. PAA Map — P2.4 FIX: 0 điểm khi không có PAA thực
    paa_from_serp = brief.get("serp_analysis", {}).get("people_also_ask", [])
    paa_from_analysis = brief.get("suggested_questions", [])
    paa_all = paa_from_serp or paa_from_analysis
    # Lọc bỏ PAA placeholder ("N/A", empty strings)
    paa_real = [q for q in paa_all if q and not str(q).startswith("N/A")]
    s4 = 10 if len(paa_real) >= 3 else (5 if paa_real else 0)
    scores["4. PAA Mapping"] = s4
    if not paa_real:
        issues.append("❌ Không có dữ liệu PAA thực từ SERP — FS Blocks không thể tạo")
    elif len(paa_real) < 3:
        issues.append(f"⚠️ Chỉ có {len(paa_real)} PAA questions (khuyến nghị ≥3)")

    # 5. Main/Supp Split
    has_main = any("[MAIN]" in h.get("text", "") for h in headings)
    has_supp = any("[SUPP]" in h.get("text", "") for h in headings)
    s5 = 10 if (has_main and has_supp) else (5 if has_main else 0)
    scores["5. Main/Supp Split"] = s5
    if not has_supp:
        issues.append("❌ Không có [SUPP] section — thiếu NAP và CTA")

    # 6. EAV Coverage — P2.4 FIX: 0 điểm khi EAV Table trống
    eav_table_md = brief.get("eav_table", "")
    if eav_table_md and len(eav_table_md.strip()) > 10:
        eav_count = sum(1 for line in eav_table_md.split("\n") if line.strip().startswith("|") and "---" not in line) - 1
    else:
        eav_data = brief.get("entity_attributes", {})
        eav_count = len(eav_data) if isinstance(eav_data, dict) else 0

    s6 = 10 if eav_count >= 3 else (5 if eav_count > 0 else 0)
    scores["6. EAV Coverage"] = s6
    if eav_count < 3:
        issues.append(f"⚠️ Chỉ có {max(0, eav_count)} dòng trong EAV Table (cần ≥3)")

    # 7. Source Context Alignment — MUST scan headings + micro_briefing (consistent with generate_source_context_alignment)
    if project:
        all_text = " ".join(h.get("text", "") for h in headings)
        for mb in micro:
            if isinstance(mb, dict):
                all_text += " " + str(mb.get("snippet", ""))
                all_text += " " + str(mb.get("bridge", ""))
        all_text_lower = all_text.lower()
        # Check 3 tiêu chí: brand, geo, hotline
        brand_ok = project.brand_name.lower() in all_text_lower
        geo_keywords = [g.strip().lower() for g in (project.geo_keywords or "").split(",") if g.strip()]
        geo_ok = any(geo in all_text_lower for geo in geo_keywords) if geo_keywords else True
        hotline_clean = re.sub(r'\D', '', project.hotline or "")
        hotline_ok = hotline_clean in re.sub(r'\D', '', all_text) if hotline_clean else True
        checks_passed = sum([brand_ok, geo_ok, hotline_ok])
        s7 = {3: 10, 2: 7, 1: 4, 0: 0}.get(checks_passed, 0)  # Phase 36: .get() safe
        if not brand_ok:
            issues.append("❌ Brand chưa xuất hiện trong SAPO hoặc [SUPP] bridge")
    else:
        s7 = 5  # Neutral khi không có project
    scores["7. Source Context Alignment"] = s7

    # 8. Internal Link Logic (SUPP có linking, MAIN không)
    linking = brief.get("internal_linking", {})
    outbound = linking.get("outbound_nodes", []) if isinstance(linking, dict) else []
    
    # FIX 7: Kiểm tra chất lượng anchor chữ (phải có từ 2 chữ trở lên) chứ không chỉ check presence
    anchor_quality = all(len(n.get("anchor", "").split()) >= 2 for n in outbound)
    s8 = 10 if (outbound and anchor_quality) else (7 if outbound else 5)  # Rule-based check cơ bản
    scores["8. Internal Link Logic"] = s8
    
    if not outbound:
        issues.append("❌ STRICT PENALTY: Không có Internal Links hợp lệ (Root không có Node ra). Trừ 15 điểm tổng.")
        strict_penalties += 15
    elif not anchor_quality:
        issues.append("❌ STRICT PENALTY: Anchor text sơ sài (1 chữ). Trừ 5 điểm tổng.")
        strict_penalties += 5

    # 9. Sapo Quality (micro_briefing[0] là SAPO)
    # Chuẩn: 80-120 từ, dung sai ±30% → 56-156 từ đạt full score
    sapo_mb = micro[0] if micro else {}
    sapo_snippet = str(sapo_mb.get("snippet", ""))
    sapo_words = len(sapo_snippet.split())
    s9 = 10 if 56 <= sapo_words <= 156 else (5 if sapo_words > 0 else 0)
    scores["9. Sapo Quality"] = s9
    if not (56 <= sapo_words <= 156):
        issues.append(f"⚠️ Sapo có {sapo_words} từ (chuẩn 80-120, dung sai 56-156 từ)")

    # 10. Attribute Filtration (số H2 hợp lý 5-12)
    s10 = 10 if 5 <= h2_count <= 12 else (5 if 3 <= h2_count < 5 else 0)
    scores["10. Attribute Filtration (H2 count)"] = s10
    if not (5 <= h2_count <= 12):
        issues.append(f"⚠️ Có {h2_count} H2 (khuyến nghị 5-12)")

    # 11. Per-H2 Writing Guidance (word_count_target)
    ctx_v4 = brief.get("contextual_structure_v4", {})
    per_h2 = ctx_v4.get("per_h2", []) if isinstance(ctx_v4, dict) else []
    if isinstance(per_h2, dict):
        per_h2 = list(per_h2.values())
    main_h2s = [h for h in per_h2 if isinstance(h, dict) and "[MAIN]" in h.get("h2", "").upper()]
    if main_h2s:
        h2_with_wc = sum(1 for h in main_h2s if h.get("word_count_target"))
        wc_ratio = h2_with_wc / len(main_h2s)
        s11 = 10 if wc_ratio >= 0.5 else (5 if wc_ratio > 0 else 0)
    else:
        s11 = 0
    scores["11. Per-H2 Guidance (Word Count)"] = s11
    if main_h2s and s11 < 10:
        issues.append(f"⚠️ Chỉ {h2_with_wc}/{len(main_h2s)} H2 MAIN có guidance word_count_target (chuẩn ≥50%)")

    total = int(sum(scores.values()) * 10 / len(scores))

    # ══════════════════════════════════════════
    # STRUCTURAL FAILURE GATE
    # Cap điểm tổng nếu H2 không đủ cho intent
    # Phase 2.2: Use centralized intent module
    # ══════════════════════════════════════════
    from modules.intent import get_h2_minimum
    detected_intent = brief.get("search_intent", {})
    if isinstance(detected_intent, dict):
        detected_intent = detected_intent.get("type", "informational").lower()
    else:
        detected_intent = str(detected_intent).lower()
    min_h2_required = get_h2_minimum(detected_intent)
    structural_cap = STRUCTURAL_CAPS.get(h2_count, 100)  # ≥5 H2 = không bị cap

    if h2_count < min_h2_required:
        issues.append(
            f"❌ STRUCTURAL FAILURE: Chỉ có {h2_count} H2 cho intent '{detected_intent}' "
            f"(cần tối thiểu {min_h2_required}). Điểm bị giới hạn {structural_cap}/100."
        )
    total = min(total, structural_cap)

    # ══════════════════════════════════════════
    # PROMINENCE PENALTY
    # Phạt -5 điểm cho mỗi H2 từ Rare Headings không có PAA support
    # ══════════════════════════════════════════
    paa_from_serp = brief.get("serp_analysis", {}).get("people_also_ask", [])
    paa_from_analysis = brief.get("suggested_questions", [])
    paa_all = paa_from_serp or paa_from_analysis
    paa_lower = [str(p).lower() for p in paa_all]

    info_gain = brief.get("serp_analysis", {}).get("information_gain", {})
    if isinstance(info_gain, dict):
        rare_headings = info_gain.get("rare_headings", [])
    else:
        rare_headings = []

    h2_headings_lower = [h.get("text", "").lower() for h in headings if h.get("level") == "H2"]

    unverified_rare_count = 0
    for rare_h in rare_headings:
        rare_lower = str(rare_h).lower()
        # Kiểm tra H2 này có trong outline không
        in_outline = any(rare_lower in h2 or h2 in rare_lower for h2 in h2_headings_lower)
        # Kiểm tra có PAA support không
        has_paa_support = any(rare_lower in paa or paa in rare_lower for paa in paa_lower)
        
        if in_outline and not has_paa_support:
            unverified_rare_count += 1

    prominence_penalty = unverified_rare_count * 5
    if prominence_penalty > 0:
        issues.append(
            f"⚠️ PROMINENCE PENALTY: -{prominence_penalty} điểm "
            f"({unverified_rare_count} H2 từ Rare Headings không có PAA support)."
        )
    
    total = max(0, total - prominence_penalty - strict_penalties)

    grade = "A" if total >= 85 else ("B" if total >= 70 else ("C" if total >= 55 else ("D" if total >= 40 else "F")))

    # Build output
    lines = [f"## 📊 KORAY QUALITY SCORE: **{total}/100** (Grade {grade})\n"]
    lines.append("| Tiêu chí | Điểm |")
    lines.append("|----------|------|")
    for criterion, score in scores.items():
        icon = "✅" if score >= 8 else ("⚠️" if score >= 5 else "❌")
        lines.append(f"| {icon} {criterion} | {score}/10 |")

    if issues:
        lines.append("\n### ❌ Các vấn đề phát hiện:")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("\n✅ Không phát hiện vấn đề nghiêm trọng!")

    return "\n".join(lines)


# ══════════════════════════════════════════════
#  LLM-BASED FUNCTIONS (có try/except fallback = "")
# ══════════════════════════════════════════════

def _get_openai_client(api_key: str):
    """Helper tạo OpenAI client. Return None nếu không có key."""
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return None
    try:
        import openai
        return openai.OpenAI(api_key=api_key)
    except Exception:
        return None


def _call_llm(client, model: str, system: str, user: str, max_tokens: int = 1500) -> str:
    """Helper gọi LLM và trả về text. Throw exception nếu thất bại."""
    # Phase 2.3: Use llm_utils for exponential backoff retry
    from modules.llm_utils import call_llm_with_retry, LLM_DEFAULTS
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return call_llm_with_retry(
            client=client,
            model=model,
            messages=messages,
            temperature=LLM_DEFAULTS["temperature_seo"],  # 0.3
            max_tokens=max_tokens,
            timeout=LLM_DEFAULTS["timeout"],              # 60s
        )
    except Exception as exc:
        logger.warning("[KorayAnalyzer._call_llm] LLM call failed (returning empty): %s", exc)
        return ""


def generate_macro_context(
    topic: str,
    analysis: Dict,
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột L: Gọi LLM sinh Macro Context & Central Entity Analysis.

    Output format:
    - Central Entity, Macro Context, Search Intent Type, Intent Subtype, Target User
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return ""

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Bạn là chuyên gia Semantic SEO (Koray Framework). Nhiệm vụ: Phân tích Macro Context cho từ khóa.\n"
            "Output phải là Markdown ngắn gọn với 5 dòng sau:\n"
            "- **Central Entity**: [tên entity chính]\n"
            "- **Macro Context**: [1 câu mô tả ngữ cảnh vĩ mô (Contextual Domain) duy nhất, KHÔNG nhập nhằng giữa nhiều ngữ cảnh]\n"
            "- **Search Intent Type**: [Definitional / Comparative / Informational / Commercial / Transactional]\n"
            "- **Intent Subtype**: [What-is / How-to / vs / Price / Guide / Review / ...]\n"
            "- **Người dùng mục tiêu**: [mô tả ngắn người đang tìm kiếm từ khóa này]\n"
            "KHÔNG GIẢI THÍCH THÊM. CHỈ OUTPUT 5 DÒNG TRÊN."
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        entity = analysis.get("central_entity", topic)
        intent = analysis.get("search_intent", "informational")
        if isinstance(intent, dict):
            intent = intent.get("type", "informational")

        user = (
            f"Từ khóa: '{topic}'\n"
            f"Central Entity hiện tại: '{entity}'\n"
            f"Search Intent phát hiện: '{intent}'\n"
            "Hãy phân tích và output theo đúng format yêu cầu."
        )

        result = _call_llm(client, model, system, user, max_tokens=400)
        logger.info("  [KORAY-L] Macro Context OK (%d chars)", len(result))
        return result

    except Exception as e:
        logger.warning("  [KORAY-L] Macro Context failed: %s", e)
        return ""


def generate_eav_table(
    topic: str,
    analysis: Dict,
    competitor_data: Optional[Dict] = None,
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột M: Gọi LLM sinh EAV Table (Entity - Attribute - Value).

    Output format: Bảng markdown | Entity | Attribute | Value |
    Fix V6: VS intent → parse 2 entities, 3-column comparison table, min 6 rows.
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return ""

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Bạn là chuyên gia Semantic SEO (Koray Framework). Nhiệm vụ: Tạo bảng EAV (Entity-Attribute-Value) cho từ khóa.\n"
            "Quy tắc BẮT BUỘC:\n"
            "1. Output PHẢI là bảng Markdown (bắt đầu bằng `|`).\n"
            "2. Bảng phải liệt kê các Attribute theo 3 nhóm (Root Attributes, Universal Attributes, Rare/Unique Attributes) theo mức độ thu hẹp dần (Khoảng cách thực thể).\n"
            "3. Mỗi entity phải có ≥6 attributes quan trọng nhất (kỹ thuật ưu tiên).\n"
            "4. Don vi do BUOC phu hop nganh. Neu la GIA (gia tham khao, lai suat, ty gia, chi phi) hoac khong chac chan -> BUOC ghi [CAN XAC MINH], TUYET DOI KHONG tu bya so.\n"
            "5. KHONG de o trong — neu khong biet ghi [CAN XAC MINH].\n"
            "OUTPUT CHỈ LÀ BẢNG MARKDOWN, KHÔNG CÓ TEXT GIỚI THIỆU."
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        # Phase 37: Industry-aware unit guidance
        industry_units_map = {
            "commodity_trading": "% [phan tram], VND, nam, diem %, lan/nam, ngay, ty le ky quy [%]",
            "construction_material": "mm, kg/m, kg/cuon, MPa, C [do], m, tan, cay, cuon, m3",
            "food_nutrition": "g, kcal, mg, mcg, %, IU, g/100g, ml",
            "tech_gadget": "GHz, nm, mAh, GB, inch, MP, W, dB",
            "finance_law": "% [phan tram], VND, nam, diem %, ngay, thang",
            "general": "mm, kg, m, % [phan tram], C [do], VND, nam",
        }
        niche_for_eav = "general"
        try:
            if project and hasattr(project, "industry") and project.industry:
                from modules.content_brief_builder import detect_niche as _dn
                niche_for_eav = _dn(topic, project.industry)
            else:
                from modules.content_brief_builder import detect_niche as _dn
                niche_for_eav = _dn(topic)
        except Exception:
            pass
        unit_guide_str = industry_units_map.get(niche_for_eav, industry_units_map["general"])

        entity = analysis.get("central_entity", topic)
        attrs = analysis.get("entity_attributes", {})
        attrs_str = "\n".join([f"- {k}: {v}" for k, v in attrs.items()]) if attrs else "N/A"

        intent = str(analysis.get("search_intent", {}).get("type", "informational") if isinstance(analysis.get("search_intent"), dict) else analysis.get("search_intent", "informational"))
        is_vs = "vs" in intent.lower() or "comparison" in intent.lower()

        if is_vs:
            # V6: Parse 2 entities from topic
            entity_parts = re.split(
                r'\bvà\b|\bvs\b|\bvới\b|\bso sánh\b|\bkhác nhau\b',
                topic, flags=re.IGNORECASE
            )
            entity_parts = [p.strip() for p in entity_parts if p.strip()]
            # Clean trailing question words
            for rem in ["thế nào", "như thế nào", "khác gì", "là gì", "ra sao"]:
                entity_parts = [p.replace(rem, "").strip() for p in entity_parts]
            entity_parts = [p for p in entity_parts if p]

            if len(entity_parts) >= 2:
                entity_a, entity_b = entity_parts[0], entity_parts[1]
            else:
                entity_a, entity_b = entity, "đối chiếu"

            user = (
                f"Từ khóa: '{topic}'\n"
                f"Search Intent: So sánh (VS)\n"
                f"Entity A: '{entity_a}'\n"
                f"Entity B: '{entity_b}'\n\n"
                f"Hãy tạo bảng EAV so sánh chi tiết.\n\n"
                f"FORMAT BẮT BUỘC 3 CỘT:\n"
                f"| Attribute (Tiêu chí so sánh) | {entity_a} | {entity_b} |\n"
                f"|------|------|------|\n"
                f"| Định nghĩa | [giá trị] | [giá trị] |\n"
                f"| Kích thước/Độ dày | [giá trị + đơn vị] | [giá trị + đơn vị] |\n"
                f"| ... | ... | ... |\n\n"
                f"QUY TẮC:\n"
                f"- Tối thiểu 6 rows (định nghĩa, kích thước, độ bền, ứng dụng, giá, ưu/nhược điểm)\n"
                f"- Don vi do phu hop nganh: {unit_guide_str}\n"
                f"- Gia tham khao LUON danh dau [CAN XAC MINH]\n"
                f"- TUYET DOI: Neu khong chac chan gia tri -> BUOC ghi [CAN XAC MINH], KHONG tu bya so\n"
                f"- KHONG de o trong — neu khong biet ghi [CAN XAC MINH]\n"
            )
        else:
            user = (
                f"Từ khóa: '{topic}'\n"
                f"Central Entity: '{entity}'\n"
                f"Attributes đã biết:\n{attrs_str}\n\n"
                f"Hãy tạo bảng EAV đầy đủ với 3 cột: | Entity | Attribute | Value |.\n"
                f"QUY TAC:\n"
                f"- Moi gia tri SOI phai co don vi do phu hop nganh: {unit_guide_str}\n"
                f"- TUYET DOI: Gia (gia tham khao, lai suat, ty gia, chi phi) -> BUOC ghi [CAN XAC MINH]\n"
                f"- TUYET DOI: Neu khong chac chan -> BUOC ghi [CAN XAC MINH], KHONG tu bya so\n"
                f"- KHONG de o trong — neu khong biet ghi [CAN XAC MINH]\n"
            )

        result = _call_llm(client, model, system, user, max_tokens=1000)
        logger.info("  [KORAY-M] EAV Table OK (%d chars)", len(result))
        return result

    except Exception as e:
        logger.warning("  [KORAY-M] EAV Table failed: %s", e)
        return ""


def generate_attribute_filtration(
    topic: str,
    headings: List[Dict],
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột N: Gọi LLM giải thích thứ tự H2 theo 3 tiêu chí Koray:
    Prominence, Popularity, Relevance (điểm /10 mỗi tiêu chí).

    Output: text markdown giải thích từng H2 + lý do loại bỏ.
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return ""

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        h2_list = [h["text"] for h in headings if h.get("level") == "H2"]
        if not h2_list:
            return ""

        base_system = (
            "Bạn là chuyên gia Semantic SEO (Koray Framework). Nhiệm vụ: Giải thích thứ tự Attribute Filtration.\n"
            "Với mỗi H2 trong outline, hãy đánh giá theo 3 tiêu chí:\n"
            "- Prominence (P): Attribute quan trọng đến mức nào để định nghĩa entity? /10\n"
            "- Popularity (Pop): Attribute này được tìm kiếm nhiều không? /10\n"
            "- Relevance (R): Attribute phù hợp với Source Context của brand không? /10\n"
            "Format cho mỗi H2: `**H2: [tên]** — P:x/10 Pop:x/10 R:x/10 → Lý do đặt ở vị trí này`\n"
            "OUTPUT NGẮN GỌN, TỐI ĐA 800 TOKENS."
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        h2_str = "\n".join([f"{i+1}. {h}" for i, h in enumerate(h2_list)])
        user = (
            f"Từ khóa: '{topic}'\n\n"
            f"Danh sách H2 theo thứ tự trong outline:\n{h2_str}\n\n"
            "Hãy phân tích Attribute Filtration cho từng H2 theo format yêu cầu."
        )

        result = _call_llm(client, model, system, user, max_tokens=800)
        logger.info("  [KORAY-N] Attribute Filtration OK (%d chars)", len(result))
        return result

    except Exception as e:
        logger.warning("  [KORAY-N] Attribute Filtration failed: %s", e)
        return ""


def generate_fs_paa_map(
    topic: str,
    paa_questions: List[str],
    headings: List[Dict],
    project=None,
    api_key: str = "",
) -> str:
    """
    Cột O: Gọi LLM map từng PAA question vào đúng H2/H3 và viết FS Block ≤40 từ.

    Output: Bảng markdown | PAA Question | Vị trí | Format | FS Block |
    """
    try:
        from config import LLM_CONFIG
        client = _get_openai_client(api_key or LLM_CONFIG.get("api_key", ""))
        if not client:
            return ""

        if not paa_questions:
            return "_(Không có PAA data từ SERP)_"

        from modules.semantic_knowledge import inject_semantic_prompt, inject_source_context
        model = LLM_CONFIG.get("model", "gpt-4o-mini")

        base_system = (
            "Bạn là chuyên gia Semantic SEO. Nhiệm vụ: Map PAA Questions vào Heading structure.\n"
            "Rules:\n"
            "1. Với mỗi PAA question: xác định heading H2/H3 phù hợp nhất để trả lời câu hỏi đó.\n"
            "2. 🚨 ANTI-CONTAMINATION (QUY TẮC SỐNG CÒN): KIỂM TRA ENTITY MATCHING TRƯỚC KHI MAP.\n"
            "   - Tuyệt đối KHÔNG map PAA của Entity A vào heading chỉ nói về Entity B.\n"
            "   - Đặc biệt trong bài 'vs' (ví dụ Tấm xi măng vs Thạch cao): Câu hỏi về 'Thạch cao' KHÔNG ĐƯỢC nằm dưới H2 'Ưu điểm của Tấm xi măng'.\n"
            "   - Chỉ map vào H2 so sánh chung, hoặc H2 định nghĩa đúng Entity đó, hoặc H2 FAQ cuối bài.\n"
            "3. Chọn Format: Snippet (câu trả lời ngắn), Table, List, hoặc Step-by-step.\n"
            "4. Viết FS Block: câu trả lời ≤40 từ, PHẢI là Exact Definitive Answer (không 'có thể', 'thường').\n"
            "Output PHẢI là bảng Markdown:\n"
            "| PAA Question | Vị trí (H2/H3) | Format | FS Block (≤40 từ) |\n"
            "|---|---|---|---|\n"
            "OUTPUT CHỈ LÀ BẢNG MARKDOWN."
        )
        system = inject_semantic_prompt(base_system)
        system = inject_source_context(system, project)

        h_list = [f"{h['level']}: {h['text']}" for h in headings if h.get("level") in ["H2", "H3"]]
        headings_str = "\n".join(h_list[:20])  # Tối đa 20 headings
        paa_str = "\n".join([f"- {q}" for q in paa_questions[:15]])  # Tối đa 15 PAA

        user = (
            f"Từ khóa (H1): '{topic}'\n\n"
            f"Heading Structure:\n{headings_str}\n\n"
            f"PAA Questions cần map:\n{paa_str}\n\n"
            "Hãy map từng PAA vào heading phù hợp và viết FS Block ≤40 từ theo format yêu cầu."
        )

        result = _call_llm(client, model, system, user, max_tokens=1500)
        logger.info("  [KORAY-O] FS/PAA Map OK (%d chars)", len(result))
        return result

    except Exception as e:
        logger.warning("  [KORAY-O] FS/PAA Map failed: %s", e)
        return ""
