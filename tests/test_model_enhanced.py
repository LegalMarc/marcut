"""
Unit tests for model_enhanced.py retry behavior.
"""

import json
import time
import requests
import pytest

import marcut.model_enhanced as model_enhanced
from marcut.cancellation import ProcessingDeadlineExceeded
from marcut.model_enhanced import ollama_validate, Entity, DocumentContext


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
        time.sleep(0.4)
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
    # Deadline is 0.05s out and the hang is 0.4s; assert the interrupt fires
    # well before the full hang completes, with headroom for slower/loaded
    # CI hosts rather than a tight bound tuned to a fast local machine.
    assert time.monotonic() - started < 0.35


def test_intelligent_pipeline_sends_seed_to_chunk_extraction(monkeypatch):
    captured = {}

    def fake_extract(model_id, text, temperature=0.0, seed=42, context=None):
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
