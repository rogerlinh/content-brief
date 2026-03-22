"""
Test V21 S-Tier Prompts — Direct Agent 1 + Agent 2 invocation.
Bypasses build_brief and calls rewrite_headings_semantic directly.
"""
import json
import logging
import os
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
load_dotenv()

from modules.content_brief_builder import (
    rewrite_headings_semantic,
    detect_niche,
)

def main():
    topic = "So sánh thép thanh vằn và thép hình"
    intent = "commercial"
    niche = detect_niche(topic)

    # Minimal mock headings — Agent 1 raw output simulation
    raw_headings = [
        {"level": "H2", "text": "Thép thanh vằn là gì?"},
        {"level": "H2", "text": "Đặc điểm thép hình"},
        {"level": "H2", "text": "So sánh chi phí thép thanh vằn và thép hình"},
        {"level": "H2", "text": "Ứng dụng trong xây dựng"},
        {"level": "H2", "text": "Bảng quy cách tiêu chuẩn"},
    ]

    logging.info("=== V21 TEST: Calling rewrite_headings_semantic (Agent 2) ===")
    logging.info("Topic: %s | Intent: %s | Niche: %s", topic, intent, niche)
    logging.info("Input headings: %d H2s", len(raw_headings))

    enriched = rewrite_headings_semantic(
        raw_headings, topic, niche, intent,
        serp_data=None,
        competitor_data=None,
        methodology_prompt="",
    )

    print("\n" + "=" * 60)
    print("ENRICHED HEADING STRUCTURE (Agent 2 Output):")
    print("=" * 60)
    for h in enriched:
        prefix = "  " if h.get("level") == "H3" else ""
        print(f'{prefix}{h["level"]}: {h["text"]}')
    print("=" * 60)

    with open("output.json", "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    logging.info("Saved %d headings to output.json", len(enriched))

if __name__ == "__main__":
    main()
