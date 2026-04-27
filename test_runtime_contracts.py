from __future__ import annotations

import json
import sys
import types
from pathlib import Path


def test_generate_content_brief_uses_degraded_serp_payload_on_serp_exception(monkeypatch, tmp_path: Path) -> None:
    import main_generator

    captured: dict[str, object] = {}

    monkeypatch.setattr(main_generator, "_llm_ready_reason", lambda: "")

    def fake_analyze_serp(topic: str):
        raise RuntimeError("serper down")

    def fake_analyze_topic(topic: str, serp_data=None, competitor_data=None):
        captured["topic"] = topic
        captured["serp_data"] = serp_data
        captured["competitor_data"] = competitor_data
        return {
            "search_intent": "informational",
            "central_entity": topic,
            "related_topics": [],
            "suggested_questions": [],
            "entity_attributes": {},
            "target_user": "",
        }

    def fake_build_brief(*args, **kwargs):
        return {
            "heading_structure": [{"level": "H2", "text": "Khai niem co ban"}],
            "micro_briefing": [
                {
                    "h2": "[MAIN] Khai niem co ban",
                    "snippet": " ".join(["noi-dung"] * 85),
                    "bridge": "",
                }
            ],
            "title_tag": "Demo Title",
            "central_entity": "Demo Entity",
            "faq_questions": [],
        }

    monkeypatch.setattr(main_generator, "analyze_serp", fake_analyze_serp)
    monkeypatch.setattr(main_generator, "analyze_topic", fake_analyze_topic)
    monkeypatch.setattr(main_generator, "build_brief", fake_build_brief)
    monkeypatch.setattr(main_generator, "_fallback_prompt_context", lambda *a, **k: {"context_vectors": [{"question": "Q", "intent": "info"}], "contextual_structure": ["rule"]})
    monkeypatch.setattr(main_generator, "refine_paa_questions_for_project", lambda **kwargs: {"faq_questions": []})
    monkeypatch.setattr(main_generator, "export_to_markdown", lambda brief, output_dir: (str(Path(output_dir) / "brief.md"), "# p1", "# p2"))

    fake_article_writer = types.ModuleType("modules.article_writer")
    fake_article_writer.auto_detect_methodology = lambda intent, topic: "informational"
    fake_article_writer.get_methodology_prompt = lambda methodology: f"prompt:{methodology}"
    monkeypatch.setitem(sys.modules, "modules.article_writer", fake_article_writer)

    fake_intent = types.ModuleType("modules.intent")
    fake_intent.normalize_intent = lambda value: str(value or "").strip() or "informational"
    monkeypatch.setitem(sys.modules, "modules.intent", fake_intent)

    fake_koray = types.ModuleType("modules.koray_analyzer")
    fake_koray.generate_macro_context = lambda *a, **k: "macro context"
    fake_koray.generate_eav_table = lambda *a, **k: "| Entity | Attribute | Value |\n|---|---|---|\n| demo | dinh nghia | mo ta |\n"
    fake_koray.extract_main_supp_split = lambda headings: {"main": headings, "supp": []}
    fake_koray.generate_source_context_alignment = lambda brief, project: "aligned"
    fake_koray.calculate_quality_score = lambda brief, headings, project: "85/100"
    fake_koray.generate_fs_paa_map = lambda *a, **k: "| PAA Question | Vi tri | Format | FS Block |\n|---|---|---|---|\n"
    fake_koray.generate_outline_readiness_report = lambda brief, headings, project: {"summary": "ok"}
    fake_koray.generate_column_audit_report = lambda brief, project: "audit"
    monkeypatch.setitem(sys.modules, "modules.koray_analyzer", fake_koray)

    output_path = main_generator.generate_content_brief(
        topic="hang hoa phai sinh la gi",
        enable_serp=True,
        enable_network=False,
        enable_context=False,
        enable_linking=False,
        methodology="auto",
        output_dir=str(tmp_path),
        project=None,
    )

    assert output_path == str(tmp_path / "brief.md")
    serp_data = captured["serp_data"]
    competitor_data = captured["competitor_data"]

    assert isinstance(serp_data, dict)
    assert serp_data["status"] == "serp_failed"
    assert "serper down" in str(serp_data["error"])
    assert serp_data["serp_source"] == "Unavailable"
    assert serp_data["source_confidence"] == "none"

    assert isinstance(competitor_data, dict)
    assert competitor_data["status"] == "serp_failed"
    assert competitor_data["competitors"] == []
    assert competitor_data["information_gain"] == {}


def _install_fake_gsheet_modules(monkeypatch):
    calls: dict[str, object] = {}

    class FakeCredentials:
        @classmethod
        def from_service_account_info(cls, info, scopes=None):
            calls["info"] = dict(info)
            calls["scopes"] = list(scopes or [])
            return {"credentials": dict(info)}

    class FakeWorksheet:
        def row_values(self, row):
            return []

        def update(self, range_name=None, values=None):
            calls["updated"] = (range_name, values)

        def format(self, *args, **kwargs):
            calls["formatted"] = True

        def resize(self, *args, **kwargs):
            calls["resized"] = True

    class FakeSheet:
        title = "Fake Sheet"

        def __init__(self):
            self.sheet1 = FakeWorksheet()

    class FakeClient:
        def open_by_url(self, sheet_url):
            calls["sheet_url"] = sheet_url
            return FakeSheet()

    fake_gspread = types.ModuleType("gspread")
    fake_gspread.authorize = lambda creds: FakeClient()

    fake_google = types.ModuleType("google")
    fake_google_oauth2 = types.ModuleType("google.oauth2")
    fake_service_account = types.ModuleType("google.oauth2.service_account")
    fake_service_account.Credentials = FakeCredentials

    monkeypatch.setitem(sys.modules, "gspread", fake_gspread)
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_google_oauth2)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_service_account)
    return calls


def _valid_service_account_info(client_email: str) -> dict[str, str]:
    return {
        "type": "service_account",
        "project_id": "demo-project",
        "private_key_id": "key-id",
        "private_key": "-----BEGIN PRIVATE KEY-----\nQUJDRA==\n-----END PRIVATE KEY-----\n",
        "client_email": client_email,
        "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def test_gsheet_logger_prefers_creds_data_over_creds_path(monkeypatch) -> None:
    from modules.gsheet_logger import GSheetLogger

    calls = _install_fake_gsheet_modules(monkeypatch)
    monkeypatch.setattr(GSheetLogger, "_ensure_headers", lambda self: None)

    creds_data = _valid_service_account_info("memory@example.iam.gserviceaccount.com")
    logger = GSheetLogger(
        creds_data=creds_data,
        creds_path=r"Z:\does-not-exist.json",
        sheet_url="https://docs.google.com/spreadsheets/d/demo",
    )

    assert logger.connect() is True
    assert calls["info"]["client_email"] == "memory@example.iam.gserviceaccount.com"
    assert calls["sheet_url"] == "https://docs.google.com/spreadsheets/d/demo"


def test_gsheet_logger_uses_explicit_creds_path_when_no_creds_data(monkeypatch, tmp_path: Path) -> None:
    from modules.gsheet_logger import GSheetLogger

    calls = _install_fake_gsheet_modules(monkeypatch)
    monkeypatch.setattr(GSheetLogger, "_ensure_headers", lambda self: None)

    creds_path = tmp_path / "service-account.json"
    creds_path.write_text(
        json.dumps(_valid_service_account_info("file@example.iam.gserviceaccount.com")),
        encoding="utf-8",
    )

    logger = GSheetLogger(
        creds_data=None,
        creds_path=str(creds_path),
        sheet_url="https://docs.google.com/spreadsheets/d/demo",
    )

    assert logger.connect() is True
    assert calls["info"]["client_email"] == "file@example.iam.gserviceaccount.com"
