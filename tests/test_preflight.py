"""
Tests for marcut.preflight's use of the shared marcut.model_naming rules
(ticket #21): `check_model_available` must delegate to
`marcut.model_naming.models_match` rather than any bespoke substring check.
"""

import marcut.preflight as preflight_module


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class TestCheckModelAvailable:
    def test_exact_match_via_api(self, monkeypatch):
        monkeypatch.setattr(
            preflight_module.requests,
            "get",
            lambda *a, **k: _MockResponse(200, {"models": [{"name": "llama3.1:8b"}]}),
        )
        assert preflight_module.check_model_available("llama3.1:8b") is True

    def test_bare_name_matches_latest_tag_via_api(self, monkeypatch):
        monkeypatch.setattr(
            preflight_module.requests,
            "get",
            lambda *a, **k: _MockResponse(200, {"models": [{"name": "llama3.2:latest"}]}),
        )
        assert preflight_module.check_model_available("llama3.2") is True

    def test_no_false_positive_substring_match_via_api(self, monkeypatch):
        # Regression guard: previously a requested "llama3" would incorrectly
        # match "llama3.2:latest" or "llama3-custom-eval:7b" via substring
        # containment / prefix checks.
        monkeypatch.setattr(
            preflight_module.requests,
            "get",
            lambda *a, **k: _MockResponse(
                200,
                {"models": [{"name": "llama3.2:latest"}, {"name": "llama3-custom-eval:7b"}]},
            ),
        )
        assert preflight_module.check_model_available("llama3") is False

    def test_clearly_non_matching_case_via_api(self, monkeypatch):
        monkeypatch.setattr(
            preflight_module.requests,
            "get",
            lambda *a, **k: _MockResponse(200, {"models": [{"name": "phi4:mini-instruct"}]}),
        )
        assert preflight_module.check_model_available("llama3.2") is False
