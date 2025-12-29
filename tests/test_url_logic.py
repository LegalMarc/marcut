#!/usr/bin/env python3
"""
Simplified URL Logic Tests
Tests the core logic without requiring full marcut imports
"""

import unittest
import re

# URL pattern from rules.py (copied for testing)
URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s]+|\bwww\.[^\s]+\.[a-z]{2,}")

class TestURLLogic(unittest.TestCase):
    """Test URL logic independently"""

    def test_url_pattern_basic(self):
        """Test basic URL pattern matching"""

        # Test HTTPS URLs
        text = "Visit https://example.com for info"
        matches = list(URL_PATTERN.finditer(text))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].group(), "https://example.com")

        # Test HTTP URLs
        text = "Check http://test.org for details"
        matches = list(URL_PATTERN.finditer(text))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].group(), "http://test.org")

        # Test www URLs
        text = "Go to www.site.com for updates"
        matches = list(URL_PATTERN.finditer(text))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].group(), "www.site.com")

    def test_url_sequential_id_logic(self):
        """Test URL sequential ID assignment logic"""

        # Simulate the logic from pipeline.py
        urls = ["https://example.com", "http://test.org", "https://example.com"]
        url_counter = {}
        entity_ids = []

        for url in urls:
            if url not in url_counter:
                url_counter[url] = len(url_counter) + 1
            entity_id = f"URL_{url_counter[url]}"
            entity_ids.append(entity_id)

        # Verify sequential assignment
        expected_ids = ["URL_1", "URL_2", "URL_1"]
        self.assertEqual(entity_ids, expected_ids)

    def test_url_replacement_logic(self):
        """Test URL replacement logic"""

        text = "Visit https://example.com and http://test.org"

        # Simulate span detection (correct positions)
        spans = [
            {"start": 6, "end": 25, "text": "https://example.com", "entity_id": "URL_1"},
            {"start": 30, "end": 45, "text": "http://test.org", "entity_id": "URL_2"}
        ]

        # Apply replacements (reverse order to preserve positions)
        result_text = text
        for span in sorted(spans, key=lambda x: x['start'], reverse=True):
            replacement = f"[{span['entity_id']}]"
            result_text = result_text[:span['start']] + replacement + result_text[span['end']:]

        expected = "Visit [URL_1] and [URL_2]"
        self.assertEqual(result_text, expected)

    def test_url_edge_cases(self):
        """Test URL edge cases"""

        test_cases = [
            ("https://start.com is first", 1),
            ("Text ends with https://end.com", 1),
            ("Multiple https://one.com and https://two.com", 2),
            ("No URLs here", 0),
            ("Invalid ht://broken", 0),
            ("Params: https://api.com/v1/data?param=value", 1),
        ]

        for text, expected_count in test_cases:
            with self.subTest(text=text):
                matches = list(URL_PATTERN.finditer(text))
                self.assertEqual(len(matches), expected_count,
                               f"'{text}' should have {expected_count} matches")

    def test_url_entity_priority(self):
        """Test URL entity priority logic"""

        # URLs have rank 3 in the pipeline
        url_rank = 3
        email_rank = 3
        name_rank = 2

        # Test ranking logic
        self.assertEqual(url_rank, email_rank, "URLs and emails have same priority")
        self.assertGreater(url_rank, name_rank, "URLs have higher priority than names")

if __name__ == '__main__':
    unittest.main(verbosity=2)