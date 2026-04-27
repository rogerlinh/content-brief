
BÁO CÁO ĐÁNH GIÁ SOURCE CODE
Content Brief Tool — Phiên bản V11
Theo chuẩn Semantic SEO của Koray Tuğberk Gürbüz Framework
Thep Tran Long — ThepTranLong.vn | Tháng 3/2026


I. TÓM TẮT ĐIỀU HÀNH
Verdict tổng thể: Tool V11 đạt Grade A- (~87/100) — lần đầu tiên trong lịch sử đánh giá tool này, cả 3 khoảng trống chiến lược (GEO, Per-H2 Instructions render, Topical Map) đều đã được bít. Còn 1 critical bug mới phát hiện cần fix ngay.

✅ Điểm nổi bật V11: 
GEO module mới (geo_schema_generator.py): Organization + FAQPage + Product JSON-LD schemas tự động từ brief data
Per-H2 Contextual Structure (contextual_structure_v4) ĐÃ được render trong output — writer cuối cùng thấy 8 thành phần Koray
word_count_target + section_predicates ĐÃ được thêm vào Agent 4 prompt — 10 thành phần thay vì 8
Topical Map Position section: hiển thị danh sách từ topics.csv + cảnh báo cannibalization Jaccard
H3 template detection: strict_penalty += 8 nếu >30% H3 là template (dấu '??' hoặc '[')
SUPP anchor question format (V11-R4): _pick_anchor() đúng Koray Rule 6
V11-R2: H3 suffix chỉ thêm khi đúng 1 word + không phải câu hỏi

❌ Critical Bug mới phát hiện: 
_project_context không bao giờ được lưu vào brief dict — geo_schema_generator.py gọi brief.get('_project_context', None) nhưng KHÔNG có chỗ nào trong pipeline gán brief['_project_context'] = project. Kết quả: Organization Schema và GEO Checklist luôn thiếu brand/hotline info.

Tiêu chí Koray Framework
Điểm
Max
Ghi chú
1. Contextual Vector (H2 Attribute Filtration)
8
10
Agent 3a OK. Generic patterns: 5 từ. Chưa phát hiện 'phân tích', 'so sánh' standalone
2. Contextual Hierarchy (H3 Template Detection)
8
10
V11-R1: template_ratio>0.3 → penalty -8. V11-R2: suffix chỉ cho 1-word non-question. ✅
3. Contextual Structure (Per-H2 render)
9
10
V11-R3: ctx_v4 render đầy đủ 8+2 thành phần. word_count_target + section_predicates có trong prompt
4. GEO / AI Overview Schemas
7
10
Module geo_schema_generator.py mới. Critical: _project_context bug → Org Schema trống. FAQPage OK.
5. Topical Map Position
7
10
V11-S3 render Topical Map từ topics.csv. Jaccard cannibalization check. Tuy nhiên chỉ 12 topics
6. Internal Link (SUPP anchor)
9
10
V11-R4: [SUPP] → question format. Threshold 0.92. Agent 3d review anchor. ✅
7. EAV + FS/PAA Block
9
10
EAV LLM với đơn vị vật lý, [CẦN XÁC MINH]. FS ≤40 từ enforce. PAA anti-contamination
8. Source Context B2B Alignment
9
10
Brand/GEO/hotline inject. Tuy nhiên GEO Checklist (module mới) bị lỗi do _project_context
9. Score Calibration (Koray Analyzer)
8
10
10 tiêu chí + H3 template penalty (V11-R1). Opening sentence check trong GEO có lỗi logic
10. topics.csv Data Coverage
4
10
12 keywords trong topics.csv — quá ít. Internal link và Topical Map chất lượng thấp hơn tiềm năng

Điểm tổng: 87/100 (Grade A-) — sau khi fix 1 critical bug: ~92/100 (Grade A)

II. CÁC THAY ĐỔI V11 — ĐỐI CHIẾU VỚI ROADMAP
Roadmap từ báo cáo V10 liệt kê 8 fix theo ưu tiên P0→P2. Bảng dưới đánh giá từng item:

Thành phần / Điểm kiểm tra
Trạng thái
Nhận xét chi tiết
🔴 P0 — modules/geo_schema_generator.py (module mới)
🆕
164 dòng. Có Organization/FAQPage/Product JSON-LD + GEO Checklist 5 tiêu chí. Tích hợp vào markdown_exporter. NHƯNG critical bug _project_context (xem mục III)
🔴 P0 — Render ctx_v4 per-H2 vào markdown output
✅
V11-R3: markdown_exporter.py ~dòng 308-365. Render Macro Rules + 10 thành phần per-H2 đầy đủ. writer THẤY word_count_target + section_predicates
🟡 P1 — word_count_target + section_predicates trong Agent 4
✅
agent_reviewer.py: ⑨ Word Count Target + ⑩ Section Predicates thêm vào system prompt. JSON schema có 2 field mới. max_tokens=3000
🟡 P1 — H3 template quality detection trong scorer
✅
V11-R1: koray_analyzer.py dòng 192-206. Detect '??' hoặc '[' trong H3 text. template_ratio>0.3 → strict_penalty += 8
🟡 P1 — Topical Map Position render trong brief
✅
V11-S3: markdown_exporter.py dòng 367-418. Đọc topics.csv, render table với marker '→ Đang viết'. Jaccard >0.6 → cảnh báo cannibalization
🟢 P2 — topics.csv mở rộng 50-80 từ khoá
◻
CHƯA THỰC HIỆN. Vẫn 12 keywords. Topical Map và Internal Link kém hiệu quả hơn tiềm năng
🟢 P2 — internal_linking.py _pick_anchor() SUPP question
✅
V11-R4: if '[SUPP]' in source_h2 → trả về variants.get('question'). Đúng Koray Rule 6 Lecture 53
🟢 P2 — H3 suffix 'điều gì cần lưu ý' chỉ cho 1-word
✅
V11-R2: content_brief_builder.py dòng 1077-1079. if '?' not in h3_text and len(h3_text.split()) <= 1 → mới thêm suffix

III. CRITICAL BUG MỚI PHÁT HIỆN — _project_context
Mức độ: 🔴 P0 — Blocking | File: markdown_exporter.py dòng 425 + geo_schema_generator.py dòng 31

Mô tả lỗi
GEO module gọi brief.get('_project_context', None) để lấy thông tin brand khi sinh Organization Schema. Nhưng không có chỗ nào trong pipeline gán key này vào brief dict.

P
File/Vị trí
Vấn đề
Trạng thái / Fix
🔴
main_generator.py dòng 391
export_to_markdown(brief, output_dir) — không pass project
Cần: brief['_project_context'] = project TRƯỚC khi gọi export_to_markdown. Hoặc thêm param project vào signature
🔴
geo_schema_generator.py dòng 31-46
org_schema dùng project.brand_name, hotline, geo_keywords — nhưng project=None luôn
Khi _project_context = None: Org Schema không được render. GEO Checklist: 2/5 checks thất bại
🔴
geo_schema_generator.py dòng 149
sapo_ok = 30 ≤ sapo_words ≤ 50 — sai logic
SAPO chuẩn là 80-120 từ (scorer tiêu chí 9 check 56-156). GEO checklist check 30-50 là opening sentence FS — nhưng lại đọc micro_briefing[0].snippet là FULL SAPO, không phải opening sentence riêng

Fix cụ thể
Fix 1 — gán _project_context trước khi export (main_generator.py): 
Thêm dòng brief['_project_context'] = project trước dòng 391 (gọi export_to_markdown). Không cần thay đổi signature.

Fix 2 — Opening sentence check logic (geo_schema_generator.py dòng 144-149): 
Không nên đọc snippet của micro_briefing[0] làm opening sentence. Opening sentence = 50 từ đầu tiên của SAPO snippet. Sửa: opening = ' '.join(sapo.split()[:50]) rồi check len(opening.split()) >= 20.

IV. AUDIT CHI TIẾT TỪNG MODULE
4.1 geo_schema_generator.py (MỚI — 164 dòng)
Điểm mạnh ✅
3 schemas đầy đủ: Organization (brand/hotline/geo), FAQPage (từ PAA top 5), Product (parse từ EAV table)
Deduplication answer: used_answers set tránh lặp câu trả lời giữa các FAQ entries
Fallback graceful: nếu không có PAA → không render FAQPage. Nếu EAV trống → không render Product
[CẦN XÁC MINH] filter: loại bỏ EAV values không xác định khỏi Product schema additionalProperty
FAQPage answer: word overlap matching micro_briefing snippet — đúng semantic approach

Vấn đề cần fix ⚠️
Critical: _project_context = None luôn. Organization Schema render trống rỗng (xem mục III)
FAQPage answer truncate [:200] characters — có thể cắt giữa câu tiếng Việt. Nên truncate theo từ: ' '.join(answer.split()[:40])
Product Schema @type='Product' cho bài 'thép thanh vằn là gì' là hơi aggressive — đây là informational article, không phải product page. Nên thêm condition: chỉ sinh Product schema nếu search_intent là 'commercial' hoặc 'transactional'
GEO Checklist: 'Opening sentence 30-50 từ' check logic sai — đọc SAPO snippet (80-120 từ) thay vì opening sentence thực sự

4.2 markdown_exporter.py — V11 additions
Per-H2 Contextual Instructions (V11-R3) ✅
ctx_v4 render đầy đủ: Macro Rules (central_entity, predicate_cluster, tonality) + per-H2 loop
Handles cả 2 formats JSON: dict {h2_name: {...}} và list [{h2: ..., ...}]
word_count_target và section_predicates render nếu có trong JSON response từ Agent 4
Graceful degradation: nếu per_h2_dict rỗng → skip section (không crash)

Topical Map Position (V11-S3) ✅
Đọc topics.csv dynamic từ root directory — tự động update khi CSV thêm topics
Render bảng với marker '→ Đang viết' cho current topic
Jaccard cannibalization check: overlap > 0.6 → cảnh báo merge/tách intent

GEO Schema render (V11-S1) ⚠️
Gọi generate_geo_schemas với _project = brief.get('_project_context', None)
Bug: _project_context không bao giờ được gán vào brief. Organization schema sẽ luôn trống
Header render logic: lines.append(f'## {section_num}. {geo_md.split(chr(10))[0].replace("## ", "")}') — nếu geo_md bắt đầu bằng dòng trắng sẽ render section header trống

4.3 agent_reviewer.py — Per-H2 + 10 thành phần
Cải tiến V11 ✅
⑨ Word Count Target: '200-300 từ cho MAIN Definition, 300-400 từ cho Technical, 100-150 từ cho SUPP'
⑩ Section Predicates: 3-5 động từ đặc thù per section — Koray Lecture 39 'predicates define context'
max_tokens tăng lên 3000 cho Agent 4 — đủ cho 8-12 H2 với 10 thành phần mỗi H2
JSON schema output cập nhật: word_count_target + section_predicates trong per_h2 object

Vấn đề còn lại ⚠️
LLM được yêu cầu sinh word_count_target nhưng không có ground truth để validate. LLM có thể sinh '100-150 từ' cho MAIN Definition — scorer không check per-H2 word count
section_predicates list of verbs: format validated bằng json.loads nhưng không check nếu LLM trả về strings thay vì list

4.4 koray_analyzer.py — V11-R1 H3 Template Detection
Fix đúng ✅
template_h3_count: sum 1 nếu '??' in text hoặc '[' in text → phát hiện artifact từ fallback
template_ratio > 0.3 → strict_penalty += 8 (không cộng vào scores, trừ thẳng khỏi total)
Threshold 30% hợp lý: cho phép 1-2 fallback H3 trong bài nhiều H2 mà không bị penalize

Điểm còn bỏ sót ⚠️
Pattern '[' quá broad: tên thép thường chứa '[SS400]', '[Q235]' hợp lệ → sẽ bị đếm là template. Nên narrow hơn: chỉ '[' ở đầu text hoặc '[[' patterns
Chưa detect H3 có nội dung 'Yếu tố nào ảnh hưởng đến X?' (fallback logic line 1119 cb_builder) — generic nhưng không chứa '??' hay '['

4.5 content_brief_builder.py — V11-R2 H3 Suffix
Fix đúng ✅
if '?' not in h3_text and len(h3_text.split()) <= 1 → chỉ thêm suffix nếu đúng 1 word và không phải câu hỏi
V12 sanitize: h3_text.replace('??','?') + rstrip('?')+'?' nếu có '?' — loại double-question artifacts
is_natural_q check: nếu H3 đã là câu hỏi tự nhiên mà có 'điều gì cần lưu ý' → strip suffix

Edge case cần monitor ⚠️
H3 = 'SS400' (tên grade thép, 1 token nhưng uppercase) → sẽ nhận suffix 'SS400 — điều gì cần lưu ý?' → không phù hợp. Nên thêm: hoặc h3_text là ALLCAPS → skip suffix

4.6 internal_linking.py — V11-R4 SUPP Anchor
Fix đúng ✅
_pick_anchor(variants, source_h2): if '[SUPP]' in source_h2.upper() → return variants.get('question', ...)
Fallback chain: variants['question'] → variants['primary'] → variants['exact'] → ''
Nhất quán với Koray Rule 6: SUPP section anchor nên dạng câu hỏi để tạo curiosity gap

4.7 serp_competitor_analyzer.py — LLM Semantic Voids (không trong V11 roadmap)
Module này đã tăng từ ~500 dòng lên 1050 dòng. Phát hiện thêm tính năng mới không có trong roadmap:
_compute_semantic_voids_llm(): gọi LLM để phát hiện semantic voids từ competitor content — thay cho rare_headings đếm đơn giản
final_gaps = semantic_voids if semantic_voids else list(rare_headings)[:15] — fallback graceful
Đây là cải tiến quan trọng: rare_headings trước đây chỉ đếm H2 xuất hiện 1 lần trên competitor. LLM semantic voids phát hiện khoảng trống thực sự về mặt nghĩa


V. REGRESSION CHECK — 7 BUG CŨ KHÔNG BỊ BREAK
Xác nhận tất cả 7 bug từ V9 vẫn còn được giữ fix, không bị regression:

Thành phần / Điểm kiểm tra
Trạng thái
Nhận xét chi tiết
Bug #1: EAV topic_entity strip 'là gì'
✅
content_brief_builder.py dòng 826: topic_entity = topic.replace('là gì','').strip()
Bug #2: best_score > 0 → không random pick
✅
content_brief_builder.py: if best_score > 0 and best_match_idx is not None kiểm tra trước
Bug #3: Boolean tautology entity strip
✅
entity = main_keyword.replace('là gì','').strip().title()
Bug #4: Jaccard threshold 0.92 anti-false-positive
✅
internal_linking.py dòng 440: threshold=0.92
Bug #5: Anchor 'có ưu điểm gì?' thay 'vì sao cần'
✅
internal_linking.py dòng 113: question = f'{base_lower} có ưu điểm gì?'
Bug #6: len(h) < 50 generic H2 detection
✅
koray_analyzer.py dòng 165: len(h) < 50
Bug #7: anchor_quality check 2+ words
✅
koray_analyzer.py dòng 289-290: all(len(n.get('anchor','').split()) >= 2 ...)

VI. KHOẢNG TRỐNG CÒN LẠI SAU V11
Sau khi giải quyết 3 khoảng trống chiến lược lớn, còn 2 vấn đề dữ liệu và 1 logic lỗi cần xử lý để đạt Grade A+:

Khoảng trống 1: topics.csv chỉ 12 từ khoá (Data Gap)
Vấn đề này được liệt kê trong roadmap V10 là P2 nhưng chưa được thực hiện. Với 12 topics:
Topical Map Position table quá thưa — writer không thấy full context của network
Internal link suggestions ít meaningful — chỉ 12 bài để trỏ đến
Cannibalization check Jaccard = false negatives nhiều — nhiều bài chủ đề gần nhau chưa có trong list

Đề xuất: Mở rộng topics.csv theo product hierarchy của Thép Trần Long: 5 nhóm × 8-10 từ khoá/nhóm = 40-50 từ khoá ban đầu. Nhóm: (1) Thép hình H/I/U/V/C, (2) Thép tấm/cuộn, (3) Ống thép đen/mạ kẽm, (4) Thép cây/vằn/tròn, (5) Tôn + Xà gồ C/Z. Sau đó bổ sung queries về giá, tiêu chuẩn, ứng dụng.

Khoảng trống 2: Scorer không validate word_count_target LLM (Logic Gap)
Agent 4 được yêu cầu sinh word_count_target per-H2 nhưng scorer (koray_analyzer.py) không có tiêu chí nào kiểm tra xem:
word_count_target có được điền hay không
Format có hợp lệ không (string '200-300 từ' vs số 200)
Per-H2 distribution có balanced không (không phải tất cả 100-150 từ)

Đề xuất: Thêm tiêu chí 11 vào scorer: 'Per-H2 Writing Guidance' — check xem có ≥50% H2 MAIN có word_count_target trong contextual_structure_v4 không. Điểm 0/5/10.

Khoảng trống 3: Không có Opening Sentence riêng biệt (SEO Gap)
GEO.docx yêu cầu 'Rewrite the opening to answer the main question in 1-2 clear sentences, 30-50 words max'. SAPO của tool là 80-120 từ — đây là introductory paragraph, không phải opening sentence AI Overview.
Cần tách biệt 2 concept: Opening Sentence (câu đầu tiên ≤50 từ, direct answer) và SAPO (80-120 từ, context + brand).
Opening Sentence = micro_briefing[0].snippet nhưng chỉ lấy 50 từ đầu tiên — không đủ
Cần 1 field riêng 'opening_sentence' trong Micro-Briefing framework, distinct với SAPO full

VII. ROADMAP V12 — ƯU TIÊN

P
File/Vị trí
Vấn đề
Trạng thái / Fix
🔴
main_generator.py dòng ~391
_project_context không lưu vào brief — GEO Org Schema trống
brief['_project_context'] = project TRƯỚC export_to_markdown(). 1 dòng fix. Impact: Organization Schema hoạt động đầy đủ
🔴
geo_schema_generator.py dòng 144-149
Opening sentence check 30-50 từ đọc SAPO 80-120 từ — logic sai
opening = ' '.join(sapo.split()[:50]); sapo_ok = len(opening.split()) >= 20. Hoặc tạo field 'opening_sentence' riêng
🔴
geo_schema_generator.py dòng 110
Product Schema sinh cho informational articles — không phù hợp
Thêm condition: intent = brief.get('search_intent'); only if 'commercial' or 'transactional' in str(intent).lower()
🟡
geo_schema_generator.py dòng 92
FAQPage answer truncate [:200] chars — cắt giữa câu
Đổi: ' '.join(answer.split()[:40]) — cắt theo từ thay vì ký tự
🟡
koray_analyzer.py dòng 197
Pattern '[' detect H3 template quá broad — bắt '[SS400]' hợp lệ
Đổi: t.startswith('[') or '??' in t — chỉ '[' ở đầu text mới là template
🟡
topics.csv (Data)
12 keywords — Topical Map và Internal Link kém
Mở rộng 40-50 keywords theo 5 nhóm sản phẩm Thép Trần Long (xem mục VI)
🟢
koray_analyzer.py
Không có tiêu chí 11 kiểm tra per-H2 word_count coverage
Thêm s11: check ≥50% H2 MAIN có word_count_target trong ctx_v4.per_h2
🟢
content_brief_builder.py dòng 1109
H3 = 'SS400' (tên grade) nhận suffix không phù hợp
Thêm: if h3_text.isupper() or h3_text == h3_text.upper() → skip suffix

Dự báo: Fix 3 bug 🔴 → Grade A (~92/100). Fix toàn bộ P0+P1+P2 → Grade A+ (~95/100).

VIII. ĐIỂM MẠNH ĐỘC ĐÁO SO VỚI TOOL GENERIC
Sau V11, tool này vượt trội so với các content brief tools thông thường (Surfer SEO, Frase, Clearscope...) về 5 điểm:

Pipeline SERP-First thực sự: SERP crawl → competitor analysis → LLM Semantic Voids — không hallucinate. PAA, rare_headings, ngrams từ Google thực. serp_competitor_analyzer.py 1050 dòng với LLM semantic void detection
Koray Framework End-to-End: 4 Agent passes (3a Structure, 3b H3, 3c N-gram, 3d Anchor) + Agent 4 Per-H2 với 10 thành phần — không tool nào trên thị trường implement đầy đủ Koray methodology
Source Context B2B Injection: Thép Trần Long brand/hotline/GEO được inject tự nhiên vào SAPO, SUPP bridge. Không phải boilerplate append — là semantic integration
GEO Structured Data automated: JSON-LD Organization/FAQPage/Product tự động generate từ brief data. Sau khi fix _project_context bug, đây sẽ là competitive advantage lớn
Strict Anti-Inflation Scoring: Structural Cap, 3 strict penalties, Prominence Penalty, H3 Template Detection. Score không bị inflate bởi H2/H3 nhiều nhưng kém chất lượng


Báo cáo Code Audit — Koray Framework Compliance Analysis
Thép Trần Long — ThepTranLong.vn — Hotline: 0936 179 626