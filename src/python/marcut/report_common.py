"""
Shared report generation utilities for HTML reports.

Common CSS, JavaScript, and helper functions used by both
scrub reports (report_html.py) and audit reports (report.py).
"""
import datetime
import html
import mimetypes
import os
import plistlib
import stat
import subprocess
from typing import Any, Dict, List, Optional

try:
    import pwd
    import grp
except Exception:  # pragma: no cover - platform specific
    pwd = None
    grp = None


def escape_html(text: str) -> str:
    """Escape HTML special characters using standard library."""
    if not text:
        return ''
    return html.escape(str(text), quote=True)


def get_mime_type(file_path: str) -> str:
    """
    Get MIME type for a file using Python's mimetypes module.
    Falls back to application/octet-stream for unknown types.
    """
    mime_type = None
    try:
        # Avoid reading system mime.types in sandboxed environments.
        local_types = mimetypes.MimeTypes(files=[])
        mime_type, _ = local_types.guess_type(file_path)
    except Exception:
        try:
            mime_type, _ = mimetypes.guess_type(file_path)
        except Exception:
            mime_type = None
    return mime_type or 'application/octet-stream'


def format_file_size(size: int) -> str:
    """Format file size in human-readable format."""
    if size == 0:
        return "0 bytes"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    elif size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} bytes"


def get_binary_icon(file_type: str) -> str:
    """Get an emoji icon for a binary file type."""
    icons = {
        'image': '🖼️',
        'thumbnail': '📷',
        'font': '🔤',
        'macro': '⚙️',
        'printer_settings': '🖨️',
        'ole_embedding': '📎',
        'activex': '🔌',
    }
    return icons.get(file_type, '📁')


def _format_timestamp(epoch_seconds: Optional[float]) -> str:
    if epoch_seconds is None:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            epoch_seconds,
            datetime.timezone.utc
        ).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


def _decode_plist_value(raw: bytes) -> Any:
    try:
        return plistlib.loads(raw)
    except Exception:
        try:
            return raw.decode("utf-8", errors="ignore")
        except Exception:
            return None


def _clean_tag_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        tags = []
        for entry in value:
            tag = str(entry)
            if "\n" in tag:
                tag = tag.split("\n", 1)[0]
            if tag:
                tags.append(tag)
        return tags
    tag = str(value)
    if "\n" in tag:
        tag = tag.split("\n", 1)[0]
    return [tag] if tag else []

def _normalize_report_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(value, list):
        sanitized = [
            entry
            for entry in (_normalize_report_value(entry) for entry in value)
            if entry not in (None, "", [], {})
        ]
        return sanitized
    if isinstance(value, tuple):
        sanitized = [
            entry
            for entry in (_normalize_report_value(entry) for entry in value)
            if entry not in (None, "", [], {})
        ]
        return sanitized
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, entry in value.items():
            cleaned = _normalize_report_value(entry)
            if cleaned not in (None, "", [], {}):
                sanitized[str(key)] = cleaned
        return sanitized
    if isinstance(value, (str, int, float, bool)):
        return value
    try:
        return str(value)
    except Exception:
        return None

def _sanitize_mdls_value(value: Any) -> Any:
    return _normalize_report_value(value)


def _read_mdls_metadata(path: str) -> Dict[str, Any]:
    try:
        output = subprocess.check_output(
            ["/usr/bin/mdls", "-plist", "-", path],
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return {}

    try:
        data = plistlib.loads(output)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    sanitized: Dict[str, Any] = {}
    for key, value in data.items():
        cleaned = _sanitize_mdls_value(value)
        if cleaned not in (None, "", [], {}):
            sanitized[key] = cleaned
    return sanitized


def get_macos_file_info(path: str) -> Dict[str, Any]:
    """
    Collect only safe file metadata for reporting.
    """
    info: Dict[str, Any] = {}
    if not path or not os.path.exists(path):
        return info

    info["file_name"] = os.path.basename(path)

    try:
        st = os.stat(path, follow_symlinks=True)
    except Exception:
        return info

    size_bytes = getattr(st, "st_size", None)
    if size_bytes is not None:
        info["size_bytes"] = size_bytes

    mime_type = get_mime_type(path)
    if mime_type:
        info["mime_type"] = mime_type

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext:
        info["file_extension"] = ext

    return info


_DEFAULT_CSS = """
:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --text-primary: #c9d1d9;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --border-color: #30363d;
    --accent-color: #238636;
    --accent-hover: #2ea043;
    --warning-color: #d29922;
    --danger-color: #da3633;
    --info-color: #58a6ff;
    --link-color: #58a6ff;
    --high-confidence: #238636;
    --medium-confidence: #d29922;
    --low-confidence: #da3633;
    --cleaned-bg: rgba(35, 134, 54, 0.15);
    --preserved-bg: rgba(210, 153, 34, 0.15);
    --unchanged-bg: rgba(110, 118, 129, 0.1);
}

@media (prefers-color-scheme: light) {
    :root {
        --bg-primary: #ffffff;
        --bg-secondary: #f6f8fa;
        --bg-tertiary: #eaeef2;
        --text-primary: #24292f;
        --text-secondary: #57606a;
        --text-muted: #8c959f;
        --border-color: #d0d7de;
        --cleaned-bg: rgba(35, 134, 54, 0.1);
        --preserved-bg: rgba(210, 153, 34, 0.1);
        --unchanged-bg: rgba(110, 118, 129, 0.05);
    }
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
}

h1 {
    font-size: 1.75rem;
    margin-bottom: 0.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.subtitle {
    color: var(--text-secondary);
    font-size: 0.9rem;
    margin-bottom: 2rem;
}

.summary-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.summary-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
    text-align: center;
}

.summary-card .label {
    color: var(--text-secondary);
    font-size: 0.8rem;
    margin-bottom: 0.25rem;
}

.summary-card .value {
    font-size: 1.75rem;
    font-weight: 600;
}

.group {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: 1rem;
    overflow: hidden;
}

.group-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    cursor: pointer;
    user-select: none;
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border-color);
}

.group-header:hover { background: var(--bg-secondary); }

.group-header h2 {
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.group-header .count {
    font-weight: normal;
    color: var(--text-muted);
    font-size: 0.9rem;
}

.group-header .toggle { transition: transform 0.2s; }
.group.collapsed .toggle { transform: rotate(-90deg); }
.group.collapsed .group-content { display: none; }

.metadata-bar {
    background: var(--bg-tertiary);
    border-radius: 6px;
    padding: 0.75rem 1rem;
    margin-bottom: 1.5rem;
    display: flex;
    gap: 2rem;
    font-size: 0.85rem;
    color: var(--text-secondary);
}

.json-link {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    color: var(--info-color);
    text-decoration: none;
    font-size: 0.875rem;
    margin-top: 2rem;
}

.json-link:hover { background: var(--bg-secondary); }

.footer {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 0.8rem;
    text-align: center;
}
"""

_DEFAULT_JS = """
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.group-header').forEach(function(header) {
        header.addEventListener('click', function() {
            header.parentElement.classList.toggle('collapsed');
        });
    });
});
"""


def get_base_css() -> str:
    """
    Return base CSS variables and reset styles used by all reports.
    Includes dark/light theme support.
    """
    return _DEFAULT_CSS


def get_base_js() -> str:
    """Return base JavaScript for collapsible sections."""
    return _DEFAULT_JS
