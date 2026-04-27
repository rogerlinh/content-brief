🔍  CODE REVIEW REPORT  —  V3
Content Brief Generator
Đánh giá toàn diện sau đợt fix thứ 2  —  Tháng 3/2026

ĐIỂM TỔNG
84/100
Grade A−
✅ Đã fix (8 items)
• per_h2 DICT vs LIST
• Field name mismatch
• Agent 1 generic example
• Cannibalization Jaccard
• FAQPage answer logic
• H3 artifact ??
• koray_analyzer -8đ
• SUPP anchor Rule 6
⚠️ Gap còn lại (4)
• sentence_before không render
• macro_rules bị drop
• Organization schema: website_url sai field
• topics.csv vẫn 12 rows
💡 Backlog (2)
• ROOT/NODE classification
• Hash Anchor #H2

1. Scorecard — Trước & Sau Fix
Đối chiếu điểm số qua 3 phiên bản: V10 gốc → V2 (fix lần 1) → V3 (fix lần 2, code hiện tại).

Tiêu chí
V10
V2
V3 (hiện tại)
Ghi chú
Contextual Vector (H2 Attribute Filtration)
8
8
8
Ổn định, không thay đổi
Contextual Hierarchy (H3 Depth + Quality)
7
8
9
H3 artifact fix + penalty tăng ✅
Contextual Structure (Per-H2 Instructions)
7
5
9
Bug DICT/field fix → render đủ 8/10 thành phần
Contextual Connection (Internal Link)
7
8
9
SUPP Rule 6 + B2B detection cải thiện ✅
FS/PAA Block (Featured Snippet)
9
9
9
Giữ nguyên, chuẩn
EAV Coverage
9
9
9
Giữ nguyên, chuẩn
Source Context / Universal Adaptation
9
9
9
Agent 1 generic example fix ✅
GEO / AI Overview Optimization
4
7
8
FAQPage fix ✅, còn org.url sai field
Score Calibration (Koray Analyzer)
7
8
9
Template penalty 0.3/-8đ ✅
Topical Map / Positional Awareness
4
5
7
Render + Jaccard ✅, thiếu ROOT/NODE
TỔNG ĐIỂM
72
~76
84
Grade A−  (target: 90+)

💡 Nhận xét tổng quan: Sau 2 lần fix, tool đã tiến từ B+ (72) lên A− (84). Pipeline 7 tầng vận hành đúng, 8 thành phần Koray per-H2 đã render đủ. Còn 4 gaps nhỏ để đạt A+ (90+): 2 fields bị drop trong exporter, 1 field sai tên trong Organization schema, 1 data gap topics.csv.

2. Xác Nhận Các Fix Đã Đúng (8/8)
2.1 ✅ per_h2 DICT vs LIST Mismatch — Đã Fix
markdown_exporter.py lines 310–318: Đúng hoàn toàn.
# ✅ Code hiện tại (đúng):
per_h2_dict = ctx_v4.get("per_h2", {}) if isinstance(ctx_v4, dict) else {}
if isinstance(per_h2_dict, list):   # backward compat
    per_h2_dict = {item.get("h2","Heading"): item for item in per_h2_dict if isinstance(item, dict)}
for h2_name, h2_inst in per_h2_dict.items():
    lines.append(f"### {h2_name}")
    # h2_inst giờ là dict với đủ fields ✅
✅ Type-safe. Backward compat cho list format. Không còn AttributeError khi iterate.

2.2 ✅ Field Name Mismatch — Đã Fix
markdown_exporter.py lines 323–329: Dual-key lookup với fallback.
# ✅ Code hiện tại (đúng):
fs = h2_inst.get("first_sentence") or h2_inst.get("first_sentence_pattern", "")
mt = h2_inst.get("micro_terms") or h2_inst.get("micro_context_terms", [])
✅ Dual-key lookup đảm bảo tương thích nếu LLM đổi tên field. First Sentence và Micro Terms nay render đúng.

2.3 ✅ Agent 1 — Generic {entity} Example
content_brief_builder.py lines 655–657: Hardcoded steel đã được thay bằng placeholder.
# ✅ Trước: "Thép thanh vằn là gì?"  →  Sau: "{entity} là gì?"
  {"level":"H2","text":"[MAIN] {entity} là gì?","children":[
    {"level":"H3","text":"Đặc điểm chính của {entity}"},
    {"level":"H3","text":"Phân biệt {entity} với các loại khác"}
  ]},
  {"level":"H2","text":"[MAIN] Bảng thông số kỹ thuật / Thành phần","children":[
    {"level":"H3","text":"Định lượng tiêu chuẩn"}
  ]},
✅ LLM giờ không bị bias bởi steel vocabulary. Pattern {entity} phù hợp mọi niche.

2.4 ✅ Cannibalization — Jaccard Warning
markdown_exporter.py lines 387–396: Logic Jaccard > 0.6 chạy đúng. Test với keyword ngoài ngành (vitamin C) không false positive. Test với 2 bài steel gần nhau sẽ đúng trigger.
✅ Logic sạch. Edge case "current not found in topics.csv" handled (current_idx = None).

2.5–2.8 ✅ FAQPage / H3 Artifact / koray_analyzer / SUPP Anchor
Tất cả 4 fixes từ lần trước vẫn còn nguyên, không bị revert. Xác nhận:
FAQPage word overlap matching + used_answers dedup set: ✅ Còn nguyên
H3 artifact ?? sanitization + is_natural_q guard: ✅ Còn nguyên
koray_analyzer template_ratio > 0.3 → -8đ: ✅ Còn nguyên
SUPP anchor _pick_anchor() Rule 6 question format: ✅ Còn nguyên

3. Gaps Còn Lại — Cần Fix Tiếp
4 gaps sau đây nhỏ về effort nhưng quan trọng về completeness. Sau khi fix, tool đạt 90+ / 100 (Grade A+).

3.1 ⚠️ sentence_before — Component ④ Không Render
Agent 4 (generate_per_h2_instructions) sinh ra field "sentence_before" (Koray Lecture component ④: "Sentence Before List/Table"). Agent docstring và LLM prompt đều khai báo đầy đủ. Nhưng markdown_exporter.py không có dòng nào đọc field này.

agent_reviewer.py — sinh ra
markdown_exporter.py — thiếu
"sentence_before": "Có X loại [entity], bao gồm:"
h2_inst.get("sentence_before") → KHÔNG CÓ dòng này

Koray Lecture 21 component ④: "Sentence Before List/Table" là trigger giúp LLM mở đầu mỗi block list/table đúng pattern. Thiếu nó, writer có thể dùng pattern tự phát không nhất quán với brief.

Fix — markdown_exporter.py (1 dòng, sau micro_terms)
# Thêm sau block micro_terms (line ~330):
if h2_inst.get("sentence_before"):
    lines.append(f"- **Sentence Before:** {h2_inst['sentence_before']}")

3.2 ⚠️ macro_rules — Agent 4 Output Bị Drop Hoàn Toàn
Agent 4 trả về 2 keys cấp cao: "macro_rules" (toàn bài) và "per_h2" (per section). Exporter chỉ đọc per_h2 và bỏ qua macro_rules hoàn toàn.

macro_rules chứa:
central_entity_term — entity chính phải xuất hiện ≥1 lần mỗi section
predicate_cluster — 4-6 động từ nhất quán toàn bài (VD: đạt, chịu, chống, sử dụng)
tonality — giọng văn tổng thể (technical B2B / conversational B2C / health-advisory)

Đây không phải data thừa — predicate_cluster là Koray Lecture 39 (Contextual Flow). Writer cần biết động từ cluster để duy trì semantic coherence giữa các section. Bỏ qua = mất một phần giá trị của Agent 4.

Fix — markdown_exporter.py (thêm macro_rules block trước per_h2 loop)
# Thêm TRƯỚC vòng lặp for h2_name, h2_inst in per_h2_dict.items():
macro = ctx_v4.get("macro_rules", {})
if macro:
    lines.append("**📌 Macro Rules (Toàn Bài)**")
    lines.append("")
    if macro.get("central_entity_term"):
        lines.append(f"- **Central Entity:** {macro['central_entity_term']}")
    if macro.get("predicate_cluster"):
        pc = macro["predicate_cluster"]
        if isinstance(pc, list): pc = ", ".join(pc)
        lines.append(f"- **Predicate Cluster:** {pc}")
    if macro.get("tonality"):
        lines.append(f"- **Tonality:** {macro['tonality']}")
    lines.append("")

3.3 ⚠️ Organization Schema — website_url Sai Field Name
geo_schema_generator.py line 37: dùng getattr(project, "website_url", "") nhưng Project dataclass không có field "website_url" — field đúng là "domain".

Code hiện tại (sai)
Đúng phải là
"url": getattr(project, "website_url", "")
"url": f"https://{project.domain}/"

Hậu quả: Organization schema luôn có "url": "" (empty string). Google / AI Overview sẽ không match được entity với website. Đây là lỗi nhỏ nhưng ảnh hưởng trực tiếp đến GEO score.

Fix — geo_schema_generator.py line 37
# Trước (sai):
"url": getattr(project, "website_url", ""),

# Sau (đúng):
"url": f"https://{getattr(project, 'domain', '')}/" if getattr(project, 'domain', '') else "",

3.4 ⚠️ topics.csv — Vẫn 12 Rows Steel Keywords
Render code đã đúng, cannibalization logic đúng. Nhưng data vẫn là 12 keywords thép. Với 12 entries:
Topical Map hiển thị được nhưng thiếu context để phát hiện cannibalization thực sự
Upstream/downstream positioning không có nghĩa với cluster nhỏ
Writer không thấy được bức tranh toàn ngành của website

Đây là data task, không phải code task. Cần expand topics.csv theo cluster thực tế của từng project. Gợi ý: tối thiểu 30-50 keywords, bao phủ đủ pillar + cluster articles.

4. Vấn Đề Phụ — Exception Handling
Silent Exception Swallow Trong Topical Map
markdown_exporter.py line 398: except Exception: pass — nuốt mọi lỗi mà không log.
# Hiện tại (nguy hiểm):
except Exception:
    pass   # ← writer không biết topical map bị lỗi, section im lặng không render

# Nên sửa thành:
except Exception as _map_err:
    logger.warning("  [EXPORTER] Topical map render failed: %s", _map_err)
    lines.append("> ⚠️ Không thể render Topical Map. Kiểm tra file topics.csv.")
Nếu topics.csv có encoding lỗi hoặc format sai, section này im lặng biến mất. Writer không biết là bug hay section không tồn tại. Thêm warning log + user-facing message là best practice.

5. Full Fix Status — Toàn Bộ Lịch Sử

#
Item
File
Lần fix
Status
Δ Pts
1
FAQPage answer logic — word overlap + dedup
geo_schema_generator.py
Fix #1
✅ Done
+3
2
H3 artifact ?? sanitization + natural_q guard
content_brief_builder.py
Fix #1
✅ Done
+2
3
koray_analyzer template penalty 0.3 → -8đ
koray_analyzer.py
Fix #1
✅ Done
+1
4
SUPP anchor Rule 6 question format
internal_linking.py
Fix #1
✅ Done
+1
5
B2B detection mở rộng đa ngành
content_brief_builder.py
Fix #1
✅ Done
+1
6
Topical Map render (table + position marker)
markdown_exporter.py
Fix #1
✅ Done
+1
7
per_h2 DICT vs LIST mismatch
markdown_exporter.py
Fix #2
✅ Done
+3
8
Field name: first_sentence + micro_terms
markdown_exporter.py
Fix #2
✅ Done
+1
9
Agent 1 generic {entity} example
content_brief_builder.py
Fix #2
✅ Done
+1
10
Cannibalization Jaccard > 0.6 warning
markdown_exporter.py
Fix #2
✅ Done
+2
11
sentence_before — component ④ không render
markdown_exporter.py
Cần Fix #3
⚠️ Missing
+1
12
macro_rules bị drop trong exporter
markdown_exporter.py
Cần Fix #3
⚠️ Missing
+2
13
Organization schema: website_url → domain
geo_schema_generator.py
Cần Fix #3
⚠️ Bug
+1
14
topics.csv mở rộng ≥30-50 keywords
topics.csv (data)
Data task
⚠️ Pending
—
15
Exception swallow → add warning log
markdown_exporter.py
Cần Fix #3
⚠️ Minor
0
16
ROOT/NODE article classification
markdown_exporter.py
Backlog
💡 P2
+1
17
Hash Anchor #H2-identifier
internal_linking.py
Backlog
💡 P2
+1

Ước tính điểm sau Fix #3: (84 + 1 + 2 + 1) = 88 / 100. Sau data task topics.csv + backlog: 90+ / 100 (Grade A+).

6. Action Plan — Fix #3 (Effort ~30 phút)

#
Action
File + Vị trí
Effort
Impact
1
Thêm render sentence_before (component ④)
markdown_exporter.py ~line 330
2 phút
+1 điểm
2
Thêm render macro_rules block (predicate_cluster, tonality, central_entity)
markdown_exporter.py ~line 313
10 phút
+2 điểm
3
Sửa website_url → domain trong Organization schema
geo_schema_generator.py line 37
2 phút
+1 điểm
4
Thêm warning log cho except Exception trong Topical Map
markdown_exporter.py line 398
3 phút
Reliability
5
Expand topics.csv ≥30 keywords theo cluster thực tế
topics.csv
Data task
Map accuracy

Tổng thời gian Fix #3: ~17 phút code + data task. Sau đó tool đạt Grade A+ với đầy đủ 10 thành phần Koray (8 per-H2 + macro_rules + topical map) render ra brief cho writer.
Code Review V3  |  Content Brief Generator  |  Tháng 3/2026