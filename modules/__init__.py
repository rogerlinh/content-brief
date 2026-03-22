# -*- coding: utf-8 -*-
"""
modules - Package chứa các module phân tích cho Content Brief Generator.

Modules:
    csv_reader                – Đọc và validate topics từ file CSV
    topic_analyzer            – Phân tích chủ đề (intent, entity, context)
    serp_competitor_analyzer  – Phân tích SERP Google và đối thủ cạnh tranh
    query_network             – Mở rộng từ khóa và phân cụm bằng LLM
    context_builder           – Tạo Context Vectors và Structure từ LLM
    internal_linking          – Phân tích Inbound/Outbound links từ Topical Map
    content_brief_builder     – Tổng hợp Content Brief
    markdown_exporter         – Xuất kết quả ra file .md
"""

from .csv_reader import read_topics
from .topic_analyzer import analyze_topic
from .serp_competitor_analyzer import analyze_serp, analyze_competitors
from .query_network import analyze_query_network
from .context_builder import build_prompt_context
from .internal_linking import build_internal_links
from .content_brief_builder import build_brief
from .markdown_exporter import export_to_markdown

__all__ = [
    "read_topics",
    "analyze_topic",
    "analyze_serp",
    "analyze_competitors",
    "analyze_query_network",
    "build_prompt_context",
    "build_internal_links",
    "build_brief",
    "export_to_markdown",
]
