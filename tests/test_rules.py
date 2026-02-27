"""
Comprehensive tests for the rules.py module.

Tests regex patterns for EMAIL, PHONE, SSN, CURRENCY, DATE, URL, ADDRESS,
and signature block name extraction.
"""

import pytest
import os
from marcut.rules import (
    run_rules, EMAIL, PHONE, SSN, CURRENCY, DATE, URL, IPV4, ADDRESS,
    SIGNATURE_NAME, INDIVIDUAL_NAME, luhn_ok, COMPANY_SUFFIX, NUMBER_BRACKET,
    _is_excluded, _is_generic_org_span, _is_excluded_combo
)


class TestEmailPattern:
    """Test EMAIL regex pattern detection."""
    
    def test_simple_email(self):
        """Test basic email detection."""
        text = "Contact me at sample123@example.com for details."
        spans = run_rules(text)
        emails = [s for s in spans if s['label'] == 'EMAIL']
        
        assert len(emails) == 1
        assert emails[0]['text'] == 'sample123@example.com'
    
    def test_email_with_subdomain(self):
        """Test email with subdomain."""
        text = "Email: sample123@mail.sample.co.uk"
        spans = run_rules(text)
        emails = [s for s in spans if s['label'] == 'EMAIL']
        
        assert len(emails) == 1
        assert emails[0]['text'] == 'sample123@mail.sample.co.uk'
    
    def test_multiple_emails(self):
        """Test multiple emails in same text."""
        text = "Primary: sample123@test.com, Secondary: sample124@other.org"
        spans = run_rules(text)
        emails = [s for s in spans if s['label'] == 'EMAIL']
        
        assert len(emails) == 2
    
    def test_email_with_plus_sign(self):
        """Test email with plus addressing."""
        text = "Use sample123+tag@example.com for filtering"
        spans = run_rules(text)
        emails = [s for s in spans if s['label'] == 'EMAIL']
        
        assert len(emails) == 1
        assert emails[0]['text'] == 'sample123+tag@example.com'


class TestPhonePattern:
    """Test PHONE regex pattern detection."""
    
    def test_us_phone_standard(self):
        """Test standard US phone format."""
        text = "Call us at (555) 123-4567"
        spans = run_rules(text)
        phones = [s for s in spans if s['label'] == 'PHONE']
        
        assert len(phones) == 1
        assert '555' in phones[0]['text']
        assert '123' in phones[0]['text']
        assert '4567' in phones[0]['text']
    
    def test_phone_with_country_code(self):
        """Test international phone with country code."""
        text = "International: +1 555-123-4567"
        spans = run_rules(text)
        phones = [s for s in spans if s['label'] == 'PHONE']
        
        assert len(phones) >= 1

    def test_international_phone_with_plus(self):
        """Test international phone formats requiring +country code."""
        text = "Office: +44 20 7123 4567"
        spans = run_rules(text)
        phones = [s for s in spans if s['label'] == 'PHONE']

        assert len(phones) >= 1
    
    def test_phone_dots_separator(self):
        """Test phone with dots as separators."""
        text = "Phone: 555.123.4567"
        spans = run_rules(text)
        phones = [s for s in spans if s['label'] == 'PHONE']
        
        assert len(phones) == 1


class TestSSNPattern:
    """Test SSN regex pattern detection."""
    
    def test_ssn_standard(self):
        """Test standard SSN format."""
        text = "SSN: 123-45-6789"
        spans = run_rules(text)
        ssns = [s for s in spans if s['label'] == 'SSN']
        
        assert len(ssns) == 1
        assert ssns[0]['text'] == '123-45-6789'
    
    def test_ssn_with_em_dash(self):
        """Test SSN with em-dash separators."""
        text = "SSN: 123–45–6789"  # em-dash
        spans = run_rules(text)
        ssns = [s for s in spans if s['label'] == 'SSN']
        
        assert len(ssns) == 1
    
    def test_not_ssn_wrong_format(self):
        """Test that wrong formats are not detected as SSN."""
        text = "Not an SSN: 12345-6789 or 123456789"
        spans = run_rules(text)
        ssns = [s for s in spans if s['label'] == 'SSN']
        
        # Should not match these
        assert len(ssns) == 0


class TestCurrencyPattern:
    """Test CURRENCY/MONEY regex pattern detection."""
    
    def test_usd_dollar_sign(self):
        """Test USD with dollar sign."""
        text = "The price is $1,234.56"
        spans = run_rules(text)
        money = [s for s in spans if s['label'] == 'MONEY']
        
        assert len(money) >= 1
    
    def test_bracketed_amount(self):
        """Test bracketed currency amounts."""
        text = "Amount: $[20,034,641.91]"
        spans = run_rules(text)
        money = [s for s in spans if s['label'] == 'MONEY']
        
        assert len(money) >= 1
    
    def test_euro_amount(self):
        """Test Euro currency."""
        text = "Price: €1.234,56"
        spans = run_rules(text)
        money = [s for s in spans if s['label'] == 'MONEY']
        
        assert len(money) >= 1
    
    def test_iso_code(self):
        """Test ISO currency codes."""
        text = "Payment: USD 5,000.00"
        spans = run_rules(text)
        money = [s for s in spans if s['label'] == 'MONEY']
        
        assert len(money) >= 1


class TestDatePattern:
    """Test DATE regex pattern detection."""
    
    def test_us_date_format(self):
        """Test US date format MM/DD/YYYY."""
        text = "Meeting on 12/25/2024"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1
        assert '12/25/2024' in dates[0]['text']
    
    def test_iso_date_format(self):
        """Test ISO date format YYYY-MM-DD."""
        text = "Date: 2024-12-25"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1
    
    def test_month_name_format(self):
        """Test date with month name."""
        text = "Due: December 25, 2024"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1
    
    def test_abbreviated_month(self):
        """Test date with abbreviated month."""
        text = "Signed: Dec 25, 2024"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1
    
    def test_ordinal_date(self):
        """Test date with ordinal suffix."""
        text = "On the 25th day of December, 2024"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1

    def test_month_placeholder_day_underscores(self):
        """Test month name with underscore placeholder day."""
        text = "Dated as of September ___, 2025"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1

    def test_month_placeholder_day_bracketed(self):
        """Test month name with bracketed placeholder day."""
        text = "Dated as of September [●], 2025"
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert len(dates) >= 1

    def test_numeric_placeholder_slash_two_digit_year(self):
        """Test numeric date with placeholder components and 2-digit year."""
        text = "Signed on __/__/25."
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert any("__/__/25" in d['text'] for d in dates)

    def test_numeric_placeholder_dash(self):
        """Test numeric date with dash separators and placeholder day."""
        text = "Dated 12-__-2025."
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert any("12-__-2025" in d['text'] for d in dates)

    def test_numeric_placeholder_dot_year_first(self):
        """Test year-first numeric placeholder date with dot separators."""
        text = "Effective 2025.[●].[●]."
        spans = run_rules(text)
        dates = [s for s in spans if s['label'] == 'DATE']
        
        assert any("2025.[●].[●]" in d['text'] for d in dates)


class TestURLPattern:
    """Test URL regex pattern detection."""
    
    def test_https_url(self):
        """Test HTTPS URL detection."""
        text = "Visit https://www.example.com/page"
        spans = run_rules(text)
        urls = [s for s in spans if s['label'] == 'URL']
        
        assert len(urls) == 1
        assert 'example.com' in urls[0]['text']
    
    def test_www_url(self):
        """Test www URL detection."""
        text = "Go to www.example.com"
        spans = run_rules(text)
        urls = [s for s in spans if s['label'] == 'URL']
        
        assert len(urls) == 1
    
    def test_url_trailing_punctuation_stripped(self):
        """Test that trailing punctuation is stripped from URLs."""
        text = "Check out https://example.com/page."
        spans = run_rules(text)
        urls = [s for s in spans if s['label'] == 'URL']
        
        assert len(urls) == 1
        assert not urls[0]['text'].endswith('.')
    
    def test_mailto_link(self):
        """Test mailto: links."""
        text = "Email: mailto:sample123@example.com"
        spans = run_rules(text)
        urls = [s for s in spans if s['label'] == 'URL']
        
        assert len(urls) >= 1


class TestIPv4Pattern:
    """Test IPv4 address detection."""
    
    def test_valid_ipv4(self):
        """Test valid IPv4 address."""
        text = "Server: 192.168.1.1"
        spans = run_rules(text)
        ips = [s for s in spans if s['label'] == 'IP']
        
        assert len(ips) == 1
        assert ips[0]['text'] == '192.168.1.1'
    
    def test_multiple_ipv4(self):
        """Test multiple IPv4 addresses."""
        text = "Primary: 10.0.0.1, Secondary: 10.0.0.2"
        spans = run_rules(text)
        ips = [s for s in spans if s['label'] == 'IP']
        
        assert len(ips) == 2


class TestAddressPattern:
    """Test ADDRESS/LOC regex pattern detection."""
    
    def test_us_address_with_zip(self):
        """Test US address with ZIP code."""
        text = "Located at 123 Main Street, New York, NY 10001"
        spans = run_rules(text)
        locs = [s for s in spans if s['label'] == 'LOC']
        
        # Should detect as address
        assert any('10001' in s['text'] for s in locs)
    
    def test_po_box(self):
        """Test PO Box detection."""
        text = "Mail to: P.O. Box 123"
        spans = run_rules(text)
        locs = [s for s in spans if s['label'] == 'LOC']
        
        assert len(locs) >= 1


class TestLuhnValidation:
    """Test Luhn algorithm for credit card validation."""
    
    def test_valid_card(self):
        """Test valid credit card number."""
        # Known valid test card number
        assert luhn_ok("4532015112830366") == True
    
    def test_invalid_card(self):
        """Test invalid credit card number."""
        assert luhn_ok("1234567890123456") == False
    
    def test_too_short(self):
        """Test number that's too short."""
        assert luhn_ok("123456789012") == False  # 12 digits


class TestNumberBracketPattern:
    """Test NUMBER_BRACKET pattern for bracketed quantities."""
    
    def test_bracketed_number(self):
        """Test bracketed number detection."""
        text = "Quantity: [2,057,103]"
        spans = run_rules(text)
        numbers = [s for s in spans if s['label'] == 'NUMBER']
        
        assert len(numbers) >= 1
        assert '[2,057,103]' in numbers[0]['text']
    
    def test_not_currency_bracket(self):
        """Test that currency-prefixed brackets are not detected as NUMBER."""
        text = "Amount: $[1,000]"
        spans = run_rules(text)
        numbers = [s for s in spans if s['label'] == 'NUMBER']
        
        # Should be detected as MONEY, not NUMBER
        assert len([n for n in numbers if '$' in n['text']]) == 0


class TestSignatureBlockExtraction:
    """Test signature block name extraction."""
    
    def test_single_name_in_signature(self):
        """Test extracting single name from signature block."""
        text = "Name: John Smith\n"
        spans = run_rules(text)
        names = [s for s in spans if s['label'] == 'NAME' and s['source'] == 'rule_signature']
        
        assert len(names) >= 1
        assert names[0]['text'] == 'John Smith'
    
    def test_individual_name_pattern(self):
        """Test individual name pattern validation."""
        assert INDIVIDUAL_NAME.match("John Smith") is not None
        assert INDIVIDUAL_NAME.match("Mary Jane Watson") is not None
        assert INDIVIDUAL_NAME.match("A. Smith") is None  # Initial not supported
        assert INDIVIDUAL_NAME.match("JOHN SMITH") is None  # All caps


class TestRuleFiltering:
    """Test MARCUT_RULE_FILTER environment variable."""
    
    def test_filter_by_label(self):
        """Test filtering rules by label."""
        text = "Email: sample123@example.com, Phone: 555-123-4567"
        
        # Set filter to only EMAIL
        os.environ['MARCUT_RULE_FILTER'] = 'EMAIL'
        try:
            spans = run_rules(text)
            labels = {s['label'] for s in spans}
            
            assert 'EMAIL' in labels
            assert 'PHONE' not in labels
        finally:
            del os.environ['MARCUT_RULE_FILTER']
    
    def test_multiple_labels_filter(self):
        """Test filtering with multiple labels."""
        text = "Email: sample123@example.com, SSN: 123-45-6789"
        
        os.environ['MARCUT_RULE_FILTER'] = 'EMAIL,SSN'
        try:
            spans = run_rules(text)
            labels = {s['label'] for s in spans}
            
            assert 'EMAIL' in labels
            assert 'SSN' in labels
        finally:
            del os.environ['MARCUT_RULE_FILTER']


class TestCompanySuffixPattern:
    """Test COMPANY_SUFFIX / ORG pattern detection."""
    
    def test_inc_company(self):
        """Test Inc. company detection."""
        text = "Contract with Sample 123 Corporation Inc."
        spans = run_rules(text)
        orgs = [s for s in spans if s['label'] == 'ORG']
        
        assert len(orgs) >= 1
    
    def test_llc_company(self):
        """Test LLC company detection."""
        text = "Partner: Sample 123 & Associates LLC"
        spans = run_rules(text)
        orgs = [s for s in spans if s['label'] == 'ORG']
        
        assert len(orgs) >= 1

    def test_org_with_unicode_apostrophe(self):
        """Test ORG detection with curly apostrophe."""
        text = "ATHLETES\u2019 PERFORMANCE, INC."
        spans = run_rules(text)
        orgs = [s for s in spans if s['label'] == 'ORG']

        assert any("ATHLETES" in org['text'] for org in orgs)

    def test_org_with_unicode_dash(self):
        """Test ORG detection with Unicode dash variant."""
        text = "ACME\u2013GLOBAL LLC"
        spans = run_rules(text)
        orgs = [s for s in spans if s['label'] == 'ORG']

        assert any("ACME" in org['text'] for org in orgs)

    def test_phone_digits_with_account_context(self):
        """Avoid labeling account numbers as PHONE in account contexts."""
        text = "Account Number 3301140347 (USD)"
        spans = run_rules(text)
        labels = {s['label'] for s in spans if "3301140347" in s['text']}

        assert "ACCOUNT" in labels
        assert "PHONE" not in labels

    def test_phone_digits_without_account_context(self):
        """Keep PHONE detection for digits-only numbers without account context."""
        text = "Call 4155551234 for details."
        spans = run_rules(text)
        assert any(s['label'] == 'PHONE' and s['text'] == '4155551234' for s in spans)


class TestRunRulesIntegration:
    """Integration tests for run_rules function."""
    
    def test_mixed_entities(self):
        """Test document with multiple entity types."""
        text = """
        Contact: sample123@example.com
        Phone: (555) 123-4567
        Amount: $10,000.00
        Date: December 25, 2024
        """
        spans = run_rules(text)
        
        labels = {s['label'] for s in spans}
        assert 'EMAIL' in labels
        assert 'PHONE' in labels
        assert 'MONEY' in labels
        assert 'DATE' in labels
    
    def test_empty_text(self):
        """Test with empty text."""
        spans = run_rules("")
        assert spans == []
    
    def test_no_entities(self):
        """Test text with no detectable entities."""
        text = "This is just plain text without any entities."
        spans = run_rules(text)
        
        # Should have no high-confidence matches
        high_conf = [s for s in spans if s['confidence'] > 0.9]
        assert len(high_conf) == 0
    
    def test_span_positions_correct(self):
        """Test that span positions are correct."""
        text = "Email: sample123@example.com"
        spans = run_rules(text)
        emails = [s for s in spans if s['label'] == 'EMAIL']
        
        if emails:
            email = emails[0]
            extracted = text[email['start']:email['end']]
            assert extracted == email['text']


class TestExclusionHelpers:
    """Test exclusion helper behavior for determiners and plurals."""

    def test_is_excluded_strips_determiners(self):
        assert _is_excluded("The Agreement") == True
        assert _is_excluded("An Agreement") == True

    def test_is_excluded_handles_plural_variants(self):
        assert _is_excluded("Agreements") == True
        assert _is_excluded("Agreement(s)") == True

    def test_is_excluded_combo_all_tokens(self):
        assert _is_excluded_combo("Company Parties") == True
        assert _is_excluded_combo("Sample 123 Parties") == False

    def test_is_generic_org_with_determiners(self):
        assert _is_generic_org_span("The Company") == True
        assert _is_generic_org_span("Certain Company") == True
        assert _is_generic_org_span("Sample 123 Company") == False


class TestSentenceBoundary:
    """Test sentence boundary detection for ORG splitting."""

    def test_sentence_boundary_improvements(self):
        from marcut.rules import _contains_sentence_boundary
        
        # Should NOT be boundaries
        assert _contains_sentence_boundary("U.S. Navy") == False
        assert _contains_sentence_boundary("Mr. Smith") == False
        assert _contains_sentence_boundary("St. John") == False
        assert _contains_sentence_boundary("Inc. A") == False
        
        # Should BE boundaries
        assert _contains_sentence_boundary("End. Start") == True
        assert _contains_sentence_boundary("Company. Then") == True
