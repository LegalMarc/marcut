"""
Text chunking utilities for document processing.

Phase 1 optimization: Skip chunking for small documents (< 8000 chars / ~2000 words)
to avoid entity fragmentation and reduce LLM call overhead.
"""

# Threshold below which documents are processed as a single chunk.
# Reduced to 4000 (~1000 words) to prevent context overflow and timeouts.
SMALL_DOC_THRESHOLD = 4000


def make_chunks(text, max_len=2500, overlap=400):
    """
    Split text into overlapping chunks for processing.
    
    Args:
        text: The document text to chunk
        max_len: Maximum characters per chunk (default 4000)
        overlap: Characters of overlap between chunks (default 400)
    
    Returns:
        List of chunk dicts with 'start', 'end', and 'text' keys
    
    Phase 1 optimization: Documents smaller than SMALL_DOC_THRESHOLD
    are returned as a single chunk to avoid splitting overhead.
    """
    # Phase 1: Skip chunking for small documents
    # A document under ~2000 words processes faster in a single LLM call
    # than being split/recombined with overlap redundancy
    if len(text) <= SMALL_DOC_THRESHOLD:
        return [{'start': 0, 'end': len(text), 'text': text}]
    
    # Standard chunking for larger documents (unchanged logic)
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
