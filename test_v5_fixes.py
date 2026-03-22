import logging
from modules.topic_analyzer import analyze_topic

logging.basicConfig(level=logging.INFO, format="%(message)s")

def test_v5_fixes():
    test_cases = [
        "Thép thanh vằn là gì",
        "So sánh thép cuộn và thép vằn",
        "Cách chọn mua điện thoại Xiaomi tốt nhất"
    ]
    
    for topic in test_cases:
        print(f"\n{'='*60}")
        print(f"TESTING TOPIC: {topic}")
        print(f"{'='*60}")
        
        # 1. Topic Analysis
        analysis = analyze_topic(topic)
        print(f"\n[V5.7] Central Entity Extracted: '{analysis.get('central_entity')}'")
        
        # Mock some minimal data to bypass heavy API calls if possible,
        # but the builder needs complete data to run the agents.
        # Let's run the full build_brief
        try:
            # We don't have full serp_data/competitor_data here without running 
            # the full pipeline via main_generator.py, so running just build_brief 
            # might fail if we don't mock them.
            # Instead, let's just test analyze_topic output for now.
            pass
        except Exception as e:
            print(f"Error building brief: {e}")

if __name__ == "__main__":
    test_v5_fixes()
