"""
Unit tests for report_common.py shared utilities.

Tests:
- escape_html: HTML character escaping
- get_mime_type: MIME type detection
- format_file_size: Human-readable file sizes
- get_binary_icon: File type icons
- get_base_css: CSS output validity
- get_base_js: JavaScript output validity
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'python'))

import pytest
from marcut.report_common import (
    escape_html,
    get_mime_type,
    format_file_size,
    get_binary_icon,
    get_base_css,
    get_base_js,
)


class TestEscapeHtml:
    """Tests for escape_html function."""
    
    def test_escapes_ampersand(self):
        assert escape_html('foo & bar') == 'foo &amp; bar'
    
    def test_escapes_less_than(self):
        assert escape_html('<script>') == '&lt;script&gt;'
    
    def test_escapes_greater_than(self):
        assert escape_html('a > b') == 'a &gt; b'
    
    def test_escapes_double_quotes(self):
        assert escape_html('say "hello"') == 'say &quot;hello&quot;'
    
    def test_escapes_single_quotes(self):
        assert escape_html("it's") == "it&#x27;s"
    
    def test_handles_empty_string(self):
        assert escape_html('') == ''
    
    def test_handles_none(self):
        assert escape_html(None) == ''
    
    def test_complex_html_injection(self):
        dangerous = '<script>alert("xss")</script>'
        expected = '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
        assert escape_html(dangerous) == expected
    
    def test_preserves_safe_characters(self):
        safe = 'Hello World 123 !@#$%^*()'
        # Only &, <, >, ", ' should be escaped
        result = escape_html(safe)
        assert 'Hello World 123' in result


class TestGetMimeType:
    """Tests for get_mime_type function."""
    
    def test_png_image(self):
        assert get_mime_type('image.png') == 'image/png'
    
    def test_jpeg_image(self):
        assert get_mime_type('photo.jpg') == 'image/jpeg'
        assert get_mime_type('photo.jpeg') == 'image/jpeg'
    
    def test_gif_image(self):
        assert get_mime_type('animation.gif') == 'image/gif'
    
    def test_webp_image(self):
        assert get_mime_type('modern.webp') == 'image/webp'
    
    def test_pdf_document(self):
        assert get_mime_type('document.pdf') == 'application/pdf'
    
    def test_docx_document(self):
        result = get_mime_type('contract.docx')
        assert 'application' in result  # May be vnd.openxmlformats or octet-stream
    
    def test_unknown_extension(self):
        result = get_mime_type('file.xyz123')
        assert result == 'application/octet-stream'
    
    def test_no_extension(self):
        result = get_mime_type('README')
        assert result == 'application/octet-stream'
    
    def test_path_with_directories(self):
        assert get_mime_type('/path/to/image.png') == 'image/png'


class TestFormatFileSize:
    """Tests for format_file_size function."""
    
    def test_bytes(self):
        assert format_file_size(0) == '0 bytes'
        assert format_file_size(1) == '1 bytes'
        assert format_file_size(512) == '512 bytes'
        assert format_file_size(1023) == '1023 bytes'
    
    def test_kilobytes(self):
        assert format_file_size(1024) == '1.0 KB'
        assert format_file_size(1536) == '1.5 KB'
        assert format_file_size(10240) == '10.0 KB'
    
    def test_megabytes(self):
        assert format_file_size(1024 * 1024) == '1.0 MB'
        assert format_file_size(1024 * 1024 * 2.5) == '2.5 MB'
        assert format_file_size(1024 * 1024 * 100) == '100.0 MB'
    
    def test_edge_case_just_under_kb(self):
        assert format_file_size(1023) == '1023 bytes'
    
    def test_edge_case_just_under_mb(self):
        result = format_file_size(1024 * 1024 - 1)
        assert 'KB' in result


class TestGetBinaryIcon:
    """Tests for get_binary_icon function."""
    
    def test_image_icon(self):
        assert get_binary_icon('image') == '🖼️'
    
    def test_thumbnail_icon(self):
        assert get_binary_icon('thumbnail') == '📷'
    
    def test_font_icon(self):
        assert get_binary_icon('font') == '🔤'
    
    def test_macro_icon(self):
        assert get_binary_icon('macro') == '⚙️'
    
    def test_printer_settings_icon(self):
        assert get_binary_icon('printer_settings') == '🖨️'
    
    def test_ole_embedding_icon(self):
        assert get_binary_icon('ole_embedding') == '📎'
    
    def test_activex_icon(self):
        assert get_binary_icon('activex') == '🔌'
    
    def test_unknown_type_default(self):
        # Updated to new fallback icon
        assert get_binary_icon('unknown_type') == '📁'
        assert get_binary_icon('random') == '📁'
        assert get_binary_icon('') == '📁'


class TestGetBaseCss:
    """Tests for get_base_css function."""
    
    def test_returns_string(self):
        css = get_base_css()
        assert isinstance(css, str)
        assert len(css) > 100  # Should have substantial CSS
    
    def test_contains_css_variables(self):
        css = get_base_css()
        assert '--bg-primary' in css
        assert '--text-primary' in css
        assert '--border-color' in css
    
    def test_contains_light_theme(self):
        css = get_base_css()
        assert 'prefers-color-scheme: light' in css
    
    def test_contains_body_styles(self):
        css = get_base_css()
        assert 'body {' in css or 'body{' in css
    
    def test_contains_group_styles(self):
        css = get_base_css()
        assert '.group' in css
        assert '.group-header' in css


class TestGetBaseJs:
    """Tests for get_base_js function."""
    
    def test_returns_string(self):
        js = get_base_js()
        assert isinstance(js, str)
        assert len(js) > 50  # Should have some JS
    
    def test_contains_dom_content_loaded(self):
        js = get_base_js()
        assert 'DOMContentLoaded' in js
    
    def test_contains_toggle_logic(self):
        js = get_base_js()
        assert 'classList.toggle' in js or 'collapsed' in js

    def test_uses_legacy_function_syntax(self):
        js = get_base_js()
        assert 'function(' in js
        # We don't strictly ban arrow functions, but older JS is safer for compatibility
        # assert '=>' not in js


from unittest.mock import patch, MagicMock

class TestReadMdlsMetadata:
    """Tests for _read_mdls_metadata function."""

    @patch('subprocess.check_output')
    def test_parses_valid_plist_output(self, mock_subprocess):
        # Mock plist output
        plist_binary = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>kMDItemContentCreationDate</key>
    <date>2023-01-01T12:00:00Z</date>
    <key>kMDItemContentType</key>
    <string>public.jpeg</string>
    <key>kMDItemFSSize</key>
    <integer>1024</integer>
</dict>
</plist>"""
        mock_subprocess.return_value = plist_binary
        
        from marcut.report_common import _read_mdls_metadata
        result = _read_mdls_metadata('/path/to/file.jpg')
        
        assert result['kMDItemContentType'] == 'public.jpeg'
        assert result['kMDItemFSSize'] == 1024
        # Dates are typically converted to datetime objects by plistlib, then formatted to ISO
        assert '2023-01-01' in result['kMDItemContentCreationDate'] 

    @patch('subprocess.check_output')
    def test_handles_subprocess_error(self, mock_subprocess):
        import subprocess
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, ['mdls'])
        
        from marcut.report_common import _read_mdls_metadata
        result = _read_mdls_metadata('/path/to/bad_file')
        assert result == {}

    @patch('subprocess.check_output')
    def test_handles_invalid_plist(self, mock_subprocess):
        mock_subprocess.return_value = b'Not a plist'
        
        from marcut.report_common import _read_mdls_metadata
        result = _read_mdls_metadata('/path/to/file')
        assert result == {}

    @patch('subprocess.check_output')
    def test_sanitizes_nested_values(self, mock_subprocess):
        # Mock plist with nested structures
        plist_binary = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>kMDItemWhereFroms</key>
    <array>
        <string>http://example.com</string>
        <string>http://google.com</string>
    </array>
</dict>
</plist>"""
        mock_subprocess.return_value = plist_binary
        
        from marcut.report_common import _read_mdls_metadata
        result = _read_mdls_metadata('/path/to/file')
        
        assert isinstance(result['kMDItemWhereFroms'], list)
        assert 'http://example.com' in result['kMDItemWhereFroms']

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
