"""
Tests for unified_redactor.py module.

Tests cover:
- validate_model_name: Model name security validation
- validate_parameters: Input parameter validation
- setup_logging: Logging configuration
"""

import pytest
import os
import tempfile
from marcut.unified_redactor import (
    validate_model_name,
    validate_parameters,
    setup_logging,
)


class TestValidateModelName:
    """Test validate_model_name security function."""

    def test_mock_model_allowed(self):
        """Test that mock model is always allowed."""
        assert validate_model_name("mock") is True

    def test_empty_model_allowed(self):
        """Test that empty model is allowed."""
        assert validate_model_name("") is True
        assert validate_model_name(None) is True

    def test_simple_ollama_model(self):
        """Test standard Ollama model names."""
        assert validate_model_name("llama3") is True
        assert validate_model_name("llama3.1:8b") is True
        assert validate_model_name("phi4:mini-instruct") is True
        assert validate_model_name("gpt-4") is True

    def test_gguf_paths_allowed(self):
        """Test that GGUF file paths are allowed."""
        assert validate_model_name("/path/to/model.gguf") is True
        assert validate_model_name("./local_model.gguf") is True
        assert validate_model_name("../relative/model.gguf") is True

    def test_command_injection_blocked(self):
        """Test that shell metacharacters are blocked."""
        # Semicolon injection
        assert validate_model_name("model; rm -rf /") is False
        # Ampersand injection
        assert validate_model_name("model && echo pwned") is False
        # Backtick injection
        assert validate_model_name("`whoami`") is False
        # Dollar sign injection
        assert validate_model_name("$(id)") is False
        # Redirect injection
        assert validate_model_name("model>output") is False
        assert validate_model_name("model<input") is False
        # Pipe injection
        assert validate_model_name("model|cat") is False

    def test_path_with_injection_blocked(self):
        """Test that paths with injection attempts are blocked."""
        assert validate_model_name("/path/to/model.gguf; rm -rf /") is False
        assert validate_model_name("/path/to/model.gguf|cat") is False


class TestValidateParameters:
    """Test validate_parameters function."""

    @pytest.fixture
    def temp_docx(self):
        """Create a temporary DOCX file for testing."""
        # Create a minimal valid DOCX (just the minimal zip structure)
        import zipfile
        from io import BytesIO
        
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        
        # Create minimal DOCX structure
        with zipfile.ZipFile(path, 'w') as zf:
            zf.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
</Types>''')
        
        yield path
        
        # Cleanup
        if os.path.exists(path):
            os.remove(path)

    def test_missing_input_file(self):
        """Test that missing input file raises error."""
        with pytest.raises(ValueError, match="Input file not found"):
            validate_parameters(
                "/nonexistent/file.docx",
                "/tmp/output.docx",
                "/tmp/report.json"
            )

    def test_non_docx_input(self, temp_docx):
        """Test that non-DOCX input raises error."""
        # Create temp txt file
        fd, txt_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            with pytest.raises(ValueError, match="must be a DOCX file"):
                validate_parameters(
                    txt_path,
                    "/tmp/output.docx",
                    "/tmp/report.json"
                )
        finally:
            os.remove(txt_path)

    def test_invalid_mode(self, temp_docx):
        """Test that invalid mode raises error."""
        with pytest.raises(ValueError, match="Invalid mode"):
            validate_parameters(
                temp_docx,
                "/tmp/output.docx",
                "/tmp/report.json",
                mode="invalid_mode"
            )

    def test_valid_modes(self, temp_docx):
        """Test that valid modes are accepted."""
        for mode in ["rules", "enhanced", "rules_override", "constrained_overrides", "llm_overrides"]:
            # Should not raise
            validate_parameters(
                temp_docx,
                "/tmp/output.docx",
                "/tmp/report.json",
                mode=mode
            )

    def test_model_backend_mismatch(self, temp_docx):
        """Test model/backend validation."""
        with pytest.raises(ValueError, match="Cannot use non-mock model with mock backend"):
            validate_parameters(
                temp_docx,
                "/tmp/output.docx",
                "/tmp/report.json",
                model="llama3.1:8b",
                backend="mock"
            )

    def test_unsafe_model_name(self, temp_docx):
        """Test that unsafe model names are rejected."""
        with pytest.raises(ValueError, match="unsafe characters"):
            validate_parameters(
                temp_docx,
                "/tmp/output.docx",
                "/tmp/report.json",
                model="model; rm -rf /"
            )

    def test_output_directory_created(self, temp_docx):
        """Test that output directories are created."""
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        nested_output = os.path.join(temp_dir, "nested", "output.docx")
        nested_report = os.path.join(temp_dir, "reports", "report.json")
        
        try:
            validate_parameters(
                temp_docx,
                nested_output,
                nested_report
            )
            
            # Directories should now exist
            assert os.path.isdir(os.path.join(temp_dir, "nested"))
            assert os.path.isdir(os.path.join(temp_dir, "reports"))
        finally:
            shutil.rmtree(temp_dir)


class TestSetupLogging:
    """Test setup_logging function."""

    def test_basic_setup(self):
        """Test basic logging setup doesn't crash."""
        # Should not raise
        setup_logging(debug=False)

    def test_debug_mode(self):
        """Test debug mode setup."""
        # Should not raise
        setup_logging(debug=True)

    def test_with_log_path(self):
        """Test logging with file output."""
        import tempfile
        fd, log_path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        
        try:
            setup_logging(debug=True, log_path=log_path)
            # Should not raise
        finally:
            if os.path.exists(log_path):
                os.remove(log_path)


class TestEdgeCases:
    """Test edge cases in validation."""

    def test_unicode_in_model_name(self):
        """Test that unicode in model names is handled."""
        # Standard regex should reject non-ASCII
        result = validate_model_name("模型名")
        # This should be False as it contains non-alphanumeric chars
        assert result is False

    def test_very_long_model_name(self):
        """Test very long model names."""
        long_name = "a" * 1000
        # Should still work (just alphanumeric)
        assert validate_model_name(long_name) is True

    def test_model_name_with_dots(self):
        """Test model names with version dots."""
        assert validate_model_name("llama3.2.1:latest") is True
        assert validate_model_name("model.v1.2.3") is True

    def test_model_name_with_underscores(self):
        """Test model names with underscores."""
        assert validate_model_name("my_custom_model") is True
        assert validate_model_name("model_v1_final_2") is True
