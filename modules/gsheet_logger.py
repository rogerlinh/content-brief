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

# ── Phase 35: Retry wrapper cho Google Sheets API ──────────────────────────────
def _gsheet_update_with_retry(worksheet, range_name, values, max_retries=3, base_delay=2.0):
    """Wrapper có retry + exponential backoff cho worksheet.update()."""
    for attempt in range(max_retries):
        try:
            worksheet.update(range_name=range_name, values=values)
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("[GSHEET] Update thất bại (lần %d), thử lại sau %.1fs: %s", attempt + 1, delay, e)
                time.sleep(delay)
            else:
                logger.error("[GSHEET] Update thất bại sau %d lần thử: %s", max_retries, e)
                raise
    return False

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
        self._col_a_cache: Dict[str, int] = {}  # keyword_lower -> latest row

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
                _gsheet_update_with_retry(self.worksheet, range_name="A1:R1", values=[SHEET_HEADERS])
                time.sleep(1.5)
                # Bold headers
                try:
                    self.worksheet.format("A1:R1", {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                        "horizontalAlignment": "CENTER",
                    })
                except Exception as fmt_e:
                    logger.warning("[GSHEET] Lỗi format headers: %s", fmt_e)
                time.sleep(1.5)
                logger.info("[GSHEET] Đã cập nhật lại headers (A1:R1) vào dòng 1")
        except Exception as e:
            logger.warning("[GSHEET] Không thể viết headers: %s", str(e))

    def _refresh_col_a_cache(self):
        """Phase 36: Đọc cột A 1 lần. Gọi nhiều lần trong cùng batch vẫn dùng cache."""
        if self._col_a_cache:  # đã có cache → bỏ qua
            return
        try:
            all_values = self.worksheet.col_values(1)
            self._col_a_cache = {}
            for idx, val in enumerate(all_values):
                if val:
                    self._col_a_cache[str(val).strip().lower()] = idx + 1  # 1-indexed
            logger.debug("[GSHEET] Đã cache %d keywords từ cột A", len(self._col_a_cache))
        except Exception as e:
            logger.warning("[GSHEET] Lỗi refresh cache cột A: %s", str(e))

    def _next_available_row(self) -> int:
        """Phase 36: Dùng cache để tìm dòng trống — O(1) thay vì O(n)."""
        self._refresh_col_a_cache()
        used_rows = set(self._col_a_cache.values())
        row = 2  # bắt đầu từ dòng 2 (dòng 1 = header)
        while row in used_rows:
            row += 1
        return row

    def _reset_keyword_row(self, row: int, keyword: str):
        """Xoa du lieu cu tren dong rerun de lan chay moi cap nhat ro rang."""
        if row < 2:
            return
        try:
            blank_values = [""] * (len(SHEET_HEADERS) - 1)
            _gsheet_update_with_retry(self.worksheet, range_name=f"B{row}:R{row}", values=[blank_values])
            time.sleep(1.0)
            _gsheet_update_with_retry(self.worksheet, range_name=f"A{row}:B{row}", values=[[keyword, "🔄 Running"]])
            time.sleep(1.0)
            self.worksheet.format(
                f"A{row}:R{row}",
                {"backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.8}},
            )
        except Exception as e:
            logger.warning("[GSHEET] Lỗi _reset_keyword_row row %d: %s", row, e)

    def start_keyword(self, keyword: str) -> int:
        """Bat dau xu ly 1 keyword va tai su dung dong cu neu keyword da ton tai."""
        if not self._connected:
            print("[GSHEET] Chua ket noi. Bo qua start_keyword.")
            return -1

        kw_lower = keyword.strip().lower()
        target_row = -1

        print(f"[GSHEET] Chuan bi ghi keyword '{keyword}' len Sheet...")
        try:
            self._refresh_col_a_cache()
            if kw_lower in self._col_a_cache:
                target_row = self._col_a_cache[kw_lower]
                print(f"[GSHEET] Keyword da co truoc do. Se cap nhat lai dong {target_row}.")
            else:
                target_row = self._next_available_row()
            self._col_a_cache[kw_lower] = target_row
            print(f"[GSHEET] Dong duoc su dung cho lan chay hien tai: {target_row}")
        except Exception as e:
            self.has_error = True
            print(f"[GSHEET] Loi tim keyword: {e}")
            logger.error("[GSHEET] Loi tim keyword: %s", str(e))
            return -1

        print(f"[GSHEET] Ghi '{keyword}' vao dong {target_row}...")
        try:
            self._reset_keyword_row(target_row, keyword)
            time.sleep(1.5)  # Phase 35: Chờ Google Sheets xác nhận ghi
            print(f"[GSHEET] Da ghi keyword + format dong {target_row}.")
        except Exception as e:
            self.has_error = True
            print(f"[GSHEET] Loi ghi keyword: {e}")
            logger.error("[GSHEET] Loi ghi keyword: %s", str(e))
            return target_row

        logger.info("[GSHEET] Keyword '%s' o dong %d", keyword, target_row)
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
        """Cập nhật trạng thái (Cột B) + đổi màu nền với retry."""
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
            # Ghi trạng thái trước
            _gsheet_update_with_retry(self.worksheet, range_name=f"B{row}", values=[[label]])
            time.sleep(0.5)
            # Format màu sau
            try:
                self.worksheet.format(f"A{row}:R{row}", {"backgroundColor": bg_color})
            except Exception as fmt_e:
                logger.warning("[GSHEET] Lỗi format dòng %d: %s", row, fmt_e)
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
        """Ghi từng cột C, F, G, I, K riêng biệt với retry."""
        if not self._connected or row < 1:
            return
        writes = [
            (HEADER_TO_COL["Search Intent"], intent if intent else "N/A (Analysis Failed)"),
            (HEADER_TO_COL["Top 3 Đối thủ"], "\n".join(top_urls[:5]) if top_urls else "N/A (No URLs)"),
            (HEADER_TO_COL["Content Gaps"], "\n".join(gaps[:10]) if gaps else "N/A (No Gaps)"),
            (HEADER_TO_COL["PAA Questions"], "\n".join(paa) if paa else "N/A (No PAA)"),
            (HEADER_TO_COL["Smart N-Grams"], ngrams if ngrams else "N/A (No N-grams)"),
        ]
        for col_idx, value in writes:
            try:
                col_letter = self._col_letter(col_idx)
                _gsheet_update_with_retry(
                    self.worksheet,
                    range_name=f"{col_letter}{row}",
                    values=[[value]],
                )
                time.sleep(0.5)
            except Exception as e:
                self.has_error = True
                logger.warning("[GSHEET] Loi log_analysis_results col %s: %s", col_idx, e)

    def log_brief_results(
        self,
        row: int,
        headings_outline: str,
        internal_links: str,
        full_brief_md: str,
        data_analysis_md: str = "",
    ):
        """Ghi batch 4 cột M-R riêng biệt, mỗi cột có retry riêng."""
        if not self._connected or row < 1:
            return
        # M = col 12 (0-indexed: 12), N=13, O=14, P=15, Q=16, R=17
        writes = [
            (HEADER_TO_COL["Structure Outline"],          headings_outline or "N/A (No Outline)"),
            (HEADER_TO_COL["Internal Links"],             internal_links or "N/A (No Links)"),
            (HEADER_TO_COL["Báo cáo phân tích dữ liệu"], data_analysis_md or "N/A (No Data)"),
            (HEADER_TO_COL["Full Content Brief"],          full_brief_md or "N/A (Brief Failed)"),
        ]
        for col_idx, value in writes:
            try:
                col_letter = self._col_letter(col_idx)
                _gsheet_update_with_retry(
                    self.worksheet,
                    range_name=f"{col_letter}{row}",
                    values=[[value]],
                )
                time.sleep(1.0)  # Giữa các write
            except Exception as e:
                self.has_error = True
                logger.warning("[GSHEET] Lỗi log_brief_results col %s: %s", col_idx, e)

    def log_error(self, row: int, error_msg: str):
        """Ghi lỗi ngắn gọn vào cột A (ghi đè keyword), tô đỏ cả dòng."""
        if not self._connected or row < 1:
            return
        # Rút gọn lỗi: loại bỏ "Error: " prefix + cắt ngắn
        short_msg = error_msg[:80].replace("❌", "").replace("Error:", "").strip()
        label = f"❌ {short_msg}"
        try:
            _gsheet_update_with_retry(self.worksheet, range_name=f"A{row}", values=[[label]])
            time.sleep(0.5)
            try:
                self.worksheet.format(f"A{row}:R{row}", {
                    "backgroundColor": {"red": 1.0, "green": 0.85, "blue": 0.85},
                })
            except Exception as fmt_e:
                logger.warning("[GSHEET] Lỗi format error row %d: %s", row, fmt_e)
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
        """Ghi từng cột D, H, J, O, P riêng biệt với retry."""
        if not self._connected or row < 1:
            return
        writes = [
            (HEADER_TO_COL["Macro Context"], macro_context),
            (HEADER_TO_COL["EAV Table"], eav_table),
            (HEADER_TO_COL["FS/PAA Map"], fs_paa_map),
            (HEADER_TO_COL["Source Context Alignment"], source_context_alignment),
            (HEADER_TO_COL["Koray Quality Score"], quality_score),
        ]
        for col_idx, value in writes:
            if not value:
                continue
            try:
                col_letter = self._col_letter(col_idx)
                _gsheet_update_with_retry(
                    self.worksheet,
                    range_name=f"{col_letter}{row}",
                    values=[[value]],
                )
                time.sleep(0.5)
            except Exception as e:
                self.has_error = True
                logger.warning("[GSHEET] Lỗi log_koray_columns col %s: %s", col_idx, e)

    def log_semantic_strategy_columns(
        self,
        row: int,
        query_network: str = "",
        context_vectors: str = "",
    ):
        """Ghi đúng cột E (Semantic Query Network) và L (Context Vectors) với retry."""
        if not self._connected or row < 1:
            return
        writes = [
            (HEADER_TO_COL["Semantic Query Network"], query_network or "N/A (No Query Network)"),
            (HEADER_TO_COL["Context Vectors & Guidelines"], context_vectors or "N/A (No Context Vectors)"),
        ]
        for col_idx, value in writes:
            if not value:
                continue
            try:
                col_letter = self._col_letter(col_idx)
                _gsheet_update_with_retry(
                    self.worksheet,
                    range_name=f"{col_letter}{row}",
                    values=[[value]],
                )
                time.sleep(0.5)
            except Exception as e:
                self.has_error = True
                logger.warning("[GSHEET] Lỗi log_semantic_strategy_columns col %s: %s", col_idx, e)

    @property
    def is_connected(self) -> bool:
        return self._connected
