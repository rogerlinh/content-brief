from modules.content_brief_builder import _apply_source_context_outline_gate


def _texts(outline):
    return "\n".join(item["text"] for item in outline)


def test_source_context_gate_keeps_evidence_outline_without_rebuilding_motif():
    outline = [
        {"level": "H1", "text": "Dau Tu Hang Hoa La Gi"},
        {"level": "H2", "text": "[MAIN] Dau Tu Hang Hoa La Gi: Dinh nghia va phan loai"},
        {"level": "H3", "text": "Dinh nghia va pham vi ap dung cua dau tu hang hoa"},
        {"level": "H2", "text": "[MAIN] Dau Tu Hang Hoa La Gi: Dac diem ky thuat, chi phi va thong so"},
        {"level": "H3", "text": "Thong so ky thuat bi chen cung"},
        {"level": "H2", "text": "[MAIN] Loi ich va rui ro theo du lieu SERP"},
        {"level": "H3", "text": "Rui ro nao duoc competitor nhac lai"},
    ]

    cleaned = _apply_source_context_outline_gate(
        outline,
        topic="Dau Tu Hang Hoa La Gi",
        intent="Informational",
        project=None,
        paa_questions=["Dau tu hang hoa can bao nhieu von?"],
    )
    text = _texts(cleaned)

    assert "Dac diem ky thuat" in text
    assert "Thong so ky thuat bi chen cung" in text
    assert "Loi ich va rui ro theo du lieu SERP" in text
    assert "Dau tu hang hoa can bao nhieu von" not in text


def test_source_context_gate_does_not_fabricate_outline_when_only_h1_exists():
    outline = [{"level": "H1", "text": "Huong Dan Cho Nguoi Moi"}]

    cleaned = _apply_source_context_outline_gate(
        outline,
        topic="huong dan cho nguoi moi",
        intent="Informational",
        project=None,
    )

    assert cleaned == outline


def test_source_context_gate_keeps_evidence_driven_product_headings():
    outline = [
        {"level": "H1", "text": "Thep Tam La Gi"},
        {"level": "H2", "text": "[MAIN] Tieu chuan JIS trong ket qua SERP"},
        {"level": "H3", "text": "JIS G3101 duoc competitor nao nhac den"},
    ]

    cleaned = _apply_source_context_outline_gate(
        outline,
        topic="thep tam la gi",
        intent="Informational",
        project=None,
    )

    assert cleaned == outline
