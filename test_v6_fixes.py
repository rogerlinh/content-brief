"""
Test V6 Fixes - Content Brief Generator
Writes results to test_results.txt (UTF-8) to avoid Windows encoding issues.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.topic_analyzer import _classify_intent
from modules.content_brief_builder import (
    _get_min_h2_for_intent,
    _get_min_h2_for_vs_symmetry,
    _postprocess_supp_enforcer,
    _postprocess_prominence_blacklist,
)
from modules.internal_linking import _generate_anchor_variants, _pick_anchor
from modules.koray_analyzer import calculate_quality_score
from modules.serp_competitor_analyzer import _classify_serp_intent

RESULTS = []
PASS_COUNT = 0
FAIL_COUNT = 0

def log(msg):
    RESULTS.append(msg)

def check(label, condition):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        log(f"  [PASS] {label}")
    else:
        FAIL_COUNT += 1
        log(f"  [FAIL] {label}")


def test_intent_detection():
    log("=== Fix 1: Intent Detection ===")
    cases = [
        ("thép tấm và thép cuộn khác nhau", "vs"),
        ("nên chọn iD14 hay là iD4", "vs"),
        ("động cơ bước là gì", "informational"),
        ("cách sửa vòi hoa sen", "informational"),  # 'cách' is in informational bucket
        ("thép tấm và thép cuộn khác nhau thế nào", "vs"),
        ("so sánh máy khoan Bosch và Makita", "vs"),
        ("giá thép hình chữ H hôm nay", "transactional"),  # 'giá' is in transactional bucket
    ]
    for topic, expected in cases:
        result = _classify_intent(topic)
        check(f"'{topic}' -> {result} (expected {expected})", result == expected)


def test_h2_min():
    log("\n=== Fix 2: H2 Minimum by Intent ===")
    check("vs -> 5", _get_min_h2_for_intent("vs") == 5)
    check("informational -> 4", _get_min_h2_for_intent("informational") == 4)
    check("how-to -> 4", _get_min_h2_for_intent("how-to") == 4)
    check("general -> 3", _get_min_h2_for_intent("general") == 3)


def test_vs_symmetry():
    log("\n=== Fix 3b: VS Symmetry Check ===")
    outline_pass = [
        {"level": "H2", "text": "Định nghĩa thép tấm"},
        {"level": "H2", "text": "Thép cuộn là gì"},
        {"level": "H2", "text": "So sánh thép tấm và thép cuộn"},
    ]
    outline_fail = [
        {"level": "H2", "text": "Định nghĩa thép tấm"},
        {"level": "H2", "text": "Thép cuộn là gì"},
    ]
    check("With comparison H2 -> True", _get_min_h2_for_vs_symmetry(outline_pass) is True)
    check("Without comparison H2 -> False", _get_min_h2_for_vs_symmetry(outline_fail) is False)


def test_anchor_text():
    log("\n=== Fix 4: Anchor Text ===")
    v1 = _generate_anchor_variants("[MAIN] Tong quan: Cac loai thep", "thep")
    check("Exact reorders entity:attr", ":" not in v1["exact"] or "tong quan" not in v1["exact"])
    check("Has 'primary' key", "primary" in v1)

    v2 = _generate_anchor_variants("Bang bao gia xi mang", "xi mang")
    check("Semantic uses 'gia' verb", "gia" in v2["semantic"].lower())

    v3 = _generate_anchor_variants("May han TIG la gi", "may han")
    check("Question adds 'la gi?' for definition", "la gi" in v3["question"].lower())

    v4 = _generate_anchor_variants("[MAIN] Huong dan thi cong thep hinh", "thep")
    check("No 'tai sao nen' in any variant",
          all("tai sao nen" not in val.lower() for val in v4.values()))
    check("No 'khi nao can' in any variant",
          all("khi nao can" not in val.lower() for val in v4.values()))


def test_supp_enforcer():
    log("\n=== Fix 6: SUPP Enforcer + PAA FAQ ===")
    headings = [
        {"level": "H2", "text": "[MAIN] Tinh nang chinh"},
        {"level": "H2", "text": "[MAIN] Uu nhuoc diem"},
        {"level": "H2", "text": "[MAIN] Gia ban"},
        {"level": "H2", "text": "[MAIN] Ung dung"},
    ]
    paa = ["San pham nay co tot khong?", "Nen mua o dau?", "Bao hanh bao lau?"]
    result = _postprocess_supp_enforcer(headings, "May khoan Bosch", "informational", paa_questions=paa)

    h2_texts = [h["text"] for h in result if h.get("level") == "H2"]
    h3_texts = [h["text"] for h in result if h.get("level") == "H3"]

    has_faq = any("faq" in t.lower() or "FAQ" in t for t in h2_texts)
    has_supp = any("[SUPP]" in t for t in h2_texts)
    has_antonym = any(
        any(s in t.lower() for s in ["không nên", "sai lầm", "không phù hợp"])
        for t in h2_texts
    )

    check("FAQ H2 created", has_faq)
    check("SUPP prefix exists", has_supp)
    check("Antonym ending exists", has_antonym)
    check("PAA H3s added (>=1)", len(h3_texts) >= 1)

    log(f"  Output headings ({len(result)} total):")
    for h in result:
        log(f"    {h['level']}: {h['text']}")


def test_koray_prominence_penalty():
    log("\n=== Fix 5: Koray Prominence Penalty ===")
    headings = [
        {"level": "H2", "text": "[MAIN] Dinh nghia may in"},
        {"level": "H2", "text": "[MAIN] Phan loai may in"},
        {"level": "H2", "text": "[MAIN] Thong so may in"},
        {"level": "H2", "text": "[MAIN] Lich su ra doi"},
        {"level": "H2", "text": "[SUPP] FAQ ve may in"},
    ]
    brief = {
        "search_intent": {"type": "informational"},
        "serp_analysis": {
            "information_gain": {
                "rare_headings": ["Lich su ra doi"],
            },
            "people_also_ask": ["May in nao tot nhat?", "Gia may in la bao nhieu?"],
        },
    }
    result = calculate_quality_score(brief, headings)
    check("Returns a string (markdown table)", isinstance(result, str))
    check("Contains PROMINENCE PENALTY", "PROMINENCE" in result.upper() or "prominence" in result.lower())
    log(f"  Score output (first 300 chars): {result[:300]}")


def test_serp_intent_classifier():
    log("\n=== V7 Fix 1b: SERP Intent Classifier (VS Bucket) ===")
    serp_data_vs = {
        "organic_results": [
            {"title": "So sánh thép tấm và thép cuộn", "snippet": "Bài viết so sánh ưu nhược điểm..."},
            {"title": "Thép cuốn khác gì thép tấm?", "snippet": "Sự khác biệt cơ bản là..."},
            {"title": "Nên chọn thép tấm hay thép cuộn?", "snippet": "Bảng so sánh chi tiết..."},
        ],
        "people_also_ask": [],
        "things_to_know": []
    }
    result = _classify_serp_intent(serp_data_vs)
    check("Correctly detects 'vs' intent from SERP", result == "vs")


def test_prominence_blacklist():
    log("\n=== V7 Fix 2: Prominence Blacklist + B2B Auto-detect ===")
    headings = [
        {"level": "H2", "text": "Định nghĩa thép tấm"},
        {"level": "H2", "text": "Thép tấm: Lợi ích môi trường"},
        {"level": "H2", "text": "Quy trình chế tạo thép cuộn"},
        {"level": "H2", "text": "Lịch sử phát triển ngành thép"},
        {"level": "H2", "text": "Ứng dụng trong xây dựng"},
    ]
    # No project passed, but topic "thép" should trigger B2B auto-detect
    result = _postprocess_prominence_blacklist(headings, project=None, topic="giá thép hôm nay")
    remaining_texts = [h["text"].lower() for h in result]
    
    check("Lợi ích môi trường is removed", not any("lợi ích" in t for t in remaining_texts))
    check("Quy trình chế tạo is removed", not any("quy trình" in t for t in remaining_texts))
    check("Lịch sử phát triển is removed", not any("lịch sử" in t for t in remaining_texts))
    check("Valid headings retained", any("định nghĩa" in t for t in remaining_texts))


def test_primary_anchor():
    log("\n=== V7 Fix 3: Primary Anchor ===")
    variants = {
        "exact": "thép thanh vằn là gì",
        "semantic": "khái niệm thép thanh vằn",
        "question": "thép thanh vằn là gì?",
        "primary": "thép thanh vằn là gì"
    }
    # Deterministic pick
    anchor1 = _pick_anchor(variants)
    anchor2 = _pick_anchor(variants)
    check("Always chooses primary without random behavior", anchor1 == "thép thanh vằn là gì" and anchor1 == anchor2)


if __name__ == "__main__":
    test_intent_detection()
    test_h2_min()
    test_vs_symmetry()
    test_anchor_text()
    test_supp_enforcer()
    test_koray_prominence_penalty()
    test_serp_intent_classifier()
    test_prominence_blacklist()
    test_primary_anchor()

    log(f"\n{'='*40}")
    log(f"TOTAL: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    log(f"{'='*40}")

    # Write results to UTF-8 file
    output_path = os.path.join(os.path.dirname(__file__), "test_results.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(RESULTS))

    # Also print summary to console (ASCII safe)
    print(f"Tests complete: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"Full results written to: {output_path}")
