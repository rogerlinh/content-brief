# -*- coding: utf-8 -*-
"""
knowledge_loader.py - KB Loading with Section-Based Extraction.

Supports full file loading and section-based loading for agent-specific injection.
Caches results to avoid repetitive disk I/O.
"""

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

KB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "knowledge_base")


@lru_cache(maxsize=10)
def load_kb(filename: str) -> str:
    """
    Reads a markdown file from the knowledge_base directory.
    Uses lru_cache to prevent repetitive disk I/O for the same file.
    """
    filepath = os.path.join(KB_DIR, filename)

    if not os.path.exists(filepath):
        logger.warning(f"  [KNOWLEDGE BASE] File not found: {filename} at {filepath}. Returning empty string.")
        return ""

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            logger.debug(f"  [KNOWLEDGE BASE] Successfully loaded {filename} ({len(content)} bytes).")
            return content
    except Exception as e:
        logger.error(f"  [KNOWLEDGE BASE] Error reading {filename}: {e}")
        return ""


@lru_cache(maxsize=30)
def load_kb_section(filename: str, section_key: str) -> str:
    """
    Extract a specific section from KB file by keyword matching.

    Section boundaries: starts at line containing section_key,
    ends at next same-level header or EOF.

    Args:
        filename: KB file name
        section_key: Section header text to search for (case-insensitive)

    Returns:
        Extracted section text, or empty string if not found.
    """
    full_content = load_kb(filename)
    if not full_content:
        return ""

    lines = full_content.split("\n")
    section_key_lower = section_key.lower()

    start_idx = -1
    start_level = 0

    for i, line in enumerate(lines):
        if section_key_lower in line.lower():
            start_idx = i
            # Detect header level (count # or * prefixes)
            stripped = line.lstrip()
            if stripped.startswith("#"):
                start_level = len(stripped) - len(stripped.lstrip("#"))
            elif stripped.startswith("*"):
                start_level = len(stripped) - len(stripped.lstrip("*"))
            else:
                start_level = 0
            break

    if start_idx == -1:
        return ""

    # Find end: next header at same or higher level
    end_idx = len(lines)
    if start_level > 0:
        for i in range(start_idx + 1, len(lines)):
            stripped = lines[i].lstrip()
            if stripped.startswith("#"):
                current_level = len(stripped) - len(stripped.lstrip("#"))
                if current_level <= start_level:
                    end_idx = i
                    break
            elif stripped.startswith("*") and len(stripped) > 1 and stripped[1] == " ":
                # Top-level bullet = same level break for outline structure
                pass

    extracted = "\n".join(lines[start_idx:end_idx]).strip()
    logger.debug(f"  [KB-SECTION] Extracted '{section_key}' from {filename}: {len(extracted)} bytes")
    return extracted


def load_kb_for_agent(agent_name: str) -> str:
    """
    Load agent-specific KB sections to keep prompt size manageable.

    Agent mapping:
    - agent_1_outline: Contextual structure, hierarchy, connections, supplemental content rules
    - agent_2_semantic: Semantic relationships, word relationships, entity relationships
    - agent_3_micro: Writing guidelines, answer structure, featured snippets
    - koray_scorer: Attribute filtration, information structure
    - eav_generator: Entity relationships, attribute filtration

    Returns:
        Concatenated KB sections relevant to this agent.
    """
    sections = []

    if agent_name == "agent_1_outline":
        # Part A: Structure + hierarchy + connections + supplemental
        sections.append("--- KB: OUTLINE STRUCTURE RULES ---")
        for key in [
            "A1. Contextual Structure Elements",
            "A3. Context Management",
            "A4. Information Structure",
            "PART B: MAIN CONTENT",
            "PART C: TRANSITIONAL CONTENT",
            "PART D: SUPPLEMENTAL CONTENT",
        ]:
            sec = load_kb_section("kb_outline_structure.md", key)
            if sec:
                sections.append(sec)

        # Lecture 16: Attribute Filtration (critical for H2 ordering)
        sec = load_kb_section("kb_outline_structure.md", "Lecture 16")
        if sec:
            sections.append(sec)

        # Lecture 9: Main vs Supplementary Content
        sec = load_kb_section("kb_outline_structure.md", "Lecture 9")
        if sec:
            sections.append(sec)

    elif agent_name == "agent_2_semantic":
        # Part A: Semantic relationships + context sharpening
        sections.append("--- KB: SEMANTIC SEO RULES ---")
        for key in [
            "A2. Semantic Relationships",
            "A3. Context Management",
            "A5. Content Optimization",
        ]:
            sec = load_kb_section("kb_outline_structure.md", key)
            if sec:
                sections.append(sec)

    elif agent_name == "agent_3_micro":
        # Writing guidelines (full - only 59KB) + answer structure
        sections.append("--- KB: WRITING GUIDELINES ---")
        kb_writing = load_kb("kb_writing_guidelines.md")
        if kb_writing:
            sections.append(kb_writing)

        # Part B2: Answer Structure from outline KB
        for key in [
            "B2. Main Content Development",
            "B3. Featured Snippet Optimization",
        ]:
            sec = load_kb_section("kb_outline_structure.md", key)
            if sec:
                sections.append(sec)

    elif agent_name == "koray_scorer":
        # Minimal: just attribute filtration + info structure
        sections.append("--- KB: SCORING RULES ---")
        for key in [
            "A4. Information Structure",
            "Lecture 16",
        ]:
            sec = load_kb_section("kb_outline_structure.md", key)
            if sec:
                sections.append(sec)

    elif agent_name == "eav_generator":
        # Entity relationships + attribute filtration
        sections.append("--- KB: EAV RULES ---")
        for key in [
            "A2.3 Entity Relationships",
            "Lecture 16",
        ]:
            sec = load_kb_section("kb_outline_structure.md", key)
            if sec:
                sections.append(sec)

    else:
        # Fallback: load writing guidelines only (smallest KB)
        sections.append("--- KB: GENERAL ---")
        kb_writing = load_kb("kb_writing_guidelines.md")
        if kb_writing:
            sections.append(kb_writing)

    result = "\n\n".join(sections)
    logger.info(f"  [KB-AGENT] Loaded {len(result)} bytes for agent '{agent_name}'")
    return result
