import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.serp_competitor_analyzer import (
    _analyze_competitor_intent_mix,
    _analyze_competitor_archetype_mix,
    _analyze_serp_intent_mix,
    _classify_competitor_content_archetype,
    _classify_competitor_content_intent,
    _classify_serp_intent,
)
from modules.content_brief_builder import (
    _ensure_competitor_archetype_coverage,
    _merge_intent_decisions,
)


def test_intent_mix_prefers_informational_when_google_serp_is_explainer_heavy():
    serp_data = {
        "organic_results": [
            {
                "position": 1,
                "title": "Hang hoa phai sinh la gi? Khai niem va co che hoat dong",
                "url": "https://example.com/hang-hoa-phai-sinh-la-gi",
                "snippet": "Giai thich dinh nghia, dac diem va cac ben tham gia thi truong.",
            },
            {
                "position": 2,
                "title": "Huong dan tim hieu hang hoa phai sinh cho nguoi moi",
                "url": "https://example.com/huong-dan-hang-hoa-phai-sinh",
                "snippet": "Tong quan ve ky quy, hop dong tuong lai va cach van hanh.",
            },
            {
                "position": 3,
                "title": "Co che giao dich hang hoa phai sinh nhu the nao?",
                "url": "https://example.com/co-che-giao-dich",
                "snippet": "Giai dap quy trinh giao dich, ky quy va thanh toan.",
            },
            {
                "position": 4,
                "title": "Review san giao dich hang hoa phai sinh",
                "url": "https://example.com/review-san-giao-dich",
                "snippet": "Danh gia uu nhuoc diem cua tung nen tang.",
            },
        ],
        "people_also_ask": [
            "Hang hoa phai sinh la gi?",
            "Ky quy trong hang hoa phai sinh la gi?",
            "Giao dich hang hoa phai sinh co rui ro khong?",
        ],
        "things_to_know": ["Thi truong hoat dong theo co che ky quy."],
        "serp_source": "serper_google",
    }

    profile = _analyze_serp_intent_mix(serp_data, topic="hang hoa phai sinh la gi")

    assert profile["selected_intent"] == "informational"
    assert profile["distribution"]["informational"]["percentage"] > profile["distribution"]["commercial investigation"]["percentage"]
    assert profile["source_confidence"] == "high"
    assert _classify_serp_intent(serp_data, topic="hang hoa phai sinh la gi") == "informational"


def test_intent_mix_maps_comparison_serp_to_commercial_investigation_but_keeps_vs_legacy():
    serp_data = {
        "organic_results": [
            {
                "position": 1,
                "title": "So sanh thep tam va thep cuon: khac nhau o dau?",
                "url": "https://example.com/so-sanh-thep-tam-thep-cuon",
                "snippet": "Bang so sanh thong so, ung dung va gia thanh.",
            },
            {
                "position": 2,
                "title": "Thep tam vs thep cuon: nen chon loai nao?",
                "url": "https://example.com/thep-tam-vs-thep-cuon",
                "snippet": "Danh gia uu nhuoc diem theo tung nhu cau.",
            },
            {
                "position": 3,
                "title": "Review thep tam va thep cuon cho du an cong nghiep",
                "url": "https://example.com/review-thep-tam-thep-cuon",
                "snippet": "Phan tich khi nao nen dung moi loai vat lieu.",
            },
        ],
        "people_also_ask": [],
        "things_to_know": [],
        "serp_source": "google_html",
    }

    profile = _analyze_serp_intent_mix(serp_data, topic="thep tam va thep cuon khac nhau nhu the nao")

    assert profile["selected_intent"] == "commercial investigation"
    assert profile["selected_intent_legacy"] == "vs"
    assert _classify_serp_intent(serp_data, topic="thep tam va thep cuon khac nhau nhu the nao") == "vs"


def test_intent_mix_marks_duckduckgo_as_low_confidence_and_can_still_choose_transactional():
    serp_data = {
        "organic_results": [
            {
                "position": 1,
                "title": "Bao gia go MDF chong am",
                "url": "https://example.com/bao-gia/go-mdf",
                "snippet": "Cap nhat bang gia va lien he dat hang nhanh.",
            },
            {
                "position": 2,
                "title": "Go MDF chong am - san pham va quy cach",
                "url": "https://example.com/san-pham/go-mdf-chong-am",
                "snippet": "Thong so, ton kho va huong dan dat mua.",
            },
            {
                "position": 3,
                "title": "Mua go MDF chong am o dau?",
                "url": "https://example.com/mua-go-mdf",
                "snippet": "Lien he de nhan bao gia va tu van don hang.",
            },
        ],
        "people_also_ask": [],
        "things_to_know": [],
        "serp_source": "duckduckgo_html",
    }

    profile = _analyze_serp_intent_mix(serp_data, topic="mua go mdf chong am")

    assert profile["selected_intent"] == "transactional"
    assert profile["source_confidence"] == "low"
    assert "DuckDuckGo" in profile["rationale"]


def test_competitor_full_body_intent_detects_transactional_pages_from_body_and_headings():
    competitor = {
        "url": "https://example.com/bao-gia/go-mdf",
        "headings": [
            {"level": "H1", "text": "Bao gia go MDF chong am"},
            {"level": "H2", "text": "Bang gia moi nhat"},
            {"level": "H2", "text": "Lien he dat hang"},
        ],
        "body_text": (
            "Bao gia go MDF chong am duoc cap nhat theo quy cach. "
            "Lien he de nhan bao gia, tu van va dat hang nhanh."
        ),
        "content_blocks": [
            "Bang gia moi nhat theo do day.",
            "Lien he de nhan bao gia va dat hang.",
        ],
        "word_count": 220,
    }

    classification = _classify_competitor_content_intent(competitor, topic="bao gia go mdf chong am")

    assert classification["intent"] == "transactional"
    assert classification["confidence"] > 0.3


def test_competitor_full_body_mix_can_override_mixed_serp_when_bodies_are_clear():
    competitors = [
        {
            "url": "https://example.com/a",
            "serp_position": 1,
            "content_intent": "transactional",
            "content_intent_subtype": "lead-gen",
            "content_intent_confidence": 0.71,
            "content_intent_format": "Landing page",
            "content_intent_reasons": ["landing/service content format"],
            "word_count": 240,
            "body_text": "Bao gia va lien he dat hang",
        },
        {
            "url": "https://example.com/b",
            "serp_position": 2,
            "content_intent": "transactional",
            "content_intent_subtype": "lead-gen",
            "content_intent_confidence": 0.69,
            "content_intent_format": "Product/Category",
            "content_intent_reasons": ["product/category content format"],
            "word_count": 260,
            "body_text": "Bang gia va dat lich tu van",
        },
        {
            "url": "https://example.com/c",
            "serp_position": 3,
            "content_intent": "transactional",
            "content_intent_subtype": "purchase",
            "content_intent_confidence": 0.66,
            "content_intent_format": "Product/Category",
            "content_intent_reasons": ["transactional path"],
            "word_count": 230,
            "body_text": "Dat mua va gui yeu cau bao gia",
        },
    ]

    competitor_profile = _analyze_competitor_intent_mix(competitors, topic="bao gia go mdf chong am")
    merged = _merge_intent_decisions(
        topic_intent="informational",
        serp_decision={
            "selected_intent": "informational",
            "source_confidence": "high",
            "dominance_share": 0.51,
            "is_mixed": True,
        },
        competitor_decision=competitor_profile,
    )

    assert competitor_profile["selected_intent"] == "transactional"
    assert merged["selected_intent"] == "transactional"


def test_competitor_content_archetype_detects_pricing_pattern_from_full_body():
    competitor = {
        "url": "https://example.com/phi-giao-dich",
        "headings": [
            {"level": "H1", "text": "Phi giao dich hang hoa phai sinh"},
            {"level": "H2", "text": "Cach tinh phi giao dich"},
            {"level": "H2", "text": "Cac yeu to anh huong den chi phi"},
        ],
        "body_text": (
            "Phi giao dich hang hoa phai sinh duoc tinh theo tung hop dong va tung so lot. "
            "Chi phi thay doi theo san pham, thanh khoan va quy dinh phi hien hanh."
        ),
        "content_blocks": [
            "Cach tinh phi theo tung hop dong va so lot.",
            "Chi phi thay doi theo tung nhom san pham.",
        ],
        "content_intent": "informational",
        "content_intent_format": "Blog/Article",
        "word_count": 620,
    }

    archetype = _classify_competitor_content_archetype(competitor, topic="phi giao dich hang hoa phai sinh")

    assert archetype["archetype"] == "pricing"
    assert archetype["confidence"] > 0.2


def test_competitor_archetype_coverage_does_not_inject_canned_sections():
    headings = [
        {"level": "H1", "text": "Phi giao dich hang hoa phai sinh"},
        {"level": "H2", "text": "[MAIN] Phi giao dich hang hoa phai sinh: Định nghĩa và phạm vi áp dụng"},
        {"level": "H3", "text": "Phi giao dich là gì?"},
    ]

    enriched = _ensure_competitor_archetype_coverage(
        headings,
        "phi giao dich hang hoa phai sinh",
        "informational",
        outline_signals={"competitor_archetypes": ["pricing", "risk"]},
    )

    h2_texts = [item["text"] for item in enriched if item.get("level") == "H2"]
    assert enriched == headings
    assert len(h2_texts) == 1


def test_competitor_archetype_mix_summarizes_top_patterns():
    competitors = [
        {"url": "https://example.com/a", "serp_position": 1, "content_archetype": "pricing", "content_archetype_confidence": 0.6, "word_count": 500},
        {"url": "https://example.com/b", "serp_position": 2, "content_archetype": "pricing", "content_archetype_confidence": 0.55, "word_count": 450},
        {"url": "https://example.com/c", "serp_position": 3, "content_archetype": "risk", "content_archetype_confidence": 0.5, "word_count": 430},
    ]

    summary = _analyze_competitor_archetype_mix(competitors)

    assert summary["selected_archetype"] == "pricing"
    assert summary["top_archetypes"][0]["archetype"] == "pricing"
