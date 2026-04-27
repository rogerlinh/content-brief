from __future__ import annotations

from typing import Any


def test_analyze_serp_contract_shape(monkeypatch) -> None:
    import modules.serp_competitor_analyzer as analyzer

    async def fake_scrape_google_serp(topic: str, headless: bool) -> dict[str, Any]:
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Hang hoa phai sinh la gi?",
                    "url": "https://example.com/guide",
                    "snippet": "Tong quan ve hang hoa phai sinh",
                },
                {
                    "position": 2,
                    "title": "So sanh hang hoa phai sinh va chung khoan",
                    "url": "https://example.com/compare",
                    "snippet": "Phan biet va lua chon",
                },
                {
                    "position": 3,
                    "title": "Mo tai khoan giao dich hang hoa phai sinh",
                    "url": "https://example.com/signup",
                    "snippet": "Huong dan dang ky",
                },
            ],
            "people_also_ask": [
                "Hang hoa phai sinh la gi?",
                "Co che ky quy nhu the nao?",
            ],
            "things_to_know": ["Ky quy", "Don bay"],
            "related_searches": ["giao dich hang hoa phai sinh"],
            "featured_snippet": {"text": "Tom tat khai niem"},
            "knowledge_panel": {},
            "serp_features": ["featured_snippet", "people_also_ask"],
            "serp_source": "serper_google",
        }

    monkeypatch.setattr(analyzer, "_scrape_google_serp", fake_scrape_google_serp)

    result = analyzer.analyze_serp("hang hoa phai sinh la gi")

    required_keys = {
        "organic_results",
        "people_also_ask",
        "things_to_know",
        "related_searches",
        "top_urls",
        "serp_entities",
        "serp_attributes",
        "topic_clusters",
        "dominant_intent",
        "featured_snippet",
        "knowledge_panel",
        "serp_features",
        "result_format_counts",
        "dominant_format",
        "serp_source",
        "intent_distribution",
        "intent_decision",
        "result_intents",
    }
    assert required_keys.issubset(result.keys())
    assert result["serp_source"] == "serper_google"
    assert isinstance(result["top_urls"], list)
    assert isinstance(result["intent_distribution"], dict)
    assert result["intent_decision"]["selected_intent"] in {
        "informational",
        "commercial investigation",
        "transactional",
        "navigational",
    }
    assert result["intent_decision"]["source"] == "serper_google"
    assert len(result["result_intents"]) == len(result["organic_results"])


def test_analyze_competitors_contract_shape(monkeypatch) -> None:
    import modules.serp_competitor_analyzer as analyzer

    async def fake_scrape_competitors(urls, headless: bool):
        return [
            {
                "url": urls[0],
                "headings": [
                    {"level": "H1", "text": "Hang hoa phai sinh la gi"},
                    {"level": "H2", "text": "Tong quan"},
                    {"level": "H2", "text": "Cach hoat dong"},
                ],
                "body_text": "Hang hoa phai sinh la hop dong tai san co so. Ky quy giup quan ly rui ro.",
                "content_blocks": ["Hang hoa phai sinh la hop dong tai san co so."],
                "word_count": 120,
                "ngrams_2": [("hang hoa", 5), ("phai sinh", 4)],
                "ngrams_3": [("hang hoa phai", 3)],
                "source": "requests_fallback",
            },
            {
                "url": urls[1],
                "headings": [
                    {"level": "H1", "text": "Huong dan giao dich"},
                    {"level": "H2", "text": "Tong quan"},
                    {"level": "H2", "text": "Rui ro"},
                ],
                "body_text": "Giao dich hang hoa phai sinh can hieu ky quy, don bay va rui ro.",
                "content_blocks": ["Giao dich hang hoa phai sinh can hieu ky quy."],
                "word_count": 110,
                "ngrams_2": [("ky quy", 4), ("rui ro", 2)],
                "ngrams_3": [("hang hoa phai", 2)],
                "source": "requests_fallback",
            },
        ]

    monkeypatch.setattr(analyzer, "_scrape_competitors", fake_scrape_competitors)

    result = analyzer.analyze_competitors(
        ["https://example.com/a", "https://example.com/b"],
        "hang hoa phai sinh la gi",
    )

    required_keys = {
        "competitors",
        "common_headings",
        "ngrams_2",
        "ngrams_3",
        "information_gain",
        "heading_frequency_matrix",
        "intent_distribution",
        "intent_decision",
        "content_intents",
        "content_archetypes",
        "archetype_summary",
    }
    assert required_keys.issubset(result.keys())
    assert len(result["competitors"]) == 2
    assert isinstance(result["common_headings"], list)
    assert isinstance(result["information_gain"], dict)
    assert isinstance(result["heading_frequency_matrix"], dict)
    assert result["intent_decision"]["selected_intent"] in {
        "informational",
        "commercial investigation",
        "transactional",
        "navigational",
    }
    assert all("content_intent" in row for row in result["competitors"])
    assert "selected_archetype" in result["archetype_summary"]


def test_build_brief_serp_analysis_contract_shape(monkeypatch) -> None:
    import modules.content_brief_builder as builder

    monkeypatch.setattr(builder, "detect_niche", lambda topic, project_industry="": "general")
    monkeypatch.setattr(
        builder,
        "_classify_ngrams",
        lambda *args, **kwargs: {"all_clean": [], "entity": [], "action": []},
    )
    monkeypatch.setattr(
        builder,
        "refine_paa_questions_for_project",
        lambda **kwargs: {"faq_questions": ["FAQ 1"], "supp_questions": ["SUPP 1"]},
    )
    monkeypatch.setattr(
        builder,
        "_derive_outline_consensus_signals",
        lambda *args, **kwargs: {
            "consensus_points": [],
            "gap_h2_candidates": [],
            "gap_h3_candidates": [],
            "coverage_notes": [],
        },
    )
    monkeypatch.setattr(
        builder,
        "_build_semantic_reasoning",
        lambda *args, **kwargs: {
            "verified_eav_rows": [],
            "enriched_candidate_rows": [],
            "eav_quality": {},
        },
    )
    monkeypatch.setattr(
        builder,
        "render_eav_markdown",
        lambda rows, fallback_table="", limit=12: fallback_table or "| Entity | Attribute | Value |",
    )
    monkeypatch.setattr(
        builder,
        "rewrite_headings_semantic",
        lambda *args, **kwargs: [
            {"level": "H2", "text": "Tong quan"},
            {"level": "H3", "text": "Dinh nghia"},
        ],
    )
    monkeypatch.setattr(
        builder,
        "_agent_micro_briefing_writer",
        lambda *args, **kwargs: [
            {
                "h2": "Tong quan",
                "snippet": " ".join(["noi-dung"] * 90),
                "bridge": "",
                "guidance": "",
            }
        ],
    )
    monkeypatch.setattr(builder, "_generate_content_guidelines", lambda *args, **kwargs: ["Guideline"])
    monkeypatch.setattr(
        builder,
        "_generate_linking_suggestions",
        lambda *args, **kwargs: {"outbound_nodes": []},
    )
    monkeypatch.setattr(builder, "_generate_eeat_checklist", lambda *args, **kwargs: ["Checklist"])
    monkeypatch.setattr(builder, "_normalize_micro_briefing_data", lambda *args, **kwargs: False)
    monkeypatch.setattr(builder, "_apply_koray_micro_postprocess", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        builder,
        "build_outline_content_framework",
        lambda brief, project=None: {"appendix_markdown": "ok"},
    )

    analysis = {
        "central_entity": "Hang hoa phai sinh",
        "search_intent": "informational",
        "entity_attributes": {"dinh nghia": "mo ta"},
        "heading_structure": [{"level": "H2", "text": "Tong quan"}],
        "suggested_questions": ["Q1"],
        "related_topics": ["Topic A"],
    }
    serp_data = {
        "organic_results": [{"position": 1, "title": "A", "url": "https://example.com/a", "snippet": "B"}],
        "top_urls": ["https://example.com/a"],
        "people_also_ask": ["PAA 1"],
        "things_to_know": ["Thing 1"],
        "related_searches": ["Related 1"],
        "serp_entities": {"primary": ["Hang hoa phai sinh"]},
        "serp_attributes": ["Ky quy"],
        "topic_clusters": ["Cluster 1"],
        "dominant_intent": "informational",
        "intent_distribution": {"informational": {"percentage": 80.0}},
        "intent_decision": {
            "selected_intent": "informational",
            "source": "serper_google",
            "source_confidence": "high",
        },
        "result_intents": [{"position": 1, "intent": "informational"}],
        "serp_source": "serper_google",
        "featured_snippet": {"text": "demo"},
        "knowledge_panel": {},
        "serp_features": ["featured_snippet"],
        "result_format_counts": {"Blog/Article": 1},
        "dominant_format": "Blog/Article",
    }
    competitor_data = {
        "competitors": [
            {
                "url": "https://example.com/a",
                "headings": [{"level": "H2", "text": "Tong quan"}],
                "word_count": 123,
                "content_intent": "informational",
            }
        ],
        "common_headings": ["Tong quan"],
        "ngrams_2": [("hang hoa", 2)],
        "ngrams_3": [("hang hoa phai", 1)],
        "information_gain": {"rare_headings": ["Rui ro"]},
        "heading_frequency_matrix": {"competitors": [{"url": "https://example.com/a", "h2": ["Tong quan"]}]},
        "intent_distribution": {"informational": {"percentage": 75.0}},
        "intent_decision": {
            "selected_intent": "informational",
            "source": "competitor_full_body",
            "source_confidence": "low",
        },
        "content_intents": [{"position": 1, "intent": "informational"}],
        "content_archetypes": [{"position": 1, "archetype": "explainer"}],
        "archetype_summary": {
            "selected_archetype": "explainer",
            "top_archetypes": [{"archetype": "explainer", "percentage": 80.0}],
            "rationale": "Top competitor bodies skew toward explainer.",
        },
    }

    brief = builder.build_brief(
        "hang hoa phai sinh la gi",
        analysis,
        serp_data=serp_data,
        competitor_data=competitor_data,
    )

    required_serp_keys = {
        "organic_results",
        "top_urls_display",
        "people_also_ask",
        "people_also_ask_rewritten",
        "things_to_know",
        "related_searches",
        "serp_entities",
        "serp_attributes",
        "topic_clusters",
        "dominant_intent",
        "intent_distribution",
        "intent_decision",
        "competitor_body_intent_distribution",
        "competitor_body_intent_decision",
        "final_intent_decision",
        "result_intents",
        "serp_source",
        "featured_snippet",
        "knowledge_panel",
        "serp_features",
        "result_format_counts",
        "dominant_format",
        "information_gain",
    }
    assert required_serp_keys.issubset(brief["serp_analysis"].keys())
    assert brief["serp_analysis"]["intent_decision"]["selected_intent"] == "informational"
    assert brief["serp_analysis"]["competitor_body_intent_decision"]["selected_intent"] in {
        "",
        "informational",
        "commercial investigation",
        "transactional",
        "navigational",
    }
    assert brief["serp_analysis"]["final_intent_decision"]["selected_intent"] == "informational"
    assert brief["serp_analysis"]["information_gain"]["rare_headings"] == ["Rui ro"]
    assert brief["competitor_analysis"]["competitor_count"] == 1
    assert brief["outline_content_framework"] == {"appendix_markdown": "ok"}


def test_outline_content_framework_shape() -> None:
    from modules.outline_content_adapter import build_outline_content_framework

    brief = {
        "seed_keyword": "hang hoa phai sinh la gi",
        "topic": "hang hoa phai sinh la gi",
        "search_intent": {"type": "Informational"},
        "central_entity": "Hang hoa phai sinh",
        "heading_structure": [
            {"level": "H2", "text": "Tong quan"},
            {"level": "H3", "text": "Dinh nghia"},
            {"level": "H2", "text": "Cach hoat dong"},
        ],
        "title_tag": "Title",
        "meta_description": "Desc",
        "entity_attributes": {"ky quy": "co che"},
        "faq_questions": ["Hang hoa phai sinh la gi?"],
        "micro_briefing": [
            {
                "h2": "Tong quan",
                "snippet": " ".join(["noi-dung"] * 90),
                "bridge": "",
                "guidance": "",
            }
        ],
        "internal_linking": {"outbound_nodes": []},
        "serp_analysis": {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Hang hoa phai sinh la gi",
                    "url": "https://example.com/a",
                    "snippet": "Giai thich khai niem",
                }
            ],
            "people_also_ask": ["Hang hoa phai sinh la gi?"],
            "people_also_ask_rewritten": ["Hang hoa phai sinh la gi?"],
            "things_to_know": ["Co che giao dich"],
            "related_searches": ["giao dich hang hoa phai sinh"],
            "serp_entities": {"primary": ["Hang hoa phai sinh"], "secondary": ["Ky quy"]},
            "serp_attributes": ["Ky quy"],
            "topic_clusters": ["Khai niem"],
            "dominant_intent": "informational",
            "intent_distribution": {
                "informational": {"percentage": 70.0},
                "commercial investigation": {"percentage": 20.0},
                "transactional": {"percentage": 10.0},
                "navigational": {"percentage": 0.0},
            },
            "intent_decision": {
                "selected_intent": "informational",
                "secondary_intent": "commercial investigation",
                "rationale": "demo",
                "source": "serper_google",
                "source_confidence": "high",
            },
            "result_intents": [{"position": 1, "intent": "informational", "url": "https://example.com/a"}],
            "serp_source": "serper_google",
            "featured_snippet": {"text": "demo"},
            "knowledge_panel": {},
            "serp_features": ["featured_snippet"],
            "result_format_counts": {"Blog/Article": 1},
            "dominant_format": "Blog/Article",
            "information_gain": {"rare_headings": ["Rui ro"]},
        },
        "competitor_analysis": {
            "common_headings": ["Tong quan"],
            "ngrams_2": [("hang hoa", 5)],
            "ngrams_3": [("hang hoa phai", 3)],
            "heading_frequency_matrix": {"competitors": [{"url": "https://example.com/a", "h2": ["Tong quan"]}]},
            "information_gain": {"rare_headings": ["Rui ro"]},
            "competitor_count": 1,
            "competitors_detail": [
                {
                    "url": "https://example.com/a",
                    "headings": [{"level": "H2", "text": "Tong quan"}],
                    "word_count": 1000,
                }
            ],
            "competitors_summary": [{"url": "https://example.com/a", "heading_count": 1, "word_count": 1000}],
        },
    }

    framework = build_outline_content_framework(brief)

    required_keys = {
        "input_mode",
        "article_language",
        "page_type",
        "serp_analysis_summary",
        "heading_frequency_matrix",
        "entity_map",
        "keyword_map",
        "outline_package",
        "meta_schema_package",
        "writer_briefing_markdown",
        "appendix_markdown",
    }
    assert required_keys.issubset(framework.keys())
    assert framework["serp_analysis_summary"]["serp_source"] == "Google via Serper.dev"
    assert isinstance(framework["entity_map"], list)
    assert isinstance(framework["keyword_map"], dict)
    assert isinstance(framework["outline_package"], dict)
    assert "Writer Briefing" in framework["appendix_markdown"]
