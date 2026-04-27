import os
import sys
import unicodedata

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.content_brief_builder import (
    _align_outline_to_preferred_flow,
    _apply_semantic_outline_gate,
    _build_semantic_blueprint,
    _normalize_micro_briefing_data,
)
from modules.koray_analyzer import generate_outline_readiness_report
from modules.outline_content_adapter import _is_quality_phrase
from modules.serp_competitor_analyzer import (
    _classify_serp_intent,
    _filter_serp_results_by_topic,
)
from modules.topic_analyzer import _generate_heading_structure


def _plain(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value.replace("đ", "d").replace("Đ", "D").lower()


def test_micro_brief_normalization():
    brief = {
        "topic": "hang hoa phai sinh la gi",
        "central_entity": "hang hoa phai sinh",
        "content_gaps": ["Canh bao an toan khi giao dich phai sinh"],
        "heading_structure": [
            {"level": "H2", "text": "[MAIN] Hang hoa phai sinh la gi?"},
            {"level": "H3", "text": "Hang hoa phai sinh duoc dinh nghia nhu the nao?"},
            {"level": "H3", "text": "Nhung san pham nao duoc giao dich tren thi truong phai sinh?"},
            {"level": "H2", "text": "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh"},
            {"level": "H3", "text": "Ky quy thap la gi?"},
            {"level": "H2", "text": "[SUPP] FAQ ve hang hoa phai sinh"},
        ],
        "micro_briefing": [
            {"h2": "SAPO (Doan mo dau)", "snippet": "ngan qua"},
            {
                "h2": "[MAIN] Hang hoa phai sinh la gi?",
                "snippet": "Section nay phan tich hang hoa phai sinh theo semantic SEO.",
                "analysis": "Section nay phan tich hang hoa phai sinh theo semantic SEO.",
                "info_gain": "Phan nay uu tien cac content gaps.",
                "bridge": "Phan nay se chuyen sang phan tiep theo.",
                "transition": "Phan nay se chuyen.",
                "guidance": "Section nay phan tich...",
            },
            {
                "h2": "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh",
                "snippet": "Cac thuoc tinh cot loi cua hang hoa phai sinh",
                "analysis": "",
                "info_gain": "",
                "bridge": "",
                "transition": "",
                "guidance": "",
            },
        ],
    }
    per_h2 = {
        "per_h2": {
            "[MAIN] Hang hoa phai sinh la gi?": {
                "content_format": "Paragraph",
                "first_sentence": "Hang hoa phai sinh can duoc chot bang nghia loi va pham vi ap dung.",
                "micro_terms": ["hang hoa phai sinh", "thi truong phai sinh", "ky quy"],
                "sentence_before": "Co 2 lop thong tin nen can lam ro, bao gom:",
                "preceding_question": "Hang hoa phai sinh la gi?",
                "contextual_bridge": "Mo sang phan thuoc tinh cot loi.",
                "word_count_target": "200-300 tu",
            },
            "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh": {
                "content_format": "Paragraph + bullet list",
                "first_sentence": "Cac thuoc tinh cot loi cua hang hoa phai sinh nam o co che ky quy va cach van hanh T+0.",
                "micro_terms": ["ky quy", "T+0", "hop dong"],
                "sentence_before": "Co 3 thuoc tinh cot loi can doi chieu, bao gom:",
                "preceding_question": "Cac thuoc tinh cot loi cua hang hoa phai sinh la gi?",
                "contextual_bridge": "Mo sang lop FAQ va luu y cuoi bai.",
                "word_count_target": "180-240 tu",
            },
        }
    }

    changed = _normalize_micro_briefing_data(brief, per_h2=per_h2)
    assert changed is True

    first_main = brief["micro_briefing"][1]
    second_main = brief["micro_briefing"][2]

    assert "semantic seo" not in first_main["analysis"].lower()
    assert "H3" in first_main["info_gain"]
    assert "Hang hoa phai sinh duoc dinh nghia nhu the nao?" in first_main["info_gain"]
    assert "thuoc tinh cot loi" in first_main["bridge"].lower()
    assert second_main["word_count_target"] == "180-240 tu"
    assert "section" in second_main["guidance"].lower()


def test_outline_readiness_report():
    brief = {
        "topic": "hang hoa phai sinh la gi",
        "central_entity": "hang hoa phai sinh",
        "semantic_reasoning": {
            "preferred_flow": ["dinh nghia", "thuoc tinh", "so sanh", "faq"],
        },
        "contextual_structure_v4": {
            "per_h2": {
                "[MAIN] Hang hoa phai sinh la gi?": {"content_format": "Paragraph"},
                "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh": {"content_format": "Paragraph"},
            }
        },
        "micro_briefing": [
            {"h2": "[MAIN] Hang hoa phai sinh la gi?", "analysis": "Lam ro nghia loi, pham vi ap dung va ranh gioi voi cac khai niem de bi nham."},
            {"h2": "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh", "analysis": "Tach tung thuoc tinh cot loi de nguoi doc doi chieu nhanh."},
            {"h2": "[SUPP] FAQ ve hang hoa phai sinh", "analysis": "Tra loi ngan, truc dien."},
        ],
        "koray_quality_score_md": "## KORAY QUALITY SCORE: **82/100**",
    }
    headings = [
        {"level": "H2", "text": "[MAIN] Hang hoa phai sinh la gi?"},
        {"level": "H3", "text": "Hang hoa phai sinh duoc dinh nghia nhu the nao?"},
        {"level": "H2", "text": "[MAIN] Cac thuoc tinh cot loi cua hang hoa phai sinh"},
        {"level": "H3", "text": "Ky quy thap la gi?"},
        {"level": "H2", "text": "[SUPP] FAQ ve hang hoa phai sinh"},
    ]

    report = generate_outline_readiness_report(brief, headings)
    assert report["verdict"] in {"ready", "needs_tuning"}
    assert report["metrics"]["h2_count"] == 3
    assert report["metrics"]["h3_count"] == 2
    assert "h3_coverage" in report["checks"]


def test_semantic_outline_gate_uses_blueprint_roles_without_duplicate_definition():
    topic = "may loc nuoc gia dinh la gi"
    blueprint = _build_semantic_blueprint(
        topic,
        "Informational",
        gap_h2_candidates=[
            "Phan loai may loc nuoc gia dinh theo cong nghe loc",
            "May loc nuoc gia dinh hoat dong nhu the nao",
            "Chi phi van hanh may loc nuoc gia dinh",
        ],
        gap_h3_candidates=["Nhung sai lam pho bien khi chon may loc nuoc gia dinh"],
        semantic_terms=["loi loc", "nguon nuoc dau vao", "cong nghe RO"],
    )
    headings = [
        {"level": "H2", "text": "[MAIN] Loi ich suc khoe tu may loc nuoc gia dinh"},
        {"level": "H2", "text": "[MAIN] Khai niem may loc nuoc gia dinh"},
        {"level": "H2", "text": "[MAIN] Khai niem may loc nuoc gia dinh: dinh nghia va cong dung"},
        {"level": "H2", "text": "[SUPP] Nhung sai lam pho bien khi chon may loc nuoc gia dinh"},
    ]

    gated = _apply_semantic_outline_gate(headings, topic, {"semantic_blueprint": blueprint})
    h2_texts = [item["text"] for item in gated if item["level"] == "H2"]
    h2_plain = " | ".join(_plain(text) for text in h2_texts)

    assert sum(1 for text in h2_texts if "khai niem" in _plain(text)) == 1
    assert "phan loai" in h2_plain
    assert "hoat dong" in h2_plain
    assert _plain(h2_texts[0]).startswith("[main] khai niem")


def test_outline_readiness_report_matches_conceptual_flow():
    brief = {
        "topic": "hang hoa phai sinh la gi",
        "central_entity": "hang hoa phai sinh",
        "semantic_reasoning": {
            "preferred_flow": [
                "definition and scope",
                "forms and market structure",
                "how it works in practice",
                "benefits and risks",
                "conditions / costs / FAQ",
            ],
        },
        "contextual_structure_v4": {"per_h2": {"[MAIN] Hang hoa phai sinh la gi": {"content_format": "Paragraph"}}},
        "micro_briefing": [
            {"h2": "[MAIN] Hang hoa phai sinh la gi", "analysis": "Lam ro dinh nghia."},
            {"h2": "[MAIN] Cac loai hop dong hang hoa phai sinh", "analysis": "Tach nhom hop dong."},
            {"h2": "[MAIN] Co che giao dich hang hoa phai sinh", "analysis": "Giai thich quy trinh."},
            {"h2": "[MAIN] Loi ich va rui ro cua hang hoa phai sinh", "analysis": "Can bang loi ich va canh bao."},
            {"h2": "[SUPP] FAQ ve hang hoa phai sinh", "analysis": "Tra loi cau hoi duoi."},
        ],
        "koray_quality_score_md": "## KORAY QUALITY SCORE: **81/100**",
    }
    headings = [
        {"level": "H2", "text": "[MAIN] Hang hoa phai sinh la gi"},
        {"level": "H3", "text": "Hang hoa phai sinh duoc dinh nghia nhu the nao?"},
        {"level": "H2", "text": "[MAIN] Cac loai hop dong hang hoa phai sinh"},
        {"level": "H3", "text": "Co nhung nhom hop dong nao?"},
        {"level": "H2", "text": "[MAIN] Co che giao dich hang hoa phai sinh"},
        {"level": "H3", "text": "Quy trinh dat lenh va ky quy ra sao?"},
        {"level": "H2", "text": "[MAIN] Loi ich va rui ro cua hang hoa phai sinh"},
        {"level": "H3", "text": "Nha dau tu can luu y gi?"},
        {"level": "H2", "text": "[SUPP] FAQ ve hang hoa phai sinh"},
    ]

    report = generate_outline_readiness_report(brief, headings)
    assert report["checks"]["preferred_flow"] is True
    assert report["verdict"] in {"ready", "needs_tuning"}


def test_serp_topic_purity_filter():
    items = [
        {
            "title": "Hang hoa phai sinh la gi?",
            "snippet": "Khai niem, phan loai va cach hoat dong cua hang hoa phai sinh",
            "url": "https://example.com/hang-hoa-phai-sinh",
        },
        {
            "title": "Ngay dao han phai sinh la gi?",
            "snippet": "Nhung dieu can luu y ve dao han chung khoan phai sinh",
            "url": "https://example.com/dao-han-phai-sinh",
        },
        {
            "title": "Giao dich hang hoa phai sinh cho nguoi moi",
            "snippet": "Co che ky quy va hop dong tuong lai hang hoa",
            "url": "https://example.com/giao-dich-hang-hoa-phai-sinh",
        },
        {
            "title": "Chung khoan phai sinh la gi",
            "snippet": "Huong dan co ban ve thi truong chung khoan phai sinh",
            "url": "https://example.com/chung-khoan-phai-sinh",
        },
    ]
    filtered = _filter_serp_results_by_topic(items, "hang hoa phai sinh la gi")
    titles = [item["title"] for item in filtered]
    assert len(filtered) == 2
    assert "Hang hoa phai sinh la gi?" in titles
    assert "Giao dich hang hoa phai sinh cho nguoi moi" in titles
    assert all("dao han" not in title.lower() for title in titles)
    assert all("chung khoan" not in title.lower() for title in titles)


def test_heading_fallback_scaffold():
    headings = _generate_heading_structure(
        topic="hang hoa phai sinh la gi",
        entity="hang hoa phai sinh",
        intent="informational",
        serp_data=None,
        competitor_data=None,
    )
    h2_texts = [item["text"] for item in headings if item["level"] == "H2"]
    assert len(h2_texts) == 6
    assert "hang hoa phai sinh" in _plain(h2_texts[0])
    assert any("hoat" in _plain(text) or "nhu the nao" in _plain(text) for text in h2_texts)
    assert any("faq" in _plain(text) or "thuong gap" in _plain(text) for text in h2_texts)


def test_align_outline_to_preferred_flow_demotes_duplicate_risk():
    headings = [
        {"level": "H1", "text": "Hang hoa phai sinh la gi"},
        {"level": "H2", "text": "[MAIN] Hang hoa phai sinh la gi"},
        {"level": "H3", "text": "Dinh nghia"},
        {"level": "H2", "text": "[MAIN] Rui ro khi giao dich hang hoa phai sinh"},
        {"level": "H3", "text": "Canh bao 1"},
        {"level": "H2", "text": "[MAIN] Nhung luu y quan trong khi tim hieu hang hoa phai sinh"},
        {"level": "H3", "text": "Canh bao 2"},
        {"level": "H2", "text": "[MAIN] Co che giao dich hang hoa phai sinh"},
        {"level": "H3", "text": "Quy trinh"},
        {"level": "H2", "text": "[SUPP] FAQ ve hang hoa phai sinh"},
    ]
    aligned = _align_outline_to_preferred_flow(
        headings,
        preferred_order=["definition", "process", "risk", "faq"],
    )
    h2s = [item["text"] for item in aligned if item["level"] == "H2"]
    assert h2s[0].startswith("[MAIN] Hang hoa phai sinh la gi")
    assert "Co che giao dich" in h2s[1]
    assert sum(1 for text in h2s if text.startswith("[MAIN]") and ("Rui ro" in text or "luu y" in text.lower())) == 1
    assert h2s[-1].startswith("[SUPP] FAQ")


def test_classify_serp_intent_prefers_query_markers():
    intent = _classify_serp_intent(
        {
            "organic_results": [
                {"title": "Gia hang hoa phai sinh", "snippet": "Bang gia va review thi truong"},
            ],
            "people_also_ask": [],
            "things_to_know": [],
        },
        topic="hang hoa phai sinh la gi",
    )
    assert intent == "informational"


def test_quality_phrase_rejects_broken_topic_fragment():
    assert _is_quality_phrase("hang hoa phai", "hang hoa phai sinh")
    assert _is_quality_phrase("sinh hang", "hang hoa phai sinh") is False


if __name__ == "__main__":
    test_micro_brief_normalization()
    test_outline_readiness_report()
    test_outline_readiness_report_matches_conceptual_flow()
    test_serp_topic_purity_filter()
    test_heading_fallback_scaffold()
    test_align_outline_to_preferred_flow_demotes_duplicate_risk()
    test_classify_serp_intent_prefers_query_markers()
    test_quality_phrase_rejects_broken_topic_fragment()
    print("test_koray_readiness.py: OK")
