📋 BÁO CÁO PHÂN TÍCH
AI Content Brief Generator
Universal Multi-Niche Edition — Đánh giá theo Khung Koray Semantic SEO
Phiên bản phân tích: V10  |  Tháng 3/2026

ĐIỂM TỔNG
72 / 100
Grade B+
Phạm vi đánh giá
• Kiến trúc pipeline 7-tầng (Universal Niche Engine)
• Source Context injection theo Koray Framework
• 5 chuyên biệt Agents: Outline → Semantic → Review → Per-H2
• GEO / AI Overview schema optimization
• Topical Map positioning & Koray Lecture compliance
Kết luận
Universal
Engine
Niche-adaptive
theo Source Context

1. Executive Summary — Nhận Định Tổng Quan
ℹ️  LƯU Ý QUAN TRỌNG: Tool này được thiết kế cho MỌI NGÀNH, không giới hạn thép/xây dựng. User nhập Source Context (brand, industry, USP, target customer, tone...) + từ khóa mục tiêu, tool tự adapt logic brief phù hợp với bất kỳ niche nào.

Đây là một AI-powered Content Brief Generator đa ngành được xây dựng theo khung Koray Semantic SEO. Tool vận hành theo mô hình: user khai báo Source Context của website (brand profile) → nhập từ khóa mục tiêu → pipeline tự động sinh ra Full Content Brief chuẩn semantic, được cá nhân hóa theo ngành và intent.

Kiến trúc Universal — Tự Adapt Theo Source Context
Pipeline được thiết kế để tự nhận diện và thích nghi với bất kỳ lĩnh vực nào:
Bước 1 — User khai báo Source Context: Brand name, domain, ngành (industry), sản phẩm chính, USP, khách hàng mục tiêu, tone văn phong, tiêu chuẩn kỹ thuật ngành, GEO keywords, NAP (địa chỉ, hotline, email).
Bước 2 — User nhập từ khóa mục tiêu (+ tuỳ chọn: topics.csv cho topical map).
Bước 3 — Tool chạy SERP analysis → Entity extraction → Niche detection (detect_niche) → Inject Source Context → 5 Agents sinh brief → GEO schema → Markdown export.

💡  detect_niche() tự phân loại keyword vào 5 niche: food_health / tech_gadget / construction_material / finance_law / general. Fallback về "general" nếu không khớp. Mỗi niche có EAV template và E-E-A-T guidance riêng. Source Context từ user override tất cả logic hardcoded.

Verdict
Tool đạt Grade B+ (72/100). Pipeline kỹ thuật 7-tầng vững chắc, cơ chế adapt-by-source-context hoạt động đúng nguyên lý Koray. Tuy nhiên có 4 khoảng trống chiến lược cần fix để đạt A (85+/100): 2 lỗi P0 render (không mất points nhưng writer không thấy guidance), 2 gap P1 về Topical Map và word count per-H2.

2. Kiến Trúc Universal — Source Context Engine
2.1 Cơ Chế User Input → Brief Adaptation
Toàn bộ quá trình cá nhân hóa brief theo ngành được điều khiển bởi 2 yếu tố do user cung cấp:

Input Layer
Fields
Tác động tới Brief
Brand Profile
(Source Context)
brand_name, domain, industry, main_products, usp, target_customers, tone, technical_standards, geo_keywords, hotline, address, warehouse
NAP inject vào [SUPP], tone guide toàn bài, competitor blacklist, B2B/B2C auto-detect, EAV units theo ngành
Target Keyword
(Từ khóa chính)
1 từ khóa chính + topics.csv (optional)
SERP intent detection, niche classification, topical map positioning, attribute filtration vector

Source Context → inject_source_context()
Function inject_source_context() trong semantic_knowledge.py thực hiện prepend Source Context block vào đầu mọi system prompt của các Agent, đảm bảo ngay cả Agent 1 (Outline) cũng đã biết brand là ai, ngành nào, tone gì, đối thủ nào không được làm H2 MAIN.

✅  Điểm mạnh: Source Context được inject TRƯỚC khi Agent 1 tạo outline. Điều này đảm bảo toàn bộ cấu trúc H2/H3 được sinh ra đã phù hợp với ngữ cảnh brand ngay từ đầu, không cần post-process lại.

2.2 Niche Detection Engine — 5 Ngành Tự Động
detect_niche(keyword) phân tích keyword để chọn EAV template và E-E-A-T guidance phù hợp:

Niche
Ví dụ từ khóa (bất kỳ ngành)
EAV Template
E-E-A-T Focus
food_health
thực phẩm, dinh dưỡng, dược phẩm, supplement, diet
Dinh dưỡng, lâm sàng, đơn vị mg/g
Y tế, bác sĩ, nghiên cứu
tech_gadget
laptop, điện thoại, phần mềm, SaaS, AI tools, thiết bị
Specs, benchmark, so sánh
Hands-on, test thực tế
construction_material
vật liệu xây dựng, thép, xi măng, nội thất, bất động sản
Kích thước, cường độ, tiêu chuẩn
Thi công, tiêu chuẩn ngành
finance_law
đầu tư, tài chính, pháp lý, bảo hiểm, thuế, kế toán
Điều luật, số liệu, case study
Trích dẫn pháp lý, YBYL
general (fallback)
Du lịch, giáo dục, marketing, lifestyle, thương mại điện tử, bất kỳ ngành nào khác
Dữ liệu có nguồn, trải nghiệm thực tế
Source uy tín, minh bạch

⚠️  Lưu ý quan trọng: detect_niche() dựa trên keyword NẾU không có Source Context. Khi user đã khai báo industry trong Source Context, giá trị đó sẽ OVERRIDE detect_niche. Ví dụ: website du lịch viết bài về "thép" → Source Context industry="du lịch" → brief sẽ không dùng niche construction_material.

2.3 B2B / B2C Auto-Detection
Tool tự detect intent B2B hay B2C từ Source Context của user để điều chỉnh:
Prominence Blacklist: B2B blacklist loại bỏ H2 như "tác động môi trường", "quy trình sản xuất" — các gap term không có search demand trong ngữ cảnh phân phối/cung cấp B2B.
Detector: Kiểm tra industry + usp của project. Signal: "phân phối", "cung cấp", "đại lý", "nhà máy", "b2b".
Fallback (no project): Nếu user không khai báo project, detect từ topic keyword — đây là fallback an toàn.

⚠️  Gap cần cải thiện: B2B fallback hiện chỉ cover từ ngành construction (thép, xi măng, tôn...). Nếu user là B2B ngành dược, logistics, phần mềm B2B thì sẽ không được detect đúng khi không có Source Context. Khuyến nghị: mở rộng b2b_topic_signals bằng cách parse industry từ Source Context thay vì dựa vào keyword match.

3. Scorecard — Đánh Giá Chi Tiết
Đánh giá dựa trên Koray Semantic SEO Framework, Google HCU, và GEO/AI Overview optimization guidelines.

Tiêu chí đánh giá
Điểm
Tối đa
Nhận xét
Contextual Vector (H2 Attribute Filtration)
8
10
Attribute Trinity hoạt động tốt, một số attribute vẫn generic khi no-project
Contextual Hierarchy (H3 Depth)
7
10
H3 từ 5 nguồn đúng spec, nhưng có template artifact "??" trong fallback
Contextual Structure (Per-H2 Instructions)
7
10
Agent 4 sinh đủ 8 thành phần nhưng KHÔNG render ra output cho writer
Contextual Connection (Internal Link)
7
10
Anchor rules 1-5 đúng, Rule 6 SUPP anchor format chưa implement
FS/PAA Block (Featured Snippet)
9
10
FS ≤40 từ enforce chặt, Exact Definitive Answer pattern chuẩn
EAV Coverage
9
10
EAV với đơn vị đo, [CẦN XÁC MINH] flag, adapt theo niche
Source Context / Universal Adaptation
9
10
inject_source_context() đúng vị trí, niche-adaptive, B2B detection
GEO / AI Overview Optimization
4
10
FAQPage schema lỗi logic answer, Organization schema thiếu field
Score Calibration (Koray Analyzer)
7
10
Template penalty chưa đủ mạnh, H3 artifact không bị penalize đủ
Topical Map / Positional Awareness
4
10
topics.csv không render vào brief, writer không biết vị trí bài trong map

TỔNG ĐIỂM
72 / 100 (Grade B+)

4. Điểm Mạnh — Những Gì Tool Đã Làm Đúng
4.1 Pipeline 7-Tầng Hoàn Chỉnh
Tool triển khai đúng tinh thần Koray: không phải 1 LLM call sinh toàn bộ, mà là 7 tầng processing độc lập, mỗi tầng có nhiệm vụ riêng:

Tầng
Module
Chức năng
1
SERP Competitor Analyzer
Phân tích top 10 SERP, extract heading structure, detect intent
2
Topic Analyzer + EAV Generator
Entity extraction, EAV table theo niche, PAA clustering
3
Semantic Query Network
N-gram analysis, semantic cluster, intent mapping
4
Agent 1 — Outline Builder
Sinh H2/H3 với Attribute Filtration Trinity + Source Context
5
Agent 2 — Semantic Rewriter + Agents 3a/3b/3c/3d
Review structure, H3 depth, N-gram quality, anchor quality
6
Agent 4 — Per-H2 Contextual Structure
8 thành phần Koray Lecture 21/39 cho từng H2
7
GEO Schema + Markdown Exporter
JSON-LD schemas + render brief ra file Markdown

4.2 Koray Framework — Compliance Chi Tiết

Lecture
Principle
Implementation
Status
L13
Featured Snippet ≤40 từ, Exact Definitive Answer
_enforce_fs_length() + FS template
✅ Đúng chuẩn
L14
MAIN/SUPP split, không đặt internal link trong MAIN
SUPP Enforcer + anchor checker
✅ Đúng chuẩn
L16
Attribute Filtration Trinity (Quality/Dimension/Application)
Agent 1 prompt + H2 rewriter
✅ Đúng chuẩn
L21/39
8 thành phần per-H2 Contextual Structure
Agent 4 generate → KHÔNG render
⚠️ Gen OK / Render MISS
L23
Distance giữa internal links
internal_linking.py spacing rules
✅ Đúng chuẩn
L38
H2 = sub-article/summary của H3
Agent 2 semantic rewrite
✅ Đúng chuẩn
L47
H3 tổng hợp từ 5 nguồn SERP
Agent 3b review_h3_depth
✅ Đúng chuẩn
L53
Anchor = entity+attribute, không chỉ adjective
Agent 3d anchor quality review
✅ Đúng chuẩn
L57
Word count target per-H2
Chỉ có SAPO target
❌ Thiếu
L4
Topical Map position trong brief
topics.csv có nhưng không render
❌ Thiếu
L13+
Hash Anchor (#H2-identifier)
Chưa implement
❌ Chưa có

5. Khoảng Trống Chiến Lược — Fix Roadmap
4 gaps sau đây là nguyên nhân khiến tool chỉ đạt B+ thay vì A. Ưu tiên theo mức độ ảnh hưởng đến chất lượng brief mà writer nhận được.

🚨  P0 — Critical #1: Per-H2 Agent 4 Output Không Render Ra Brief

Agent 4 (generate_per_h2_instructions) tạo ra dict brief['contextual_structure_v4'] với đầy đủ 8 thành phần Koray Lecture 21/39:
Content Format (narrative / listicle / comparison / how-to)
Micro Terms (5-8 semantic terms bắt buộc cover)
Tonality (formal / conversational / technical)
Word Count Target
FS/PAA answer block
Internal Link placement
Image/Media guidance
CTA instruction

🚨  Vấn đề: markdown_exporter.py hoàn toàn không có code render section contextual_structure_v4. Writer nhận brief chỉ thấy outline H2/H3 + micro-briefing tổng, không thấy per-H2 instructions cụ thể. Đây là lý do chính khiến writer vẫn sản xuất content generic dù tool đã chạy Agent 4.

Fix — markdown_exporter.py
Thêm render block sau section Micro-Briefing hiện tại:
ctxv4 = brief.get('contextual_structure_v4', {})
for h2_key, inst in ctxv4.items():
    md += f'\n### {h2_key}\n'
    for field in ['content_format','micro_terms','tonality',
                   'word_count','fs_answer','link_placement',
                   'media_guidance','cta']:


🚨  P0 — Critical #2: H3 Template Artifact "??" Trong Output

Hệ thống _enforce_h3_ratio thêm suffix fallback vào H3 khi tỉ lệ H3/H2 thấp hơn ngưỡng. Kết quả là output thực tế có H3 dạng: "lưu ý quan trọng khi áp dụng [entity] ??" — dấu ?? là artifact không mong muốn.

🚨  Vấn đề ảnh hưởng mọi niche: Dù keyword là thực phẩm, tài chính hay du lịch, _enforce_h3_ratio đều có thể sinh ra artifact này. Penalty hiện tại (template_ratio > 0.5: -5 điểm) chưa đủ mạnh để ngăn chặn.

Fix 1 — koray_analyzer.py ~line 163
Tăng penalty: nếu template_ratio > 0.3 (thay vì 0.5) thì strict_penalties += 8 (thay vì 5).
Fix 2 — _enforce_h3_ratio
Chỉ append suffix nếu H3 text chưa phải câu hỏi tự nhiên. Kiểm tra: h3_text không chứa "?", "là gì", "như thế nào", "khi nào", "tại sao", "bao nhiêu", "có nên".

⚠️  P1 — High Priority: Topical Map Position Không Hiển Thị

Koray Lecture 4: "mỗi search query chỉ là 1 bước trong cuộc đua 100m — brief phải chỉ rõ bài này đứng ở đâu trong map để writer hiểu độ sâu cần thiết." topics.csv đã tồn tại (12 keywords) nhưng không được render vào brief output.

⚠️  Hậu quả với mọi ngành: Dù website là về thực phẩm, SaaS, hay du lịch, writer không biết bài hiện tại là ROOT của cluster hay NODE phụ. Dẫn đến: ROOT bị viết quá ngắn, NODE bị viết quá dài và overlap với bài khác (keyword cannibalization).

Fix — markdown_exporter.py
Thêm section "🗺️ Topical Map Position" ngay sau header brief:
Hiển thị: bài hiện tại là ROOT / NODE / PILLAR
3 bài upstream (parent + siblings có intent rộng hơn)
3 bài downstream (child articles có intent hẹp hơn)
Cannibalization warning nếu Jaccard similarity > 0.6 với bài khác trong map

Long-term Recommendation
Mở rộng topics.csv từ 12 lên ≥ 50 keywords để Topical Map Position thực sự có ý nghĩa. Với 12 entries, context map quá mỏng để phát hiện cannibalization.

⚠️  P1 — High Priority: Word Count Guidance Per-H2 Thiếu

Koray Lecture 57: "brief phải chỉ định số từ cụ thể cho từng H2 section, không phải chỉ tổng bài." Hiện tại tool chỉ có SAPO target (80-120 từ). Các H2 khác không có word count guidance.

Fix — generate_per_h2_instructions() trong content_brief_builder.py
Thêm word_count_target vào dict output của Agent 4:
Section Type
Word Count Target
Ghi chú
MAIN — Definition/Answer
200–300 từ
H2 trả lời trực tiếp intent chính
MAIN — Technical/Data
300–400 từ
H2 có bảng dữ liệu, thông số kỹ thuật
MAIN — Comparison
400–600 từ
H2 so sánh, đánh giá nhiều options
SUPP — FAQ
100–150 từ/Q
Mỗi Q&A trong FAQ block
SUPP — NAP/Contact
60–80 từ
Block Source Context, không viết nhiều hơn

6. GEO & AI Overview — Lỗi Cần Fix
6.1 FAQPage Schema — Lỗi Logic Answer
File geo_schema_generator.py có bug nghiêm trọng: vòng lặp qua 5 PAA questions nhưng answer luôn lấy từ H2 đầu tiên trong micro_data thay vì tìm H2 liên quan nhất.

🚨  Hậu quả: 5 FAQ entries trong JSON-LD schema đều có cùng 1 answer text → Google/AI Overview parse xong thấy duplicate → không index vào AI snapshot. Bug này xảy ra với mọi ngành, mọi keyword.

Fix — geo_schema_generator.py
Thêm function _find_relevant_mb(micro_data, question) sử dụng word overlap matching để mỗi PAA question tìm đúng H2 micro-briefing liên quan nhất làm answer. Nếu không tìm được match thì dùng generic answer thay vì duplicate H2 đầu tiên.

6.2 B2B Blacklist — Title Case Bypass
B2B_BLACKLIST có pattern "tác động môi trường" nhưng input H2 từ Agent 1 thường là Title Case ("Tác Động Môi Trường"). Pattern match case-sensitive sẽ bypass blacklist.

Fix — _postprocess_prominence_blacklist()
Đã có .lower() trong so sánh (h_text_lower). Tuy nhiên, nên chuyển sang pattern matching rộng hơn: kiểm tra sự kết hợp của ("tác động", "ảnh hưởng") AND ("môi trường", "khí thải") thay vì exact phrase.

6.3 SUPP Anchor Rule 6 — Chưa Implement
Koray Rule 6: anchor trong SUPP sections nên dùng question format (ví dụ: "mua thép ở đâu uy tín?" thay vì "thép uy tín"). Code hiện tại không distinguish MAIN vs SUPP khi chọn anchor variant.

Fix — internal_linking.py
Nếu source_h2 chứa tag [SUPP] → pick variants['question'] làm anchor format thay vì variants['default'].

7. Full Checklist — Universal Application
Checklist này áp dụng cho mọi ngành mà tool phục vụ. Sử dụng khi review brief output trước khi chuyển cho writer.

7.1 Source Context Setup — Kiểm Tra Trước Khi Chạy
✓
Checklist Item
Ghi chú / Ví dụ
☐
brand_name & domain đã điền chính xác
VD: TechViet / techviet.vn
☐
industry mô tả đúng lĩnh vực (1 dòng ngắn)
VD: "Phân phối thiết bị y tế B2B"
☐
main_products liệt kê sản phẩm/dịch vụ cốt lõi
Tối đa 5-7 items
☐
usp nêu rõ lợi thế cạnh tranh khác biệt
Câu ngắn, có thể dùng làm CTA
☐
target_customers mô tả đúng persona
B2B: "kỹ sư, chủ thầu, procurement" | B2C: "người tiêu dùng 25-45 tuổi"
☐
tone phù hợp với brand và audience
VD: "chuyên nghiệp, trực tiếp, không hoa mỹ"
☐
technical_standards khai báo tiêu chuẩn ngành (nếu có)
VD: ISO 9001, TCVN, FDA, CE...
☐
geo_keywords chứa địa danh mục tiêu
VD: "Hà Nội, TP.HCM, Đà Nẵng"
☐
hotline & address đầy đủ cho NAP block
Sẽ inject vào cuối bài [SUPP]
☐
competitor_brands liệt kê brand đối thủ không được H2 MAIN
Tránh vô tình quảng bá đối thủ

7.2 Brief Output Quality — Checklist Sau Khi Chạy
[MAIN/SUPP] tag xuất hiện đúng: ≥3 MAIN, tỉ lệ SUPP 20-35%
H3 count: mỗi H2 MAIN có 3-5 H3, không có H2 empty
Featured Snippet answer ≤ 40 từ, là câu định nghĩa trực tiếp
EAV table: entity đúng, attribute đủ, unit/value điền [CẦN XÁC MINH] nếu không chắc
NAP block: brand name + hotline + địa chỉ xuất hiện trong [SUPP] cuối bài
Internal links: không có link nào trong [MAIN] H2, chỉ trong [SUPP]
Anchor text: không phải tính từ đơn thuần, phải là entity + attribute
Không có H2 về brand đối thủ trong danh sách competitor_brands
Per-H2 instructions: render đủ Content Format, Micro Terms, Word Count (sau khi fix P0)
Topical Map: bài là ROOT hay NODE, upstream/downstream rõ ràng (sau khi fix P1)

8. Implementation Roadmap

#
Priority
Task
File
Impact
1
🚨 P0
Render contextual_structure_v4 vào markdown output
markdown_exporter.py
+8 điểm Contextual Structure
2
🚨 P0
Fix FAQPage answer logic — per-question matching
geo_schema_generator.py
+5 điểm GEO / AI Overview
3
🚨 P0
Fix H3 artifact "??" — không append suffix nếu đã là câu hỏi tự nhiên
content_brief_builder.py
+2 điểm H3 Quality
4
⚠️ P1
Render Topical Map Position trong brief output
markdown_exporter.py
+5 điểm Topical Map
5
⚠️ P1
Thêm word_count_target per-H2 vào Agent 4 output
content_brief_builder.py
+2 điểm Contextual Structure
6
⚠️ P1
Mở rộng topics.csv từ 12 → ≥50 keywords
topics.csv
Topical Map thực sự hữu dụng
7
💡 P2
SUPP anchor Rule 6 — question format variant
internal_linking.py
+1 điểm Internal Link
8
💡 P2
B2B detection từ industry field thay vì keyword match
content_brief_builder.py
Accuracy cho mọi ngành B2B
9
💡 P2
Hash Anchor (#H2-identifier) cho internal links
internal_linking.py
Koray Lecture 13+ compliance
10
💡 P2
Thêm food_health & general vào b2b_topic_signals fallback
content_brief_builder.py
Robustness đa ngành

✅  Sau khi fix 5 items P0+P1 đầu tiên, dự kiến điểm tổng đạt 87–90/100 (Grade A). Tool sẽ thực sự trở thành Universal Content Brief Generator chuẩn Koray cho mọi ngành.

9. Kết Luận
Tool Content Brief Generator này đã xây dựng đúng nền tảng kỹ thuật của một universal semantic SEO tool. Kiến trúc Source Context injection đảm bảo rằng khi user khai báo đúng brand profile, tool sẽ tự adapt brief phù hợp — dù là ngành thực phẩm, công nghệ, tài chính, hay bất kỳ lĩnh vực nào khác.

Điểm mạnh cốt lõi là pipeline không phụ thuộc vào hardcoded domain knowledge mà phụ thuộc vào Source Context do user cung cấp. Đây là thiết kế đúng: tool là orchestrator, user là domain expert. 4 khoảng trống hiện tại đều là rendering và completeness gaps — engine đã tính đúng nhưng chưa show ra đúng cho writer.

💡  Khuyến nghị cuối: Ưu tiên fix P0 render gaps trước. Writer hiện tại đang "miss" một nửa giá trị mà Agent 4 đã tạo ra vì markdown_exporter.py không render contextual_structure_v4. Đây là quick win lớn nhất với effort nhỏ nhất.
Báo cáo được tạo theo khung Koray Semantic SEO Framework  |  Tháng 3/2026