"""
Tests for the model.py module - LLM extraction and JSON parsing utilities.

These tests focus on pure functions that don't require an actual LLM.
"""

import pytest
import json
import threading
import time
import marcut.llm_timing as llm_timing_module
import marcut.model as model_module
from marcut.cancellation import ProcessingDeadlineExceeded
from marcut.model import (
    parse_llm_response, _map_label, _valid_candidate, _find_entity_spans,
    get_ollama_base_url, _is_generic_term, get_exclusion_patterns,
    get_system_prompt, DEFAULT_EXTRACT_SYSTEM, _normalize_for_exclusion,
    _matches_exclusion_literal, ollama_extract, OllamaStreamIncompleteError
)


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


class TestParseLLMResponse:
    """Test JSON parsing of LLM responses."""
    
    def test_parse_clean_json(self):
        """Test parsing clean JSON response."""
        response = '{"entities": [{"text": "John", "type": "NAME"}]}'
        result = parse_llm_response(response)
        
        assert 'entities' in result
        assert len(result['entities']) == 1
        assert result['entities'][0]['text'] == 'John'
    
    def test_parse_json_with_markdown(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        response = """```json
{"entities": [{"text": "Test Corp", "type": "ORG"}]}
```"""
        result = parse_llm_response(response)
        
        assert 'entities' in result
        assert result['entities'][0]['text'] == 'Test Corp'
    
    def test_parse_json_with_surrounding_text(self):
        """Test parsing JSON with surrounding explanation text."""
        response = """Here are the entities I found:

{"entities": [{"text": "Jane Doe", "type": "NAME"}]}

These are all the entities."""
        result = parse_llm_response(response)
        
        assert 'entities' in result
        assert result['entities'][0]['text'] == 'Jane Doe'
    
    def test_parse_json_with_trailing_commas(self):
        """Test parsing JSON with trailing commas (common LLM error)."""
        response = '{"entities": [{"text": "Test", "type": "NAME",},]}'
        result = parse_llm_response(response)
        
        assert 'entities' in result
    
    def test_parse_json_with_comments(self):
        """Test parsing JSON with line comments."""
        response = '''{"entities": [
            {"text": "John", "type": "NAME"} // This is a name
        ]}'''
        result = parse_llm_response(response)
        
        assert 'entities' in result
    
    def test_parse_empty_entities(self):
        """Test parsing response with no entities."""
        response = '{"entities": []}'
        result = parse_llm_response(response)
        
        assert result['entities'] == []
    
    def test_parse_invalid_json_raises(self):
        """Test that invalid JSON raises JSONDecodeError."""
        response = "This is not JSON at all"

        with pytest.raises(json.JSONDecodeError):
            parse_llm_response(response)

    def test_parse_nested_json(self):
        """Test parsing entities with nested object/array structure (Issue #42)."""
        response = json.dumps({
            "entities": [
                {
                    "text": "Sample 123 Holdings, Inc.",
                    "type": "ORG",
                    "metadata": {"aliases": ["Sample 123"], "confidence": {"score": 0.9}},
                },
                {"text": "Jane Doe", "type": "NAME"},
            ]
        })
        result = parse_llm_response(response)

        assert len(result['entities']) == 2
        assert result['entities'][0]['metadata']['confidence']['score'] == 0.9

    def test_parse_truncated_json_missing_closing_brackets(self):
        """Test tolerant repair of JSON cut off after a complete entity object
        (Issue #42: truncated LLM output, e.g. hit a token limit)."""
        response = '{"entities": [{"text": "John Smith", "type": "NAME"}'
        result = parse_llm_response(response)

        assert result['entities'][0]['text'] == 'John Smith'

    def test_parse_truncated_json_mid_string_value(self):
        """Test tolerant repair when generation is cut off mid-string."""
        response = '{"entities": [{"text": "John Smith", "type": "NAM'
        result = parse_llm_response(response)

        assert result['entities'][0]['text'] == 'John Smith'

    def test_parse_truncated_json_trailing_comma_before_cutoff(self):
        """Test tolerant repair when truncated right after a dangling comma
        between array elements."""
        response = '{"entities": [{"text": "John Smith", "type": "NAME"},'
        result = parse_llm_response(response)

        assert result['entities'][0]['text'] == 'John Smith'

    def test_parse_unrepairable_json_still_raises(self):
        """Test that a closer with nothing open (not a truncation) still
        raises JSONDecodeError rather than being silently guessed at."""
        response = '{"entities": []}}'

        with pytest.raises(json.JSONDecodeError):
            parse_llm_response(response)

    def test_parse_code_fence_with_truncated_content(self):
        """Test tolerant repair still applies inside a fenced code block."""
        response = '```json\n{"entities": [{"text": "Test Corp", "type": "ORG"}\n```'
        result = parse_llm_response(response)

        assert result['entities'][0]['text'] == 'Test Corp'


class TestMapLabel:
    """Test label normalization function."""
    
    def test_name_variants(self):
        """Test NAME label variants."""
        assert _map_label("NAME") == "NAME"
        assert _map_label("PERSON") == "NAME"
        assert _map_label("person") == "NAME"
        assert _map_label("HUMAN") == "NAME"
        assert _map_label("INDIVIDUAL") == "NAME"
    
    def test_org_variants(self):
        """Test ORG label variants."""
        assert _map_label("ORG") == "ORG"
        assert _map_label("ORGANIZATION") == "ORG"
        assert _map_label("COMPANY") == "ORG"
        assert _map_label("INSTITUTION") == "ORG"
        assert _map_label("BUSINESS") == "ORG"
    
    def test_loc_variants(self):
        """Test LOC label variants."""
        assert _map_label("LOC") == "LOC"
        assert _map_label("LOCATION") == "LOC"
        assert _map_label("GPE") == "LOC"
        assert _map_label("ADDRESS") == "LOC"
    
    def test_money_variants(self):
        """Test MONEY label variants."""
        assert _map_label("MONEY") == "MONEY"
        assert _map_label("CURRENCY") == "MONEY"
    
    def test_date_label(self):
        """Test DATE label."""
        assert _map_label("DATE") == "DATE"
    
    def test_unknown_label_returns_none(self):
        """Test that unknown labels return None."""
        assert _map_label("UNKNOWN") is None
        assert _map_label("RANDOM") is None
        assert _map_label("") is None


class TestValidCandidate:
    """Test entity candidate validation."""
    
    def test_valid_name(self):
        """Test valid person name."""
        assert _valid_candidate("John Smith", "NAME") == True
        assert _valid_candidate("Mary Jane Watson", "NAME") == True
    
    def test_single_word_name_rejected(self):
        """Test that single-word names are rejected."""
        assert _valid_candidate("John", "NAME") == False
        assert _valid_candidate("Smith", "NAME") == False
    
    def test_valid_org(self):
        """Test valid organization names."""
        assert _valid_candidate("Sample 123 Corporation Inc.", "ORG") == True
        assert _valid_candidate("Sample 123 & Associates LLC", "ORG") == True
    
    def test_boilerplate_rejected(self):
        """Test that boilerplate terms are rejected."""
        assert _valid_candidate("the Agreement", "ORG") == False
        assert _valid_candidate("Section 1", "NAME") == False
        assert _valid_candidate("Board of Directors", "ORG") == False
    
    def test_empty_string_rejected(self):
        """Test that empty strings are rejected."""
        assert _valid_candidate("", "NAME") == False
        assert _valid_candidate("   ", "ORG") == False


class TestExclusionNormalization:
    """Test exclusion normalization and singularization behavior."""

    def test_normalize_strips_determiners_and_whitespace(self):
        assert _normalize_for_exclusion("  The   Company  ") == "company"
        assert _normalize_for_exclusion("These   Delaware   Corporations") == "delaware corporations"

    def test_normalize_strips_possessive(self):
        """Issue #41: possessive suffix must be stripped so "Company's" normalizes to
        the same key as "Company"."""
        assert _normalize_for_exclusion("Company's") == "company"
        assert _normalize_for_exclusion("Company’s") == "company"  # curly apostrophe
        assert _normalize_for_exclusion("Companies'") == "companies"
        assert _normalize_for_exclusion("the Company's") == "company"

    def test_matches_exclusion_literal_singularizes(self):
        literals = {"agreement", "company"}
        assert _matches_exclusion_literal("agreements", literals) == True
        assert _matches_exclusion_literal("company(s)", literals) == True
        assert _matches_exclusion_literal("cats", literals) == False
        assert _matches_exclusion_literal("parties", {"party"}) == True

    def test_generic_term_singularization(self):
        assert _is_generic_term("The Agreements") == True
        assert _is_generic_term("A Company(s)") == True


class TestFindEntitySpans:
    """Test entity span finding in text."""
    
    def test_find_single_occurrence(self):
        """Test finding single entity occurrence."""
        text = "Contact John Smith for details."
        spans = _find_entity_spans(text, "John Smith", "NAME")
        
        assert len(spans) == 1
        assert spans[0]['start'] == 8
        assert spans[0]['end'] == 18
        assert spans[0]['label'] == "NAME"
    
    def test_find_multiple_occurrences(self):
        """Test finding multiple entity occurrences."""
        text = "John Smith met John Smith at the office."
        spans = _find_entity_spans(text, "John Smith", "NAME")
        
        assert len(spans) == 2
    
    def test_no_match_returns_empty(self):
        """Test that no match returns empty list."""
        text = "Nothing to find here."
        spans = _find_entity_spans(text, "John Smith", "NAME")
        
        assert spans == []
    
    def test_invalid_candidate_returns_empty(self):
        """Test that invalid candidates return empty list."""
        text = "The Company is located here."
        spans = _find_entity_spans(text, "the Company", "ORG")
        
        # Should be empty because "the Company" is generic
        assert spans == []


class TestGetOllamaBaseUrl:
    """Test Ollama URL construction."""
    
    def test_default_url(self):
        """Test default URL when no env var set."""
        import os
        # Save and clear any existing env var
        saved = os.environ.get('OLLAMA_HOST')
        if 'OLLAMA_HOST' in os.environ:
            del os.environ['OLLAMA_HOST']
        
        try:
            url = get_ollama_base_url()
            assert url == "http://127.0.0.1:11434"
        finally:
            if saved:
                os.environ['OLLAMA_HOST'] = saved
    
    def test_custom_host(self):
        """Test custom host from env var."""
        import os
        os.environ['OLLAMA_HOST'] = 'localhost:11435'
        try:
            url = get_ollama_base_url()
            assert url == "http://localhost:11435"
        finally:
            del os.environ['OLLAMA_HOST']
    
    def test_host_with_scheme(self):
        """Test remote host is forced to loopback by default."""
        import os
        os.environ['OLLAMA_HOST'] = 'http://custom-host:8080'
        try:
            url = get_ollama_base_url()
            assert url == "http://127.0.0.1:8080"
        finally:
            del os.environ['OLLAMA_HOST']

    def test_legacy_remote_host_override_is_ignored(self):
        """Test legacy remote Ollama override no longer disables loopback."""
        import os
        os.environ['OLLAMA_HOST'] = 'http://custom-host:8080'
        os.environ['MARCUT_ALLOW_REMOTE_OLLAMA'] = '1'
        try:
            url = get_ollama_base_url()
            assert url == "http://127.0.0.1:8080"
        finally:
            del os.environ['OLLAMA_HOST']
            del os.environ['MARCUT_ALLOW_REMOTE_OLLAMA']

    def test_remote_host_requires_developer_unsafe_override(self):
        """Test remote Ollama hosts require an explicit developer-unsafe opt-in."""
        import os
        os.environ['OLLAMA_HOST'] = 'http://custom-host:8080'
        os.environ['MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA'] = '1'
        try:
            url = get_ollama_base_url()
            assert url == "http://custom-host:8080"
        finally:
            del os.environ['OLLAMA_HOST']
            del os.environ['MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA']


class TestOllamaDiagnostics:
    """Test LLM diagnostics avoid persisting document-derived text."""

    def test_timing_path_uses_production_context_and_prediction_budget(self, monkeypatch):
        captured = {}

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": '{"entities": []}'}

        def fake_post(*args, **kwargs):
            captured.update(kwargs)
            return MockResponse()

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_REQUEST_TIMEOUT", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_NUM_PREDICT", raising=False)
        monkeypatch.delenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", raising=False)
        monkeypatch.setattr(llm_timing_module.requests, "post", fake_post)

        spans, _timing = llm_timing_module.ollama_extract_with_timing("mock-model", "Document text")
        assert spans == []
        assert captured["timeout"] == 300.0
        assert captured["json"]["options"]["num_ctx"] == 12288
        assert captured["json"]["options"]["num_predict"] == 2048

    def test_request_timeout_and_prediction_limit_are_bounded_by_default(self, monkeypatch):
        captured = {}

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": '{"entities": []}'}

        def fake_post(*args, **kwargs):
            captured.update(kwargs)
            return MockResponse()

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_REQUEST_TIMEOUT", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_NUM_PREDICT", raising=False)
        monkeypatch.delenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        assert ollama_extract("mock-model", "Document text", temperature=0.0) == []
        assert captured["timeout"] == 300.0
        assert captured["json"]["options"]["num_predict"] == 2048

    def test_request_timeout_respects_processing_deadline(self, monkeypatch):
        captured = {}

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"response": '{"entities": []}'}

        def fake_post(*args, **kwargs):
            captured.update(kwargs)
            return MockResponse()

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_REQUEST_TIMEOUT", raising=False)
        monkeypatch.delenv("MARCUT_OLLAMA_NUM_PREDICT", raising=False)
        monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() + 1.5))
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        assert ollama_extract("mock-model", "Document text", temperature=0.0) == []
        assert 0.25 <= captured["timeout"] <= 1.5

    # --- Streaming (docs/design/streaming_progress.md, Option B) --------

    def test_stream_incomplete_error_is_a_json_decode_error(self):
        """OllamaStreamIncompleteError must subclass json.JSONDecodeError so a
        dropped stream flows through the *existing* malformed-JSON
        self-correction retry rather than becoming a new failure path."""
        err = OllamaStreamIncompleteError()
        assert isinstance(err, json.JSONDecodeError)

    def test_stream_deadline_checked_per_line_not_just_at_request_start(self, monkeypatch):
        """A long generation that keeps emitting NDJSON lines well past the
        deadline must be interrupted by the per-line check_processing_deadline()
        inside the streaming loop -- not only once before the request opens,
        and not left to run for however long `done: true` takes to arrive."""
        lines_consumed = {"count": 0}

        def fake_post(*args, stream=False, **kwargs):
            assert stream is True

            def lines():
                # Many quick token deltas -- if nothing checks the deadline
                # per-line, this would run for ~2s total before `done: true`.
                for _ in range(200):
                    lines_consumed["count"] += 1
                    time.sleep(0.01)
                    yield json.dumps({"response": "x", "done": False})
                yield json.dumps({"response": "", "done": True, "eval_count": 200})

            return _FakeStreamResponse(lines())

        monkeypatch.delenv("MARCUT_OLLAMA_REQUEST_TIMEOUT", raising=False)
        monkeypatch.setenv("MARCUT_PROCESSING_DEADLINE_MONOTONIC", str(time.monotonic() + 0.15))
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        started = time.monotonic()
        with pytest.raises(ProcessingDeadlineExceeded):
            ollama_extract("mock-model", "Document text", temperature=0.0, stream=True)

        # Interrupted well before all 200 lines (~2s) would have been consumed.
        assert time.monotonic() - started < 1.0
        assert lines_consumed["count"] < 200

    def test_stream_cancel_event_stops_reading_without_further_progress(self, monkeypatch):
        """T6 invariant: once cancel_event fires mid-stream, the loop must
        stop reading immediately and must not call on_token_progress again."""
        progress_calls = []

        def fake_post(*args, **kwargs):
            def lines():
                yield json.dumps({"response": "first", "done": False})
                yield json.dumps({"response": "second", "done": False})
                yield json.dumps({"response": "third", "done": False})
                yield json.dumps({"response": "", "done": True, "eval_count": 3})

            return _FakeStreamResponse(lines())

        monkeypatch.setattr(model_module.requests, "post", fake_post)

        cancel_event = threading.Event()

        def on_token_progress(chars_so_far, eval_count_so_far):
            progress_calls.append(chars_so_far)
            if chars_so_far >= len("first"):
                cancel_event.set()

        with pytest.raises(ProcessingDeadlineExceeded):
            ollama_extract(
                "mock-model",
                "Document text",
                stream=True,
                cancel_event=cancel_event,
                on_token_progress=on_token_progress,
            )

        assert progress_calls == [len("first")]

    def test_stream_incomplete_falls_through_to_self_correction_retry(self, monkeypatch):
        """A stream that ends without `done: true` (dropped/reset connection)
        must discard the partial text and route through the *existing*
        malformed-JSON self-correction retry rather than a new failure path,
        rather than crashing or silently accepting a truncated answer."""
        calls = {"count": 0}

        def fake_post(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                def dropped_lines():
                    yield json.dumps({"response": '{"entities": [', "done": False})
                    # Connection drops here -- no `done: true` line ever arrives.

                return _FakeStreamResponse(dropped_lines())

            # Self-correction retry succeeds.
            def corrected_lines():
                yield json.dumps({
                    "response": '{"entities": [{"text": "Jane Doe", "type": "NAME"}]}',
                    "done": True,
                    "eval_count": 10,
                })

            return _FakeStreamResponse(corrected_lines())

        monkeypatch.setattr(model_module.requests, "post", fake_post)

        spans = ollama_extract("mock-model", "Contact Jane Doe for details.", stream=True)

        assert calls["count"] == 2
        assert any(s["label"] == "NAME" for s in spans)

    def test_parse_failure_omits_raw_response_from_log_and_exception(self, tmp_path, monkeypatch):
        secret = "patient@example.com"
        log_path = tmp_path / "marcut.log"

        class MockResponse:
            def __init__(self, response_text):
                self.response_text = response_text

            def raise_for_status(self):
                return None

            def json(self):
                return {"response": self.response_text}

        responses = iter([
            MockResponse(f"not json {secret}"),
            MockResponse(f"still not json {secret}"),
        ])

        def fake_post(*args, **kwargs):
            return next(responses)

        monkeypatch.setenv("MARCUT_LOG_PATH", str(log_path))
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        with pytest.raises(RuntimeError) as exc_info:
            ollama_extract("mock-model", "Document text", temperature=0.0)

        log_text = log_path.read_text(encoding="utf-8")
        assert secret not in log_text
        assert secret not in str(exc_info.value)
        assert "Raw response omitted" in log_text

    def test_truncated_first_response_recovered_without_self_correction(self, monkeypatch):
        """Issue #42: a truncated (but bracket-repairable) first response should
        parse via the tolerant-repair fallback -- no self-correction round-trip,
        and no RuntimeError."""

        class MockResponse:
            def __init__(self, response_text):
                self.response_text = response_text

            def raise_for_status(self):
                return None

            def json(self):
                return {"response": self.response_text}

        # Only one response queued: a second `.post` call (i.e. a
        # self-correction retry) would raise StopIteration and fail the test.
        responses = iter([
            MockResponse('{"entities": [{"text": "Sample 123 Inc", "type": "ORG"}'),
        ])

        def fake_post(*args, **kwargs):
            return next(responses)

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        spans = ollama_extract("mock-model", "Contact Sample 123 Inc for details.", temperature=0.0)
        assert any(s["label"] == "ORG" for s in spans)

    def test_self_corrected_response_truncated_is_still_recovered(self, monkeypatch):
        """Issue #42: if the first response is unparseable prose, the existing
        self-correction round-trip fires; if *that* corrected response is itself
        truncated, the tolerant-repair fallback must still recover it instead of
        raising RuntimeError (previously the only outcome once self-correction
        also failed to parse)."""

        class MockResponse:
            def __init__(self, response_text):
                self.response_text = response_text

            def raise_for_status(self):
                return None

            def json(self):
                return {"response": self.response_text}

        responses = iter([
            MockResponse("Sorry, I cannot comply with that request."),
            MockResponse('{"entities": [{"text": "Jane Doe", "type": "NAME"}'),
        ])

        def fake_post(*args, **kwargs):
            return next(responses)

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        spans = ollama_extract("mock-model", "Contact Jane Doe for details.", temperature=0.0)
        assert any(s["label"] == "NAME" for s in spans)

    def test_empty_response_retried_with_perturbed_seed_before_self_correction(self, monkeypatch):
        """Regression for the E2E failure streak (2026-07-10 through 07-14):
        an empty completion (not just malformed JSON) must be retried with a
        DIFFERENT seed, not the self-correction prompt at the identical seed --
        Ollama's sampling is otherwise deterministic for a fixed seed, so a
        naive retry would just reproduce the same empty output forever. Only
        two total requests should fire: the perturbed-seed retry succeeds
        directly, so the self-correction path (a third request) must never
        be reached."""

        class MockResponse:
            def __init__(self, response_text):
                self.response_text = response_text

            def raise_for_status(self):
                return None

            def json(self):
                return {"response": self.response_text}

        seeds_seen = []
        responses = iter([
            MockResponse(""),
            MockResponse('{"entities": [{"text": "Jane Doe", "type": "NAME"}]}'),
        ])

        def fake_post(*args, **kwargs):
            seeds_seen.append(kwargs["json"]["options"]["seed"])
            return next(responses)

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        spans = ollama_extract("mock-model", "Contact Jane Doe for details.", temperature=0.0, seed=42)
        assert any(s["label"] == "NAME" for s in spans)
        assert seeds_seen == [42, 43]

    def test_empty_response_still_empty_after_retry_falls_through_to_self_correction(self, monkeypatch):
        """If the perturbed-seed retry is ALSO empty, today's existing
        self-correction/fail-closed behavior must still apply -- this fix
        adds one extra chance to recover, it does not weaken the eventual
        RuntimeError guarantee when the model genuinely cannot produce output."""

        class MockResponse:
            def __init__(self, response_text):
                self.response_text = response_text

            def raise_for_status(self):
                return None

            def json(self):
                return {"response": self.response_text}

        responses = iter([
            MockResponse(""),
            MockResponse(""),
            MockResponse(""),
        ])

        def fake_post(*args, **kwargs):
            return next(responses)

        monkeypatch.delenv("OLLAMA_HOST", raising=False)
        monkeypatch.setattr(model_module.requests, "post", fake_post)

        with pytest.raises(RuntimeError, match="not valid JSON after self-correction"):
            ollama_extract("mock-model", "Contact Jane Doe for details.", temperature=0.0, seed=42)


class TestIsGenericTerm:
    """Test generic term detection."""
    
    def test_agreement_generic(self):
        """Test that 'agreement' is detected as generic."""
        assert _is_generic_term("agreement") == True
        assert _is_generic_term("Agreement") == True
    
    def test_company_generic(self):
        """Test that 'company' is detected as generic."""
        assert _is_generic_term("company") == True
        # Note: "the Company" with article is handled differently by _valid_candidate
    
    def test_board_generic(self):
        """Test that 'board' terms are generic."""
        assert _is_generic_term("board") == True
        assert _is_generic_term("Board of Directors") == True
    
    def test_real_name_not_generic(self):
        """Test that real names are not generic."""
        assert _is_generic_term("John Smith") == False
        assert _is_generic_term("Sample 123 Inc.") == False


class TestGetExclusionPatterns:
    """Test exclusion pattern loading."""
    
    def test_returns_set(self):
        """Test that function returns a set."""
        patterns = get_exclusion_patterns()
        assert isinstance(patterns, set)
    
    def test_base_patterns_included(self):
        """Test that base patterns are included."""
        patterns = get_exclusion_patterns()
        
        # Should have patterns for common terms
        assert len(patterns) > 0
        
        # Test that 'agreement' matches at least one pattern
        matched = any(p.match("agreement") for p in patterns)
        assert matched == True


class TestGetSystemPrompt:
    """Test system prompt loading."""
    
    def test_default_prompt(self):
        """Test that default prompt is returned."""
        prompt = get_system_prompt()
        
        assert DEFAULT_EXTRACT_SYSTEM in prompt or len(prompt) > 0
    
    def test_prompt_contains_expected_content(self):
        """Test that prompt contains expected content."""
        prompt = get_system_prompt()
        
        # Should contain entity type guidance
        assert "NAME" in prompt or "entities" in prompt.lower()


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_unicode_in_entity(self):
        """Test handling of unicode characters."""
        text = "Contact Jose Garcia at the office."
        spans = _find_entity_spans(text, "Jose Garcia", "NAME")
        
        # Should find the name
        assert len(spans) == 1
    
    def test_entity_with_special_chars(self):
        """Test entity with special characters."""
        text = "Partner: Sample 123 & Associates, LLC"
        spans = _find_entity_spans(text, "Sample 123 & Associates, LLC", "ORG")
        
        assert len(spans) == 1
    
    def test_case_sensitive_matching(self):
        """Test that matching is case-sensitive."""
        text = "john smith is not John Smith"
        spans = _find_entity_spans(text, "John Smith", "NAME")
        
        # Should only match the properly cased one
        assert len(spans) == 1
        assert text[spans[0]['start']:spans[0]['end']] == "John Smith"


class TestSmartSplitClean:
    """Test _smart_split_clean function."""

    def test_extracts_name_from_prefix(self):
        """Test extracting name after boilerplate prefix."""
        from marcut.model import _smart_split_clean
        
        # Common pattern: boilerplate text, then actual entity
        result = _smart_split_clean("FOR VALUE RECEIVED, Sample 123 Holdings, Inc.")
        assert result == "Sample 123 Holdings, Inc."

    def test_removes_leading_boilerplate(self):
        """Test removing leading boilerplate segment."""
        from marcut.model import _smart_split_clean
        
        result = _smart_split_clean("Company: Sample 123 Corp")
        assert "Sample 123 Corp" in result

    def test_preserves_commas_in_org_names(self):
        """Test that commas in org names are preserved."""
        from marcut.model import _smart_split_clean
        
        result = _smart_split_clean("Smith, Jones & Associates")
        assert result == "Smith, Jones & Associates"

    def test_empty_returns_none(self):
        """Test empty input returns None."""
        from marcut.model import _smart_split_clean
        
        result = _smart_split_clean("")
        assert result is None

    def test_all_boilerplate_returns_none(self):
        """Test all boilerplate text returns None."""
        from marcut.model import _smart_split_clean
        
        result = _smart_split_clean("the Agreement; the Company")
        assert result is None


class TestStripLeadingDeterminer:
    """Test _strip_leading_determiner function."""

    def test_strips_the(self):
        """Test stripping 'the'."""
        from marcut.model import _strip_leading_determiner
        
        assert _strip_leading_determiner("the Company") == "Company"
        assert _strip_leading_determiner("The Agreement") == "Agreement"

    def test_strips_a_an(self):
        """Test stripping 'a' and 'an'."""
        from marcut.model import _strip_leading_determiner
        
        assert _strip_leading_determiner("a Company") == "Company"
        assert _strip_leading_determiner("an Agreement") == "Agreement"

    def test_strips_other_determiners(self):
        """Test stripping various other determiners."""
        from marcut.model import _strip_leading_determiner
        
        assert _strip_leading_determiner("this Agreement") == "Agreement"
        assert _strip_leading_determiner("such Company") == "Company"
        assert _strip_leading_determiner("any Party") == "Party"
        assert _strip_leading_determiner("each Member") == "Member"

    def test_preserves_non_determiner_prefix(self):
        """Test that non-determiners are preserved."""
        from marcut.model import _strip_leading_determiner
        
        assert _strip_leading_determiner("John Smith") == "John Smith"
        assert _strip_leading_determiner("Sample 123 Inc") == "Sample 123 Inc"


class TestGetExclusionData:
    """Test get_exclusion_data function."""

    def test_returns_tuple(self):
        """Test that function returns a tuple of (set, list)."""
        from marcut.model import get_exclusion_data
        
        literals, patterns = get_exclusion_data()
        assert isinstance(literals, set)
        assert isinstance(patterns, list)

    def test_base_literals_included(self):
        """Test that base literals are in the set."""
        from marcut.model import get_exclusion_data
        
        literals, _ = get_exclusion_data()
        # These should be in base literals
        assert "agreement" in literals
        assert "company" in literals
        assert "board" in literals

    def test_caching_returns_same_object(self):
        """Test that caching works (returns same object on repeated calls)."""
        from marcut.model import get_exclusion_data
        
        lit1, pat1 = get_exclusion_data()
        lit2, pat2 = get_exclusion_data()
        # Should be same object due to caching
        assert lit1 is lit2
        assert pat1 is pat2
