"""
Tests for specific pipeline.py fixes.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'python'))

import pytest
from marcut import pipeline

class TestPipelineFixes:
    
    def test_entity_ranks_and_merge(self):
        # 21. Add ORG/LOC to Entity Ranks & 22. Fix Aggressive Span Merging
        # Case 1: High Priority (PHONE) overlaps Low Priority (org?)
        # Actually ORG is rank 2. EMAIL is rank 3.
        # "Contact info@sample123.com"
        # Span A: "info@sample123.com", EMAIL (3)
        # Span B: "company.com", ORG (2)
        # Result: EMAIL should win. ORG swallowed or merged.
        
        spans = [
            {"start": 8, "end": 24, "label": "EMAIL", "confidence": 0.9},
            {"start": 13, "end": 24, "label": "ORG", "confidence": 0.5},
        ]
        text = "Contact info@sample123.com"
        merged = pipeline._merge_overlaps(spans, text)
        assert len(merged) == 1
        assert merged[0]["label"] == "EMAIL"
        assert merged[0]["start"] == 8
        
        # Case 2: Equal Priority, Different Confidence
        # Span A: "The Company", ORG (2), Conf 0.9
        # Span B: "Company", ORG (2), Conf 0.8
        # Result: "The Company" wins (longer & higher conf)
        spans2 = [
            {"start": 0, "end": 11, "label": "ORG", "confidence": 0.9},
            {"start": 4, "end": 11, "label": "ORG", "confidence": 0.8},
        ]
        text2 = "The Company Inc"
        merged2 = pipeline._merge_overlaps(spans2, text2)
        assert len(merged2) == 1
        assert merged2[0]["text"] == "The Company" # text update handled by logic?
        # Note: Logic updates text if provided.
        # Wait, if start 0 end 11 is "The Company".
        
    def test_snap_boundaries_punctuation(self):
        # 24. Improve _snap_to_boundaries logic
        # Text: "Visit Co-Op now"
        # Span "Co", should expand to "Co-Op"
        text = "Visit Co-Op now"
        # Span covering "Co" (indices 6-8)
        spans = [{"start": 6, "end": 8, "label": "ORG", "text": "Co"}]
        snapped = pipeline._snap_to_boundaries(text, spans)
        assert snapped[0]["text"] == "Co-Op"
        
        # Test 2: Intra-word apostrophe "John's"
        text2 = "John's House"
        # Span "John" (0-4)
        spans2 = [{"start": 0, "end": 4, "label": "NAME", "text": "John"}]
        snapped2 = pipeline._snap_to_boundaries(text2, spans2)
        # Should NOT expand to "John's" if it's possessive?
        # Actually logic includes apostrophe in word chars.
        # So it expands to "John's". Ideally we handle 's separation later or allow it.
        # Current logic allows it.
        assert snapped2[0]["text"] == "John's"

    def test_trim_trailing_delimited_dots_slashes(self):
        # 26. Add . and / to delimiters
        # "Company Name/Division"
        # If "Division" is excluded, trim it.
        text = "Company Name/Division"
        # Excluded combo needs to be mocked or we rely on real excluded list.
        # "Division" might not be in real excluded list.
        # Let's try known excluded term if any?
        # Or just test _find_last_top_level_separator directly.
        idx = pipeline._find_last_top_level_separator("Name/Title")
        assert idx == 4 # Index of '/'
        
        idx2 = pipeline._find_last_top_level_separator("Name, Inc.")
        assert idx2 == 4 # Index of ','
        
        # Test DASH surrounded by spaces
        idx3 = pipeline._find_last_top_level_separator("Name - Title")
        assert idx3 == 5 # Index of '-'
        
        # Test DASH NOT surrounded
        idx4 = pipeline._find_last_top_level_separator("Co-Op")
        assert idx4 is None 

    def test_trim_trailing_parenthetical_nested(self, monkeypatch):
        # 27. Fix nested/multiple parens
        # "Company (Type) (Former)"
        # Should find last open paren
        text = "Company (Type) (Former)"
        monkeypatch.setattr(pipeline, "_is_excluded_combo", lambda value: value == "Former")
        trimmed = pipeline._trim_trailing_parenthetical(text)
        assert trimmed == "Company (Type)"
    
    def test_tokenize_defined_term_hyphen(self):
        # 12. Hyphenated tokens
        tokens = pipeline._tokenize_defined_term("Co-Op")
        # Should return ["Co-Op"] or ["Co", "Op"]?
        # Regex: [A-Za-z0-9]+(?:['\u2019-][A-Za-z0-9]+)*
        # This matches "Co-Op" as ONE token.
        assert tokens == ["Co-Op"]
        
    def test_build_org_acronym_single_letter(self):
        # 13. Single letter tokens
        # "A Plus Corp" -> "AP"
        # "A" should be kept (Capitalized). "Plus" kept. "Corp" skipped.
        acronym = pipeline._build_org_acronym(["A", "Plus", "Corp"])
        assert acronym == "AP"
        
        # Also verify "A Corp" -> "A" (previously empty)
        acronym2 = pipeline._build_org_acronym(["A", "Corp"])
        assert acronym2 == "A"
        
    def test_consistency_pass(self):
        # 14. Optimize Consistency Pass
        # Should add a second span for the same exact ORG match, without duplicates.
        text = "Sample 123 Inc signed. Later, Sample 123 Inc confirmed."
        spans = [{"start": 0, "end": 8, "label": "ORG", "text": "Sample 123 Inc"}]

        out = pipeline._apply_consistency_pass(text, spans)
        org_spans = [sp for sp in out if sp.get("label") == "ORG" and sp.get("text") == "Sample 123 Inc"]
        assert len(org_spans) == 2
