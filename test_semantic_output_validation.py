from modules.markdown_exporter import _render_markdown
from modules.outline_content_adapter import build_outline_content_framework


class Project:
    name = "SACT"
    brand_name = "SACT"
    domain = "sact.vn"
    industry = "Tư vấn đầu tư và môi giới giao dịch hàng hóa phái sinh"
    source_context = "Dịch vụ tài chính phái sinh hàng hóa"
    description = ""
    project_type = ""
    target_customers = "nhà đầu tư"
    tone = "chuyên gia"
    hotline = ""
    geo_keywords = "Vietnam"


def _brief():
    return {
        "seed_keyword": "hàng hóa phái sinh",
        "topic": "hàng hóa phái sinh",
        "central_entity": "hàng hóa phái sinh",
        "search_intent": {"type": "Transactional"},
        "meta_description": (
            "Bảng giá hàng hóa phái sinh mới nhất 2026. "
            "Thông tin sản phẩm, chính sách giao hàng và bảo hành."
        ),
        "faq_questions": [
            "hàng hóa phái sinh là gì?",
            "hàng hóa phái sinh hoạt động như thế nào?",
        ],
        "heading_structure": [
            {"level": "H2", "text": "Hàng hóa phái sinh: Định nghĩa và phân loại"},
            {"level": "H3", "text": "Hàng hóa phái sinh là gì?"},
            {"level": "H2", "text": "Hàng hóa phái sinh: Tỷ lệ, thời gian và điều kiện tối thiểu"},
            {"level": "H3", "text": "Quy trình cắt xả băng trong giao dịch phái sinh"},
            {"level": "H2", "text": "FAQ về hàng hóa phái sinh"},
            {"level": "H3", "text": "hàng hóa phái sinh là gì?"},
        ],
        "semantic_reasoning": {
            "semantic_terms_curated": [
                "hàng hóa",
                "giao dịch",
                "nhà đầu tư",
                "hợp đồng tương lai",
            ],
            "decision_blockers": [
                "Người đọc chưa biết điều kiện tham gia và rủi ro ký quỹ."
            ],
        },
        "eav_table_rows": [
            {
                "entity": "hàng hóa phái sinh",
                "attribute": "Định nghĩa",
                "value": "Hàng hóa phái sinh là công cụ tài chính dựa trên giá hàng hóa cơ sở.",
                "is_verified": True,
                "confidence": 1.0,
            }
        ],
        "serp_analysis": {
            "dominant_format": "Blog/Article",
            "organic_results": [
                {"url": f"https://example{i}.com/a", "title": "A", "snippet": "S"}
                for i in range(10)
            ],
        },
    }


def test_full_brief_applies_semantic_output_validation():
    brief = _brief()
    project = Project()
    brief["outline_content_framework"] = build_outline_content_framework(brief, project=project)
    brief["_project_context"] = project

    markdown = _render_markdown(brief)

    assert "Outline-Content Framework Pack" not in markdown
    assert "Bảng giá hàng hóa phái sinh mới nhất" in markdown
    assert '"@type": "Product"' not in markdown
    assert "Tỷ lệ, thời gian và điều kiện tối thiểu" in markdown
    assert "Quy trình cắt xả băng" in markdown
    assert "Decision blocker:" in markdown
    assert "FS target:" in markdown
    assert "Context terms" in markdown
