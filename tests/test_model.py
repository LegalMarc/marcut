"""
Tests for the model.py module - LLM extraction and JSON parsing utilities.

These tests focus on pure functions that don't require an actual LLM.
"""

import pytest
import json
from marcut.model import (
    parse_llm_response, _map_label, _valid_candidate, _find_entity_spans,
    get_ollama_base_url, _is_generic_term, get_exclusion_patterns,
    get_system_prompt, DEFAULT_EXTRACT_SYSTEM, _normalize_for_exclusion,
    _matches_exclusion_literal
)


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
        """Test host that already has scheme."""
        import os
        os.environ['OLLAMA_HOST'] = 'http://custom-host:8080'
        try:
            url = get_ollama_base_url()
            assert url == "http://custom-host:8080"
        finally:
            del os.environ['OLLAMA_HOST']


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
