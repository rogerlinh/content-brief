# -*- coding: utf-8 -*-
"""
worker.py - Phase 14.5: Emergency Stability Patch

Background Worker chạy TUẦN TỰ từng keyword.
- KHÔNG dùng ThreadPool / ProcessPool.
- Mỗi keyword được bọc trong try...except riêng biệt.
- Nếu 1 keyword lỗi → ghi log lỗi vào CSV → nhảy sang keyword tiếp theo.
- Nghỉ 3 giây giữa các keyword để tránh Rate Limit.
"""

import json
import os
import sys
import io
import time
import logging
import traceback

# ── Phase 18: Force Flush stdout/stderr (không buffer) ──
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)
except Exception:
    pass  # Bỏ qua nếu đã wrapped

# Setup logging
try:
    from config import setup_logging
    setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO)

from modules.gsheet_logger import GSheetLogger
from modules.csv_logger import CsvLogger

logger = logging.getLogger("Worker")

JOB_FILE = "job_queue.json"
LOCK_FILE = "worker_lock.txt"
CSV_DB = "database_v2.csv"


def set_lock():
    """Tạo file lock chứa PID để UI biết worker đang chạy."""
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def remove_lock():
    """Xóa file lock khi worker kết thúc."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass


def process_single_keyword(kw, idx, total, config_opts, output_dir, glog, csv_log):
    """
    Xử lý 1 keyword duy nhất. Toàn bộ logic được bọc trong try...except.
    Nếu lỗi → ghi vào CSV → return (không crash worker).
    """
    csv_row = -1
    try:
        # 1. Tạo dòng trong CSV (luôn thành công)
        csv_row = csv_log.start_keyword(kw)
        logger.info("Worker [%d/%d]: Bắt đầu '%s' (CSV row=%d)", idx, total, kw, csv_row)

        # 2. Import pipeline function (lazy import để tránh circular)
        from main_generator import _process_single_topic

        # Phase 33: Load project từ DB (backward-compatible: project=None nếu không có project_id)
        project = None
        project_id = config_opts.get("project_id")
        if project_id:
            try:
                from modules.project_manager import ProjectManager
                pm = ProjectManager()
                project = pm.get_by_id(project_id)
                if project:
                    logger.info("  [WORKER] Dùng Project: %s (ID=%d)", project.brand_name, project.id)
                else:
                    logger.warning("  [WORKER] Không tìm thấy project_id=%s trong DB", project_id)
            except Exception as pe:
                logger.warning("  [WORKER] Lỗi load project: %s", pe)

        # 3. Gọi pipeline — truyền glog vào nhưng nếu GSheet lỗi bên trong,
        #    main_generator đã tự bắt exception rồi.
        filepath = _process_single_topic(
            topic=kw,
            enable_serp=config_opts.get("enable_serp", True),
            enable_network=config_opts.get("enable_network", True),
            enable_context=config_opts.get("enable_context", False),
            enable_linking=config_opts.get("enable_linking", True),
            methodology=config_opts.get("methodology", "auto"),
            output_dir=output_dir,
            total_steps=1,
            glog=glog,
            csv_log=csv_log,
            csv_row=csv_row,
            project=project,  # Phase 33
        )

        if filepath:
            logger.info("Worker [%d/%d]: ✅ Hoàn thành '%s' -> %s", idx, total, kw, filepath)
        else:
            logger.error("Worker [%d/%d]: ❌ Pipeline trả về None cho '%s'", idx, total, kw)
            csv_log.set_status(csv_row, "Error", "Pipeline trả về None")

    except Exception as e:
        # BẮT MỌI LỖI – ghi nguyên văn lỗi vào CSV Status rồi nhảy tiếp
        error_msg = str(e)
        logger.error("Worker [%d/%d]: ❌ LỖI NGHIÊM TRỌNG '%s': %s", idx, total, kw, error_msg)
        logger.error("Traceback:\n%s", traceback.format_exc())
        print(f"❌ [WORKER] Lỗi keyword '{kw}': {error_msg}")

        # Ghi lỗi vào CSV (LUÔN thành công vì CSV là local)
        if csv_row >= 0:
            try:
                csv_log.set_status(csv_row, "Error", error_msg[:200])
            except Exception:
                pass

        # Thử ghi lỗi vào GSheet (BỎ QUA nếu lỗi)
        try:
            if glog and glog.is_connected:
                print(f"➡️ [GSHEET] Thử ghi lỗi vào Sheet cho '{kw}'...")
                glog.log_error(-1, f"[{kw}] {error_msg[:150]}")
                print("✅ [GSHEET] Đã ghi lỗi lên Sheet.")
        except Exception as ge:
            print(f"⚠️ [GSHEET] Lỗi Sync Google Sheet (Bỏ qua): {ge}")
            # KHÔNG ĐƯỢC RAISE. Chỉ print và chạy tiếp.


def main():
    logger.info("=" * 50)
    logger.info("WORKER BẮT ĐẦU (Phase 14.5 - Sequential Mode)")
    logger.info("=" * 50)

    if not os.path.exists(JOB_FILE):
        logger.error("Không tìm thấy %s. Worker tự động thoát.", JOB_FILE)
        return

    # ── 1. Đọc cấu hình từ job_queue.json ──
    try:
        with open(JOB_FILE, "r", encoding="utf-8") as f:
            raw = f.read()

        # Parse JSON an toàn
        job_data = json.loads(raw)

        # Đề phòng double-encoded string
        if isinstance(job_data, str):
            logger.warning("job_data là string, thử parse lần 2...")
            try:
                job_data = json.loads(job_data)
            except Exception:
                logger.error("⚠️ Không thể parse job_data: %s", job_data[:300])
                return

        if not isinstance(job_data, dict):
            logger.error("⚠️ job_data không phải dict, type=%s", type(job_data).__name__)
            return

    except Exception as e:
        logger.error("Lỗi đọc job_queue.json: %s", e)
        return

    keywords = job_data.get("keywords", [])
    config_opts = job_data.get("config", {})
    creds_path = job_data.get("creds_path")
    sheet_url = job_data.get("sheet_url")
    output_dir = job_data.get("output_dir", "output_ui")

    if not keywords:
        logger.warning("Danh sách keywords rỗng. Worker thoát.")
        return

    # Đảm bảo config_opts là dict
    if not isinstance(config_opts, dict):
        config_opts = {}

    # ── 2. Set Lock ──
    set_lock()
    os.makedirs(output_dir, exist_ok=True)

    # ── 3. Khởi tạo Loggers ──
    glog = GSheetLogger(creds_path=creds_path, sheet_url=sheet_url)
    try:
        if creds_path and os.path.exists(str(creds_path)):
            glog.connect()
    except Exception as e:
        logger.warning("Không thể kết nối GSheet: %s. Tiếp tục chỉ ghi CSV.", e)

    csv_log = CsvLogger(db_path=CSV_DB)

    total = len(keywords)
    logger.info("Worker nhận %d keywords để xử lý TUẦN TỰ", total)

    # ── 4. Vòng lặp TUẦN TỰ (KHÔNG dùng ThreadPool/ProcessPool) ──
    for i, kw in enumerate(keywords, 1):
        process_single_keyword(kw, i, total, config_opts, output_dir, glog, csv_log)

        # Nghỉ 3 giây giữa các keyword để tránh Rate Limit
        if i < total:
            logger.info("Worker: Nghỉ 3 giây trước keyword tiếp theo...")
            time.sleep(3)

    # ── 5. Hoàn tất ──
    logger.info("=" * 50)
    logger.info("WORKER HOÀN TẤT: %d/%d keywords đã xử lý", total, total)
    logger.info("=" * 50)
    remove_lock()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # ── Phase 18: Bắn traceback ra stderr cho app.py đọc ──
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"💀 WORKER CRASH: {e}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
        
        # Xóa lock file để UI biết worker đã chết
        try:
            if os.path.exists("worker_lock.txt"):
                os.remove("worker_lock.txt")
        except Exception:
            pass
