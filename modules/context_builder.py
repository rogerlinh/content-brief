# -*- coding: utf-8 -*-
"""
context_builder.py - Biến đổi Competitor Headings thành Context Vectors & Guidelines bằng LLM (OpenAI/Gemini).

Mục tiêu chính (Yêu cầu nghiêm ngặt):
1. Nhận cụm Headings H2/H3 của top 4 đối thủ.
2. Dùng LLM prompt để:
   a. Chuyển đổi headings thành các CÂU HỎI TRỰC TIẾP (Context Vectors).
   b. Sắp xếp câu hỏi theo luồng logic (Từ cơ bản đến chuyên sâu).
   c. Tạo Guidelines (Contextual Structure) ép buộc: 
      - Trả lời trực tiếp ngay dòng đầu (No fluff).
      - Xưng hô "Tôi/Chúng tôi" để tăng E-E-A-T.
      - Tối ưu Micro-semantics (đưa thực thể lên trước).

Usage:
    from modules.context_builder import build_prompt_context
    context = build_prompt_context("keyword chính", competitor_data)
"""

import json
import logging
import re
from typing import Dict, Optional
from config import LLM_CONFIG
from modules.outline_content_prompt_catalog import build_context_vector_prompts

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)




def _questionize_heading(text: str, topic: str) -> str:
    cleaned = re.sub(r"^\[H[23]\]\s*", "", str(text or "").strip(), flags=re.I)
    cleaned = re.sub(r"^\d+[\.\)]\s*", "", cleaned).strip()
    if not cleaned:
        return f"{topic} la gi?"
    lower = cleaned.lower()
    if any(sig in lower for sig in ["la gi", "nhu the nao", "bao nhieu", "so sanh", "khac nhau", "rui ro", "luu y", "quy trinh", "cach"]):
        return cleaned if cleaned.endswith("?") else f"{cleaned}?"
    if topic and lower in topic.lower():
        return f"{topic} co gi can biet?"
    return f"{cleaned} lien quan den {topic} nhu the nao?"


def _project_scope_summary(project) -> str:
    if not project:
        return ""
    parts = []
    for attr in ["industry", "main_products", "target_customers", "usp"]:
        value = getattr(project, attr, "") or ""
        value = str(value).strip()
        if value:
            parts.append(value)
    return " | ".join(parts)


def _fallback_prompt_context(topic: str, competitor_data: dict, project=None) -> Dict:
    competitors = competitor_data.get("competitors", []) if isinstance(competitor_data, dict) else []
    headings = []
    for comp in competitors[:4]:
        for h in comp.get("headings", []):
            if isinstance(h, dict):
                h_type = str(h.get("level", "")).lower()
                text = str(h.get("text", "")).strip()
            elif isinstance(h, (list, tuple)) and len(h) >= 2:
                h_type = str(h[0]).lower()
                text = str(h[1]).strip()
            else:
                continue
            if h_type in ["h2", "h3"] and text:
                headings.append(text)

    vectors = []
    seen = set()
    for raw in headings[:12]:
        q = _questionize_heading(raw, topic)
        key = q.lower()
        if key not in seen:
            seen.add(key)
            vectors.append({"question": q, "intent": "Tim kiem thong tin"})

    scope = _project_scope_summary(project)
    scope_hint = scope or "ngữ cảnh của chủ đề"
    if not vectors:
        fallback_questions = [
            f"{topic} la gi trong {scope_hint}?",
            f"{topic} hoat dong nhu the nao trong {scope_hint}?",
            f"Nhung yeu to chinh cua {topic} can xem xet la gi?",
            f"Cach ap dung {topic} trong thuc te nhu the nao?",
            f"Nhung luu y quan trong khi tim hieu {topic} la gi?",
        ]
        vectors = [{"question": q, "intent": "Tim kiem thong tin"} for q in fallback_questions]

    structure = [
        "Nguyen tac 1: Tra loi truc tiep ngay dong dau tien sau moi heading.",
        "Nguyen tac 2: Uu tien heading dang cau hoi neu intent la informational/how-to.",
        "Nguyen tac 3: Entity va attribute can nam o dau cau de tang micro-semantics.",
        "Nguyen tac 4: Brand, hotline va CTA chi duoc chen o [SUPP] hoac cuoi bai.",
        f"Nguyen tac 5: Giữ đúng topical border theo source context: {scope_hint}.",
    ]
    if headings:
        structure.insert(
            1,
            "Nguyen tac 1.1: Su dung headings doi thu nhu nguon y tuong, khong copy nguyen van.",
        )

    return {"context_vectors": vectors, "contextual_structure": structure}


def build_prompt_context(topic: str, competitor_data: dict, project=None) -> Dict:
    """
    Override: always return a usable context payload.
    LLM path is kept when available, otherwise fall back to rule-based vectors.
    """
    logger.info("  [CONTEXT] Bat dau xay dung Context Vectors cho: '%s'", topic)
    competitor_data = competitor_data or {}

    if not OpenAI:
        logger.warning("  [CONTEXT] Thieu thu vien 'openai'. Dung fallback rule-based.")
        return _fallback_prompt_context(topic, competitor_data, project=project)

    api_key = LLM_CONFIG.get("api_key")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.warning("  [CONTEXT] OPENAI_API_KEY chua cau hinh. Dung fallback rule-based.")
        return _fallback_prompt_context(topic, competitor_data, project=project)

    competitors = competitor_data.get("competitors", [])
    if not competitors:
        logger.warning("  [CONTEXT] Khong co du lieu doi thu. Dung fallback rule-based.")
        return _fallback_prompt_context(topic, competitor_data, project=project)

    all_headings = []
    for comp in competitors[:4]:
        for h in comp.get("headings", []):
            if isinstance(h, dict):
                h_type = h.get("level", "").lower()
                text = h.get("text", "")
            elif isinstance(h, (list, tuple)) and len(h) >= 2:
                h_type, text = h[0].lower(), h[1]
            else:
                continue
            if h_type in ["h2", "h3"] and str(text).strip():
                all_headings.append(f"[{h_type.upper()}] {str(text).strip()}")

    if not all_headings:
        logger.warning("  [CONTEXT] Khong tim thay headings H2/H3 nao tu doi thu.")
        return _fallback_prompt_context(topic, competitor_data, project=project)

    headings_str = "\n".join(all_headings[:80])
    client = OpenAI(
        api_key=api_key,
        base_url=LLM_CONFIG.get("base_url") if LLM_CONFIG.get("base_url") else None
    )

    system_prompt, user_prompt = build_context_vector_prompts(topic=topic, headings_text=headings_str)

    try:
        logger.info("  [CONTEXT] Dang gui %d headings toi LLM (%s)...", min(len(all_headings), 80), LLM_CONFIG.get("model"))
        response = client.chat.completions.create(
            model=LLM_CONFIG.get("model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=60,
        )
        content = response.choices[0].message.content
        try:
            context_data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            data = _fallback_prompt_context(topic, competitor_data, project=project)
            data["error"] = "LLM unavailable: JSON parse failed"
            return data
        if "context_vectors" not in context_data:
            context_data["context_vectors"] = []
        if "contextual_structure" not in context_data:
            context_data["contextual_structure"] = []
        if not context_data["context_vectors"] or not context_data["contextual_structure"]:
            data = _fallback_prompt_context(topic, competitor_data, project=project)
            data["error"] = "LLM unavailable: empty context output"
            return data
        logger.info(
            "  [CONTEXT] Hoan tat: %d vectors, %d guidelines",
            len(context_data["context_vectors"]),
            len(context_data["contextual_structure"]),
        )
        return context_data
    except Exception as e:
        logger.error("  [CONTEXT] LLM Error: %s", str(e))
        data = _fallback_prompt_context(topic, competitor_data, project=project)
        data["error"] = f"LLM unavailable: {type(e).__name__}"
        return data
