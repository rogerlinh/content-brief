# -*- coding: utf-8 -*-
"""
csv_reader.py - Đọc danh sách chủ đề từ file CSV.

Xử lý encoding UTF-8 và validate dữ liệu đầu vào.
File CSV có thể chứa header hoặc không (auto-detect).
"""

import csv
import logging
import os
from typing import List, Dict

logger = logging.getLogger(__name__)


def read_topics(filepath: str) -> List[Dict]:
    """
    Đọc danh sách topics từ file CSV.

    Args:
        filepath: Đường dẫn tuyệt đối tới file CSV.

    Returns:
        Danh sách dict với keys: {"id": int, "topic": str}

    Raises:
        FileNotFoundError: Nếu file không tồn tại.
        ValueError: Nếu file rỗng hoặc không có topic hợp lệ.
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Không tìm thấy file CSV: {filepath}")

    topics = []
    topic_id = 1

    # Đọc file với encoding UTF-8 (hỗ trợ UTF-8-BOM)
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)

        for row in reader:
            if not row:
                continue

            # Lấy cột đầu tiên làm topic
            raw_topic = row[0].strip()

            # Bỏ qua dòng trống hoặc header-like
            if not raw_topic or raw_topic.lower() in ("topic", "topics", "chủ đề"):
                continue

            topics.append({
                "id": topic_id,
                "topic": raw_topic,
            })
            topic_id += 1

    if not topics:
        raise ValueError(f"File CSV không chứa topic hợp lệ: {filepath}")

    logger.info("Đã đọc %d topics từ %s", len(topics), os.path.basename(filepath))
    return topics
