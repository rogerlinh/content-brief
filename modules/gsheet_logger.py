# -*- coding: utf-8 -*-
"""
gsheet_logger.py - Phase 11: Real-time Google Sheets Logging.

Ghi log tiến trình pipeline vào Google Sheet theo thời gian thực.
Mỗi keyword = 1 dòng, cập nhật từng cột khi hoàn thành từng bước.
"""

import logging
import os
import time
from typing import List

logger = logging.getLogger(__name__)

# Cấu trúc cột trên Google Sheet (Sắp xếp theo Logical Semantic Workflow)
SHEET_HEADERS = [
    "Keyword",                      # A: Topic chính
    "Trạng thái",                   # B: Status
    "Search Intent",                # C: Phân loại ý định tìm kiếm
    "Macro Context",                # D: Bối cảnh vĩ mô (Koray)
    "Semantic Query Network",       # E: Mạng lưới LSI/Variants (Cluster)
    "Top 3 Đối thủ",                # F: SERP Competitors
    "Content Gaps",                 # G: Khoảng trống ngữ nghĩa
    "EAV Table",                    # H: Bảng Thực thể & Thuộc tính
    "PAA Questions",                # I: Câu hỏi người dùng
    "FS/PAA Map",                   # J: Bản đồ Featured Snippet
    "Smart N-Grams",                # K: Lexical tokens (Entity/Action)
    "Context Vectors & Guidelines", # L: Luật khung/Ngữ cảnh tuyến tính
    "Structure Outline",            # M: Outline thô
    "Internal Links",               # N: Liên kết nội bộ
    "Source Context Alignment",     # O: Tone/Thương hiệu 
    "Koray Quality Score",          # P: Điểm chất lượng
    "Báo cáo phân tích dữ liệu",    # Q: Report raw
    "Full Content Brief",           # R: Kết quả cuối cùng cho Writer
]

# Default credentials path
DEFAULT_CREDS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "gen-lang-client-0396271616-70425b3ad4fb.json",
)

# Default Sheet URL
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1i_lgFmoB1LJq2Lt01CwDlOk3hVbQxPiZ4LqGqf8mgwM"
)


class GSheetLogger:
    """
    Logger ghi tiến trình pipeline vào Google Sheet.

    Usage:
        glog = GSheetLogger(creds_path="path/to/creds.json")
        glog.connect(sheet_url="https://docs.google.com/spreadsheets/d/...")
        row = glog.start_keyword("Protein cho người ăn chay")
        glog.update_cell(row, "Search Intent", "Informational")
        glog.set_status(row, "Done")
    """

    def __init__(self, creds_path: str = None, sheet_url: str = None):
        self.creds_path = creds_path or DEFAULT_CREDS_PATH
        self.sheet_url = sheet_url or DEFAULT_SHEET_URL
        self.client = None
        self.sheet = None
        self.worksheet = None
        self._connected = False
        self.has_error = False

    def connect(self, sheet_url: str = None) -> bool:
        """
        Kết nối Google Sheet qua Service Account.

        Returns:
            True nếu kết nối thành công.
        """
        if sheet_url:
            self.sheet_url = sheet_url

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            creds = Credentials.from_service_account_file(
                self.creds_path, scopes=scopes
            )
            self.client = gspread.authorize(creds)

            # Mở sheet bằng URL
            self.sheet = self.client.open_by_url(self.sheet_url)
            self.worksheet = self.sheet.sheet1

            # Viết headers nếu chưa có
            self._ensure_headers()

            self._connected = True
            logger.info("[GSHEET] Kết nối thành công: %s", self.sheet.title)
            return True

        except FileNotFoundError:
            logger.error(
                "[GSHEET] Không tìm thấy file credentials: %s", self.creds_path
            )
            return False
        except Exception as e:
            logger.error("[GSHEET] Lỗi kết nối: %s", str(e))
            return False

    def _ensure_headers(self):
        """Viết header vào dòng 1 nếu chưa có."""
        try:
            first_row = self.worksheet.row_values(1)
            # Nếu list rỗng hoặc sai kích thước/tiêu đề -> force write
            if not first_row or len(first_row) < len(SHEET_HEADERS) or first_row[:len(SHEET_HEADERS)] != SHEET_HEADERS:
                self.worksheet.update(
                    range_name="A1:R1",
                    values=[SHEET_HEADERS],
                )
                time.sleep(1.5)
                # Bold headers
                self.worksheet.format("A1:R1", {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                    "horizontalAlignment": "CENTER",
                })
                time.sleep(1.5)
                logger.info("[GSHEET] Đã cập nhật lại headers (A1:R1) vào dòng 1")
        except Exception as e:
            logger.warning("[GSHEET] Không thể viết headers: %s", str(e))

    def start_keyword(self, keyword: str) -> int:
        """
        Bắt đầu xử lý 1 keyword — TÌM dòng cũ hoặc tạo dòng mới.
        MỌI thao tác GSheet đều bọc try/except riêng biệt.
        
        Returns:
            Số dòng (row number), hoặc -1 nếu GSheet lỗi.
        """
        if not self._connected:
            print("⚠️ [GSHEET] Chưa kết nối. Bỏ qua start_keyword.")
            return -1

        target_row = -1

        # ── Bước 1: Tìm keyword trong cột A ──
        print(f"➡️ [GSHEET] Đang tìm keyword '{keyword}' trên Sheet...")
        try:
            all_values = self.worksheet.col_values(1)
            time.sleep(1.5)
            
            for idx, val in enumerate(all_values):
                if str(val).strip().lower() == keyword.strip().lower():
                    target_row = idx + 1  # 1-indexed
                    break
            
            if target_row > 0:
                print(f"✅ [GSHEET] Đã tìm thấy keyword ở dòng {target_row}.")
            else:
                target_row = len(all_values) + 1
                print(f"❌ [GSHEET] Không tìm thấy -> Tạo dòng mới: {target_row}")
                
        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi tìm keyword: {e}")
            logger.error("[GSHEET] Lỗi tìm keyword: %s", str(e))
            return -1

        # ── Bước 2: Ghi keyword + trạng thái ──
        print(f"➡️ [GSHEET] Ghi '{keyword}' vào dòng {target_row}...")
        try:
            self.worksheet.update(
                range_name=f"A{target_row}:B{target_row}",
                values=[[keyword, "🔄 Running"]],
            )
            time.sleep(1.5)
            print("✅ [GSHEET] Đã ghi keyword thành công.")
        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi ghi keyword: {e}")
            logger.error("[GSHEET] Lỗi ghi keyword: %s", str(e))
            return target_row  # Vẫn trả row để các bước sau thử ghi tiếp

        # ── Bước 3: Tô nền vàng ──
        try:
            self.worksheet.format(f"A{target_row}:R{target_row}", {
                "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.8},
            })
            time.sleep(1.5)
        except Exception as e:
            # Format lỗi thì bỏ qua, không quan trọng
            print(f"⚠️ [GSHEET] Lỗi tô màu (bỏ qua): {e}")

        logger.info("[GSHEET] Keyword '%s' ở dòng %d", keyword, target_row)
        return target_row

    def update_cell(self, row: int, column_name: str, value: str):
        """Cập nhật 1 ô cụ thể theo tên cột. Bọc try/except toàn bộ."""
        if not self._connected or row < 1:
            return

        try:
            col_idx = SHEET_HEADERS.index(column_name)
            col_letter = chr(65 + col_idx)  # A=0, B=1, ...
            # Truncate nếu quá dài (Google Sheets limit 50000 chars)
            if len(str(value)) > 45000:
                value = str(value)[:45000] + "\n\n... (truncated)"
            print(f"➡️ [GSHEET] Ghi {col_letter}{row} ({column_name})...")
            self.worksheet.update(
                range_name=f"{col_letter}{row}",
                values=[[value]],
            )
            time.sleep(1.5)
            print(f"✅ [GSHEET] Đã ghi {col_letter}{row}.")
        except ValueError:
            print(f"⚠️ [GSHEET] Cột '{column_name}' không tồn tại (bỏ qua)")
        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi update_cell {column_name}: {e}")

    def set_status(self, row: int, status: str):
        """Cập nhật trạng thái (Cột B) + đổi màu nền."""
        if not self._connected or row < 1:
            return

        try:
            status_map = {
                "Running":  ("🔄 Running",  {"red": 1.0, "green": 0.95, "blue": 0.8}),
                "Done":     ("✅ Done",      {"red": 0.85, "green": 1.0, "blue": 0.85}),
                "Error":    ("❌ Error",     {"red": 1.0, "green": 0.85, "blue": 0.85}),
            }
            label, bg_color = status_map.get(
                status, (status, {"red": 1.0, "green": 1.0, "blue": 1.0})
            )

            self.worksheet.update(range_name=f"B{row}", values=[[label]])
            time.sleep(1.5)
            self.worksheet.format(f"A{row}:R{row}", {
                "backgroundColor": bg_color,
            })
            time.sleep(1.5)
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi set_status: %s", str(e))

    def log_analysis_results(
        self,
        row: int,
        intent: str,
        top_urls: List[str],
        paa: List[str],
        gaps: List[str],
        ngrams: str,
    ):
        """Đưa kết quả phân tích vào cột C-G. Ghi 'N/A' nếu rỗng."""
        self.update_cell(row, "Search Intent", intent if intent else "N/A (Analysis Failed)")
        self.update_cell(row, "Top 3 Đối thủ", "\n".join(top_urls[:5]) if top_urls else "N/A (No URLs)")
        self.update_cell(row, "PAA Questions", "\n".join(paa) if paa else "N/A (No PAA)")
        self.update_cell(row, "Content Gaps", "\n".join(gaps[:10]) if gaps else "N/A (No Gaps)")
        self.update_cell(row, "Smart N-Grams", ngrams if ngrams else "N/A (No N-grams)")

    def log_brief_results(
        self,
        row: int,
        headings_outline: str,
        internal_links: str,
        full_brief_md: str,
        data_analysis_md: str = "",
    ):
        """Đưa kết quả Brief vào cột H-K. Ghi 'N/A' nếu rỗng."""
        self.update_cell(row, "Structure Outline", headings_outline if headings_outline else "N/A (No Outline)")
        self.update_cell(row, "Internal Links", internal_links if internal_links else "N/A (No Links)")
        self.update_cell(row, "Báo cáo phân tích dữ liệu", data_analysis_md if data_analysis_md else "N/A (No Data)")
        self.update_cell(row, "Full Content Brief", full_brief_md if full_brief_md else "N/A (Brief Failed)")

    def log_error(self, row: int, error_msg: str):
        """Ghi lỗi vào cột B và tô đỏ."""
        if not self._connected or row < 1:
            return
        try:
            self.worksheet.update(
                range_name=f"B{row}",
                values=[[f"❌ Error: {error_msg[:200]}"]],
            )
            time.sleep(1.5)
            self.worksheet.format(f"A{row}:R{row}", {
                "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85},
            })
            time.sleep(1.5)
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi log_error: %s", str(e))

    def log_koray_columns(
        self,
        row: int,
        macro_context: str = "",
        eav_table: str = "",
        fs_paa_map: str = "",
        source_context_alignment: str = "",
        quality_score: str = "",
    ):
        """Phase 33: Ghi 5 cột Koray (L-P) vào Google Sheet."""
        self.update_cell(row, "Macro Context", macro_context or "")
        self.update_cell(row, "EAV Table", eav_table or "")
        self.update_cell(row, "FS/PAA Map", fs_paa_map or "")
        self.update_cell(row, "Source Context Alignment", source_context_alignment or "")
        self.update_cell(row, "Koray Quality Score", quality_score or "")
        logger.info("[GSHEET] Đã ghi 5 cột Koray (L-P) vào dòng %d", row)

    def log_semantic_strategy_columns(
        self,
        row: int,
        query_network: str = "",
        context_vectors: str = "",
    ):
        """Phase 35: Ghi 2 cột Semantic Strategy (Q-R) vào Google Sheet."""
        self.update_cell(row, "Semantic Query Network", query_network or "N/A (No Query Network)")
        self.update_cell(row, "Context Vectors & Guidelines", context_vectors or "N/A (No Context Vectors)")
        logger.info("[GSHEET] Đã ghi 2 cột Semantic Strategy (Q-R) vào dòng %d", row)

    @property
    def is_connected(self) -> bool:
        return self._connected
