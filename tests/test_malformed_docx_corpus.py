"""
Malformed-DOCX corpus tests (issue #50 / B8).

Feeds a generated corpus of broken DOCX inputs (truncated zip, bad
content-types, mismatched relationship targets, undeclared XML entities --
see tests/malformed_docx_corpus.py) through both `DocxMap.load_accepting_revisions`
and the real `run_redaction()` pipeline entry point, and asserts the pipeline
fails cleanly:

  - a specific, classified error (`RedactionError` with error_code
    "DOC_LOAD_FAILED"), surfaced to the caller as run_redaction()'s documented
    (code, timings) contract rather than a raised exception or a crash
    (pipeline.py's outer try/except always converts a RedactionError into a
    non-zero return code plus a "status": "error" report -- see
    _write_failure_report),
  - no partial/misleading output DOCX ever appears at `output_path`,
  - no leftover `_sibling_temp_path()`-style staging artifacts are left behind
    in the output directory,
  - and it happens fast (bounded wall-clock time), i.e. it never hangs.

Nothing here is a committed .docx -- the corpus is generated at test time;
ci.yml's hygiene step forbids committing .docx/.doc/.pdf/.dmg files.
"""

from __future__ import annotations

import glob
import json
import time

import pytest

from marcut.docx_io import DocxMap
from marcut.pipeline import RedactionError, run_redaction

from tests.malformed_docx_corpus import CORRUPTORS, generate_corpus

# A load failure never reaches the network/LLM, so it should resolve almost
# instantly; this is a generous ceiling that only trips if something is
# actually stuck (e.g. an XML-parsing infinite loop), not a tight perf budget.
MAX_FAIL_SECONDS = 10.0


@pytest.fixture(params=sorted(CORRUPTORS))
def corrupt_variant(request, tmp_path):
    """(variant_name, path_to_corrupted_docx) for each entry in the malformed corpus."""
    corpus = generate_corpus()
    name = request.param
    path = tmp_path / f"{name}.docx"
    path.write_bytes(corpus[name])
    return name, path


class TestMalformedDocxCorpusLoad:
    """DocxMap-level: every variant must fail to load, never silently succeed."""

    def test_variant_fails_to_load(self, corrupt_variant):
        name, path = corrupt_variant
        with pytest.raises(Exception):
            DocxMap.load_accepting_revisions(str(path))

    def test_variant_never_hangs_on_load(self, corrupt_variant):
        name, path = corrupt_variant
        start = time.perf_counter()
        with pytest.raises(Exception):
            DocxMap.load_accepting_revisions(str(path))
        elapsed = time.perf_counter() - start
        assert elapsed < MAX_FAIL_SECONDS, f"{name}: DocxMap.load took {elapsed:.2f}s -- looks hung"


class TestMalformedDocxCorpusPipeline:
    """Full run_redaction(): must fail cleanly, fast, with no partial artifacts."""

    def test_pipeline_fails_cleanly_with_no_partial_artifacts(self, corrupt_variant, tmp_path):
        name, input_path = corrupt_variant
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"

        start = time.perf_counter()
        code, _timings = run_redaction(
            str(input_path), str(output_path), str(report_path),
            mode="rules", model_id="rules", chunk_tokens=250, overlap=50,
            temperature=0.0, seed=42, debug=False,
        )
        elapsed = time.perf_counter() - start

        assert code != 0, f"{name}: run_redaction must report failure, not success"
        assert elapsed < MAX_FAIL_SECONDS, f"{name}: pipeline took {elapsed:.2f}s to fail -- looks hung"

        # No partial/misleading output DOCX -- the redacted document is never
        # produced when the input never loaded in the first place.
        assert not output_path.exists(), f"{name}: output.docx must not exist after a load failure"

        # A minimal error report IS expected (by design, so the GUI/CLI can surface
        # context -- see _write_failure_report) but it must be explicitly an error
        # status, never a report that could be mistaken for a completed redaction.
        assert report_path.exists(), f"{name}: an error report should still be written for GUI/CLI context"
        report = json.loads(report_path.read_text())
        assert report["status"] == "error", f"{name}: report must be explicitly marked as an error"
        assert report["error_code"] == "DOC_LOAD_FAILED", (
            f"{name}: expected DOC_LOAD_FAILED, got {report.get('error_code')}"
        )

        # No leftover staging artifacts (`_sibling_temp_path()` writes files named
        # `.{stem}.<random>.tmp{ext}` in the output directory -- dot-prefixed, so a
        # plain report.json/output.docx never collides with this glob).
        leftover_temp = glob.glob(str(tmp_path / ".*"))
        assert leftover_temp == [], f"{name}: unexpected temp artifacts left behind: {leftover_temp}"

    def test_pipeline_never_raises_uncaught_exception(self, corrupt_variant, tmp_path):
        """run_redaction()'s documented contract is (code, timings), never a raised
        exception -- pipeline.py's outer try/except classifies every failure into a
        RedactionError and converts it to a return code (see run_redaction's final
        except clauses). A malformed-input corpus is exactly the kind of input that
        could slip past that classification if a new failure mode were introduced."""
        name, input_path = corrupt_variant
        output_path = tmp_path / "output2.docx"
        report_path = tmp_path / "report2.json"

        try:
            code, _timings = run_redaction(
                str(input_path), str(output_path), str(report_path),
                mode="rules", model_id="rules", chunk_tokens=250, overlap=50,
                temperature=0.0, seed=42, debug=False,
            )
        except RedactionError:
            pytest.fail(
                f"{name}: run_redaction() must not raise RedactionError to its caller -- "
                "it should catch and convert to a non-zero return code"
            )
        assert code != 0
