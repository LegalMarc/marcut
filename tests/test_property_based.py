"""
Property-based invariant tests (issue #50 / B8).

For random text + random entity placements and random chunk sizes/overlaps,
these check invariants that must hold regardless of the specific input:

  - every span `_merge_overlaps()` produces satisfies text[start:end] == its
    own recorded `text` (bounds and text never drift apart);
  - `_merge_overlaps()` never returns overlapping output spans;
  - `make_chunks()` round-trips offsets: every chunk's `text` matches
    text[start:end], and chunks fully cover the input text (no gaps).

Uses a fixed, derandomized hypothesis profile (see tests/conftest.py) so runs
are reproducible/flake-free in CI, per this issue's acceptance criteria.

Note on scope: make_chunks() now clamps overlap to max_len - 1 whenever
overlap >= max_len (see chunker.py and its regression tests in
tests/test_chunker.py::TestOverlapGreaterThanOrEqualMaxLen), so it always
terminates. This file still keeps overlap < max_len out of its fuzzed input
domain regardless: an overlap right at the max_len boundary produces a
1-char sliding-window step, i.e. thousands of near-duplicate chunks for a
document of any real size -- correct but pathologically slow, and not a
configuration any real caller uses (every real caller keeps overlap
comfortably below max_len -- see chunker.py and pipeline.py's
chunk_tokens/overlap plumbing). Excluding it here keeps this property suite
fast rather than avoiding a hang.
"""

from __future__ import annotations

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st  # noqa: E402

from marcut.chunker import make_chunks, SMALL_DOC_THRESHOLD  # noqa: E402
from marcut.pipeline import _merge_overlaps  # noqa: E402

LABELS = ["EMAIL", "PHONE", "SSN", "CARD", "NAME", "ORG", "BRAND", "MONEY", "DATE", "URL"]


@st.composite
def _text_and_spans(draw, max_text_size: int = 400, max_spans: int = 10):
    """A random text plus a random list of well-formed spans over it.

    Each span's `text` is set to text[start:end] up front, mirroring how real
    detectors (rules.py, model_enhanced.py) populate spans -- so the interesting
    question for `_merge_overlaps()` is whether it *preserves* the invariant
    through merging, not whether malformed input spans get filtered (that's a
    separate defensive-filtering concern already covered by
    `_merge_overlaps`'s `valid_spans` construction).
    """
    text = draw(st.text(min_size=0, max_size=max_text_size))
    n = len(text)
    spans = []
    if n > 0:
        num_spans = draw(st.integers(min_value=0, max_value=max_spans))
        for _ in range(num_spans):
            start = draw(st.integers(min_value=0, max_value=n - 1))
            end = draw(st.integers(min_value=start + 1, max_value=n))
            label = draw(st.sampled_from(LABELS))
            confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
            spans.append({
                "start": start,
                "end": end,
                "label": label,
                "text": text[start:end],
                "confidence": confidence,
            })
    return text, spans


class TestMergeOverlapsInvariants:
    @given(_text_and_spans())
    def test_every_merged_span_text_matches_its_own_bounds(self, data):
        text, spans = data
        merged = _merge_overlaps(spans, text)
        for sp in merged:
            assert text[sp["start"]:sp["end"]] == sp["text"], (
                f"span {sp} drifted from its own [start:end) slice of the source text"
            )

    @given(_text_and_spans())
    def test_no_overlapping_output_spans(self, data):
        text, spans = data
        merged = _merge_overlaps(spans, text)
        # _merge_overlaps sorts by start position; output must already be in that
        # order, so checking adjacent pairs is sufficient to catch any overlap.
        ordered = sorted(merged, key=lambda s: s["start"])
        for a, b in zip(ordered, ordered[1:]):
            assert a["end"] <= b["start"], (
                f"overlapping merged spans survived merge: {a} overlaps {b}"
            )

    @given(_text_and_spans())
    def test_merged_spans_stay_within_text_bounds(self, data):
        text, spans = data
        merged = _merge_overlaps(spans, text)
        for sp in merged:
            assert 0 <= sp["start"] < sp["end"] <= len(text)


class TestChunkOffsetInvariants:
    @given(st.text(min_size=0, max_size=SMALL_DOC_THRESHOLD))
    def test_small_doc_round_trips_as_single_chunk(self, text):
        # Below SMALL_DOC_THRESHOLD, make_chunks() takes the single-chunk shortcut
        # regardless of max_len/overlap (chunker.py), so those parameters aren't
        # varied here -- this covers arbitrary (including unicode) content instead.
        chunks = make_chunks(text)
        assert len(chunks) == 1
        assert chunks[0]["start"] == 0
        assert chunks[0]["end"] == len(text)
        assert chunks[0]["text"] == text

    @given(
        extra_len=st.integers(min_value=1, max_value=8000),
        max_len=st.integers(min_value=50, max_value=3000),
        overlap_fraction=st.floats(min_value=0.0, max_value=0.95, allow_nan=False),
    )
    def test_large_doc_round_trips_offsets(self, extra_len, max_len, overlap_fraction):
        # Text length is pinned just over SMALL_DOC_THRESHOLD (plus a random amount)
        # so this exercises the general chunking branch every time, across a range
        # of max_len values relative to the text length (chunk larger/smaller/equal
        # to the remaining text). overlap is always < max_len, matching every real
        # caller (see module docstring) so the sliding window always advances.
        text = "The quick brown fox jumps over the lazy dog. " * ((SMALL_DOC_THRESHOLD + extra_len) // 46 + 1)
        overlap = int(max_len * overlap_fraction)

        chunks = make_chunks(text, max_len=max_len, overlap=overlap)

        assert chunks, "make_chunks must always return at least one chunk for non-empty text"
        assert chunks[0]["start"] == 0
        assert chunks[-1]["end"] == len(text)

        for chunk in chunks:
            assert text[chunk["start"]:chunk["end"]] == chunk["text"], (
                f"chunk {chunk['start']}:{chunk['end']} text doesn't match its own slice of the source"
            )

        for a, b in zip(chunks, chunks[1:]):
            # No gap between consecutive chunks: the next chunk must start at or
            # before the previous one's end (contiguous or overlapping).
            assert b["start"] <= a["end"], f"gap between chunks: {a} then {b}"
            # And chunking must make forward progress (each chunk starts later
            # than the last, so this always terminates).
            assert b["start"] > a["start"], f"chunking did not advance: {a} then {b}"
