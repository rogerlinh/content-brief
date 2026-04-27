from __future__ import annotations

import os

from modules.runtime_keys import apply_resolved_api_keys


def clean_env_value(value: str) -> str:
    return str(value or "").strip()


def update_env_file(env_path: str, updates: dict[str, str]) -> None:
    current: dict[str, str] = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as file:
            for raw_line in file.read().splitlines():
                if "=" not in raw_line or raw_line.strip().startswith("#"):
                    continue
                key, value = raw_line.split("=", 1)
                current[key.strip()] = value

    for key, value in updates.items():
        if value:
            current[key] = value.strip()

    with open(env_path, "w", encoding="utf-8") as file:
        for key, value in current.items():
            file.write(f"{key}={value}\n")


def save_api_keys(*, env_path: str, serper_key: str, openai_key: str) -> str:
    updates: dict[str, str] = {}
    for key, value in {
        "SERPER_API_KEY": serper_key,
        "OPENAI_API_KEY": openai_key,
    }.items():
        cleaned = clean_env_value(value)
        if cleaned:
            updates[key] = cleaned

    if not updates:
        return "Không có key mới để lưu."

    try:
        import config as _config
        from config import LLM_CONFIG

        apply_resolved_api_keys(
            updates,
            {key: "settings_form" for key in updates},
            config_module=_config,
            llm_config=LLM_CONFIG,
        )
    except Exception:
        pass

    update_env_file(env_path, updates)
    for key, value in updates.items():
        os.environ[key] = value

    try:
        import streamlit as st

        if "api_keys" not in st.session_state:
            st.session_state["api_keys"] = {}
        st.session_state["api_keys"].update(updates)
    except Exception:
        pass

    return "Đã lưu API keys (.env + session)."
