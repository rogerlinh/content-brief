
CHẨN ĐOÁN LỖI & FIX ĐẦY ĐỦ
Content Brief Tool — Output Quality Issues
4 bug gốc rễ được xác minh từ source code + output thực tế
Thep Tran Long — ThepTranLong.vn | Tháng 3/2026


I. TỔNG QUAN — 4 VẤN ĐỀ ĐƯỢC XÁC NHẬN
Đã đọc toàn bộ source code và output thực tế của từ khoá 'Thép thanh vằn là gì'. Dưới đây là 4 bug có địa chỉ file + dòng code cụ thể, không phải suy đoán:

#
Vấn đề
File / Dòng
Ảnh hưởng
1
H3 vô nghĩa tautology
content_brief_builder.py ~1093
H3 = 'Thép Thanh Vằn có thép thanh vằn không?' — entity = h2_core khi H2 trùng topic
2
H2 outline = Semantic Voids chưa lọc
content_brief_builder.py ~604 + Agent 1 Prominence Gate
Outline lệch hoàn toàn: 'Bảng kiểm tra chất lượng', 'Cảnh báo an toàn' thay vì thông số, phân loại
3
Micro-briefing mất nhãn gốc
markdown_exporter.py ~201-226
Các phần 'Trả lời trực diện', 'Điểm khác biệt & góc nhìn vượt trội', 'Liên hệ source context' bị đổi thành generic labels
4
SAPO liệt kê toàn bộ tên H2
content_brief_builder.py ~1798
SAPO biến thành mục lục cơ học, lặp từ khoá 6 lần liên tiếp

II. CHI TIẾT 4 BUG + CODE FIX
Bug 1 — H3 Tautology: 'Thép Thanh Vằn có thép thanh vằn không?'

Nguyên nhân gốc rễ: Khi H2 trùng với topic chính (VD: H2 = 'Thép Thanh Vằn Là Gì?'), logic fallback H3 tạo ra tautology hoàn toàn.

Trace code: content_brief_builder.py dòng 1086–1093
h2_text_clean = 'Thép Thanh Vằn Là Gì'
Strip 'là gì' → h2_core = 'Thép Thanh Vằn'
entity = main_keyword.replace('là gì','').strip().title() = 'Thép Thanh Vằn'
Kết quả: '{entity} có {h2_core} không?' = 'Thép Thanh Vằn có Thép Thanh Vằn không?' — tautology hoàn toàn

Code hiện tại vs Fix đề xuất:
❌ OUTPUT HIỆN TẠI (BỊ LỖI)
✅ OUTPUT SAU KHI FIX
# Dòng 1093 — HIỆN TẠI (BỊ LỖI)
entity = main_keyword.replace('là gì','').replace('tổng quan','').strip().title()
h3_text = f'{entity} có {h2_core} không?'
# → 'Thép Thanh Vằn có Thép Thanh Vằn không?' ← SAI
# FIX: kiểm tra h2_core != entity trước khi dùng template
entity = main_keyword.replace('là gì','').replace('tổng quan','').strip().title()
# Chỉ dùng template Boolean nếu h2_core KHÁC entity
if h2_core.lower().strip() != entity.lower().strip():
    h3_text = f'{entity} có {h2_core} không?'
else:
    # H2 trùng topic → dùng attribute question thay vì Boolean
    h3_text = f'{entity} được sản xuất như thế nào?'

Kết quả sau fix cho bài 'Thép thanh vằn là gì': H2 'Thép Thanh Vằn Là Gì?' → H3 đề xuất: 'Thép thanh vằn được sản xuất như thế nào?' thay vì tautology

Bug 2 — H2 Outline lệch: Semantic Voids chưa qua Prominence Gate

Nguyên nhân gốc rễ: Agent 1 nhận danh sách Content Gaps (Semantic Voids) trực tiếp không qua bộ lọc Attribute Prominence. LLM inject nguyên xi 'Bảng kiểm tra chất lượng', 'Quy trình kiểm định', 'Cảnh báo an toàn' vào H2 — đây là topics đặc thù cho safety manual, không phải bài 'là gì' định nghĩa.

Trace: content_brief_builder.py dòng 604, 683-684 (Agent 1 user prompt)
gaps = info_gain.get('rare_headings', [])[:7] — lấy thẳng không lọc
user_content += f'Content Gaps (CHỈ ĐƯA VÀO NẾU QUA PROMINENCE GATE)...' — chỉ là instruction text, không có code enforce
Hậu quả: Agent 1 LLM nghe lệnh 'CHỈ ĐƯA VÀO NẾU...' nhưng không có hard filter → inject toàn bộ vào outline

H2 outline kỳ vọng cho 'Thép thanh vằn là gì' (Informational Intent): 
Thép thanh vằn là gì? (Định nghĩa)
Phân loại thép thanh vằn theo tiêu chuẩn TCVN / JIS / ASTM
Thông số kỹ thuật: đường kính, trọng lượng, chiều dài thanh
Ứng dụng trong xây dựng — cột, dầm, sàn, móng
So sánh thép vằn với thép tròn trơn
[SUPP] FAQ | [SUPP] Khi nào không nên dùng thép vằn?

H2 outline thực tế (sai): 'Bảng Kiểm Tra Chất Lượng', 'Quy Trình Kiểm Định', 'Cảnh Báo An Toàn', 'Hướng Dẫn Bảo Trì' — đây là nội dung cho Safety Manual / Technical Procedure, không phải bài định nghĩa.

Cách fix — Code Enforcement cho Prominence Gate:
❌ OUTPUT HIỆN TẠI (BỊ LỖI)
✅ OUTPUT SAU KHI FIX
# Dòng 604 — HIỆN TẠI: lấy thẳng không lọc
gaps = info_gain.get('rare_headings', [])[:7]
# Rồi truyền nguyên xi vào Agent 1 prompt
# FIX: lọc gaps theo Attribute Prominence trước khi truyền vào LLM
raw_gaps = info_gain.get('rare_headings', [])[:10]
ANTI_PROMINENCE_PATTERNS = [
    'kiểm định', 'kiểm tra chất lượng', 'quy trình sản xuất',
    'cảnh báo an toàn', 'hướng dẫn bảo trì', 'bảo dưỡng định kỳ'
]
if 'là gì' in topic.lower() or intent == 'informational':
    gaps = [g for g in raw_gaps
            if not any(p in str(g).lower() for p in ANTI_PROMINENCE_PATTERNS)]
gaps = gaps[:7]

Bug 3 — Mất nhãn chi tiết trong Hướng Dẫn Viết (Phần 3)

Vấn đề bạn mô tả: 'các phần Trả lời trực diện - Nội dung phân tích - Điểm khác biệt & góc nhìn vượt trội - Liên hệ source context nếu có - câu nối chuyển ý đâu?'

Chẩn đoán: Không có bug code. Đây là vấn đề UX/labeling. Các trường đang được render đúng nhưng dùng tên chung chung.

Trường trong JSON
Label render hiện tại
Label bạn muốn
snippet
**Snippet:**
**A. Trả lời trực diện (FS ≤40 từ):**
analysis
**Phân tích:**
**B. Nội dung phân tích chi tiết:**
info_gain
**Information Gain:**
**C. Điểm khác biệt & góc nhìn vượt trội:**
bridge
**Bridge:**
**D. Liên hệ Source Context (Thép Trần Long):**
transition
*→ Chuyển ý: ...*
**E. Câu nối chuyển ý tự nhiên:**

Fix trong markdown_exporter.py dòng 200–226: 
# HIỆN TẠI — generic labels
if micro.get('snippet'):
    label = '**Nội dung SAPO (80-120 từ):**' if is_sapo else '**Snippet:**'
    lines.append(f'{label} {micro["snippet"]}')
if micro.get('analysis'):
    lines.append(f'**Phân tích:** {micro["analysis"]}')
if micro.get('info_gain'):
    lines.append(f'**Information Gain:** {info_clean}')
if micro.get('bridge'):
    lines.append(f'**Bridge:** {micro["bridge"]}')

# FIX — labels rõ ràng theo A-B-C-D-E Framework
if micro.get('snippet'):
    if is_sapo:
        label = '**SAPO (80–120 từ) — Câu mở đầu định nghĩa + Brand + Liệt kê H2:**'
    else:
        label = '**A. Trả lời trực diện (Featured Snippet ≤40 từ):**'
    lines.append(f'{label} {micro["snippet"]}')
if micro.get('analysis'):
    lines.append(f'**B. Nội dung phân tích chi tiết:** {micro["analysis"]}')
if micro.get('info_gain') and info_clean:
    lines.append(f'**C. Điểm khác biệt & góc nhìn vượt trội:** {info_clean}')
if micro.get('bridge'):
    lines.append(f'**D. Liên hệ Source Context (Thép Trần Long):** {micro["bridge"]}')
if micro.get('transition'):
    lines.append(f'**E. Câu nối chuyển ý:** *{micro["transition"]}*')



Bug 4 — SAPO liệt kê toàn bộ tên H2 (lặp từ khoá 6 lần)

Vấn đề: SAPO hiện tại: '...Bài viết phân tích lần lượt: Thép Thanh Vằn Là Gì?, Bảng Kiểm Tra Chất Lượng Thép Thanh Vằn, Quy Trình Kiểm Định Thép Thanh Vằn...' — đây là mục lục cơ học, không phải sapo hấp dẫn.

Nguyên nhân: Instruction SAPO dòng 1798 yêu cầu: '3. Liệt kê rõ ràng thứ tự các H2 sẽ được đề cập trong bài viết.' → LLM copy nguyên tên H2 vào SAPO, gây lặp từ khoá và mất chất lượng.

SAPO trước và sau khi fix instruction:
❌ OUTPUT HIỆN TẠI (BỊ LỖI)
✅ OUTPUT SAU KHI FIX
// OUTPUT HIỆN TẠI — mục lục thay vì intro:
'...Bài viết phân tích lần lượt:
 Thép Thanh Vằn Là Gì?,
 Bảng Kiểm Tra Chất Lượng Thép Thanh Vằn,
 Quy Trình Kiểm Định Thép Thanh Vằn,
 Cảnh Báo An Toàn Khi Sử Dụng Thép Thanh Vằn...'
// → keyword lặp 6 lần, không có giá trị đọc
// OUTPUT ĐÚNG — preview lợi ích thay vì tên H2:
'...Bài viết này cung cấp:
 định nghĩa và tiêu chuẩn kỹ thuật,
 bảng thông số theo đường kính,
 ứng dụng trong cột-dầm-sàn-móng,
 cùng hướng dẫn chọn đúng loại thép vằn
 cho từng cấu kiện công trình.'
// → mô tả lợi ích, không lặp tên H2 nguyên văn

Fix instruction trong content_brief_builder.py dòng ~1793-1800: 
# HIỆN TẠI (gây mục lục cơ học):
"3. Liệt kê rõ ràng thứ tự các H2 sẽ được đề cập trong bài viết.\n\n"

# FIX (preview lợi ích thay vì tên H2 nguyên văn):
"3. Liệt kê 3-4 LỢI ÍCH độc giả sẽ nhận được sau khi đọc bài."
"   KHÔNG copy nguyên tên H2. Diễn đạt bằng kết quả/giá trị."
"   VD: 'Sau bài này bạn nắm được: tiêu chuẩn kỹ thuật,"
"   cách chọn đúng đường kính, và bảng trọng lượng tra cứu nhanh.'\n\n"


III. TẠI SAO OUTLINE KHÔNG GIỐNG 'FULL CONTENT BRIEF' TRƯỚC ĐÂY?

Đây là câu hỏi quan trọng nhất. Outline đang hiển thị đúng về mặt kỹ thuật nhưng nội dung H2 sai do Bug 2. Cụ thể:


Full Content Brief chuẩn (kỳ vọng)
Output hiện tại (bị lỗi)
H2 #1
Thép thanh vằn là gì? (định nghĩa cốt lõi)
Thép Thanh Vằn Là Gì? ← chỉ cái này đúng
H2 #2
Phân loại thép thanh vằn (TCVN, JIS, ASTM)
Bảng Kiểm Tra Chất Lượng ← sai intent
H2 #3
Thông số kỹ thuật: D10→D32, kg/m, chiều dài
Quy Trình Kiểm Định ← sai intent
H2 #4
Ứng dụng: cột, dầm, sàn, tường, móng
Cảnh Báo An Toàn ← sai intent
H2 #5
So sánh với thép tròn trơn
Hướng Dẫn Bảo Trì ← sai intent
H2 #6
[SUPP] FAQ về thép vằn
So Sánh Độ Bền ← generic
H3
Con của H2 cha, khác entity
4/8 H3 là tautology hoặc generic

Nguyên nhân căn cơ: Bug 2 → Semantic Voids ('Bảng kiểm tra chất lượng', 'Quy trình kiểm định'...) được LLM inject trực tiếp thành H2 MAIN thay vì ở dạng H3 children hoặc bị lọc bỏ do không match Informational intent.


IV. 2 BUG PHỤ THÊM

Bug 5 — Anchor text 3 variants giống nhau (Internal Linking)
Bảng anchor hiện tại: "thép tấm là gì" / "thép tấm là gì" / "thép tấm là gì?"
Simulation cho thấy primary = exact = 'thép tấm là gì', semantic = 'tìm hiểu thép tấm là gì', question = 'thép tấm là gì?'. Khi render thì primary và exact trùng nhau hoàn toàn.

Fix trong markdown_exporter.py: Thay vì render 3 variants {exact}/{semantic}/{question}, render rõ tên từng biến thể:
# HIỆN TẠI — render 3 fields tuần tự không rõ loại:
f'"..." / "..." / "..."'

# FIX — render có nhãn, hiện cả semantic variant:
lines.append(f'| {node} | **{primary}** |')
lines.append(f'  Exact: "{exact}" |')
lines.append(f'  Semantic: "{semantic}" |')
lines.append(f'  Question: "{question}" |')


Bug 6 — Organization Schema URL bị double-encode
Output hiện tại: "url": "https://https://theptranlong.vn//" — double https:// và trailing //

# geo_schema_generator.py — hiện tại (BUG):
"url": f"https://{getattr(project, 'domain', '')}/"
# → nếu domain = 'https://theptranlong.vn'
#   kết quả: 'https://https://theptranlong.vn/'

# FIX: strip schema trước khi format:
domain = getattr(project, 'domain', '')
domain = domain.replace('https://','').replace('http://','').strip('/')
"url": f"https://{domain}/" if domain else ""



V. THỨ TỰ ƯU TIÊN FIX

P
Bug
File/Dòng
Vấn đề
Impact nếu fix
🔴
Bug 2
cb_builder.py ~604
Prominence Gate chỉ là text instruction, không có code filter
Outline trở về đúng intent: Phân loại, Thông số, Ứng dụng
🔴
Bug 1
cb_builder.py ~1093
H3 tautology entity = h2_core
H3 có nghĩa, không bị vô nghĩa
🔴
Bug 3
markdown_exporter.py ~201
Labels A-B-C-D-E bị đổi thành generic
Writer hiểu rõ vai trò từng block
🔴
Bug 4
cb_builder.py ~1798
SAPO instruction gây mục lục cơ học
SAPO preview lợi ích, không lặp từ khoá
🟡
Bug 6
geo_schema_generator.py ~40
URL double-encode
Organization Schema valid
🟢
Bug 5
markdown_exporter.py anchor
3 variants không phân biệt loại
Clarity khi đọc brief

Kết luận: Toàn bộ 4 bug 🔴 nằm trong 2 file: content_brief_builder.py và markdown_exporter.py. Fix 4 bug này trước, output sẽ trở lại đúng chuẩn Full Content Brief với 5 blocks A-B-C-D-E rõ ràng và outline đúng intent.


Thép Trần Long — ThepTranLong.vn — Hotline: 0936 179 626