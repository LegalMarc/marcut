"""
Tests for specific rules.py fixes from code review.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'python'))

import pytest
import regex as re
from marcut import rules

class TestRulesFixes:
    
    def test_trans_table_consistency(self):
        # 6. Translation Table
        # Ensure en-dash and em-dash are handled
        text = "A\u2013B\u2014C"
        # The translation table maps \u2013 -> - and \u2014 -> -
        # (Original code mapped \u2014 to -, review noted inconsistency or missing items)
        # We will update it to map both cleanly.
        normalized = rules._normalize_rule_scan_text(text)
        assert normalized == "A-B-C"

    def test_account_context_boundary(self):
        # 7. Dynamic Context / boundary
        # Test that "account number" is detected even if abutting punctuation in a weird way?
        # Or just verify the regex is robust.
        # "My account number:123"
        text = "Checking account number: 12345"
        # We need to call internal helper if exposed, or mock usage.
        # _looks_like_account_context(text, start, end)
        # It looks BEFORE the start index.
        # Let's say "of account number: " is in the window.
        idx = text.find("12345")
        if idx == -1: pytest.fail("setup error")
        assert rules._looks_like_account_context(text, idx, idx+5)

    def test_url_punctuation(self):
        # 10. URL Regex
        # Should not capture trailing ). or ,
        text = "Visit (http://example.com)."
        # run_rules should extract just the URL
        spans = rules.run_rules(text)
        url_spans = [s for s in spans if s['label'] == 'URL']
        assert len(url_spans) == 1
        assert url_spans[0]['text'] == "http://example.com"
        
        text2 = "Contact sample123@example.com."
        spans2 = rules.run_rules(text2)
        email_spans = [s for s in spans2 if s['label'] == 'EMAIL']
        # Email has its own regex, but URL logic is similar. URL regex matches emails too sometimes?
        # Typically EMAIL label comes from EMAIL regex. URL regex handles "sample123@example.com" too if strict?
        # The fix is for URL regex specifically.
        
        text3 = "Go to google.com,"
        spans3 = rules.run_rules(text3)
        url_spans3 = [s for s in spans3 if s['label'] == 'URL']
        assert len(url_spans3) == 1
        assert url_spans3[0]['text'] == "google.com"

        text4 = "Open https://example.com/)"
        spans4 = rules.run_rules(text4)
        url_spans4 = [s for s in spans4 if s['label'] == 'URL']
        assert len(url_spans4) == 1
        assert url_spans4[0]['text'] == "https://example.com/"

        text5 = "See http://example.com]."
        spans5 = rules.run_rules(text5)
        url_spans5 = [s for s in spans5 if s['label'] == 'URL']
        assert len(url_spans5) == 1
        assert url_spans5[0]['text'] == "http://example.com"

    def test_international_suffixes(self):
        # 18. International Suffixes
        # Check if S.A.S. is detected as ORG suffix
        text = "Sample 123 S.A.S."
        # rules.COMPANY_SUFFIX is used in run_rules
        spans = rules.run_rules(text)
        org_spans = [s for s in spans if s['label'] == 'ORG']
        # It might not match "Sample 123" if it's not known, but the suffix should trigger it?
        # The COMPANY_SUFFIX regex matches "[CapWord]+ [Suffix]".
        assert any(s['text'] == "Sample 123 S.A.S." for s in org_spans)

    def test_is_generic_org_renamed(self):
        # 9. Rename
        # Verify function exists with new name
        assert hasattr(rules, '_is_generic_org_span')
        assert not hasattr(rules, '_is_generic_org')
        # Test logic
        assert rules._is_generic_org_span("The Company")
        assert not rules._is_generic_org_span("Apple Inc.")
