🔍 CODE REVIEW REPORT
Content Brief Generator — Kiểm Tra Sau Fix
Đối chiếu source code thực tế vs. khuyến nghị trong Báo Cáo V2

KẾT QUẢ
6 / 10
fixes đúng
✅ Đã fix đúng (6)
• FAQPage answer logic — word overlap match
• H3 artifact "??" sanitization
• koray_analyzer template penalty (0.3 → -8đ)
• SUPP anchor Rule 6 question format
• B2B detection mở rộng đa ngành
• Topical Map render (table)
🐛 Bug mới (2)
• per_h2: DICT vs LIST
  mismatch
• Field name mismatch:
  first_sentence vs
  first_sentence_pattern
⚠️ Chưa xong (2)
• topics.csv vẫn 12 rows
  (cần ≥50)
• Agent 1 example vẫn
  hardcoded steel

1. Kiểm Tra Các Fix Đã Thực Hiện
Phương pháp: Đọc trực tiếp source code mới, so sánh từng dòng với khuyến nghị trong báo cáo V2. Tất cả kết luận dựa trên code thực tế.

1.1 ✅ FAQPage Schema — Answer Logic Fix
Vấn đề gốc: vòng lặp qua 5 PAA questions nhưng answer luôn lấy snippet của H2 đầu tiên → 5 entries trùng answer.

Đã fix: geo_schema_generator.py lines 60–83 thêm function _find_relevant_mb() sử dụng word overlap matching.

def _find_relevant_mb(micro_list, question):
    q_words = set(str(question).lower().split())
    best_score, best_snippet = 0, ""
    for mb in micro_list:
        snippet = str(mb.get("snippet", ""))
        if not snippet or len(snippet.split()) < 10: continue
        overlap = len(q_words & set(snippet.lower().split()))
        if overlap > best_score:
            best_score, best_snippet = overlap, snippet
    return best_snippet

# + used_answers set() để tránh duplicate answers across entries ✅

✅ Fix đúng và đầy đủ. Thêm bonus: used_answers set() đảm bảo không có 2 FAQ entries nào share cùng answer text, dù word overlap trùng. Fallback generic answer khi không tìm được match.

1.2 ✅ H3 Artifact "??" — Sanitization Fix
Đã fix tại 2 điểm:
_enforce_h3_ratio ~line 1099: h3_text.replace("??", "?").rstrip("?") + "?" — strip artifact trước khi insert
Natural question guard: kiểm tra natural_q_signals ["là gì", "như thế nào", "khi nào"...] trước khi thêm suffix " — điều gì cần lưu ý?"
V11-R2 rule: chỉ append suffix nếu H3 text là single-word VÀ không phải câu hỏi

✅ Fix đúng. Logic guard "is_natural_q" (line 1103–1107) kiểm tra cả signals lẫn endswith("?"), bắt được mọi dạng câu hỏi tự nhiên.

1.3 ✅ koray_analyzer — Template Penalty Tăng
Đã sửa: template_ratio threshold 0.5 → 0.3, penalty +5 → +8 (line 201–206). Đúng với khuyến nghị V2.
✅ Fix đúng.

1.4 ✅ SUPP Anchor Rule 6 — Question Format
internal_linking.py: function _pick_anchor() (lines 129–138) thêm check:
def _pick_anchor(variants, source_h2=""):
    if source_h2 and "[SUPP]" in source_h2.upper():
        return variants.get("question", variants.get("primary", variants.get("exact", "")))
    return variants.get("primary", variants.get("exact", ""))

✅ Fix đúng. Fallback chain đảm bảo không bao giờ trả về empty string.

1.5 ✅ B2B Detection — Mở Rộng Đa Ngành
b2b_signals (line 135–139) đã thêm: logistics, saas, enterprise, wholesale, oem, nhập khẩu, xuất khẩu, công nghiệp, manufacturer, distributor
b2b_topic_signals fallback (line 144–152) đã thêm: thiết bị y tế, dược phẩm, hóa chất, máy móc, phần mềm doanh nghiệp, erp, crm.
✅ Fix đúng. B2B detection giờ cover đúng đa ngành. Priority vẫn là Source Context → keyword fallback.

1.6 ✅ Topical Map Position — Render Vào Brief
markdown_exporter.py lines 346–384: đọc topics.csv, hiển thị bảng toàn bộ keywords với marker "→ Đang viết" cho bài hiện tại.
Đây là fix cơ bản đúng hướng. Tuy nhiên còn thiếu (xem Section 2.2).
✅ Fix đã render được Topical Map. Còn thiếu: ROOT/NODE classification, cannibalization warning.

2. Bug Mới Phát Sinh Sau Khi Fix — CẦN FIX NGAY
🚨 Đây là 2 bugs nghiêm trọng phát sinh trong quá trình implement fix P0#1 (per-H2 render). Cả 2 bugs khiến toàn bộ Deep Contextual Instructions section bị render sai hoặc throw AttributeError.

2.1 🐛 BUG CRITICAL: per_h2 DICT vs LIST Mismatch
Agent 4 (generate_per_h2_instructions) trả về:
# agent_reviewer.py — actual output structure:
{
  "macro_rules": {...},
  "per_h2": {
    "[MAIN] Thép thanh vằn là gì?": { "content_format": "...", ... },
    "[MAIN] Bảng trọng lượng":      { "content_format": "...", ... },
  }
}
# per_h2 = DICT với key là H2 text, value là instructions dict

Nhưng markdown_exporter.py xử lý như sau:
# markdown_exporter.py lines 310–316 — SAI:
per_h2_data = ctx_v4.get("per_h2", [])   # type = dict, không phải list!
for h2_inst in per_h2_data:               # iterate dict → yields KEYS (strings)
    h2_name = h2_inst.get("h2", "Heading") # AttributeError: str has no .get()
    # → CRASH hoặc render rỗng hoàn toàn

Hậu quả: Section "Deep Contextual Instructions (Per-H2)" hoàn toàn không render. Toàn bộ 8 thành phần Koray Lecture 21/39 bị mất. Đây là fix P0 quan trọng nhất của V2 nhưng lại bị broken bởi type mismatch.

Fix cần thực hiện — markdown_exporter.py lines 310–316
# TRƯỚC (sai):
per_h2_data = ctx_v4.get("per_h2", [])
for h2_inst in per_h2_data:
    h2_name = h2_inst.get("h2", "Heading")

# SAU (đúng):
per_h2_dict = ctx_v4.get("per_h2", {})
if isinstance(per_h2_dict, list):   # backward compat nếu có old data
    per_h2_dict = {item.get("h2","?"): item for item in per_h2_dict}
for h2_name, h2_inst in per_h2_dict.items():
    # h2_name = H2 heading text (string)
    # h2_inst = dict with fields
    lines.append(f"### {h2_name}")

2.2 🐛 BUG HIGH: Field Name Mismatch — 2 Fields Không Bao Giờ Render
Agent 4 và markdown_exporter dùng tên field khác nhau cho 2 components quan trọng:

Component
Agent output (agent_reviewer.py)
Exporter reads (markdown_exporter.py)
② First Sentence Pattern
"first_sentence"
"first_sentence_pattern" ← SAI
③ Micro Context Terms
"micro_terms"
"micro_context_terms" ← SAI
Các fields khác
content_format, preceding_question, contextual_bridge, boolean_h3, word_count_target, section_predicates
✅ Tên đúng khớp

Hậu quả: Sau khi fix bug #2.1, "First Sentence Pattern" và "Micro Terms" vẫn không bao giờ render vì h2_inst.get("first_sentence_pattern") luôn trả về None khi LLM trả về key "first_sentence".

Fix — markdown_exporter.py lines 322–328
# TRƯỚC (sai):
if h2_inst.get("first_sentence_pattern"):
    lines.append(f"- **First Sentence:** {h2_inst['first_sentence_pattern']}")
if h2_inst.get("micro_context_terms"):
    terms = h2_inst["micro_context_terms"]

# SAU (đúng — dùng đúng key theo agent output):
fs = h2_inst.get("first_sentence") or h2_inst.get("first_sentence_pattern", "")
if fs:
    lines.append(f"- **First Sentence:** {fs}")
mt = h2_inst.get("micro_terms") or h2_inst.get("micro_context_terms", [])
if mt:
    if isinstance(mt, list): mt = ", ".join(mt)
    lines.append(f"- **Micro Terms (≤5):** {mt}")

3. Items Chưa Được Thực Hiện
3.1 ⚠️ topics.csv — Vẫn Chỉ Có 12 Keywords
Topical Map section đã render (✅) nhưng topics.csv vẫn chỉ có 12 rows — tất cả là steel keywords (thép thanh vằn, thép cuộn, thép tấm...).

Thực trạng
Khuyến nghị V2
12 rows, 100% steel keywords
→ Map quá mỏng để có ý nghĩa
≥50 keywords bao phủ toàn bộ cluster chủ đề
→ Topical Map mới thực sự hữu dụng

Lưu ý: Đây là data issue, không phải code issue. Tool đã sẵn sàng đọc topics.csv — cần user bổ sung data đủ rộng cho từng website (tùy ngành). Không có fix chung cho mọi dự án.

3.2 ⚠️ Topical Map — Thiếu ROOT/NODE và Cannibalization Warning
Topical Map hiện tại chỉ render bảng danh sách toàn bộ keywords với marker "→ Đang viết". Chưa có:
Phân loại bài là ROOT (pillar) hay NODE (cluster article)
Hiển thị upstream (parent/sibling rộng hơn) và downstream (child articles hẹp hơn)
Cannibalization warning khi Jaccard similarity > 0.6 với bài khác trong map

Hướng fix bổ sung
# Sau khi render table, thêm classification block:
current_words = set(current.lower().split())
for ti, t in enumerate(_all_topics):
    if t == current: continue
    t_words = set(t.lower().split())
    union = current_words | t_words
    jaccard = len(current_words & t_words) / len(union) if union else 0
    if jaccard > 0.6:
        lines.append(f"> ⚠️ CẢNH BÁO CANNIBALIZATION: [{t}] (Jaccard={jaccard:.2f})")

3.3 ⚠️ Agent 1 Example — Vẫn Hardcoded Steel
Agent 1 system prompt (content_brief_builder.py ~line 648) vẫn dùng ví dụ "Thép thanh vằn là gì?", "TCVN", "D10 đến D32" làm JSON example cho LLM.

Tác động thực tế: LLM sẽ học pattern từ example và có xu hướng tạo ra H2/H3 theo ngữ cảnh kỹ thuật dạng thép dù keyword hoàn toàn khác ngành. Ví dụ: keyword "vitamin C là gì" có thể nhận outline kiểu "Bảng hàm lượng theo tiêu chuẩn..." — đúng structure nhưng sai domain vocabulary.

Fix khuyến nghị
Thay example cụ thể bằng placeholder generic hoặc inject example từ Source Context:
# Thay vì hardcode:
  {"level":"H2","text":"[MAIN] Thép thanh vằn là gì?","children":[
    {"level":"H3","text":"Đặc điểm bề mặt gân nổi..."}
  ]}

# Dùng generic placeholder:
  {"level":"H2","text":"[MAIN] {entity} là gì?","children":[
    {"level":"H3","text":"Đặc điểm chính của {entity}"},
    {"level":"H3","text":"Phân biệt {entity} với {related_entity}"}
  ]}

# Hoặc inject từ Source Context:
example_entity = main_keyword.split()[0] if main_keyword else "{entity}"

4. Tổng Hợp — Full Fix Status

Fix Item
File
Trạng thái
Ghi chú
FAQPage answer logic (word overlap)
geo_schema_generator.py
✅ Done
used_answers dedup bonus
H3 artifact "??" sanitization
content_brief_builder.py
✅ Done
natural_q guard đúng
koray_analyzer template penalty ≥0.3→-8đ
koray_analyzer.py
✅ Done
threshold & penalty đúng
SUPP anchor Rule 6 question format
internal_linking.py
✅ Done
fallback chain an toàn
B2B detection mở rộng đa ngành
content_brief_builder.py
✅ Done
SaaS/dược/logistics OK
Topical Map render vào brief
markdown_exporter.py
✅ Done
Còn thiếu ROOT/NODE
per_h2 render: DICT vs LIST mismatch
markdown_exporter.py
🐛 New Bug
CRASH khi chạy thực tế
Field name mismatch: first_sentence / micro_terms
markdown_exporter.py
🐛 New Bug
2 fields không bao giờ render
topics.csv mở rộng ≥50 keywords
topics.csv (data)
⚠️ Pending
Data issue, tùy project
Topical Map: ROOT/NODE + Cannibalization
markdown_exporter.py
⚠️ Partial
Cần thêm logic
Agent 1 example generic placeholder
content_brief_builder.py
⚠️ Pending
Low-effort, high-value
Hash Anchor (#H2-identifier)
internal_linking.py
⚠️ Pending
P2 backlog

Điểm số
V10 (gốc)
V2 Report (target)
Thực tế hiện tại
Tổng điểm
72 / 100
87–90 / 100
~76 / 100
Contextual Structure (Per-H2)
7 / 10
10 / 10
7 / 10 (bug mới)
GEO / AI Overview
4 / 10
8 / 10
7 / 10 (FAQPage fix ✅)
Topical Map Position
4 / 10
8 / 10
5 / 10 (render ok, thiếu logic)
H3 Quality / Template Penalty
7 / 10
9 / 10
9 / 10 ✅

Kết luận: 6 fixes đúng, nhưng fix quan trọng nhất (per-H2 render — P0#1) lại bị broken bởi 2 bugs type mismatch mới. Sau khi fix 2 bugs này, điểm dự kiến lên 85+ / 100.

5. Action Plan — Thứ Tự Ưu Tiên

#
Priority
Action
File
Effort
1
🚨 CRITICAL
Fix per_h2_data: DICT iteration (lines 310–316)
markdown_exporter.py
5 phút
2
🚨 CRITICAL
Fix field names: first_sentence + micro_terms (lines 322–328)
markdown_exporter.py
5 phút
3
⚠️ HIGH
Thêm ROOT/NODE + Jaccard cannibalization warning vào Topical Map
markdown_exporter.py
30 phút
4
⚠️ HIGH
Thay Agent 1 hardcoded steel example bằng generic placeholder
content_brief_builder.py
10 phút
5
💡 MEDIUM
Mở rộng topics.csv theo ngành thực tế của từng project
topics.csv (data)
Tùy project
6
💡 LOW
Hash Anchor (#H2-identifier) cho internal links
internal_linking.py
1-2h

Fix #1 và #2 chỉ cần ~10 phút sửa 2 đoạn code trong markdown_exporter.py. Sau đó toàn bộ "Deep Contextual Instructions (Per-H2)" section sẽ render đúng với đủ 8 thành phần Koray Lecture 21/39.
Code Review Report  |  Content Brief Generator V2  |  Tháng 3/2026