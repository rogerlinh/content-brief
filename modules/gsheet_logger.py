# -*- coding: utf-8 -*-
"""
gsheet_logger.py - Phase 11: Real-time Google Sheets Logging.

Ghi log tiến trình pipeline vào Google Sheet theo thời gian thực.
Mỗi keyword = 1 dòng, cập nhật từng cột khi hoàn thành từng bước.
"""

import logging
import os
import base64
import json
import re
import sys
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


def _safe_console_print(message: str) -> None:
    text = str(message)
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
        print(safe_text)

# Cấu trúc cột trên Google Sheet (Sắp xếp theo Logical Semantic Workflow)
SHEET_HEADERS = [
    "Keyword",                      # A: Topic chính
    "Trạng thái",                   # B: Status
    "Search Intent",                # C: Phân loại ý định tìm kiếm
    "Macro Context",                # D: Bối cảnh vĩ mô (Koray)
    "Semantic Query Network",       # E: Mạng lưới LSI/Variants (Cluster)
    "Top 10 Đối thủ",               # F: SERP Competitors
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
    "Full Content Brief",           # Q: Kết quả cuối cùng cho Writer
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


def _normalize_service_account_info(creds_data: dict | None) -> dict | None:
    if not isinstance(creds_data, dict):
        return creds_data
    normalized = dict(creds_data)
    private_key = str(normalized.get("private_key", "") or "")
    if private_key:
        if "\\n" in private_key and "\n" not in private_key:
            private_key = private_key.replace("\\n", "\n")
        private_key = private_key.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not private_key.endswith("\n"):
            private_key += "\n"
        normalized["private_key"] = private_key
    return normalized


def _validate_private_key_pem(private_key: str) -> tuple[bool, str]:
    key_text = str(private_key or "")
    if not key_text:
        return False, "Thiếu private_key trong credentials."
    if "-----BEGIN PRIVATE KEY-----" not in key_text or "-----END PRIVATE KEY-----" not in key_text:
        return False, "private_key thiếu PEM markers BEGIN/END PRIVATE KEY."

    body = key_text.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
    body_no_ws = re.sub(r"\s+", "", body)
    if not body_no_ws:
        return False, "private_key không có nội dung base64."
    if len(body_no_ws) % 4 != 0:
        return False, (
            "private_key bị hỏng hoặc bị cắt cụt: PEM base64 length "
            f"{len(body_no_ws)} không chia hết cho 4."
        )
    try:
        base64.b64decode(body_no_ws, validate=True)
    except Exception as exc:
        return False, f"private_key không decode được dạng PEM base64: {exc}"
    return True, ""


class GSheetLogger:
    """
    Logger ghi tiến trình pipeline vào Google Sheet.

    Usage:
        glog = GSheetLogger(creds_data=creds_dict, sheet_url="https://...")
        # OR legacy:
        glog = GSheetLogger(creds_path="path/to/creds.json")
        glog.connect(sheet_url="https://docs.google.com/spreadsheets/d/...")
        row = glog.start_keyword("Protein cho người ăn chay")
        glog.update_cell(row, "Search Intent", "Informational")
        glog.set_status(row, "Done")
    """

    def __init__(self, creds_path: str = None, sheet_url: str = None, creds_data: dict = None):
        self.creds_path = creds_path or DEFAULT_CREDS_PATH
        self.sheet_url = sheet_url or DEFAULT_SHEET_URL
        # Phase 38: creds_data dict (in-memory) ưu tiên hơn creds_path
        self._creds_data = creds_data
        self.client = None
        self.sheet = None
        self.worksheet = None
        self._connected = False
        self.has_error = False
        # Phase 39: Lưu lỗi chi tiết để caller đọc được
        self._last_error: str = ""
        # P1 FIX: Cache col_values để tránh O(n) scan mỗi lần gọi start_keyword
        self._col_a_cache: Dict[str, int] = {}  # keyword_lower -> latest row

    def connect(self, sheet_url: str = None) -> bool:
        """
        Kết nối Google Sheet qua Service Account.

        Priority:
        1. creds_data (in-memory dict — từ user upload hoặc Streamlit Secrets)
        2. st.secrets (Streamlit Cloud Secrets — persist qua redeploy)
        3. creds_path (file local — chỉ dùng được trên máy user)

        Returns:
            True nếu kết nối thành công.
        """
        if sheet_url:
            self.sheet_url = sheet_url

        # Credential precedence is resolved by app.py / worker.py before
        # instantiating GSheetLogger. Keep connect() deterministic so a stale
        # local secrets file cannot override the caller-selected source.
        if self._creds_data is not None:
            logger.info("[GSHEET] Dùng creds_data do caller truyền vào.")
        elif self.creds_path:
            logger.info("[GSHEET] Dùng creds_path do caller truyền vào: %s", self.creds_path)

        try:
            import gspread
            from google.oauth2.service_account import Credentials

            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive",
            ]

            # Phase 43: Debug JWT token trước khi gửi request
            _safe_console_print(f"[GSHEET DEBUG] _creds_data = {type(self._creds_data).__name__} ({'None' if self._creds_data is None else 'has data'})")
            _safe_console_print(f"[GSHEET DEBUG] creds_path = {self.creds_path or 'None'}")

            # Phase 38: Ưu tiên creds_data (in-memory dict) > creds_path (file)
            if self._creds_data is not None:
                self._creds_data = _normalize_service_account_info(self._creds_data)
                key_ok, key_error = _validate_private_key_pem(self._creds_data.get("private_key", ""))
                if not key_ok:
                    raise ValueError(key_error)
                creds = Credentials.from_service_account_info(
                    self._creds_data, scopes=scopes
                )
                pk_val = self._creds_data.get("private_key", "")
                _safe_console_print(f"[GSHEET DEBUG] creds_data: pk length={len(pk_val)}, starts={pk_val[:50]!r}, ends=...{pk_val[-30:]!r}")
                _safe_console_print(f"[GSHEET DEBUG] creds_data: client_email={self._creds_data.get('client_email', 'MISSING')}")
                _safe_console_print(f"[GSHEET DEBUG] creds_data: token_uri={self._creds_data.get('token_uri', 'MISSING')}")
                logger.info("[GSHEET] Dùng credentials từ in-memory dict.")
            elif self.creds_path:
                _safe_console_print(f"[GSHEET DEBUG] Dùng creds_path: {self.creds_path}")
                # Phase 43: Đọc và verify private_key từ file trước khi dùng
                import json as _json
                _data = {}
                _pk = ""
                try:
                    with open(self.creds_path, "r", encoding="utf-8") as _f:
                        _data = _normalize_service_account_info(_json.load(_f))
                    _pk = _data.get("private_key", "")
                    _safe_console_print(f"[GSHEET DEBUG] file pk: length={len(_pk)}, starts={_pk[:50]!r}")
                    _safe_console_print(f"[GSHEET DEBUG] file: client_email={_data.get('client_email', 'MISSING')}")
                except Exception as _e:
                    _safe_console_print(f"[GSHEET DEBUG] Lỗi đọc file verify: {_e}")
                key_ok, key_error = _validate_private_key_pem(_pk)
                if not key_ok:
                    raise ValueError(key_error)
                creds = Credentials.from_service_account_info(_data, scopes=scopes)
                logger.info("[GSHEET] Dùng credentials từ file: %s", self.creds_path)
            else:
                raise ValueError("Không có credentials: cả creds_data (None) và creds_path (None) đều None.")
            self.client = gspread.authorize(creds)

            # Mở sheet bằng URL
            self.sheet = self.client.open_by_url(self.sheet_url)
            self.worksheet = self.sheet.sheet1

            # Viết headers nếu chưa có
            self._ensure_headers()

            self._connected = True
            logger.info("[GSHEET] Kết nối thành công: %s", self.sheet.title)
            _safe_console_print("[GSHEET] Ket noi Google Sheet thanh cong!")
            return True

        except FileNotFoundError as e:
            self._last_error = f"FileNotFoundError: {e} — path: {self.creds_path}"
            logger.error("[GSHEET] %s", self._last_error)
            return False
        except Exception as e:
            import traceback
            self._last_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            logger.error("[GSHEET] Lỗi kết nối: %s", str(e))
            return False

    def _ensure_headers(self):
        """Viết header vào dòng 1 nếu chưa có."""
        try:
            first_row = self.worksheet.row_values(1)
            # Fix: first_row có thể là None → kiểm tra trước khi so sánh
            if not first_row or not isinstance(first_row, list):
                needs_write = True
            elif len(first_row) < len(SHEET_HEADERS):
                needs_write = True
            else:
                header_slice = first_row[:len(SHEET_HEADERS)]
                # So sánh từng ô — bỏ qua ô None/empty
                needs_write = False
                for i, (actual, expected) in enumerate(zip(header_slice, SHEET_HEADERS)):
                    if actual != expected:
                        needs_write = True
                        break
            if needs_write:
                _gsheet_update_with_retry(self.worksheet, range_name="A1:Q1", values=[SHEET_HEADERS])
                time.sleep(1.5)
                # Bold headers
                try:
                    self.worksheet.format("A1:Q1", {
                        "textFormat": {"bold": True},
                        "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9},
                        "horizontalAlignment": "CENTER",
                    })
                except Exception as fmt_e:
                    logger.warning("[GSHEET] Lỗi format headers: %s", fmt_e)
                time.sleep(1.5)
                try:
                    self.worksheet.resize(cols=len(SHEET_HEADERS))
                except Exception as resize_e:
                    logger.warning("[GSHEET] Không thể resize cột sheet: %s", resize_e)
                time.sleep(0.5)
                logger.info("[GSHEET] Đã cập nhật lại headers (A1:Q1) vào dòng 1")
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
            end_col = self._col_letter(len(SHEET_HEADERS) - 1)
            _gsheet_update_with_retry(self.worksheet, range_name=f"B{row}:{end_col}{row}", values=[blank_values])
            time.sleep(1.0)
            _gsheet_update_with_retry(self.worksheet, range_name=f"A{row}:B{row}", values=[[keyword, "🔄 Running"]])
            time.sleep(1.0)
            self.worksheet.format(
                f"A{row}:Q{row}",
                {"backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.8}},
            )
        except Exception as e:
            logger.warning("[GSHEET] Lỗi _reset_keyword_row row %d: %s", row, e)

    def start_keyword(self, keyword: str) -> int:
        """Bat dau xu ly 1 keyword va tai su dung dong cu neu keyword da ton tai."""
        if not self._connected:
            _safe_console_print("[GSHEET] Chua ket noi. Bo qua start_keyword.")
            return -1

        kw_lower = keyword.strip().lower()
        target_row = -1

        _safe_console_print(f"[GSHEET] Chuan bi ghi keyword '{keyword}' len Sheet...")
        try:
            self._refresh_col_a_cache()
            if kw_lower in self._col_a_cache:
                target_row = self._col_a_cache[kw_lower]
                _safe_console_print(f"[GSHEET] Keyword da co truoc do. Se cap nhat lai dong {target_row}.")
            else:
                target_row = self._next_available_row()
            self._col_a_cache[kw_lower] = target_row
            _safe_console_print(f"[GSHEET] Dong duoc su dung cho lan chay hien tai: {target_row}")
        except Exception as e:
            self.has_error = True
            _safe_console_print(f"[GSHEET] Loi tim keyword: {e}")
            logger.error("[GSHEET] Loi tim keyword: %s", str(e))
            return -1

        _safe_console_print(f"[GSHEET] Ghi '{keyword}' vao dong {target_row}...")
        try:
            self._reset_keyword_row(target_row, keyword)
            time.sleep(1.5)  # Phase 35: Chờ Google Sheets xác nhận ghi
            _safe_console_print(f"[GSHEET] Da ghi keyword + format dong {target_row}.")
        except Exception as e:
            self.has_error = True
            _safe_console_print(f"[GSHEET] Loi ghi keyword: {e}")
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
                _safe_console_print(f"[GSHEET] Cot '{column_name}' khong ton tai (bo qua)")
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
            _safe_console_print(f"[GSHEET] Cot '{column_name}' khong ton tai (bo qua)")
        except Exception as e:
            self.has_error = True
            _safe_console_print(f"[GSHEET] Loi update_cell {column_name}: {e}")

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
                self.worksheet.format(f"A{row}:Q{row}", {"backgroundColor": bg_color})
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
            (HEADER_TO_COL["Top 10 Đối thủ"], "\n".join(top_urls[:10]) if top_urls else "Offline fallback: SERP unavailable"),
            (HEADER_TO_COL["Content Gaps"], "\n".join(gaps[:10]) if gaps else "Offline fallback: derived semantic gaps"),
            (HEADER_TO_COL["PAA Questions"], "\n".join(paa) if paa else "Offline fallback: no PAA"),
            (HEADER_TO_COL["Smart N-Grams"], ngrams if ngrams else "Offline fallback: semantic n-grams unavailable"),
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
    ):
        """Ghi batch 4 cột M-R riêng biệt, mỗi cột có retry riêng."""
        if not self._connected or row < 1:
            return
        # M = col 12 (0-indexed: 12), N=13, O=14, P=15, Q=16, R=17
        writes = [
            (HEADER_TO_COL["Structure Outline"],          headings_outline or "N/A (No Outline)"),
            (HEADER_TO_COL["Internal Links"],             internal_links or "N/A (No Links)"),
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
            _gsheet_update_with_retry(self.worksheet, range_name=f"B{row}", values=[[label]])
            time.sleep(0.5)
            detail_col = self._col_letter(HEADER_TO_COL["Full Content Brief"])
            _gsheet_update_with_retry(self.worksheet, range_name=f"{detail_col}{row}", values=[[error_msg[:2000]]])
            time.sleep(0.5)
            try:
                self.worksheet.format(f"A{row}:Q{row}", {
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
            (HEADER_TO_COL["Semantic Query Network"], query_network or "Offline fallback: no query network"),
            (HEADER_TO_COL["Context Vectors & Guidelines"], context_vectors or "Offline fallback: no context vectors"),
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
