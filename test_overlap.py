import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'python'))

import time
from marcut.unified_redactor import run_unified_redaction

def run_test(overlap_size):
    start = time.time()
    res = run_unified_redaction(
        input_path="sample-files/loan-term-sheet.docx",
        output_path=f"sample-files/loan-term-sheet_ov{overlap_size}.docx",
        report_path=f"sample-files/loan-term-sheet_ov{overlap_size}.json",
        mode="enhanced",
        model="qwen3.5:9b",
        overlap=overlap_size,
        debug=True,
        llm_concurrency=3
    )
    return time.time() - start, res.get("entity_count", 0)

print("\n--- Testing Async Overlap 200 ---")
t200, e200 = run_test(200)
print(f"Async LLM Concurrency 3 | Overlap 200: {t200:.2f}s, Entities: {e200}")
