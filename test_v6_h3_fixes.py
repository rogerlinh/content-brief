import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from modules.content_brief_builder import _agent_micro_briefing_writer

@patch("modules.content_brief_builder.openai")
def test_h3_prompt_injection(mock_openai):
    # Setup mock to return a dummy response
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "[]" # Empty JSON array for test
    mock_client.chat.completions.create.return_value = mock_response
    mock_openai.OpenAI.return_value = mock_client
    
    headings = [
        {"level": "H2", "text": "Đặc điểm của thép cuộn"},
        {"level": "H3", "text": "Thép cuộn mạ kẽm"},
        {"level": "H3", "text": "Thép cuộn đen"},
    ]
    
    # Call the writer function
    _agent_micro_briefing_writer(
        topic="So sánh thép",
        entity="thép cuộn",
        intent="vs",
        niche="construction",
        methodology_prompt="abc",
        headings=headings,
    )
    
    # Assert that the chat API was called with the modified instructions
    call_args = mock_client.chat.completions.create.call_args
    if call_args:
        messages = call_args[1].get("messages", [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        
        print("Test 1: Does the strict H3 listing rule exist in the System Prompt?")
        expected_str = "MỤC NÀY BẮT BUỘC PHẢI DÙNG ĐÚNG FORMAT NÀY"
        if expected_str in system_msg:
            print("- PASS: Strict Formatting Rule is present.")
        else:
            print("- FAIL: Not found in rule block.")
            
        print("\nTest 2: Does the strict format example exist in the json example block?")
        expected_format = "DÙNG FORMAT: 'Các H3 trong phần này bao gồm"
        if expected_format in system_msg:
            print("- PASS: JSON structure example enforces H3 list.")
        else:
            print("- FAIL: Not found in example block.")

if __name__ == "__main__":
    test_h3_prompt_injection()
