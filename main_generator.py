# -*- coding: utf-8 -*-
"""
main_generator.py - Pipeline chính của Content Brief Generator.

Đọc danh sách chủ đề từ topics.csv, chạy tuần tự qua các module
phân tích, và xuất kết quả Content Brief ra file .md.

Usage:
    python main_generator.py
    python main_generator.py --input custom_topics.csv --output custom_output/
"""

import argparse
import logging
import os
import re
import sys
import time
# Phase 36: Removed unused ProcessPoolExecutor, as_completed

# Đảm bảo project root nằm trong sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TOPICS_CSV, OUTPUT_DIR, LLM_CONFIG, setup_logging
from modules.csv_reader import read_topics
from modules.topic_analyzer import analyze_topic
from modules.serp_competitor_analyzer import analyze_serp, analyze_competitors
from modules.query_network import analyze_query_network, get_network_clusters
from modules.context_builder import build_prompt_context, _fallback_prompt_context
from modules.content_brief_builder import (
    build_brief,
    refine_paa_questions_for_project,
    _apply_koray_micro_postprocess,
)
from modules.markdown_exporter import export_to_markdown
from modules.keyword_identity import review_keyword_identity

logger = logging.getLogger(__name__)


def _llm_ready_reason() -> str:
    api_key = str(LLM_CONFIG.get("api_key") or "").strip()
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        return "LLM unavailable: missing API key"
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return "LLM unavailable: missing openai library"
    return ""


def _format_network_for_log(network_data) -> str:
    """Serialize query_network dict thành chuỗi hiển thị cho CSV/GSheet."""
    if not network_data or not isinstance(network_data, dict):
        return ""
    cluster_list = get_network_clusters(network_data)
    kws = []
    for c in cluster_list[:3]:
        if isinstance(c, dict):
            cluster_keywords = c.get("keywords") or c.get("variants") or []
            if isinstance(cluster_keywords, list):
                kws.extend(cluster_keywords[:3])
    if kws:
        return ", ".join(kws)
    total = network_data.get("total_fetched", 0)
    return f"{total} keywords fetched" if total else ""


def _format_context_vectors_for_log(context_data) -> str:
    """Serialize context vectors data thành chuỗi hiển thị cho CSV/GSheet."""
    if not context_data:
        return ""
    if isinstance(context_data, str):
        return context_data[:500]
    if isinstance(context_data, dict):
        # build_prompt_context returns {"context_vectors": [...], "contextual_structure": [...]}
        guidelines = context_data.get("contextual_structure", context_data.get("guidelines", []))
        if guidelines and isinstance(guidelines, list):
            return " | ".join(str(g) for g in guidelines[:5])
        vectors = context_data.get("context_vectors", [])
        if vectors and isinstance(vectors, list):
            preview = []
            for item in vectors[:5]:
                if isinstance(item, dict):
                    preview.append(str(item.get("question", item.get("intent", ""))).strip())
                else:
                    preview.append(str(item))
            preview = [p for p in preview if p]
            if preview:
                return " | ".join(preview)
        return str(context_data)[:500]
    return str(context_data)[:500]


def _fallback_smart_ngrams_for_log(topic: str, analysis: dict, project=None) -> str:
    """Derive a deterministic n-gram preview when competitor n-grams are unavailable."""
    tokens = []
    seen = set()

    def _push(text: str):
        if not text:
            return
        cleaned = re.sub(r"[\W_]+", " ", str(text).lower()).strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        tokens.append(cleaned)

    def _push_words(text: str):
        if not text:
            return
        cleaned = re.sub(r"[\W_]+", " ", str(text).lower()).strip()
        parts = [p for p in cleaned.split() if len(p) >= 3]
        if not parts:
            return
        for i in range(min(3, len(parts))):
            window = " ".join(parts[i:i + 2]) if i + 1 < len(parts) else parts[i]
            if window and window not in seen:
                seen.add(window)
                tokens.append(window)

    base_items = [
        topic,
        analysis.get("central_entity", ""),
        getattr(project, "industry", "") if project else "",
        getattr(project, "main_products", "") if project else "",
        getattr(project, "target_customers", "") if project else "",
    ]
    for item in base_items:
        _push(item)
        _push_words(item)

    entity_attrs = analysis.get("entity_attributes", {})
    if isinstance(entity_attrs, dict):
        for key in list(entity_attrs.keys())[:8]:
            _push(key)
            _push_words(key)

    for rel in (analysis.get("related_topics", []) or [])[:6]:
        _push(rel)
        _push_words(rel)

    if not tokens:
        tokens = [re.sub(r"\s+", " ", topic).strip().lower()]

    return ", ".join(tokens[:15])


def _fallback_macro_context_for_log(topic: str, analysis: dict, project=None) -> str:
    """Build a richer macro context string without depending on LLM output."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    intent = analysis.get("search_intent", {}) if isinstance(analysis, dict) else {}
    intent_type = ""
    intent_subtype = ""
    target_user = ""
    if isinstance(intent, dict):
        intent_type = str(intent.get("type", "") or "").strip()
        intent_subtype = str(intent.get("subtype", "") or "").strip()
    else:
        intent_type = str(intent or "").strip()

    target_user = str(analysis.get("target_user", "") or "").strip()
    industry = str(getattr(project, "industry", "") or "").strip()
    main_products = str(getattr(project, "main_products", "") or "").strip()
    target_customers = str(getattr(project, "target_customers", "") or "").strip()
    scope_parts = [p for p in [main_products, industry] if p]
    scope = " trong ".join(scope_parts) if len(scope_parts) >= 2 else (scope_parts[0] if scope_parts else topic)
    macro_context = f"{scope} va cac thuoc tinh, quan he, boi canh va nhu cau tim kiem lien quan den {entity}"

    lines = [
        f"- **Central Entity**: {entity}",
        f"- **Macro Context**: {macro_context}",
        f"- **Search Intent Type**: {intent_type or 'informational'}",
        f"- **Intent Subtype**: {intent_subtype or 'What-is'}",
        f"- **Nguoi dung muc tieu**: {target_user or target_customers or 'Nguoi dung tim hieu thong tin lien quan den chu de nay'}",
    ]
    return "\n".join(lines)


def _fallback_top_competitors_for_log(topic: str, analysis: dict, project=None) -> list[str]:
    """Build a non-empty competitor preview when SERP URLs are unavailable."""
    competitor_brands = []
    if project is not None:
        raw = str(getattr(project, "competitor_brands", "") or "").strip()
        if raw:
            competitor_brands = [c.strip() for c in raw.split(",") if c.strip()]

    if competitor_brands:
        return competitor_brands[:3]

    related = [str(t).strip() for t in (analysis.get("related_topics", []) or []) if str(t).strip()]
    if related:
        return [f"[Offline theme] {t}" for t in related[:3]]

    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    return [
        f"[Offline reference] {entity} - guide",
        f"[Offline reference] {entity} - how-to",
        f"[Offline reference] {entity} - cost/risk",
    ]


def _fallback_content_gaps_for_log(topic: str, analysis: dict, project=None) -> list[str]:
    """Generate generic evidence requests when SERP gaps are empty."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    industry = str(getattr(project, "industry", "") or "").strip()
    related = [str(t).strip() for t in (analysis.get("related_topics", []) or []) if str(t).strip()]

    if related:
        return related[:5]

    context_label = industry or "ngu canh hien tai"
    return [
        f"{entity} duoc hieu nhu the nao trong {context_label}",
        f"SERP hien tai con thieu du kien nao de giai thich {entity}",
        f"Nguoi doc can kiem chung diem nao truoc khi tin vao noi dung ve {entity}",
        f"Source context cua brand co the bo sung goc nhin nao cho {entity}",
        f"Can them fact, vi du hoac nguon nao de brief ve {entity} du tin cay",
    ]

def _fallback_context_vectors_for_log(topic: str, analysis: dict, project=None) -> str:
    """Fallback text for Context Vectors & Guidelines when context_builder is empty."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    industry = str(getattr(project, "industry", "") or "").strip()
    main_products = str(getattr(project, "main_products", "") or "").strip()
    scope = main_products or industry or topic
    questions = [
        f"{entity} la gi trong {scope}?",
        f"{entity} hoat dong nhu the nao trong {scope}?",
        f"Nhung yeu to can xem xet khi viet ve {entity} la gi?",
        f"{entity} co nhung luu y va rui ro nao can nho?",
        f"Lam sao trien khai {entity} thanh noi dung phu hop source context?",
    ]
    guidelines = [
        "Nguyen tac 1: Tra loi truc tiep ngay sau heading dau tien.",
        "Nguyen tac 2: Uu tien cau hoi co entity + attribute ro rang.",
        f"Nguyen tac 3: Giữ topical border theo {scope}.",
        "Nguyen tac 4: Brand/hotline/CTA chi dat o [SUPP] hoac cuoi bai.",
    ]
    return " | ".join(questions[:5] + guidelines[:4])


def _fallback_query_network_for_log(topic: str, analysis: dict, project=None) -> str:
    """Fallback semantic network preview when query-network output is unavailable."""
    entity = str(analysis.get("central_entity") or topic or "").strip() or topic
    industry = str(getattr(project, "industry", "") or "").strip()
    main_products = str(getattr(project, "main_products", "") or "").strip()
    target_customers = str(getattr(project, "target_customers", "") or "").strip()
    seed_phrases = [
        entity,
        f"{entity} la gi",
        f"{entity} nhu the nao",
        f"{entity} lien quan den dieu gi",
        f"{entity} can luu y gi",
    ]
    if industry:
        seed_phrases.extend([
            f"{entity} trong {industry}",
            f"{industry} va {entity}",
        ])
    if main_products:
        seed_phrases.append(f"{entity} va {main_products}")
    if target_customers:
        seed_phrases.append(f"{entity} cho {target_customers}")
    return ", ".join([p for p in seed_phrases if p][:10])


def _normalize_paa_list(raw_paa) -> list[str]:
    """Normalize PAA payloads into a clean list of question strings."""
    if raw_paa is None:
        return []

    if isinstance(raw_paa, dict):
        raw_paa = raw_paa.get("questions") or raw_paa.get("paa_questions") or raw_paa.get("items") or []

    if isinstance(raw_paa, str):
        text = raw_paa.strip()
        if not text:
            return []
        try:
            import json as _json
            parsed = _json.loads(text)
            return _normalize_paa_list(parsed)
        except Exception:
            lines = [line.strip().lstrip("-•* ").strip() for line in text.splitlines()]
            raw_paa = [line for line in lines if line]

    if not isinstance(raw_paa, (list, tuple, set)):
        raw_paa = [raw_paa]

    questions = []
    for item in raw_paa:
        if item is None:
            continue
        if isinstance(item, dict):
            nested = item.get("questions") or item.get("paa_questions") or item.get("items")
            if nested:
                questions.extend(_normalize_paa_list(nested))
                continue
            value = item.get("question") or item.get("text") or item.get("title") or item.get("value") or ""
        else:
            value = str(item)

        value = str(value).strip()
        if not value:
            continue
        if value.startswith("{") and value.endswith("}"):
            try:
                import json as _json
                parsed = _json.loads(value)
                nested = _normalize_paa_list(parsed)
                if nested:
                    questions.extend(nested)
                    continue
            except Exception:
                pass

        cleaned = value.replace("\r", "\n").strip()
        if "\n" in cleaned and len(cleaned.splitlines()) > 1:
            for line in cleaned.splitlines():
                line = line.strip().lstrip("-•* ").strip()
                line = line.lstrip("0123456789.-) \t").strip()
                if line:
                    questions.append(line)
        else:
            questions.append(cleaned.lstrip("0123456789.-) \t").strip())

    deduped = []
    seen = set()
    for q in questions:
        if q:
            key = q.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(q)
    return deduped


def _run_isolated_postprocessor(brief: dict, headings: list, project=None) -> None:
    """
    Phase 46 fix: Isolated SAPO rebuild + NAP injection.
    Runs AFTER Koray block so it doesn't crash the main pipeline.
    Fixes Sapo=0 words when Agent 3 fails or exception swallowed the post-processor.

    Logic:
    1. Rebuild SAPO if micro_briefing[0] is empty or <80 words.
       Rebuild uses: entity definition + brand context + H2 listing.
    2. Inject NAP into last [SUPP] bridge.
    3. No recalculate here (already done in Koray block).
    """
    import logging as _pp_log
    _pp = _pp_log.getLogger(__name__)

    micro = brief.get("micro_briefing", [])
    if not micro:
        _pp.warning("  [ISOLATED-PP] micro_briefing is empty — cannot post-process.")
        return

    # Normalize dict wrapper {"items": [...]} if Agent 3 used json_object format
    if isinstance(micro, dict):
        brief["micro_briefing"] = micro.get("items", []) if "items" in micro else list(micro.values())
        micro = brief["micro_briefing"]

    if not micro:
        _pp.warning("  [ISOLATED-PP] micro_briefing empty after normalization.")
        return

    brand_name = getattr(project, "brand_name", "") or ""
    geo_kw = getattr(project, "geo_keywords", "") or ""
    hotline = getattr(project, "hotline", "") or ""
    industry = getattr(project, "industry", "") or ""
    topic = brief.get("topic", brief.get("central_entity", ""))

    # ── 1. SAPO REBUILD ──────────────────────────────────────────────
    sapo_item = micro[0] if micro else {}
    old_sapo_snippet = str(sapo_item.get("snippet", "")).strip()
    old_words = len(old_sapo_snippet.split())

    should_rebuild = old_words < 80 or old_words == 0
    if should_rebuild:
        entity_name = brief.get("central_entity", topic)

        # Build definition sentence
        definition = ""
        entity_attrs = brief.get("entity_attributes", {})
        if isinstance(entity_attrs, dict):
            for key in ["Định nghĩa", "definition", "Mô tả", "Description"]:
                if key in entity_attrs:
                    definition = str(entity_attrs[key]).strip()
                    break
        elif isinstance(entity_attrs, list):
            for attr in entity_attrs:
                if isinstance(attr, str) and "định nghĩa" in attr.lower():
                    definition = attr.strip()
                    break

        if not definition:
            if old_sapo_snippet:
                first_sent = old_sapo_snippet.split(".")[0].strip()
                definition = first_sent + "." if first_sent else ""
            if not definition:
                definition = f"{entity_name} là chủ đề quan trọng trong ngành."

        # Build brand sentence
        brand_sentence = ""
        if brand_name:
            if industry:
                geo_part = geo_kw.split(",")[0].strip() if geo_kw else "Việt Nam"
                brand_sentence = (
                    f"{brand_name} — đơn vị chuyên {industry.lower()} tại {geo_part} "
                    f"— biên soạn bài phân tích dưới đây dựa trên dữ liệu thực tế từ quá trình cung ứng."
                )
            else:
                brand_sentence = f"{brand_name} biên soạn nội dung dưới đây dựa trên kinh nghiệm thực tế trong ngành."

        # Build H2 listing
        h2_listing = ""
        if headings:
            h2_names = [
                h.get("text", "").replace("[MAIN] ", "").replace("[SUPP] ", "").strip()
                for h in headings if h.get("level") == "H2"
            ]
            if h2_names:
                h2_listing = "Bài viết phân tích lần lượt: " + ", ".join(h2_names[:6]) + "."

        # Compose new SAPO
        sapo_parts = [p for p in [definition, brand_sentence, h2_listing] if p]
        new_sapo = " ".join(sapo_parts)

        # Cap at 156 words (Koray tolerance max)
        try:
            from modules.constants import SAPO_FULL_SCORE_MAX
            cap = SAPO_FULL_SCORE_MAX
        except ImportError:
            cap = 156
        words = new_sapo.split()
        if len(words) > cap:
            new_sapo = " ".join(words[:cap])
            # Cut at nearest sentence boundary
            last_punct = max(
                new_sapo.rfind("."),
                new_sapo.rfind("!"),
                new_sapo.rfind("?"),
            )
            if last_punct > cap * 0.65:
                new_sapo = new_sapo[:last_punct + 1]

        new_words = len(new_sapo.split())

        # Apply only if new SAPO is better (longer and >= 80 words)
        if new_words >= 80 and (new_words > old_words or old_words < 80):
            sapo_item["snippet"] = new_sapo
            # Also set h2 label if missing
            if not sapo_item.get("h2"):
                sapo_item["h2"] = "SAPO (Đoạn mở đầu)"
            if not sapo_item.get("intent"):
                sapo_item["intent"] = "Giới thiệu tổng quan bài viết"
            _pp.info(
                "  [ISOLATED-PP] SAPO rebuilt: %d → %d words (old was %d).",
                old_words, new_words, old_words
            )

    # ── 2. NAP INJECTION ──────────────────────────────────────────────
    if brand_name and len(micro) > 1:
        # Find last [SUPP] or last micro item
        last_supp_idx = -1
        for i in range(len(micro) - 1, 0, -1):
            h2_text = str(micro[i].get("h2", ""))
            if "[SUPP]" in h2_text or i == len(micro) - 1:
                last_supp_idx = i
                break

        if last_supp_idx > 0:
            bridge = str(micro[last_supp_idx].get("bridge", "")).strip()
            if brand_name.lower() not in bridge.lower():
                nap_parts = [f"Để được tư vấn chọn {topic} phù hợp, liên hệ {brand_name}"]
                if hotline:
                    nap_parts.append(f"qua Hotline/Zalo: {hotline}")
                if geo_kw:
                    geo_part = geo_kw.split(",")[0].strip()
                    nap_parts.append(f"(phục vụ khu vực {geo_part})")
                nap_sentence = ". ".join(nap_parts) + "."
                micro[last_supp_idx]["bridge"] = (bridge + "\n\n" + nap_sentence).strip()
                _pp.info("  [ISOLATED-PP] NAP injected into micro[%d].", last_supp_idx)

    brief["micro_briefing"] = micro


def _process_single_topic(
    topic: str,
    enable_serp: bool,
    enable_network: bool,
    enable_context: bool,
    enable_linking: bool,
    methodology: str = "auto",
    output_dir: str = "output_ui",
    total_steps: int = 1,
    glog=None,  # Optional GSheetLogger instance
    csv_log=None, # Optional Local CsvLogger instance
    csv_row: int = -1, # Row index for Local CsvLogger
    project=None,  # Phase 33: Project/Brand Profile
    gsheet_row: int = -1,  # Optional pre-resolved Google Sheet row
) -> str:
    """
    Xử lý 1 topic duy nhất qua toàn bộ pipeline.

    Hàm này được tách ra để hỗ trợ multi-processing (ProcessPoolExecutor).
    Mỗi worker sẽ gọi hàm này độc lập cho 1 topic.

    Returns:
        Đường dẫn file .md được tạo, hoặc None nếu lỗi.
    """
    if glog and glog.is_connected and gsheet_row <= 0:
        gsheet_row = glog.start_keyword(topic)

    def _abort_with_error(message: str):
        logger.error("[BLOCKED] %s", message)
        if glog and gsheet_row > 0:
            try:
                glog.update_cell(gsheet_row, "Full Content Brief", f"BLOCKED: {message}")
                glog.set_status(gsheet_row, "Error")
            except Exception as exc:
                logger.warning("[BLOCKED] Failed to update GSheet status: %s", exc)
        if csv_log and csv_row >= 0:
            try:
                csv_log.update_cell(csv_row, "Full Content Brief", f"BLOCKED: {message}")
                csv_log.set_status(csv_row, "Error", message=message)
            except Exception as exc:
                logger.warning("[BLOCKED] Failed to update CSV status: %s", exc)
        return None

    llm_precheck = _llm_ready_reason()
    if llm_precheck:
        return _abort_with_error(llm_precheck)

    # Step 2: SERP + Competitor analysis (TRƯỚC analyze_topic để có data cho Dynamic Heading)
    serp_data = None
    competitor_data = None
    serp_error_msg = ""
    if enable_serp:
        # Phase 4.2: SERP failure is degraded, not fatal.
        # Keep the pipeline running with explicit placeholder payloads so
        # downstream analysis/logging can distinguish failure from "SERP off".
        try:
            serp_data = analyze_serp(topic)

            # Guard: đảm bảo serp_data là dict.
            if isinstance(serp_data, str):
                logger.warning("serp_data là string thay vì dict: %s", serp_data[:200])
                serp_data = {}
            if not isinstance(serp_data, dict):
                serp_data = {}

            if serp_data.get("top_urls"):
                competitor_data = analyze_competitors(serp_data["top_urls"], topic)

                # Guard: đảm bảo competitor_data là dict.
                if isinstance(competitor_data, str):
                    logger.warning("competitor_data là string: %s", competitor_data[:200])
                    competitor_data = {}
                if not isinstance(competitor_data, dict):
                    competitor_data = {}
            else:
                serp_error_msg = (
                    f"SERP crawl cho '{topic}': không tìm thấy URL đối thủ trên Google. "
                    "Chạy tiếp ở degraded mode để batch không dừng."
                )
                logger.warning("[SERP-DEGRADED] %s", serp_error_msg)
        except Exception as serp_exc:
            serp_error_msg = f"SERP lỗi cho '{topic}': {serp_exc}. Chạy tiếp ở degraded mode."
            logger.warning("[SERP-DEGRADED] %s", serp_error_msg)
            serp_data = None
            competitor_data = None

    if serp_error_msg and enable_serp:
        serp_data = {
            "status": "serp_failed",
            "error": serp_error_msg,
            "top_urls": [],
            "organic_results": [],
            "people_also_ask": [],
            "related_searches": [],
            "serp_source": "Unavailable",
            "source_confidence": "none",
        }
        competitor_data = {
            "status": "serp_failed",
            "error": serp_error_msg,
            "competitors": [],
            "common_headings": [],
            "information_gain": {},
        }

    # Step 3: Phân tích topic (Dynamic Heading Construction dùng SERP + Competitor data)
    analysis = analyze_topic(
        topic,
        serp_data=serp_data,
        competitor_data=competitor_data,
    )
    
    # ── GUARD: đảm bảo analysis là dict ──
    if isinstance(analysis, str):
        logger.warning("analysis là string: %s", analysis[:200])
        analysis = {}
    if not isinstance(analysis, dict):
        analysis = {}

    # ── LOG GSHEET & LOCAL CSV PHẦN 1: PHÂN TÍCH ──
    intent_val = analysis.get("search_intent", {})
    if isinstance(intent_val, str):
        pass  # Đã là string, giữ nguyên
    elif isinstance(intent_val, dict):
        intent_val = intent_val.get("type", "")
    else:
        intent_val = ""
    serp_intent_decision = serp_data.get("intent_decision", {}) if isinstance(serp_data, dict) else {}
    if isinstance(serp_intent_decision, dict):
        serp_selected_intent = str(serp_intent_decision.get("selected_intent", "") or "").strip()
        if serp_selected_intent:
            intent_val = serp_selected_intent

    urls_val = []
    if competitor_data and isinstance(competitor_data, dict):
        competitors_list = competitor_data.get("competitors", [])
        if isinstance(competitors_list, list):
            urls_val = [c.get("url", "") for c in competitors_list if isinstance(c, dict)]
    if not urls_val:
        urls_val = _fallback_top_competitors_for_log(topic, analysis, project)
            
    paa_raw_val = _normalize_paa_list(serp_data.get("people_also_ask", [])) if serp_data else []
    if not paa_raw_val:
        paa_raw_val = _normalize_paa_list(analysis.get("suggested_questions", []))
    paa_refined_val = refine_paa_questions_for_project(
        topic=topic,
        entity=analysis.get("central_entity") or topic,
        project=project,
        raw_questions=paa_raw_val,
        intent=str(intent_val) if intent_val else "",
        competitor_data=competitor_data,
    )
    paa_val = paa_refined_val.get("faq_questions", []) or paa_raw_val
        
    gaps_val = []
    if competitor_data and isinstance(competitor_data, dict):
        # FIX: rare_headings nằm TRONG information_gain, KHÔNG phải top-level
        info_gain = competitor_data.get("information_gain", {})
        if isinstance(info_gain, dict):
            gaps_val = info_gain.get("rare_headings", [])
        if not isinstance(gaps_val, list):
            gaps_val = []
        # Đảm bảo toàn bộ items trong gaps là string (có thể là dict hoặc tuple)
        gaps_val = [str(g) if not isinstance(g, str) else g for g in gaps_val]
    if not gaps_val:
        related_topics = analysis.get("related_topics", []) if isinstance(analysis, dict) else []
        if isinstance(related_topics, list) and related_topics:
            gaps_val = [str(t) for t in related_topics[:5] if str(t).strip()]
        if not gaps_val:
            gaps_val = _fallback_content_gaps_for_log(topic, analysis, project)
            
    ngrams_val = []
    if competitor_data and isinstance(competitor_data, dict):
        raw_ngrams = competitor_data.get("ngrams_2", [])[:5]
        if not isinstance(raw_ngrams, list):
            raw_ngrams = []
        # FIX: ngrams_2 trả về List[Tuple[str, int]], ví dụ [("keyword chính", 5)]
        # Phải convert sang string TRƯỚC khi truyền vào logger
        for item in raw_ngrams:
            if isinstance(item, tuple) and len(item) >= 2:
                ngrams_val.append(f"{item[0]} ({item[1]})")
            elif isinstance(item, str):
                ngrams_val.append(item)
            else:
                ngrams_val.append(str(item))
    # Step 3: Log vào GSheet cột A-K
    # Chuyển đổi ngrams_val thành string format chuẩn list cho GSheet
    ngrams_str = ""
    if isinstance(ngrams_val, dict) and "all_clean" in ngrams_val:
        entities = ", ".join(ngrams_val.get("entity", [])[:10])
        actions = ", ".join(ngrams_val.get("action", [])[:10])
        ngrams_str = f"Entities/Noun: {entities}\nActions/Verb: {actions}"
    elif isinstance(ngrams_val, list):
        clean_list = [n[0] if isinstance(n, tuple) else str(n) for n in ngrams_val][:15]
        ngrams_str = ", ".join(clean_list)
    else:
        ngrams_str = str(ngrams_val) if ngrams_val else ""

    if glog and gsheet_row > 0:
        glog.log_analysis_results(
            row=gsheet_row,
            intent=str(intent_val), top_urls=urls_val, paa=paa_val, gaps=gaps_val, ngrams=ngrams_str
        )
    if csv_log and csv_row >= 0:
        csv_log.log_analysis_results(
            row_idx=csv_row,
            intent=str(intent_val), top_urls=urls_val, paa=paa_val, gaps=gaps_val, ngrams=ngrams_val
        )

    # Step 4: Semantic Keyword Network
    network_data = None
    if enable_network:
        entity_for_net = analysis.get("central_entity") or topic  # Phase 36: guard KeyError
        network_data = analyze_query_network(entity_for_net, project=project)

    # Step 4.5: Keyword Identity Review
    keyword_identity_data = None
    if project and enable_serp and serp_data:
        try:
            keyword_identity_data = review_keyword_identity(
                topic,
                project=project,
                current_urls=serp_data.get("top_urls", []),
                search_fn=analyze_serp,
            )
            logger.info(
                "  [IDENTITY] relation=%s | canonical=%s | score=%s",
                keyword_identity_data.get("relation", ""),
                keyword_identity_data.get("canonical_root", ""),
                keyword_identity_data.get("score", ""),
            )
        except Exception as identity_err:
            logger.warning("  [IDENTITY] Review failed: %s", identity_err)

    # Step 5: Context Builder
    context_data = None
    if enable_context:
        context_data = build_prompt_context(topic, competitor_data or {}, project=project)
    else:
        context_data = _fallback_prompt_context(topic, competitor_data or {}, project=project)
    if not context_data:
        context_data = _fallback_prompt_context(topic, competitor_data or {}, project=project)
    if isinstance(context_data, dict) and context_data.get("error"):
        has_fallback_context = bool(context_data.get("context_vectors")) and bool(context_data.get("contextual_structure"))
        if has_fallback_context:
            logger.warning("  [CONTEXT] LLM error but fallback context is usable. Continue with fallback: %s", context_data.get("error"))
            context_data["llm_error"] = context_data.pop("error")
        else:
            return _abort_with_error(str(context_data.get("error")))

    # Step 7: Internal Linking — MOVED AFTER build_brief (V5.3 fix)
    # Linking is now generated INSIDE build_brief using enriched headings + keyword_clusters.
    # The old call here used raw headings without clusters, bypassing V5.3/V5.4 fixes.
    linking_data = None  # Will be populated from brief["internal_linking"] after build_brief

    # Step 7.5: Xác định Methodology
    # Phase 2.2: Normalize intent string trước khi dùng (single source of truth)
    from modules.article_writer import auto_detect_methodology, get_methodology_prompt
    from modules.intent import normalize_intent
    if methodology == "auto":
        intent_str = normalize_intent(str(intent_val) if intent_val else "informational")
        methodology = auto_detect_methodology(intent_str, topic)
    methodology_prompt = get_methodology_prompt(methodology)
    logger.info("  [METHODOLOGY] Sử dụng: %s", methodology)

    # ── Phase 35: Chained Context Flow (Generate Semantic Contexts BEFORE Brief) ──
    macro_context = ""
    eav_table = ""
    try:
        from modules.koray_analyzer import generate_macro_context, generate_eav_table
        from config import LLM_CONFIG
        api_key_check = LLM_CONFIG.get("api_key", "")
        _ak_short = (api_key_check[:12] + "...") if api_key_check else "(empty)"
        logger.info("  [CHAINED-CONTEXT] api_key from LLM_CONFIG: '%s'", _ak_short)
        macro_context = generate_macro_context(topic, analysis, project, api_key_check)
        eav_table = generate_eav_table(topic, analysis, competitor_data, project, api_key_check)
        logger.info("  [CHAINED-CONTEXT] Generated Macro Context and EAV Table.")
    except Exception as koray_err:
        logger.warning("  [CHAINED-CONTEXT] Lỗi sinh Macro/EAV: %s", koray_err)
        return _abort_with_error(f"LLM unavailable: {koray_err}")
    if not str(macro_context or "").strip():
        return _abort_with_error("LLM unavailable: empty Macro Context")
    if not str(eav_table or "").strip():
        return _abort_with_error("LLM unavailable: empty EAV Table")
    if "[LLM_FALLBACK]" in str(macro_context):
        return _abort_with_error("LLM unavailable: Macro Context fallback triggered")
    if "[LLM_FALLBACK]" in str(eav_table):
        return _abort_with_error("LLM unavailable: EAV Table fallback triggered")

    # Step 8: Xây dựng Content Brief
    brief = build_brief(
        topic, analysis,
        serp_data=serp_data,
        competitor_data=competitor_data,
        network_data=network_data,
        context_data=context_data,
        linking_data=linking_data,
        methodology_prompt=methodology_prompt,
        project=project,  # Phase 33
        macro_context=macro_context, # Phase 35 Chained Context Flow
        eav_table=eav_table, # Phase 35 Chained Context Flow
    )
    brief["eav_table"] = eav_table # Lưu lại dùng cho Phase 33 Logging
    brief["seed_keyword"] = topic
    if keyword_identity_data:
        brief["keyword_identity"] = keyword_identity_data
        brief["semantic_anchor"] = keyword_identity_data.get("semantic_anchor", topic)
        brief["semantic_expansion_keywords"] = keyword_identity_data.get("semantic_expansion_keywords", [])
        brief["canonical_topic"] = topic
    else:
        brief["semantic_anchor"] = topic
        brief["semantic_expansion_keywords"] = []
        brief["canonical_topic"] = topic

    # Phase 4.2: Validate required keys từ build_brief trước khi dùng
    _required_brief_keys = ["heading_structure", "micro_briefing", "title_tag", "central_entity"]
    for _key in _required_brief_keys:
        if _key not in brief:
            logger.warning(
                "[BUILD-BRIEF] Key '%s' missing from brief. Setting empty default.",
                _key,
            )
            brief[_key] = [] if _key == "heading_structure" or _key == "micro_briefing" else ""

    # V18: Build display strings cho CSV/GSheet logging (BUG-2A/2B fix)
    brief["query_network_str"] = _format_network_for_log(brief.get("query_network"))
    if not brief["query_network_str"]:
        brief["query_network_str"] = _format_network_for_log(network_data) or _fallback_query_network_for_log(topic, analysis, project)
    if not brief.get("context_builder"):
        brief["context_builder"] = context_data
    brief["context_vectors_str"] = _format_context_vectors_for_log(brief.get("context_builder") or context_data)
    brief["smart_ngrams_str"] = ngrams_str or _fallback_smart_ngrams_for_log(topic, analysis, project)
    brief.setdefault("column_audit_report", "")

    # ── Phase 33: GENERATE VÀ LOG CÁC CỘT KORAY CÒN LẠI (L-P) ──
    try:
        from modules.koray_analyzer import (
            extract_main_supp_split,
            generate_source_context_alignment,
            calculate_quality_score,
            generate_fs_paa_map,
            generate_outline_readiness_report,
        )
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        headings_for_koray = brief.get("heading_structure", [])
        paa_questions = _normalize_paa_list(brief.get("faq_questions", [])) if brief.get("faq_questions") else paa_val

        # ── LLM-based ──
        fs_paa_map = ""
        fs_paa_map = generate_fs_paa_map(topic, paa_questions, headings_for_koray, project, api_key)
        if not str(fs_paa_map or "").strip():
            return _abort_with_error("LLM unavailable: empty FS/PAA Map")
        if "[LLM_FALLBACK]" in str(fs_paa_map):
            return _abort_with_error("LLM unavailable: FS/PAA Map fallback triggered")

        # ── Rule-based (luôn chạy) ──
        _ = extract_main_supp_split(headings_for_koray)
        source_context_alignment = generate_source_context_alignment(brief, project)
        quality_score = calculate_quality_score(brief, headings_for_koray, project)
        brief["koray_quality_score_md"] = quality_score
        readiness_report = generate_outline_readiness_report(brief, headings_for_koray, project)
        
        # Nhét vào brief để markdown_exporter có thể đọc
        brief["source_context_alignment"] = source_context_alignment
        brief["koray_outline_readiness"] = readiness_report

        # ══════════════════════════════════════════════════════════════
        # RULE-BASED POST-PROCESSOR (Koray-compliant)
        # Chạy SAU LLM, TRƯỚC markdown export. Enforce 3 ràng buộc:
        #   1. SAPO đúng công thức Koray (≥80 từ, brand tự nhiên)
        #   2. NAP/hotline trong [SUPP] bridge cuối
        #   3. Recalculate score
        # ══════════════════════════════════════════════════════════════
        postprocess_applied = False
        micro = brief.get("micro_briefing", [])

        # Lấy thông tin Source Context từ project
        brand_name = ""
        geo_kw = ""
        hotline = ""
        industry = ""
        if project:
            brand_name = getattr(project, "brand_name", "") or ""
            geo_kw = getattr(project, "geo_keywords", "") or ""
            hotline = getattr(project, "hotline", "") or ""
            __usp = getattr(project, "usp", "") or ""
            industry = getattr(project, "industry", "") or ""

        # ── 1. KORAY-COMPLIANT SAPO BUILDER ──
        if micro and len(micro) > 0:
            entity_name = brief.get("central_entity", topic)
            h2_names = [
                h["text"].replace("[MAIN] ", "").replace("[SUPP] ", "")
                for h in headings_for_koray if h.get("level") == "H2"
            ]

            # Câu 1: Định nghĩa Main Entity (lấy từ entity_attributes nếu có)
            entity_attrs = brief.get("entity_attributes", {})
            definition = ""
            if isinstance(entity_attrs, dict):
                # Tìm attribute "Định nghĩa" hoặc description
                for key in ["Định nghĩa", "definition", "Mô tả"]:
                    if key in entity_attrs:
                        definition = str(entity_attrs[key])
                        break
            if isinstance(entity_attrs, list):
                for attr in entity_attrs:
                    if isinstance(attr, str) and "định nghĩa" in attr.lower():
                        definition = attr
                        break

            if not definition:
                # Fallback: dùng snippet gốc từ LLM (câu đầu tiên)
                original_snippet = str(micro[0].get("snippet", ""))
                first_sentences = original_snippet.split(".")
                definition = first_sentences[0].strip() + "." if first_sentences else f"{entity_name} là chủ đề quan trọng trong ngành."

            # Câu 2: Source Context declaration (tự nhiên, KHÔNG boilerplate)
            source_ctx_sentence = ""
            if brand_name:
                if industry:
                    source_ctx_sentence = f"{brand_name} — đơn vị chuyên {industry.lower()} tại {geo_kw.split(',')[0].strip() if geo_kw else 'Việt Nam'} — biên soạn bài phân tích dưới đây dựa trên dữ liệu thực tế từ quá trình vận hành."
                else:
                    source_ctx_sentence = f"{brand_name} biên soạn nội dung dưới đây dựa trên kinh nghiệm thực tế trong ngành."

            # Câu 3-4: Liệt kê H2 theo ĐÚNG THỨ TỰ
            h2_listing = ""
            if h2_names:
                h2_listing = "Bài viết phân tích lần lượt: " + ", ".join(h2_names[:6]) + "."

            # Ghép SAPO hoàn chỉnh
            sapo_parts = [p for p in [definition, source_ctx_sentence, h2_listing] if p]
            new_sapo = " ".join(sapo_parts)

            # Fix: Cap SAPO tại SAPO_FULL_SCORE_MAX (156 từ) — tránh over-enforce như log (166 từ)
            from modules.constants import SAPO_FULL_SCORE_MAX
            if len(new_sapo.split()) > SAPO_FULL_SCORE_MAX:
                new_sapo = " ".join(new_sapo.split()[:SAPO_FULL_SCORE_MAX])
                # Cắt câu tại dấu câu gần nhất
                last_punct = max(new_sapo.rfind("."), new_sapo.rfind("!"), new_sapo.rfind("?"))
                if last_punct > SAPO_FULL_SCORE_MAX * 0.7:  # giữ nguyên nếu cắt quá sớm
                    new_sapo = new_sapo[:last_punct + 1]

            # Chỉ thay nếu SAPO mới dài hơn SAPO cũ hoặc SAPO cũ < 80 từ
            old_sapo = str(micro[0].get("snippet", ""))
            old_words = len(old_sapo.split())
            new_words = len(new_sapo.split())

            if old_words < 80 or (brand_name and brand_name.lower() not in old_sapo.lower()):
                micro[0]["snippet"] = new_sapo
                postprocess_applied = True
                logger.info("  [POST-PROCESS] SAPO rebuilt (Koray formula): %d từ (was %d, cap=%d).",
                            new_words, old_words, SAPO_FULL_SCORE_MAX)

        # ── 2. NAP INJECTION IN LAST [SUPP] BRIDGE ──
        if micro and len(micro) > 1 and brand_name:
            last_supp_idx = -1
            for i in range(len(micro) - 1, 0, -1):
                h2_name = str(micro[i].get("h2", ""))
                if "[SUPP]" in h2_name or i == len(micro) - 1:
                    last_supp_idx = i
                    break

            if last_supp_idx > 0:
                bridge_text = str(micro[last_supp_idx].get("bridge", ""))
                if brand_name.lower() not in bridge_text.lower():
                    # NAP block tự nhiên, không phải tagline
                    nap_parts = [f"Để được tư vấn chọn {entity_name} phù hợp, liên hệ {brand_name}"]
                    if hotline:
                        nap_parts.append(f"qua Hotline/Zalo: {hotline}")
                    if geo_kw:
                        nap_parts.append(f"(phục vụ khu vực {geo_kw.split(',')[0].strip()})")
                    nap_sentence = " ".join(nap_parts) + "."
                    micro[last_supp_idx]["bridge"] = bridge_text.rstrip() + "\n\n" + nap_sentence
                    postprocess_applied = True
                    logger.info("  [POST-PROCESS] NAP injected into [SUPP] #%d.", last_supp_idx)

        # ── 3. RECALCULATE scores (chạy luôn, không phụ thuộc postprocess_applied) ──
        if postprocess_applied:
            brief["micro_briefing"] = micro
        try:
            quality_score = calculate_quality_score(brief, headings_for_koray, project)
            source_context_alignment = generate_source_context_alignment(brief, project)
            brief["koray_quality_score_md"] = quality_score
            readiness_report = generate_outline_readiness_report(brief, headings_for_koray, project)
            brief["source_context_alignment"] = source_context_alignment
            brief["koray_outline_readiness"] = readiness_report
            from modules.koray_analyzer import generate_column_audit_report
            brief["column_audit_report"] = generate_column_audit_report(brief, project)
            logger.info("  [POST-PROCESS] Recalculated Quality Score + Alignment.")
        except Exception as recalc_err:
            logger.warning("  [POST-PROCESS] Recalculate score failed (non-fatal): %s", recalc_err)

    except Exception as koray_err:
        logger.warning("  [KORAY] Lỗi sinh Koray columns: %s", koray_err)
        return _abort_with_error(f"LLM unavailable: {koray_err}")

    # ── CHUẨN BỊ LOG BRIEF ──
    headings_str = "\n".join([f"{h['level']}: {h['text']}" for h in brief.get("heading_structure", [])])

    # V5.3 FIX: Use internal_linking from build_brief (enriched headings + keyword clusters)
    # instead of the old early linking_data that used raw headings.
    links_str = ""
    brief_linking = brief.get("internal_linking", {})
    if isinstance(brief_linking, dict) and brief_linking.get("outbound_nodes"):
        links_str = "\n".join([f"Node: {n.get('topic', '')} ({n.get('anchor', '')})" for n in brief_linking.get("outbound_nodes", [])])
    elif isinstance(brief_linking, list):
        # Fallback format: list of dicts with target_topic
        parts = []
        for item in brief_linking:
            if isinstance(item, dict):
                t = item.get("target_topic", item.get("topic", ""))
                a = item.get("anchor_text_suggestion", item.get("anchor", t))
                parts.append(f"Node: {t} ({a})")
        links_str = "\n".join(parts)
        
    # Step 9: Xuất file .md (Thực hiện SAU KHI RECHECK để đảm bảo MD chứa brief đã được fix)
    brief["_project_context"] = project
    filepath, part1_md, part2_md = export_to_markdown(brief, output_dir)

    # ── LOG FINAL BRIEF VÀO GSHEET & LOCAL CSV ──
    error_msg = ""

    if glog and gsheet_row > 0:
        glog.log_brief_results(
            row=gsheet_row,
            headings_outline=headings_str,
            internal_links=links_str,
            full_brief_md=part2_md,
        )
        glog.log_koray_columns(
            row=gsheet_row,
            macro_context=macro_context,
            eav_table=eav_table,
            fs_paa_map=fs_paa_map,
            source_context_alignment=source_context_alignment,
            quality_score=quality_score,
        )
        # Bổ sung ghi log Cột Q, R
        glog.log_semantic_strategy_columns(
            row=gsheet_row,
            query_network=brief.get("query_network_str", ""),
            context_vectors=brief.get("context_vectors_str", "")
        )
        final_status = "Done"
        if error_msg:
            final_status = "Error"
        elif glog and getattr(glog, 'has_error', False):
            final_status = "Done (Sheet Error)"
        glog.set_status(gsheet_row, final_status if final_status != "Done (Sheet Error)" else "Done")
    else:
        final_status = "Done"
        if error_msg:
            final_status = "Error"
        elif glog and getattr(glog, 'has_error', False):
            final_status = "Done (Sheet Error)"

    if csv_log and csv_row >= 0:
        csv_log.log_brief_results(
            row_idx=csv_row,
            headings_outline=headings_str,
            internal_links=links_str,
            full_brief_md=part2_md,
        )
        csv_log.log_koray_columns(
            row_idx=csv_row,
            macro_context=macro_context,
            eav_table=eav_table,
            fs_paa_map=fs_paa_map,
            source_context_alignment=source_context_alignment,
            quality_score=quality_score,
        )
        csv_log.log_semantic_strategy_columns(
            row_idx=csv_row,
            query_network=brief.get("query_network_str", ""),
            context_vectors=brief.get("context_vectors_str", "")
        )
        csv_log.set_status(csv_row, "Done" if final_status == "Done" else "Error", message=error_msg)




    return filepath


def generate_content_brief(
    topic: str,
    enable_serp: bool = False,
    enable_network: bool = False,
    enable_context: bool = False,
    enable_linking: bool = False,
    methodology: str = "auto",
    output_dir: str = "output_ui",
    project=None,
) -> str:
    """Public single-topic entrypoint for Streamlit app."""
    total_steps = 4
    if enable_serp:
        total_steps += 2
    if enable_network:
        total_steps += 1
    if enable_context:
        total_steps += 1
    if enable_linking:
        total_steps += 1

    os.makedirs(output_dir, exist_ok=True)
    return _process_single_topic(
        topic=topic,
        enable_serp=enable_serp,
        enable_network=enable_network,
        enable_context=enable_context,
        enable_linking=enable_linking,
        methodology=methodology,
        output_dir=output_dir,
        total_steps=total_steps,
        glog=None,
        csv_log=None,
        csv_row=-1,
        project=project,
    )


def run_pipeline(
    input_csv: str,
    output_dir: str,
    enable_serp: bool = False,
    enable_network: bool = False,
    enable_context: bool = False,
    enable_linking: bool = False,
    workers: int = 1,
) -> None:
    """
    Chạy pipeline Content Brief Generator tuần tự.

    Pipeline flow:
        1. Đọc topics từ CSV
        2. Phân tích từng topic (topic_analyzer)
        3. [SERP] Phân tích SERP Google (nếu --serp)
        4. [SERP] Phân tích đối thủ (nếu --serp)
        5. [NETWORK] Phân nhóm từ khóa với LLM (nếu --network)
        6. [CONTEXT] Build Context Vectors & Structure từ LLM (nếu --context)
        7. [LINKING] Đọc Topical Map tạo liên kết nội bộ (nếu --linking)
        8. Xây dựng Content Brief (content_brief_builder)
        9. Xuất file .md (markdown_exporter)

    Args:
        input_csv: Đường dẫn tới file CSV chứa danh sách topics.
        output_dir: Thư mục đầu ra cho các file .md.
        enable_serp: Bật phân tích SERP + đối thủ (mặc định: False).
        enable_network: Bật phân tích Semantic Query Network (mặc định: False).
        enable_context: Bật Context Builder từ LLM (yêu cầu --serp, mặc định: False).
        enable_linking: Bật tự động xây dựng Internal Links từ topical_map.csv (mặc định: False).
    """
    logger.info("=" * 60)
    logger.info("CONTENT BRIEF GENERATOR - PIPELINE START")
    logger.info("=" * 60)
    logger.info("Input:   %s", input_csv)
    logger.info("Output:  %s", output_dir)
    logger.info("SERP:    %s", "✓ Enabled" if enable_serp else "✗ Disabled")
    logger.info("NETWORK: %s", "✓ Enabled" if enable_network else "✗ Disabled")
    logger.info("CONTEXT: %s", "✓ Enabled" if enable_context else "✗ Disabled")
    logger.info("LINKING: %s", "✓ Enabled" if enable_linking else "✗ Disabled")
    logger.info("-" * 60)

    start_time = time.time()
    
    # Tính tổng số step cho logging
    total_steps = 4 
    if enable_serp:
        total_steps += 2
    if enable_network:
        total_steps += 1
    if enable_context:
        total_steps += 1
    if enable_linking:
        total_steps += 1

    # ── STEP 1: Đọc topics từ CSV ──
    logger.info("[Step 1/%s] Đọc danh sách topics...", total_steps)
    topics = read_topics(input_csv)
    logger.info("  → Tổng cộng: %d topics", len(topics))

    # ── STEP 2-N: Xử lý từng topic ──
    generated_files = []
    errors = []

    if workers > 1 and len(topics) > 1:
        # ── Multi-processing: RAISED — disables logging silently ──
        # ⚠️  Bug Fix Phase 1: glog và csv_log = None trong parallel mode → không log gì cả.
        # Raise error để user biết. Dùng workers=1 hoặc chạy qua app.py.
        logger.error(
            "[MULTI-PROCESS] workers=%d ENABLED but GSheet+CSV logging is DISABLED "
            "in parallel mode. Results will not be logged. Use workers=1 or app.py.",
            workers,
        )
        raise NotImplementedError(
            "Multi-processing mode (workers>1) disables GSheet and CSV logging. "
            "The current CLI pipeline silently skips all logging in parallel mode. "
            "To fix: use workers=1 (sequential) or run batch via app.py (which handles logging). "
            "TODO: Implement a multiprocessing-safe logging queue to re-enable parallel mode."
        )
    else:
        # ── Tuần tự (single-process, mặc định) ──
        for i, topic_data in enumerate(topics, 1):
            topic = topic_data["topic"]
            logger.info("-" * 40)
            logger.info("[%d/%d] Đang xử lý: '%s'", i, len(topics), topic)

            try:
                filepath = _process_single_topic(
                    topic, enable_serp, enable_network, enable_context, enable_linking,
                    "auto", output_dir, total_steps,
                    None, None, -1, None,
                )
                if filepath:
                    generated_files.append(filepath)
            except Exception as e:
                error_msg = f"Lỗi khi xử lý '{topic}': {str(e)}"
                logger.error("  ✗ %s", error_msg)
                errors.append(error_msg)

    # ── SUMMARY REPORT ──
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY REPORT")
    logger.info("=" * 60)
    logger.info("Tổng topics:     %d", len(topics))
    logger.info("Thành công:      %d", len(generated_files))
    logger.info("Thất bại:        %d", len(errors))
    logger.info("SERP analysis:   %s", "✓" if enable_serp else "✗")
    logger.info("Network cluster: %s", "✓" if enable_network else "✗")
    logger.info("Context builder: %s", "✓" if enable_context else "✗")
    logger.info("Internal links:  %s", "✓" if enable_linking else "✗")
    logger.info("Thời gian:       %.2f giây", elapsed)
    logger.info("Output dir:      %s", os.path.abspath(output_dir))

    if errors:
        logger.warning("")
        logger.warning("CÁC LỖI GẶP PHẢI:")
        for err in errors:
            logger.warning("  - %s", err)

    if generated_files:
        logger.info("")
        logger.info("FILES ĐÃ TẠO:")
        for f in generated_files:
            logger.info("  ✓ %s", os.path.basename(f))

    logger.info("=" * 60)
    logger.info("PIPELINE HOÀN TẤT")
    logger.info("=" * 60)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Content Brief Generator - Tạo Content Brief từ danh sách topics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python main_generator.py
  python main_generator.py --input my_topics.csv --output briefs/
        """,
    )
    parser.add_argument(
        "--input", "-i",
        default=TOPICS_CSV,
        help=f"Đường dẫn file CSV chứa topics (mặc định: {TOPICS_CSV})",
    )
    parser.add_argument(
        "--output", "-o",
        default=OUTPUT_DIR,
        help=f"Đường dẫn thư mục đầu ra cho file .md (mặc định: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--serp", "-s",
        action="store_true",
        default=False,
        help="Bật phân tích SERP Google + đối thủ cạnh tranh (Playwright)",
    )
    parser.add_argument(
        "--network", "-n",
        action="store_true",
        default=False,
        help="Bật phân tích Query Network & LLM Clustering (Cần OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--context", "-c",
        action="store_true",
        default=False,
        help="Bật sinh Context Vectors & Structure (Yêu cầu bật kèm --serp, cần OPENAI_API_KEY)",
    )
    parser.add_argument(
        "--linking", "-l",
        action="store_true",
        default=False,
        help="Bật tự động đề xuất Internal Linking dựa trên topical_map.csv",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="Số lượng workers cho multi-processing (mặc định: 1 = tuần tự)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # CẢNH BÁO MẠNH nếu không bật --serp
    if not args.serp:
        print("=" * 60)
        print("⚠️  CẢNH BÁO: Bạn đang chạy KHÔNG CÓ --serp")
        print("   Output sẽ chỉ chứa dữ liệu rule-based (templates)")
        print("   KHÔNG có dữ liệu SERP/đối thủ thực tế từ Google.")
        print("   → Khuyến nghị: python main_generator.py --serp")
        print("=" * 60)

    # Context Builder bắt buộc phải có thông tin đối thủ từ SERP
    if args.context and not args.serp:
        print("LỖI: --context yêu cầu phải chạy cùng --serp (-s -c) để thu thập URL đối thủ. Hủy chạy.")
        sys.exit(1)

    # Thiết lập environment variable nếu user truyền key ảo cho test
    if (args.network or args.context) and LLM_CONFIG.get("api_key") == "YOUR_API_KEY_HERE":
        logger.warning("CẢNH BÁO: OPENAI_API_KEY chưa được set. Module '--network'/ '--context' có thể bị lỗi ở bước LLM.")

    # Thiết lập logging
    setup_logging()

    # Chạy pipeline
    try:
        run_pipeline(
            args.input, 
            args.output, 
            enable_serp=args.serp,
            enable_network=args.network,
            enable_context=args.context,
            enable_linking=args.linking,
            workers=args.workers,
        )
    except FileNotFoundError as e:
        logger.error("FILE ERROR: %s", e)
        sys.exit(1)
    except ValueError as e:
        logger.error("DATA ERROR: %s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("\nPipeline bị hủy bởi người dùng.")
        sys.exit(130)

if __name__ == "__main__":
    main()
