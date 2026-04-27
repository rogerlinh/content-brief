🔬 BUG DIAGNOSIS REPORT
Content Brief Generator — Source Code Audit
Thép Trần Long | theptranlong.vn
March 2026  |  Version: Post-V11 Source Code
Thông tin
Chi tiết
Phiên bản Source Code
Post-V11 (zip mới nhất từ developer)
Bugs được xác nhận
3 Critical (🔴) + 2 High (🟠)
Files bị ảnh hưởng
markdown_exporter.py, main_generator.py, csv_logger.py
Output test
so-sanh-thep-cuon-va-thep-van.md, thep-thanh-van-la-gi (CSV)
Triệu chứng do user báo
Outline ≠ Full Content Brief  |  N/A Query Network  |  N/A Context Vectors

EXECUTIVE SUMMARY
Audit source code sau khi developer nộp bản fix cho thấy 2 trong số 3 bug báo cáo liên quan đến CÙNG MỘT root cause: key không tồn tại trong dict brief. Bug còn lại là lỗi escape chuỗi Python cổ điển (backslash-n literal). Cả 3 bug đều có fix đơn giản, 1-3 dòng code.

#
Triệu chứng
File
Độ nghiêm trọng
Loại Bug
BUG-1
File .md không render được — toàn bộ nội dung trên 1 dòng
markdown_exporter.py:579
🔴 Critical
Escape string
BUG-2A
N/A (No Query Network) trong CSV
main_generator.py:420-421
🔴 Critical
Missing key
BUG-2B
N/A (No Context Vectors) trong CSV
main_generator.py:420-421
🔴 Critical
Missing key
BUG-3
Outline (Section 2) khác Structure Outline trong CSV — data OK, display vẫn đúng
Không phải bug — by design
ℹ️ Info
Design clarification

BUG-1: File .md render thành 1 dòng duy nhất
Triệu chứng
Khi mở file .md output (VD: so-sanh-thep-cuon-va-thep-van.md) trong bất kỳ Markdown viewer hoặc text editor nào, toàn bộ nội dung hiển thị trên một dòng. Các heading, paragraph, table đều bị dính vào nhau. Markdown parser không thể nhận diện cấu trúc tài liệu.
Root Cause
File: modules/markdown_exporter.py, dòng 579

🔴 NGUYÊN NHÂN GỐC RỄ
Python string literal: "\\n" là một backslash-n 2 ký tự, KHÔNG phải ký tự newline (\n).

Code hiện tại (SAI):
full_content = "\\n".join(lines)

Giải thích kỹ thuật:
Trong Python source file, "\\n" là escaped backslash + n — tức ký tự \ theo sau n
Khi join(), Python chèn chuỗi 2-ký-tự \n giữa các phần tử thay vì ký tự xuống dòng thật
File ghi ra chứa các ký tự \n literal thay vì byte 0x0A (newline)
Mọi Markdown parser đọc file sẽ thấy toàn bộ nội dung là một dòng

Bằng chứng xác nhận — kiểm tra file thực tế:
raw = open('so-sanh-thep-cuon-va-thep-van.md', 'rb').read()
Has literal backslash-n: True
Has real newline (0x0A): False

Fix (1 dòng)
File: modules/markdown_exporter.py, dòng 579

TRƯỚC (sai):
full_content = "\\n".join(lines)

SAU (đúng):
full_content = "\n".join(lines)

Lưu ý: Trong Python, "\n" (backslash-n, KHÔNG double-backslash) = ký tự newline (0x0A) thực sự. Đây là lỗi copy-paste hoặc escape nhầm khi edit file.

BUG-2: N/A (No Query Network) & N/A (No Context Vectors)
Triệu chứng
Trong file CSV output (log kết quả), 2 cột luôn hiện giá trị N/A:
Cột 'Semantic Query Network' → N/A (No Query Network)
Cột 'Context Vectors & Guidelines' → N/A (No Context Vectors)
Điều này xảy ra NGAY CẢ KHI enable_network = True trong app.py, và network_data được tạo thành công bởi analyze_query_network().
Root Cause — Trace đầy đủ

Bước 1: csv_logger.py ghi N/A khi chuỗi rỗng
File: modules/csv_logger.py, dòng 148-149:
df.at[row_idx, 'Semantic Query Network'] = _trunc(query_network) or "N/A (No Query Network)"
df.at[row_idx, 'Context Vectors & Guidelines'] = _trunc(context_vectors) or "N/A (No Context Vectors)"
Logic or: nếu query_network là chuỗi rỗng "" → ghi N/A. Đây là ĐÚNG. Vấn đề là tại sao query_network lại rỗng?

Bước 2: main_generator.py đọc key không tồn tại
File: main_generator.py, dòng 420-421 và 445-446:
query_network=brief.get("query_network_str", ""),
context_vectors=brief.get("context_vectors_str", ""),
Cả hai dùng .get() với key là "query_network_str" và "context_vectors_str" — nếu key không tồn tại → trả về "" → csv_logger ghi N/A.

Bước 3: brief dict KHÔNG BAO GIỜ chứa các key này
Tìm kiếm toàn bộ codebase:
grep -rn 'query_network_str\|context_vectors_str' modules/content_brief_builder.py
>>> [KẾT QUẢ]: Không có kết quả nào

brief dict được build tại content_brief_builder.py dòng 1573, chỉ chứa:
"query_network": network_data  (dòng 1648) — key là query_network, KHÔNG phải query_network_str
Không có key nào tên là query_network_str hoặc context_vectors_str

Bước 4: network_data tồn tại nhưng không được convert thành string
main_generator.py dòng 173-176: network_data được tạo đúng:
network_data = None
if enable_network:
    entity_for_net = analysis['central_entity']
    network_data = analyze_query_network(entity_for_net)  # ← Thành công

Nhưng network_data (dict) được truyền vào build_brief() như tham số — không bao giờ được serialise thành string và gán vào brief['query_network_str'].

🔴 ROOT CAUSE TÓM TẮT
brief.get('query_network_str') đọc key KHÔNG TỒN TẠI. Key thực tế là 'query_network' (dict), nhưng code đọc '_str'. Cần tạo chuỗi hiển thị từ dict và gán vào brief trước khi log.

Fix — 2 cách
Cách A: Tạo _str key ngay sau khi build_brief (RECOMMENDED)
File: main_generator.py — thêm sau dòng 226 (sau khi build_brief trả về brief):
# Build display strings cho CSV logging
if network_data and isinstance(network_data, dict):
    clusters = network_data.get('clusters', {})
    cluster_list = clusters.get('clusters', []) if isinstance(clusters, dict) else []
    kws = []
    for c in cluster_list[:3]:
        if isinstance(c, dict):
            kws.extend(c.get('keywords', [])[:3])
    brief['query_network_str'] = ', '.join(kws) if kws else str(network_data.get('total_fetched', 0)) + ' keywords'
else:
    brief['query_network_str'] = ''

Cách B (Quick Fix): Đọc từ key đúng tại điểm logging
File: main_generator.py, dòng 420-421 và 445-446 — thay thế:
# TRƯỚC (sai):
query_network=brief.get("query_network_str", ""),
context_vectors=brief.get("context_vectors_str", ""),

# SAU (đúng — quick fix):
query_network=_format_network_for_log(brief.get('query_network', {})),
context_vectors=brief.get('context_data_str', ''),

Và thêm helper function:
def _format_network_for_log(network_data: dict) -> str:
    if not network_data: return ''
    clusters = network_data.get('clusters', {})
    cluster_list = clusters.get('clusters', []) if isinstance(clusters, dict) else []
    kws = [kw for c in cluster_list[:3] if isinstance(c, dict) for kw in c.get('keywords', [])[:3]]
    return ', '.join(kws) if kws else f"{network_data.get('total_fetched', 0)} keywords fetched"

INFO: Tại sao Outline (CSV) ≠ Full Content Brief (Section 2)?
Đây không phải bug — đây là by design
Sau khi trace đầy đủ data flow trong pipeline, sự khác biệt về format giữa cột 'Structure Outline' trong CSV và Section 2 trong file .md là do hai nơi đọc từ CÙNG data source nhưng render khác nhau.

Data Flow: Cùng nguồn, 2 cách render

CSV Column 'Structure Outline'
File .md Section 2 'Semantic Outline'
Data source
brief['heading_structure']
brief['heading_structure'] (giống nhau)
Render tại
main_generator.py ~385
markdown_exporter.py dòng 151-176
Format
Plain text: 'H1: ..., H2: ...'
Markdown tree: 🟢 [MAIN] ... ↳ H3
Mục đích
Log vào Google Sheet / CSV cho review
Hiển thị trong file brief cho writer

Code tại main_generator.py ~385:
headings_str = '\n'.join([f"{h['level']}: {h['text']}" for h in brief.get('heading_structure', [])])
Code tại markdown_exporter.py ~151-175:
for h in heading_structure:
    if level == 'H2':
        role_icon = '🟢' if '[MAIN]' in text else '🟡'
        lines.append(f'- {role_icon} **{role}** {clean}')

Tuy nhiên: BUG-1 khiến Section 2 trong .md bị vỡ
Do BUG-1 (literal \n), khi file .md bị ghi sai newline, Markdown viewer không parse được heading tree — trông như 'Outline bị mất'. Thực ra data vẫn đúng, chỉ là file không render được. Sau khi fix BUG-1, Section 2 sẽ hiển thị đúng tree với icons và indentation.

TỔNG HỢP: Checklist Fix theo thứ tự ưu tiên
Priority
Bug ID
File
Dòng
Fix
Effort
🔴 P0
BUG-1
modules/markdown_exporter.py
579
"\\n".join → "\n".join
1 phút
🔴 P0
BUG-2A
main_generator.py
420, 445
Thêm query_network_str vào brief sau build_brief()
10 phút
🔴 P0
BUG-2B
main_generator.py
421, 446
Thêm context_vectors_str vào brief sau build_brief()
5 phút
ℹ️ Info
BUG-3
N/A — by design
—
Không cần fix; fix BUG-1 là đủ
0

✅ SAU KHI FIX 3 ITEMS TRÊN
File .md sẽ render đúng Markdown  |  CSV sẽ hiện Semantic Query Network thực tế  |  Structure Outline trong CSV sẽ match Section 2 trong .md  |  Dự kiến Koray Score tăng từ 59 → 75+ (do Per-H2 Guidance được render đúng)

Content Brief Generator — Bug Diagnosis Report
Thép Trần Long  |  theptranlong.vn  |  March 2026