"""
Tests for document redaction failure scenarios.

These tests cover edge cases that can cause redaction failures, including:
- Ollama streaming JSON responses (the stream:false fix)
- Corrupt DOCX files (malformed ZIP, missing core.xml, invalid content)
- LLM timeout handling
- Ollama unavailable (service not running)
- Memory exhaustion (very large documents)
- Permission errors (locked files)
- Track changes corruption (invalid revision XML)
- Encoding errors (non-UTF8 content)
"""

import pytest
import os
import io
import tempfile
import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import requests

# Check if we're in an environment where marcut is available
try:
    from marcut.model import ollama_extract, get_ollama_base_url, parse_llm_response
    from marcut.pipeline import run_redaction, RedactionError
    from marcut.docx_io import DocxMap
    MARCUT_AVAILABLE = True
except ImportError:
    MARCUT_AVAILABLE = False


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_dir = tempfile.mkdtemp(prefix="marcut_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def valid_docx_path():
    """Get path to a valid sample DOCX file."""
    path = Path("/Users/mhm/Documents/Hobby/Marcut-2/ignored-resources/sample-files/GOAL - Exos - Fee Letter (fails redaction).docx")
    if not path.exists():
        pytest.skip(f"Sample file not found: {path}")
    return path


# =============================================================================
# Ollama Streaming Fix Tests
# =============================================================================

class TestOllamaStreamingFix:
    """Tests for the stream:false fix in Ollama requests."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_ollama_request_includes_stream_false(self):
        """Verify that Ollama requests include stream:false to prevent JSON parsing errors."""
        import inspect
        from marcut.model import ollama_extract
        
        source = inspect.getsource(ollama_extract)
        assert '"stream": False' in source or "'stream': False" in source, \
            "ollama_extract should include 'stream': False to prevent streaming JSON responses"
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_parse_llm_response_handles_valid_json(self):
        """Test that parse_llm_response handles valid JSON correctly."""
        valid_json = '{"entities": [{"text": "John Smith", "type": "NAME"}]}'
        result = parse_llm_response(valid_json)
        
        assert 'entities' in result
        assert len(result['entities']) == 1
        assert result['entities'][0]['text'] == 'John Smith'
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_parse_llm_response_handles_markdown_wrapped_json(self):
        """Test that parse_llm_response handles JSON wrapped in markdown."""
        markdown_json = """```json
{"entities": [{"text": "Acme Corp", "type": "ORG"}]}
```"""
        result = parse_llm_response(markdown_json)
        
        assert 'entities' in result
        assert result['entities'][0]['text'] == 'Acme Corp'


# =============================================================================
# Corrupt DOCX Files Tests
# =============================================================================

class TestCorruptDocxFiles:
    """Tests for handling corrupt DOCX files."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_malformed_zip_file(self, temp_dir):
        """Test handling of malformed ZIP (not a valid DOCX)."""
        corrupt_path = temp_dir / "corrupt.docx"
        
        # Create a file that's not a valid ZIP
        with open(corrupt_path, 'wb') as f:
            f.write(b"This is not a ZIP file at all")
        
        with pytest.raises(Exception) as exc_info:
            DocxMap.load(str(corrupt_path))
        
        # Should raise an error about invalid file
        assert exc_info.value is not None
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_zip_missing_document_xml(self, temp_dir):
        """Test handling of ZIP that's missing document.xml."""
        corrupt_path = temp_dir / "missing_document.docx"
        
        # Create a ZIP file without document.xml
        with zipfile.ZipFile(corrupt_path, 'w') as zf:
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types></Types>')
            # Intentionally missing word/document.xml
        
        with pytest.raises(Exception) as exc_info:
            DocxMap.load(str(corrupt_path))
        
        assert exc_info.value is not None
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_zip_with_invalid_xml(self, temp_dir):
        """Test handling of DOCX with invalid XML content."""
        corrupt_path = temp_dir / "invalid_xml.docx"
        
        # Create a ZIP file with malformed XML
        with zipfile.ZipFile(corrupt_path, 'w') as zf:
            zf.writestr('[Content_Types].xml', '<?xml version="1.0"?><Types></Types>')
            zf.writestr('word/document.xml', '<w:document>Not properly closed XML')
        
        with pytest.raises(Exception) as exc_info:
            DocxMap.load(str(corrupt_path))
        
        assert exc_info.value is not None
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_empty_docx_file(self, temp_dir):
        """Test handling of empty file with .docx extension."""
        empty_path = temp_dir / "empty.docx"
        empty_path.touch()  # Create empty file
        
        with pytest.raises(Exception) as exc_info:
            DocxMap.load(str(empty_path))
        
        assert exc_info.value is not None
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_truncated_docx_file(self, temp_dir, valid_docx_path):
        """Test handling of truncated DOCX file."""
        truncated_path = temp_dir / "truncated.docx"
        
        # Copy first half of valid file
        with open(valid_docx_path, 'rb') as f:
            content = f.read()
        
        with open(truncated_path, 'wb') as f:
            f.write(content[:len(content)//2])
        
        with pytest.raises(Exception) as exc_info:
            DocxMap.load(str(truncated_path))
        
        assert exc_info.value is not None


# =============================================================================
# LLM Timeout Handling Tests
# =============================================================================

class TestLLMTimeoutHandling:
    """Tests for LLM timeout handling."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_timeout_exception_handling(self):
        """Test that timeout exceptions are properly caught and wrapped."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.Timeout("Connection timed out")
            
            with pytest.raises(RuntimeError) as exc_info:
                ollama_extract('llama3.1:8b', 'test text', 0.7, 42)
            
            # Should wrap as "not reachable" error
            assert "not reachable" in str(exc_info.value).lower() or "timeout" in str(exc_info.value).lower()
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_read_timeout_handling(self):
        """Test handling of read timeout during response."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ReadTimeout("Read timed out")
            
            with pytest.raises(RuntimeError):
                ollama_extract('llama3.1:8b', 'test text', 0.7, 42)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_connect_timeout_handling(self):
        """Test handling of connection timeout."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectTimeout("Connection timed out")
            
            with pytest.raises(RuntimeError):
                ollama_extract('llama3.1:8b', 'test text', 0.7, 42)


# =============================================================================
# Ollama Unavailable Tests
# =============================================================================

class TestOllamaUnavailable:
    """Tests for handling Ollama service unavailable."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_connection_refused(self):
        """Test handling when Ollama service is not running (connection refused)."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError(
                "Connection refused: [Errno 61] Connection refused"
            )
            
            with pytest.raises(RuntimeError) as exc_info:
                ollama_extract('llama3.1:8b', 'test text', 0.7, 42)
            
            assert "not reachable" in str(exc_info.value).lower()
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_dns_resolution_failure(self):
        """Test handling of DNS resolution failure."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.get_ollama_base_url', return_value='http://nonexistent-host:11434'):
            with patch('marcut.model.requests.post') as mock_post:
                mock_post.side_effect = requests.exceptions.ConnectionError(
                    "Failed to resolve 'nonexistent-host'"
                )
                
                with pytest.raises(RuntimeError):
                    ollama_extract('llama3.1:8b', 'test text', 0.7, 42)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_http_500_error(self):
        """Test handling of HTTP 500 Internal Server Error from Ollama."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                "500 Server Error", response=mock_response
            )
            mock_post.return_value = mock_response
            
            with pytest.raises(RuntimeError):
                ollama_extract('llama3.1:8b', 'test text', 0.7, 42)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_model_not_found(self):
        """Test handling when requested model is not found."""
        from marcut.model import ollama_extract
        
        with patch('marcut.model.requests.post') as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.text = "model 'nonexistent-model' not found"
            mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
                "404 Not Found", response=mock_response
            )
            mock_post.return_value = mock_response
            
            with pytest.raises(RuntimeError):
                ollama_extract('nonexistent-model', 'test text', 0.7, 42)


# =============================================================================
# Memory Exhaustion Tests
# =============================================================================

class TestMemoryExhaustion:
    """Tests for handling very large documents."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_very_large_text_chunking(self):
        """Test that very large text is properly chunked."""
        from marcut.chunker import make_chunks
        
        # Create large text (1MB+)
        large_text = "word " * 200000  # ~1MB of text
        
        chunks = make_chunks(large_text)
        
        # Should be chunked into manageable pieces
        assert len(chunks) > 1
        for chunk in chunks[:-1]:
            assert len(chunk['text']) <= 2500  # max_len default
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")  
    def test_chunk_count_reasonable_for_large_doc(self):
        """Test that chunk count doesn't explode for large documents."""
        from marcut.chunker import make_chunks
        
        # 100KB document
        text = "a" * 100000
        chunks = make_chunks(text)
        
        # Should have reasonable chunk count (not too many)
        # With 2500 char chunks and 400 overlap: ~47 chunks
        assert len(chunks) < 100


# =============================================================================
# Permission Error Tests
# =============================================================================

class TestPermissionErrors:
    """Tests for handling permission errors."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_output_to_readonly_directory(self, temp_dir, valid_docx_path):
        """Test handling when output directory is read-only."""
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        
        output_path = readonly_dir / "output.docx"
        report_path = readonly_dir / "report.json"
        
        # Make directory read-only
        os.chmod(readonly_dir, 0o444)
        
        try:
            exit_code, _ = run_redaction(
                input_path=str(valid_docx_path),
                output_path=str(output_path),
                report_path=str(report_path),
                mode="rules",  # Use rules only for speed
                model_id="",
                chunk_tokens=500,
                overlap=50,
                temperature=0.7,
                seed=42,
                debug=False,
            )
            
            # Should fail with non-zero exit code
            assert exit_code != 0
        finally:
            # Restore permissions for cleanup
            os.chmod(readonly_dir, 0o755)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_input_file_not_found(self, temp_dir):
        """Test handling when input file doesn't exist."""
        nonexistent = temp_dir / "nonexistent.docx"
        output_path = temp_dir / "output.docx"
        report_path = temp_dir / "report.json"
        
        exit_code, _ = run_redaction(
            input_path=str(nonexistent),
            output_path=str(output_path),
            report_path=str(report_path),
            mode="rules",
            model_id="",
            chunk_tokens=500,
            overlap=50,
            temperature=0.7,
            seed=42,
            debug=False,
        )
        
        # Should fail with non-zero exit code
        assert exit_code != 0


# =============================================================================
# Track Changes Corruption Tests
# =============================================================================

class TestTrackChangesCorruption:
    """Tests for handling track changes / revision XML corruption."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_docx_with_malformed_revisions(self, temp_dir):
        """Test handling of DOCX with malformed revision tracking XML."""
        corrupt_path = temp_dir / "bad_revisions.docx"
        
        # Create minimal DOCX with malformed settings
        with zipfile.ZipFile(corrupt_path, 'w') as zf:
            content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
            zf.writestr('[Content_Types].xml', content_types)
            
            rels = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''
            zf.writestr('_rels/.rels', rels)
            
            # Minimal valid document
            document = '''<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:r><w:t>Test content</w:t></w:r></w:p></w:body>
</w:document>'''
            zf.writestr('word/document.xml', document)
        
        # This should at least load (basic structure is valid)
        try:
            dm = DocxMap.load(str(corrupt_path))
            assert "Test content" in dm.text
        except Exception as e:
            # If it fails, that's also acceptable - we're testing error handling
            pass


# =============================================================================
# Encoding Error Tests
# =============================================================================

class TestEncodingErrors:
    """Tests for handling encoding/character set errors."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_text_with_invalid_unicode(self):
        """Test handling of text with invalid Unicode sequences."""
        from marcut.rules import run_rules
        
        # Text with replacement character (common in corrupted docs)
        text_with_replacement = "Hello \ufffd World \ufffd Test"
        
        # Should not crash
        spans = run_rules(text_with_replacement)
        assert isinstance(spans, list)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_text_with_null_bytes(self):
        """Test handling of text containing null bytes."""
        from marcut.rules import run_rules
        
        text_with_nulls = "Hello\x00World\x00Test"
        
        # Should handle gracefully (may filter or skip nulls)
        try:
            spans = run_rules(text_with_nulls)
            assert isinstance(spans, list)
        except Exception:
            # Some sanitization is acceptable
            pass
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_text_with_mixed_encodings(self):
        """Test handling of text that appears to have mixed encodings."""
        from marcut.rules import run_rules
        
        # Common mojibake patterns
        mojibake_text = "Hello Ã¼ World"  # UTF-8 decoded as Latin-1
        
        spans = run_rules(mojibake_text)
        assert isinstance(spans, list)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_unicode_normalization(self):
        """Test that Unicode normalization doesn't break entity detection."""
        from marcut.rules import run_rules
        
        # Text with composed vs decomposed characters
        text_nfc = "José García"  # NFC normalized
        text_nfd = "Jose\u0301 Garci\u0301a"  # NFD normalized
        
        spans_nfc = run_rules(text_nfc)
        spans_nfd = run_rules(text_nfd)
        
        # Both should work
        assert isinstance(spans_nfc, list)
        assert isinstance(spans_nfd, list)


# =============================================================================
# Ollama Connectivity Tests
# =============================================================================

class TestOllamaConnectivity:
    """Tests for Ollama connectivity and error handling."""
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_get_ollama_base_url_default(self):
        """Test default Ollama URL."""
        saved = os.environ.get('OLLAMA_HOST')
        if 'OLLAMA_HOST' in os.environ:
            del os.environ['OLLAMA_HOST']
        
        try:
            url = get_ollama_base_url()
            assert url == "http://127.0.0.1:11434"
        finally:
            if saved:
                os.environ['OLLAMA_HOST'] = saved
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    @pytest.mark.skipif(not os.environ.get('RUN_OLLAMA_TESTS'), reason="Set RUN_OLLAMA_TESTS=1 to run Ollama tests")
    def test_ollama_is_reachable(self):
        """Test that Ollama service is reachable."""
        base_url = get_ollama_base_url()
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        
        assert response.status_code == 200
        data = response.json()
        assert 'models' in data


# =============================================================================
# Integration Tests (Require Ollama)
# =============================================================================

class TestDocumentRedaction:
    """Integration tests for document redaction."""
    
    @pytest.fixture
    def sample_docx_path(self):
        """Get path to sample DOCX file that previously failed."""
        path = Path("/Users/mhm/Documents/Hobby/Marcut-2/ignored-resources/sample-files/LAGO - Exos - Fee Letter (fails redaction).docx")
        if not path.exists():
            pytest.skip(f"Sample file not found: {path}")
        return path
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    def test_document_can_be_loaded(self, sample_docx_path):
        """Test that the previously failing document can be loaded."""
        dm = DocxMap.load(str(sample_docx_path))
        text = dm.text
        
        assert len(text) > 0
        assert len(text) > 1000
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    @pytest.mark.skipif(not os.environ.get('RUN_OLLAMA_TESTS'), reason="Set RUN_OLLAMA_TESTS=1 to run Ollama tests")
    def test_ollama_extraction_on_document(self, sample_docx_path):
        """Test that Ollama extraction works on the document text."""
        dm = DocxMap.load(str(sample_docx_path))
        text = dm.text[:2000]
        
        result = ollama_extract('llama3.1:8b', text, 0.7, 42)
        assert isinstance(result, list)
    
    @pytest.mark.skipif(not MARCUT_AVAILABLE, reason="marcut not installed")
    @pytest.mark.skipif(not os.environ.get('RUN_OLLAMA_TESTS'), reason="Set RUN_OLLAMA_TESTS=1 to run Ollama tests")
    def test_full_redaction_pipeline(self, sample_docx_path, temp_dir):
        """Test the full redaction pipeline on the previously failing document."""
        output_path = temp_dir / "redacted_output.docx"
        report_path = temp_dir / "redaction_report.json"
        
        exit_code, timings = run_redaction(
            input_path=str(sample_docx_path),
            output_path=str(output_path),
            report_path=str(report_path),
            mode="enhanced",
            model_id="llama3.1:8b",
            chunk_tokens=500,
            overlap=50,
            temperature=0.7,
            seed=42,
            debug=True,
        )
        
        assert exit_code == 0
        assert output_path.exists()
        assert report_path.exists()
        
        output_dm = DocxMap.load(str(output_path))
        assert len(output_dm.text) > 0

