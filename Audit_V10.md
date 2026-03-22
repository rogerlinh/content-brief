
BÁO CÁO ĐÁNH GIÁ TOÀN DIỆN
Tool Tạo Content Brief – Thép Trần Long

Dựa trên Framework Semantic SEO của Koray Tuğberk Gürbüz

Source Code Version: Post-V9 Fix (7 bugs patched)
Ngày đánh giá: Tháng 3/2026


I. TÓM TẮT ĐIỀU HÀNH
Verdict tổng thể: Tool đã đạt Grade B+ (~78–82/100) — hoàn thiện về pipeline kỹ thuật nhưng còn 3 khoảng trống chiến lược quan trọng cần bổ sung trước khi đạt chuẩn Full Content Brief theo Koray Framework.

✅ Đã làm tốt (Grade A): Pipeline đa tầng 7 bước, SERP crawl thực tế, EAV Table LLM, Agent 3a–3d, Per-H2 Contextual Structure, Micro-Briefing A-B-C-D-E, Source Context B2B injection
⚠️ Còn thiếu (cần bổ sung): GEO/JSON-LD Schema, Topical Coverage Map hiển thị, Word Count Guidance per-H2, Predicate Cluster tracking, H3 template detection trong Scorer

Tiêu chí Koray
Điểm
Tối đa
Nhận xét
Contextual Vector (H2 Attribute Filtration)
8
10
Agent 3a rewrite tốt, Attribute Filtration Trinity đã implement
Contextual Hierarchy (H3 Depth)
7
10
6 rules đúng, nhưng scorer chưa phát hiện H3 template quality
Contextual Structure (Per-H2 Instructions)
8
10
8 thành phần Koray đủ, nhưng word count per-H2 vẫn thiếu
Contextual Connection (Internal Link)
7
10
Fix Jaccard threshold OK, anchor reviewer có, nhưng Topical Map nhỏ
FS/PAA Block (Featured Snippet)
9
10
FS ≤40 từ enforce, PAA mapping có anti-contamination
EAV Coverage
9
10
LLM EAV với đơn vị đo, VS intent 3-column, [CẦN XÁC MINH]
Source Context / B2B Alignment
10
10
Project.brand_name, GEO, hotline, NAP inject vào SUPP bridge
GEO / AI Overview Optimization
3
10
THIẾU HOÀN TOÀN: Không có JSON-LD, FAQ Schema, structured data
Score Calibration (Koray Analyzer)
7
10
7 fix đã áp dụng, nhưng H3 quality vs. template chưa detect
Topical Coverage / Map Visualization
4
10
topics.csv có nhưng chỉ 12 từ khoá, không hiện trong Brief output

Điểm tổng: 72/100 → sau khi bổ sung 3 khoảng trống: ~88/100

II. XÁC NHẬN 7 BUG FIX (POST-V9)
Tất cả 7 bug đã được fix xác nhận qua đọc trực tiếp source code:

Thành phần
Trạng thái
Nhận xét / Lỗi cụ thể
Bug #1: EAV inject 'là gì' vào topic
✅
Dòng 815: topic_entity = topic.replace('là gì','').strip() — câu hỏi H3 không còn thừa 'là gì'
Bug #2: best_score==0 → random pick
✅
Dòng 1057-1058: if best_score > 0 → dùng best match, else → boolean fallback. Không còn chọn ngẫu nhiên
Bug #3: Boolean tautology main_keyword
✅
Dòng 1079: entity = main_keyword.replace('là gì','').strip().title() — 'Thép Thanh Vằn có...' thay vì 'Thép Thanh Vằn Là Gì có...'
Bug #4: Jaccard false positive loại bài liên quan
✅
Dòng 434: threshold=0.92 — 'thép tròn trơn là gì' (sim=0.75) không còn bị loại như self-reference
Bug #5: 'vì sao cần X?' anchor không tự nhiên
✅
Dòng 113: question = 'X có ưu điểm gì?' — tự nhiên hơn, tránh câu hỏi sai ngữ pháp
Bug #6: len<30 bỏ lọt H2 generic dài
✅
Dòng 165: len(h) < 50 — phát hiện được 'Ứng dụng thực tiễn trong đời sống' (len=46)
Bug #7: s8 không đo anchor quality
✅
Dòng 273-274: anchor_quality check + s8=10 nếu đủ 2 từ, -5 penalty nếu anchor đơn từ

Kết quả thực tế sau fix: Jaccard simulation cho 'Thép thanh vằn là gì' vs topics.csv → Top 5 bây giờ bao gồm 'thép tròn trơn là gì', 'thép tấm là gì' — các bài liên quan trực tiếp không còn bị loại nhầm.

III. ĐÁNH GIÁ PIPELINE THEO 5 TẦNG KORAY
Koray Framework định nghĩa Full Content Brief = Contextual Vector + Hierarchy + Structure + Connection + Coverage. Dưới đây là đánh giá từng tầng dựa trên source code thực tế.

TẦNG 1: CONTEXTUAL VECTOR (H2 Headings)
Những gì đã làm được ✅
Agent 3a (review_structure) enforce Pattern: [Entity]+[Attribute]+[Context] và Attribute Filtration Trinity (Prominence → Popularity → Relevance)
Bài VS intent: prompt cấm 'Đặc điểm của A và B', yêu cầu '[Attribute]: [Entity A] vs [Entity B]'
MAIN/SUPP split logic: test 'H2 này trả lời câu hỏi gốc hay chỉ quảng bá?' — đúng với Koray Lecture 14
H2 minimum enforcement: VS=5, Informational=4, với Structural Cap scoring nếu thiếu
NAVIGATION_HEADING_BLACKLIST loại bỏ 'liên hệ', 'hotline', 'danh mục'... khỏi outline

Khoảng trống cần fix ⚠️
Generic pattern list trong scorer chỉ check 5 từ: ['tổng quan','kết luận','giới thiệu','đặc điểm','ứng dụng']. Thiếu: 'phân tích', 'so sánh' standalone, 'lưu ý quan trọng'
Attribute Filtration output (Cột N: generate_attribute_filtration) được gọi nhưng KHÔNG được render trong markdown_exporter — writer không thấy lý do thứ tự H2

TẦNG 2: CONTEXTUAL HIERARCHY (H3 Depth)
Những gì đã làm được ✅
Agent 3b (review_h3_depth): 5 data sources theo đúng ưu tiên — PAA (cao nhất) → Keyword Clusters → Semantic Voids → EAV Attributes → Boolean Questions
6 RULES H3 enforce: ≥50% H2 có H3, mỗi H3 = [Entity/Attribute cụ thể], H3 ≤3 per H2, Boolean H3 đặt cuối
_enforce_h3_ratio: fail-safe backup, bug #1-3 đã fix — EAV parse đúng, boolean không còn tautology
H3 source matching: word overlap để pick PAA/EAV phù hợp nhất với H2 cha; fallback khi overlap=0

Khoảng trống cần fix ⚠️
QUAN TRỌNG NHẤT: Koray Quality Scorer (tiêu chí 2) chỉ đếm H3 COUNT, không detect H3 TEMPLATE. Nếu Agent 3b fallback sinh ra 'Tiêu chuẩn kỹ thuật nào áp dụng cho [H2]??' → scorer vẫn cho 7/10 vì count đạt 50%
Cần thêm penalty: -8 điểm nếu >30% H3 có dấu '??' cuối hoặc chứa pattern '[H2]' trong text
PAA mapping vào H3 đúng H2 cha: code hiện gộp toàn bộ PAA vào 1 pool chung, best match bằng word overlap — chấp nhận được nhưng không tối ưu bằng semantic matching

TẦNG 3: CONTEXTUAL STRUCTURE (Per-H2 Instructions)
Đây là tầng mạnh nhất của tool. Hai lớp hướng dẫn được sinh song song:

Lớp 1: Micro-Briefing A-B-C-D-E ✅
A — Snippet Block: Preceding Question (K2Q format) + FS ≤40 từ + Exact Definitive Answer, cấm 'có thể/thường'
B — Deep Analysis: Contextual Structure cụ thể — số cột bảng, tên cột, đơn vị, không generic
C — Information Gain: EAV Coverage, H3 listing bắt buộc format 'Các H3 bao gồm: [...]'
D — Contextual Bridge: Source Context injection — brand tự nhiên trong SAPO, NAP đầy đủ trong SUPP
E — Transition: Semantic Bridge không rập khuôn

Lớp 2: Per-H2 Contextual Instructions (Agent 4) ✅
8 thành phần theo Koray Lecture 21/39: Content Format, First Sentence Pattern, Micro Context Terms (≤5), Sentence Before List, Preceding Question, Contextual Bridge, Boolean H3, Tonality
Macro Rules: central entity ≥1 lần per section, predicate cluster nhất quán, tonality B2B

Khoảng trống còn lại ⚠️
Word Count Guidance: Per-H2 instructions KHÔNG có hướng dẫn số từ cần viết cho từng section. Koray Lecture 57 yêu cầu brief phải chỉ định '150-200 từ cho H2 này'. Hiện tại writer không biết mỗi section cần dài bao nhiêu.
Predicate Cluster per section: Macro Rules sinh 'predicate_cluster' tổng thể cả bài, nhưng không chỉ định predicates cụ thể cho từng H2 (ví dụ: H2 'Độ bền' dùng predicates 'đạt/chịu/chống', H2 'Ứng dụng' dùng 'sử dụng/áp dụng/phù hợp')

TẦNG 4: CONTEXTUAL CONNECTION (Internal Link)
Những gì đã làm được ✅
3 tầng ưu tiên: CSV Topical Map → Semantic Clusters → Dynamic H2
Anti-self-reference đã fix threshold=0.92 — không còn loại bài liên quan
Agent 3d (review_anchor_quality): 6 rules Koray, pre-check duplicate words, adjective-only fix
Rule: TUYỆT ĐỐI không link ở khu vực [MAIN] — đúng với Koray Lecture 14 về internal link placement
Inbound suggestions: gợi ý bài nào nên trỏ về bài hiện tại với anchor cụ thể

Vấn đề còn lại ⚠️
topics.csv chỉ có 12 từ khoá: Đây là vấn đề dữ liệu không phải code. Jaccard với 12 topics cho kết quả kém hơn nhiều so với topical map đầy đủ 50-100 bài.
Koray Lecture 53 (Hash Anchor): 'Anchor Text = Related Article + #Hash Identifier' — code hiện tại không sinh #hash link đến đúng H2/H3 của trang đích. Đây là advanced feature chưa có.
Jaccard vs Semantic: Word overlap chỉ đo surface similarity. 'thép tấm' và 'thép cuộn' share 1 word nhưng có relationship rõ. TF-IDF hoặc embedding sẽ tốt hơn nhưng overkill cho v hiện tại.

TẦNG 5: CONTEXTUAL COVERAGE (Topical Authority)
Những gì đã làm được ✅
Query Network: Google Autocomplete → 40+ từ khoá → LLM clustering theo intent → keyword cannibalization prevention
Context Builder: context_vectors và contextual_structure từ competitor data
Database_v2.csv tracking: mỗi từ khoá có trạng thái ✅ Done/❌ Error — visibility coverage

Khoảng trống lớn nhất ❌
Topical Map không hiển thị trong Brief: topics.csv tồn tại nhưng KHÔNG được render trong markdown output. Writer không thấy bài hiện tại nằm đâu trong topical map, không biết bài nào đã có, bài nào chưa cover. Koray Lecture 4 yêu cầu mỗi brief phải có context về coverage position.
Sequential Query Path thiếu: Koray nhấn mạnh 'search query là 1 bước trong 100m race'. Brief không chỉ ra query nào đến TRƯỚC và SAU query hiện tại — thiếu sequential context cho writer.

IV. 3 KHOẢNG TRỐNG CHIẾN LƯỢC LỚN NHẤT
Đây là 3 thành phần HOÀN TOÀN THIẾU hoặc thiếu nghiêm trọng so với chuẩn Full Content Brief:

KHOẢNG TRỐNG 1: GEO / AI Overview Optimization (0%)
Tại sao quan trọng: Theo file GEO.docx trong knowledge base, AI Overview của Google hiện xuất hiện trong 40%+ kết quả tìm kiếm (tháng 3/2025). Nếu content không được cấu trúc để AI có thể đọc và trích dẫn, traffic từ AI Search sẽ = 0.

Hiện tại tool có gì: Không có bất kỳ GEO optimization nào trong pipeline hoặc output.

Cần bổ sung: 
JSON-LD Schema: Organization, Product, FAQPage — tự động generate từ Source Context + FAQ section của brief
FAQ Section generator: ≥5 Q&A cụ thể từ PAA questions với answer ≤50 từ (format được AI citation)
Structured Data Checklist trong output: đánh dấu section nào là FS candidate, section nào là PAA answer
Opening sentence optimizer: 30-50 từ đầu bài phải trả lời main query trực tiếp — AI Overview ưu tiên

Code cần thêm: 1 module mới: modules/geo_schema_generator.py — input là brief object, output là JSON-LD blocks + GEO checklist section trong markdown output.


KHOẢNG TRỐNG 2: Word Count & Content Depth Guidance (thiếu per-H2)
Tại sao quan trọng: Koray Lecture 57 yêu cầu brief phải chỉ định số từ cụ thể cho từng H2 section. Writer không có guidance này sẽ viết quá ngắn hoặc quá dài, phá vỡ contextual balance.

Hiện tại: SAPO có word count target (80-120 từ). Các H2 khác không có. Scorer check SAPO word count nhưng không check individual H2 depth.

Cần bổ sung: 
Per-H2 word count target trong generate_per_h2_instructions: ['MAIN Definition H2': 200-300 từ, 'MAIN Technical H2': 300-400 từ với bảng, 'SUPP H2': 100-150 từ]
Total target word count cho bài: tính từ intent và H2 count (Informational 1500-2500 từ, VS 2000-3500 từ)
Scorer tiêu chí mới: 'Word Count Balance' — phát hiện khi có H2 không có micro_briefing guidance


KHOẢNG TRỐNG 3: Topical Map Position & Sequential Context (thiếu hoàn toàn)
Tại sao quan trọng: Koray: 'Topical Authority = Topical Map + Semantically Organised Content Network'. Writer cần biết bài đang viết nằm ở đâu trong map để đặt đúng context, link đúng, không overlap với bài khác.

Hiện tại: topics.csv có 12 từ khoá nhưng không được hiển thị trong brief output. Writer không thấy map.

Cần bổ sung: 
Section 'Topical Map Position' trong brief output: hiện thị bài hiện tại + 3 bài upstream (query đến trước) + 3 bài downstream (query đến sau)
Cảnh báo overlap: nếu 2 bài trong topics.csv có Jaccard > 0.6 → flag để tránh keyword cannibalization
topics.csv mở rộng: cần ít nhất 50-80 từ khoá thay vì 12 để Internal Link có meaningful context

V. RESIDUAL BUGS CÒN LẠI SAU 7 FIX
Sau khi xác nhận 7 bug đã fix, code audit phát hiện thêm 4 vấn đề nhỏ hơn:

Ưu tiên
File / Hàm
Vấn đề
Fix cụ thể
🟡 P1
koray_analyzer.py dòng 163
H3 template không bị penalize — scorer chỉ đếm count, không check quality
Thêm: if any('??' in h.get('text','') for h in headings if h['level']=='H3'): strict_penalties += 8
🟡 P1
content_brief_builder.py dòng 1062
H3 ≤3 từ → thêm '— điều gì cần lưu ý?' — tạo ra heading generic tương tự template cũ
Thay condition: chỉ thêm suffix nếu h3_text KHÔNG phải câu hỏi (không chứa '?') VÀ không phải entity phrase
🟡 P1
markdown_exporter.py dòng 437
contextual_structure_v4 (per-H2 8 thành phần) được generate nhưng KHÔNG render trong output
Thêm section render brief.get('contextual_structure_v4') vào PHẦN 1 của markdown, sau Micro-Briefing
🟢 P2
internal_linking.py dòng 60-70
Anchor SUPP rule 6: nên dùng question format cho SUPP anchor. Code không distinguish MAIN vs SUPP khi pick anchor variant
Trong _pick_anchor: nếu source_h2 chứa '[SUPP]' → trả về variants['question'] thay vì variants['primary']

VI. CHECKLIST: FULL CONTENT BRIEF THEO KORAY — TRẠNG THÁI HIỆN TẠI
Đây là danh sách đầy đủ các thành phần Koray yêu cầu trong một Full Content Brief và trạng thái của tool:

Thành phần
Trạng thái
Nhận xét / Lỗi cụ thể
Meta: Title Tag (<60 ký tự, entity+modifier)
✅
_generate_title_tag() trong content_brief_builder.py — có entity + intent modifier
Meta: Meta Description (120-160 ký tự)
✅
_generate_meta_description() — có entity, call-to-action, B2B tone
Meta: Central Entity xác định rõ
✅
Koray Column L: generate_macro_context() LLM — Central Entity, Intent Type, Target User
EAV Table (Entity-Attribute-Value) đầy đủ
✅
Koray Column M: generate_eav_table() — ≥6 rows, đơn vị đo, [CẦN XÁC MINH], VS 3-column
Attribute Filtration order (Prominence > Popularity > Relevance)
⚠️
Agent 3a có logic đúng, nhưng output Cột N không được render trong brief — writer không thấy
FS/PAA Map — mỗi PAA gán vào đúng H2
✅
Koray Column O: generate_fs_paa_map() với anti-contamination rule cho VS intent
SAPO 80-120 từ, định nghĩa entity, khai báo Source Context, liệt kê H2
✅
Micro-Briefing writer: 3 yếu tố SAPO enforce, word count check trong scorer
Contextual Vector: H2 = Entity+Attribute+Context, không generic
✅
Agent 3a + NAVIGATION_BLACKLIST + Scorer tiêu chí 1 (len<50 threshold)
Contextual Hierarchy: ≥50% H2 có H3 data-driven
⚠️
Agent 3b 6 rules + _enforce_h3_ratio. Thiếu: template quality detection trong scorer
Per-H2 Contextual Structure: 8 thành phần Koray
⚠️
Agent 4 generate đủ 8 thành phần nhưng KHÔNG render trong markdown output — writer không thấy
Micro-Briefing A-B-C-D-E mỗi H2
✅
Agent 3 (Micro-Briefing Writer): Snippet ≤40 từ, Deep Analysis, Info Gain, Bridge, Transition
Word Count target per-H2
◻
THIẾU HOÀN TOÀN — chỉ có SAPO word count. Các H2 khác không có guidance
Internal Link: ROOT→NODE với anchor entity+attribute
✅
3 tầng ưu tiên, threshold fix, Agent 3d review anchor, 6 rules Koray
Internal Link: MAIN không có link, SUPP có link
✅
Hardcoded rule: skip [MAIN] headings, chỉ link trong [SUPP]. SUPP anchor nên question format (P2)
Source Context: Brand, GEO, Hotline, NAP trong SUPP
✅
inject_source_context() + SUPP bridge enforcement trong Micro-Briefing writer
GEO Optimization: JSON-LD Schema (Organization, Product, FAQPage)
◻
THIẾU HOÀN TOÀN — không có module nào sinh structured data
GEO: FAQ Section ≥5 câu hỏi từ PAA, answer ≤50 từ
◻
PAA có trong brief nhưng không có dedicated FAQ section generator
GEO: Opening sentence 30-50 từ answer direct query
◻
SAPO có nhưng không có standalone opening optimizer cho AI Overview
Topical Map Position trong brief output
◻
topics.csv có nhưng không được render — writer không thấy coverage context
Sequential Query Path (query trước/sau)
◻
THIẾU — Koray Lecture 4 yêu cầu brief phải có correlative/sequential query context
Koray Quality Score với strict penalties
✅
10 tiêu chí, Structural Cap, Prominence Penalty, 3 strict penalties cộng dồn
E-E-A-T: Experience/Expertise signals trong brief
⚠️
eeat_checklist có trong brief dict nhưng chỉ render 4 items đầu — cần expand và verify

VII. ROADMAP V10 — ƯU TIÊN THEO IMPACT

Ưu tiên
File / Hàm
Vấn đề
Fix cụ thể
🔴 P0
modules/geo_schema_generator.py (MỚI)
Không có GEO/JSON-LD — AI Overview blind spot
Tạo module mới: sinh FAQPage schema từ PAA + Product schema từ EAV + Organization từ Source Context. Render trong Section 5 của markdown output
🔴 P0
markdown_exporter.py ~dòng 245
Per-H2 contextual_structure_v4 không được render
Thêm section render brief.get('contextual_structure_v4', {}).get('per_h2') vào PHẦN 1, sau mỗi H2 trong Semantic Outline
🟡 P1
agent_reviewer.py generate_per_h2_instructions()
Thiếu word_count_target và per-section predicates
Thêm field 'word_count_target': '200-300 từ' và 'section_predicates': ['đạt','chịu'] vào 8 thành phần per-H2
🟡 P1
koray_analyzer.py calculate_quality_score()
H3 template không bị phát hiện — score inflation
Thêm h3_template_count detection: đếm H3 chứa '??' hoặc '[' → strict_penalty += 8 nếu >30% H3 là template
🟡 P1
markdown_exporter.py PHẦN 1
Topical Map position không hiển thị trong brief
Thêm section 'Vị trí trong Topical Map' từ topics.csv: bài trước, bài hiện tại, bài sau + coverage status
🟢 P2
topics.csv (DATA)
Chỉ 12 từ khoá — internal linking và map visualization kém
Mở rộng lên 50-80 từ khoá cho toàn bộ thép → pipes → purlins product family của Trần Long
🟢 P2
internal_linking.py _pick_anchor()
SUPP anchor nên question format theo Rule 6 Koray
if '[SUPP]' in source_h2: return variants['question'] else return variants['primary']
🟢 P2
content_brief_builder.py dòng 1062
'H3 ≤3 từ → thêm điều gì cần lưu ý?' tạo heading generic
Chỉ thêm suffix nếu h3_text không chứa '?' VÀ không phải entity noun phrase (check bằng len(words)>=2)

Dự báo điểm sau V10: Nếu fix P0+P1 → Grade A (~88-92/100). Toàn bộ P0+P1+P2 → Grade A+ (~93-96/100).

VIII. ĐIỂM MẠNH TỔNG HỢP — PHÂN BIỆT VỚI TOOL GENERIC
Đây là những gì tool này làm tốt hơn các content brief tool thông thường trên thị trường:

Pipeline 7 bước có SERP crawl thực tế — không hallucinate competitor data. PAA, Rare Headings, N-grams đều từ Google search results thực
EAV Table với LLM reasoning — không phải template cứng. Đơn vị đo vật lý đúng context (kg/m vs kg/cuộn), [CẦN XÁC MINH] marker cho giá biến động
4 Agent Review passes — Structure, H3, N-gram, Anchor — mỗi pass có LLM call riêng với specific prompt, không phải 1 monolithic prompt
Source Context B2B injection — brand Thép Trần Long, GEO Hà Nội, hotline được inject tự nhiên vào SAPO và SUPP bridge, không phải append cứng cuối bài
Strict Scoring với Structural Cap — không thể đạt Grade A nếu thiếu H3, thiếu internal link, hay FS quá dài. Tránh 'score inflation' sai lệch
VS Intent specialization — bài so sánh có EAV 3-column, H2 pattern '[Attribute]: A vs B', PAA anti-contamination giữa 2 entities


Báo cáo được tạo bởi Code Audit + Project Knowledge (Koray Framework, GEO, Semantic SEO Checklist)
Thép Trần Long — ThepTranLong.vn — Hotline: 0936 179 626