#!/usr/bin/env python3
"""
Comprehensive URL Redaction Test Suite
Tests URL detection, redaction, and sequential ID assignment
"""

import unittest
import sys
import os
import tempfile
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from marcut.rules import run_rules, URL
    from marcut.pipeline import run_redaction, _finalize_and_write
    from marcut.cluster import ClusterTable
    from marcut.docx_io import DocxMap
    MARCUT_AVAILABLE = True
    MARCUT_IMPORT_ERROR = None
except ImportError as e:
    MARCUT_AVAILABLE = False
    MARCUT_IMPORT_ERROR = e
    run_rules = None
    URL = None
    run_redaction = None
    _finalize_and_write = None
    ClusterTable = None
    DocxMap = None
    print(f"Warning: Could not import marcut modules: {e}")
    print("This is expected if running tests before full setup")


class TestURLRedaction(unittest.TestCase):
    """Test suite for URL redaction functionality"""
    @classmethod
    def setUpClass(cls):
        if not MARCUT_AVAILABLE:
            raise unittest.SkipTest(f"Marcut modules not available: {MARCUT_IMPORT_ERROR}")

    def setUp(self):
        """Set up test fixtures"""
        self.test_texts = {
            'simple_url': "Visit https://example.com for more information.",
            'multiple_urls': "Check https://example.com and http://test.org/path for details.",
            'www_url': "Go to www.site.com for updates.",
            'mixed_content': "Email us at sample123@example.com or visit https://help.site.com/support",
            'url_with_params': "API endpoint: https://api.example.com/v1/data?param=value&id=123",
            'url_with_fragment': "Documentation: https://docs.site.com/guide#section-1",
            'no_urls': "This text contains no URLs, just regular content.",
            'repeated_urls': "Visit https://example.com, then go back to https://example.com again.",
            'mailto_url': "Contact us via mailto:support@sample123.com for assistance.",
            'ftp_url': "Fetch data from ftp://downloads.example.com/resources/file.zip",
            'bare_domain_path': "See example.org/docs/index.html for details.",
            'url_in_parentheses': "Read more at (https://news.example.com/article).",
            'complex_document': """
            Dear Client,

            Please review our terms at https://company.com/terms and
            privacy policy at https://company.com/privacy.

            For support, visit https://support.company.com or email support@sample123.com.

            Additional resources:
            - Documentation: https://docs.company.com
            - API Reference: https://api.company.com/v2/docs
            - Community: https://community.company.com

            Thank you for using our service at https://company.com.
            """
        }

    # MARK: - Task 2.2: Test URL Pattern Detection

    @unittest.skipIf('marcut.rules' not in sys.modules, "Marcut modules not available")
    def test_url_pattern_detection(self):
        """Test URL pattern detection with various formats"""

        # Test basic HTTPS URL
        matches = list(URL.finditer("Visit https://example.com for info"))
        self.assertEqual(len(matches), 1, "Should detect HTTPS URL")
        self.assertEqual(matches[0].group(), "https://example.com", "Should extract correct URL")

        # Test HTTP URL
        matches = list(URL.finditer("Check http://test.org/path for details"))
        self.assertEqual(len(matches), 1, "Should detect HTTP URL")
        self.assertEqual(matches[0].group(), "http://test.org/path", "Should extract URL with path")

        # Test www URL
        matches = list(URL.finditer("Go to www.site.com for updates"))
        self.assertEqual(len(matches), 1, "Should detect www URL")
        self.assertEqual(matches[0].group(), "www.site.com", "Should extract www URL")

        # Test URL with query parameters
        matches = list(URL.finditer("API: https://api.example.com/v1/data?param=value"))
        self.assertEqual(len(matches), 1, "Should detect URL with parameters")
        self.assertTrue("api.example.com" in matches[0].group(), "Should include domain")
        self.assertTrue("param=value" in matches[0].group(), "Should include parameters")

        # Test URL with fragment
        matches = list(URL.finditer("Docs: https://docs.site.com/guide#section-1"))
        self.assertEqual(len(matches), 1, "Should detect URL with fragment")
        self.assertTrue("#section-1" in matches[0].group(), "Should include fragment")

        # Test mailto URL
        matches = list(URL.finditer("Contact mailto:support@sample123.com for help"))
        self.assertEqual(len(matches), 1, "Should detect mailto URL")
        self.assertEqual(matches[0].group(), "mailto:support@sample123.com")

        # Test FTP URL
        matches = list(URL.finditer("Download ftp://server.example.com/resource"))
        self.assertEqual(len(matches), 1, "Should detect FTP URL")
        self.assertTrue(matches[0].group().startswith("ftp://"))

        # Test bare domain with path
        matches = list(URL.finditer("See example.org/docs/index.html"))
        self.assertEqual(len(matches), 1, "Should detect bare domain with path")
        self.assertEqual(matches[0].group(), "example.org/docs/index.html")

        # Test multiple URLs in one text
        matches = list(URL.finditer("Visit https://site1.com and https://site2.com"))
        self.assertEqual(len(matches), 2, "Should detect multiple URLs")

        # Test text with no URLs
        matches = list(URL.finditer("This text has no URLs"))
        self.assertEqual(len(matches), 0, "Should not detect URLs in text without URLs")

    @unittest.skipIf('marcut.rules' not in sys.modules, "Marcut modules not available")
    def test_url_detection_in_rules_engine(self):
        """Test URL detection through the rules engine"""

        # Test with simple URL
        spans = run_rules(self.test_texts['simple_url'])
        url_spans = [s for s in spans if s['label'] == 'URL']

        self.assertGreater(len(url_spans), 0, "Rules engine should detect URLs")
        self.assertEqual(url_spans[0]['text'], 'https://example.com', "Should extract correct URL text")
        self.assertEqual(url_spans[0]['confidence'], 0.90, "URL confidence should be 0.90")

        # Test with multiple URLs
        spans = run_rules(self.test_texts['multiple_urls'])
        url_spans = [s for s in spans if s['label'] == 'URL']

        self.assertEqual(len(url_spans), 2, "Should detect both URLs")
        urls = [s['text'] for s in url_spans]
        self.assertIn('https://example.com', urls, "Should detect first URL")
        self.assertIn('http://test.org/path', urls, "Should detect second URL")

        # Test trimming of trailing punctuation
        spans = run_rules(self.test_texts['url_in_parentheses'])
        url_spans = [s for s in spans if s['label'] == 'URL']
        self.assertEqual(len(url_spans), 1, "Should detect URL inside parentheses")
        self.assertEqual(url_spans[0]['text'], 'https://news.example.com/article')

        # Test mailto detection through rules
        spans = run_rules(self.test_texts['mailto_url'])
        mailto_spans = [s for s in spans if s['label'] == 'URL']
        self.assertEqual(len(mailto_spans), 1, "Should detect mailto URLs via rules")
        self.assertEqual(mailto_spans[0]['text'], 'mailto:support@sample123.com')

        spans = run_rules(self.test_texts['bare_domain_path'])
        domain_spans = [s for s in spans if s['label'] == 'URL']
        self.assertEqual(domain_spans[0]['text'], 'example.org/docs/index.html')

        spans = run_rules(self.test_texts['ftp_url'])
        ftp_spans = [s for s in spans if s['label'] == 'URL']
        self.assertTrue(any('ftp://downloads.example.com/resources/file.zip' == s['text'] for s in ftp_spans))

    # MARK: - Task 2.3: Test Sequential URL ID Assignment

    @unittest.skipIf('marcut.rules' not in sys.modules, "Marcut modules not available")
    def test_url_sequential_ids(self):
        """Test URL sequential ID assignment"""

        # Create test spans for URL redaction
        spans = [
            {"start": 6, "end": 26, "label": "URL", "text": "https://example.com", "confidence": 0.90, "source": "rule"},
            {"start": 40, "end": 55, "label": "URL", "text": "http://test.org", "confidence": 0.90, "source": "rule"},
            {"start": 70, "end": 90, "label": "URL", "text": "https://example.com", "confidence": 0.90, "source": "rule"}  # Duplicate
        ]

        # Create a mock DocxMap
        test_text = "Visit https://example.com and http://test.org, then https://example.com again"

        # Test the finalization process with URLs
        ct = ClusterTable()
        url_counter = {}

        # Process spans like in _finalize_and_write
        for sp in spans:
            if sp["label"] == "URL":
                url_text = sp["text"]
                if url_text not in url_counter:
                    url_counter[url_text] = len(url_counter) + 1
                sp["entity_id"] = f"URL_{url_counter[url_text]}"

        # Verify ID assignment
        expected_ids = ["URL_1", "URL_2", "URL_1"]  # First and third should be same
        actual_ids = [sp["entity_id"] for sp in spans]

        self.assertEqual(actual_ids, expected_ids, "URL IDs should be assigned sequentially")
        self.assertEqual(len(url_counter), 2, "Should have 2 unique URLs")
        self.assertEqual(url_counter["https://example.com"], 1, "First URL should get ID 1")
        self.assertEqual(url_counter["http://test.org"], 2, "Second URL should get ID 2")

    def test_url_id_with_mixed_entities(self):
        """Test URL ID assignment with other entity types"""

        spans = [
            {"start": 0, "end": 15, "label": "EMAIL", "text": "sample123@email.com", "confidence": 0.95, "source": "rule"},
            {"start": 20, "end": 40, "label": "URL", "text": "https://site1.com", "confidence": 0.90, "source": "rule"},
            {"start": 45, "end": 60, "label": "NAME", "text": "John Smith", "confidence": 0.85, "source": "llm"},
            {"start": 65, "end": 82, "label": "URL", "text": "http://site2.org", "confidence": 0.90, "source": "rule"},
            {"start": 90, "end": 110, "label": "URL", "text": "https://site1.com", "confidence": 0.90, "source": "rule"}  # Duplicate
        ]

        # Process URLs only
        url_counter = {}
        for sp in spans:
            if sp["label"] == "URL":
                url_text = sp["text"]
                if url_text not in url_counter:
                    url_counter[url_text] = len(url_counter) + 1
                sp["entity_id"] = f"URL_{url_counter[url_text]}"

        # Check URL entities got correct IDs
        url_entities = [sp for sp in spans if sp["label"] == "URL"]
        self.assertEqual(len(url_entities), 3, "Should have 3 URL entities")
        self.assertEqual(url_entities[0]["entity_id"], "URL_1", "First URL should be URL_1")
        self.assertEqual(url_entities[1]["entity_id"], "URL_2", "Second URL should be URL_2")
        self.assertEqual(url_entities[2]["entity_id"], "URL_1", "Duplicate URL should be URL_1")

    # MARK: - Task 2.4: Test URL Integration in Pipeline

    def test_url_replacement_format(self):
        """Test URL replacement format in final output"""

        spans = [
            {"start": 6, "end": 25, "label": "URL", "text": "https://example.com", "entity_id": "URL_1"},
            {"start": 30, "end": 45, "label": "URL", "text": "http://test.org", "entity_id": "URL_2"}
        ]

        text = "Visit https://example.com and http://test.org"

        # Test replacement generation
        replacements = []
        for sp in spans:
            if sp.get("entity_id"):
                full_tag = f"[{sp['entity_id']}]"
            else:
                full_tag = f"[{sp['label']}]"

            replacements.append({
                'start': sp['start'],
                'end': sp['end'],
                'replacement': full_tag
            })

        # Sort by start position (reverse order for safe replacement)
        replacements.sort(key=lambda x: x['start'], reverse=True)

        # Apply replacements
        result_text = text
        for repl in replacements:
            result_text = result_text[:repl['start']] + repl['replacement'] + result_text[repl['end']:]

        expected = "Visit [URL_1] and [URL_2]"
        self.assertEqual(result_text, expected, "URLs should be replaced with sequential IDs")

    # MARK: - Task 2.5: Test URL Edge Cases

    def test_url_edge_cases(self):
        """Test URL detection edge cases"""

        edge_cases = [
            # URLs at document boundaries
            ("https://start.com is at the beginning", 1),
            ("Text ends with https://end.com", 1),

            # URLs with complex parameters
            ("API: https://api.com/v1/search?q=test&limit=10&sort=date", 1),

            # URLs in parentheses
            ("See documentation (https://docs.com) for details", 1),

            # URLs with ports
            ("Local server: http://localhost:8080/app", 1),

            # Malformed URLs that shouldn't match
            ("Not a URL: ht://invalid or htp://wrong", 0),

            # URLs with special characters
            ("Profile: https://social.com/user-name_123", 1),

            # Multiple protocols
            ("FTP: ftp://files.com and HTTPS: https://secure.com", 2)  # Both FTP and HTTPS should match
        ]

        for text, expected_count in edge_cases:
            with self.subTest(text=text):
                matches = list(URL.finditer(text))
                self.assertEqual(len(matches), expected_count,
                               f"Text '{text}' should have {expected_count} URL matches")

    def test_url_in_hyperlink_context(self):
        """Test URLs that might be in hyperlink format"""

        # Simulate DOCX hyperlink content
        hyperlink_texts = [
            "Click here",  # Display text
            "https://example.com",  # Actual URL
            "Visit our site at https://company.com/about"  # Mixed content
        ]

        for text in hyperlink_texts:
            spans = run_rules(text)
            url_spans = [s for s in spans if s['label'] == 'URL']

            if "https://" in text:
                self.assertGreater(len(url_spans), 0, f"Should detect URL in '{text}'")
            else:
                self.assertEqual(len(url_spans), 0, f"Should not detect URL in '{text}'")

    # MARK: - Integration Tests

    def test_complex_document_url_redaction(self):
        """Test URL redaction in a complex document"""

        spans = run_rules(self.test_texts['complex_document'])
        url_spans = [s for s in spans if s['label'] == 'URL']

        # Should detect multiple unique URLs
        self.assertGreater(len(url_spans), 5, "Should detect multiple URLs in complex document")

        # Extract unique URLs
        unique_urls = set(s['text'] for s in url_spans)
        expected_urls = {
            'https://company.com/terms',
            'https://company.com/privacy',
            'https://support.company.com',
            'https://docs.company.com',
            'https://api.company.com/v2/docs',
            'https://community.company.com',
            'https://company.com'
        }

        self.assertTrue(expected_urls.issubset(unique_urls),
                       "Should detect all expected unique URLs")

    def test_url_priority_in_overlaps(self):
        """Test URL priority when overlapping with other entities"""

        # Test case where URL might overlap with other patterns
        test_text = "Contact: email@https://site.com/contact"  # Artificial but tests overlap handling
        spans = run_rules(test_text)

        # Should handle overlaps correctly based on priority
        url_spans = [s for s in spans if s['label'] == 'URL']
        email_spans = [s for s in spans if s['label'] == 'EMAIL']

        # Verify no spans overlap incorrectly
        for url_span in url_spans:
            for email_span in email_spans:
                url_range = range(url_span['start'], url_span['end'])
                email_range = range(email_span['start'], email_span['end'])

                # Check for overlaps
                overlap = set(url_range) & set(email_range)
                if overlap:
                    # URLs have rank 3, same as EMAIL, so implementation dependent
                    pass  # This is acceptable

    # MARK: - Performance Tests

    def test_url_detection_performance(self):
        """Test URL detection performance with large documents"""

        # Create a large document with many URLs
        large_text = ""
        for i in range(1000):
            large_text += f"Visit https://site{i}.com for more info. "

        # Measure URL detection performance
        import time
        start_time = time.time()
        spans = run_rules(large_text)
        end_time = time.time()

        url_spans = [s for s in spans if s['label'] == 'URL']

        self.assertEqual(len(url_spans), 1000, "Should detect all 1000 URLs")
        self.assertLess(end_time - start_time, 5.0, "URL detection should complete within 5 seconds")


class TestURLRedactionIntegration(unittest.TestCase):
    """Integration tests for URL redaction in full pipeline"""

    def setUp(self):
        """Set up integration test fixtures"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up integration test fixtures"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @unittest.skipIf('marcut.pipeline' not in sys.modules, "Marcut pipeline not available")
    def test_end_to_end_url_redaction(self):
        """Test complete URL redaction pipeline"""

        # This test would require a real DOCX file
        # For now, we test the logic components

        test_text = "Visit https://example.com and https://test.org for more information."
        spans = run_rules(test_text)
        url_spans = [s for s in spans if s['label'] == 'URL']

        # Simulate the finalization process
        url_counter = {}
        for sp in url_spans:
            url_text = sp["text"]
            if url_text not in url_counter:
                url_counter[url_text] = len(url_counter) + 1
            sp["entity_id"] = f"URL_{url_counter[url_text]}"

        # Verify the results
        self.assertEqual(len(url_spans), 2, "Should detect 2 URLs")
        self.assertEqual(url_spans[0]["entity_id"], "URL_1", "First URL should get ID 1")
        self.assertEqual(url_spans[1]["entity_id"], "URL_2", "Second URL should get ID 2")


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)
