# -*- coding: utf-8 -*-
"""
csv_logger.py - Phase 12: Local Real-time State Database.

Ghi log tiến trình pipeline vào file database.csv ở local liên tục.
Giúp frontend app.py đọc lại state khi người dùng F5 hoặc đóng/mở tab.
"""

import pandas as pd
import os
import logging
import threading
from typing import List

logger = logging.getLogger(__name__)

# Lock file để tránh tranh chấp khi có nhiều process read/write
file_lock = threading.Lock()

DB_HEADERS = [
    "Keyword",                      # 0
    "Trạng thái",                   # 1
    "Search Intent",                # 2
    "Macro Context",                # 3
    "Semantic Query Network",       # 4
    "Top 3 Đối thủ",                # 5
    "Content Gaps",                 # 6
    "EAV Table",                    # 7
    "PAA Questions",                # 8
    "FS/PAA Map",                   # 9
    "Smart N-Grams",                # 10
    "Context Vectors & Guidelines", # 11
    "Structure Outline",            # 12
    "Internal Links",               # 13
    "Source Context Alignment",     # 14
    "Koray Quality Score",          # 15
    "Báo cáo phân tích dữ liệu",    # 16
    "Full Content Brief",           # 17
]


class CsvLogger:
    """
    Logger ghi tiến trình pipeline vào file database.csv nội bộ.
    Mỗi khi cập nhật, flush thẳng xuống ổ đĩa dùng pandas to_csv.
    """
    
    def __init__(self, db_path: str = "database.csv"):
        self.db_path = db_path
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        """Khởi tạo file database.csv với Header nếu chưa có."""
        with file_lock:
            if not os.path.exists(self.db_path):
                df = pd.DataFrame(columns=DB_HEADERS)
                df.to_csv(self.db_path, index=False, encoding="utf-8-sig")
                logger.debug("[CSV] Khởi tạo %s", self.db_path)
            else:
                # Phase 33: Thêm cột mới nếu file cũ thiếu cột Koray
                try:
                    df_check = pd.read_csv(self.db_path, nrows=0, encoding="utf-8-sig")
                    missing = [c for c in DB_HEADERS if c not in df_check.columns]
                    if missing:
                        df_full = pd.read_csv(self.db_path, encoding="utf-8-sig")
                        for col in missing:
                            df_full[col] = ""
                        df_full.to_csv(self.db_path, index=False, encoding="utf-8-sig")
                        logger.info("[CSV] Đã thêm %d cột mới: %s", len(missing), missing)
                except Exception:
                    pass

    def _read_db(self) -> pd.DataFrame:
        """Đọc file CSV lên"""
        try:
            return pd.read_csv(self.db_path, encoding="utf-8-sig")
        except Exception:
            # Fallback nếu file lỗi
            return pd.DataFrame(columns=DB_HEADERS)

    def _write_db(self, df: pd.DataFrame):
        """Ghi đè file CSV và flush"""
        df.to_csv(self.db_path, index=False, encoding="utf-8-sig")

    def start_keyword(self, keyword: str) -> int:
        """
        Bắt đầu xử lý keyword -> Append row với trạng thái Running.
        Trả về Index row vừa tạo.
        """
        with file_lock:
            df = self._read_db()
            
            # Kiểm tra xem keyword đã có trong hôm nay hay job hiện tại chưa
            # Thực tế cứ append vào cuối
            new_row = {col: "" for col in DB_HEADERS}
            new_row["Keyword"] = keyword
            new_row["Trạng thái"] = "🔄 Running"
            
            # Thêm row dùng append hoặc concat
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            self._write_db(df)
            
            row_index = len(df) - 1
            logger.debug("[CSV] Started row %d for %s", row_index, keyword)
            return row_index

    def update_cell(self, row_idx: int, column_name: str, value: str):
        """Cập nhật một ô và flush đĩa."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df) and column_name in df.columns:
                df.at[row_idx, column_name] = value
                self._write_db(df)

    def log_analysis_results(
        self,
        row_idx: int,
        intent: str,
        top_urls: List[str],
        paa: List[str],
        gaps: List[str],
        ngrams: List[str],
    ):
        """Cập nhật bước phân tích."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df):
                df.at[row_idx, "Search Intent"] = str(intent) if intent else "N/A (Analysis Failed)"
                df.at[row_idx, "Top 3 Đối thủ"] = "\n".join([str(u) for u in top_urls[:5]]) if top_urls else "N/A (No URLs)"
                df.at[row_idx, "PAA Questions"] = "\n".join([str(q) for q in paa]) if paa else "N/A (No PAA)"
                df.at[row_idx, "Content Gaps"] = "\n".join([str(g) for g in gaps[:10]]) if gaps else "N/A (No Gaps)"
                df.at[row_idx, "Smart N-Grams"] = "\n".join([str(n) for n in ngrams[:5]]) if ngrams else "N/A (No N-grams)"
                self._write_db(df)

    def log_semantic_strategy_columns(
        self,
        row_idx: int,
        query_network: str = "",
        context_vectors: str = "",
    ):
        """Phase 35: Ghi 2 cột Semantic Strategy (Q-R) vào CSV database."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df):
                def _trunc(s, n=1500):
                    return s[:n] + "\n...(truncated)" if len(s or "") > n else (s or "")
                
                df.at[row_idx, "Semantic Query Network"] = _trunc(query_network) or "N/A (No Query Network)"
                df.at[row_idx, "Context Vectors & Guidelines"] = _trunc(context_vectors) or "N/A (No Context Vectors)"
                self._write_db(df)
                logger.debug("[CSV] Ghi 2 cột Semantic Strategy (Q-R) vào row %d", row_idx)

    def log_brief_results(
        self,
        row_idx: int,
        headings_outline: str,
        internal_links: str,
        full_brief_md: str,
        data_analysis_md: str = "",
    ):
        """Cập nhật bước Brief tạo ra."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df):
                df.at[row_idx, "Structure Outline"] = headings_outline
                df.at[row_idx, "Internal Links"] = internal_links
                # Tạm thời cắt giới hạn brief trên CSV để tránh quá tải RAM UI
                # Nếu UI ko tải nổi bản full, ta cắt ngắn (Ví dụ hiển thị 1000 char preview)
                preview = full_brief_md
                if len(preview) > 2000:
                    preview = preview[:2000] + "\n...(Xem full trong file MD)"
                    
                preview_analysis = data_analysis_md
                if len(preview_analysis) > 2000:
                    preview_analysis = preview_analysis[:2000] + "\n...(Xem full trong file MD)"
                    
                df.at[row_idx, "Báo cáo phân tích dữ liệu"] = preview_analysis
                df.at[row_idx, "Full Content Brief"] = preview
                self._write_db(df)

    def set_status(self, row_idx: int, status: str, message: str = ""):
        """Cập nhật Cột trạng thái."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df):
                flag = status
                if status == "Running":
                    flag = "🔄 Running"
                elif status == "Done":
                    flag = "✅ Done"
                elif status == "Error":
                    flag = f"❌ Error: {message[:100]}"
                
                df.at[row_idx, "Trạng thái"] = flag
                self._write_db(df)

    def log_koray_columns(
        self,
        row_idx: int,
        macro_context: str = "",
        eav_table: str = "",
        fs_paa_map: str = "",
        source_context_alignment: str = "",
        quality_score: str = "",
    ):
        """Phase 33: Ghi 5 cột Koray vào CSV database."""
        with file_lock:
            df = self._read_db()
            if 0 <= row_idx < len(df):
                # Truncate dài để tránh file quá nặng
                def _trunc(s, n=1500):
                    return s[:n] + "\n...(truncated)" if len(s or "") > n else (s or "")

                df.at[row_idx, "Macro Context"] = _trunc(macro_context)
                df.at[row_idx, "EAV Table"] = _trunc(eav_table)
                df.at[row_idx, "FS/PAA Map"] = _trunc(fs_paa_map)
                df.at[row_idx, "Source Context Alignment"] = _trunc(source_context_alignment)
                df.at[row_idx, "Koray Quality Score"] = _trunc(quality_score)
                self._write_db(df)
                logger.debug("[CSV] Ghi 5 cột Koray vào row %d", row_idx)

