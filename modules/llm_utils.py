# -*- coding: utf-8 -*-
"""
modules/llm_utils.py — Phase 2.3 Refactor

Shared LLM utilities:
- call_llm_with_retry() : exponential backoff retry wrapper
- call_llm()            : simple non-retry wrapper (backward compat)
- LLM_DEFAULTS          : unified LLM settings dict

All LLM calls in the pipeline MUST use these helpers.
This replaces ~25 hardcoded temperature/max_tokens/timeout scattered
across content_brief_builder.py, koray_analyzer.py, etc.

Usage:
    from modules.llm_utils import call_llm_with_retry, LLM_DEFAULTS
    result = call_llm_with_retry(
        client=openai_client,
        model="gpt-4o-mini",
        messages=[...],
        temperature=LLM_DEFAULTS["temperature_outline"],
        max_tokens=LLM_DEFAULTS["max_tokens_outline"],
        timeout=LLM_DEFAULTS["timeout"],
    )
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
#  Unified LLM settings (consolidated from modules/constants.py)
# ─────────────────────────────────────────────────────────────────
LLM_DEFAULTS = {
    # Temperature
    "temperature_outline": 0.4,   # Agent 1 (Outline Synthesizer)
    "temperature_seo":     0.3,   # Agent 2 (Semantic Enforcer)
    "temperature_micro":  0.4,   # Agent 3 (Micro-Briefing)
    # Max tokens
    "max_tokens_outline": 2000,
    "max_tokens_seo":     2500,
    "max_tokens_micro":   4000,
    "max_tokens_koray":   1000,  # Koray analyzer helpers
    # Timeout
    "timeout":             60,
    "timeout_long":        120,   # For large micro-briefing calls
    # Retry
    "max_retries":         3,
    "base_delay":          2.0,   # seconds, exponential backoff
}

# ─────────────────────────────────────────────────────────────────
#  Retry-aware LLM caller
# ─────────────────────────────────────────────────────────────────

class LLMRetryExhausted(Exception):
    """Raised when all retry attempts are exhausted."""
    pass


class LLMAPIError(Exception):
    """Raised when LLM returns a non-retryable API error."""
    pass


def _is_retryable_error(exception: Exception) -> bool:
    """Check if an exception is a retryable LLM API error."""
    err_str = str(exception).lower()
    retryable_keywords = [
        "rate limit",
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "connection",
        "temporarily unavailable",
    ]
    return any(kw in err_str for kw in retryable_keywords)


def call_llm_with_retry(
    client,
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 1500,
    timeout: int = 60,
    max_retries: int = LLM_DEFAULTS["max_retries"],
    base_delay: float = LLM_DEFAULTS["base_delay"],
) -> str:
    """
    Gọi LLM với exponential backoff retry.

    Args:
        client:      OpenAI client instance
        model:       Model name (e.g. "gpt-4o-mini")
        messages:    List of {"role": ..., "content": ...} dicts
        temperature: Sampling temperature
        max_tokens:  Max tokens to generate
        timeout:     Request timeout in seconds
        max_retries: Số lần retry tối đa
        base_delay:  Delay ban đầu (exponential: delay * 2^attempt)

    Returns:
        LLM response text, stripped.

    Raises:
        LLMRetryExhausted: Khi đã retry hết mà vẫn lỗi.
        LLMAPIError: Khi lỗi không phải retryable (auth, model not found, etc.)
    """
    last_exception: Optional[Exception] = None

    for attempt in range(max_retries + 1):  # +1 = initial attempt
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            content = response.choices[0].message.content
            if content is None:
                logger.warning("[LLM] Response content is None, treating as empty string.")
                return ""
            return content.strip()

        except Exception as exc:
            last_exception = exc
            err_type = type(exc).__name__

            if not _is_retryable_error(exc):
                # Non-retryable: auth failure, model not found, invalid request
                logger.error("[LLM] Non-retryable error (%s): %s", err_type, exc)
                raise LLMAPIError(f"{err_type}: {exc}") from exc

            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "[LLM] Retryable error (%s) on attempt %d/%d. "
                    "Waiting %.1fs before retry: %s",
                    err_type, attempt + 1, max_retries + 1, delay, exc,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "[LLM] All %d retries exhausted. Last error: %s",
                    max_retries + 1, exc,
                )

    # Should not reach here, but just in case
    raise LLMRetryExhausted(
        f"LLM call failed after {max_retries + 1} attempts. Last error: {last_exception}"
    ) from last_exception


def call_llm(
    client,
    model: str,
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 1500,
    timeout: int = 60,
) -> str:
    """
    Simple LLM call WITHOUT retry (backward compatibility wrapper).

    Prefer call_llm_with_retry() for production pipeline calls.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return call_llm_with_retry(
            client=client,
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=0,  # No retry for simple wrapper
        )
    except (LLMRetryExhausted, LLMAPIError) as exc:
        logger.warning("[LLM] call_llm failed (returning empty string): %s", exc)
        return ""


# ─────────────────────────────────────────────────────────────────
#  Convenience wrappers for each agent type
# ─────────────────────────────────────────────────────────────────

def call_llm_outline(client, model: str, messages: list[dict]) -> str:
    """Gọi LLM cho Agent 1 (Outline Synthesizer) — temperature=0.4, tokens=2000."""
    return call_llm_with_retry(
        client=client,
        model=model,
        messages=messages,
        temperature=LLM_DEFAULTS["temperature_outline"],
        max_tokens=LLM_DEFAULTS["max_tokens_outline"],
        timeout=LLM_DEFAULTS["timeout"],
    )


def call_llm_seo(client, model: str, messages: list[dict]) -> str:
    """Gọi LLM cho Agent 2 (Semantic Enforcer) — temperature=0.3, tokens=2500."""
    return call_llm_with_retry(
        client=client,
        model=model,
        messages=messages,
        temperature=LLM_DEFAULTS["temperature_seo"],
        max_tokens=LLM_DEFAULTS["max_tokens_seo"],
        timeout=LLM_DEFAULTS["timeout"],
    )


def call_llm_micro(client, model: str, messages: list[dict]) -> str:
    """Gọi LLM cho Agent 3 (Micro-Briefing) — temperature=0.4, tokens=4000."""
    return call_llm_with_retry(
        client=client,
        model=model,
        messages=messages,
        temperature=LLM_DEFAULTS["temperature_micro"],
        max_tokens=LLM_DEFAULTS["max_tokens_micro"],
        timeout=LLM_DEFAULTS["timeout_long"],
    )


def call_llm_koray(client, model: str, messages: list[dict], max_tokens: int = 1000) -> str:
    """Gọi LLM cho Koray analyzer helpers — temperature=0.3, configurable tokens."""
    return call_llm_with_retry(
        client=client,
        model=model,
        messages=messages,
        temperature=LLM_DEFAULTS["temperature_seo"],  # 0.3 same as SEO agent
        max_tokens=max_tokens,
        timeout=LLM_DEFAULTS["timeout"],
    )
