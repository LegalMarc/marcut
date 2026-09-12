#!/usr/bin/env python3
"""
Standalone runner for the PII detection precision/recall harness (A1).

CI only ever exercises `--mode rules` (see tests/test_pii_eval_harness.py and
the "smoke" job in .github/workflows/ci.yml) because it requires no Ollama
install and is fully deterministic. This script additionally supports
`--mode llm`, which runs the *same* labeled corpus through the enhanced
two-pass LLM pipeline against a real local Ollama model -- useful for
comparing models/prompts, but intentionally not run in CI (it needs Ollama
running locally and is not deterministic run-to-run).

Usage:
    # Rules-only (same thing the CI gate runs; no Ollama needed)
    PYTHONPATH=src/python python3 -m tests.pii_eval.run_eval --mode rules

    # Full LLM-backed eval against a local Ollama model
    ollama serve &
    ollama pull qwen2.5:14b
    PYTHONPATH=src/python python3 -m tests.pii_eval.run_eval --mode llm --model qwen2.5:14b
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PYTHON = REPO_ROOT / "src" / "python"
if str(SRC_PYTHON) not in sys.path:
    sys.path.insert(0, str(SRC_PYTHON))

from tests.pii_eval.corpus import build_corpus_docx, load_expected_entities  # noqa: E402
from tests.pii_eval.scoring import score_entities, format_score_table  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["rules", "llm"], default="rules")
    parser.add_argument("--model", default="qwen2.5:14b", help="Ollama model id (--mode llm only)")
    parser.add_argument("--backend", default="ollama", choices=["ollama", "llama_cpp"])
    parser.add_argument("--llama-gguf", default="", help="Path to a GGUF file (--backend llama_cpp)")
    parser.add_argument("--keep-docx", help="Optional path to save the generated corpus .docx for inspection")
    parser.add_argument("--min-precision", type=float, default=0.85)
    parser.add_argument("--min-recall", type=float, default=0.85)
    args = parser.parse_args()

    from marcut import pipeline

    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / "pii_eval_input.docx"
        output_path = Path(tmp) / "pii_eval_output.docx"
        report_path = Path(tmp) / "pii_eval_report.json"

        build_corpus_docx(str(input_path))
        if args.keep_docx:
            Path(args.keep_docx).write_bytes(input_path.read_bytes())
            print(f"Saved corpus document to: {args.keep_docx}")

        mode = "rules" if args.mode == "rules" else "rules_override"
        print(f"Running pipeline in mode={mode!r} (backend={args.backend if mode != 'rules' else 'n/a'})...")
        code, _timings = pipeline.run_redaction(
            str(input_path),
            str(output_path),
            str(report_path),
            mode=mode,
            model_id=args.model if mode != "rules" else "rules",
            chunk_tokens=800,
            overlap=80,
            temperature=0.1,
            seed=42,
            debug=False,
            backend=args.backend,
            llama_gguf=args.llama_gguf,
        )
        if code != 0:
            print(f"Pipeline returned non-zero exit code: {code}", file=sys.stderr)
            return code

        report = json.loads(report_path.read_text(encoding="utf-8"))

    predicted = report.get("spans", [])
    expected = load_expected_entities()
    results = score_entities(expected, predicted)
    print()
    print(format_score_table(results))

    failures = []
    for label in sorted({e["label"] for e in expected}):
        r = results.get(label, {"precision": 0.0, "recall": 0.0})
        if r["recall"] < args.min_recall:
            failures.append(f"{label}: recall {r['recall']:.2f} < {args.min_recall}")
        if r["precision"] < args.min_precision:
            failures.append(f"{label}: precision {r['precision']:.2f} < {args.min_precision}")

    if failures:
        print("\nBelow threshold:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll entity types at or above threshold.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
