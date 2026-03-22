import traceback
import sys

try:
    import test_v21_prompts
    test_v21_prompts.main()
except Exception:
    with open("err.txt", "w") as f:
        traceback.print_exc(file=f)
