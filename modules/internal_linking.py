# -*- coding: utf-8 -*-
"""
internal_linking.py - Phase 10: Intelligent Linking Architecture.

Topical Cluster Model:
- Auto-detect ROOT/NODE from H2 headings
- Anchor text variation (exact, semantic, question)
- Loop prevention (fuzzy dedup, anti-self)
- Tree view output format
"""

import csv
import os
import re
import logging
from typing import Dict, List, Optional
from difflib import SequenceMatcher

try:
    from config import TOPICAL_MAP_CSV
except ImportError:
    TOPICAL_MAP_CSV = ""

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════
#  FUZZY MATCHING (Chống vòng lặp)
# ══════════════════════════════════════════════

def _similarity(a: str, b: str) -> float:
    """Tính độ tương đồng giữa 2 chuỗi (0.0 → 1.0)."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _is_self_reference(candidate: str, current_topic: str, threshold: float = 0.80) -> bool:
    """
    Kiểm tra link có trỏ về chính bài viết hiện tại không.

    Dùng fuzzy matching > threshold để bắt các biến thể gần giống.
    VD: "Entity A là gì" ≈ "Tổng quan về Entity A"
    """
    return _similarity(candidate, current_topic) >= threshold


# ══════════════════════════════════════════════
#  ANCHOR TEXT VARIATION
# ══════════════════════════════════════════════

def _generate_anchor_variants(node_text: str, main_keyword: str) -> Dict[str, str]:
    """
    Sinh 3 biến thể Anchor Text tự nhiên cho 1 link.

    Nguyên tắc:
    1. Exact anchor: Tên node được reorder tự nhiên (không thêm prefix lạ)
    2. Semantic anchor: Verb tự nhiên + topic (như người thực sự search)
    3. Question anchor: Câu hỏi ngắn gọn tự nhiên (chỉ dùng "là gì" nếu node là định nghĩa)

    TUYỆT ĐỐI KHÔNG dùng: "tại sao nên", "khi nào cần", "định nghĩa X", "kiểm tra X" nếu không tự nhiên.
    """
    # Clean node text — bỏ [MAIN]/[SUPP] prefix và suffix sau "—"
    clean = node_text.strip()
    clean = re.sub(r'^\[(MAIN|SUPP)\]\s*', '', clean)
    base = clean.split("—")[0].strip() if "—" in clean else clean
    base = base.strip(":").strip()
    base_lower = base.lower()

    # --- EXACT ANCHOR: Dạng tự nhiên ngắn nhất ---
    # Nếu heading dạng "Entity: Attribute" → "attribute entity"
    if ":" in base_lower:
        parts = base_lower.split(":", 1)
        entity_part = parts[0].strip()
        attr_part = parts[1].strip()
        exact = f"{attr_part} {entity_part}".strip()
    else:
        exact = base_lower

    # --- SEMANTIC ANCHOR: verb + topic ---
    semantic = None
    VERB_MAPPING = [
        (["phân loại", "loại", "các loại"], f"phân loại {base_lower}"),
        (["tiêu chuẩn", "quy chuẩn"], f"tiêu chuẩn {base_lower}"),
        (["ứng dụng", "sử dụng", "dùng"], f"ứng dụng {base_lower}"),
        (["giá", "báo giá", "chi phí"], f"giá {base_lower}"),
        (["so sánh", "khác nhau", "vs"], f"so sánh {base_lower}"),
        (["hướng dẫn", "cách", "quy trình"], f"hướng dẫn {base_lower}"),
        (["thuoc tinh"], f"thuoc tinh {base_lower}"),
    ]
    for keywords, result in VERB_MAPPING:
        if any(kw in base_lower for kw in keywords):
            semantic = result
            break
    if not semantic:
        semantic = f"tìm hiểu {base_lower}"

    # --- QUESTION ANCHOR: Câu hỏi ngắn, tự nhiên ---
    IS_DEFINITION = ["là gì", "định nghĩa", "khái niệm", "là loại"]
    is_def = any(sig in base_lower for sig in IS_DEFINITION)

    if is_def:
        if "là gì" not in base_lower and "là sao" not in base_lower:
            question = f"{base_lower} là gì?"
        else:
            question = base_lower + "?" if not base_lower.endswith("?") else base_lower
    elif any(sig in base_lower for sig in ["so sánh", "khác nhau"]):
        question = f"{base_lower} như thế nào?"
    elif any(sig in base_lower for sig in ["quy trình", "cách", "hướng dẫn"]):
        question = f"{base_lower} như thế nào?"
    elif any(sig in base_lower for sig in ["giá", "chi phí"]):
        question = f"{base_lower} bao nhiêu?"
    else:
        # FIX 5: Thay 'vì sao cần X?' bằng 'X có ưu điểm gì?' tự nhiên hơn
        question = f"{base_lower} có ưu điểm gì?"

    if exact == semantic:
        semantic = f"tìm hiểu {exact}" if "tìm hiểu" not in exact else f"bài viết về {exact}"
    
    if question == exact or question == semantic:
        question = f"{exact} mang lại lợi ích gì?"

    return {
        "exact": exact,
        "semantic": semantic,
        "question": question,
        "primary": exact  # V6: Primary is now exact (shortest/most natural)
    }


def _pick_anchor(variants: Dict[str, str], source_h2: str = "") -> str:
    """
    Chọn anchor text.
    V11-R4: Nếu source_h2 chứa [SUPP] → dùng question format (Rule 6 Koray).
    Mặc định: 'primary' — anchor ngắn nhất và tự nhiên nhất.
    """
    if source_h2 and "[SUPP]" in source_h2.upper():
        return variants.get("question", variants.get("primary", variants.get("exact", "")))
    return variants.get("primary", variants.get("exact", ""))


# ══════════════════════════════════════════════
#  AUTO-DETECT ROOT & NODES
# ══════════════════════════════════════════════

def _extract_nodes_from_headings(headings: List[Dict], current_topic: str) -> List[Dict]:
    """
    Trích xuất NODE con từ danh sách H2 headings.

    Logic:
    - Mỗi H2 (trừ FAQ, Information Gain) → 1 NODE tiềm năng
    - Loại bỏ self-reference
    - Sinh anchor variants cho mỗi node

    Returns:
        List[{"node_topic": str, "source_h2": str, "anchors": {...}}]
    """
    nodes = []
    skip_patterns = ["faq", "câu hỏi"]

    for h in headings:
        if h["level"] != "H2":
            continue

        text = h["text"].strip()
        text_lower = text.lower()

        # KB RULE: TUYỆT ĐỐI KHÔNG chèn Internal Link trong [MAIN] section
        # Chỉ sinh link từ [SUPP] headings
        if text.startswith("[MAIN]"):
            continue

        # Bỏ qua heading đặc biệt
        if any(pat in text_lower for pat in skip_patterns):
            continue

        # Bỏ qua self-reference
        if _is_self_reference(text, current_topic):
            continue

        # Lấy base topic (bỏ phần enrichment sau "—")
        base = text.split("—")[0].strip()

        # Sinh slug cho topic con
        node_topic = base

        # Sinh anchor variants
        anchors = _generate_anchor_variants(text, current_topic)

        nodes.append({
            "node_topic": node_topic,
            "source_h2": text,
            "anchors": anchors,
            "selected_anchor": _pick_anchor(anchors),
        })

    return nodes


# ══════════════════════════════════════════════
#  MAIN PUBLIC API
# ══════════════════════════════════════════════

def build_internal_links(
    current_topic: str,
    headings: List[Dict] = None,
    niche: str = "general",
    keyword_clusters: List[str] = None,
    topical_map_csv: str = "",  # Phase 37: project-specific topical map
) -> Optional[Dict]:
    """
    Phase 10: Intelligent Linking Architecture (V9).

    Ưu tiên 1: Topical Map (topics.csv hoặc database_v2.csv)
    Ưu tiên 2: Semantic Clusters (từ keyword_clusters truyền vào)
    Ưu tiên 3: Auto-detect từ H2 headings (Dynamic - fallback cuối)

    Args:
        current_topic: Chủ đề bài viết hiện tại.
        headings: Danh sách heading đã enriched.
        niche: Lĩnh vực (food_health, tech_gadget...).
        keyword_clusters: Danh sách các topic semantic phụ trợ.
        topical_map_csv: Đường dẫn project-specific topics.csv.

    Returns:
        Dict: {"role", "cluster", "outbound_nodes", "inbound_topics", "tree_view"}
    """
    # ── Ưu tiên 1: Topical Map CSV (V9 Fix, Phase 37 project-aware) ──
    csv_result = _try_topics_csv(current_topic, topical_map_csv, niche=niche)
    if csv_result and csv_result.get("outbound_nodes"):
        logger.info("  [LINKING] Loaded internal links directly from topics.csv topical map")
        return csv_result

    # ── Ưu tiên 2: Semantic Clusters (V5.3 - Avoid internal H2 loops) ──
    if keyword_clusters:
        cluster_result = _build_from_clusters(keyword_clusters, current_topic, niche)
        if cluster_result and cluster_result.get("outbound_nodes"):
            return cluster_result
        logger.info("  [LINKING] Cluster không có outbound hợp lệ → fallback xuống H2 Dynamic")

    # ── Ưu tiên 3: Auto-detect từ H2 (Fallback cuối) ──
    if not headings:
        logger.warning("  [LINKING] Không có heading data. Bỏ qua linking.")
        return None

    return _build_from_headings(headings, current_topic, niche)

def _build_from_clusters(
    keyword_clusters: List[str],
    current_topic: str,
    niche: str,
) -> Optional[Dict]:
    """
    Xây dựng Internal Links từ Keyword Clusters bổ trợ (V5.3).

    Thay vì link đến chính H2 của bài viết, ta link đến các topic/cluster liên quan.
    Phase 38: Filter theo industry keywords từ niche để tránh link sai ngành.
    """
    outbound_nodes = []
    seen_topics = set()

    # Phase 38: Build industry keyword set từ niche để filter
    if niche and niche not in ("general", ""):
        STOPWORDS = {
            "và", "hoặc", "của", "trong", "cho", "để", "theo", "với", "từ", "là",
            "một", "các", "được", "giao", "dịch", "hàng", "hóa", "phái", "sinh",
            "tư", "vấn", "đầu", "tư", "môi", "giới", "bao", "gồm",
            "chiến", "lược", "phòng", "hộ", "rủi", "ro", "giá", "nhà",
            "doanh", "nghiệp", "hệ", "sinh", "thái", "mxv",
        }
        niche_words = niche.lower().split()
        industry_keywords = {
            w for w in niche_words
            if len(w) > 3 and w not in STOPWORDS
        }
    else:
        industry_keywords = set()

    current_words = set(current_topic.lower().split())

    # Lấy tối đa 5 clusters an toàn
    safe_clusters = [c for c in keyword_clusters if c and isinstance(c, str)]

    for topic in safe_clusters:
        topic_lower = topic.lower().strip()

        # Bỏ qua từ khóa quá ngắn hoặc bị trùng
        if len(topic_lower) < 3 or topic_lower in seen_topics:
            continue

        # Anti-self check (Không link về chính topic hiện tại)
        if _is_self_reference(topic, current_topic, threshold=0.7):
            continue

        # Phase 38: Filter theo industry keywords
        topic_words = set(topic_lower.split())
        industry_match = bool(industry_keywords & topic_words) if industry_keywords else True
        topic_overlap = bool(current_words & topic_words)
        if not industry_match and not topic_overlap:
            continue

        seen_topics.add(topic_lower)
        anchors = _generate_anchor_variants(topic, current_topic)
        outbound_nodes.append({
            "topic": topic.title(),  # Normalize case
            "anchor": _pick_anchor(anchors),
            "all_anchors": anchors,
            "source": "Semantic Cluster",
        })

    if not outbound_nodes:
        return None

    # Giới hạn 5 outbound nodes quan trọng nhất
    outbound_nodes = outbound_nodes[:5]

    # Inbound: Ai nên trỏ về bài ROOT?
    inbound_topics = [
        {"topic": node["topic"], "suggested_anchor": current_topic.lower()}
        for node in outbound_nodes
    ]

    # Tree View
    tree_lines = [f"ROOT: {current_topic} (from Target Clusters)"]
    for i, node in enumerate(outbound_nodes):
        connector = "├──" if i < len(outbound_nodes) - 1 else "└──"
        tree_lines.append(
            f"  {connector} NODE: {node['topic']} "
            f"(Anchor: \"{node['anchor']}\")"
        )

    result = {
        "role": "Root",
        "cluster": _detect_cluster_name(current_topic),
        "outbound_nodes": outbound_nodes,
        "inbound_topics": inbound_topics,
        "tree_view": tree_lines,
        "mode": "cluster",
    }

    logger.info(
        "  [LINKING] Cluster Mode: %d outbound nodes (Role: Root)",
        len(outbound_nodes),
    )
    return result

def _build_from_headings(
    headings: List[Dict],
    current_topic: str,
    niche: str,
) -> Dict:
    """
    Xây dựng Internal Links từ H2 headings (Dynamic mode).

    Bài hiện tại = ROOT. Mỗi H2 = NODE con.
    """
    # Trích xuất nodes từ H2
    nodes = _extract_nodes_from_headings(headings, current_topic)

    # ── Outbound: ROOT → NODEs ──
    outbound_nodes = []
    seen_topics = set()

    for node in nodes:
        topic_lower = node["node_topic"].lower()

        # Dedup
        if topic_lower in seen_topics:
            continue
        seen_topics.add(topic_lower)

        # Anti-self check
        if _is_self_reference(node["node_topic"], current_topic):
            continue

        outbound_nodes.append({
            "topic": node["node_topic"],
            "anchor": node["selected_anchor"],
            "all_anchors": node["anchors"],
            "source": f"H2: {node['source_h2']}",
        })

    # ── Inbound: Ai nên trỏ về bài ROOT? ──
    # Gợi ý = các NODEs nên link ngược về ROOT
    inbound_topics = []
    for node in outbound_nodes:
        inbound_topics.append({
            "topic": node["topic"],
            "suggested_anchor": current_topic.lower(),
        })

    # ── Loop Prevention: Đảm bảo không trùng ──
    outbound_set = {n["topic"].lower() for n in outbound_nodes}
    inbound_clean = [
        t for t in inbound_topics
        if t["topic"].lower() not in outbound_set
        # Inbound là gợi ý cho bài KHÁC link VỀ bài này
        # Chỉ lọc: loại bỏ topics nằm trong outbound_set (tránh circular)
        and t["topic"].lower() != current_topic.lower()
        # Giữ lại inbound topics khác bài hiện tại
    ]

    # ── Tree View ──
    tree_lines = [f"ROOT: {current_topic}"]
    for i, node in enumerate(outbound_nodes):
        connector = "├──" if i < len(outbound_nodes) - 1 else "└──"
        tree_lines.append(
            f"  {connector} NODE: {node['topic']} "
            f"(Anchor: \"{node['anchor']}\")"
        )

    result = {
        "role": "Root",
        "cluster": _detect_cluster_name(current_topic),
        "outbound_nodes": outbound_nodes,
        "inbound_topics": inbound_clean,
        "tree_view": tree_lines,
        "mode": "dynamic",
    }

    logger.info(
        "  [LINKING] Dynamic: %d outbound nodes, %d inbound topics (Role: Root)",
        len(outbound_nodes), len(inbound_clean),
    )
    return result


def _detect_cluster_name(topic: str) -> str:
    """Trích xuất tên cluster từ topic chính."""
    # Lấy entity chính (bỏ các modifier)
    clean = topic.strip()
    for prefix in ["hướng dẫn", "cách", "top", "review", "so sánh"]:
        if clean.lower().startswith(prefix):
            clean = clean[len(prefix):].strip()
    return clean.title() if clean else topic.title()


# ══════════════════════════════════════════════
#  CSV TOPICAL MAP (Legacy support)
# ══════════════════════════════════════════════

def _try_topics_csv(
    current_topic: str,
    project_topical_map_csv: str = "",
    niche: str = "general",
) -> Optional[Dict]:
    """
    Đọc file topics.csv (Cột 1: Keyword) để lấy danh sách bài viết thực tế trong Topical Map.
    Chọn ra 5 bài viết liên quan nhất làm internal link.

    Priority: project.topical_map_csv > global topics.csv > global database_v2.csv

    Phase 38 Fix: Lọc candidates theo industry keyword từ niche/industry để tránh
    gợi ý bài ngành khác.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Ưu tiên: project-specific topical_map_csv
    file_to_read = None
    if project_topical_map_csv and os.path.exists(project_topical_map_csv):
        file_to_read = project_topical_map_csv
    # Phase 38 Fix: KHÔNG fallback sang global topics.csv/database_v2.csv
    # vì global map thuộc ngành KHÁC → gây nhầm lẫn topic hiện tại
    # Nếu project không có topical_map_csv riêng → _try_topics_csv trả None
    # → caller sẽ dùng keyword_clusters thay vì stale topical map
        
    if not file_to_read:
        return None

    try:
        topics = []
        with open(file_to_read, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            _ = next(reader, None)
            for row in reader:
                if row and len(row) > 0 and row[0].strip():
                    topics.append(row[0].strip())
                    
        # Lọc các topic hợp lệ
        candidates = []

        # Phase 38 Fix: Build industry keyword set từ niche để filter.
        # Chỉ dùng từ khóa ngành đến từ source context hiện tại.
        industry_keywords = set()
        if niche and niche not in ("general", ""):
            # Extract meaningful words: loại bỏ stopwords, giữ noun/verb
            STOPWORDS = {
                "và", "hoặc", "của", "trong", "cho", "để", "theo", "với", "từ", "là",
                "một", "các", "được", "giao", "dịch", "hàng", "hóa", "phái", "sinh",
                "tư", "vấn", "đầu", "tư", "môi", "giới", "bao", "gồm",
                "chiến", "lược", "phòng", "hộ", "rủi", "ro", "giá", "nhà",
                "doanh", "nghiệp", "hệ", "sinh", "thái", "mxv",
            }
            niche_words = niche.lower().split()
            industry_keywords = {
                w for w in niche_words
                if len(w) > 3 and w not in STOPWORDS
            }
        # Tính điểm liên quan (Jaccard word overlap)
        current_words = set(current_topic.lower().split())

        for t in set(topics):
            # FIX 4: Thay threshold=0.7 -> 0.92 để chỉ loại bản thân, KHÔNG loại bài anh em liên quan
            if _is_self_reference(t, current_topic, threshold=0.92):
                continue
            # Phase 38: Nếu có industry_keywords, ưu tiên topic chứa ≥1 industry keyword
            # Nếu topic KHÔNG chứa industry keyword VÀ KHÔNG overlap với current_topic → loại
            topic_words = set(t.lower().split())
            industry_match = bool(industry_keywords & topic_words) if industry_keywords else True
            topic_overlap = bool(current_words & topic_words)
            if not industry_match and not topic_overlap:
                continue
            candidates.append(t)
            
        if not candidates:
            return None

        def score_word_overlap(target: str) -> float:
            target_words = set(target.lower().split())
            if not target_words or not current_words:
                return 0.0
            # Phase 38: Boost score nếu topic chứa industry keyword
            industry_bonus = 0.5 if (industry_keywords and (industry_keywords & target_words)) else 0.0
            overlap = len(target_words & current_words)
            return industry_bonus + (overlap / len(target_words | current_words))

        candidates.sort(key=score_word_overlap, reverse=True)
        selected = candidates[:5]
        
        outbound_nodes = []
        for t in selected:
            anchors = _generate_anchor_variants(t, current_topic)
            outbound_nodes.append({
                "topic": t,
                "anchor": _pick_anchor(anchors),
                "all_anchors": anchors,
                "source": "Topical Map (CSV)"
            })
            
        if not outbound_nodes:
            return None
            
        tree_lines = [f"ROOT: {current_topic} (từ Topical Map CSV)"]
        for i, node in enumerate(outbound_nodes):
            connector = "├──" if i < len(outbound_nodes) - 1 else "└──"
            tree_lines.append(f"  {connector} NODE: {node['topic']} (Anchor: \"{node['anchor']}\")")
            
        return {
            "role": "Root",
            "cluster": _detect_cluster_name(current_topic),
            "outbound_nodes": outbound_nodes,
            "inbound_topics": [{"topic": n["topic"], "suggested_anchor": current_topic.lower()} for n in outbound_nodes],
            "tree_view": tree_lines,
            "mode": "topical_map"
        }
    except Exception as e:
        logger.warning(f"  [LINKING] Lỗi đọc Topical Map CSV: {e}")
        return None

