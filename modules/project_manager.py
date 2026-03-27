# -*- coding: utf-8 -*-
"""
modules/project_manager.py - Phase 33: Source Context Management.

Quản lý Project (Brand Profile) dùng SQLite local.
Mỗi Project lưu Source Context của 1 brand và tự động inject
vào tất cả LLM prompts khi pipeline chạy.
"""

import sqlite3
import os
import logging
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# SQLite DB nằm ở thư mục gốc của project
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "projects.db"
)


@dataclass
class Project:
    """Brand Profile dùng để inject Source Context vào LLM prompts."""
    id: int = 0
    name: str = ""                   # Tên project (VD: "ThepTranLong - Hanoi")
    brand_name: str = ""             # Tên brand (VD: "Thép Trần Long")
    domain: str = ""                 # Domain (VD: "theptranlong.vn")
    company_full_name: str = ""      # Tên công ty đầy đủ
    industry: str = ""               # Ngành (VD: "Phân phối thép xây dựng")
    main_products: str = ""          # Sản phẩm chính (textarea)
    usp: str = ""                    # USP / Lợi thế cạnh tranh
    target_customers: str = ""       # Khách hàng mục tiêu
    competitor_brands: str = ""      # Brand đối thủ KHÔNG đặt H2 Main
    tone: str = ""                   # Tone & giọng văn
    technical_standards: str = ""    # Tiêu chuẩn kỹ thuật (ASTM, JIS, TCVN...)
    geo_keywords: str = ""           # GEO Keywords (Hà Nội, Miền Bắc...)
    hotline: str = ""                # Hotline / Zalo
    email: str = ""                  # Email
    address: str = ""                # Địa chỉ trụ sở
    warehouse: str = ""              # Kho / Chi nhánh
    topical_map_csv: str = ""         # Đường dẫn topics.csv riêng của project
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = False          # Project đang được chọn


class ProjectManager:
    """CRUD operations cho Project table trong SQLite."""

    CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            brand_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            company_full_name TEXT DEFAULT '',
            industry TEXT DEFAULT '',
            main_products TEXT DEFAULT '',
            usp TEXT DEFAULT '',
            target_customers TEXT DEFAULT '',
            competitor_brands TEXT DEFAULT '',
            tone TEXT DEFAULT '',
            technical_standards TEXT DEFAULT '',
            geo_keywords TEXT DEFAULT '',
            hotline TEXT DEFAULT '',
            email TEXT DEFAULT '',
            address TEXT DEFAULT '',
            warehouse TEXT DEFAULT '',
            topical_map_csv TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 0
        )
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        """Tạo kết nối SQLite với row_factory để tránh lỗi lệch index cột."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Khởi tạo bảng projects nếu chưa có."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(self.CREATE_TABLE_SQL)
                # Migration: thêm cột topical_map_csv nếu chưa có
                try:
                    conn.execute(
                        "ALTER TABLE projects ADD COLUMN topical_map_csv TEXT DEFAULT ''"
                    )
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Cột đã tồn tại
            logger.debug("[PM] SQLite DB initialized at %s", self.db_path)
        except Exception as e:
            logger.error("[PM] Lỗi khởi tạo DB: %s", e)

    def _normalize_domain(self, domain: str) -> str:
        """Chuẩn hóa domain để không lưu cả protocol/path trong DB."""
        if not domain:
            return ""
        cleaned = str(domain).strip()
        cleaned = cleaned.replace("https://", "").replace("http://", "")
        cleaned = cleaned.split("/", 1)[0].strip()
        return cleaned

    def _row_to_project(self, row) -> Project:
        """Convert SQLite row thành Project dataclass."""
        return Project(
            id=row["id"],
            name=row["name"] or "",
            brand_name=row["brand_name"] or "",
            domain=self._normalize_domain(row["domain"] or ""),
            company_full_name=row["company_full_name"] or "",
            industry=row["industry"] or "",
            main_products=row["main_products"] or "",
            usp=row["usp"] or "",
            target_customers=row["target_customers"] or "",
            competitor_brands=row["competitor_brands"] or "",
            tone=row["tone"] or "",
            technical_standards=row["technical_standards"] or "",
            geo_keywords=row["geo_keywords"] or "",
            hotline=row["hotline"] or "",
            email=row["email"] or "",
            address=row["address"] or "",
            warehouse=row["warehouse"] or "",
            topical_map_csv=row["topical_map_csv"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            is_active=bool(row["is_active"]),
        )

    def create(self, data: dict) -> Optional[Project]:
        """Tạo project mới. Trả về Project vừa tạo."""
        now = datetime.now().isoformat()
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO projects (
                        name, brand_name, domain, company_full_name, industry,
                        main_products, usp, target_customers, competitor_brands,
                        tone, technical_standards, geo_keywords, hotline, email,
                        address, warehouse, topical_map_csv,
                        created_at, updated_at, is_active
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                    """,
                    (
                        data.get("name", ""),
                        data.get("brand_name", ""),
                        self._normalize_domain(data.get("domain", "")),
                        data.get("company_full_name", ""),
                        data.get("industry", ""),
                        data.get("main_products", ""),
                        data.get("usp", ""),
                        data.get("target_customers", ""),
                        data.get("competitor_brands", ""),
                        data.get("tone", ""),
                        data.get("technical_standards", ""),
                        data.get("geo_keywords", ""),
                        data.get("hotline", ""),
                        data.get("email", ""),
                        data.get("address", ""),
                        data.get("warehouse", ""),
                        data.get("topical_map_csv", ""),
                        now, now,
                    ),
                )
                conn.commit()
                return self.get_by_id(cur.lastrowid)
        except Exception as e:
            logger.error("[PM] Lỗi tạo project: %s", e)
            return None

    def get_all(self) -> List[Project]:
        """Lấy tất cả projects."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM projects ORDER BY is_active DESC, id DESC"
                ).fetchall()
            return [self._row_to_project(r) for r in rows]
        except Exception as e:
            logger.error("[PM] Lỗi get_all: %s", e)
            return []

    def get_by_id(self, project_id: int) -> Optional[Project]:
        """Lấy project theo ID."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
            return self._row_to_project(row) if row else None
        except Exception as e:
            logger.error("[PM] Lỗi get_by_id: %s", e)
            return None

    def get_active(self) -> Optional[Project]:
        """Lấy project đang active (is_active=1)."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM projects WHERE is_active=1 LIMIT 1"
                ).fetchone()
            return self._row_to_project(row) if row else None
        except Exception as e:
            logger.error("[PM] Lỗi get_active: %s", e)
            return None

    def set_active(self, project_id: int):
        """Set project active, bỏ active tất cả project khác."""
        try:
            with self._connect() as conn:
                conn.execute("UPDATE projects SET is_active=0")
                conn.execute(
                    "UPDATE projects SET is_active=1, updated_at=? WHERE id=?",
                    (datetime.now().isoformat(), project_id),
                )
                conn.commit()
            logger.info("[PM] Set active project_id=%d", project_id)
        except Exception as e:
            logger.error("[PM] Lỗi set_active: %s", e)

    def update(self, project_id: int, data: dict) -> Optional[Project]:
        """Cập nhật project."""
        now = datetime.now().isoformat()
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE projects SET
                        name=?, brand_name=?, domain=?, company_full_name=?,
                        industry=?, main_products=?, usp=?, target_customers=?,
                        competitor_brands=?, tone=?, technical_standards=?,
                        geo_keywords=?, hotline=?, email=?, address=?,
                        warehouse=?, topical_map_csv=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        data.get("name", ""),
                        data.get("brand_name", ""),
                        self._normalize_domain(data.get("domain", "")),
                        data.get("company_full_name", ""),
                        data.get("industry", ""),
                        data.get("main_products", ""),
                        data.get("usp", ""),
                        data.get("target_customers", ""),
                        data.get("competitor_brands", ""),
                        data.get("tone", ""),
                        data.get("technical_standards", ""),
                        data.get("geo_keywords", ""),
                        data.get("hotline", ""),
                        data.get("email", ""),
                        data.get("address", ""),
                        data.get("warehouse", ""),
                        data.get("topical_map_csv", ""),
                        now,
                        project_id,
                    ),
                )
                conn.commit()
            return self.get_by_id(project_id)
        except Exception as e:
            logger.error("[PM] Lỗi update: %s", e)
            return None

    def delete(self, project_id: int):
        """Xóa project."""
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
                conn.commit()
            logger.info("[PM] Đã xóa project_id=%d", project_id)
        except Exception as e:
            logger.error("[PM] Lỗi delete: %s", e)

    def _normalize_phone(self, phone: str) -> str:
        """Chuẩn hóa số điện thoại Việt Nam: +84 → 0, loại bỏ khoảng trắng."""
        import re
        if not phone:
            return ""
        p = phone.strip()
        # +84xxx → 0xxx
        p = re.sub(r'^\+84', '0', p)
        # Loại bỏ khoảng trắng, dấu ngoặc thừa
        p = re.sub(r'[\s\(\)\.-]', '', p)
        # Đảm bảo bắt đầu bằng 0
        if not p.startswith('0') and len(p) >= 9:
            p = '0' + p
        return p

    def to_source_context_string(self, project: "Project") -> str:
        """
        Convert Project thành chuỗi Source Context để inject vào LLM prompt.
        Format này được inject vào đầu mọi system prompt của Agent1/2/3.
        """
        if not project:
            return ""

        competitor_note = (
            f"TUYỆT ĐỐI KHÔNG đặt các brand sau làm H2 độc lập trong [MAIN]: {project.competitor_brands}"
            if project.competitor_brands
            else "KHÔNG đặt tên brand đối thủ làm H2 độc lập trong [MAIN]"
        )

        nap_lines = [f"📞 Hotline/Zalo: {self._normalize_phone(project.hotline)}" if project.hotline else ""]
        if project.email:
            nap_lines.append(f"✉️  Email: {project.email}")
        if project.address:
            nap_lines.append(f"📍 Địa chỉ: {project.address}")
        if project.warehouse:
            nap_lines.append(f"🏭 Kho: {project.warehouse}")
        if project.domain:
            nap_lines.append(f"🌐 Website: https://{project.domain}/")
        nap_block = "\n".join(line for line in nap_lines if line)

        # Geo keyword đầu tiên cho ví dụ đoạn mẫu
        first_geo = (project.geo_keywords or "Việt Nam").split(",")[0].strip()

        source_ctx = f"""
## SOURCE CONTEXT — {project.domain.upper()} (ĐỌC KỸ VÀ ÁP DỤNG VÀO MỌI OUTPUT)

```
Brand:               {project.brand_name}
Domain:              {project.domain}
"""
        if project.company_full_name:
            source_ctx += f"Tên công ty:         {project.company_full_name}\n"

        source_ctx += f"""Ngành / Lĩnh vực:   {project.industry}
Sản phẩm chính:     {project.main_products}
USP / Lợi thế:      {project.usp}
Khách hàng:         {project.target_customers}
Tone & giọng văn:   {project.tone}
Tiêu chuẩn KT:      {project.technical_standards or "theo tiêu chuẩn ngành"}
GEO Keywords:       {project.geo_keywords or "Việt Nam"}
```

NAP chuẩn (bắt buộc chèn cuối bài trong [SUPP]):
{nap_block}

Đoạn Source Context mẫu:
"{project.brand_name} cung cấp {{TÊN SẢN PHẨM}} {{QUY CÁCH}} tại {first_geo}. {project.usp}. Liên hệ: {project.hotline}."

Quy tắc brand đối thủ: {competitor_note}
"""
        # Phase 1.3 fix: f-string escapes {{...}} as literal braces.
        # Build the sample sentence correctly (not via f-string double-brace).
        product_ph = "{TÊN SẢN PHẨM}"
        spec_ph = "{QUY CÁCH}"
        sample_sentence = (
            project.brand_name + " cung cấp " + product_ph + " " + spec_ph
            + " tại " + first_geo + ". " + project.usp + ". Liên hệ: " + project.hotline + "."
        )
        # Replace the double-brace literal with the correctly-built sentence
        source_ctx = source_ctx.replace(
            f'"{project.brand_name} cung cấp {{TÊN SẢN PHẨM}} {{QUY CÁCH}} '
            f'tại {first_geo}. {project.usp}. Liên hệ: {project.hotline}."',
            f'"{sample_sentence}"',
        )
        return source_ctx
