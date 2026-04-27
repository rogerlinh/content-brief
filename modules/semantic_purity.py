# -*- coding: utf-8 -*-
"""
semantic_purity.py

Utilities to keep semantic reasoning specific to the current keyword.
This layer removes cross-keyword contamination before outline/brief generation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional


STOP = {"nhung", "cach", "la", "gi", "cho", "voi", "the", "nao", "trong", "cac", "mot", "tai", "ve"}
GENERIC_NOISE = {
    "bai viet lien quan",
    "lien quan",
    "download",
    "template",
    "checklist",
    "viet nam",
}
CROSS_TOPIC_TERMS = set()

URLISH_RE = re.compile(r"(https?://|www\.|mailto:|tel:|/[\w\-]+/[\w\-]+)")
HEAVY_SEPARATOR_RE = re.compile(r"(>{2,}|={2,}|\|{2,}|[_]{2,}|[-]{3,})")
PROMO_CONTACT_RE = re.compile(r"(\+?\d[\d\-\.\s]{7,}\d|@\w+)")


def normalize_text(value: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^a-z0-9\s]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def token_set(value: Any) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", normalize_text(value))
    return {token for token in tokens if token not in STOP}


def overlap_score(left: Any, right: Any) -> float:
    a = token_set(left)
    b = token_set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def build_query_state(
    topic: str,
    intent: str,
    paa_questions: Optional[List[str]] = None,
    common_headings: Optional[List[str]] = None,
    content_gaps: Optional[List[str]] = None,
    eav_rows: Optional[List[Dict[str, str]]] = None,
    semantic_terms: Optional[List[str]] = None,
    project_scope: str = "",
) -> Dict[str, Any]:
    return {
        "topic": str(topic or "").strip(),
        "topic_norm": normalize_text(topic),
        "intent": str(intent or "").strip(),
        "paa_questions": [str(x).strip() for x in (paa_questions or []) if str(x).strip()],
        "common_headings": [str(x).strip() for x in (common_headings or []) if str(x).strip()],
        "content_gaps": [str(x).strip() for x in (content_gaps or []) if str(x).strip()],
        "eav_rows": [row for row in (eav_rows or []) if isinstance(row, dict)],
        "semantic_terms": [str(x).strip() for x in (semantic_terms or []) if str(x).strip()],
        "project_scope": str(project_scope or "").strip(),
    }


def is_noise_candidate(text: Any, state: Dict[str, Any]) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    if norm in GENERIC_NOISE:
        return True
    if any(term in norm for term in CROSS_TOPIC_TERMS):
        return True
    if "?" in str(text) and len(token_set(text)) <= 3:
        return True
    if norm == state.get("topic_norm", ""):
        return True
    return False


def clean_fact_text(value: Any) -> str:
    text = str(value or "").replace("\r", "\n").strip()
    text = text.replace(">>>>", " ").replace(">>>", " ").replace(">>", " ")
    text = re.sub(r"\s+", " ", text)
    if ":" in text:
        left, right = text.split(":", 1)
        left = left.strip()
        title_like_ratio = 0.0
        left_tokens = [token for token in re.split(r"\s+", left) if token]
        if left_tokens:
            title_like_ratio = sum(1 for token in left_tokens if token[:1].isupper()) / len(left_tokens)
        if len(left_tokens) <= 4 and title_like_ratio >= 0.75 and right.strip():
            text = right.strip()
    return text.strip(" -")


def is_meta_instruction_text(text: Any) -> bool:
    norm = normalize_text(text)
    if not norm:
        return True
    first_tokens = norm.split()[:4]
    if len(first_tokens) >= 2 and first_tokens[0] in {"bai", "phan", "section", "faq"} and first_tokens[1] in {"viet", "nay", "can", "nen"}:
        return True
    if len(first_tokens) >= 2 and first_tokens[0] == "nguoi" and first_tokens[1] == "doc":
        return True
    if any(phrase in norm for phrase in ["theo dung intent", "noi dung can", "can tra loi", "can lam ro"]):
        return True
    return False


def _looks_like_navigational_text(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return True
    if URLISH_RE.search(raw):
        return True
    if HEAVY_SEPARATOR_RE.search(raw):
        return True
    if PROMO_CONTACT_RE.search(raw) and len(raw.split()) <= 8:
        return True
    if raw.endswith(":"):
        return True
    return False


def _looks_like_complete_fact(text: str) -> bool:
    raw = clean_fact_text(text)
    norm = normalize_text(raw)
    if not norm:
        return False
    if len(norm.split()) < 4 and not re.search(r"\d", norm):
        return False
    if _looks_like_navigational_text(raw):
        return False
    if overlap_score(raw, norm) == 0 and len(raw) < 12:
        return False
    return True


def is_clean_fact_candidate(attribute: Any, value: Any, state: Optional[Dict[str, Any]] = None) -> bool:
    attr = clean_fact_text(attribute)
    val = clean_fact_text(value)
    attr_norm = normalize_text(attr)
    val_norm = normalize_text(val)
    combo_norm = f"{attr_norm} {val_norm}".strip()

    if not attr_norm or not val_norm:
        return False
    if _looks_like_navigational_text(attr) or _looks_like_navigational_text(val):
        return False
    if not _looks_like_complete_fact(val):
        return False
    if len(attr_norm.split()) > 16:
        return False
    if overlap_score(attr_norm, val_norm) >= 0.70 and len(val_norm.split()) <= 6:
        return False
    if is_meta_instruction_text(val) and len(val_norm.split()) <= 12:
        return False
    if state is not None and purity_score(f"{attr} {val}", state) < 0.04 and purity_score(attr, state) < 0.04:
        return False
    return True


def sanitize_fact_row(row: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(row, dict):
        return None
    clean_row = dict(row)
    clean_row["attribute"] = clean_fact_text(clean_row.get("attribute", ""))
    clean_row["value"] = clean_fact_text(clean_row.get("value", ""))
    if not is_clean_fact_candidate(clean_row.get("attribute", ""), clean_row.get("value", ""), state=state):
        return None
    return clean_row


def purity_score(text: Any, state: Dict[str, Any]) -> float:
    norm = normalize_text(text)
    if not norm:
        return 0.0
    topic_overlap = overlap_score(norm, state.get("topic", ""))
    paa_overlap = max([overlap_score(norm, q) for q in state.get("paa_questions", [])] or [0.0])
    heading_overlap = max([overlap_score(norm, h) for h in state.get("common_headings", [])] or [0.0])
    eav_overlap = max(
        [
            max(
                overlap_score(norm, row.get("attribute", "")),
                overlap_score(norm, row.get("attribute", "") + " " + row.get("value", "")),
            )
            for row in state.get("eav_rows", [])
        ] or [0.0]
    )
    return max(topic_overlap * 0.45 + paa_overlap * 0.2 + heading_overlap * 0.15 + eav_overlap * 0.2, topic_overlap)


def filter_pure_phrases(items: Optional[List[str]], state: Dict[str, Any], min_score: float = 0.16, limit: int = 0) -> List[str]:
    clean: List[str] = []
    seen = set()
    for item in items or []:
        text = str(item or "").strip()
        norm = normalize_text(text)
        if not text or norm in seen or is_noise_candidate(text, state):
            continue
        if purity_score(text, state) < min_score:
            continue
        seen.add(norm)
        clean.append(text)
        if limit and len(clean) >= limit:
            break
    return clean


def filter_eav_rows(rows: Optional[List[Dict[str, str]]], state: Dict[str, Any], min_score: float = 0.14) -> List[Dict[str, str]]:
    clean: List[Dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        attr = str(row.get("attribute", "")).strip()
        value = str(row.get("value", "")).strip()
        if not attr or not value:
            continue
        if purity_score(attr + " " + value, state) < min_score and purity_score(attr, state) < min_score:
            continue
        clean.append(row)
    return clean




def curated_semantic_terms(state: Dict[str, Any]) -> List[str]:
    terms = filter_pure_phrases(state.get("semantic_terms", []), state, min_score=0.12, limit=12)
    if terms:
        return terms
    fallback = []
    for heading in state.get("common_headings", []):
        if purity_score(heading, state) >= 0.14:
            fallback.append(heading)
    return list(dict.fromkeys(fallback))[:8]


def derive_misinterpretation_risks(state: Dict[str, Any], semantic_terms: Optional[List[str]] = None) -> List[str]:
    risks: List[str] = []
    topic_norm = state.get("topic_norm", "")
    scope_norm = normalize_text(state.get("project_scope", ""))
    topic_tokens = token_set(topic_norm)
    scope_tokens = token_set(scope_norm)

    if scope_tokens and topic_tokens and len(topic_tokens & scope_tokens) < max(1, min(len(topic_tokens), 2)):
        risks.append(
            "De truot khoi topical border cua project neu khong khoa ro thuc the trung tam va pham vi ap dung"
        )

    for term in semantic_terms or []:
        norm = normalize_text(term)
        if topic_tokens and overlap_score(norm, state.get("topic", "")) < 0.08 and len(token_set(norm)) >= 2:
            risks.append(f"De bi mo rong sang huong khong cung vector boi semantic term '{term}'")

    return list(dict.fromkeys(risks))[:5]


PILLAR_SECONDARY_TERMS = set()
PILLAR_NARROW_MARKERS = set()


def _is_broad_pillar_topic(state: Dict[str, Any]) -> bool:
    topic_norm = normalize_text(state.get("topic", ""))
    tokens = token_set(topic_norm)
    if not tokens or len(tokens) > 4:
        return False
    if any(marker in topic_norm for marker in PILLAR_NARROW_MARKERS):
        return False
    broad_signals = [
        "huong dan",
        "tong quan",
        "kinh nghiem",
        "kien thuc",
        "khai niem",
        "nen biet",
    ]
    return any(signal in topic_norm for signal in broad_signals) or len(tokens) <= 3


def _signal_hits(text: str, state: Dict[str, Any]) -> int:
    norm = normalize_text(text)
    if not norm:
        return 0
    pool = []
    pool.extend(state.get("paa_questions", []))
    pool.extend(state.get("common_headings", []))
    pool.extend(state.get("content_gaps", []))
    hits = 0
    for item in pool:
        item_norm = normalize_text(item)
        if not item_norm:
            continue
        if overlap_score(norm, item_norm) >= 0.22:
            hits += 1
            continue
        if any(term in item_norm for term in norm.split() if len(term) >= 4):
            hits += 1
    return hits


def _is_secondary_pillar_term(text: str) -> bool:
    norm = normalize_text(text)
    return any(term in norm for term in PILLAR_SECONDARY_TERMS)


def derive_dominant_user_task(state: Dict[str, Any]) -> str:
    topic = state.get("topic", "")
    intent = normalize_text(state.get("intent", ""))
    if _is_broad_pillar_topic(state):
        return (
            f"Người đọc cần hiểu rõ {topic}, các nhóm chính, cách hoạt động, lợi ích và rủi ro trước khi đi sâu vào "
            "các điều kiện hỗ trợ như chi phí, tiêu chí lựa chọn hoặc công cụ triển khai."
        )
    if "commercial" in intent:
        return f"Người đọc cần hiểu rõ {topic}, các tiêu chí đánh giá chính và điểm khác biệt giữa các lựa chọn trước khi ra quyết định."
    if "transactional" in intent:
        return f"Người đọc cần biết điều kiện áp dụng, quy trình thực hiện và các điểm cần kiểm tra trước khi hành động với {topic}."
    if "navigational" in intent:
        return f"Người đọc cần xác nhận đúng thực thể liên quan đến {topic} và tìm đường đi ngắn nhất đến thông tin hoặc dịch vụ phù hợp."
    return f"Người đọc cần hiểu đúng {topic}, các thuộc tính cốt lõi, cách phân biệt với khái niệm gần nghĩa và cách áp dụng thông tin vào thực tế."


def derive_supporting_tasks(state: Dict[str, Any], h2_gaps: Optional[List[str]] = None) -> List[str]:
    tasks: List[str] = []
    if _is_broad_pillar_topic(state):
        tasks.extend(
            [
                "Nắm định nghĩa và phạm vi của thực thể trung tâm",
                "Hiểu các hình thức hoặc nhóm chính trong chủ đề",
                "Hiểu cách hoạt động và cơ chế áp dụng trong thực tế",
                "Biết rủi ro, điều kiện tham gia và yếu tố cần chuẩn bị",
            ]
        )
    for question in state.get("paa_questions", []):
        q = normalize_text(question)
        if any(sig in q for sig in ["khac", "phan biet", "so sanh"]):
            tasks.append("Phân biệt với các khái niệm hoặc lựa chọn gần nghĩa")
        elif any(sig in q for sig in ["cach", "nhu the nao", "hoat dong", "ap dung"]):
            tasks.append("Hiểu cách hoạt động hoặc cách áp dụng trong thực tế")
        elif any(sig in q for sig in ["rui ro", "luu y", "canh bao", "sai lam"]):
            tasks.append("Tránh hiểu nhầm và nhận diện rủi ro trước khi áp dụng")
        elif any(sig in q for sig in ["bao nhieu", "muc", "dieu kien"]):
            tasks.append("Biết các khoản hoặc điều kiện dễ bị bỏ sót")
    for gap in h2_gaps or []:
        g = normalize_text(gap)
        if _is_broad_pillar_topic(state) and _is_secondary_pillar_term(g) and _signal_hits(gap, state) < 2:
            tasks.append("Biết các điều kiện hỗ trợ chỉ khi chúng thật sự ảnh hưởng đến cách hiểu hoặc quyết định")
            continue
        if any(sig in g for sig in ["so sanh", "danh gia"]):
            tasks.append("Có đủ tiêu chí để so sánh và đánh giá")
        elif any(sig in g for sig in ["dieu kien", "rui ro", "sai lam"]):
            tasks.append("Biết các khoản hoặc điều kiện dễ bị bỏ sót")
        elif any(sig in g for sig in ["chien luoc", "cach", "hoat dong", "phan tich"]):
            tasks.append("Áp dụng thông tin đúng vào ngữ cảnh thực tế")
    if not tasks:
        tasks = [
            "Nắm định nghĩa và phạm vi nghĩa chính xác",
            "Phân biệt với các khái niệm gần nghĩa",
            "Áp dụng thông tin đúng vào ngữ cảnh thực tế",
        ]
    return list(dict.fromkeys(tasks))[:6]


def derive_decision_blockers(state: Dict[str, Any], gap_candidates: Optional[List[str]] = None) -> List[str]:
    blockers: List[str] = []
    if _is_broad_pillar_topic(state):
        blockers.extend(
            [
                "Người đọc chưa rõ chủ đề chính khác gì với các khái niệm gần nghĩa",
                "Người đọc chưa hình dung các nhóm chính và tình huống áp dụng thực tế",
                "Người đọc chưa biết khi nào các điều kiện phụ mới thực sự quan trọng",
            ]
        )
    for question in state.get("paa_questions", []):
        q = normalize_text(question)
        if any(sig in q for sig in ["khac", "phan biet", "la gi"]):
            blockers.append("Người đọc dễ nhầm chủ đề với khái niệm gần nghĩa")
        if any(sig in q for sig in ["bao nhieu", "cach", "dieu kien"]):
            blockers.append("Người đọc chưa có đủ dữ kiện hoặc ví dụ để tự đối chiếu trong thực tế")
    for gap in gap_candidates or []:
        g = normalize_text(gap)
        if _is_broad_pillar_topic(state) and _is_secondary_pillar_term(g) and _signal_hits(gap, state) < 2:
            continue
        if any(sig in g for sig in ["phat sinh", "an", "dieu kien"]):
            blockers.append("Nguoi doc thuong khong nhin thay dieu kien phat sinh hoac gioi han an")
        if any(sig in g for sig in ["so sanh", "danh gia"]):
            blockers.append("Người đọc thiếu khung tiêu chí cố định để so sánh")
    if not blockers:
        blockers = [
            "Người đọc dễ nhầm chủ đề với khái niệm gần nghĩa",
            "Người đọc thiếu ví dụ hoặc điều kiện cụ thể để áp dụng thông tin đúng cách",
        ]
    return list(dict.fromkeys(blockers))[:5]


def derive_consensus_facts(state: Dict[str, Any], project_scope: str = "") -> List[str]:
    topic = state.get("topic", "")
    facts: List[str] = []
    broad_pillar = _is_broad_pillar_topic(state)
    for row in state.get("eav_rows", []):
        attr = str(row.get("attribute", "")).strip()
        value = str(row.get("value", "")).strip()
        attr_norm = normalize_text(attr)
        if not attr or not value:
            continue
        if broad_pillar and _is_secondary_pillar_term(attr_norm) and _signal_hits(attr_norm, state) < 2:
            continue
        if "dinh nghia" in attr_norm:
            facts.append(f"{topic} cần được chốt bằng một định nghĩa rõ ràng trước khi mở rộng sang các phần sau.")
        elif "phan loai" in attr_norm:
            facts.append(f"{topic} thường cần được tách rõ theo nhóm hoặc cấu phần như {value}.")
        elif any(sig in attr_norm for sig in ["dac diem", "co che", "yeu to", "ung dung", "loi ich", "rui ro"]):
            facts.append(f"{attr}: {value}.")
    for heading in state.get("common_headings", []):
        norm = normalize_text(heading)
        if any(sig in norm for sig in ["la gi", "khai niem", "dinh nghia"]):
            facts.append("Bài viết phải chốt định nghĩa và phạm vi nghĩa trước khi mở rộng sang các phần sau.")
        elif any(sig in norm for sig in ["khac", "so sanh", "phan biet"]):
            facts.append("Người đọc thường cần một lớp phân biệt với khái niệm hoặc lựa chọn gần nghĩa.")
        elif any(sig in norm for sig in ["rui ro", "luu y", "sai lam"]):
            facts.append("Bài viết cần có lớp cảnh báo hoặc lưu ý để ngăn hiểu sai và áp dụng sai.")
    for question in state.get("paa_questions", []):
        q = normalize_text(question)
        if any(sig in q for sig in ["hoat dong", "nhu the nao", "cach"]):
            facts.append("Người đọc không chỉ cần định nghĩa mà còn cần biết cơ chế hoạt động hoặc cách áp dụng trong thực tế.")
    return filter_pure_phrases(facts, state, min_score=0.08, limit=7)


def classify_gap_map(state: Dict[str, Any], gaps: Optional[List[str]] = None, consensus_facts: Optional[List[str]] = None) -> Dict[str, List[str]]:
    gap_map = {"h2_worthy": [], "supporting_detail": [], "topical_expansion": [], "noise": []}
    broad_pillar = _is_broad_pillar_topic(state)
    for gap in gaps or []:
        text = str(gap or "").strip()
        norm = normalize_text(text)
        if not text:
            continue
        score = purity_score(text, state)
        if is_noise_candidate(text, state) or score < 0.08:
            gap_map["noise"].append(text)
            continue

        hits = _signal_hits(text, state)
        broad = len(token_set(text)) >= 4 or any(
            sig in norm for sig in ["so sanh", "danh gia", "rui ro", "sai lam", "chien luoc", "phan tich", "cach", "hoat dong"]
        )

        if broad_pillar and _is_secondary_pillar_term(norm):
            if hits >= 3 and score >= 0.22:
                gap_map["supporting_detail"].append(text)
            elif score >= 0.12:
                gap_map["topical_expansion"].append(text)
            else:
                gap_map["noise"].append(text)
            continue

        if broad and score >= 0.18:
            gap_map["h2_worthy"].append(text)
        elif any(sig in norm for sig in ["vi du", "truong hop", "yeu to", "dieu kien", "luu y", "bao nhieu", "muc"]):
            gap_map["supporting_detail"].append(text)
        elif score >= 0.12:
            gap_map["topical_expansion"].append(text)
        else:
            gap_map["noise"].append(text)

    for key in gap_map:
        gap_map[key] = list(dict.fromkeys(gap_map[key]))[: (10 if key == "noise" else 7)]
    return gap_map
