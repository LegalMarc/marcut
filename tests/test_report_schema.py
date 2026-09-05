"""
Tests for report_schema.py -- pydantic models for the three on-disk report
shapes written by the redaction pipeline (audit report, scrub/metadata
report, failure report) and the validate-before-write wiring in report.py
and pipeline.py.

Covers issue #67's acceptance criteria:
- One model per shape, each rejecting a malformed dict before it can cross
  the write boundary.
- The failure report's message/technical_details stay free-form so the
  AI_PROCESSING_TIMEOUT deadline/timeout classifier keeps working.
"""
import pytest
from pydantic import ValidationError

from marcut.report_schema import AuditReport, ScrubReport, FailureReport


VALID_AUDIT = {
    "created_at": "2026-09-05T00:00:00Z",
    "input_sha256": "a" * 64,
    "model": "mock",
    "spans": [{"start": 0, "end": 4, "label": "NAME"}],
}

VALID_SCRUB = {
    "summary": {"total_cleaned": 0, "total_preserved": 0, "total_unchanged": 0},
    "groups": {},
}

VALID_FAILURE = {
    "status": "error",
    "input_file": "input.docx",
    "error_code": "AI_PROCESSING_TIMEOUT",
    "message": "AI processing timed out",
    "technical_details": "Model: mock, Error: processing deadline exceeded",
}


class TestAuditReportSchema:
    """Mirrors the dict built by report.write_report()."""

    def test_valid_shape_round_trips(self):
        model = AuditReport.model_validate(VALID_AUDIT)
        assert model.spans[0]["label"] == "NAME"

    def test_missing_required_field_rejected_before_write_boundary(self):
        """A malformed audit dict (missing 'spans') must be rejected by the
        model before it ever reaches write_json_file()."""
        bad = dict(VALID_AUDIT)
        del bad["spans"]
        with pytest.raises(ValidationError):
            AuditReport.model_validate(bad)

    def test_permissive_on_unknown_top_level_keys(self):
        """extra='allow': catch shape drift in known fields, don't reject
        today's valid reports just because a caller adds an ad-hoc key."""
        extended = dict(VALID_AUDIT, future_field="anything")
        AuditReport.model_validate(extended)  # must not raise

    def test_optional_fields_accepted_when_present(self):
        full = dict(
            VALID_AUDIT,
            warnings=[{"code": "X", "message": "y"}],
            suppressed=[{"reason": "invalid_span_bounds"}],
            settings={"mode": "enhanced"},
        )
        AuditReport.model_validate(full)  # must not raise


class TestScrubReportSchema:
    """Mirrors the dict built by pipeline._build_scrub_report()."""

    def test_valid_shape_round_trips(self):
        ScrubReport.model_validate(VALID_SCRUB)

    def test_missing_required_field_rejected_before_write_boundary(self):
        """A malformed scrub dict (missing 'groups') must be rejected before
        crossing the T7 temp-write boundary."""
        bad = dict(VALID_SCRUB)
        del bad["groups"]
        with pytest.raises(ValidationError):
            ScrubReport.model_validate(bad)

    def test_permissive_on_loosely_typed_nested_data(self):
        """Nested forensic/explorer data is intentionally untyped (dict/list
        of Any) -- only the top-level keys the rest of the codebase relies
        on are enforced."""
        full = dict(
            VALID_SCRUB,
            file_info={"input": {}, "output": {}},
            warnings=[{"code": "X"}],
            forensic_findings={"count": 0, "findings": []},
            deep_explorer={"pre": {"label": "pre_scrub", "parts": []}},
            binary_exports=[{"name": "a.bin"}],
            large_exports=[{"name": "b.bin"}],
        )
        ScrubReport.model_validate(full)  # must not raise


class TestFailureReportSchema:
    """Mirrors the dict built by pipeline._write_failure_report()."""

    def test_valid_shape_round_trips(self):
        FailureReport.model_validate(VALID_FAILURE)

    def test_missing_required_field_rejected_before_write_boundary(self):
        """A malformed failure dict (missing 'message') must be rejected
        before it ever reaches write_json_file()."""
        bad = dict(VALID_FAILURE)
        del bad["message"]
        with pytest.raises(ValidationError):
            FailureReport.model_validate(bad)

    def test_deadline_message_survives_validation_for_timeout_classifier(self):
        """Regression (non-negotiable per the design doc): message and
        technical_details must stay free-form str, not enums or constrained
        patterns, so pipeline.py's AI_PROCESSING_TIMEOUT classifier -- which
        greps these fields for the substrings 'timeout'/'deadline' -- keeps
        matching after this model is introduced."""
        payload = dict(
            VALID_FAILURE,
            message="AI processing timeout",
            technical_details=(
                "Model: mock, Error: Processing deadline exceeded. "
                "Try with a smaller document or different model."
            ),
        )
        model = FailureReport.model_validate(payload)
        assert "timeout" in model.message.lower()
        assert "deadline" in model.technical_details.lower()

    def test_message_field_is_unconstrained_string_type(self):
        """Guards against a future edit accidentally narrowing these fields
        to an enum/Literal, which would silently break the classifier."""
        field = FailureReport.model_fields["message"]
        assert field.annotation is str
        details_field = FailureReport.model_fields["technical_details"]
        assert details_field.annotation is str
