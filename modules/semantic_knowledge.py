# -*- coding: utf-8 -*-
"""
semantic_knowledge.py - Phase 20: Semantic SEO Knowledge Base (Koray's Framework)

Đọc và parse nội dung từ file skill.md ở thư mục gốc để cung cấp cho System Prompts.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Cache biến để không phải đọc file nhiều lần
_KNOWLEDGE_CACHE = None

def get_semantic_skills() -> str:
    """
    Đọc toàn bộ định nghĩa Semantic SEO từ skill.md để nhúng vào Prompt.
    
    Returns:
        Chuỗi text chứa nội dung skill.md. Trả về rỗng nếu không tìm thấy.
    """
    global _KNOWLEDGE_CACHE
    if _KNOWLEDGE_CACHE is not None:
        return _KNOWLEDGE_CACHE

    try:
        # Giả sử skill.md nằm ở thư mục gốc của project (trên 1 level so với modules)
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        skill_path = os.path.join(root_dir, "skill.md")
        
        if not os.path.exists(skill_path):
            logger.warning(f"  [SEMANTIC] Không tìm thấy file {skill_path}. Sẽ run không có semantic knowledge.")
            _KNOWLEDGE_CACHE = ""
            return _KNOWLEDGE_CACHE

        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract phần Framework Semantic SEO (Từ dòng "Dưới đây là danh sách..." trở đi)
        # Cách lấy đơn giản là lấy toàn bộ, vì skill.md user cung cấp full về Semantic SEO
        # Tùy chỉnh nếu skill.md có nhiều phần khác.
        
        _KNOWLEDGE_CACHE = content
        logger.info("  [SEMANTIC] Đã nạp thành công bộ kiến thức Semantic SEO từ skill.md")
        return _KNOWLEDGE_CACHE

    except Exception as e:
        logger.error(f"  [SEMANTIC] Lỗi khi đọc skill.md: {e}")
        _KNOWLEDGE_CACHE = ""
        return _KNOWLEDGE_CACHE

def inject_semantic_prompt(base_prompt: str, agent_name: str = "") -> str:
    """
    Inject System Prompt với Semantic Knowledge (skill.md) và KB sections phù hợp với agent.

    Args:
        base_prompt: System prompt gốc.
        agent_name: Tên agent để load KB phù hợp.
            - "agent_1_outline": Outline structure + attribute filtration
            - "agent_2_semantic": Semantic relationships + context optimization
            - "agent_3_micro": Writing guidelines + answer structure
            - "koray_scorer": Scoring rules only
            - "eav_generator": EAV + entity relationships
            - "" (empty): Fallback — writing guidelines + geo only (~75KB)
    """
    knowledge = get_semantic_skills()

    try:
        from modules.knowledge_loader import load_kb, load_kb_section, load_kb_for_agent

        if agent_name:
            # Agent-specific KB sections (reduced size)
            agent_kb = load_kb_for_agent(agent_name)
            kb_geo = load_kb("kb_review_geo.md")
            full_kb = (
                f"--- SEMANTIC SEO SKILL ---\n{knowledge}\n"
                f"--- AGENT-SPECIFIC KB ({agent_name}) ---\n{agent_kb}\n"
                f"--- COMMERCIAL/GEO ---\n{kb_geo}\n"
            )
        else:
            # Fallback: writing guidelines + geo only (NOT full 220KB)
            kb_writing = load_kb("kb_writing_guidelines.md")
            kb_geo = load_kb("kb_review_geo.md")
            full_kb = (
                f"--- SEMANTIC SEO SKILL ---\n{knowledge}\n"
                f"--- WRITING GUIDELINES ---\n{kb_writing}\n"
                f"--- COMMERCIAL/GEO ---\n{kb_geo}\n"
            )
    except ImportError:
        full_kb = f"--- KNOWLEDGE BASE ---\n{knowledge}\n"

    system_prefix = (
        "Bạn là chuyên gia Semantic SEO tuân thủ framework của Koray Tuğberk Gürbüz.\n"
        "BẠN BẮT BUỘC PHẢI ÁP DỤNG TOÀN BỘ CÁC QUY TẮC CỦA KNOWLEDGE BASE DƯỚI ĐÂY ĐỂ THỰC HIỆN NHIỆM VỤ:\n\n"
        f"{full_kb}\n"
        "----------------------\n\n"
        "VÀ DƯỚI ĐÂY LÀ NHIỆM VỤ ĐỘC QUYỀN VÀ CỤ THỂ CỦA BẠN TRONG LUỒNG WORKFLOW NÀY:\n"
    )
    return system_prefix + base_prompt


def inject_source_context(base_prompt: str, project=None) -> str:
    """
    Inject Source Context của active project vào đầu base_prompt.
    Gọi SAU inject_semantic_prompt() để đảm bảo thứ tự đúng.

    Args:
        base_prompt: System prompt gốc (đã được inject semantic knowledge).
        project: Project object từ ProjectManager, hoặc None.

    Returns:
        Prompt đã được prepend Source Context (hoặc prompt gốc nếu không có project).
    """
    if not project:
        return base_prompt

    try:
        # Gọi trực tiếp method trên object, không cần tạo lại ProjectManager
        from modules.project_manager import ProjectManager
        pm = ProjectManager()
        source_ctx = pm.to_source_context_string(project)
        if source_ctx.strip():
            logger.info("  [SEMANTIC] Đã inject Source Context của project '%s'", project.brand_name)
            return source_ctx + "\n\n" + base_prompt
    except Exception as e:
        logger.warning("  [SEMANTIC] Không thể inject Source Context: %s", e)

    return base_prompt
