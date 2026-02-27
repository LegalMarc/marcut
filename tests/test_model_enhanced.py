"""
Unit tests for model_enhanced.py retry behavior.
"""

import json
import requests
import pytest

import marcut.model_enhanced as model_enhanced
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
