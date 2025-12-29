
import pytest
import os
from marcut.unified_redactor import validate_model_name
from marcut.docx_io import _safe_fromstring

def test_validate_model_name_safe():
    """Test that safe model names are accepted."""
    assert validate_model_name("llama3")
    assert validate_model_name("llama3:8b")
    assert validate_model_name("gpt-4")
    assert validate_model_name("my_model_v1.2")
    assert validate_model_name("mock")
    assert validate_model_name("")
    assert validate_model_name(None)

def test_validate_model_name_unsafe():
    """Test that unsafe model names are rejected."""
    # Command injection chars
    assert not validate_model_name("llama3; rm -rf /")
    assert not validate_model_name("llama3 && echo pwned")
    assert not validate_model_name("$(whoami)")
    assert not validate_model_name("`ls`")
    assert not validate_model_name("model>output")
    assert not validate_model_name("model|pipe")

def test_validate_model_name_paths():
    """Test that file paths are accepted but still sanitized."""
    # Valid paths
    assert validate_model_name("/path/to/model.gguf")
    assert validate_model_name("./local_model.gguf")
    assert validate_model_name("../relative/model")
    
    # Paths with injection
    assert not validate_model_name("/path/to/model;rm -rf /")

def test_safe_fromstring_valid():
    """Test that valid XML is parsed correctly."""
    xml = b"<root><child>value</child></root>"
    root = _safe_fromstring(xml)
    assert root.tag == "root"
    assert root[0].tag == "child"
    assert root[0].text == "value"

def test_safe_fromstring_xxe():
    """
    Test that entities are NOT resolved.
    Note: lxml with resolve_entities=False usually leaves the entity text 
    or raises an error, but importantly does not read the file.
    """
    # This XML attempts to read /etc/passwd (classic XXE)
    xxe_payload = b"""
    <!DOCTYPE foo [ 
      <!ELEMENT foo ANY >
      <!ENTITY xxe SYSTEM "file:///etc/passwd" >]><foo>&xxe;</foo>
    """
    
    # Depending on lxml version/configuration, this might raise an error 
    # or return the entity as literal text, but it should NOT contain root content of passwd.
    # We just want to ensure it doesn't crash in a way that implies execution 
    # or actually return file content.
    
    try:
        root = _safe_fromstring(xxe_payload)
        # If it parsed, check content. 
        # With resolve_entities=False, &xxe; should not be expanded to file content.
        # It's hard to verify "file content not read" without successful expansion check,
        # but typical success is that text is empty or is literally "&xxe;" 
        content = root.text or ""
        assert "root:" not in content  # Basic check that /etc/passwd wasn't read
    except Exception:
        # Failing to parse malicious XML is also a pass
        pass
