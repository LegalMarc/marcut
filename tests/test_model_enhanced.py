"""
Unit tests for model_enhanced.py retry behavior.
"""

import json
import re
import threading
import time
import requests
import pytest

import marcut.model_enhanced as model_enhanced
import marcut.model as model_module
from marcut.cancellation import ProcessingDeadlineExceeded
from marcut.model_enhanced import ollama_validate, Entity, DocumentContext, LlamaCppRedactionPipeline


class DummyResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _make_entity():
    return Entity(
        text="Sample 123 Inc.",
        label="ORG",
        start=0,
        end=9,
        confidence=0.8,
        needs_redaction=True,
    )


def _make_response_payload(classification="SKIP", needs_redaction=False):
    return json.dumps({
        "response": json.dumps({
            "classification": classification,
            "needs_redaction": needs_redaction,
        })
    })


def test_ollama_validate_retries_on_two_failures(monkeypatch):
    timeouts = []
    sleeps = []
    calls = {"count": 0}

    def fake_post(url, json=None, timeout=None):
        timeouts.append(timeout)
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.exceptions.Timeout("timeout")
        if calls["count"] == 2:
            return DummyResponse(500, "server error")
        return DummyResponse(200, _make_response_payload())

    monkeypatch.setattr(model_enhanced.requests, "post", fake_post)
    monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: sleeps.append(s))

    result = ollama_validate("test-model", _make_entity(), "text", DocumentContext(), temperature=0.1)

    assert result["classification"] == "SKIP"
    assert timeouts == [5, 20, 45]
    assert sleeps == [2, 5]


def test_ollama_validate_retries_on_parse_error(monkeypatch):
    timeouts = []
    sleeps = []
    parse_calls = {"count": 0}

    def fake_post(url, json=None, timeout=None):
        timeouts.append(timeout)
        return DummyResponse(200, _make_response_payload())

    def fake_parse(response_text):
        parse_calls["count"] += 1
        if parse_calls["count"] == 1:
            raise json.JSONDecodeError("bad", response_text, 0)
        return {"classification": "SKIP", "needs_redaction": False}

    monkeypatch.setattr(model_enhanced.requests, "post", fake_post)
    monkeypatch.setattr(model_enhanced, "parse_llm_response", fake_parse)
    monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: sleeps.append(s))

    result = ollama_validate("test-model", _make_entity(), "text", DocumentContext(), temperature=0.1)

    assert result["classification"] == "SKIP"
    assert timeouts == [5, 20]
    assert sleeps == [2]


def test_ollama_validate_no_retry_on_4xx(monkeypatch):
    timeouts = []
    sleeps = []

    def fake_post(url, json=None, timeout=None):
        timeouts.append(timeout)
        return DummyResponse(404, "not found")

    monkeypatch.setattr(model_enhanced.requests, "post", fake_post)
    monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError):
        ollama_validate("test-model", _make_entity(), "text", DocumentContext(), temperature=0.1)

    assert timeouts == [5]
    assert sleeps == []


def test_ollama_validate_sends_seed(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        return DummyResponse(200, _make_response_payload())

    monkeypatch.setattr(model_enhanced.requests, "post", fake_post)

    result = ollama_validate("test-model", _make_entity(), "text", DocumentContext(), temperature=0.2, seed=123)

    assert result["classification"] == "SKIP"
    assert captured["options"]["temperature"] == 0.2
    assert captured["options"]["seed"] == 123


def test_ollama_validate_respects_processing_deadline(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["timeout"] = timeout
        return DummyResponse(200, _make_response_payload())

    monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() + 1.25))
    monkeypatch.setattr(model_enhanced.requests, "post", fake_post)

    result = ollama_validate("test-model", _make_entity(), "text", DocumentContext(), temperature=0.1)

    assert result["classification"] == "SKIP"
    assert 0.25 <= captured["timeout"] <= 1.25


def test_intelligent_pipeline_rejects_expired_processing_deadline(monkeypatch):
    monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() - 0.01))
    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model", temperature=0.3, seed=456)

    with pytest.raises(ProcessingDeadlineExceeded):
        pipeline.process_document(
            "John Smith",
            [{"text": "John Smith", "start": 0, "end": 10}],
            warnings=[],
            suppressed=[],
        )


def test_intelligent_pipeline_deadline_interrupts_hanging_extraction(monkeypatch):
    calls = {"count": 0}

    def hanging_extract(*args, **kwargs):
        calls["count"] += 1
        time.sleep(1.5)
        return [{"start": 0, "end": 10, "label": "NAME"}]

    monkeypatch.setattr("marcut.model.ollama_extract", hanging_extract)
    monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() + 0.05))
    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model", temperature=0.3, seed=456)

    started = time.monotonic()
    with pytest.raises(ProcessingDeadlineExceeded):
        pipeline.process_document(
            "John Smith",
            [{"text": "John Smith", "start": 0, "end": 10}],
            warnings=[],
            suppressed=[],
        )

    assert calls["count"] == 1
    # The deadline poll loop only re-checks every `remaining_seconds()`
    # minimum floor (0.25s, see cancellation.py) regardless of how soon the
    # deadline itself expires, so the interrupt can never fire faster than
    # that floor. The hang is deliberately much longer than the floor (1.5s
    # vs 0.25s) so the assertion has real headroom for CI scheduling jitter
    # while still proving the interrupt fires well before the hang would
    # complete on its own.
    assert time.monotonic() - started < 0.75


# --- Streaming intra-chunk progress (docs/design/streaming_progress.md) -----
#
# process_single_chunk() now calls ollama_extract(..., stream=True, ...), so
# these mirror test_intelligent_pipeline_deadline_interrupts_hanging_extraction
# above but patch `requests.post` (not `ollama_extract` itself) with a fake
# NDJSON stream, so the *real* streaming loop in model.py's `_request()` runs
# end-to-end through the pipeline.

class _FakeStreamResponse:
    """Minimal stand-in for `requests.Response` when `stream=True`."""

    def __init__(self, lines):
        self._lines = lines
        self.status_code = 200

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=True):
        for line in self._lines:
            yield line

    def close(self):
        pass


def test_intelligent_pipeline_deadline_interrupts_hanging_stream(monkeypatch):
    """A stream that emits a couple of NDJSON lines and then goes silent
    (connection stalls mid-generation) must not be able to hold up the whole
    pipeline past the processing deadline -- the per-line
    check_processing_deadline() inside model.py's streaming loop must fire
    instead of waiting for `done: true` that never arrives."""
    calls = {"count": 0}

    def hanging_stream(*args, **kwargs):
        calls["count"] += 1

        def lines():
            yield json.dumps({"response": "par", "done": False})
            yield json.dumps({"response": "tial", "done": False})
            # Simulate a stalled connection: much longer than the deadline
            # below, so only a per-line deadline check (not the request's
            # own timeout, which applies per socket read) can catch this.
            time.sleep(1.5)
            yield json.dumps({"response": "", "done": True, "eval_count": 3})

        return _FakeStreamResponse(lines())

    monkeypatch.setattr(model_module.requests, "post", hanging_stream)
    monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() + 0.05))
    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model", temperature=0.3, seed=456)

    started = time.monotonic()
    with pytest.raises(ProcessingDeadlineExceeded):
        pipeline.process_document(
            "John Smith",
            [{"text": "John Smith", "start": 0, "end": 10}],
            warnings=[],
            suppressed=[],
        )

    assert calls["count"] == 1
    # Same headroom rationale as the hanging-extraction test above.
    assert time.monotonic() - started < 0.75


def test_intelligent_pipeline_stream_cancel_event_stops_without_further_progress(monkeypatch):
    """Once cancel_event fires mid-stream, the streaming loop must stop
    reading immediately and must not invoke on_token_progress again (T6:
    'cancellation must not emit progress after cancel')."""
    progress_calls = []

    def make_stream(*args, **kwargs):
        def lines():
            yield json.dumps({"response": "first", "done": False})
            # By the time this second line is read, the test's on_token_progress
            # wrapper (below) will have set the cancel_event.
            yield json.dumps({"response": "second", "done": False})
            yield json.dumps({"response": "third", "done": False})
            yield json.dumps({"response": "", "done": True, "eval_count": 3})

        return _FakeStreamResponse(lines())

    monkeypatch.setattr(model_module.requests, "post", make_stream)

    cancel_event = threading.Event()

    def on_token_progress(chars_so_far, eval_count_so_far):
        progress_calls.append(chars_so_far)
        if chars_so_far >= len("first"):
            cancel_event.set()

    with pytest.raises(ProcessingDeadlineExceeded):
        model_module.ollama_extract(
            "test-model",
            "John Smith",
            stream=True,
            cancel_event=cancel_event,
            on_token_progress=on_token_progress,
        )

    # Progress was reported for the first line, but the loop must have
    # stopped at or immediately after cancellation -- it must never reach
    # the third/fourth lines' worth of accumulated chars.
    assert progress_calls
    assert all(chars <= len("firstsecond") for chars in progress_calls)


def test_intelligent_pipeline_sends_seed_to_chunk_extraction(monkeypatch):
    captured = {}

    def fake_extract(model_id, text, temperature=0.0, seed=42, context=None, **_kwargs):
        captured["model_id"] = model_id
        captured["temperature"] = temperature
        captured["seed"] = seed
        return [{"start": 0, "end": 10, "label": "NAME"}]

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    monkeypatch.setattr(model_enhanced, "needs_validation", lambda entity, doc_context: False)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model", temperature=0.3, seed=456)
    spans = pipeline.process_document(
        "John Smith",
        [{"text": "John Smith", "start": 0, "end": 10}],
        warnings=[],
        suppressed=[],
    )

    assert spans
    assert captured == {"model_id": "test-model", "temperature": 0.3, "seed": 456}


def test_llama_cpp_pipeline_extract_entities_returns_entities(monkeypatch):
    """Regression test: extract_entities() used to build Entity(source=self.model_id),
    but __init__ never sets self.model_id (only self.model_path), so every call raised
    AttributeError. That was silently swallowed by the method's broad except handler,
    so the llama_cpp backend always returned zero entities. Stub _generate_response so
    this doesn't require the optional llama-cpp-python dependency to be installed.
    """
    pipeline = LlamaCppRedactionPipeline(model_path="/fake/path/model.gguf", temperature=0.1, seed=42)

    fake_response = json.dumps({
        "entities": [
            {"text": "John Smith", "label": "NAME", "confidence": 0.9, "needs_redaction": True}
        ]
    })
    monkeypatch.setattr(pipeline, "_generate_response", lambda prompt, max_tokens=1024: fake_response)

    doc_context = DocumentContext()
    doc_context.analyze_document("John Smith signed the agreement.")

    entities = pipeline.extract_entities("John Smith signed the agreement.", doc_context)

    assert len(entities) == 1
    entity = entities[0]
    assert entity.text == "John Smith"
    assert entity.label == "NAME"
    assert entity.source == "/fake/path/model.gguf"


def test_document_context_collects_specific_org_alias_after_formation_clause():
    text = (
        'This agreement is by and between TIME USA, LLC, a Limited Liability Company '
        'formed under the laws of Delaware ("Publisher" or "TIME").'
    )
    ctx = DocumentContext()
    ctx.analyze_document(text)

    aliases = ctx.entity_aliases.get("time usa, llc", [])
    assert "TIME" in aliases
    assert "Publisher" not in aliases


# --- A3: chunk-boundary entity handling in enhanced extraction ---------------
#
# `chunker.make_chunks` deliberately overlaps adjacent chunks so no mention is
# silently dropped at a chunk boundary. That overlap means the *same* mention
# can be extracted more than once (identically, from the shared overlap
# window, or as a full match alongside a truncated fragment when it straddles
# the boundary). These tests pin down that every such mention is reported
# exactly once, at correct document offsets, and that the invariant
# text[start:end] == entity_text is enforced rather than silently violated.

def _patch_no_validation(monkeypatch):
    """Skip LLM validation so raw extraction output flows straight to spans."""
    monkeypatch.setattr(model_enhanced, "needs_validation", lambda entity, doc_context: False)


def test_chunk_overlap_window_entity_deduplicated_to_one(monkeypatch):
    """A NAME sitting entirely inside the overlap window shared by two
    adjacent chunks is visible, in full, to both chunks -- it must still be
    reported exactly once, at the correct document offsets."""
    filler = "lorem " * 45  # 270 chars of filler before the name
    name = "John Smith"
    middle = " is a witness to this agreement, executed on this day. "
    suffix = "lorem " * 70
    text = filler + name + middle + suffix
    name_start = len(filler)
    name_end = name_start + len(name)

    chunk1 = {"start": 0, "end": 300, "text": text[0:300]}
    chunk2 = {"start": 260, "end": len(text), "text": text[260:]}
    # Sanity-check the fixture: the name must fall entirely inside the
    # overlap window, i.e. both chunks see it whole.
    assert chunk2["start"] <= name_start and name_end <= chunk1["end"]

    def fake_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        return [
            {"start": m.start(), "end": m.end(), "label": "NAME"}
            for m in re.finditer(r"\bJohn Smith\b", chunk_text)
        ]

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    _patch_no_validation(monkeypatch)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model")
    warnings = []
    spans = pipeline.process_document(text, [chunk1, chunk2], warnings=warnings, suppressed=[])

    name_spans = [s for s in spans if s["label"] == "NAME"]
    assert len(name_spans) == 1
    sp = name_spans[0]
    assert (sp["start"], sp["end"]) == (name_start, name_end)
    assert text[sp["start"]:sp["end"]] == sp["text"] == name
    assert warnings == []


def test_chunk_boundary_straddling_entity_keeps_full_span(monkeypatch):
    """A NAME that straddles the actual chunk boundary can leave a full
    mention in one chunk and a truncated fragment in the next, because the
    fragment's leading tokens fall outside the neighbor's window. The
    complete mention must win, reported exactly once."""
    filler = "lorem " * 45
    name = "John Smith"
    middle = " is a witness to this agreement, executed on this day. "
    suffix = "lorem " * 70
    text = filler + name + middle + suffix
    name_start = len(filler)
    name_end = name_start + len(name)

    chunk1 = {"start": 0, "end": 300, "text": text[0:300]}
    # chunk2 begins mid-name (right after "John "), so it only ever sees
    # the bare surname "Smith".
    chunk2_start = name_start + len("John ")
    chunk2 = {"start": chunk2_start, "end": len(text), "text": text[chunk2_start:]}
    assert text[chunk2_start:chunk2_start + 5] == "Smith"

    def fake_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        spans = [
            {"start": m.start(), "end": m.end(), "label": "NAME"}
            for m in re.finditer(r"\bJohn Smith\b", chunk_text)
        ]
        for m in re.finditer(r"\bSmith\b", chunk_text):
            if not any(s["start"] <= m.start() and m.end() <= s["end"] for s in spans):
                spans.append({"start": m.start(), "end": m.end(), "label": "NAME"})
        return spans

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    _patch_no_validation(monkeypatch)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model")
    warnings = []
    spans = pipeline.process_document(text, [chunk1, chunk2], warnings=warnings, suppressed=[])

    name_spans = [s for s in spans if s["label"] == "NAME"]
    assert len(name_spans) == 1
    sp = name_spans[0]
    assert (sp["start"], sp["end"]) == (name_start, name_end)
    assert sp["text"] == name
    assert warnings == []


def test_entities_at_document_start_and_end_of_chunks_survive(monkeypatch):
    """Entities exactly at the leading edge of the first chunk and the
    trailing edge of the last chunk must round-trip with correct offsets --
    the edge case where there is no overlap partner on the outer side."""
    head_name = "Jane Doe"
    middle = "lorem " * 60
    tail_name = "Robert Lee"
    text = head_name + " " + middle + tail_name
    tail_start = len(text) - len(tail_name)

    chunk1 = {"start": 0, "end": 150, "text": text[0:150]}
    chunk2 = {"start": 100, "end": 250, "text": text[100:250]}
    chunk3 = {"start": 200, "end": len(text), "text": text[200:]}

    def fake_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        spans = []
        for pattern in (r"\bJane Doe\b", r"\bRobert Lee\b"):
            for m in re.finditer(pattern, chunk_text):
                spans.append({"start": m.start(), "end": m.end(), "label": "NAME"})
        return spans

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    _patch_no_validation(monkeypatch)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model")
    spans = pipeline.process_document(text, [chunk1, chunk2, chunk3], warnings=[], suppressed=[])

    name_spans = sorted((s["start"], s["end"], s["text"]) for s in spans if s["label"] == "NAME")
    assert name_spans == [
        (0, len(head_name), head_name),
        (tail_start, len(text), tail_name),
    ]
    for start, end, txt in name_spans:
        assert text[start:end] == txt


def test_drop_invalid_entity_offsets_removes_and_logs_mismatches():
    """The hard invariant text[start:end] == entity.text must hold for every
    surviving entity; violations are dropped and logged rather than emitted."""
    text = "Contact John Smith regarding the matter."
    good = Entity(text="John Smith", label="NAME", start=8, end=18, confidence=0.7, needs_redaction=True)
    drifted = Entity(text="John Smith", label="NAME", start=9, end=19, confidence=0.7, needs_redaction=True)
    out_of_bounds = Entity(text="ignored", label="NAME", start=30, end=999, confidence=0.7, needs_redaction=True)

    warnings = []
    survivors = model_enhanced._drop_invalid_entity_offsets(text, [good, drifted, out_of_bounds], warnings)

    assert survivors == [good]
    assert len(warnings) == 2
    assert all(w["code"] == "LLM_ENTITY_OFFSET_MISMATCH" for w in warnings)


def test_process_document_drops_out_of_bounds_span_instead_of_corrupting_output(monkeypatch):
    """An extraction span that lands out of bounds must be dropped and
    logged, never surfaced as a corrupted entity."""
    text = "Contact John Smith today please."

    def fake_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        # An "end" far beyond the chunk (and the document) simulates a
        # drifted/corrupted span rather than a legitimate extraction.
        return [{"start": 8, "end": 999999, "label": "NAME"}]

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    _patch_no_validation(monkeypatch)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model")
    warnings = []
    spans = pipeline.process_document(
        text,
        [{"start": 0, "end": len(text), "text": text}],
        warnings=warnings,
        suppressed=[],
    )

    assert spans == []
    assert any(w["code"] == "LLM_ENTITY_OFFSET_MISMATCH" for w in warnings)


def test_dedupe_chunk_overlap_entities_prefers_redaction_then_length_then_confidence():
    """Tie-break contract for overlapping same-label entities: a positive
    redaction decision wins first (fail closed), then the longer span, then
    higher confidence."""
    # needs_redaction=True beats needs_redaction=False even though the
    # False entity is longer.
    keep_redacts = Entity(text="Smith", label="NAME", start=10, end=15, confidence=0.7, needs_redaction=True)
    skip_longer = Entity(text="Mr. Smith", label="NAME", start=6, end=15, confidence=0.7, needs_redaction=False)
    result = model_enhanced._dedupe_chunk_overlap_entities([skip_longer, keep_redacts])
    assert result == [keep_redacts]

    # Same redaction decision: longer span wins.
    short = Entity(text="Smith", label="NAME", start=10, end=15, confidence=0.9, needs_redaction=True)
    longer = Entity(text="John Smith", label="NAME", start=5, end=15, confidence=0.7, needs_redaction=True)
    result = model_enhanced._dedupe_chunk_overlap_entities([short, longer])
    assert result == [longer]

    # Same decision and length: higher confidence wins.
    low_conf = Entity(text="Smith", label="NAME", start=10, end=15, confidence=0.6, needs_redaction=True)
    high_conf = Entity(text="Smith", label="NAME", start=10, end=15, confidence=0.9, needs_redaction=True)
    result = model_enhanced._dedupe_chunk_overlap_entities([low_conf, high_conf])
    assert result == [high_conf]

    # Non-overlapping repeats of the same label/text elsewhere are untouched.
    first = Entity(text="Smith", label="NAME", start=0, end=5, confidence=0.7, needs_redaction=True)
    second = Entity(text="Smith", label="NAME", start=100, end=105, confidence=0.7, needs_redaction=True)
    result = model_enhanced._dedupe_chunk_overlap_entities([first, second])
    assert result == [first, second]


# --- A4: fail-open behavior on partial chunk failure -------------------------
#
# If the LLM extractor cannot analyze a chunk even after retries, the document
# text in that chunk's range was never scanned for PII. Marcut is a privacy
# tool, so this must fail the whole run closed (a clear, disclosed error)
# rather than silently return whatever the other chunks found while treating
# the unanalyzed range as if it were clean. A genuine deadline/cancellation
# abort is a separate, pre-existing code path and must keep surfacing as
# ProcessingDeadlineExceeded rather than being folded into this new failure.

def test_process_document_fails_closed_when_chunk_extraction_never_succeeds(monkeypatch):
    """Chunk 2 of 5 fails extraction on every retry attempt: the run must
    raise LLMChunkExtractionFailed identifying that chunk's exact
    document-coordinate character range, rather than returning spans from
    the other four chunks as if the document were fully analyzed."""
    chunks = [
        {"start": i * 100, "end": i * 100 + 20, "text": f"chunk {i} content"}
        for i in range(5)
    ]
    calls = {}

    def fake_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        calls[chunk_text] = calls.get(chunk_text, 0) + 1
        if chunk_text == "chunk 2 content":
            raise RuntimeError("simulated Ollama timeout on chunk 2")
        return []

    monkeypatch.setattr("marcut.model.ollama_extract", fake_extract)
    monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: None)

    # Sequential (llm_concurrency=1) so every chunk is deterministically
    # attempted regardless of thread scheduling.
    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model", llm_concurrency=1)
    warnings = []

    with pytest.raises(model_enhanced.LLMChunkExtractionFailed) as exc_info:
        pipeline.process_document(
            "irrelevant full-document text",
            chunks,
            warnings=warnings,
            suppressed=[],
        )

    err = exc_info.value
    assert err.total_chunks == 5
    assert len(err.failures) == 1
    failure = err.failures[0]
    assert failure["chunk_index"] == 2
    assert failure["start"] == 200
    assert failure["end"] == 220

    # (a) Processing must continue to every other chunk despite chunk 2's
    # persistent failure -- the run doesn't stop early; it fails closed only
    # once the full picture of what wasn't analyzed is known.
    assert set(calls.keys()) == {c["text"] for c in chunks}

    # (b) The failure is also recorded in `warnings` with its character
    # range, so a future opt-in "disclose and continue" path would have the
    # data it needs without re-deriving it.
    chunk_warnings = [w for w in warnings if w["code"] == "LLM_CHUNK_FAILED"]
    assert len(chunk_warnings) == 1
    assert chunk_warnings[0]["start"] == 200
    assert chunk_warnings[0]["end"] == 220


def test_process_document_deadline_exceeded_not_reclassified_as_chunk_failure(monkeypatch):
    """A deadline that elapses between a chunk's retry attempts must
    surface as ProcessingDeadlineExceeded -- never reclassified as an
    ordinary LLMChunkExtractionFailed (and certainly never swallowed as a
    successful, but partially unanalyzed, result)."""

    def failing_then_deadline_extract(model_id, chunk_text, temperature=0.0, seed=42, context=None, **_kwargs):
        # Deterministically simulate the deadline elapsing while this
        # (failed) extraction attempt was in flight, rather than relying on
        # real sleep/timing.
        monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() - 0.01))
        raise RuntimeError("transient extraction failure")

    monkeypatch.setattr("marcut.model.ollama_extract", failing_then_deadline_extract)

    pipeline = model_enhanced.IntelligentRedactionPipeline("test-model")

    with pytest.raises(ProcessingDeadlineExceeded):
        pipeline.process_document(
            "John Smith",
            [{"text": "John Smith", "start": 0, "end": 10}],
            warnings=[],
            suppressed=[],
        )


# --- A4 (llama_cpp parity): fail-closed on partial chunk failure -------------
#
# LlamaCppRedactionPipeline.extract_entities() used to catch all of its own
# exceptions and return [] -- indistinguishable from "the model found nothing
# in this chunk." Combined with process_document() never threading a
# `warnings` list through, a genuine inference/parsing failure was completely
# invisible: no warning, no error, no retry. These tests mirror the Ollama-path
# A4 fix above (IntelligentRedactionPipeline.process_document) for the
# llama_cpp backend: retry once, then fail the whole run closed via the same
# LLMChunkExtractionFailed exception, identifying the unanalyzed range.

def test_llama_cpp_extract_entities_propagates_inference_failure(monkeypatch):
    """extract_entities() must let a genuine inference/parsing failure
    propagate rather than silently returning [] -- process_document's retry
    and chunk_failures bookkeeping depends on seeing the real exception."""
    pipeline = LlamaCppRedactionPipeline(model_path="/fake/path/model.gguf", temperature=0.1, seed=42)
    monkeypatch.setattr(
        pipeline,
        "_generate_response",
        lambda prompt, max_tokens=1024: (_ for _ in ()).throw(RuntimeError("Error during inference: boom")),
    )

    doc_context = DocumentContext()
    doc_context.analyze_document("John Smith signed the agreement.")

    with pytest.raises(RuntimeError, match="boom"):
        pipeline.extract_entities("John Smith signed the agreement.", doc_context)


def test_llama_cpp_process_document_fails_closed_when_chunk_extraction_never_succeeds(monkeypatch):
    """Chunk 2 of 5 fails extraction on every retry attempt: the run must
    raise LLMChunkExtractionFailed identifying that chunk's exact
    document-coordinate character range, rather than returning spans from
    the other four chunks as if the document were fully analyzed."""
    chunks = [
        {"start": i * 100, "end": i * 100 + 20, "text": f"chunk {i} content"}
        for i in range(5)
    ]
    calls = {}

    def fake_extract_entities(chunk_text, doc_context):
        calls[chunk_text] = calls.get(chunk_text, 0) + 1
        if chunk_text == "chunk 2 content":
            raise RuntimeError("simulated llama.cpp inference failure on chunk 2")
        return []

    pipeline = LlamaCppRedactionPipeline(model_path="/fake/path/model.gguf", temperature=0.1, seed=42)
    monkeypatch.setattr(pipeline, "extract_entities", fake_extract_entities)
    monkeypatch.setattr(model_enhanced.time, "sleep", lambda s: None)

    warnings = []
    with pytest.raises(model_enhanced.LLMChunkExtractionFailed) as exc_info:
        pipeline.process_document(
            "irrelevant full-document text",
            chunks,
            warnings=warnings,
        )

    err = exc_info.value
    assert err.total_chunks == 5
    assert len(err.failures) == 1
    failure = err.failures[0]
    assert failure["chunk_index"] == 2
    assert failure["start"] == 200
    assert failure["end"] == 220

    # Every chunk must still be attempted despite chunk 2's persistent
    # failure -- the run doesn't stop early; it fails closed only once the
    # full picture of what wasn't analyzed is known.
    assert set(calls.keys()) == {c["text"] for c in chunks}

    chunk_warnings = [w for w in warnings if w["code"] == "LLM_CHUNK_FAILED"]
    assert len(chunk_warnings) == 1
    assert chunk_warnings[0]["start"] == 200
    assert chunk_warnings[0]["end"] == 220


def test_llama_cpp_process_document_deadline_exceeded_not_reclassified_as_chunk_failure(monkeypatch):
    """A deadline that elapses between a chunk's retry attempts must
    surface as ProcessingDeadlineExceeded -- never reclassified as an
    ordinary LLMChunkExtractionFailed (and certainly never swallowed as a
    successful, but partially unanalyzed, result)."""

    def failing_then_deadline_extract(chunk_text, doc_context):
        # Deterministically simulate the deadline elapsing while this
        # (failed) extraction attempt was in flight, rather than relying on
        # real sleep/timing.
        monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() - 0.01))
        raise RuntimeError("transient extraction failure")

    pipeline = LlamaCppRedactionPipeline(model_path="/fake/path/model.gguf", temperature=0.1, seed=42)
    monkeypatch.setattr(pipeline, "extract_entities", failing_then_deadline_extract)

    with pytest.raises(ProcessingDeadlineExceeded):
        pipeline.process_document(
            "John Smith",
            [{"text": "John Smith", "start": 0, "end": 10}],
            warnings=[],
        )


def test_llama_cpp_process_document_succeeds_without_failures(monkeypatch):
    """Sanity check: a fully successful run (no chunk failures) still
    returns spans normally, adjusts offsets to document coordinates, and
    does not raise."""
    def fake_extract_entities(chunk_text, doc_context):
        # Entity offsets are chunk-relative; process_document must shift
        # them into document coordinates using chunk_start.
        start = chunk_text.index("John Smith")
        return [Entity(
            text="John Smith", label="NAME", start=start, end=start + len("John Smith"),
            confidence=0.85, needs_redaction=True,
        )]

    pipeline = LlamaCppRedactionPipeline(model_path="/fake/path/model.gguf", temperature=0.1, seed=42)
    monkeypatch.setattr(pipeline, "extract_entities", fake_extract_entities)

    text = "Preamble. John Smith signed."
    chunk_start = len("Preamble. ")
    warnings = []
    spans = pipeline.process_document(
        text,
        [{"start": chunk_start, "end": len(text), "text": text[chunk_start:]}],
        warnings=warnings,
    )

    assert len(spans) == 1
    assert spans[0]["start"] == chunk_start
    assert spans[0]["text"] == "John Smith"
    assert text[spans[0]["start"]:spans[0]["end"]] == "John Smith"
    assert warnings == []
