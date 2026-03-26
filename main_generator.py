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
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

# Đảm bảo project root nằm trong sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TOPICS_CSV, OUTPUT_DIR, LLM_CONFIG, setup_logging
from modules.csv_reader import read_topics
from modules.topic_analyzer import analyze_topic
from modules.serp_competitor_analyzer import analyze_serp, analyze_competitors
from modules.query_network import analyze_query_network
from modules.context_builder import build_prompt_context
from modules.content_brief_builder import build_brief
from modules.markdown_exporter import export_to_markdown

logger = logging.getLogger(__name__)


def _format_network_for_log(network_data) -> str:
    """Serialize query_network dict thành chuỗi hiển thị cho CSV/GSheet."""
    if not network_data or not isinstance(network_data, dict):
        return ""
    clusters = network_data.get("clusters", {})
    cluster_list = clusters.get("clusters", []) if isinstance(clusters, dict) else []
    if not isinstance(cluster_list, list):
        cluster_list = []
    kws = []
    for c in cluster_list[:3]:
        if isinstance(c, dict):
            kws.extend(c.get("keywords", [])[:3])
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
        return str(context_data)[:500]
    return str(context_data)[:500]


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
) -> str:
    """
    Xử lý 1 topic duy nhất qua toàn bộ pipeline.

    Hàm này được tách ra để hỗ trợ multi-processing (ProcessPoolExecutor).
    Mỗi worker sẽ gọi hàm này độc lập cho 1 topic.

    Returns:
        Đường dẫn file .md được tạo, hoặc None nếu lỗi.
    """
    gsheet_row = -1
    if glog and glog.is_connected:
        gsheet_row = glog.start_keyword(topic)
    # Step 2: SERP + Competitor analysis (TRƯỚC analyze_topic để có data cho Dynamic Heading)
    serp_data = None
    competitor_data = None
    if enable_serp:
        serp_data = analyze_serp(topic)
        
        # ── GUARD: đảm bảo serp_data là dict ──
        if isinstance(serp_data, str):
            logger.warning("serp_data là string thay vì dict: %s", serp_data[:200])
            serp_data = {}
        if not isinstance(serp_data, dict):
            serp_data = {}
            
        if serp_data.get("top_urls"):
            competitor_data = analyze_competitors(serp_data["top_urls"], topic)
            
            # ── GUARD: đảm bảo competitor_data là dict ──
            if isinstance(competitor_data, str):
                logger.warning("competitor_data là string: %s", competitor_data[:200])
                competitor_data = {}
            if not isinstance(competitor_data, dict):
                competitor_data = {}
        else:
            raise RuntimeError(
                f"SERP crawl thất bại cho '{topic}': không tìm thấy URL đối thủ nào trên Google. "
                "Pipeline DỪNG để tránh sinh nội dung giả (hallucination). "
                "Kiểm tra kết nối mạng hoặc thử lại sau."
            )

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
        
    urls_val = []
    if competitor_data and isinstance(competitor_data, dict):
        competitors_list = competitor_data.get("competitors", [])
        if isinstance(competitors_list, list):
            urls_val = [c.get("url", "") for c in competitors_list if isinstance(c, dict)]
            
    paa_val = serp_data.get("people_also_ask", []) if serp_data else []
    if not isinstance(paa_val, list) or len(paa_val) == 0:
        paa_val = analysis.get("suggested_questions", [])
        
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
            
    ngrams_val = []
    if competitor_data and isinstance(competitor_data, dict):
        raw_ngrams = competitor_data.get("ngrams_2", [])[:5]
        if not isinstance(raw_ngrams, list):
            raw_ngrams = []
        # FIX: ngrams_2 trả về List[Tuple[str, int]] ví dụ [("thép tấm", 5)]
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
        entity_for_net = analysis["central_entity"]
        network_data = analyze_query_network(entity_for_net)

    # Step 5: Context Builder
    context_data = None
    if enable_context:
        if not competitor_data or not competitor_data.get("competitors"):
            context_data = {"error": "Lack of competitor data"}
        else:
            context_data = build_prompt_context(topic, competitor_data)

    # Step 7: Internal Linking — MOVED AFTER build_brief (V5.3 fix)
    # Linking is now generated INSIDE build_brief using enriched headings + keyword_clusters.
    # The old call here used raw headings without clusters, bypassing V5.3/V5.4 fixes.
    linking_data = None  # Will be populated from brief["internal_linking"] after build_brief

    # Step 7.5: Xác định Methodology
    from modules.article_writer import auto_detect_methodology, get_methodology_prompt
    if methodology == "auto":
        intent_str = str(intent_val) if intent_val else "informational"
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
        if api_key_check and api_key_check != "YOUR_API_KEY_HERE":
            macro_context = generate_macro_context(topic, analysis, project, api_key_check)
            eav_table = generate_eav_table(topic, analysis, competitor_data, project, api_key_check)
            logger.info("  [CHAINED-CONTEXT] Generated Macro Context and EAV Table.")
    except Exception as koray_err:
        logger.warning("  [CHAINED-CONTEXT] Lỗi sinh Macro/EAV: %s", koray_err)

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

    # V18: Build display strings cho CSV/GSheet logging (BUG-2A/2B fix)
    brief["query_network_str"] = _format_network_for_log(brief.get("query_network"))
    brief["context_vectors_str"] = _format_context_vectors_for_log(brief.get("context_builder"))

    # ── Phase 33: GENERATE VÀ LOG CÁC CỘT KORAY CÒN LẠI (L-P) ──
    try:
        from modules.koray_analyzer import (
            extract_main_supp_split,
            generate_source_context_alignment,
            calculate_quality_score,
            generate_fs_paa_map,
        )
        from config import LLM_CONFIG
        api_key = LLM_CONFIG.get("api_key", "")
        headings_for_koray = brief.get("heading_structure", [])
        paa_questions = serp_data.get("people_also_ask", []) if serp_data else []
        if not paa_questions or (isinstance(paa_questions, list) and len(paa_questions) == 0):
            paa_questions = analysis.get("suggested_questions", [])

        # ── LLM-based ──
        fs_paa_map = ""
        if api_key:
            fs_paa_map = generate_fs_paa_map(topic, paa_questions, headings_for_koray, project, api_key)

        # ── Rule-based (luôn chạy) ──
        _ = extract_main_supp_split(headings_for_koray)
        source_context_alignment = generate_source_context_alignment(brief, project)
        quality_score = calculate_quality_score(brief, headings_for_koray, project)
        
        # Nhét vào brief để markdown_exporter có thể đọc
        brief["source_context_alignment"] = source_context_alignment

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
                    source_ctx_sentence = f"{brand_name} — đơn vị chuyên {industry.lower()} tại {geo_kw.split(',')[0].strip() if geo_kw else 'Việt Nam'} — biên soạn bài phân tích dưới đây dựa trên dữ liệu thực tế từ quá trình cung ứng và thi công."
                else:
                    source_ctx_sentence = f"{brand_name} biên soạn nội dung dưới đây dựa trên kinh nghiệm thực tế trong ngành."

            # Câu 3-4: Liệt kê H2 theo ĐÚNG THỨ TỰ
            h2_listing = ""
            if h2_names:
                h2_listing = "Bài viết phân tích lần lượt: " + ", ".join(h2_names[:6]) + "."

            # Ghép SAPO hoàn chỉnh
            sapo_parts = [p for p in [definition, source_ctx_sentence, h2_listing] if p]
            new_sapo = " ".join(sapo_parts)

            # Chỉ thay nếu SAPO mới dài hơn SAPO cũ hoặc SAPO cũ < 80 từ
            old_sapo = str(micro[0].get("snippet", ""))
            old_words = len(old_sapo.split())
            new_words = len(new_sapo.split())

            if old_words < 80 or (brand_name and brand_name.lower() not in old_sapo.lower()):
                micro[0]["snippet"] = new_sapo
                postprocess_applied = True
                logger.info("  [POST-PROCESS] SAPO rebuilt (Koray formula): %d từ (was %d).", new_words, old_words)

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

        # ── 3. RECALCULATE scores ──
        if postprocess_applied:
            brief["micro_briefing"] = micro
            quality_score = calculate_quality_score(brief, headings_for_koray, project)
            source_context_alignment = generate_source_context_alignment(brief, project)
            brief["source_context_alignment"] = source_context_alignment
            logger.info("  [POST-PROCESS] Recalculated Quality Score + Alignment.")

        # (LLM-based koray columns đã chạy ở trên)

    except Exception as koray_err:
        logger.warning("  [KORAY] Lỗi sinh Koray columns: %s", koray_err)
        macro_context = eav_table = fs_paa_map = source_context_alignment = quality_score = ""

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
    __full_md = ""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                f.read()
        except Exception:
            pass

    if glog and gsheet_row > 0:
        glog.log_brief_results(
            row=gsheet_row, headings_outline=headings_str,
            internal_links=links_str, full_brief_md=part2_md,
            data_analysis_md=part1_md
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
        glog.set_status(gsheet_row, "Done")
        
    final_status = "Done"
    if glog and getattr(glog, 'has_error', False):
        final_status = "Done (Sheet Error)"

    if csv_log and csv_row >= 0:
        csv_log.log_brief_results(
            row_idx=csv_row, headings_outline=headings_str,
            internal_links=links_str, full_brief_md=part2_md,
            data_analysis_md=part1_md
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
        csv_log.set_status(csv_row, final_status)




    return filepath


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
        # ── Đa luồng (multi-processing) ──
        logger.info("[MULTI-PROCESS] Sử dụng %d workers cho %d topics", workers, len(topics))
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_topic = {}
            for i, topic_data in enumerate(topics, 1):
                topic = topic_data["topic"]
                future = executor.submit(
                    _process_single_topic,
                    topic, enable_serp, enable_network, enable_context, enable_linking,
                    "auto", output_dir, total_steps,
                    glog, csv_log, -1, None,
                )
                future_to_topic[future] = (i, topic)

            for future in as_completed(future_to_topic):
                idx, topic = future_to_topic[future]
                try:
                    filepath = future.result()
                    if filepath:
                        generated_files.append(filepath)
                except Exception as e:
                    error_msg = f"Lỗi khi xử lý '{topic}': {str(e)}"
                    logger.error("  ✗ %s", error_msg)
                    errors.append(error_msg)
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
