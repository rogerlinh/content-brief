from __future__ import annotations

import os
from typing import Mapping, Sequence

KEY_NAMES = (
    "OPENAI_API_KEY",
    "SERPER_API_KEY",
)

_PLACEHOLDER_MARKERS = (
    "YOUR_",
    "PLACEHOLDER",
    "_KEY_HERE",
    "_TOKEN_HERE",
    "_SECRET_HERE",
)


def is_real_api_key(value: str, name: str) -> bool:
    if not value:
        return False
    val = str(value).strip()
    if not val:
        return False
    if any(marker in val for marker in _PLACEHOLDER_MARKERS):
        return False
    return True


def _collect_named_values(mapping: Mapping[str, str] | None) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in KEY_NAMES:
        values[key] = str((mapping or {}).get(key, "") or "")
    return values


def collect_runtime_api_key_sources(
    *,
    session_keys: Mapping[str, str] | None = None,
    secrets_keys: Mapping[str, str] | None = None,
    env_keys: Mapping[str, str] | None = None,
) -> list[tuple[str, dict[str, str]]]:
    ordered: list[tuple[str, dict[str, str]]] = []
    st = None

    if session_keys is None or secrets_keys is None:
        try:
            import streamlit as _st

            st = _st
        except Exception:
            st = None

    if session_keys is None:
        session_keys = {}
        if st is not None:
            try:
                session_keys = dict(st.session_state.get("api_keys", {}) or {})
            except Exception:
                session_keys = {}

    if secrets_keys is None:
        secrets_keys = {}
        if st is not None:
            try:
                secrets_keys = {key: st.secrets.get(key, "") for key in KEY_NAMES}
            except Exception:
                secrets_keys = {}

    if env_keys is None:
        env_keys = {key: os.environ.get(key, "") for key in KEY_NAMES}

    ordered.append(("session_state", _collect_named_values(session_keys)))
    ordered.append(("st.secrets", _collect_named_values(secrets_keys)))
    ordered.append(("process_env", _collect_named_values(env_keys)))
    return ordered


def resolve_api_keys(
    source_maps: Sequence[tuple[str, Mapping[str, str]]],
) -> tuple[dict[str, str], dict[str, str]]:
    resolved: dict[str, str] = {}
    sources: dict[str, str] = {}

    for source_name, mapping in source_maps:
        if not mapping:
            continue
        for key in KEY_NAMES:
            if key in resolved:
                continue
            value = mapping.get(key, "")
            if is_real_api_key(value, key):
                resolved[key] = str(value).strip()
                sources[key] = source_name

    return resolved, sources


def snapshot_api_keys(
    source_maps: Sequence[tuple[str, Mapping[str, str]]],
) -> dict[str, dict[str, str]]:
    snapshot: dict[str, dict[str, str]] = {}
    for source_name, mapping in source_maps:
        entries: dict[str, str] = {}
        for key in KEY_NAMES:
            value = mapping.get(key, "") if mapping else ""
            if value:
                val = str(value).strip()
                entries[key] = val[:12] + "..." if len(val) > 12 else val
            else:
                entries[key] = "(empty)"
        snapshot[source_name] = entries
    return snapshot


def apply_resolved_api_keys(
    resolved: Mapping[str, str],
    sources: Mapping[str, str] | None = None,
    *,
    config_module=None,
    llm_config: dict | None = None,
) -> dict:
    source_map = dict(sources or {})
    debug = {
        "resolved_api_keys": {},
        "resolved_api_key_sources": source_map,
        "llm_config_updated": False,
        "llm_config_key": "(none)",
        "openai_source": source_map.get("OPENAI_API_KEY", "missing"),
        "serper_source": source_map.get("SERPER_API_KEY", "missing"),
    }

    for name in KEY_NAMES:
        value = resolved.get(name, "")
        if not is_real_api_key(value, name):
            continue
        clean = str(value).strip()
        os.environ[name] = clean
        debug["resolved_api_keys"][name] = clean[:12] + "..." if len(clean) > 12 else clean

    if config_module is not None:
        try:
            serper_val = resolved.get("SERPER_API_KEY", "")
            if is_real_api_key(serper_val, "SERPER_API_KEY"):
                config_module.SERPER_API_KEY = str(serper_val).strip()

            openai_val = resolved.get("OPENAI_API_KEY", "")
            if is_real_api_key(openai_val, "OPENAI_API_KEY") and llm_config is not None:
                llm_config["api_key"] = str(openai_val).strip()
                debug["llm_config_updated"] = True
                debug["llm_config_key"] = str(openai_val).strip()[:12] + "..."
        except Exception:
            pass

    return debug
