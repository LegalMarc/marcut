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

from marcut.report_schema import (
    AuditReport,
    ScrubReport,
    FailureReport,
    SpanRationale,
    MetadataScrubPayload,
    MetadataReportPayload,
)


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


class TestSpanRationaleSchema:
    """Issue #68's rationale field: {text, origin, model?} on every span,
    with `origin` mandatory and enum-constrained -- see
    docs/design/redaction_rationale_reporting.md's mitigation #1."""

    def test_valid_llm_validation_rationale_round_trips(self):
        span = {
            "start": 0, "end": 4, "label": "NAME",
            "rationale": {
                "text": "This is the name of a specific individual.",
                "origin": "llm_validation",
                "model": "qwen2.5:14b",
            },
        }
        model = AuditReport.model_validate(dict(VALID_AUDIT, spans=[span]))
        assert model.spans[0]["rationale"]["origin"] == "llm_validation"

    def test_valid_rule_deterministic_rationale_without_model_field(self):
        """A rule has no model -- `model` is optional and normally omitted
        for rule_deterministic/unavailable origins."""
        span = {
            "start": 0, "end": 4, "label": "SSN",
            "rationale": {
                "text": "Matched a deterministic SSN detection rule.",
                "origin": "rule_deterministic",
            },
        }
        AuditReport.model_validate(dict(VALID_AUDIT, spans=[span]))  # must not raise

    def test_valid_unavailable_rationale(self):
        span = {
            "start": 0, "end": 4, "label": "ORG",
            "rationale": {"text": "No rationale was generated for this entity.", "origin": "unavailable"},
        }
        AuditReport.model_validate(dict(VALID_AUDIT, spans=[span]))  # must not raise

    def test_rationale_missing_origin_is_rejected(self):
        """Acceptance criterion: the pydantic model must reject a rationale
        object missing `origin` -- `unavailable` must be stated explicitly,
        never implied by omitting the field."""
        span = {"start": 0, "end": 4, "label": "NAME", "rationale": {"text": "some text"}}
        with pytest.raises(ValidationError):
            AuditReport.model_validate(dict(VALID_AUDIT, spans=[span]))

    def test_rationale_with_invalid_origin_value_is_rejected(self):
        """`llm_summary` (Option C-lite) was explicitly deferred out of v1 --
        only the three shipped values are valid."""
        span = {
            "start": 0, "end": 4, "label": "NAME",
            "rationale": {"text": "some text", "origin": "llm_summary"},
        }
        with pytest.raises(ValidationError):
            AuditReport.model_validate(dict(VALID_AUDIT, spans=[span]))

    def test_span_without_rationale_key_still_validates(self):
        """A disabled-feature run's spans (no `rationale` key at all) must
        keep validating -- this field is additive, not required."""
        AuditReport.model_validate(VALID_AUDIT)  # must not raise (no rationale key)

    def test_span_rationale_model_directly_requires_origin(self):
        with pytest.raises(ValidationError):
            SpanRationale.model_validate({"text": "x"})


class TestRationaleGenerationMetadata:
    """Issue #68 mitigation #7: report-level disclosure of whether/how
    rationale was generated, distinguishing "not requested" from "requested
    and failed for every span"."""

    def test_disabled_metadata_accepted(self):
        full = dict(VALID_AUDIT, rationale_generation={"enabled": False, "model": None, "mode": None})
        AuditReport.model_validate(full)  # must not raise

    def test_enabled_metadata_accepted(self):
        full = dict(
            VALID_AUDIT,
            rationale_generation={"enabled": True, "model": "qwen2.5:14b", "mode": "validation_extended"},
        )
        AuditReport.model_validate(full)  # must not raise

    def test_absent_metadata_still_validates(self):
        """A report written before this feature existed has no
        rationale_generation key at all -- must not be rejected."""
        AuditReport.model_validate(VALID_AUDIT)  # must not raise


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


class TestMetadataPayloadSchemas:
    """Issue #91 (step 3 of the bridge-schema migration): the two tuple
    return payloads crossing the PythonKit bridge from
    pipeline.scrub_metadata_only() and pipeline.metadata_report_only().
    Both are subclasses of ScrubReport -- same underlying dict shape,
    built by the same pipeline._build_scrub_report() -- but each validates
    its own function's return boundary independently, so one function's
    payload rejecting a malformed dict says nothing about the other."""

    def test_metadata_scrub_payload_valid_shape_round_trips(self):
        MetadataScrubPayload.model_validate(VALID_SCRUB)

    def test_metadata_scrub_payload_missing_required_field_rejected(self):
        bad = dict(VALID_SCRUB)
        del bad["summary"]
        with pytest.raises(ValidationError):
            MetadataScrubPayload.model_validate(bad)

    def test_metadata_report_payload_valid_shape_round_trips(self):
        MetadataReportPayload.model_validate(VALID_SCRUB)

    def test_metadata_report_payload_missing_required_field_rejected(self):
        bad = dict(VALID_SCRUB)
        del bad["groups"]
        with pytest.raises(ValidationError):
            MetadataReportPayload.model_validate(bad)

    def test_payloads_are_independent_models_not_aliases(self):
        """Guards against a lazy `MetadataReportPayload = MetadataScrubPayload`
        alias silently collapsing the two named types back into one."""
        assert MetadataScrubPayload is not MetadataReportPayload


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
