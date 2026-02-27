"""
Report generation for redaction audit reports.

Generates both JSON and beautiful HTML reports for redacted entities.
"""
import json
import hashlib
import time
import os
from typing import Any, Dict, List, Optional

from .report_common import escape_html, get_base_css


def sha256_file(p: str) -> str:
    """Calculate SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for ch in iter(lambda: f.read(8192), b''):
            h.update(ch)
    return h.hexdigest()


def write_report(
    report_path: str,
    input_path: str,
    model: str,
    spans: List[Dict],
    settings: Optional[Dict] = None,
    warnings: Optional[List[Dict]] = None,
    suppressed: Optional[List[Dict]] = None
):
    """
    Write JSON and HTML audit reports.
    
    Args:
        report_path: Path for the JSON report (HTML will be same name with .html)
        input_path: Original input document path  
        model: Model identifier used for processing
        spans: List of detected entity spans
        settings: Optional processing settings
    """
    data = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'input_sha256': sha256_file(input_path),
        'model': model,
        'spans': spans
    }
    if warnings:
        data['warnings'] = warnings
    if suppressed:
        data['suppressed'] = suppressed
    if settings is not None:
        data['settings'] = settings
    
    # Write JSON report
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data, indent=2))
    
    # Generate HTML report alongside JSON
    try:
        html_path = os.path.splitext(report_path)[0] + '.html'
        _generate_html_audit_report(data, input_path, html_path)
    except Exception as e:
        data.setdefault("warnings", []).append({
            "code": "AUDIT_REPORT_HTML_FAILED",
            "message": "Audit report HTML generation failed.",
            "details": str(e)
        })
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(data, indent=2))
        except Exception:
            pass
        print(f"[MARCUT_REPORT] HTML report generation failed: {e}")


def _format_file_info_value(value: Any) -> str:
    if value is None or value == "":
        return '<span class="empty">(empty)</span>'
    if isinstance(value, list):
        items = ''.join(f'<li>{escape_html(str(item))}</li>' for item in value)
        return f'<ul>{items}</ul>'
    if isinstance(value, dict):
        try:
            payload = json.dumps(value, indent=2)
        except Exception:
            payload = str(value)
        return f'<pre>{escape_html(payload)}</pre>'
    return escape_html(str(value))


def _render_file_info_block(title: str, info: Dict[str, Any]) -> str:
    if not info:
        return ""

    ordered_fields = [
        ("input_sha256", "Input SHA-256"),
        ("file_name", "File Name"),
        ("file_extension", "Extension"),
        ("mime_type", "MIME Type"),
        ("size_bytes", "Size (Bytes)"),
    ]

    rows = []
    seen_keys = set()
    for key, label in ordered_fields:
        if key in info and info[key] not in (None, "", [], {}):
            rows.append(
                f'<div class="file-info-item"><div class="label">{escape_html(label)}</div>'
                f'<div class="value">{_format_file_info_value(info[key])}</div></div>'
            )
            seen_keys.add(key)

    for key in sorted(k for k in info.keys() if k not in seen_keys):
        value = info[key]
        if value in (None, "", [], {}):
            continue
        rows.append(
            f'<div class="file-info-item"><div class="label">{escape_html(str(key))}</div>'
            f'<div class="value">{_format_file_info_value(value)}</div></div>'
        )

    if not rows:
        return ""

    grid = "\n".join(rows)
    return f'''
    <div class="file-info">
        <h2>{escape_html(title)}</h2>
        <div class="file-info-grid">
            {grid}
        </div>
    </div>
'''


def _generate_html_audit_report(data: Dict[str, Any], input_path: str, html_path: str):
    """
    Generate an interactive HTML report for the redaction audit.
    
    Features:
    - Entity categorization by type
    - Confidence visualization
    - Source indicators (rule vs LLM)
    - Collapsible sections
    - Dark/light theme support
    """
    spans = data.get('spans', [])
    created_at = data.get('created_at', '')
    model = data.get('model', 'Unknown')
    input_hash = data.get('input_sha256', '')[:16]
    warnings = data.get('warnings') or []
    suppressed = data.get('suppressed') or []
    
    # Categorize spans by label
    categories: Dict[str, List[Dict]] = {}
    for span in spans:
        label = span.get('label', 'UNKNOWN')
        if label not in categories:
            categories[label] = []
        categories[label].append(span)
    
    # Count by source
    rule_count = sum(1 for s in spans if s.get('source', '') == 'rule')
    llm_count = sum(1 for s in spans if s.get('source', '') in ('llm', 'model', 'enhanced'))
    
    try:
        size_bytes = os.path.getsize(input_path)
        if size_bytes >= 1024 * 1024:
            size_label = f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            size_label = f"{size_bytes / 1024:.1f} KB"
        else:
            size_label = f"{size_bytes} bytes"
    except Exception:
        size_label = "unknown size"
    redaction_timestamp = created_at if created_at else "Unknown timestamp"
    file_name = os.path.basename(input_path)
    full_hash = data.get('input_sha256', '')

    # Build HTML
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Marcut Redaction Audit Report - {escape_html(file_name)}</title>
    <style>{_get_css()}</style>
</head>
<body>
    <div class="report-hero">
        <div class="report-summary">
            <div class="summary-title">Marcut Redaction Audit Report</div>
            <div class="summary-meta">Redaction timestamp: {escape_html(redaction_timestamp)} • File size: {escape_html(str(size_label))} • <a href="https://www.linkedin.com/in/marcmandel/" target="_blank" rel="noopener noreferrer">Authored by Marc Mandel</a></div>
            <div class="summary-file">File: {escape_html(file_name)}</div>
            <div class="summary-file">Model: {escape_html(str(model))} • Document SHA-256: {escape_html(full_hash)}</div>
        </div>
    </div>

    <div class="report-actions">
        <button class="report-action" id="print-report">🖨️ Print</button>
        <button class="report-action" id="share-report">⤴️ Share</button>
        <button class="report-action" id="burn-report">🔥 Burn</button>
    </div>
    
    <div class="summary-cards">
        <div class="summary-card total">
            <div class="label">Total Entities</div>
            <div class="value">{len(spans)}</div>
        </div>
        <div class="summary-card rule">
            <div class="label">Rule-based</div>
            <div class="value">{rule_count}</div>
        </div>
        <div class="summary-card llm">
            <div class="label">AI-detected</div>
            <div class="value">{llm_count}</div>
        </div>
        <div class="summary-card categories">
            <div class="label">Categories</div>
            <div class="value">{len(categories)}</div>
        </div>
    </div>
    
'''

    if warnings:
        warning_rows = []
        for w in warnings[:50]:
            detail = w.get("details")
            detail_html = f'<div class="notice-detail">{escape_html(str(detail))}</div>' if detail else ""
            warning_rows.append(
                f"<li><strong>{escape_html(w.get('code', 'WARNING'))}</strong> "
                f"{escape_html(w.get('message', ''))}{detail_html}</li>"
            )
        warning_items = "\n".join(warning_rows)
        html += f'''
    <div class="notice warning">
        <h2>Warnings</h2>
        <ul class="notice-list">
            {warning_items}
        </ul>
    </div>
'''

    suppressed_html = ""
    if suppressed:
        rows = []
        for item in suppressed[:200]:
            text = item.get("text", "")
            confidence = item.get("confidence")
            if confidence is None:
                confidence = item.get("score")
            if confidence is None:
                confidence = item.get("confidence_score")
            confidence_html = "—"
            if isinstance(confidence, (int, float)):
                confidence_class = 'high' if confidence >= 0.9 else ('medium' if confidence >= 0.7 else 'low')
                confidence_html = f'<span class="confidence-bar {confidence_class}" style="width: {confidence*100}%"></span> {confidence:.0%}'
            rows.append(
                f"<tr><td>{escape_html(str(item.get('reason', '')))}</td>"
                f"<td>{escape_html(str(item.get('label', '')))}</td>"
                f"<td class=\"entity-text\">{escape_html(text[:80])}{' …' if len(text) > 80 else ''}</td>"
                f"<td>{confidence_html}</td>"
                f"<td>{escape_html(str(item.get('source', '')))}</td></tr>"
            )
        suppressed_html = f'''
    <div class="group">
        <div class="group-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <h2>Suppressed Candidates <span class="count">({len(suppressed)})</span></h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
            <table class="entity-table">
                <thead>
                    <tr>
                        <th>Reason</th>
                        <th>Label</th>
                        <th>Text</th>
                        <th>Confidence</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </div>
'''
    
    # Add category sections
    for label, category_spans in sorted(categories.items(), key=lambda x: -len(x[1])):
        html += f'''
    <div class="group">
        <div class="group-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <h2>{escape_html(label)} <span class="count">({len(category_spans)})</span></h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
            <table class="entity-table">
                <thead>
                    <tr>
                        <th>Text</th>
                        <th>Confidence</th>
                        <th>Source</th>
                        <th>Position</th>
                    </tr>
                </thead>
                <tbody>
'''
        for span in category_spans[:100]:  # Limit to 100 per category
            text = span.get('text', '')[:80]
            confidence = span.get('confidence', 0)
            source = span.get('source', 'unknown')
            start = span.get('start', 0)
            end = span.get('end', 0)
            
            confidence_class = 'high' if confidence >= 0.9 else ('medium' if confidence >= 0.7 else 'low')
            source_badge = 'rule' if source == 'rule' else 'llm'
            
            html += f'''
                    <tr>
                        <td class="entity-text">{escape_html(text)}{' …' if len(span.get('text', '')) > 80 else ''}</td>
                        <td><span class="confidence-bar {confidence_class}" style="width: {confidence*100}%"></span> {confidence:.0%}</td>
                        <td><span class="source-badge {source_badge}">{source}</span></td>
                        <td class="position">{start}–{end}</td>
                    </tr>
'''
        
        if len(category_spans) > 100:
            html += f'''
                    <tr class="more-row">
                        <td colspan="4">... and {len(category_spans) - 100} more {label} entities</td>
                    </tr>
'''
        
        html += '''
                </tbody>
            </table>
        </div>
    </div>
'''
    if suppressed_html:
        html += suppressed_html
    
    # Footer and JSON link
    json_basename = os.path.basename(os.path.splitext(html_path)[0] + '.json')
    html += f'''
    <a href="{escape_html(json_basename)}" class="json-link" target="_blank">
        📄 View Raw JSON Data
    </a>
    
    <div class="footer">
        Generated by Marcut Legal Document Redactor
    </div>
    
    <script>
    function snapshotCollapseState() {{
        document.querySelectorAll('.group').forEach(group => {{
            group.dataset.wasCollapsed = group.classList.contains('collapsed') ? '1' : '0';
        }});
    }}

    function expandAllGroups() {{
        document.querySelectorAll('.group').forEach(group => {{
            group.classList.remove('collapsed');
        }});
    }}

    function restoreCollapseState() {{
        document.querySelectorAll('.group').forEach(group => {{
            if (group.dataset.wasCollapsed === '1') {{
                group.classList.add('collapsed');
            }} else {{
                group.classList.remove('collapsed');
            }}
        }});
    }}

    document.querySelectorAll('.group-header').forEach(header => {{
        header.style.cursor = 'pointer';
    }});

    const postReportAction = (action) => {{
        if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.reportAction) {{
            window.webkit.messageHandlers.reportAction.postMessage({{ action }});
            return true;
        }}
        return false;
    }};

    const printButton = document.getElementById('print-report');
    if (printButton) {{
        printButton.addEventListener('click', () => {{
            snapshotCollapseState();
            expandAllGroups();
            if (!postReportAction('print')) {{
                window.print();
            }}
        }});
    }}

    const shareButton = document.getElementById('share-report');
    if (shareButton) {{
        shareButton.addEventListener('click', () => {{
            if (postReportAction('share')) {{
                return;
            }}
            if (navigator.share) {{
                navigator.share({{
                    title: document.title,
                    url: window.location.href
                }}).catch(() => {{}});
            }} else {{
                alert('Sharing is available in the Marcut app.');
            }}
        }});
    }}

    const burnButton = document.getElementById('burn-report');
    if (burnButton) {{
        burnButton.addEventListener('click', () => {{
            if (postReportAction('burn')) {{
                return;
            }}
            alert('Burn is available in the Marcut app.');
        }});
    }}

    window.addEventListener('beforeprint', () => {{
        snapshotCollapseState();
        expandAllGroups();
    }});

    window.addEventListener('afterprint', restoreCollapseState);
    </script>
</body>
</html>
'''
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)




def _get_css() -> str:
    """Return embedded CSS for the audit report."""
    return """
:root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --text-primary: #c9d1d9;
    --text-secondary: #8b949e;
    --text-muted: #6e7681;
    --border-color: #30363d;
    --accent-color: #238636;
    --warning-color: #d29922;
    --info-color: #58a6ff;
    --high-confidence: #238636;
    --medium-confidence: #d29922;
    --low-confidence: #da3633;
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
    }
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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

h1::before { content: '🔍'; }

.report-hero {
    position: relative;
    background: linear-gradient(135deg, rgba(88, 166, 255, 0.18), rgba(35, 134, 54, 0.12));
    border: 1px solid rgba(88, 166, 255, 0.25);
    border-radius: 16px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1.75rem;
    display: grid;
    gap: 0.4rem;
    overflow: hidden;
}

.report-hero::after {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(circle at top right, rgba(88, 166, 255, 0.25), transparent 55%);
    pointer-events: none;
}

.report-summary {
    display: grid;
    gap: 0.4rem;
    position: relative;
    z-index: 1;
}

.summary-title {
    font-size: 1.25rem;
    font-weight: 800;
    letter-spacing: 0.02em;
}

.summary-meta {
    color: var(--text-secondary);
    font-size: 0.9rem;
}

.summary-meta a {
    color: var(--info-color);
    text-decoration: none;
}

.summary-meta a:hover {
    text-decoration: underline;
}

.summary-file {
    color: var(--text-muted);
    font-size: 0.85rem;
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

.summary-card.total .value { color: var(--info-color); }
.summary-card.rule .value { color: var(--accent-color); }
.summary-card.llm .value { color: #a371f7; }
.summary-card.categories .value { color: var(--text-primary); }

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

.notice {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    margin-bottom: 1.5rem;
    padding: 1rem;
}

.notice.warning {
    border-left: 4px solid var(--warning-color);
}

.notice h2 {
    font-size: 1rem;
    margin-bottom: 0.5rem;
}

.notice-list {
    margin-left: 1.25rem;
}

.notice-detail {
    color: var(--text-secondary);
    font-size: 0.85rem;
    margin-top: 0.25rem;
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
    background: var(--bg-tertiary);
    border-bottom: 1px solid var(--border-color);
    user-select: none;
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

.entity-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}

.entity-table th {
    text-align: left;
    padding: 0.75rem 1rem;
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-weight: 500;
    border-bottom: 1px solid var(--border-color);
}

.entity-table td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
}

.entity-table tr:hover { background: var(--bg-tertiary); }

.entity-text {
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    color: var(--text-primary);
    max-width: 400px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.confidence-bar {
    display: inline-block;
    height: 6px;
    border-radius: 3px;
    margin-right: 8px;
    vertical-align: middle;
}

.confidence-bar.high { background: var(--high-confidence); }
.confidence-bar.medium { background: var(--medium-confidence); }
.confidence-bar.low { background: var(--low-confidence); }

.source-badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
}

.source-badge.rule {
    background: var(--accent-color);
    color: white;
}

.source-badge.llm {
    background: #a371f7;
    color: white;
}

.position {
    color: var(--text-muted);
    font-family: 'SF Mono', Monaco, monospace;
    font-size: 0.8rem;
}

.more-row td {
    text-align: center;
    color: var(--text-muted);
    font-style: italic;
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

.report-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    margin-bottom: 1.5rem;
}

.report-action {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.8rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    color: var(--text-primary);
    font-size: 0.85rem;
    cursor: pointer;
}

.report-action:hover {
    background: var(--bg-tertiary);
}

.file-info {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1.5rem;
}

.file-info h2 {
    font-size: 1rem;
    margin-bottom: 0.75rem;
}

.file-info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.75rem;
}

.file-info-item .label {
    color: var(--text-secondary);
    font-size: 0.8rem;
    margin-bottom: 0.25rem;
}

.file-info-item .value {
    color: var(--text-primary);
    font-size: 0.9rem;
    word-break: break-word;
}

.file-info-item .value ul {
    margin-left: 1rem;
}

.file-info-item .value pre {
    white-space: pre-wrap;
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    font-size: 0.8rem;
}

@media print {
    body {
        max-width: none;
        padding: 0;
    }

    .report-actions,
    .json-link {
        display: none !important;
    }

    .group-content,
    .group.collapsed .group-content {
        display: block !important;
    }

    .group-header {
        background: transparent;
        border-bottom: none;
    }
}
"""
