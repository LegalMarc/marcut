"""
Tests for marcut.model_naming - the single authoritative implementation of
Ollama model-name/tag parsing and matching rules (ticket #21).

These fixtures mirror the Swift-side parity test
`MarcutAppTests.testNormalizedModelIdentifierMatchesPythonModelNaming` in
`src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift` -- if you
change a case here, update it there too (and vice versa).
"""


from marcut.model_naming import (
    ParsedModelName,
    parse_model_identifier,
    models_match,
    find_matching_model,
)


class TestParseModelIdentifier:
    def test_bare_name_defaults_to_library_and_latest_tag(self):
        assert parse_model_identifier("llama3.2") == ParsedModelName(
            library="library", model="llama3.2", tag="latest"
        )

    def test_explicit_tag_is_preserved(self):
        assert parse_model_identifier("llama3.2:3b") == ParsedModelName(
            library="library", model="llama3.2", tag="3b"
        )

    def test_user_library_prefix_is_preserved(self):
        assert parse_model_identifier("user/llama3.2:3b") == ParsedModelName(
            library="user", model="llama3.2", tag="3b"
        )

    def test_default_library_prefix_collapses(self):
        assert parse_model_identifier("library/llama3.2:3b") == ParsedModelName(
            library="library", model="llama3.2", tag="3b"
        )

    def test_registry_host_prefix_is_dropped(self):
        assert parse_model_identifier("registry.ollama.ai/library/llama3.2:3b") == ParsedModelName(
            library="library", model="llama3.2", tag="3b"
        )

    def test_registry_host_with_user_library_keeps_last_two_segments(self):
        assert parse_model_identifier("registry.ollama.ai/user/llama3.2:3b") == ParsedModelName(
            library="user", model="llama3.2", tag="3b"
        )

    def test_empty_and_whitespace_input(self):
        assert parse_model_identifier("") == ParsedModelName(
            library="library", model="", tag="latest"
        )
        assert parse_model_identifier("   ") == ParsedModelName(
            library="library", model="", tag="latest"
        )

    def test_trailing_whitespace_is_trimmed(self):
        assert parse_model_identifier("  llama3.2:3b  ") == ParsedModelName(
            library="library", model="llama3.2", tag="3b"
        )


class TestModelsMatch:
    def test_exact_match(self):
        assert models_match("llama3.1:8b", "llama3.1:8b") is True

    def test_bare_name_matches_latest_tag(self):
        # Acceptance criteria: "llama3.2" matches "llama3.2:latest"
        assert models_match("llama3.2", "llama3.2:latest") is True

    def test_bare_name_does_not_match_other_tag(self):
        # Canonical (Swift) behavior: an unspecified tag resolves to
        # "latest" -- it does not match arbitrarily-tagged installs.
        assert models_match("llama3.2", "llama3.2:3b") is False

    def test_clearly_non_matching_case(self):
        assert models_match("llama3.2", "phi4:mini-instruct") is False

    def test_no_false_positive_substring_match(self):
        # Regression guard for the bug fixed by this ticket: gui.py used to
        # do `self.model_name in n or n.startswith(base)`, which incorrectly
        # matched unrelated models sharing a prefix.
        assert models_match("llama3", "llama3.2:latest") is False
        assert models_match("llama3", "llama3-custom-eval:7b") is False

    def test_different_tags_do_not_match(self):
        assert models_match("llama3.2:3b", "llama3.2:70b") is False


class TestFindMatchingModel:
    def test_finds_match_among_candidates(self):
        candidates = ["phi4:mini-instruct", "llama3.2:latest", "mistral:7b"]
        assert find_matching_model("llama3.2", candidates) is True

    def test_no_match_returns_false(self):
        candidates = ["phi4:mini-instruct", "mistral:7b"]
        assert find_matching_model("llama3.2", candidates) is False

    def test_empty_candidates(self):
        assert find_matching_model("llama3.2", []) is False
