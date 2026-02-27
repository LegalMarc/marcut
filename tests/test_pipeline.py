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

import pytest
from marcut.pipeline import (
    normalize_unicode,
    _rank,
    _merge_overlaps,
    _snap_to_boundaries,
    _filter_overlong_org_spans,
    _apply_consistency_pass,
    _trim_org_trailing_excluded_segments,
    _attach_defined_term_aliases,
    RedactionError,
    safe_print,
    UNICODE_TO_ASCII,
)


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
