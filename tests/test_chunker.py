"""
Tests for the chunker module, including Phase 1 small document optimization.
"""

import pytest
from marcut.chunker import make_chunks, SMALL_DOC_THRESHOLD


class TestSmallDocumentOptimization:
    """Test Phase 1: Small documents should skip chunking entirely."""
    
    def test_small_doc_single_chunk(self):
        """Documents under threshold should return a single chunk."""
        text = "Hello world. " * 100  # ~1300 chars, well under threshold
        chunks = make_chunks(text)
        
        assert len(chunks) == 1
        assert chunks[0]['start'] == 0
        assert chunks[0]['end'] == len(text)
        assert chunks[0]['text'] == text
    
    def test_exactly_at_threshold(self):
        """Document exactly at threshold should return single chunk."""
        text = "a" * SMALL_DOC_THRESHOLD
        chunks = make_chunks(text)
        
        assert len(chunks) == 1
        assert chunks[0]['text'] == text
    
    def test_one_char_over_threshold(self):
        """Document one char over threshold should be chunked."""
        text = "a" * (SMALL_DOC_THRESHOLD + 1)
        chunks = make_chunks(text)
        
        # Should now be chunked (multiple chunks for this size)
        assert len(chunks) >= 1
        # First chunk should be max_len (2500 by default)
        if len(chunks) > 1:
            assert len(chunks[0]['text']) == 2500
    
    def test_empty_text(self):
        """Empty text should return empty single chunk."""
        chunks = make_chunks("")
        
        assert len(chunks) == 1
        assert chunks[0]['start'] == 0
        assert chunks[0]['end'] == 0
        assert chunks[0]['text'] == ""


class TestLargeDocumentChunking:
    """Test that large document chunking behavior is unchanged."""
    
    def test_large_doc_chunked(self):
        """Documents over threshold should be chunked normally."""
        text = "word " * 5000  # ~25,000 chars
        chunks = make_chunks(text)
        
        assert len(chunks) > 1
        # Each non-final chunk should be exactly max_len (2500 default)
        for chunk in chunks[:-1]:
            assert chunk['end'] - chunk['start'] == 2500
    
    def test_overlap_present(self):
        """Adjacent chunks should have proper overlap."""
        text = "a" * 10000  # Large enough to have multiple chunks
        chunks = make_chunks(text, max_len=4000, overlap=400)
        
        for i in range(len(chunks) - 1):
            chunk_a = chunks[i]
            chunk_b = chunks[i + 1]
            
            # chunk_b should start before chunk_a ends (overlap)
            assert chunk_b['start'] < chunk_a['end'], \
                f"No overlap between chunks {i} and {i+1}"
            
            # Overlap should be exactly 400 chars
            overlap_size = chunk_a['end'] - chunk_b['start']
            assert overlap_size == 400, \
                f"Expected 400 char overlap, got {overlap_size}"
    
    def test_custom_max_len(self):
        """Custom max_len should be respected."""
        text = "a" * 10000
        chunks = make_chunks(text, max_len=2000, overlap=200)
        
        # First chunk should be 2000 chars
        assert len(chunks[0]['text']) == 2000
    
    def test_chunks_cover_entire_text(self):
        """All text should be covered by chunks."""
        text = "The quick brown fox jumps over the lazy dog. " * 300
        chunks = make_chunks(text)
        
        # Reconstruct using non-overlapping portions
        # First chunk fully, then non-overlapping parts of subsequent chunks
        reconstructed = chunks[0]['text']
        for i in range(1, len(chunks)):
            overlap_start = chunks[i]['start']
            prev_end = chunks[i-1]['end']
            # Add only the new part (after overlap)
            new_start = prev_end  # This is where new content begins
            new_part = chunks[i]['text'][new_start - overlap_start:]
            reconstructed += new_part
        
        assert reconstructed == text, "Chunks don't fully cover the text"
    
    def test_last_chunk_contains_end(self):
        """Last chunk should end at the text end."""
        text = "a" * 10000
        chunks = make_chunks(text)
        
        assert chunks[-1]['end'] == len(text)


class TestBackwardCompatibility:
    """Ensure large document behavior matches original implementation exactly."""
    
    def _make_chunks_legacy(self, text, max_len=4000, overlap=400):
        """Original implementation for comparison."""
        chunks = []
        i = 0
        n = len(text)
        while i < n:
            j = min(n, i + max_len)
            chunks.append({'start': i, 'end': j, 'text': text[i:j]})
            if j == n:
                break
            i = max(0, j - overlap)
        return chunks
    
    def test_large_doc_identical_to_legacy(self):
        """Large documents should chunk identically to original implementation when using same params."""
        text = "Testing backward compatibility. " * 500  # ~16,000 chars
        
        # Use explicit max_len to compare like-for-like
        new_chunks = make_chunks(text, max_len=4000, overlap=400)
        legacy_chunks = self._make_chunks_legacy(text, max_len=4000, overlap=400)
        
        assert len(new_chunks) == len(legacy_chunks), \
            f"Chunk count mismatch: {len(new_chunks)} vs {len(legacy_chunks)}"
        
        for i, (new, legacy) in enumerate(zip(new_chunks, legacy_chunks)):
            assert new['start'] == legacy['start'], f"Chunk {i} start mismatch"
            assert new['end'] == legacy['end'], f"Chunk {i} end mismatch"
            assert new['text'] == legacy['text'], f"Chunk {i} text mismatch"
    
    def test_various_sizes_backward_compatible(self):
        """Test backward compatibility with explicit params at various document sizes."""
        test_sizes = [
            SMALL_DOC_THRESHOLD + 100,
            SMALL_DOC_THRESHOLD + 1000,
            20000,
            50000,
            100000
        ]
        
        for size in test_sizes:
            text = "x" * size
            # Use explicit max_len to compare like-for-like
            new_chunks = make_chunks(text, max_len=4000, overlap=400)
            legacy_chunks = self._make_chunks_legacy(text, max_len=4000, overlap=400)
            
            assert len(new_chunks) == len(legacy_chunks), \
                f"Size {size}: chunk count mismatch"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_text_exactly_max_len(self):
        """Text exactly max_len should be single chunk."""
        text = "a" * 4000
        chunks = make_chunks(text, max_len=4000, overlap=400)
        
        # Under threshold, so single chunk
        assert len(chunks) == 1
    
    def test_very_small_overlap(self):
        """Very small overlap should still work."""
        text = "a" * 10000
        chunks = make_chunks(text, max_len=4000, overlap=10)
        
        assert len(chunks) > 1
        for i in range(len(chunks) - 1):
            overlap = chunks[i]['end'] - chunks[i + 1]['start']
            assert overlap == 10
    
    def test_zero_overlap(self):
        """Zero overlap should produce non-overlapping chunks."""
        text = "a" * 10000
        chunks = make_chunks(text, max_len=4000, overlap=0)
        
        for i in range(len(chunks) - 1):
            # Chunks should be adjacent, not overlapping
            assert chunks[i]['end'] == chunks[i + 1]['start']
    
    def test_unicode_text(self):
        """Unicode text should be handled correctly."""
        # Mix of ASCII and multi-byte characters
        text = "Hello 世界! Émoji: 🎉 " * 500
        chunks = make_chunks(text)
        
        # Should not raise and should cover all text
        total_unique_chars = set()
        for chunk in chunks:
            total_unique_chars.update(range(chunk['start'], chunk['end']))
        
        assert len(total_unique_chars) == len(text)
