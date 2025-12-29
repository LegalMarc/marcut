"""
Tests for the model.py module - LLM extraction and JSON parsing utilities.

These tests focus on pure functions that don't require an actual LLM.
"""

import pytest
import json
from marcut.model import (
    parse_llm_response, _map_label, _valid_candidate, _find_entity_spans,
    get_ollama_base_url, _is_generic_term, get_exclusion_patterns,
    get_system_prompt, DEFAULT_EXTRACT_SYSTEM
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
        assert _valid_candidate("Acme Corporation Inc.", "ORG") == True
        assert _valid_candidate("Smith & Associates LLC", "ORG") == True
    
    def test_boilerplate_rejected(self):
        """Test that boilerplate terms are rejected."""
        assert _valid_candidate("the Agreement", "ORG") == False
        assert _valid_candidate("Section 1", "NAME") == False
        assert _valid_candidate("Board of Directors", "ORG") == False
    
    def test_empty_string_rejected(self):
        """Test that empty strings are rejected."""
        assert _valid_candidate("", "NAME") == False
        assert _valid_candidate("   ", "ORG") == False


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
        assert _is_generic_term("Acme Inc.") == False


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
        text = "Partner: Smith & Associates, LLC"
        spans = _find_entity_spans(text, "Smith & Associates, LLC", "ORG")
        
        assert len(spans) == 1
    
    def test_case_sensitive_matching(self):
        """Test that matching is case-sensitive."""
        text = "john smith is not John Smith"
        spans = _find_entity_spans(text, "John Smith", "NAME")
        
        # Should only match the properly cased one
        assert len(spans) == 1
        assert text[spans[0]['start']:spans[0]['end']] == "John Smith"
