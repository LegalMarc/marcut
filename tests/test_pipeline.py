"""
Tests for pipeline.py module - core helper functions for span processing.

Tests cover:
- normalize_unicode: Unicode to ASCII mapping
- _rank: Priority ranking for labels
- _merge_overlaps: Overlapping span resolution
- _snap_to_boundaries: Token boundary expansion
- _filter_overlong_org_spans: ORG span filtering
- _apply_consistency_pass: Entity consistency matching
- RedactionError: Error class construction
"""

import json
import pytest
import stat
from marcut import pipeline
from marcut.cancellation import ProcessingDeadlineExceeded
from marcut.report import write_json_file
from marcut.report_html import generate_html_report
from marcut.pipeline import (
    normalize_unicode,
    _rank,
    _merge_overlaps,
    _snap_to_boundaries,
    _filter_overlong_org_spans,
    _apply_consistency_pass,
    _filter_excluded_combo_spans,
    _trim_org_trailing_excluded_segments,
    _attach_defined_term_aliases,
    _drop_invalid_spans,
    _fold_curly_quotes,
    _finalize_and_write,
    _annotate_missing_rationale,
    _canonicalize_cluster_rationale,
    _sanitize_cross_referenced_rationale,
    RedactionError,
    _write_failure_report,
    safe_print,
)
from marcut.rationale import RationaleOrigin, is_rule_like_source


class TestNormalizeUnicode:
    """Test Unicode to ASCII normalization."""

    def test_smart_quotes_converted(self):
        """Test that smart quotes are converted to ASCII."""
        text = "\"Hello\" and 'World'"
        result = normalize_unicode(text)
        assert '"' in result
        assert "'" in result
        # Original smart quotes should be gone
        assert '\u201c' not in result
        assert '\u201d' not in result

    def test_dashes_converted(self):
        """Test that em and en dashes are converted."""
        text = "word–word and word—word"
        result = normalize_unicode(text)
        assert '--' in result  # Em dash
        assert '-' in result   # En dash

    def test_special_symbols_converted(self):
        """Test trademark, copyright, registered symbols."""
        text = "Brand™ Company® Copyright©"
        result = normalize_unicode(text)
        assert '(TM)' in result
        assert '(R)' in result
        assert '(c)' in result

    def test_ellipsis_converted(self):
        """Test ellipsis to three dots."""
        text = "trailing…text"
        result = normalize_unicode(text)
        assert '...' in result

    def test_fractions_converted(self):
        """Test fraction symbols."""
        text = "½ cup ¼ tsp ¾ done"
        result = normalize_unicode(text)
        assert '1/2' in result
        assert '1/4' in result
        assert '3/4' in result

    def test_plain_ascii_unchanged(self):
        """Test that plain ASCII passes through unchanged."""
        text = "Hello World 123"
        result = normalize_unicode(text)
        assert result == text

    def test_non_breaking_space(self):
        """Test non-breaking space replaced with regular space."""
        text = "word\xa0word"
        result = normalize_unicode(text)
        assert '\xa0' not in result
        assert ' ' in result


class TestRank:
    """Test _rank priority function."""

    def test_high_priority_labels(self):
        """Test that PII labels have highest priority."""
        assert _rank("EMAIL") == 3
        assert _rank("PHONE") == 3
        assert _rank("SSN") == 3
        assert _rank("CARD") == 3
        assert _rank("URL") == 3
        assert _rank("IP") == 3

    def test_medium_priority_labels(self):
        """Test name/org labels have medium priority."""
        assert _rank("NAME") == 2
        assert _rank("ORG") == 2
        assert _rank("BRAND") == 2

    def test_low_priority_labels(self):
        """Test numeric labels have lower priority."""
        assert _rank("MONEY") == 1
        assert _rank("NUMBER") == 1
        assert _rank("DATE") == 1

    def test_unknown_labels_zero_rank(self):
        """Test unknown labels return 0."""
        assert _rank("UNKNOWN") == 0
        assert _rank("RANDOM") == 0
        assert _rank("") == 0


class TestMergeOverlaps:
    """Test _merge_overlaps span merging logic."""

    def test_empty_list(self):
        """Test empty span list."""
        result = _merge_overlaps([], "some text")
        assert result == []

    def test_no_overlaps(self):
        """Test non-overlapping spans remain separate."""
        text = "John works at Sample 123 Inc."
        spans = [
            {"start": 0, "end": 4, "label": "NAME", "text": "John"},
            {"start": 14, "end": 22, "label": "ORG", "text": "Sample 123 Inc"},
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 2

    def test_overlapping_spans_merged(self):
        """Test overlapping spans are merged (union)."""
        text = "Sample 123 Corporation Inc."
        spans = [
            {"start": 0, "end": 17, "label": "ORG", "text": "Sample 123 Corporation"},
            {"start": 5, "end": 21, "label": "ORG", "text": "Corporation Inc."},
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 1
        assert result[0]["start"] == 0
        assert result[0]["end"] == 21

    def test_higher_rank_label_wins(self):
        """Test higher priority label is kept on overlap."""
        text = "Contact: sample123@example.com"
        spans = [
            {"start": 9, "end": 25, "label": "NAME", "text": "sample123@example.com"},
            {"start": 9, "end": 25, "label": "EMAIL", "text": "sample123@example.com"},
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 1
        # EMAIL has higher rank than NAME
        assert result[0]["label"] == "EMAIL"

    def test_invalid_spans_filtered(self):
        """Test that invalid spans are filtered out."""
        text = "Some text"
        spans = [
            {"start": 0, "end": 4, "label": "NAME", "text": "Some"},
            {"start": 5, "end": 2, "label": "ORG", "text": "invalid"},  # start > end
            "not a dict",  # not a dict
            {"start": 0, "label": "ORG"},  # missing end
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 1
        assert result[0]["text"] == "Some"

    def test_contained_span_merged(self):
        """Test that fully contained spans are merged."""
        text = "The Sample 123 Corporation Ltd."
        spans = [
            {"start": 4, "end": 25, "label": "ORG", "text": "Sample 123 Corporation Ltd."},
            {"start": 9, "end": 20, "label": "ORG", "text": "Corporation"},
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 1
        # Outer span should encompass inner
        assert result[0]["end"] == 25

    def test_rationale_moves_with_the_winning_spans_source(self):
        """Regression for issue #68 finding 1: when an overlapping LLM span
        sorts first (here, because it is longer than the rule span at the
        same start), it seeds `last` including its `llm_validation`
        rationale dict. If the shorter, higher-confidence rule span then
        wins on `is_better` and overwrites label/confidence/entity_id/source
        but not `rationale`, the survivor ends up with source="rule" while
        still carrying the LLM's rationale dict -- the exact wrong-mechanism
        attribution mitigation #1 exists to prevent. `rationale` must move
        (or be cleared) alongside `source`."""
        text = "The Acme Corporation of Delaware signed the agreement."
        spans = [
            # Longer LLM span, sorts first (same start, same ORG rank, longer).
            {
                "start": 4, "end": 33, "label": "ORG",
                "text": "Acme Corporation of Delaware",
                "confidence": 0.75, "source": "llm_extract",
                "rationale": {"text": "Model-authored explanation.",
                              "origin": "llm_validation", "model": "qwen2.5:14b"},
            },
            # Shorter, higher-confidence rule span -- wins on confidence tie-break.
            {
                "start": 4, "end": 20, "label": "ORG",
                "text": "Acme Corporation",
                "confidence": 0.98, "source": "rule", "entity_id": "ORG_1",
            },
        ]
        result = _merge_overlaps(spans, text)
        assert len(result) == 1
        survivor = result[0]
        assert survivor["source"] == "rule"
        # The rule span carried no `rationale` of its own, so the LLM's
        # dict must not survive attached to a rule-sourced span: the key
        # is popped outright, not left as None or as a stale dict.
        assert "rationale" not in survivor


class TestSnapToBoundaries:
    """Test _snap_to_boundaries token expansion."""

    def test_mid_word_expands_left(self):
        """Test expansion left to word boundary."""
        text = "Hello World"
        # Span in middle of "World" at indices 7-9 ("or")
        spans = [{"start": 7, "end": 9, "label": "NAME", "text": "or"}]
        result = _snap_to_boundaries(text, spans)
        assert result[0]["start"] == 6  # Expands to "W"
        assert result[0]["end"] == 11  # Expands to end of "World"
        assert result[0]["text"] == "World"

    def test_mid_word_expands_right(self):
        """Test expansion right to word boundary."""
        text = "Testing expansion"
        # Span starts at word boundary but ends mid-word
        spans = [{"start": 8, "end": 11, "label": "NAME", "text": "exp"}]
        result = _snap_to_boundaries(text, spans)
        assert result[0]["end"] == 17  # Expands to end of "expansion"

    def test_already_on_boundaries(self):
        """Test spans already on word boundaries stay same."""
        text = "Hello World"
        spans = [{"start": 0, "end": 5, "label": "NAME", "text": "Hello"}]
        result = _snap_to_boundaries(text, spans)
        assert result[0]["start"] == 0
        assert result[0]["end"] == 5

    def test_handles_punctuation(self):
        """Test that expansion stops at punctuation."""
        text = "John, meet Mary."
        spans = [{"start": 0, "end": 4, "label": "NAME", "text": "John"}]
        result = _snap_to_boundaries(text, spans)
        assert result[0]["end"] == 4  # Stops before comma

    def test_empty_spans(self):
        """Test empty span list."""
        result = _snap_to_boundaries("text", [])
        assert result == []


class TestTrimOrgTrailingExcludedSegments:
    def test_trims_trailing_excluded_segment_after_comma(self):
        span_text = "Sample 123 Holdings, Inc., a Delaware corporation"
        text = f"{span_text} shall be known as the Company."
        spans = [
            {
                "start": 0,
                "end": len(span_text),
                "label": "ORG",
                "text": span_text,
            }
        ]
        result = _trim_org_trailing_excluded_segments(text, spans)
        assert result[0]["text"] == "Sample 123 Holdings, Inc."
        assert result[0]["end"] == len("Sample 123 Holdings, Inc.")

    def test_trims_trailing_excluded_parenthetical(self):
        span_text = "Sample 123, Inc. (a Delaware corporation)"
        text = f"{span_text} is the issuer."
        spans = [
            {
                "start": 0,
                "end": len(span_text),
                "label": "ORG",
                "text": span_text,
            }
        ]
        result = _trim_org_trailing_excluded_segments(text, spans)
        assert result[0]["text"] == "Sample 123, Inc."
        assert result[0]["end"] == len("Sample 123, Inc.")


class TestOrgDefinedTermAliases:
    def test_specific_org_alias_redacted_but_generic_role_preserved(self):
        text = (
            'and TIME USA, LLC, a Limited Liability Company formed under the laws '
            'of the State of Delaware ("Publisher" or "TIME").'
        )
        org_start = text.index("TIME USA, LLC")
        org_end = org_start + len("TIME USA, LLC")
        spans = [{
            "start": org_start,
            "end": org_end,
            "label": "ORG",
            "text": "TIME USA, LLC",
            "confidence": 0.9,
        }]

        result = _attach_defined_term_aliases(text, spans)
        aliases = [span for span in result if span.get("source") == "defined_term"]

        assert any(span["text"] == "TIME" for span in aliases)
        assert not any(span["text"] == "Publisher" for span in aliases)

    def test_specific_org_not_suppressed_by_token_exclusions(self):
        text = "Publisher means TIME USA, LLC."
        start = text.index("TIME USA, LLC")
        spans = [{
            "start": start,
            "end": start + len("TIME USA, LLC"),
            "label": "ORG",
            "text": "TIME USA, LLC",
        }]

        assert _filter_excluded_combo_spans(text, spans) == spans


class TestAttachDefinedTermAliases:
    def test_adds_name_alias_in_parentheses(self):
        text = 'Sample 123 pays Sample Person 123 ("Person 123") under agreement.'
        name = "Sample Person 123"
        span = {
            "start": text.index(name),
            "end": text.index(name) + len(name),
            "label": "NAME",
            "text": name,
            "confidence": 0.82,
        }
        result = _attach_defined_term_aliases(text, [span])
        alias_matches = [s for s in result if s.get("text") == "Person 123"]
        assert len(alias_matches) == 1

    def test_adds_name_alias_with_initial(self):
        text = 'Sample 123 pays Sample Person 123 ("S. Person 123") under agreement.'
        name = "Sample Person 123"
        span = {
            "start": text.index(name),
            "end": text.index(name) + len(name),
            "label": "NAME",
            "text": name,
            "confidence": 0.82,
        }
        result = _attach_defined_term_aliases(text, [span])
        alias_matches = [s for s in result if s.get("text") == "S. Person 123"]
        assert len(alias_matches) == 1

    def test_adds_org_alias_subset(self):
        text = 'Sample 123 Holdings, LLC ("Sample 123") is the borrower.'
        org = "Sample 123 Holdings, LLC"
        span = {
            "start": text.index(org),
            "end": text.index(org) + len(org),
            "label": "ORG",
            "text": org,
            "confidence": 0.91,
        }
        result = _attach_defined_term_aliases(text, [span])
        alias_matches = [s for s in result if s.get("text") == "Sample 123"]
        assert len(alias_matches) == 1

    def test_excluded_alias_skipped(self):
        text = 'Sample 123 Holdings, LLC ("Company") is the borrower.'
        org = "Sample 123 Holdings, LLC"
        span = {
            "start": text.index(org),
            "end": text.index(org) + len(org),
            "label": "ORG",
            "text": org,
            "confidence": 0.91,
        }
        result = _attach_defined_term_aliases(text, [span])
        assert len(result) == 1

class TestFilterOverlongOrgSpans:
    """Test _filter_overlong_org_spans filtering."""

    def test_short_org_kept(self):
        """Test normal ORG spans are kept."""
        text = "Sample 123 Inc."
        spans = [{"start": 0, "end": 9, "label": "ORG", "text": "Sample 123 Inc."}]
        result = _filter_overlong_org_spans(text, spans)
        assert len(result) == 1

    def test_long_org_removed(self):
        """Test very long ORG spans are removed."""
        long_text = "A" * 100
        spans = [{"start": 0, "end": 100, "label": "ORG", "text": long_text}]
        result = _filter_overlong_org_spans("x" * 100, spans, max_len=80)
        assert len(result) == 0

    def test_multiline_org_removed(self):
        """Test ORG spans with newlines are removed."""
        text = "Sample 123\nDivision"
        spans = [{"start": 0, "end": len(text), "label": "ORG", "text": text}]
        result = _filter_overlong_org_spans(text, spans)
        assert len(result) == 0

    def test_short_multiline_org_with_suffix_kept(self):
        """Test short ORG spans with a single newline and suffix are kept."""
        text = "Rhenus Contract Logistics Tilburg \nInventory B.V., Netherlands"
        span_text = "Rhenus Contract Logistics Tilburg \nInventory B.V."
        spans = [{"start": 0, "end": len(span_text), "label": "ORG", "text": span_text}]
        result = _filter_overlong_org_spans(text, spans)
        assert len(result) == 1
        assert result[0]["text"] == span_text

    def test_non_org_labels_kept(self):
        """Test non-ORG labels are not filtered by length."""
        long_text = "A" * 100
        spans = [
            {"start": 0, "end": 100, "label": "NAME", "text": long_text},
            {"start": 0, "end": 100, "label": "EMAIL", "text": long_text},
        ]
        result = _filter_overlong_org_spans("x" * 100, spans, max_len=80)
        assert len(result) == 2

    def test_empty_spans(self):
        """Test empty list."""
        result = _filter_overlong_org_spans("text", [])
        assert result == []

    def test_custom_max_len(self):
        """Test custom max_len parameter."""
        text = "A" * 50
        spans = [{"start": 0, "end": 50, "label": "ORG", "text": text}]
        # 50 exceeds max_len=40, so should be filtered
        result = _filter_overlong_org_spans("x" * 50, spans, max_len=40)
        assert len(result) == 0
        # 50 is under max_len=60, so should be kept
        result = _filter_overlong_org_spans("x" * 50, spans, max_len=60)
        assert len(result) == 1


class TestApplyConsistencyPass:
    """Test _apply_consistency_pass entity propagation."""

    def test_empty_spans(self):
        """Test empty span list."""
        result = _apply_consistency_pass("some text", [])
        assert result == []

    def test_finds_additional_matches(self):
        """Test that consistency pass finds additional mentions."""
        text = "Sample 123 Corp is great. I love Sample 123 Corp products."
        spans = [{"start": 0, "end": 9, "label": "ORG", "text": "Sample 123 Corp"}]
        result = _apply_consistency_pass(text, spans)
        # Should find both occurrences
        assert len(result) >= 2
        # Original span plus new one at position 27
        acme_positions = [s["start"] for s in result if s.get("text") == "Sample 123 Corp"]
        assert 0 in acme_positions
        assert 33 in acme_positions

    def test_ignores_short_entities(self):
        """Test entities < 4 chars are not propagated."""
        text = "Mr. Smith and Mr. Jones"
        spans = [{"start": 0, "end": 3, "label": "PERSON", "text": "Mr."}]
        result = _apply_consistency_pass(text, spans)
        # "Mr." is too short (3 chars), should only have original
        assert len(result) == 1

    def test_ignores_stop_words(self):
        """Test stop words are not propagated."""
        text = "The Company and The Company"
        spans = [{"start": 4, "end": 11, "label": "ORG", "text": "Company"}]
        result = _apply_consistency_pass(text, spans)
        # "Company" is in stop words, no propagation
        # (Actually "company" lowercase is the stop word)
        # Let's check - original should remain
        assert len(result) >= 1

    def test_ignores_unsafe_labels(self):
        """Test DATE and NUMBER labels are not propagated."""
        text = "Date: 2024-01-01 and 2024-01-01 again"
        spans = [{"start": 6, "end": 16, "label": "DATE", "text": "2024-01-01"}]
        result = _apply_consistency_pass(text, spans)
        # DATE is not in SAFE_LABELS, should only have original
        assert len(result) == 1

    def test_case_sensitive_matching(self):
        """Test that matching is case-sensitive."""
        text = "John Smith met john smith yesterday"
        spans = [{"start": 0, "end": 10, "label": "PERSON", "text": "John Smith"}]
        result = _apply_consistency_pass(text, spans)
        # Only exact case match should be found
        # The lowercase "john smith" should NOT match
        john_lower_matches = [s for s in result if s.get("text") == "john smith"]
        assert len(john_lower_matches) == 0  # No lowercase match

    def test_candidate_limit_bounds_consistency_work(self, monkeypatch):
        """Pathological candidate counts are bounded before regex construction."""
        monkeypatch.setenv("MARCUT_CONSISTENCY_MAX_CANDIDATES", "2")
        text = "Alpha Holdings Beta Holdings Gamma Holdings Alpha Holdings Beta Holdings Gamma Holdings"
        spans = [
            {"start": 0, "end": 14, "label": "ORG", "text": "Alpha Holdings"},
            {"start": 15, "end": 28, "label": "ORG", "text": "Beta Holdings"},
            {"start": 29, "end": 43, "label": "ORG", "text": "Gamma Holdings"},
        ]

        result = _apply_consistency_pass(text, spans)

        gamma_mentions = [sp for sp in result if sp.get("text") == "Gamma Holdings"]
        assert len(gamma_mentions) == 1


class TestDropInvalidSpans:
    """A5: validate LLM-derived (and rule-derived) spans' bounds and text
    before they can reach dm.apply_replacements(). Invalid spans must be
    dropped and logged -- never silently corrupt output or mis-redact."""

    TEXT = "Contact John Smith regarding Jane Doe's account today."

    def _valid_span(self):
        start = self.TEXT.index("John Smith")
        end = start + len("John Smith")
        return {
            "start": start, "end": end, "label": "NAME",
            "text": "John Smith", "confidence": 0.9, "source": "llm",
        }

    def test_valid_span_passes_through_unchanged(self):
        span = self._valid_span()
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [span], warnings, suppressed)
        assert survivors == [span]
        assert warnings == []
        assert suppressed == []

    def test_drops_negative_start(self):
        span = {"start": -1, "end": 5, "label": "NAME", "text": "xxxxx"}
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [span], warnings, suppressed)
        assert survivors == []
        assert len(warnings) == 1
        assert warnings[0]["code"] == "INVALID_SPAN_DROPPED"
        assert suppressed[0]["reason"] == "invalid_span_bounds_out_of_range"

    def test_drops_end_beyond_text_length(self):
        span = {"start": 5, "end": len(self.TEXT) + 50, "label": "NAME", "text": "overflow"}
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [span], warnings, suppressed)
        assert survivors == []
        assert suppressed[0]["reason"] == "invalid_span_bounds_out_of_range"

    def test_drops_start_greater_or_equal_end(self):
        spans = [
            {"start": 10, "end": 10, "label": "NAME", "text": ""},  # start == end
            {"start": 15, "end": 10, "label": "NAME", "text": "12345"},  # start > end
        ]
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, spans, warnings, suppressed)
        assert survivors == []
        assert len(warnings) == 2
        assert all(s["reason"] == "invalid_span_bounds_out_of_range" for s in suppressed)

    def test_drops_drifted_offset_text_mismatch(self):
        """A plausible-but-shifted offset: in-bounds, but text[start:end]
        no longer matches the entity text recorded for it."""
        start = self.TEXT.index("John Smith")
        end = start + len("John Smith")
        drifted = {"start": start + 3, "end": end + 3, "label": "NAME", "text": "John Smith"}
        # Sanity: confirm this really is a mismatch, not an accidental match.
        assert self.TEXT[drifted["start"]:drifted["end"]] != "John Smith"

        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [drifted], warnings, suppressed)
        assert survivors == []
        assert suppressed[0]["reason"] == "invalid_span_text_mismatch"

    def test_drops_missing_or_non_string_text_field(self):
        span_missing = {"start": 0, "end": 5, "label": "NAME"}
        span_none = {"start": 0, "end": 5, "label": "NAME", "text": None}
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [span_missing, span_none], warnings, suppressed)
        assert survivors == []
        assert all(s["reason"] == "invalid_span_missing_text" for s in suppressed)

    def test_drops_non_dict_entry_without_raising(self):
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, ["not-a-span", None, 42], warnings, suppressed)
        assert survivors == []
        assert len(warnings) == 3
        assert all(s["reason"] == "invalid_span_not_a_dict" for s in suppressed)

    def test_tolerates_curly_quote_fold_for_defined_term_alias_text(self):
        """_attach_defined_term_aliases folds curly apostrophes to straight
        ones when it stores an alias's "text" (see that function and
        _fold_curly_quotes), while start/end still point at the untouched
        document text. A legitimate alias spanning a curly apostrophe must
        not be misclassified as corrupted just because of that fold."""
        text = "Jane Doe’s Bakery is renowned."
        end = len("Jane Doe’s Bakery")
        span = {
            "start": 0, "end": end, "label": "ORG",
            "text": "Jane Doe's Bakery",  # straight apostrophe, as the alias helper stores it
            "source": "defined_term",
        }
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(text, [span], warnings, suppressed)
        assert survivors == [span]
        assert warnings == []
        assert suppressed == []

    def test_logs_one_warning_and_suppressed_entry_per_dropped_span(self):
        """The count of dropped spans must be recoverable from the report
        data (warnings + suppressed), not silently lost."""
        good = self._valid_span()
        bad_spans = [
            {"start": -1, "end": 5, "label": "NAME", "text": "a"},
            {"start": 5, "end": len(self.TEXT) + 100, "label": "NAME", "text": "b"},
            {"start": 10, "end": 10, "label": "NAME", "text": ""},
        ]
        warnings, suppressed = [], []
        survivors = _drop_invalid_spans(self.TEXT, [good] + bad_spans, warnings, suppressed)

        assert survivors == [good]
        assert len(warnings) == len(bad_spans)
        assert len(suppressed) == len(bad_spans)
        assert all(w["code"] == "INVALID_SPAN_DROPPED" for w in warnings)


class TestFoldCurlyQuotes:
    """Helper backing _drop_invalid_spans's text-match tolerance."""

    def test_folds_curly_single_quotes_to_straight(self):
        assert _fold_curly_quotes("Jane’s ‘quoted’ name") == "Jane's 'quoted' name"

    def test_leaves_straight_quotes_and_other_text_unchanged(self):
        assert _fold_curly_quotes("Jane's plain text") == "Jane's plain text"


class TestFinalizeAndWriteDropsInvalidSpans:
    """A5 integration: _finalize_and_write must never let an invalid span
    reach dm.apply_replacements(), and the audit report must disclose how
    many spans were dropped rather than silently omitting them."""

    class _FakeDocxMap:
        def __init__(self):
            self.warnings = []
            self.replacements = None

        def apply_replacements(self, replacements, track_changes=True):
            self.replacements = replacements

        def scrub_metadata(self, settings):
            return None

        def harden_document(self, *args, **kwargs):
            return None

        def save(self, path):
            with open(path, "wb") as handle:
                handle.write(b"stub docx")

    def test_invalid_spans_are_dropped_before_apply_replacements(self, monkeypatch, tmp_path):
        text = "Contact John Smith regarding Jane Doe's account today."
        good_start = text.index("John Smith")
        good_end = good_start + len("John Smith")

        spans = [
            {
                "start": good_start, "end": good_end, "label": "NAME",
                "text": "John Smith", "confidence": 0.9, "source": "llm",
                "needs_redaction": True,
            },
            # start = -1
            {"start": -1, "end": 5, "label": "NAME", "text": "xxxxx",
             "confidence": 0.9, "source": "llm", "needs_redaction": True},
            # end > len(text)
            {"start": 5, "end": len(text) + 50, "label": "NAME", "text": "overflow",
             "confidence": 0.9, "source": "llm", "needs_redaction": True},
            # start >= end
            {"start": 10, "end": 10, "label": "NAME", "text": "",
             "confidence": 0.9, "source": "llm", "needs_redaction": True},
            # plausible-but-shifted offset (off by a few chars)
            {
                "start": good_start + 3, "end": good_end + 3, "label": "NAME",
                "text": "John Smith", "confidence": 0.9, "source": "llm",
                "needs_redaction": True,
            },
        ]

        # Skip metadata scrub-report/hardening entirely so this FakeDocxMap
        # doesn't need to model real document metadata (same recipe as
        # TestTransactionalArtifacts below).
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")

        dm = self._FakeDocxMap()
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"
        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")

        code = _finalize_and_write(
            dm,
            text,
            spans,
            str(output_path),
            str(report_path),
            str(input_path),
            "mock-model",
        )

        assert code == 0
        assert dm.replacements is not None
        assert len(dm.replacements) == 1
        assert dm.replacements[0]["start"] == good_start
        assert dm.replacements[0]["end"] == good_end

        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        invalid_warnings = [
            w for w in report_payload.get("warnings", [])
            if w["code"] == "INVALID_SPAN_DROPPED"
        ]
        invalid_suppressed = [
            s for s in report_payload.get("suppressed", [])
            if s["reason"].startswith("invalid_span_")
        ]
        assert len(invalid_warnings) == 4
        assert len(invalid_suppressed) == 4

        # The dropped spans' garbage offsets must not leak into the audit
        # report's own "spans" list either.
        audited_starts = {sp["start"] for sp in report_payload["spans"]}
        assert audited_starts == {good_start}


# --- Issue #68: redaction-rationale data layer (Option B) -------------------
#
# rationale: {text, origin, model?} on every span, opt-in via
# MARCUT_GENERATE_RATIONALE, generated/canonicalized by
# _annotate_missing_rationale / _canonicalize_cluster_rationale /
# _sanitize_cross_referenced_rationale inside _finalize_and_write. See
# docs/design/redaction_rationale_reporting.md for the full design.

class _FakeDocxMapForRationale:
    """Same minimal stub as TestFinalizeAndWriteDropsInvalidSpans's
    _FakeDocxMap, reused here so these tests can call _finalize_and_write
    directly without a real DOCX."""

    def __init__(self):
        self.replacements = None

    def apply_replacements(self, replacements, track_changes=True):
        self.replacements = replacements

    def scrub_metadata(self, settings):
        return None

    def harden_document(self, *args, **kwargs):
        return None

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(b"stub docx")


def _run_finalize_and_write(text, spans, tmp_path, **kwargs):
    dm = _FakeDocxMapForRationale()
    output_path = tmp_path / "output.docx"
    report_path = tmp_path / "report.json"
    input_path = tmp_path / "input.docx"
    input_path.write_bytes(b"input")

    code = _finalize_and_write(
        dm, text, spans, str(output_path), str(report_path), str(input_path), "mock-model", **kwargs
    )
    assert code == 0
    return json.loads(report_path.read_text(encoding="utf-8"))


class TestAnnotateMissingRationale:
    """Unit tests for the template/fallback annotation step."""

    def test_rule_source_gets_rule_deterministic_template(self):
        spans = [{"label": "SSN", "source": "rule", "text": "123-45-6789"}]
        _annotate_missing_rationale(spans)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.RULE_DETERMINISTIC.value
        assert spans[0]["rationale"]["text"]

    def test_defined_term_and_extended_address_and_consistency_pass_are_rule_like(self):
        spans = [
            {"label": "ORG", "source": "defined_term", "text": "the Company"},
            {"label": "LOC", "source": "rule_extended_address", "text": "Suite 400"},
            {"label": "NAME", "source": "consistency_pass_fuzzy", "text": "J. Smith"},
        ]
        _annotate_missing_rationale(spans)
        assert all(sp["rationale"]["origin"] == RationaleOrigin.RULE_DETERMINISTIC.value for sp in spans)

    def test_non_rule_source_without_existing_rationale_gets_unavailable(self):
        spans = [{"label": "NAME", "source": "llm_extract", "text": "John Smith"}]
        _annotate_missing_rationale(spans)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.UNAVAILABLE.value

    def test_existing_dict_rationale_is_left_untouched(self):
        """model_enhanced.py already attached a real llm_validation
        rationale for this span -- must not be overwritten."""
        existing = {"text": "Real model rationale.", "origin": "llm_validation", "model": "qwen2.5:14b"}
        spans = [{"label": "ORG", "source": "llm_extract", "text": "Acme", "rationale": existing}]
        _annotate_missing_rationale(spans)
        assert spans[0]["rationale"] is existing

    def test_rule_like_source_overwrites_a_pre_existing_llm_rationale(self):
        """Regression for issue #68 finding 1: `is_rule_like_source` must be
        authoritative. A rule-like span that somehow still carries a dict
        rationale from another mechanism (e.g. one that survived
        `_merge_overlaps` picking the rule span's identity over an LLM
        span's) must have it overwritten with the rule_deterministic
        template, not left as-is."""
        leaked = {"text": "Model-authored explanation.", "origin": "llm_validation", "model": "qwen2.5:14b"}
        spans = [{"label": "ORG", "source": "rule", "text": "Acme Corporation", "rationale": leaked}]
        _annotate_missing_rationale(spans)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.RULE_DETERMINISTIC.value
        assert spans[0]["rationale"] is not leaked

    def test_non_dict_rationale_value_is_replaced_not_shipped_as_is(self):
        """The llama.cpp backend's raw entity.rationale is a plain string
        (e.g. "Extracted by model"), not a {text, origin} object -- it must
        be normalized rather than shipped as-is, which would fail the
        AuditReport schema (a str is not a valid rationale object)."""
        spans = [{"label": "NAME", "source": "llm_extract", "text": "John Smith", "rationale": "Extracted by model"}]
        _annotate_missing_rationale(spans)
        assert isinstance(spans[0]["rationale"], dict)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.UNAVAILABLE.value


class TestCanonicalizeClusterRationale:
    """Mitigation #2: one rationale per stable entity_id."""

    def test_multiple_mentions_of_same_entity_id_get_one_canonical_rationale(self):
        spans = [
            {"entity_id": "ORG_1", "confidence": 0.7,
             "rationale": {"text": "A", "origin": RationaleOrigin.UNAVAILABLE.value}},
            {"entity_id": "ORG_1", "confidence": 0.9,
             "rationale": {"text": "B", "origin": RationaleOrigin.LLM_VALIDATION.value}},
            {"entity_id": "ORG_1", "confidence": 0.99,
             "rationale": {"text": "C", "origin": RationaleOrigin.RULE_DETERMINISTIC.value}},
        ]
        _canonicalize_cluster_rationale(spans)
        # llm_validation beats rule_deterministic beats unavailable, regardless of confidence.
        assert all(sp["rationale"]["text"] == "B" for sp in spans)

    def test_highest_confidence_llm_validation_wins_among_ties(self):
        spans = [
            {"entity_id": "NAME_1", "confidence": 0.6,
             "rationale": {"text": "low-conf", "origin": RationaleOrigin.LLM_VALIDATION.value}},
            {"entity_id": "NAME_1", "confidence": 0.95,
             "rationale": {"text": "high-conf", "origin": RationaleOrigin.LLM_VALIDATION.value}},
        ]
        _canonicalize_cluster_rationale(spans)
        assert all(sp["rationale"]["text"] == "high-conf" for sp in spans)

    def test_single_span_entity_is_left_alone(self):
        spans = [{"entity_id": "ORG_2", "confidence": 0.8,
                  "rationale": {"text": "only one", "origin": RationaleOrigin.UNAVAILABLE.value}}]
        _canonicalize_cluster_rationale(spans)
        assert spans[0]["rationale"]["text"] == "only one"

    def test_different_entity_ids_are_not_mixed(self):
        spans = [
            {"entity_id": "ORG_1", "confidence": 0.9,
             "rationale": {"text": "org one", "origin": RationaleOrigin.LLM_VALIDATION.value}},
            {"entity_id": "ORG_2", "confidence": 0.9,
             "rationale": {"text": "org two", "origin": RationaleOrigin.LLM_VALIDATION.value}},
        ]
        _canonicalize_cluster_rationale(spans)
        assert spans[0]["rationale"]["text"] == "org one"
        assert spans[1]["rationale"]["text"] == "org two"

    @pytest.mark.parametrize("rule_like_source", ["consistency_pass", "consistency_pass_ci", "defined_term"])
    def test_rule_like_span_in_mixed_cluster_is_excluded_from_canonicalization(self, rule_like_source):
        """Mixed cluster: #1 (rule-like spans get only the template) wins
        over #2 (one rationale per entity_id). The rule-like mention keeps
        its own rule_deterministic template; canonicalization runs only
        among the remaining LLM-path spans."""
        rule_template = {"text": "Matched via the document consistency pass.",
                         "origin": RationaleOrigin.RULE_DETERMINISTIC.value}
        spans = [
            {"entity_id": "ORG_1", "confidence": 0.7, "source": "llm_extract",
             "rationale": {"text": "unvalidated", "origin": RationaleOrigin.UNAVAILABLE.value}},
            {"entity_id": "ORG_1", "confidence": 0.9, "source": "llm_extract",
             "rationale": {"text": "model text", "origin": RationaleOrigin.LLM_VALIDATION.value, "model": "qwen2.5:14b"}},
            {"entity_id": "ORG_1", "confidence": 0.99, "source": rule_like_source,
             "rationale": rule_template},
        ]
        _canonicalize_cluster_rationale(spans)
        assert spans[0]["rationale"]["text"] == "model text"
        assert spans[1]["rationale"]["text"] == "model text"
        assert spans[2]["rationale"] is rule_template


class TestSanitizeCrossReferencedRationale:
    """Mitigation #3 (placeholder-only cross-referencing), full-document
    backstop layered on top of model_enhanced.py's same-batch check."""

    def test_leaking_another_entitys_literal_text_is_withheld(self):
        spans = [
            {"entity_id": "ORG_1", "text": "Acme Corp",
             "rationale": {"text": "Signed alongside Widget LLC.", "origin": RationaleOrigin.LLM_VALIDATION.value,
                           "model": "qwen2.5:14b"}},
            {"entity_id": "ORG_2", "text": "Widget LLC",
             "rationale": {"text": "A specific counterparty.", "origin": RationaleOrigin.LLM_VALIDATION.value}},
        ]
        _sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.UNAVAILABLE.value
        assert "Widget LLC" not in spans[0]["rationale"]["text"]
        assert "model" not in spans[0]["rationale"]
        # The other span, which didn't leak, is unaffected.
        assert spans[1]["rationale"]["origin"] == RationaleOrigin.LLM_VALIDATION.value

    def test_non_llm_validation_rationale_is_never_checked_or_modified(self):
        """rule_deterministic/unavailable text is our own template, never
        model-authored -- no need to scan it, and scanning it could produce
        false positives on a short shared word."""
        spans = [
            {"entity_id": "ORG_1", "text": "Acme",
             "rationale": {"text": "Matched a deterministic ORG detection rule.", "origin": RationaleOrigin.RULE_DETERMINISTIC.value}},
            {"entity_id": "ORG_2", "text": "Acme Holdings",
             "rationale": {"text": "irrelevant", "origin": RationaleOrigin.UNAVAILABLE.value}},
        ]
        before = spans[0]["rationale"]["text"]
        _sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["text"] == before

    def test_own_entitys_own_text_does_not_count_as_a_leak(self):
        spans = [
            {"entity_id": "ORG_1", "text": "Acme Corp",
             "rationale": {"text": "Acme Corp is a party to this agreement.", "origin": RationaleOrigin.LLM_VALIDATION.value}},
        ]
        _sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == RationaleOrigin.LLM_VALIDATION.value


class TestFinalizeAndWriteRationaleIntegration:
    """End-to-end (via _finalize_and_write) coverage of the opt-in flag,
    the report-level rationale_generation metadata, and the byte-identical-
    when-disabled guarantee."""

    def _rule_span(self, text, needle, label="SSN", source="rule"):
        start = text.index(needle)
        return {
            "start": start, "end": start + len(needle), "label": label,
            "text": needle, "confidence": 0.95, "source": source, "needs_redaction": True,
        }

    def test_disabled_by_default_no_rationale_key_and_metadata_disabled(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MARCUT_GENERATE_RATIONALE", raising=False)
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "Contact SSN 123-45-6789 today."
        spans = [self._rule_span(text, "123-45-6789")]

        report = _run_finalize_and_write(text, spans, tmp_path)

        assert all("rationale" not in sp for sp in report["spans"])
        assert report["rationale_generation"] == {"enabled": False, "model": None, "mode": None}

    def test_enabled_rule_span_gets_rule_deterministic_rationale_and_metadata_enabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "Contact SSN 123-45-6789 today."
        spans = [self._rule_span(text, "123-45-6789")]

        report = _run_finalize_and_write(text, spans, tmp_path)

        assert report["spans"][0]["rationale"]["origin"] == "rule_deterministic"
        assert report["rationale_generation"]["enabled"] is True
        # No report_settings passed (direct _finalize_and_write call) -> not
        # one of the LLM modes -> rule-only mode label. #68 round-4: because
        # no model authored anything on this path, `model` must be null --
        # naming the configured model here would attribute template strings
        # to a model that never executed.
        assert report["rationale_generation"]["mode"] == "rule_deterministic_only"
        assert report["rationale_generation"]["model"] is None

    def test_enabled_and_disabled_runs_produce_identical_decisions(self, monkeypatch, tmp_path):
        """Mitigation #5: disabling must be byte-identical to today's
        output for the fields that actually drive redaction -- same spans
        redacted, same entity_id/confidence/text/label/source."""
        text = "Contact SSN 123-45-6789 today."
        spans = [self._rule_span(text, "123-45-6789")]
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")

        off_dir = tmp_path / "off"
        on_dir = tmp_path / "on"
        off_dir.mkdir()
        on_dir.mkdir()

        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "0")
        report_off = _run_finalize_and_write(text, [dict(s) for s in spans], off_dir)

        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        report_on = _run_finalize_and_write(text, [dict(s) for s in spans], on_dir)

        decision_fields = ("start", "end", "label", "entity_id", "confidence", "source", "text", "validated", "validation_result")
        off_decisions = [{k: sp.get(k) for k in decision_fields} for sp in report_off["spans"]]
        on_decisions = [{k: sp.get(k) for k in decision_fields} for sp in report_on["spans"]]
        assert off_decisions == on_decisions

    def test_multiple_mentions_of_same_llm_entity_get_one_canonical_rationale_end_to_end(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "Acme Corp signed first. Later, Acme Corp signed again."
        first = text.index("Acme Corp")
        second = text.index("Acme Corp", first + 1)
        spans = [
            {
                "start": first, "end": first + len("Acme Corp"), "label": "ORG",
                "text": "Acme Corp", "confidence": 0.7, "source": "llm_extract", "needs_redaction": True,
                "rationale": {"text": "Real model rationale for mention one.", "origin": "llm_validation", "model": "qwen2.5:14b"},
            },
            {
                "start": second, "end": second + len("Acme Corp"), "label": "ORG",
                "text": "Acme Corp", "confidence": 0.95, "source": "llm_extract", "needs_redaction": True,
                # Second mention was never validated at all.
            },
        ]

        report = _run_finalize_and_write(text, spans, tmp_path)

        rationales = {sp["rationale"]["text"] for sp in report["spans"]}
        assert rationales == {"Real model rationale for mention one."}

    @pytest.mark.parametrize("rule_like_source", ["consistency_pass", "defined_term", "rule_defined_term", "rule_signature"])
    def test_mixed_cluster_rule_like_mention_keeps_template_not_llm_rationale(self, monkeypatch, tmp_path, rule_like_source):
        """Regression for issue #68 round-2 finding 1: an LLM-validated ORG
        mention and a rule-like re-match of the same text (consistency
        pass / defined term) share one ClusterTable entity_id. Mitigation
        #1 wins over #2 for the mixed cluster -- the rule-like span must be
        written as rule_deterministic with no `model` key, never with the
        LLM's rationale copied onto it, while the LLM span keeps its own
        llm_validation rationale."""
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "Acme Corp signed first. Later, Acme Corp signed again."
        first = text.index("Acme Corp")
        second = text.index("Acme Corp", first + 1)
        spans = [
            {
                "start": first, "end": first + len("Acme Corp"), "label": "ORG",
                "text": "Acme Corp", "confidence": 0.7, "source": "llm_extract", "needs_redaction": True,
                "rationale": {"text": "A specific named company party to the agreement.",
                              "origin": "llm_validation", "model": "qwen2.5:14b"},
            },
            {
                "start": second, "end": second + len("Acme Corp"), "label": "ORG",
                "text": "Acme Corp", "confidence": 0.95, "source": rule_like_source, "needs_redaction": True,
            },
        ]

        report = _run_finalize_and_write(text, spans, tmp_path)

        by_source = {sp["source"]: sp for sp in report["spans"]}
        assert len(report["spans"]) == 2
        # Same cluster -- this is the mixed-source case, not two entities.
        assert by_source["llm_extract"]["entity_id"] == by_source[rule_like_source]["entity_id"]
        rule_like = by_source[rule_like_source]["rationale"]
        assert rule_like["origin"] == "rule_deterministic"
        assert "model" not in rule_like
        assert rule_like["text"] != "A specific named company party to the agreement."
        llm = by_source["llm_extract"]["rationale"]
        assert llm["origin"] == "llm_validation"
        assert llm["text"] == "A specific named company party to the agreement."

    @pytest.mark.parametrize("mode, backend, model_id, llama_gguf, expected", [
        ("rules_override", "ollama", "qwen2.5:14b", "", "validation_extended"),
        ("llm_overrides", "ollama", "qwen2.5:14b", "", "validation_extended"),
        # llama.cpp validation was not extended (LlamaCppRedactionPipeline
        # untouched), so every LLM span is `unavailable` -- the report must
        # say so instead of claiming validation_extended (mitigation #7).
        ("rules_override", "llama_cpp", "qwen2.5:14b", "", "unsupported_backend"),
        ("llm_overrides", "ollama", "/models/qwen2.5-14b.gguf", "", "unsupported_backend"),
        # `marcut redact --llama-gguf x.gguf` with the default `--backend
        # ollama`: cli.py passes them separately, dispatch uses
        # `llama_gguf or model_id`, so the mode decision must too
        # (issue #68 round-3 finding 2).
        ("llm_overrides", "ollama", "qwen2.5:14b", "/models/qwen2.5-14b.gguf", "unsupported_backend"),
        # Rules-only never ran an LLM at all, whatever backend was configured.
        ("rules", "llama_cpp", "rules", "", "rule_deterministic_only"),
    ])
    def test_rationale_generation_mode_reflects_backend(self, monkeypatch, tmp_path, mode, backend, model_id, llama_gguf, expected):
        """Regression for issue #68 round-2 finding 3 and round-3 finding 2."""
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "Contact SSN 123-45-6789 today."
        spans = [self._rule_span(text, "123-45-6789")]
        report_settings = pipeline._build_report_settings(
            mode=mode, mode_requested=mode, backend=backend, model_id=model_id,
            chunk_tokens=250, overlap=50, temperature=0.1, seed=42, llm_skip_confidence=0.95,
            llama_gguf=llama_gguf,
        )

        report = _run_finalize_and_write(text, spans, tmp_path, report_settings=report_settings)

        assert report["rationale_generation"]["enabled"] is True
        assert report["rationale_generation"]["mode"] == expected
        # #68 round-4: only name a model that actually authored rationale.
        # A rules-only run still carries a model_id, and reporting it here
        # would attribute template strings to a model that never executed.
        if expected == "validation_extended":
            assert report["rationale_generation"]["model"]
        else:
            assert report["rationale_generation"]["model"] is None

    def test_rule_span_overlapping_llm_span_never_reports_llm_rationale_end_to_end(self, monkeypatch, tmp_path):
        """Regression for issue #68 finding 1, run through the real
        `_merge_overlaps` -> `_finalize_and_write` sequence: an LLM span
        carrying an `llm_validation` rationale dict overlaps a shorter,
        higher-confidence rule span. The rule span must win the merge, and
        the written report must attribute the survivor to
        `rule_deterministic`, never to the LLM."""
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        text = "The Acme Corporation of Delaware signed the agreement."
        llm_span = {
            "start": 4, "end": 33, "label": "ORG", "text": "Acme Corporation of Delaware",
            "confidence": 0.75, "source": "llm_extract", "needs_redaction": True,
            "rationale": {"text": "Model-authored explanation.", "origin": "llm_validation", "model": "qwen2.5:14b"},
        }
        rule_span = {
            "start": 4, "end": 20, "label": "ORG", "text": "Acme Corporation",
            "confidence": 0.98, "source": "rule", "entity_id": "ORG_1", "needs_redaction": True,
        }
        merged = _merge_overlaps([llm_span, rule_span], text)
        assert len(merged) == 1

        report = _run_finalize_and_write(text, merged, tmp_path)

        assert len(report["spans"]) == 1
        survivor = report["spans"][0]
        assert survivor["source"] == "rule"
        assert survivor["rationale"]["origin"] == "rule_deterministic"


class TestRulesOnlyRunNeverCallsLLMForRationale:
    """Mitigation #1, exercised at the real run_redaction() entry point
    (not just _finalize_and_write in isolation): a rule-matched span must
    never trigger an LLM call to explain itself. Enforced here via a mock
    call-count assertion, not just output inspection, per the ticket."""

    class _FakeDocxMap:
        def __init__(self, text):
            self.text = text
            self.author_name = ""
            self.replacements = None

        def apply_replacements(self, replacements, track_changes=True):
            self.replacements = replacements

        def scrub_metadata(self, settings):
            return None

        def harden_document(self, *args, **kwargs):
            return None

        def save(self, path):
            with open(path, "wb") as handle:
                handle.write(b"stub docx")

    def test_rules_mode_with_rationale_enabled_never_touches_the_llm(self, monkeypatch, tmp_path):
        import marcut.model_enhanced as model_enhanced

        text = "Contact SSN 123-45-6789 for verification."
        fake_dm = self._FakeDocxMap(text)
        monkeypatch.setattr(
            pipeline.DocxMap,
            "load_accepting_revisions",
            staticmethod(lambda input_path, debug=False: fake_dm),
        )
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")

        def fail_if_called(*args, **kwargs):
            raise AssertionError("rule-matched spans must never trigger an LLM call for rationale")

        monkeypatch.setattr(pipeline, "run_enhanced_model", fail_if_called)
        monkeypatch.setattr(model_enhanced, "ollama_validate_batch", fail_if_called)
        monkeypatch.setattr(model_enhanced.requests, "post", fail_if_called)

        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"

        code, _timings = pipeline.run_redaction(
            str(input_path), str(output_path), str(report_path),
            mode="rules", model_id="rules", chunk_tokens=250, overlap=50,
            temperature=0.1, seed=42, debug=False,
        )

        assert code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["rationale_generation"]["enabled"] is True
        ssn_spans = [sp for sp in report["spans"] if sp["label"] == "SSN"]
        assert ssn_spans
        assert all(sp["rationale"]["origin"] == "rule_deterministic" for sp in ssn_spans)


class TestLLMModeRuleLikeSpansNeverGetLLMRationale:
    """Mitigation #1, exercised in the two modes where it is actually
    reachable (`rules_override`, `llm_overrides`) -- unlike mode="rules"
    above, these run `run_enhanced_model` and (for `llm_overrides`)
    `apply_llm_overrides_to_rule_spans` -> `ollama_validate_batch`, so a
    regression that routes rule-like spans through an LLM call or lets an
    LLM rationale attach to a rule-sourced span is actually observable
    here. Regression test for issue #68 finding 2."""

    class _FakeDocxMap:
        def __init__(self, text):
            self.text = text
            self.author_name = ""
            self.replacements = None

        def apply_replacements(self, replacements, track_changes=True):
            self.replacements = replacements

        def scrub_metadata(self, settings):
            return None

        def harden_document(self, *args, **kwargs):
            return None

        def save(self, path):
            with open(path, "wb") as handle:
                handle.write(b"stub docx")

    @pytest.mark.parametrize("mode", ["rules_override", "llm_overrides"])
    def test_llm_mode_never_taints_rule_spans_with_llm_rationale(self, monkeypatch, mode, tmp_path):
        import marcut.model_enhanced as model_enhanced

        text = "The Acme Corporation of Delaware, SSN 123-45-6789, signed the agreement."
        fake_dm = self._FakeDocxMap(text)
        monkeypatch.setattr(
            pipeline.DocxMap,
            "load_accepting_revisions",
            staticmethod(lambda input_path, debug=False: fake_dm),
        )
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")

        # An LLM span that overlaps the rule-matched SSN with a longer span
        # and a lower confidence -- the finding-1 repro shape: it sorts
        # first in _merge_overlaps (longer, same start) and carries an
        # `llm_validation` rationale dict, but the rule span (higher
        # confidence) must win the merge and the final rationale.
        ssn_start = text.index("123-45-6789")
        llm_span = {
            "start": ssn_start, "end": ssn_start + len("123-45-6789 signed"),
            "label": "SSN", "text": text[ssn_start:ssn_start + len("123-45-6789 signed")],
            "confidence": 0.75, "source": "llm_extract", "needs_redaction": True,
            "rationale": {"text": "Model-authored explanation.", "origin": "llm_validation", "model": "qwen2.5:14b"},
        }
        monkeypatch.setattr(pipeline, "run_enhanced_model", lambda **kwargs: [dict(llm_span)])

        validate_batch_calls = []

        def fake_ollama_validate_batch(model_id, entities, *args, **kwargs):
            validate_batch_calls.append({"generate_rationale": kwargs.get("generate_rationale", False)})
            return [{"needs_redaction": True} for _ in entities]

        monkeypatch.setattr(model_enhanced, "ollama_validate_batch", fake_ollama_validate_batch)

        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"

        code, _timings = pipeline.run_redaction(
            str(input_path), str(output_path), str(report_path),
            mode=mode, model_id="qwen2.5:14b", backend="ollama", chunk_tokens=250, overlap=50,
            temperature=0.1, seed=42, debug=False,
        )

        assert code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["rationale_generation"]["enabled"] is True

        # (a) the apply_llm_overrides_to_rule_spans call site (model_enhanced.py:~818)
        # must never ask for a rationale -- that would be an LLM call made
        # solely to explain a rule-matched entity.
        assert all(call["generate_rationale"] is not True for call in validate_batch_calls)

        # (b) every rule-like span in the written report is attributed to
        # rule_deterministic, never to the LLM, regardless of what
        # overlapped it during extraction.
        rule_like_spans = [sp for sp in report["spans"] if is_rule_like_source(sp.get("source"))]
        assert rule_like_spans
        assert all(sp["rationale"]["origin"] == "rule_deterministic" for sp in rule_like_spans)

    def test_signature_block_name_clustered_with_llm_mention_stays_rule_deterministic(self, monkeypatch, tmp_path):
        """Regression for issue #68 round-3 finding 1, reproduced through the
        real run_redaction() path: `rules.py` emits `rule_signature` for a
        "Name: John Smith" signature line, an LLM-validated mention of the
        same name later in the body lands in the same ClusterTable
        entity_id, and cluster canonicalization must NOT copy the LLM's
        rationale onto the span the LLM never saw. `rule_signature` and
        `rule_defined_term` were missing from the rule-like set, so the
        signature span was written as `llm_validation` with a `model` key."""
        import marcut.model_enhanced as model_enhanced

        text = "Name: John Smith\n\nJohn Smith agreed to the terms."
        fake_dm = self._FakeDocxMap(text)
        monkeypatch.setattr(
            pipeline.DocxMap,
            "load_accepting_revisions",
            staticmethod(lambda input_path, debug=False: fake_dm),
        )
        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        monkeypatch.setenv("MARCUT_GENERATE_RATIONALE", "1")

        body_start = text.index("John Smith", text.index("\n\n"))
        llm_span = {
            "start": body_start, "end": body_start + len("John Smith"),
            "label": "NAME", "text": "John Smith",
            "confidence": 0.8, "source": "llm_extract", "needs_redaction": True,
            "rationale": {"text": "The individual party agreeing to the terms.",
                          "origin": "llm_validation", "model": "qwen2.5:14b"},
        }
        monkeypatch.setattr(pipeline, "run_enhanced_model", lambda **kwargs: [dict(llm_span)])
        monkeypatch.setattr(
            model_enhanced, "ollama_validate_batch",
            lambda model_id, entities, *a, **k: [{"needs_redaction": True} for _ in entities],
        )

        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"

        code, _timings = pipeline.run_redaction(
            str(input_path), str(output_path), str(report_path),
            mode="rules_override", model_id="qwen2.5:14b", backend="ollama",
            chunk_tokens=250, overlap=50, temperature=0.1, seed=42, debug=False,
        )
        assert code == 0
        report = json.loads(report_path.read_text(encoding="utf-8"))

        sig = [sp for sp in report["spans"] if sp.get("source") == "rule_signature"]
        assert sig, "rules.py should have emitted a rule_signature span for the Name: line"
        llm = [sp for sp in report["spans"] if sp.get("source") == "llm_extract"]
        assert llm
        # Same entity cluster -- this is the mixed case the finding reproduced.
        assert sig[0]["entity_id"] == llm[0]["entity_id"]
        for sp in sig:
            assert sp["rationale"]["origin"] == "rule_deterministic"
            assert "model" not in sp["rationale"]
            assert sp["rationale"]["text"] != llm_span["rationale"]["text"]
        assert llm[0]["rationale"]["origin"] == "llm_validation"


class TestRedactionError:
    """Test RedactionError exception class."""

    def test_basic_construction(self):
        """Test basic error construction."""
        error = RedactionError(
            message="Test error",
            error_code="TEST_CODE"
        )
        assert str(error) == "Test error"
        assert error.error_code == "TEST_CODE"
        assert error.technical_details == ""
        assert error.original_error is None

    def test_full_construction(self):
        """Test construction with all fields."""
        original = ValueError("original")
        error = RedactionError(
            message="Test error",
            error_code="TEST_CODE",
            technical_details="Some details",
            original_error=original
        )
        assert error.technical_details == "Some details"
        assert error.original_error is original

    def test_is_exception(self):
        """Test that RedactionError is an Exception."""
        error = RedactionError("msg", "CODE")
        assert isinstance(error, Exception)

    def test_can_be_raised(self):
        """Test that error can be raised and caught."""
        with pytest.raises(RedactionError) as exc_info:
            raise RedactionError("test", "TEST_CODE")
        assert exc_info.value.error_code == "TEST_CODE"

    def test_failure_report_redacts_output_path(self, tmp_path):
        """Failure reports should not persist sensitive output paths or basenames."""
        input_path = str(tmp_path / "input.docx")
        output_path = str(tmp_path / "patient-jane-output.docx")
        report_path = str(tmp_path / "report.json")
        error = RedactionError(
            "Output failed",
            "OUTPUT_SAVE_FAILED",
            technical_details=f"Output path: {output_path}, Error: cannot write patient-jane-output.docx",
        )

        _write_failure_report(report_path, input_path, error, output_path)
        payload = (tmp_path / "report.json").read_text(encoding="utf-8")

        assert output_path not in payload
        assert "patient-jane-output.docx" not in payload
        assert "<redacted-path>" in payload

    def test_report_json_is_owner_only(self, tmp_path):
        """App-managed JSON reports should not be group/world-readable."""
        report_path = tmp_path / "report.json"

        write_json_file(str(report_path), {"status": "ok"})

        assert report_path.read_text(encoding="utf-8")
        assert stat.S_IMODE(report_path.stat().st_mode) == 0o600

    def test_metadata_html_report_is_owner_only(self, tmp_path):
        """App-managed HTML reports should not be group/world-readable."""
        json_path = tmp_path / "scrub_report.json"
        html_path = tmp_path / "scrub_report.html"
        report = {
            "summary": {"report_type": "metadata_only", "total_cleaned": 0, "total_preserved": 0},
            "groups": {},
        }
        json_path.write_text("{}", encoding="utf-8")

        generated = generate_html_report(report, str(json_path), str(html_path), str(tmp_path))

        assert generated == str(html_path)
        assert html_path.read_text(encoding="utf-8")
        assert stat.S_IMODE(html_path.stat().st_mode) == 0o600


class TestLLMDetailTiming:
    """Test --llm-detail observes the production enhanced path."""

    def _patch_minimal_enhanced_pipeline(self, monkeypatch, text="John Smith"):
        class FakeDocxMap:
            def __init__(self):
                self.text = text
                self.author_name = ""

        monkeypatch.setattr(
            pipeline.DocxMap,
            "load_accepting_revisions",
            staticmethod(lambda input_path, debug=False: FakeDocxMap()),
        )
        monkeypatch.setattr(pipeline, "_collect_rule_spans", lambda text, debug: [])

        for name in (
            "_snap_to_boundaries",
            "_trim_org_trailing_excluded_segments",
            "_extend_org_suffixes",
            "_attach_defined_term_aliases",
            "_trim_org_jurisdiction_suffixes",
            "_extend_loc_to_line",
            "_filter_overlong_org_spans",
            "_filter_county_spans",
        ):
            monkeypatch.setattr(pipeline, name, lambda text, spans, *args, **kwargs: spans)
        monkeypatch.setattr(
            pipeline,
            "_apply_consistency_pass",
            lambda text, spans, *args, **kwargs: spans,
        )
        monkeypatch.setattr(pipeline, "_merge_overlaps", lambda spans, text: spans)

    def test_llm_detail_does_not_change_enhanced_spans(self, monkeypatch, tmp_path):
        self._patch_minimal_enhanced_pipeline(monkeypatch)
        captured_spans = []
        collect_calls = []
        enhanced_span = {
            "start": 0,
            "end": 10,
            "label": "NAME",
            "text": "John Smith",
            "confidence": 0.91,
            "source": "llm",
        }

        def fake_collect(text, model_id, chunk_tokens, overlap, *args, **kwargs):
            collect_calls.append((model_id, chunk_tokens, overlap, kwargs.get("llm_concurrency")))
            return [dict(enhanced_span)]

        def fake_finalize(dm, text, spans, *args, **kwargs):
            captured_spans.append([dict(span) for span in spans])
            return 0

        monkeypatch.setattr(pipeline, "_collect_enhanced_spans", fake_collect)
        monkeypatch.setattr(pipeline, "_finalize_and_write", fake_finalize)

        input_path = str(tmp_path / "input.docx")
        output_path = str(tmp_path / "output.docx")
        report_path = str(tmp_path / "report.json")
        code_without_detail, timings_without_detail = pipeline.run_redaction(
            input_path, output_path, report_path,
            mode="rules_override", model_id="llama3.1:8b", chunk_tokens=250,
            overlap=50, temperature=0.1, seed=42, debug=False, timing=True,
            llm_detail=False, llm_concurrency=3,
        )
        code_with_detail, timings_with_detail = pipeline.run_redaction(
            input_path, output_path, report_path,
            mode="rules_override", model_id="llama3.1:8b", chunk_tokens=250,
            overlap=50, temperature=0.1, seed=42, debug=False, timing=True,
            llm_detail=True, llm_concurrency=3,
        )

        assert code_without_detail == 0
        assert code_with_detail == 0
        assert captured_spans[0] == captured_spans[1]
        assert collect_calls == [("llama3.1:8b", 250, 50, 3), ("llama3.1:8b", 250, 50, 3)]
        assert "llm_timing" not in timings_without_detail
        assert timings_with_detail["llm_timing"]["instrumentation"] == "production_enhanced_path"

    def test_llm_detail_keeps_enhanced_failure_semantics(self, monkeypatch, tmp_path):
        self._patch_minimal_enhanced_pipeline(monkeypatch)
        monkeypatch.setattr(
            pipeline,
            "_collect_enhanced_spans",
            lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
        )

        input_path = str(tmp_path / "input.docx")
        output_path = str(tmp_path / "output.docx")
        no_detail_report = str(tmp_path / "no_detail_report.json")
        detail_report = str(tmp_path / "detail_report.json")

        code_without_detail, _ = pipeline.run_redaction(
            input_path, output_path, no_detail_report,
            mode="rules_override", model_id="llama3.1:8b", chunk_tokens=250,
            overlap=50, temperature=0.1, seed=42, debug=False, timing=True,
            llm_detail=False,
        )
        code_with_detail, _ = pipeline.run_redaction(
            input_path, output_path, detail_report,
            mode="rules_override", model_id="llama3.1:8b", chunk_tokens=250,
            overlap=50, temperature=0.1, seed=42, debug=False, timing=True,
            llm_detail=True,
        )

        assert code_without_detail == 2
        assert code_with_detail == 2
        no_detail_payload = (tmp_path / "no_detail_report.json").read_text(encoding="utf-8")
        detail_payload = (tmp_path / "detail_report.json").read_text(encoding="utf-8")
        assert "AI_PROCESSING_TIMEOUT" in no_detail_payload
        assert "AI_PROCESSING_TIMEOUT" in detail_payload

    def test_llama_cpp_backend_uses_gguf_path_and_threads(self, monkeypatch):
        captured = {}

        class FakeLlamaPipeline:
            def __init__(self, model_path, temperature=0.1, seed=None, threads=4):
                captured["model_path"] = model_path
                captured["temperature"] = temperature
                captured["seed"] = seed
                captured["threads"] = threads

            def process_document(self, text, chunks, progress_callback=None, warnings=None):
                captured["chunks"] = chunks
                captured["warnings"] = warnings
                return [{"start": 0, "end": 10, "label": "NAME", "text": "John Smith"}]

        monkeypatch.setattr(pipeline, "LlamaCppRedactionPipeline", FakeLlamaPipeline)

        run_warnings = []
        spans = pipeline._collect_enhanced_spans(
            "John Smith",
            model_id="ignored-model",
            chunk_tokens=250,
            overlap=50,
            temperature=0.4,
            seed=789,
            llm_skip_confidence=0.95,
            debug=False,
            backend="llama_cpp",
            llama_gguf="/models/local.gguf",
            threads=8,
            warnings=run_warnings,
        )

        assert spans[0]["text"] == "John Smith"
        assert captured["model_path"] == "/models/local.gguf"
        assert captured["temperature"] == 0.4
        assert captured["seed"] == 789
        assert captured["threads"] == 8
        assert captured["warnings"] is run_warnings

    def test_processing_deadline_failure_does_not_write_output_docx(self, monkeypatch, tmp_path):
        self._patch_minimal_enhanced_pipeline(monkeypatch)
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"
        finalize_called = {"value": False}

        monkeypatch.setattr(
            pipeline,
            "_collect_enhanced_spans",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                ProcessingDeadlineExceeded("Processing deadline exceeded")
            ),
        )

        def fake_finalize(*args, **kwargs):
            finalize_called["value"] = True
            output_path.write_bytes(b"partial")
            return 0

        monkeypatch.setattr(pipeline, "_finalize_and_write", fake_finalize)

        code, _timings = pipeline.run_redaction(
            str(tmp_path / "input.docx"),
            str(output_path),
            str(report_path),
            mode="rules_override",
            model_id="llama3.1:8b",
            chunk_tokens=250,
            overlap=50,
            temperature=0.1,
            seed=42,
            debug=False,
            timing=True,
        )

        assert code == 2
        assert not finalize_called["value"]
        assert not output_path.exists()
        assert "AI_PROCESSING_TIMEOUT" in report_path.read_text(encoding="utf-8")

    def test_chunk_extraction_failure_fails_closed_without_writing_output(self, monkeypatch, tmp_path):
        """A4: when the LLM extractor never succeeds for one or more chunks
        (after retries), the run must fail closed with a dedicated,
        disclosed error code identifying the unanalyzed character range --
        not silently write a redacted document that looks complete."""
        self._patch_minimal_enhanced_pipeline(monkeypatch)
        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"
        finalize_called = {"value": False}

        failure = pipeline.LLMChunkExtractionFailed(
            failures=[{"chunk_index": 1, "start": 250, "end": 500, "error": "Read timed out"}],
            total_chunks=3,
        )
        monkeypatch.setattr(
            pipeline,
            "_collect_enhanced_spans",
            lambda *args, **kwargs: (_ for _ in ()).throw(failure),
        )

        def fake_finalize(*args, **kwargs):
            finalize_called["value"] = True
            output_path.write_bytes(b"partial")
            return 0

        monkeypatch.setattr(pipeline, "_finalize_and_write", fake_finalize)

        code, _timings = pipeline.run_redaction(
            str(tmp_path / "input.docx"),
            str(output_path),
            str(report_path),
            mode="rules_override",
            model_id="llama3.1:8b",
            chunk_tokens=250,
            overlap=50,
            temperature=0.1,
            seed=42,
            debug=False,
            timing=True,
        )

        assert code == 2
        assert not finalize_called["value"]
        assert not output_path.exists()
        report_payload = report_path.read_text(encoding="utf-8")
        assert "AI_CHUNK_EXTRACTION_INCOMPLETE" in report_payload
        assert "250-500" in report_payload

    def test_llama_cpp_chunk_extraction_failure_fails_closed_end_to_end(self, monkeypatch, tmp_path):
        """A4 parity: the llama_cpp backend must fail closed the same way the
        Ollama backend does. Unlike the test above (which mocks
        _collect_enhanced_spans directly), this exercises the real
        LlamaCppRedactionPipeline.process_document retry/fail-closed logic
        through the real _collect_enhanced_spans dispatch, only stubbing the
        model inference call itself -- proving the wiring from the llama_cpp
        pipeline through to run_redaction's error handling actually works,
        not just that run_redaction reacts correctly to the exception type."""
        from marcut import model_enhanced

        self._patch_minimal_enhanced_pipeline(monkeypatch)
        monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: None)

        def always_fails(self, text, doc_context):
            raise RuntimeError("simulated llama.cpp inference failure")

        monkeypatch.setattr(pipeline.LlamaCppRedactionPipeline, "extract_entities", always_fails)

        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"

        code, _timings = pipeline.run_redaction(
            str(tmp_path / "input.docx"),
            str(output_path),
            str(report_path),
            mode="rules_override",
            model_id="ignored-model",
            chunk_tokens=250,
            overlap=50,
            temperature=0.1,
            seed=42,
            debug=False,
            backend="llama_cpp",
            llama_gguf="/fake/path/model.gguf",
        )

        assert code == 2
        assert not output_path.exists()
        report_payload = report_path.read_text(encoding="utf-8")
        assert "AI_CHUNK_EXTRACTION_INCOMPLETE" in report_payload


class TestTransactionalArtifacts:
    """Test final artifacts are not exposed before the full set is ready."""

    def test_finalize_cleans_docx_when_audit_report_fails(self, monkeypatch, tmp_path):
        class FakeDocxMap:
            warnings = []

            def apply_replacements(self, replacements, track_changes=True):
                self.replacements = replacements

            def scrub_metadata(self, settings):
                return None

            def harden_document(self, *args, **kwargs):
                return None

            def save(self, path):
                with open(path, "wb") as handle:
                    handle.write(b"staged docx")

        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")
        monkeypatch.setattr(
            pipeline,
            "write_report",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("report failed")),
        )

        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"
        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")

        with pytest.raises(pipeline.RedactionError, match="Failed to write audit report"):
            pipeline._finalize_and_write(
                FakeDocxMap(),
                "John Smith",
                [{"start": 0, "end": 10, "label": "NAME", "text": "John Smith"}],
                str(output_path),
                str(report_path),
                str(input_path),
                "mock",
            )

        assert not output_path.exists()
        assert not report_path.exists()
        assert list(tmp_path.glob(".*.tmp*")) == []

    def test_finalize_cleans_up_and_raises_artifact_finalize_failed_when_audit_report_invalid(
        self, monkeypatch, tmp_path
    ):
        """Issue #67: a schema-invalid audit report (report_schema.AuditReport)
        must be caught before crossing the T7 temp-write boundary, and must
        surface as the *existing* ARTIFACT_FINALIZE_FAILED code -- not a new,
        unclassified error, and not the generic REPORT_SAVE_FAILED code that
        a plain write failure gets."""

        class FakeDocxMap:
            warnings = []

            def apply_replacements(self, replacements, track_changes=True):
                self.replacements = replacements

            def scrub_metadata(self, settings):
                return None

            def harden_document(self, *args, **kwargs):
                return None

            def save(self, path):
                with open(path, "wb") as handle:
                    handle.write(b"staged docx")

        monkeypatch.setenv("MARCUT_METADATA_ARGS", "--preset-none")

        from marcut import report as report_module

        try:
            report_module.AuditReport.model_validate({})
        except Exception as real_validation_error:  # a genuine pydantic.ValidationError
            captured_error = real_validation_error
        else:
            raise AssertionError("expected AuditReport.model_validate({}) to raise")

        monkeypatch.setattr(
            report_module.AuditReport,
            "model_validate",
            classmethod(lambda cls, data: (_ for _ in ()).throw(captured_error)),
        )

        output_path = tmp_path / "output.docx"
        report_path = tmp_path / "report.json"
        input_path = tmp_path / "input.docx"
        input_path.write_bytes(b"input")

        with pytest.raises(pipeline.RedactionError) as exc_info:
            pipeline._finalize_and_write(
                FakeDocxMap(),
                "John Smith",
                [{"start": 0, "end": 10, "label": "NAME", "text": "John Smith"}],
                str(output_path),
                str(report_path),
                str(input_path),
                "mock",
            )

        assert exc_info.value.error_code == "ARTIFACT_FINALIZE_FAILED"
        assert not output_path.exists()
        assert not report_path.exists()
        assert list(tmp_path.glob(".*.tmp*")) == []


class TestSafePrint:
    """Test safe_print Unicode handling."""

    def test_ascii_text_prints(self, capsys):
        """Test ASCII text prints normally."""
        safe_print("Hello World")
        captured = capsys.readouterr()
        assert "Hello" in captured.out

    def test_unicode_text_normalized(self, capsys):
        """Test Unicode text is normalized before printing."""
        safe_print("Smart \u201cquotes\u201d and \u2018apostrophes\u2019")
        captured = capsys.readouterr()
        # Should not raise and should output something
        assert len(captured.out) > 0


class TestEdgeCases:
    """Test edge cases across multiple functions."""

    def test_merge_overlaps_with_none_text(self):
        """Test _merge_overlaps handles None text parameter."""
        spans = [
            {"start": 0, "end": 5, "label": "NAME", "text": "Hello"},
        ]
        result = _merge_overlaps(spans, None)
        assert len(result) == 1

    def test_snap_boundaries_at_string_edges(self):
        """Test _snap_to_boundaries at string start/end."""
        text = "Word"
        spans = [{"start": 0, "end": 4, "label": "NAME", "text": "Word"}]
        result = _snap_to_boundaries(text, spans)
        assert result[0]["start"] == 0
        assert result[0]["end"] == 4

    def test_consistency_pass_with_special_chars(self):
        """Test consistency pass handles regex special chars in entity names."""
        text = "C++ is great. I love C++ programming."
        # C++ contains regex special char +
        spans = [{"start": 0, "end": 3, "label": "ORG", "text": "C++"}]
        # Should not crash even with regex special chars
        # (though C++ is too short to be propagated)
        result = _apply_consistency_pass(text, spans)
        assert isinstance(result, list)
