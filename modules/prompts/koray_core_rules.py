# -*- coding: utf-8 -*-
"""
modules/prompts/koray_core_rules.py — Phase 2.1

"8 Quy tắc Cốt lõi Koray" — verbatim text shared across all agents.
This was copy-pasted in 6+ places, now consolidated here.

The 8 rules enforce: contextual flow, hierarchy, anti-stuffing,
fuzzy NER, E-E-A-T signals, answer-directness, and geographic relevance.
"""

# ──────────────────────────────────────────────────────────────────────────
#  8 QUY TẮC CỐT LÕI KORAY (verbatim — DO NOT MODIFY without review)
# ──────────────────────────────────────────────────────────────────────────
KORAY_8_RULES = """
## 8 QUY TẮC CỐT LÕI KORAY — TUYỆT ĐỐI ÁP DỤNG

1. **CONTEXTUAL FLOW (Luồng ngữ cảnh):** Mỗi heading phải nối tiếp tự nhiên với heading trước đó. Không nhảy cóc, không lặp ý. Cuối bài phải quay về chủ đề chính (H1 circular flow).

2. **CONTEXTUAL HIERARCHY (Phân cấp ngữ cảnh):** H1 → H2 → H3 → H4 phải có quan hệ cha-con rõ ràng. H2 định nghĩa khái niệm cấp cao. H3 giải thích chi tiết hơn. H4 bổ sung ví dụ/so sánh. KHÔNG viết H3 như H2.

3. **ANTI-STUFFING (Chống nhồi nhét):** Mỗi heading chỉ phục vụ 1 chủ đề duy nhất. Không nhồi từ khóa, không liệt kê 20 điểm trong 1 heading. Nếu muốn liệt kê → dùng H3 chia nhỏ.

4. **ENTITY FUZZY NER (Giải thể chủ quan):** Khi viết về chủ thể/danh từ riêng, luôn kèm mô tả/định nghĩa ở first occurrence. VD: "thép Hòa Phát (thép HP) — nhà máy thép lớn nhất miền Bắc)".

5. **E-E-A-T SIGNALS (Tín hiệu E-E-A-T):** Nội dung phải thể hiện: Experience (kinh nghiệm thực tế), Expertise (chuyên môn kỹ thuật), Authoritativeness (bằng chứng/cứ liệu), Trustworthiness (thông tin xác thực). Luôn cite tiêu chuẩn (ASTM, JIS, TCVN) khi có cơ hội.

6. **ANSWER DIRECTNESS (Trả lời trực tiếp):** Viết câu đầu tiên dưới mỗi H2 phải trả lời TRỰC TIẾP câu hỏi của H2 đó. Không mở đầu bằng "Trong bài viết này, chúng ta sẽ...", "Hãy cùng tìm hiểu...", "Theo như...".

7. **GEOGRAPHIC RELEVANCE (Liên quan địa lý):** Luôn gắn thông tin với context địa lý Việt Nam. Không dùng generic examples từ nước ngoài. Tham chiếu khu vực (miền Bắc, miền Nam, Đông Nam Bộ...) khi phù hợp.

8. **SEMANTIC CLARITY (Rõ ràng ngữ nghĩa):** Mỗi heading phải có câu mở đầu trả lời trực tiếp vào câu hỏi/tiêu đề của heading đó. Nội dung phải cung cấp GIÁ TRỊ BỔ SUNG so với những gì đối thủ đã viết (information gain).
"""

# ──────────────────────────────────────────────────────────────────────────
#  3-PILLAR ATTRIBUTE FILTRATION
# ──────────────────────────────────────────────────────────────────────────
KORAY_3_FILTRATION = """
## 3-PILLAR ATTRIBUTE FILTRATION (Lọc thuộc tính theo 3 tiêu chí)

Khi chọn attributes/EAV để đưa vào outline, ưu tiên attributes đáp ứng ĐỒNG THỜI 3 tiêu chí:

1. **PROMINENCE (Nổi bật):** Attribute phải CÓ TRONG title/heading của ít nhất 1 top-3 đối thủ. Nếu không có trên SERP → KHÔNG đưa vào outline.
2. **POPULARITY (Phổ biến):** Attribute phải xuất hiện trong ≥3 nguồn. Dùng N-gram frequency và competitor heading analysis.
3. **RELEVANCE (Liên quan):** Attribute phải phù hợp với search intent của keyword gốc. Informational → attributes giải thích. Commercial → attributes so sánh. Transactional → attributes về giá/quy cách.
"""

# ──────────────────────────────────────────────────────────────────────────
#  EAV UNIT GUIDANCE (shared between koray_analyzer.py and ccb.py)
# ──────────────────────────────────────────────────────────────────────────
KORAY_EAV_UNIT_GUIDANCE = """
## EAV UNIT GUIDANCE (Hướng dẫn viết EAV Triple)

Mỗi EAV triple phải tuân theo format:
    [ENTITY] | [ATTRIBUTE mô tả ngắn] | [VALUE cụ thể]

VD đúng:
    Thép tấm SS400 | Tiêu chuẩn | JIS G3101 SS400
    Thép tấm SS400 | Kích thước | 1220×2440mm (4×8 feet)
    Thép tấm SS400 | Ứng dụng | Kết cấu xây dựng, dầm cột, tàu biển

VD sai:
    Thép tấm SS400 | Thông tin | Thép tấm SS400 là một loại thép...
    Thép tấm SS400 | ... | ... (attribute chung chung, không có giá trị cụ thể)

QUY TẮC:
- VALUE phải là CONCRETE DATA (con số, chuẩn, quy cách cụ thể), không phải mô tả
- ATTRIBUTE phải ngắn gọn (2-4 từ)
- Mỗi entity nên có 3-7 EAV triples
"""

# ──────────────────────────────────────────────────────────────────────────
#  All rules combined (convenience constant)
# ──────────────────────────────────────────────────────────────────────────
KORAY_ALL_RULES = KORAY_8_RULES + "\n" + KORAY_3_FILTRATION + "\n" + KORAY_EAV_UNIT_GUIDANCE
