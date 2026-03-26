# -*- coding: utf-8 -*-
"""
gsheet_logger.py - Phase 11: Real-time Google Sheets Logging.

Ghi log tiến trình pipeline vào Google Sheet theo thời gian thực.
Mỗi keyword = 1 dòng, cập nhật từng cột khi hoàn thành từng bước.
"""

import logging
import os
import time
from typing import List, Dict

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
    "Báo cáo phân tích dữ liệu",   # Q: Report raw
    "Full Content Brief",           # R: Kết quả cuối cùng cho Writer
]

# Build header -> column index mapping once
HEADER_TO_COL = {name: idx for idx, name in enumerate(SHEET_HEADERS)}

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
        # P1 FIX: Cache col_values để tránh O(n) scan mỗi lần gọi start_keyword
        self._col_a_cache: Dict[str, int] = {}  # keyword_lower -> row

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

    def _refresh_col_a_cache(self):
        """P1 FIX: Đọc toàn bộ cột A 1 lần, cache lại. Gọi khi cần."""
        try:
            all_values = self.worksheet.col_values(1)
            self._col_a_cache = {}
            for idx, val in enumerate(all_values):
                if val:
                    self._col_a_cache[str(val).strip().lower()] = idx + 1  # 1-indexed
            logger.debug("[GSHEET] Đã cache %d keywords từ cột A", len(self._col_a_cache))
        except Exception as e:
            logger.warning("[GSHEET] Lỗi refresh cache cột A: %s", str(e))

    def start_keyword(self, keyword: str) -> int:
        """
        Bắt đầu xử lý 1 keyword — TÌM dòng cũ hoặc tạo dòng mới.
        MỌI thao tác GSheet đều bọc try/except riêng biệt.

        P1 FIX:
          - Dùng cache _col_a_cache thay vì O(n) scan mỗi lần
          - Batch write keyword + status + format trong 1 call

        Returns:
            Số dòng (row number), hoặc -1 nếu GSheet lỗi.
        """
        if not self._connected:
            print("⚠️ [GSHEET] Chưa kết nối. Bỏ qua start_keyword.")
            return -1

        kw_lower = keyword.strip().lower()
        target_row = -1

        # ── Bước 1: Tìm keyword trong cache ──
        print(f"➡️ [GSHEET] Đang tìm keyword '{keyword}' trên Sheet...")
        try:
            # P1 FIX: Dùng cache thay vì scan lại
            if kw_lower in self._col_a_cache:
                target_row = self._col_a_cache[kw_lower]
                print(f"✅ [GSHEET] Đã tìm thấy keyword ở dòng {target_row} (cache hit).")
            else:
                # Cache miss: refresh rồi tìm lại
                self._refresh_col_a_cache()
                if kw_lower in self._col_a_cache:
                    target_row = self._col_a_cache[kw_lower]
                    print(f"✅ [GSHEET] Đã tìm thấy keyword ở dòng {target_row} (sau refresh).")
                else:
                    # Tạo dòng mới
                    target_row = len(self._col_a_cache) + 2  # +2 vì dòng 1 = header
                    print(f"❌ [GSHEET] Không tìm thấy -> Tạo dòng mới: {target_row}")
                # Cập nhật cache
                self._col_a_cache[kw_lower] = target_row

        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi tìm keyword: {e}")
            logger.error("[GSHEET] Lỗi tìm keyword: %s", str(e))
            return -1

        # ── Bước 2: Batch write keyword + status + format (P1 FIX: gộp 3 calls) ──
        print(f"➡️ [GSHEET] Ghi '{keyword}' vào dòng {target_row}...")
        try:
            # Ghi cùng lúc A, B, format
            kw_value = keyword
            status_value = "🔄 Running"
            bg_color = {"red": 1.0, "green": 0.95, "blue": 0.8}

            self.worksheet.update(
                range_name=f"A{target_row}:B{target_row}",
                values=[[kw_value, status_value]],
            )
            # P1 FIX: Bỏ 1.5s sleep sau ghi, giữ 0.8s duy nhất cho cả batch
            time.sleep(0.8)
            self.worksheet.format(f"A{target_row}:R{target_row}", {
                "backgroundColor": bg_color,
            })
            # P1 FIX: Bỏ sleep sau format vì không cần thiết
            print(f"✅ [GSHEET] Đã ghi keyword + format dòng {target_row}.")
        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi ghi keyword: {e}")
            logger.error("[GSHEET] Lỗi ghi keyword: %s", str(e))
            return target_row  # Vẫn trả row để các bước sau thử ghi tiếp

        logger.info("[GSHEET] Keyword '%s' ở dòng %d", keyword, target_row)
        return target_row

    def update_cell(self, row: int, column_name: str, value: str):
        """P1 FIX: Cập nhật 1 ô. Bỏ sleep sau mỗi write (batch ở caller)."""
        if not self._connected or row < 1:
            return

        try:
            if column_name not in HEADER_TO_COL:
                print(f"⚠️ [GSHEET] Cột '{column_name}' không tồn tại (bỏ qua)")
                return

            col_idx = HEADER_TO_COL[column_name]
            col_letter = chr(65 + col_idx)  # A=0, B=1, ...
            # Truncate nếu quá dài (Google Sheets limit 50000 chars)
            if len(str(value)) > 45000:
                value = str(value)[:45000] + "\n\n... (truncated)"
            self.worksheet.update(
                range_name=f"{col_letter}{row}",
                values=[[value]],
            )
            # P1 FIX: Bỏ sleep — gọi flush_pending() ở cuối pipeline thay thế
        except ValueError:
            print(f"⚠️ [GSHEET] Cột '{column_name}' không tồn tại (bỏ qua)")
        except Exception as e:
            self.has_error = True
            print(f"⚠️ [GSHEET] Lỗi update_cell {column_name}: {e}")

    def _col_letter(self, col_idx: int) -> str:
        """Convert 0-based column index to Excel letter (A, B, ..., Z, AA, AB, ...)."""
        result = ""
        while col_idx >= 0:
            result = chr(65 + (col_idx % 26)) + result
            col_idx = col_idx // 26 - 1
        return result

    def set_status(self, row: int, status: str):
        """P1 FIX: Cập nhật trạng thái (Cột B) + đổi màu nền. Bỏ sleep."""
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
            # P1 FIX: Bỏ sleep
            self.worksheet.format(f"A{row}:R{row}", {
                "backgroundColor": bg_color,
            })
            # P1 FIX: Bỏ sleep
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
        """P1 FIX: Ghi batch 5 cột C-G trong 1 call thay vì 5 calls riêng."""
        if not self._connected or row < 1:
            return
        try:
            row_data = [""] * len(SHEET_HEADERS)
            row_data[HEADER_TO_COL["Search Intent"]] = intent if intent else "N/A (Analysis Failed)"
            row_data[HEADER_TO_COL["Top 3 Đối thủ"]] = "\n".join(top_urls[:5]) if top_urls else "N/A (No URLs)"
            row_data[HEADER_TO_COL["PAA Questions"]] = "\n".join(paa) if paa else "N/A (No PAA)"
            row_data[HEADER_TO_COL["Content Gaps"]] = "\n".join(gaps[:10]) if gaps else "N/A (No Gaps)"
            row_data[HEADER_TO_COL["Smart N-Grams"]] = ngrams if ngrams else "N/A (No N-grams)"
            self.worksheet.update(
                range_name=f"C{row}:G{row}",
                values=[row_data[2:7]],  # C=col2 → G=col6
            )
            # P1 FIX: Bỏ sleep
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi log_analysis_results: %s", str(e))

    def log_brief_results(
        self,
        row: int,
        headings_outline: str,
        internal_links: str,
        full_brief_md: str,
        data_analysis_md: str = "",
    ):
        """P1 FIX: Ghi batch 4 cột M-R trong 1 call."""
        if not self._connected or row < 1:
            return
        try:
            row_data = [""] * len(SHEET_HEADERS)
            row_data[HEADER_TO_COL["Structure Outline"]] = headings_outline if headings_outline else "N/A (No Outline)"
            row_data[HEADER_TO_COL["Internal Links"]] = internal_links if internal_links else "N/A (No Links)"
            row_data[HEADER_TO_COL["Báo cáo phân tích dữ liệu"]] = data_analysis_md if data_analysis_md else "N/A (No Data)"
            row_data[HEADER_TO_COL["Full Content Brief"]] = full_brief_md if full_brief_md else "N/A (Brief Failed)"
            self.worksheet.update(
                range_name=f"M{row}:R{row}",
                values=[row_data[12:18]],  # M=col12 → R=col17
            )
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi log_brief_results: %s", str(e))

    def log_error(self, row: int, error_msg: str):
        """Ghi lỗi ngắn gọn vào cột A (ghi đè keyword), tô đỏ cả dòng."""
        if not self._connected or row < 1:
            return
        # Rút gọn lỗi: loại bỏ "Error: " prefix + cắt ngắn
        short_msg = error_msg[:80].replace("❌", "").replace("Error:", "").strip()
        label = f"❌ {short_msg}"
        try:
            self.worksheet.update(
                range_name=f"A{row}",
                values=[[label]],
            )
            self.worksheet.format(f"A{row}:R{row}", {
                "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85},
            })
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
        """Ghi từng cột D, H, J, O, P riêng biệt để không đè data đã ghi ở log_analysis_results."""
        if not self._connected or row < 1:
            return
        try:
            writes = [
                (self._col_letter(HEADER_TO_COL["Macro Context"]), macro_context),           # D
                (self._col_letter(HEADER_TO_COL["EAV Table"]), eav_table),                   # H
                (self._col_letter(HEADER_TO_COL["FS/PAA Map"]), fs_paa_map),                 # J
                (self._col_letter(HEADER_TO_COL["Source Context Alignment"]), source_context_alignment),  # O
                (self._col_letter(HEADER_TO_COL["Koray Quality Score"]), quality_score),     # P
            ]
            for col_letter, value in writes:
                if value:
                    self.worksheet.update(
                        range_name=f"{col_letter}{row}",
                        values=[[value]],
                    )
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi log_koray_columns: %s", str(e))

    def log_semantic_strategy_columns(
        self,
        row: int,
        query_network: str = "",
        context_vectors: str = "",
    ):
        """Ghi đúng cột E (Semantic Query Network) và L (Context Vectors), không đè F."""
        if not self._connected or row < 1:
            return
        try:
            # E = col4 = index 4, L = col11 = index 11
            if query_network:
                self.worksheet.update(
                    range_name=f"{self._col_letter(4)}{row}",
                    values=[[query_network or "N/A (No Query Network)"]],
                )
            if context_vectors:
                self.worksheet.update(
                    range_name=f"{self._col_letter(11)}{row}",
                    values=[[context_vectors or "N/A (No Context Vectors)"]],
                )
        except Exception as e:
            self.has_error = True
            logger.warning("[GSHEET] Lỗi log_semantic_strategy_columns: %s", str(e))

    @property
    def is_connected(self) -> bool:
        return self._connected
