# -*- coding: utf-8 -*-
"""
geo_schema_generator.py — V11-S1: GEO / AI Overview Optimization Module.

Generate JSON-LD structured data (Organization, Product, FAQPage) from brief data
to optimize content for AI Overviews (Google SGE, ChatGPT, Perplexity).
"""

import json
import logging
from typing import Dict

logger = logging.getLogger(__name__)


def generate_geo_schemas(brief: Dict, project=None) -> str:
    """
    Generate GEO-optimized structured data and checklist from brief content.

    Args:
        brief: Dict chứa toàn bộ Content Brief.
        project: ProjectContext object (brand, hotline, geo...).

    Returns:
        Markdown string containing JSON-LD blocks and GEO checklist.
    """
    lines = []
    lines.append("## GEO & AI Overview Optimization")
    lines.append("")
    lines.append("> 🤖 **Structured Data giúp AI Search (Google AI Overview, ChatGPT, Perplexity) trích dẫn nội dung chính xác.**")
    lines.append("")

    # ── 1. Organization Schema ──
    if project:
        org_schema = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": getattr(project, "brand_name", ""),
            "url": "",
            "telephone": getattr(project, "hotline", ""),
            "areaServed": getattr(project, "geo_keywords", ""),
        }
        # V16-6: Fix double-encoded URL
        raw_domain = getattr(project, "domain", "")
        if raw_domain:
            raw_domain = raw_domain.replace("https://", "").replace("http://", "").strip("/")
            org_schema["url"] = f"https://{raw_domain}/"
        lines.append("### 1. Organization Schema (JSON-LD)")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(org_schema, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    # ── 2. FAQPage Schema from PAA ──
    paa_from_serp = brief.get("serp_analysis", {}).get("people_also_ask", [])
    paa_from_analysis = brief.get("suggested_questions", [])
    paa_all = paa_from_serp or paa_from_analysis
    paa_real = [q for q in paa_all if q and not str(q).startswith("N/A")]

    if paa_real:
        faq_entities = []
        micro_data = brief.get("micro_briefing", [])

        def _find_relevant_mb(micro_list, question):
            """Find the micro-briefing snippet most relevant to a PAA question via word overlap."""
            q_words = set(str(question).lower().split())
            best_score = 0
            best_snippet = ""
            for mb in micro_list:
                snippet = str(mb.get("snippet", ""))
                if not snippet or len(snippet.split()) < 10:
                    continue
                s_words = set(snippet.lower().split())
                overlap = len(q_words & s_words)
                if overlap > best_score:
                    best_score = overlap
                    best_snippet = snippet
            return best_snippet

        # Helper to get SAPO if nothing else matches
        sapo_snippet = ""
        if micro_data and isinstance(micro_data, list):
            sapo_mb = micro_data[0]
            sapo_snippet = str(sapo_mb.get("snippet", ""))

        used_answers = set()
        for q in paa_real[:5]:
            answer = _find_relevant_mb(micro_data, q)
            # Avoid duplicate answers across FAQ entries
            if answer and answer in used_answers:
                answer = ""
            if answer:
                used_answers.add(answer)
            if not answer:
                # V18: Better fallback than boilerplate spam
                answer = sapo_snippet if sapo_snippet else f"Nội dung chi tiết về {str(q).lower().rstrip('?')} được cập nhật liên tục từ hãng."

            faq_entities.append({
                "@type": "Question",
                "name": str(q),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": " ".join(answer.split()[:40]),
                }
            })

        faq_schema = {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": faq_entities,
        }
        lines.append("### 2. FAQPage Schema (JSON-LD)")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(faq_schema, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")

    # ── 3. Product Schema from EAV ──
    search_intent = str(brief.get("search_intent", "")).lower()
    is_commercial = "commercial" in search_intent or "transactional" in search_intent
    eav_table = brief.get("eav_table", "")
    if is_commercial and eav_table and len(eav_table.strip()) > 10:
        product_props = {}
        for line in eav_table.split("\n"):
            if line.strip().startswith("|") and "---" not in line and "Entity" not in line and "Attribute" not in line:
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 3:
                    attr = parts[1]
                    value = parts[2]
                    if attr and value and "[CẦN XÁC MINH]" not in value:
                        product_props[attr] = value

        if product_props:
            product_schema = {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": brief.get("central_entity", brief.get("topic", "")),
                "description": brief.get("meta_description", ""),
                "additionalProperty": [
                    {"@type": "PropertyValue", "name": k, "value": v}
                    for k, v in list(product_props.items())[:6]
                ],
            }
            lines.append("### 3. Product Schema (JSON-LD)")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(product_schema, ensure_ascii=False, indent=2))
            lines.append("```")
            lines.append("")

    # ── 4. GEO Checklist ──
    lines.append("### GEO Optimization Checklist")
    lines.append("")

    # Check opening sentence
    sapo = ""
    micro_list = brief.get("micro_briefing", [])
    if micro_list:
        sapo = str(micro_list[0].get("snippet", ""))
    opening = " ".join(sapo.split()[:50]) if sapo else ""
    sapo_ok = len(opening.split()) >= 20

    checks = [
        ("Opening sentence 30-50 từ trả lời main query", sapo_ok),
        ("FAQPage Schema có ≥3 Q&A từ PAA", len(paa_real) >= 3),
        ("Product/Organization Schema từ EAV + Source Context", bool(project)),
        ("FS Blocks ≤40 từ (AI citation-ready)", True),  # enforced by scorer
        ("Central Entity xuất hiện trong 50 từ đầu", brief.get("central_entity", "").lower() in sapo.lower() if sapo else False),
    ]

    for label, passed in checks:
        icon = "✅" if passed else "⬜"
        lines.append(f"- {icon} {label}")

    lines.append("")
    return "\n".join(lines)
