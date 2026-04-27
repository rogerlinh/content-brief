import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.content_brief_builder import _agent_micro_briefing_writer


@patch("modules.content_brief_builder.openai")
def test_h3_prompt_injection(mock_openai):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "[]"
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai.OpenAI.return_value = mock_client

    headings = [
        {"level": "H2", "text": "Dac diem cua thep cuon"},
        {"level": "H3", "text": "Thep cuon ma kem"},
        {"level": "H3", "text": "Thep cuon den"},
    ]

    _agent_micro_briefing_writer(
        topic="So sanh thep",
        entity="thep cuon",
        intent="vs",
        niche="construction",
        methodology_prompt="abc",
        headings=headings,
    )

    call_args = mock_client.chat.completions.create.call_args
    if call_args:
        messages = call_args[1].get("messages", [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")

        print("Test 1: Does the strict H3 listing rule exist in the System Prompt?")
        legacy_rule = "MỤC NÀY BẮT BUỘC PHẢI DÙNG ĐÚNG FORMAT NÀY"
        new_rule = "Information gain should explicitly mention H3 coverage"
        if legacy_rule in system_msg or new_rule in system_msg:
            print("- PASS: Strict Formatting Rule is present.")
        else:
            print("- FAIL: Not found in rule block.")

        print("\nTest 2: Does the strict format example exist in the json example block?")
        legacy_format = "DÙNG FORMAT: 'Các H3 trong phần này bao gồm"
        new_format = "FORMAT" in system_msg and "H3 1" in system_msg and "H3 2" in system_msg
        if legacy_format in system_msg or new_format:
            print("- PASS: JSON structure example enforces H3 list.")
        else:
            print("- FAIL: Not found in example block.")


if __name__ == "__main__":
    test_h3_prompt_injection()
