"""
Precision/recall evaluation harness for PII detection (issue A1).

Builds a small synthetic, labeled DOCX corpus at test time (see
tests/pii_eval/corpus.py and tests/pii_eval/labels.json -- generator code and
JSON labels only; CI's hygiene job forbids checked-in .docx/.doc/.pdf/.dmg
files), runs it through the rules-only pipeline (no Ollama required, so this
runs in every CI job -- see the "smoke" job in .github/workflows/ci.yml), and
asserts per-entity-type precision/recall against regression floors.

This closes the gap the survey flagged: previously, precision/recall metrics
existed only in manual, Ollama-dependent tooling (tests/benchmark/model_benchmark.py,
tests/scripts/score_answer_key_matrix.py) that isn't wired into pytest/CI and
doesn't break results out per entity type. This module is the automated,
CI-gated counterpart; see docs/DEVELOPER_GUIDE.md for how to run the same
corpus through the full LLM-backed pipeline locally via
tests/pii_eval/run_eval.py.
"""

import json

import pytest

try:
    from marcut import pipeline
    IMPORTS_SUCCESS = True
except Exception:
    IMPORTS_SUCCESS = False

from tests.pii_eval.corpus import DOCX_AVAILABLE, build_corpus_docx, load_expected_entities
from tests.pii_eval.scoring import format_score_table, score_entities

# Regression floors, not aspirational targets. This corpus is small and fully
# deterministic under rules-only mode (no LLM sampling involved), so today's
# rules engine clears every entity type at 1.0 precision/recall; the floor
# below leaves room for legitimate future corpus growth without making the
# gate flaky, while still catching a real detection regression.
MIN_PRECISION = 0.85
MIN_RECALL = 0.85


@pytest.mark.skipif(
    not (DOCX_AVAILABLE and IMPORTS_SUCCESS),
    reason="python-docx or marcut not available",
)
def test_rules_only_precision_recall_per_entity_type(tmp_path):
    input_path = tmp_path / "pii_eval_input.docx"
    output_path = tmp_path / "pii_eval_output.docx"
    report_path = tmp_path / "pii_eval_report.json"

    build_corpus_docx(str(input_path))

    code, _timings = pipeline.run_redaction(
        str(input_path),
        str(output_path),
        str(report_path),
        mode="rules",
        model_id="rules",
        chunk_tokens=800,
        overlap=80,
        temperature=0.1,
        seed=42,
        debug=False,
    )
    assert code == 0
    assert report_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    predicted = report.get("spans", [])

    expected = load_expected_entities()
    results = score_entities(expected, predicted)
    print("\n" + format_score_table(results))

    failures = []
    for label in sorted({e["label"] for e in expected}):
        r = results.get(label, {"precision": 0.0, "recall": 0.0})
        if r["recall"] < MIN_RECALL:
            failures.append(f"{label}: recall {r['recall']:.2f} < {MIN_RECALL}")
        if r["precision"] < MIN_PRECISION:
            failures.append(f"{label}: precision {r['precision']:.2f} < {MIN_PRECISION}")

    assert not failures, "Precision/recall regression:\n" + "\n".join(failures)
