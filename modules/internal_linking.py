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
    VD: "Thép tấm là gì" ≈ "Tổng quan về thép tấm"
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
        (["thông số", "kỹ thuật", "đặc điểm"], f"thông số {base_lower}"),
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

    Returns:
        Dict: {"role", "cluster", "outbound_nodes", "inbound_topics", "tree_view"}
    """
    # ── Ưu tiên 1: Topical Map CSV (V9 Fix) ──
    csv_result = _try_topics_csv(current_topic)
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
    """
    outbound_nodes = []
    seen_topics = set()
    
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
        or True  # Inbound là gợi ý cho bài KHÁC link VỀ bài này, nên OK
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

def _try_topics_csv(current_topic: str) -> Optional[Dict]:
    """
    Đọc file topics.csv (Cột 1: Keyword) để lấy danh sách bài viết thực tế trong Topical Map.
    Chọn ra 5 bài viết liên quan nhất làm internal link.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(base_dir, "topics.csv")
    db_path = os.path.join(base_dir, "database_v2.csv")
    
    # Ưu tiên đọc topics.csv trước, nếu không thử database_v2.csv
    file_to_read = None
    if os.path.exists(csv_path):
        file_to_read = csv_path
    elif os.path.exists(db_path):
        file_to_read = db_path
        
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
        for t in set(topics):
            # FIX 4: Thay threshold=0.7 -> 0.92 để chỉ loại bản thân, KHÔNG loại bài anh em liên quan
            if _is_self_reference(t, current_topic, threshold=0.92):
                continue
            candidates.append(t)
            
        if not candidates:
            return None
            
        # Tính điểm liên quan (Jaccard word overlap)
        current_words = set(current_topic.lower().split())
        
        def score_word_overlap(target: str) -> float:
            target_words = set(target.lower().split())
            if not target_words or not current_words:
                return 0.0
            overlap = len(target_words & current_words)
            return overlap / len(target_words | current_words)
            
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

