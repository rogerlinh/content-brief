📋 CODE EVALUATION REPORT
Đánh giá Code sau khi Fix — Content Brief Generator
Thép Trần Long  |  theptranlong.vn
March 2026  |  Source: content_brief.zip (post-fix submission)
Hạng mục
Kết quả
Bugs đã báo cáo (BugDiagnosis_PostV11)
3 critical (BUG-1, BUG-2A, BUG-2B)
Bugs được fix đúng
2/3 — BUG-1 ✅, BUG-2A ✅
Bugs còn tồn đọng
1 mới phát hiện (context_builder key mismatch)
Bugs tồn đọng từ V11 audit
3 vẫn chưa fix (SAPO template, bracket, topics.csv)
Syntax/Import errors
0 — tất cả modules compile sạch
Đánh giá tổng thể
PASS WITH ISSUES — Production-ready sau 3 fix nhỏ

PHẦN 1: BUGS ĐÃ ĐƯỢC FIX — XÁC NHẬN
✅ BUG-1 FIXED: markdown_exporter.py dòng 579
Trạng thái: ĐÃ FIX ĐÚNG — Verified bằng byte-level analysis

Cách developer fix: Tạo script Python (fix_bug1.py) dùng regex để replace pattern trong file. Script chạy local trên máy developer (path Windows) rồi nộp file .py kèm source.

Xác minh kết quả:
Byte tại dòng 579: 0x22 0x5C 0x6E 0x22 = quote + 0x5C (backslash) + 0x6E (n) + quote
0x5C 0x6E trong Python source file = escape sequence \n → runtime cho byte 0x0A (newline thực)
Đây KHÁC với bug cũ: 0x5C 0x5C 0x6E = double-backslash + n = literal 2-char string \n
Kiểm tra runtime: '\n'.join(['a','b']) = 'a\nb' với real newline byte → ĐÚNG


Version cũ (BUG)
Version mới (FIXED)
Bytes trong file
0x5C 0x5C 0x6E (double backslash-n)
0x5C 0x6E (single backslash-n)
Runtime behaviour
join chèn chuỗi \n 2-ký-tự
join chèn byte 0x0A (newline)
File .md output
Tất cả content trên 1 dòng
Đúng format Markdown, xuống dòng đúng
Status
❌ BUG
✅ FIXED

✅ BUG-2A FIXED: query_network_str
Trạng thái: ĐÃ FIX ĐÚNG

Thay đổi trong code:
Thêm helper function _format_network_for_log() tại main_generator.py dòng 35-50
Thêm brief['query_network_str'] = _format_network_for_log(brief.get('query_network')) tại dòng 261
Hàm serialize đúng: lấy clusters[:3], keywords[:3] per cluster, join bằng ', '
Fallback: nếu không có cluster → trả về '{total} keywords fetched'
Guard: check isinstance(network_data, dict) và isinstance(cluster_list, list) → robust

Khi enable_network=True, cột 'Semantic Query Network' trong CSV sẽ hiển thị top keywords thay vì N/A.

⚠️ BUG-2B: context_vectors_str — FIX KHÔNG HOÀN CHỈNH
Hàm _format_context_vectors_for_log() đã được tạo và được gọi đúng tại dòng 262.
TUY NHIÊN: brief.get('context_data', brief.get('context_vectors')) đọc key SAI.
content_brief_builder.py dòng 1652: brief['context_builder'] = context_data  ← key là 'context_builder'
main_generator.py dòng 262: brief.get('context_data', ...)  ← tìm key 'context_data' — KHÔNG TỒN TẠI
Kết quả: khi enable_context=True, cột Context Vectors vẫn hiện N/A (No Context Vectors).

PHẦN 2: BUG MỚI PHÁT HIỆN TRONG LẦN REVIEW NÀY
🟠 BUG-3 (MỚI): context_vectors_str key mismatch
Severity: Medium — ảnh hưởng khi enable_context=True (hiện mặc định False trong app.py)

Vị trí
Code
Vấn đề
content_brief_builder.py:1652
brief['context_builder'] = context_data
Key được SET là 'context_builder'
main_generator.py:262
brief.get('context_data', brief.get('context_vectors'))
Key được ĐỌC là 'context_data' — KHÔNG TỒN TẠI
Kết quả
_format_context_vectors_for_log nhận None
CSV luôn ghi N/A cho cột Context Vectors

Fix (1 dòng):
# TRƯỚC (sai):
brief["context_vectors_str"] = _format_context_vectors_for_log(brief.get("context_data", brief.get("context_vectors")))

# SAU (đúng):
brief["context_vectors_str"] = _format_context_vectors_for_log(brief.get("context_builder"))

PHẦN 3: BUGS TỒN ĐỌNG TỪ V11 AUDIT — CHƯA ĐƯỢC FIX
3 vấn đề dưới đây đã được báo cáo trong BugDiagnosis_ContentBrief_V11.docx và BugDiagnosis_ContentBrief_PostV11.docx nhưng KHÔNG có trong bản fix này.

🟡 SAPO Template JSON: Vẫn hướng dẫn 'Liệt kê H2 theo đúng thứ tự'
File: modules/content_brief_builder.py, dòng 1878

Vấn đề:
Trong JSON output template cho LLM, field 'snippet' của SAPO vẫn có hướng dẫn:
"snippet": "Nội dung Sapo (Định nghĩa, Source Context, Liệt kê H2 theo đúng thứ tự)..."

Mâu thuẫn với instruction ở trên (dòng 1871-1873) đã được fix đúng:
3. Liệt kê 3-4 LỢI ÍCH độc giả sẽ nhận được sau khi đọc bài.
   KHÔNG copy nguyên tên H2. Diễn đạt bằng kết quả/giá trị.

Hậu quả: LLM nhận 2 instruction mâu thuẫn — instruction text (đúng) vs JSON example template (sai). LLM thường ưu tiên example template → SAPO vẫn liệt kê tên H2 nguyên văn, keyword lặp lại.

Fix (1 dòng):
# TRƯỚC:
"snippet": "Nội dung Sapo (Định nghĩa, Source Context, Liệt kê H2 theo đúng thứ tự)...",

# SAU:
"snippet": "Nội dung Sapo (Định nghĩa, Source Context, 3-4 lợi ích giá trị — KHÔNG copy tên H2)...",

🟡 Bracket Pattern: [SS400] hợp lệ bị phạt nhầm
File: modules/koray_analyzer.py, dòng 198

Vấn đề:
Điều kiện phát hiện H3 template chất lượng thấp:
if "??" in t or t.strip().startswith("[") or "[[" in t or t.endswith("??")

Test thực tế:
[SS400] tiêu chuẩn kỹ thuật → template=True  ← SAI (H3 hợp lệ về tiêu chuẩn thép)
[Bảng kiểm định chất lượng] → template=True   ← ĐÚNG (template rác)
Thép SS400 là gì? → template=False             ← ĐÚNG

Hậu quả: H3 kỹ thuật thép hợp lệ chứa ký hiệu tiêu chuẩn trong ngoặc ([SS400], [TCVN], [JIS]) bị tính là template, Koray score bị trừ điểm sai.

Fix:
# TRƯỚC:
if "??" in t or t.strip().startswith("[") or "[[" in t or t.endswith("??")

# SAU (thêm check: chỉ flag nếu bracket KHÔNG phải standard code):
import re
def _is_template_h3(t):
    if '??' in t or t.endswith('??'): return True
    if '[[' in t: return True
    if t.strip().startswith('['):
        # Allow standard codes: [SS400], [TCVN], [JIS], [ASTM], [Q235]
        if re.match(r'^\[[A-Z0-9\-\/]+\]', t.strip()): return False
        return True
    return False

🟡 topics.csv: Chỉ có 12 keywords — Topical Map không đủ
File: topics.csv (root directory)

Vấn đề: topics.csv hiện có 12 dòng (11 keywords + header). Đây là seed file để tool chạy batch. Topical Map coverage quá thấp để build Internal Linking graph có ý nghĩa.
Koray framework yêu cầu ≥40 keywords để Topical Authority Map cover đủ entity clusters. Với 12 keywords, Internal Linking suggestions và Topical Map Position analysis sẽ rất thưa.

Khuyến nghị: Mở rộng lên 40-50 keywords theo cấu trúc:
10 keywords định nghĩa: 'X là gì' — thép tấm, thép hộp, thép ống, thép hình...
10 keywords thông số: 'thép X kích thước/trọng lượng/tiêu chuẩn'
10 keywords so sánh: 'so sánh X và Y', 'X khác Y thế nào'
10 keywords transactional: 'giá thép X', 'mua thép X Hà Nội'
5 keywords brand: 'Thép Trần Long', 'thep tran long', 'theptranlong.vn'
5 keywords dự án: 'thép cầu Vĩnh Tuy', 'thép Vinhomes'

PHẦN 4: TỔNG HỢP & ĐIỂM ĐÁNH GIÁ
#
Vấn đề
Trước Fix
Sau Fix (lần này)
Priority
BUG-1
File .md không render được
❌ BUG
✅ FIXED
—
BUG-2A
N/A query_network trong CSV
❌ BUG
✅ FIXED
—
BUG-2B
N/A context_vectors trong CSV
❌ BUG
⚠️ PARTIAL (key mismatch còn)
🔴 P0
BUG-3 (MỚI)
context_builder vs context_data key mismatch
—
❌ BUG (mới phát hiện)
🔴 P0
SAPO template
LLM vẫn liệt kê tên H2 trong SAPO
❌ BUG
❌ CHƯA FIX
🟠 P1
Bracket pattern
[SS400] bị phạt sai trong Koray score
❌ BUG
❌ CHƯA FIX
🟡 P1
topics.csv
12 keywords — Topical Map thưa
⚠️ Thiếu
⚠️ CHƯA FIX
🟡 P2

Đánh giá chất lượng Fix
Tiêu chí
Điểm
Nhận xét
BUG-1 Fix chất lượng
10/10
Fix script tuy hơi phức tạp nhưng kết quả đúng về byte
BUG-2A Fix chất lượng
9/10
Helper function clean, có guard checks, logic đúng
BUG-2B Fix chất lượng
4/10
Function đúng nhưng key lookup sai — 1 dòng còn lại
Regression risk
Thấp
Tất cả modules compile sạch, không có syntax error
Tổng thể
PASS WITH ISSUES
2.5/3 bugs được fix — cần 1 fix nhỏ nữa là hoàn chỉnh

✅ ACTION ITEMS — Theo thứ tự ưu tiên
🔴 P0 — Fix ngay (5 phút): main_generator.py:262 — đổi brief.get('context_data') → brief.get('context_builder')
🟠 P1 — Fix SAPO template JSON (2 phút): content_brief_builder.py:1878 — đổi 'Liệt kê H2 theo đúng thứ tự' → '3-4 lợi ích giá trị — KHÔNG copy tên H2'
🟡 P1 — Fix bracket pattern (10 phút): koray_analyzer.py:198 — thêm regex check cho standard codes [SS400], [TCVN]...
🟡 P2 — Mở rộng topics.csv từ 12 → 40-50 keywords theo cấu trúc Topical Map

Content Brief Generator — Code Evaluation Report (Post-Fix)  |  Thép Trần Long  |  March 2026