
import unittest
import os
import sys

# Ensure we can import marcut
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from marcut.pipeline import _merge_overlaps, _snap_to_boundaries
from marcut.unified_redactor import validate_parameters
# We need to test model_enhanced but it requires significant mocking. 
# We'll focus on the logic we can isolate or verify basic import safety.

class TestFixes(unittest.TestCase):
    def test_merge_overlaps_updates_text(self):
        text = "0123456789"
        spans = [
            {"start": 2, "end": 5, "label": "A", "text": "234"},
            {"start": 4, "end": 7, "label": "B", "text": "456"}
        ]
        
        merged = _merge_overlaps(spans, text)
        
        self.assertEqual(len(merged), 1)
        m = merged[0]
        self.assertEqual(m["start"], 2)
        self.assertEqual(m["end"], 7)
        self.assertEqual(m["text"], "23456") 
        
    def test_cli_validation_balanced_rejected(self):
        with open("dummy_balanced.docx", "w") as f: f.write("dummy")
        try:
            with self.assertRaises(ValueError):
                validate_parameters("dummy_balanced.docx", "out.docx", "rep.json", mode="balanced")
        finally:
            if os.path.exists("dummy_balanced.docx"): os.remove("dummy_balanced.docx")
            
    def test_pipeline_variable_safety(self):
        # We can't easily execute the full pipeline without mocking models,
        # but we can verify that importing it doesn't crash and key functions exist.
        import marcut.pipeline
        self.assertTrue(hasattr(marcut.pipeline, "_merge_overlaps"))
        # Verify call signature via inspection or simple call
        try:
            marcut.pipeline._merge_overlaps([], "text")
        except TypeError:
            self.fail("_merge_overlaps signature mismatch")

if __name__ == "__main__":
    unittest.main()
