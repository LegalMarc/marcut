"""
HTML Report Generator for Metadata Scrub Reports

Generates a beautiful, interactive HTML report that wraps the JSON data.
Features:
- Dark/light theme support
- Collapsible sections for large data
- Inline image previews
- Links to extracted binary files
- Link to raw JSON source
"""

import base64
import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import quote as url_quote

from .report_common import escape_html, get_mime_type, format_file_size, get_binary_icon


def _get_css() -> str:
    """Return embedded CSS for the report."""
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
    --accent-hover: #2ea043;
    --warning-color: #d29922;
    --danger-color: #da3633;
    --link-color: #58a6ff;
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

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

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

h1::before {
    content: '🔒';
}

body.metadata-only h1::before {
    content: '🔍';
}

.subtitle {
    color: var(--text-secondary);
    font-size: 0.9rem;
    margin-bottom: 2rem;
}

.summary-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
}

.summary-card {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 1rem;
}

.summary-card .label {
    color: var(--text-secondary);
    font-size: 0.875rem;
    margin-bottom: 0.25rem;
}

.summary-card .value {
    font-size: 1.5rem;
    font-weight: 600;
}

.summary-card.cleaned .value { color: var(--accent-color); }
.summary-card.preserved .value { color: var(--warning-color); }
.summary-card.unchanged .value { color: var(--text-muted); }

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

.file-info-labels {
    display: grid;
    grid-template-columns: minmax(180px, 1.15fr) minmax(260px, 2.25fr) minmax(260px, 2.25fr) max-content;
    gap: 1rem;
    padding: 0.4rem 1rem;
    border-bottom: 1px solid var(--border-color);
    color: var(--text-muted);
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.metadata-only .file-info-labels {
    grid-template-columns: minmax(180px, 1.15fr) minmax(320px, 3.35fr) max-content;
}

.file-info-label {
    font-weight: 600;
}

.info-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    margin-left: 0.5rem;
    border-radius: 50%;
    border: 1px solid var(--border-color);
    background: var(--bg-tertiary);
    color: var(--text-secondary);
    font-size: 0.7rem;
    cursor: pointer;
}

.info-tooltip-panel {
    position: absolute;
    z-index: 50;
    max-width: 520px;
    max-height: 260px;
    overflow-y: auto;
    padding: 0.85rem 1rem;
    border-radius: 10px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.45);
    color: var(--text-secondary);
    font-size: 0.85rem;
    white-space: pre-wrap;
}

.forensic-card {
    background: linear-gradient(135deg, rgba(218, 54, 51, 0.1), rgba(210, 153, 34, 0.1));
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
}

.forensic-card h2 {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1.05rem;
    margin-bottom: 0.5rem;
}

.forensic-subtitle {
    color: var(--text-muted);
    font-size: 0.85rem;
    margin-top: -0.15rem;
    margin-bottom: 0.75rem;
}

.forensic-items {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}

.forensic-item {
    padding: 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--bg-secondary);
}

.forensic-item.high { border-left: 4px solid var(--danger-color); }
.forensic-item.medium { border-left: 4px solid var(--warning-color); }
.forensic-item.low { border-left: 4px solid var(--text-muted); }
.forensic-item.info { border-left: 4px solid var(--link-color); }

.forensic-item strong { display: block; margin-bottom: 0.25rem; }
.forensic-evidence { color: var(--text-secondary); font-size: 0.9rem; margin-top: 0.15rem; }

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

.group-header:hover {
    background: var(--bg-secondary);
}

.group-header h2 {
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.group-header .toggle {
    transition: transform 0.2s;
}

.group-header.no-toggle {
    cursor: default;
}

.group-header.no-toggle .toggle {
    display: none;
}

.group.collapsed .toggle {
    transform: rotate(-90deg);
}

.group.collapsed .group-content {
    display: none;
}

.group-content {
    padding: 0;
}

.field-row {
    display: grid;
    grid-template-columns: minmax(180px, 1.15fr) minmax(260px, 2.25fr) minmax(260px, 2.25fr) max-content;
    gap: 1rem;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--border-color);
    align-items: start;
}

.metadata-only .field-row {
    grid-template-columns: minmax(180px, 1.15fr) minmax(320px, 3.35fr) max-content;
}

.field-row:last-child {
    border-bottom: none;
}

.field-row.cleaned { background: var(--cleaned-bg); }
.field-row.preserved { background: var(--preserved-bg); }
.field-row.unchanged { background: var(--unchanged-bg); }
.field-row.observed { background: var(--bg-secondary); }

.field-name {
    font-weight: 500;
    color: var(--text-primary);
}

.field-value {
    color: var(--text-secondary);
    word-break: break-word;
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    font-size: 0.875rem;
    min-width: 0;
}

.long-value-wrapper {
    position: relative;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    cursor: pointer;
}

.long-value-wrapper .long-value-preview {
    max-width: 100%;
    display: inline-block;
    font-family: inherit;
}

.long-value-tooltip {
    display: none;
    position: absolute;
    top: calc(100% + 0.25rem);
    left: 0;
    z-index: 10;
    width: min(420px, 90vw);
    padding: 0.75rem;
    border-radius: 8px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    word-break: break-word;
    white-space: pre-wrap;
}

.long-value-wrapper:hover .long-value-tooltip {
    display: block;
}

.long-value-tooltip .long-value-full {
    max-height: 200px;
    overflow: auto;
    margin-bottom: 0.5rem;
    font-size: 0.82rem;
    color: var(--text-secondary);
}

.long-value-copy {
    display: inline-flex;
    gap: 0.35rem;
    align-items: center;
    justify-content: center;
    border: none;
    background: var(--border-color);
    color: var(--text-primary);
    border-radius: 6px;
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    cursor: pointer;
}

.long-value-copy.copied {
    background: var(--accent-color);
    color: #fff;
}

.list-item {
    padding: 0.35rem 0;
}

.list-item + .list-item {
    border-top: 1px solid var(--border-color);
}

.list-item-block {
    display: grid;
    gap: 0.35rem;
}

.list-item-row {
    display: grid;
    grid-template-columns: 160px 1fr;
    gap: 0.5rem;
    align-items: start;
}

.list-item-key {
    font-weight: 600;
    color: var(--text-secondary);
}

.list-item-value {
    word-break: break-word;
}

.comment-card {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 0.6rem 0.75rem;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
    color: var(--text-primary);
}

.comment-header {
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.comment-author {
    font-weight: 600;
}

.comment-meta {
    color: var(--text-muted);
    font-size: 0.75rem;
}

.comment-status {
    padding: 0.1rem 0.45rem;
    border-radius: 999px;
    font-size: 0.65rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 600;
}

.comment-status.visible {
    background: rgba(35, 134, 54, 0.18);
    color: var(--accent-color);
}

.comment-status.hidden {
    background: rgba(210, 153, 34, 0.18);
    color: var(--warning-color);
}

.comment-status.deleted {
    background: rgba(218, 54, 51, 0.18);
    color: var(--danger-color);
}

.comment-anchor {
    margin-top: 0.35rem;
    font-size: 0.8rem;
    color: var(--text-secondary);
}

.comment-anchor .label {
    color: var(--text-muted);
    font-size: 0.65rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    font-weight: 600;
    margin-right: 0.35rem;
}

.comment-body {
    margin-top: 0.5rem;
    white-space: pre-wrap;
    font-size: 0.9rem;
    line-height: 1.45;
}

.metadata-only .after-value {
    display: none;
}

.field-value.empty {
    font-style: italic;
    color: var(--text-muted);
}

.status-badge {
    padding: 0.125rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 500;
    text-transform: uppercase;
    white-space: nowrap;
}

.status-badge.cleaned {
    background: var(--accent-color);
    color: white;
}

.status-badge.preserved {
    background: var(--warning-color);
    color: white;
}

.status-badge.unchanged {
    background: var(--text-muted);
    color: white;
}

.status-badge.observed {
    background: rgba(87, 96, 106, 0.12);
    color: #57606a;
}

.collapsible-content {
    max-height: 200px;
    overflow-y: auto;
    background: var(--bg-tertiary);
    border-radius: 4px;
    padding: 0.5rem;
    margin-top: 0.5rem;
}

.collapsible-toggle {
    color: var(--link-color);
    cursor: pointer;
    font-size: 0.8rem;
    margin-top: 0.25rem;
}

.collapsible-toggle:hover {
    text-decoration: underline;
}

.binary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 1rem;
    padding: 1rem;
}

.binary-tag {
    align-self: flex-start;
    display: inline-block;
    margin-bottom: 0.35rem;
    padding: 0.15rem 0.5rem;
    border-radius: 999px;
    background: rgba(88, 166, 255, 0.15);
    color: var(--text-secondary);
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.binary-card {
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    overflow: hidden;
    text-decoration: none;
    color: inherit;
    transition: border-color 0.2s;
    cursor: pointer;
}

.binary-card:hover {
    border-color: var(--link-color);
}

.binary-preview {
    height: 100px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--bg-secondary);
    font-size: 2rem;
}

.binary-preview img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}

.binary-info {
    padding: 0.75rem;
}

.binary-name {
    font-size: 0.75rem;
    color: var(--text-primary);
    word-break: break-all;
    margin-bottom: 0.25rem;
}

.binary-size {
    font-size: 0.7rem;
    color: var(--text-muted);
}

.json-link {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    color: var(--link-color);
    text-decoration: none;
    font-size: 0.875rem;
    margin-top: 2rem;
}

.deep-explorer {
    display: grid;
    gap: 1rem;
    padding: 1rem;
}

.deep-explorer-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 1rem;
}

.deep-explorer-controls {
    display: flex;
    gap: 0.75rem;
    align-items: center;
}

.deep-explorer-controls input {
    flex: 1;
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    border: 1px solid var(--border-color);
    background: var(--bg-tertiary);
    color: var(--text-primary);
}

.deep-explorer-section {
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 0.75rem;
    cursor: pointer;
}

.deep-explorer-section.active {
    border-color: var(--link-color);
    box-shadow: 0 0 0 1px rgba(88, 166, 255, 0.35);
}

.deep-explorer-section h3 {
    margin: 0 0 0.5rem;
    font-size: 0.95rem;
}

.deep-explorer-links {
    display: flex;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
}

.deep-explorer-links a {
    font-size: 0.75rem;
    color: var(--link-color);
    text-decoration: none;
}

.deep-explorer-links a:hover {
    text-decoration: underline;
}

.deep-explorer-tree ul {
    list-style: none;
    padding-left: 1rem;
    margin: 0.25rem 0;
}

.deep-explorer-tree details > summary {
    cursor: pointer;
    color: var(--text-primary);
    font-size: 0.85rem;
}

.deep-explorer-tree .part-link {
    color: var(--link-color);
    font-size: 0.8rem;
    text-decoration: none;
}

.deep-explorer-tree .part-meta {
    color: var(--text-muted);
    font-size: 0.72rem;
    margin-left: 0.4rem;
}

.deep-explorer-results {
    margin-top: 0.5rem;
    font-size: 0.85rem;
    color: var(--text-secondary);
}

.deep-explorer-result {
    border-bottom: 1px solid var(--border-color);
    padding: 0.5rem 0;
}

.deep-explorer-result:last-child {
    border-bottom: none;
}

.deep-explorer-snippet {
    color: var(--text-muted);
    font-size: 0.78rem;
    margin-top: 0.25rem;
    white-space: pre-wrap;
}

.json-link:hover {
    background: var(--bg-secondary);
}

.footer {
    margin-top: 3rem;
    padding-top: 1.25rem;
    border-top: 1px solid var(--border-color);
    color: var(--text-secondary);
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: 0.01em;
    text-align: center;
}

.search-overlay {
    position: fixed;
    top: 1rem;
    right: 1rem;
    display: none;
    align-items: center;
    gap: 0.25rem;
    padding: 0.35rem;
    border-radius: 12px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    z-index: 50;
}

.search-overlay.active {
    display: inline-flex;
}

.search-overlay input {
    border: none;
    background: transparent;
    outline: none;
    color: var(--text-primary);
    font-size: 0.9rem;
    min-width: 180px;
}

.search-overlay button {
    border: none;
    border-radius: 8px;
    background: var(--border-color);
    color: var(--text-primary);
    padding: 0.25rem 0.5rem;
    font-size: 0.75rem;
    cursor: pointer;
}

.search-overlay button.close {
    background: transparent;
    color: var(--text-muted);
}


.report-hero {
    position: relative;
    background: linear-gradient(135deg, rgba(88, 166, 255, 0.18), rgba(35, 134, 54, 0.12));
    border: 1px solid rgba(88, 166, 255, 0.25);
    border-radius: 16px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1.75rem;
    display: grid;
    gap: 1rem;
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
    color: var(--link-color);
    text-decoration: none;
}

.summary-meta a:hover {
    text-decoration: underline;
}

.summary-file {
    color: var(--text-muted);
    font-size: 0.85rem;
}

.report-hero .forensic-card {
    background: transparent;
    border: none;
    padding: 0;
    margin: 0;
    position: relative;
    z-index: 1;
}

.scroll-box {
    max-height: 200px;
    overflow: auto;
    padding: 0.6rem 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background: var(--bg-tertiary);
    font-family: 'SF Mono', Monaco, Consolas, monospace;
    font-size: 0.85rem;
    color: var(--text-secondary);
    white-space: pre-wrap;
    max-width: 100%;
    box-sizing: border-box;
    word-break: break-word;
}

.scroll-box pre {
    margin: 0;
    white-space: pre-wrap;
}

.scroll-box ul {
    margin: 0;
    padding-left: 1rem;
}

.file-info-group {
    margin-bottom: 1.5rem;
}

.file-info-group .group-content {
    padding: 0;
}

.file-info-group .field-row {
    border-bottom: 1px solid var(--border-color);
}

.file-info-group .field-row:last-child {
    border-bottom: none;
}

.field-row.file-info-row {
    grid-template-columns: 1fr 3fr;
    gap: 1rem;
    padding: 0.75rem 1rem;
}

.field-row.file-info-row .field-value {
    font-size: 0.9rem;
    color: var(--text-primary);
}

/* Image inline preview */
.inline-image {
    max-width: 200px;
    max-height: 150px;
    border-radius: 4px;
    margin: 0.5rem 0;
}

@media print {
    body {
        max-width: none;
        padding: 0;
    }

    .json-link,
    .collapsible-toggle {
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


def _get_js() -> str:
    """Return embedded JavaScript for interactivity."""
    return """
function snapshotCollapseState() {
    document.querySelectorAll('.group').forEach(group => {
        group.dataset.wasCollapsed = group.classList.contains('collapsed') ? '1' : '0';
    });
}

function expandAllGroups() {
    document.querySelectorAll('.group').forEach(group => {
        group.classList.remove('collapsed');
    });
}

function restoreCollapseState() {
    document.querySelectorAll('.group').forEach(group => {
        if (group.dataset.wasCollapsed === '1') {
            group.classList.add('collapsed');
        } else {
            group.classList.remove('collapsed');
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // Toggle group collapse
    document.querySelectorAll('.group-header').forEach(header => {
        if (header.classList.contains('no-toggle')) {
            return;
        }
        header.addEventListener('click', () => {
            header.parentElement.classList.toggle('collapsed');
        });
    });
    
    // Collapsible content toggle
    document.querySelectorAll('.collapsible-toggle').forEach(toggle => {
        toggle.addEventListener('click', (e) => {
            e.preventDefault();
            const content = toggle.previousElementSibling;
            if (content.style.maxHeight === 'none') {
                content.style.maxHeight = '200px';
                toggle.textContent = 'Show all ▼';
            } else {
                content.style.maxHeight = 'none';
                toggle.textContent = 'Collapse ▲';
            }
        });
    });

    const searchOverlay = document.getElementById('report-search-overlay');
    const searchInput = document.getElementById('report-search-input');
    const searchNext = document.getElementById('report-search-next');
    const closeSearch = document.getElementById('report-search-close');

    const showSearch = () => {
        if (!searchOverlay || !searchInput) return;
        searchOverlay.classList.add('active');
        searchInput.focus();
        searchInput.select();
    };

    const hideSearch = () => {
        if (searchOverlay) {
            searchOverlay.classList.remove('active');
        }
    };

    document.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && (event.key === 'f' || event.key === 'F')) {
            event.preventDefault();
            showSearch();
        } else if (event.key === 'Escape') {
            hideSearch();
        }
    });

    const findNext = () => {
        const value = searchInput ? searchInput.value : '';
        if (!value) {
            return;
        }
        window.find(value, false, false, true, false, true, false);
    };

    if (searchNext) {
        searchNext.addEventListener('click', findNext);
    }
    if (searchInput) {
        searchInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                findNext();
            }
        });
    }
    if (closeSearch) {
        closeSearch.addEventListener('click', hideSearch);
    }

    document.addEventListener('click', function(event) {
        var target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        var button = target.closest('.long-value-copy');
        if (!button) {
            return;
        }
        var text = button.getAttribute('data-fulltext') || '';
        if (!text) {
            var wrapper = button.closest('.long-value-wrapper');
            text = wrapper ? wrapper.getAttribute('data-fulltext') || '' : '';
        }
        if (!text) {
            return;
        }
        var copyBlock = function(content) {
            try {
                navigator.clipboard.writeText(content).then(function() {
                    button.classList.add('copied');
                    setTimeout(function() { button.classList.remove('copied'); }, 1200);
                });
            } catch (err) {
                var textarea = document.createElement('textarea');
                textarea.value = content;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                button.classList.add('copied');
                setTimeout(function() { button.classList.remove('copied'); }, 1200);
            }
        };
        copyBlock(text);
        event.stopPropagation();
    });

    const tooltipPanel = document.createElement('div');
    tooltipPanel.className = 'info-tooltip-panel';
    tooltipPanel.style.display = 'none';
    document.body.appendChild(tooltipPanel);

    document.addEventListener('click', function(event) {
        const target = event.target;
        if (!(target instanceof HTMLElement)) {
            return;
        }
        const icon = target.closest('.info-icon');
        if (icon) {
            const content = icon.getAttribute('data-tooltip') || '';
            tooltipPanel.textContent = content;
            const rect = icon.getBoundingClientRect();
            tooltipPanel.style.top = window.scrollY + rect.bottom + 8 + 'px';
            tooltipPanel.style.left = window.scrollX + rect.left + 'px';
            tooltipPanel.style.display = 'block';
            event.stopPropagation();
            return;
        }
        if (tooltipPanel.style.display === 'block') {
            tooltipPanel.style.display = 'none';
        }
    });

    const deepExplorerDataEl = document.getElementById('deep-explorer-data');
    if (deepExplorerDataEl) {
        try {
            const deepData = JSON.parse(deepExplorerDataEl.textContent || '{}');
            const searchInput = document.getElementById('deep-explorer-search');
            const countEl = document.getElementById('deep-explorer-count');
            const resultEl = document.getElementById('deep-explorer-results');
            const sectionEls = Array.from(document.querySelectorAll('.deep-explorer-section[data-scope]'));
            const hasPostScope = sectionEls.some(function(el) { return (el.dataset.scope || '') === 'post'; });
            let activeScope = 'pre';
            const safeHref = function(rawPath) {
                if (!rawPath) {
                    return '#';
                }
                try {
                    return encodeURI(rawPath);
                } catch (e) {
                    return '#';
                }
            };

            const buildTree = function(parts) {
                const root = {};
                parts.forEach(function(part) {
                    const segments = part.name.split('/');
                    let node = root;
                    segments.forEach(function(seg, idx) {
                        node.children = node.children || {};
                        node.children[seg] = node.children[seg] || {};
                        node = node.children[seg];
                        if (idx === segments.length - 1) {
                            node.part = part;
                        }
                    });
                });
                return root;
            };

            const renderNode = function(node) {
                const ul = document.createElement('ul');
                const children = node.children || {};
                Object.keys(children).sort().forEach(function(key) {
                    const child = children[key];
                    const li = document.createElement('li');
                    if (child.children) {
                        const details = document.createElement('details');
                        const summary = document.createElement('summary');
                        summary.textContent = key;
                        details.appendChild(summary);
                        details.appendChild(renderNode(child));
                        li.appendChild(details);
                    } else if (child.part) {
                        const link = document.createElement('a');
                        link.href = safeHref(child.part.path);
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.className = 'part-link';
                        link.textContent = key;
                        const meta = document.createElement('span');
                        meta.className = 'part-meta';
                        meta.textContent = `(${child.part.size} bytes)`;
                        li.appendChild(link);
                        li.appendChild(meta);
                    }
                    ul.appendChild(li);
                });
                return ul;
            };

            const attachTree = function(scope, treeId, linkId) {
                const payload = deepData[scope];
                if (!payload || !payload.parts) {
                    return;
                }
                const treeRoot = buildTree(payload.parts);
                const treeContainer = document.getElementById(treeId);
                if (treeContainer) {
                    treeContainer.appendChild(renderNode(treeRoot));
                }
                const linksContainer = document.getElementById(linkId);
                if (linksContainer && payload.raw_text_path) {
                    const rawLink = document.createElement('a');
                    rawLink.href = safeHref(payload.raw_text_path);
                    rawLink.target = '_blank';
                    rawLink.rel = 'noopener noreferrer';
                    rawLink.textContent = 'Open Raw Text Index';
                    linksContainer.appendChild(rawLink);
                }
            };

            attachTree('pre', 'deep-explorer-pre-tree', 'deep-explorer-pre-links');
            attachTree('post', 'deep-explorer-post-tree', 'deep-explorer-post-links');

            const allParts = []
                .concat(deepData.pre && deepData.pre.parts ? deepData.pre.parts.map(p => ({...p, scope: 'pre'})) : [])
                .concat(deepData.post && deepData.post.parts ? deepData.post.parts.map(p => ({...p, scope: 'post'})) : []);

            const setActiveScope = function(scope) {
                activeScope = scope;
                sectionEls.forEach(function(el) {
                    el.classList.toggle('active', el.dataset.scope === scope);
                });
                if (searchInput) {
                    const query = searchInput.value || '';
                    renderResults(searchParts(query), query);
                }
            };

            sectionEls.forEach(function(el) {
                el.addEventListener('click', function() {
                    setActiveScope(el.dataset.scope || 'pre');
                });
            });

            const searchParts = function(query) {
                const q = query.toLowerCase();
                return allParts.filter(function(part) {
                    if (part.scope !== activeScope) {
                        return false;
                    }
                    if (part.name.toLowerCase().includes(q)) {
                        return true;
                    }
                    if (part.text && part.text.toLowerCase().includes(q)) {
                        return true;
                    }
                    return false;
                });
            };

            const renderResults = function(results, query) {
                if (!resultEl) {
                    return;
                }
                resultEl.innerHTML = '';
                if (!query) {
                    resultEl.textContent = '';
                    if (countEl) countEl.textContent = '';
                    return;
                }
                if (countEl) {
                    const scopeLabel = hasPostScope
                        ? (activeScope === 'post' ? 'Post‑Scrub' : 'Pre‑Scrub')
                        : 'Document Package';
                    countEl.textContent = `${results.length} matches • ${scopeLabel}`;
                }
                results.slice(0, 200).forEach(function(part) {
                    const wrapper = document.createElement('div');
                    wrapper.className = 'deep-explorer-result';
                    const link = document.createElement('a');
                    link.href = safeHref(part.path);
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.className = 'part-link';
                    link.textContent = hasPostScope ? `${part.scope.toUpperCase()}: ${part.name}` : part.name;
                    wrapper.appendChild(link);
                    if (part.text) {
                        const idx = part.text.toLowerCase().indexOf(query.toLowerCase());
                        if (idx >= 0) {
                            const start = Math.max(0, idx - 80);
                            const end = Math.min(part.text.length, idx + 160);
                            const snippet = part.text.substring(start, end);
                            const snippetEl = document.createElement('div');
                            snippetEl.className = 'deep-explorer-snippet';
                            snippetEl.textContent = snippet;
                            wrapper.appendChild(snippetEl);
                        }
                    }
                    resultEl.appendChild(wrapper);
                });
            };

            setActiveScope(activeScope);

            if (searchInput) {
                searchInput.addEventListener('input', function() {
                    const query = searchInput.value || '';
                    renderResults(searchParts(query), query);
                });
            }
        } catch (err) {
            // ignore deep explorer parsing errors
        }
    }
});

window.addEventListener('beforeprint', () => {
    snapshotCollapseState();
    expandAllGroups();
});

window.addEventListener('afterprint', restoreCollapseState);
"""


def _long_value_html(text: str) -> str:
    """
    Format a long string in an inline scroll box.
    """
    if len(text) <= 80:
        return escape_html(text)
    escaped_full = escape_html(text)
    return f'<div class="scroll-box">{escaped_full}</div>'


def _format_value(value: Any, max_items: int = 10) -> tuple[str, bool]:
    """
    Format a value for HTML display.
    Returns (html_string, needs_collapsible).
    """
    if value is None or value == '':
        return '<span class="empty">(empty)</span>', False
    
    if isinstance(value, str):
        if len(value) > 500:
            return f'<div class="collapsible-content">{escape_html(value)}</div><span class="collapsible-toggle">Show all ▼</span>', True
        return escape_html(value), False
    
    if isinstance(value, bool):
        return str(value).lower(), False
    
    if isinstance(value, (int, float)):
        return str(value), False
    
    if isinstance(value, list):
        if not value:
            return '<span class="empty">(empty list)</span>', False
        
        if len(value) > max_items:
            items_html = ''.join(f'<div class="list-item">{_format_list_item(item)}</div>' for item in value)
            return f'<div class="collapsible-content">{items_html}</div><span class="collapsible-toggle">Show all {len(value)} items ▼</span>', True
        
        return ''.join(f'<div class="list-item">{_format_list_item(item)}</div>' for item in value), False
    
    if isinstance(value, dict):
        if not value:
            return '<span class="empty">(empty)</span>', False
        
        items = [f'<strong>{escape_html(str(k))}:</strong> {escape_html(str(v))}' for k, v in value.items()]
        if len(items) > 5:
            content = '<br>'.join(items)
            return f'<div class="collapsible-content">{content}</div><span class="collapsible-toggle">Show all ▼</span>', True
        return '<br>'.join(items), False
    
    return escape_html(str(value)), False


def _format_list_item(item: Any) -> str:
    """Format a single list item."""
    if isinstance(item, dict):
        if "comment_text" in item or "anchor_text" in item:
            return _format_review_comment(item)
        rows = []
        needs_scroll = False
        for key, value in item.items():
            if value is None or value == "" or value == [] or value == {}:
                rendered = '<span class="empty">(empty)</span>'
            elif isinstance(value, str):
                if len(value) > 120:
                    rendered = escape_html(value)
                    needs_scroll = True
                else:
                    rendered = escape_html(value)
            else:
                rendered, _ = _format_value(value, max_items=5)
                if isinstance(rendered, str) and ("scroll-box" in rendered or "collapsible-content" in rendered):
                    needs_scroll = True
            rows.append(
                f'<div class="list-item-row">'
                f'<span class="list-item-key">{escape_html(str(key))}</span>'
                f'<span class="list-item-value">{rendered}</span>'
                f'</div>'
            )
        if not rows:
            return '(empty)'
        body = f'<div class="list-item-block">{"".join(rows)}</div>'
        return f'<div class="scroll-box">{body}</div>' if needs_scroll else body
    return escape_html(str(item))

def _format_review_comment(item: Dict[str, Any]) -> str:
    author = (item.get("author") or "").strip() or "Unknown"
    date = (item.get("date") or "").strip()
    status = (item.get("status") or "visible").strip().lower()
    if status not in ("visible", "hidden", "deleted"):
        status = "visible"
    anchor_text = (item.get("anchor_text") or "").strip() or "(none)"
    comment_text = (item.get("comment_text") or "").strip() or "(empty)"
    comment_id = (item.get("comment_id") or "").strip()

    meta_bits = []
    if comment_id:
        meta_bits.append(f"ID {comment_id}")
    if date:
        meta_bits.append(date)
    meta_html = " • ".join(escape_html(bit) for bit in meta_bits)
    meta_html_block = f'<div class="comment-meta">{meta_html}</div>' if meta_html else ""
    status_label = f"status: {status}"

    return f"""
<div class="comment-card">
    <div class="comment-header">
        <div class="comment-author">{escape_html(author)}</div>
        {meta_html_block}
        <span class="comment-status {escape_html(status)}">{escape_html(status_label)}</span>
    </div>
    <div class="comment-anchor">
        <span class="label">Anchor</span>{escape_html(anchor_text)}
    </div>
    <div class="comment-body">{escape_html(comment_text)}</div>
</div>
"""

def _format_file_info_value(value: Any) -> str:
    if value is None or value == "":
        return '<span class="empty">(empty)</span>'
    if isinstance(value, list):
        items = ''.join(f'<li>{escape_html(str(item))}</li>' for item in value)
        return f'<div class="scroll-box"><ul>{items}</ul></div>'
    if isinstance(value, dict):
        try:
            payload = json.dumps(value, indent=2)
        except Exception:
            payload = str(value)
        return f'<div class="scroll-box"><pre>{escape_html(payload)}</pre></div>'
    text = str(value)
    if isinstance(value, str) and len(text) > 100:
        return _long_value_html(text)
    return escape_html(text)


_FILE_INFO_GLOSSARY = {
    "sha256": "SHA-256 — cryptographic hash of the file bytes. In comparison view, left is the pre-scrub input file and right is the post-scrub output file.",
    "file_name": "File Name — the filename as recorded by the macOS filesystem. It reflects how the file is labeled on disk (Finder), not the internal name inside the DOCX package. This value can change when a file is copied, renamed, or saved elsewhere.",
    "file_extension": "Extension — the suffix of the filename (e.g., .docx). This is used by macOS and applications to infer file type and default handlers. It is not stored inside the DOCX.",
    "mime_type": "MIME Type — the media type reported by macOS for this file (e.g., application/vnd.openxmlformats-officedocument.wordprocessingml.document). It is derived by Spotlight and the OS, not embedded in the DOCX.",
    "size_bytes": "Size (Bytes) — the exact byte count of the file as stored on disk by macOS. This is not embedded in the DOCX, but can indicate changes or packing differences.",
}


_GROUP_SOURCE_MAP = {
    "App Properties": "docProps/app.xml (Office application metadata)",
    "Core Properties": "docProps/core.xml (Dublin Core + core document metadata)",
    "Custom Properties": "docProps/custom.xml and /customXml parts",
    "Document Structure": "word/document.xml + related structural parts (settings, comments, headers/footers)",
    "Embedded Content": "binary package parts (word/media, word/embeddings, fonts, macros)",
    "Advanced Hardening": "relationships, styles, and extended Office namespaces",
}


_FIELD_GLOSSARY = {
    "Title": "Technical: <dc:title> in docProps/core.xml. User-supplied document title string. Forensic relevance: can reveal intended title or distinguish versions when populated.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Subject": "Technical: <dc:subject> free-text topic in docProps/core.xml. Forensic relevance: often empty, but can contain project or matter labels.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Author": "Technical: <dc:creator> initial creator saved by Word. Forensic relevance: primary attribution of origin.\nForensic notes: Often reflects the Windows/macOS Office user profile and may be a full name, login, or email. Templates and DMS systems sometimes overwrite this field, so corroborate with tracked changes or comments.",
    "Last Modified By": "Technical: <cp:lastModifiedBy> updated on each save. Forensic relevance: identifies the most recent editor.\nForensic notes: Frequently changes with every save, so it can reveal the last environment the file passed through. If it conflicts with tracked changes authors, that mismatch is often evidentiary.",
    "Created Date": "Technical: <dcterms:created> W3C datetime. Forensic relevance: anchors when the document was first authored.\nForensic notes: Stored in ISO/W3C datetime; if no timezone is present, Word treats it as local time. Creation time can change if content is copied into a new file or if a template is saved as a new document.",
    "Modified Date": "Technical: <dcterms:modified> W3C datetime. Forensic relevance: last save timestamp for timeline analysis.\nForensic notes: Updated on each save; it can be more reliable than filesystem timestamps, which change on copy. If a document is edited by non-Word tools, this value may be stale or inconsistent.",
    "Last Printed": "Technical: <cp:lastPrinted> timestamp when print was invoked. Forensic relevance: shows if/when a hard copy was produced.\nForensic notes: Word records only the timestamp of the last print command, not who printed it. The field is often blank in documents that were never printed or when saving is disabled after printing.",
    "Revision Number": "Technical: <cp:revision> save counter incremented by Word. Forensic relevance: indicates editing activity; resets can signal Save As or cleaning.\nForensic notes: This counter increments on save and can reset after Save As or when metadata is scrubbed. A high revision count with very low edit time can be suspicious, but autosave and template reuse can also explain it.",
    "Category": "Technical: <cp:category> user-defined grouping label. Forensic relevance: can reveal internal classification if populated.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Content Status": "Technical: <cp:contentStatus> workflow state (Draft/Final/Reviewed). Forensic relevance: indicates document stage.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Content Type": "Technical: <cp:contentType> content genre label (not MIME). Forensic relevance: can reveal intended use if set (proposal, manual).\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Comments": "Technical: <dc:description> free-text summary or notes. Forensic relevance: may contain internal context not meant for recipients.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Keywords": "Technical: <cp:keywords> tag list string. Forensic relevance: can expose case numbers, topics, or internal search tags.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Language": "Technical: <dc:language> locale code (e.g., en-US). Forensic relevance: can indicate origin or intended audience.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Identifier": "Technical: <dc:identifier> optional external ID. Forensic relevance: ties the file to a DMS, GUID, or URI if present.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Version": "Technical: <cp:version> manual version label. Forensic relevance: indicates declared version separate from revision count.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Rights (Copyright)": "Technical: <dc:rights> rights/copyright statement. Forensic relevance: can show restrictions or publisher policy.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Publisher": "Technical: <dc:publisher> organization responsible for the document. Forensic relevance: can indicate corporate origin.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Issued Date": "Technical: <dcterms:issued> publication/issuance date. Forensic relevance: rare in DOCX but useful if present.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Available Date": "Technical: <dcterms:available> availability date. Forensic relevance: rare, can indicate release window.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Valid Date": "Technical: <dcterms:valid> validity period. Forensic relevance: rare, can indicate expiration.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Type (DC)": "Technical: <dc:type> optional genre/type. Forensic relevance: can describe document class when populated.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Format (DC)": "Technical: <dc:format> optional format descriptor. Forensic relevance: rarely used but can expose tooling.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Source (DC)": "Technical: <dc:source> optional source reference. Forensic relevance: can link to system-of-record or upstream material.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Relation (DC)": "Technical: <dc:relation> optional related resource. Forensic relevance: can link to companion files or sources.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Coverage (DC)": "Technical: <dc:coverage> optional spatial/temporal scope. Forensic relevance: can indicate geography or time range.\nForensic notes: Core properties live in docProps/core.xml and are editable via File > Info > Properties or by templates and DMS tools. Many are blank unless explicitly set; treat populated values as author- or system-supplied context, not a guaranteed truth.",
    "Template": "Technical: <Template> in docProps/app.xml. Base template name (e.g., Normal.dotm), not a path. Forensic relevance: can identify organizational templates or workflows.\nForensic notes: This is just the template filename from app.xml. The full path (often the most revealing) is stored separately in settings.xml as Attached Template Path.",
    "Total Editing Time": "Technical: <TotalTime> total minutes the document was open (includes idle). Forensic relevance: rough effort indicator; very low values can suggest reset.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Document Statistics": "Technical: app.xml counts (Pages, Words, Characters, CharactersWithSpaces, Paragraphs, Lines). Forensic relevance: compares document size at last save to visible content.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Company": "Technical: <Company> from Office user profile or document properties. Forensic relevance: strong indicator of organization.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Manager": "Technical: <Manager> profile/property value. Forensic relevance: can reveal supervisor or approval chain.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Application": "Technical: <Application> software that last saved the file. Forensic relevance: toolchain attribution (Word vs automation).\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "App Version": "Technical: <AppVersion> numeric version string (e.g., 16.0000). Forensic relevance: consistency check for claimed environment.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Document Security": "Technical: <DocSecurity> numeric flags (0 none, 1 encrypted, 2 read-only recommended, 4 read-only enforced, 8 track-changes lock). Forensic relevance: indicates protection state.\nForensic notes: Values are bit flags (0 none, 1 encrypted, 2 read-only recommended, 4 read-only enforced, 8 track-changes lock). This is separate from package encryption detection, which looks for EncryptionInfo/EncryptedPackage.",
    "Hyperlink Base": "Technical: <HyperlinkBase> base URL/path for relative links. Forensic relevance: can expose network shares or SharePoint roots.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Hyperlink List (HLinks)": "Technical: <HLinks> vector enumerating hyperlinks at last save. Forensic relevance: can expose link targets even if removed from visible text.\nForensic notes: Stored as a vector of hyperlink strings at last save. Entries can persist even if the visible hyperlink text was removed, so it is useful for ghost links.",
    "Hyperlinks Changed Flag": "Technical: <HyperlinksChanged> boolean. Forensic relevance: indicates hyperlink targets were updated since last save.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Links Up-to-Date Flag": "Technical: <LinksUpToDate> boolean. Forensic relevance: indicates linked objects were refreshed.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Shared Document Flag": "Technical: <SharedDoc> legacy shared editing flag. Forensic relevance: rare, but indicates shared status.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Thumbnail Settings": "Technical: <ScaleCrop> preview thumbnail scaling. Forensic relevance: low, but relevant when thumbnails exist.\nForensic notes: Extended application properties live in docProps/app.xml and are updated by Word on save/close. Third-party editors may leave them stale; use them as indicators, not absolute proof.",
    "Paragraphs": "Technical: <Paragraphs> count updated on save. Forensic relevance: confirms structural size of the document.\nForensic notes: When populated, compare against other fields to spot inconsistencies or automation artifacts.",
    "Lines": "Technical: <Lines> line count updated on save. Forensic relevance: low, but inconsistencies can indicate stale stats.\nForensic notes: When populated, compare against other fields to spot inconsistencies or automation artifacts.",
    "Characters": "Technical: <Characters> count excluding spaces. Forensic relevance: low, complements characters-with-spaces.\nForensic notes: When populated, compare against other fields to spot inconsistencies or automation artifacts.",
    "Heading Pairs": "Technical: <HeadingPairs> vector of section categories and counts. Forensic relevance: can reveal outline structure.\nForensic notes: This internal vector often pairs category names (Heading, Table, etc.) with counts. It can hint at document structure even when the body content is scrubbed.",
    "Titles of Parts": "Technical: <TitlesOfParts> list of section or heading titles. Forensic relevance: can expose outline names.\nForensic notes: Often contains top-level heading text. It can expose section titles that no longer appear in visible text.",
    "Track Changes": "Technical: <w:ins>/<w:del> tags in word/document.xml with author/date/id. Forensic relevance: shows who changed what and when.\nForensic notes: Insertions and deletions carry author and timestamp attributes; these are among the most probative artifacts in legal discovery. If changes are accepted, the metadata may disappear, which is why pre-scrub analysis matters.",
    "Visible Review Comments": "Technical: word/comments.xml comment records with author, initials, date, and text. Forensic relevance: exposes review discussions.\nForensic notes: Comments preserve author names, initials, timestamps, and the comment text itself. Even short comments can reveal intent or internal review discussions.",
    "Hidden/Resolved Review Comments": "Technical: retained or resolved comment threads still stored in XML. Forensic relevance: can reveal intent or internal notes.\nForensic notes: Resolved comments can remain in XML even when hidden in Word’s UI. These are frequently overlooked and can contain sensitive instructions or redline guidance.",
    "RSIDs": "Technical: revision session IDs (w:rsid*) in document.xml and w:rsids in settings.xml. Forensic relevance: links documents to common editing lineage.\nForensic notes: RSIDs are revision session identifiers stored in settings.xml and throughout document.xml. Shared RSIDs across documents can prove a common lineage or shared editing session.",
    "Document GUID": "Technical: Word document identity GUID (e.g., w:docId/w15:docId). Forensic relevance: can correlate related documents derived from the same source.\nForensic notes: The document GUID can persist across Save As and copies, acting as a fingerprint for document lineage.",
    "Spell/Grammar State": "Technical: w:proofState in settings.xml indicating proofing status. Forensic relevance: low, but shows if proofreading flags were cleared.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "Document Variables": "Technical: w:docVars name/value pairs set by macros or add-ins. Forensic relevance: often hides IDs or workflow flags.\nForensic notes: Accessible via Word’s automation APIs (ActiveDocument.Variables). Add-ins and macros use them to store hidden IDs, flags, or workflow state.",
    "Attached Template Path": "Technical: w:attachedTemplate path in settings.xml. Forensic relevance: can expose user names, network shares, or custom templates.\nForensic notes: Frequently includes full local or UNC paths such as C:\\Users\\Name\\... or \\\\Server\\Share. Those paths can disclose usernames, departments, or network structure.",
    "Document Protection": "Technical: w:documentProtection in settings.xml describing edit restrictions and password hash metadata. Forensic relevance: explains locked editing modes.\nForensic notes: Indicates edit restrictions (readOnly, comments-only, form filling, trackedChanges lock) and can include password hash metadata.",
    "Mail Merge Data": "Technical: w:mailMerge references to data sources (r:id in settings.xml). Forensic relevance: can expose links to external data files.\nForensic notes: Mail merge references are stored via relationship IDs that can point to external data sources. Those sources can reveal file paths or server locations in the .rels files.",
    "Data Bindings": "Technical: content-control bindings to custom XML parts. Forensic relevance: shows hidden data sources and structured fields.\nForensic notes: Content controls can bind to custom XML data parts. This reveals structured metadata and is a common place for hidden IDs or labels.",
    "Document Versions": "Technical: /word/versions parts, if present. Forensic relevance: indicates stored version history within the package.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "Ink Annotations": "Technical: ink annotation parts and references. Forensic relevance: can reveal handwritten notes or revisions.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "Hidden Text": "Technical: text runs marked hidden (e.g., w:vanish). Forensic relevance: content is present but not visible in normal view.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "Invisible Objects": "Technical: shapes/objects flagged hidden or zero-size. Forensic relevance: can conceal embedded content.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "Headers & Footers": "Technical: header/footer parts. Forensic relevance: can expose letterhead, addresses, IDs, or watermark text.\nForensic notes: Letterhead, file paths, clause IDs, and watermarks often live here. Headers/footers may persist even after body content changes.",
    "Watermarks": "Technical: watermark shapes in headers or document background. Forensic relevance: indicates document status or origin branding.\nForensic notes: These values live in document or settings XML and are often invisible in Word’s UI. They can preserve collaboration history even after surface-level scrubbing.",
    "OLE Objects": "Technical: embedded/linked OLE objects with ProgID/CLSID and rels targets. Forensic relevance: can expose original filenames or external paths.\nForensic notes: OLE objects include ProgID/CLSID and can be embedded or linked. Linked objects often expose original file paths; embedded objects may contain full files with their own metadata.",
    "Embedded Files": "Technical: /word/embeddings parts containing full files. Forensic relevance: embedded files carry their own metadata and content.\nForensic notes: Files under /word/embeddings can be Office docs, PDFs, or arbitrary binaries. Each embedded file should be extracted and analyzed separately.",
    "Audio/Video Media": "Technical: audio/video files stored in /word/media. Forensic relevance: media metadata can reveal device, time, or creator.\nForensic notes: Embedded parts are separate files inside the DOCX package and should be analyzed independently. They often carry their own metadata and can survive a superficial scrub.",
    "VBA Macros": "Technical: vbaProject.bin macro storage. Forensic relevance: potential malicious code and signed publisher info.\nForensic notes: Presence of vbaProject.bin is a security signal. In a .docx it is unusual and may indicate injection; in .docm it indicates active macro code.",
    "Digital Signatures": "Technical: package signature parts in /_xmlsignatures. Forensic relevance: indicates the document was signed for integrity.\nForensic notes: Package signatures prove integrity at signing time. If the document is altered after signing, the signature becomes invalid.",
    "Digital Signature Details": "Technical: signer subject, issuer, serial, and signing time from signature XML. Forensic relevance: attribution and timing.\nForensic notes: Signer subject/issuer, serial, and signing time are extracted from _xmlsignatures. This can identify who attested to the document and when.",
    "Printer Settings": "Technical: /word/printerSettings parts presence. Forensic relevance: can hint at printer device or environment.\nForensic notes: Stored in /word/printerSettings as .bin parts. They can contain device names or configuration hints about the originating environment.",
    "Printer Settings Details": "Technical: printer settings parts with sizes/paths. Forensic relevance: environment clues when present.\nForensic notes: Embedded parts are separate files inside the DOCX package and should be analyzed independently. They often carry their own metadata and can survive a superficial scrub.",
    "Embedded Fonts": "Technical: /word/fonts embedded (obfuscated) fonts. Forensic relevance: low, but can fingerprint source.\nForensic notes: Embedded fonts are stored as obfuscated font files. They rarely matter legally, but can see if a document was prepared for distribution or to preserve layout.",
    "Thumbnail Image": "Technical: /docProps/thumbnail.* preview image of first page. Forensic relevance: can reveal content even if text is removed.\nForensic notes: The thumbnail is a snapshot (often of the first page). It can leak content even when the body is scrubbed and may include EXIF metadata.",
    "Hyperlink URLs": "Technical: hyperlinks extracted from document.xml and rels. Forensic relevance: exposes external targets and file paths.\nForensic notes: Extracted from document XML and relationship files. Can include file://, UNC paths, and web URLs that reveal systems or sources.",
    "Alt Text on Images": "Technical: image descriptions in drawing properties (docPr title/descr). Forensic relevance: can carry sensitive labels.\nForensic notes: Alt text is often entered manually and can include internal filenames, figure captions, or sensitive descriptions.",
    "Glossary/AutoText": "Technical: /word/glossary parts (building blocks). Forensic relevance: reusable text can reveal template content.\nForensic notes: Building blocks are reusable boilerplate that can reveal the originating template or organization standards.",
    "Fast Save Data": "Technical: legacy fast-save related settings in settings.xml (e.g., savePreviewPicture). Forensic relevance: DOCX does not keep old text chunks, so this is usually minimal.\nForensic notes: DOCX does not use legacy fast-save deltas, so this field is usually minimal. Its presence mainly reflects settings, not hidden text.",
    "Package Encryption": "Technical: EncryptionInfo/EncryptedPackage presence. Forensic relevance: indicates password protection and limits metadata visibility.\nForensic notes: When encryption is present, most internal XML parts are not readable without a password. This is a strong indicator of protected content.",
    "Custom Properties & Custom XML": "Technical: docProps/custom.xml properties and /customXml data parts. Forensic relevance: often contains case IDs, labels, or workflow data not visible in the document.\nForensic notes: Custom properties (docProps/custom.xml) and custom XML parts can hold case numbers, document IDs, MIP labels, or DMS fields. These are common sources of hidden identifiers because they are not visible in the document body.",
    "Custom Style Names": "Technical: custom styles in word/styles.xml. Forensic relevance: can reveal template lineage or organization conventions.\nForensic notes: Advanced hardening targets artifacts created by add-ins, templates, or external content. These fields frequently carry identifiers that do not appear in the visible text.",
    "Chart Labels": "Technical: labels and titles stored in chart parts. Forensic relevance: may disclose names, amounts, or hidden series titles.\nForensic notes: Advanced hardening targets artifacts created by add-ins, templates, or external content. These fields frequently carry identifiers that do not appear in the visible text.",
    "Form Field Defaults": "Technical: default values for form fields/content controls. Forensic relevance: can expose intended answers or template placeholders.\nForensic notes: Advanced hardening targets artifacts created by add-ins, templates, or external content. These fields frequently carry identifiers that do not appear in the visible text.",
    "Language Settings": "Technical: language/locale settings at paragraph or run level. Forensic relevance: can indicate author locale or mixed-language edits.\nForensic notes: Advanced hardening targets artifacts created by add-ins, templates, or external content. These fields frequently carry identifiers that do not appear in the visible text.",
    "ActiveX Controls": "Technical: embedded ActiveX controls in the package. Forensic relevance: potential security risk and automation artifacts.\nForensic notes: Advanced hardening targets artifacts created by add-ins, templates, or external content. These fields frequently carry identifiers that do not appear in the visible text.",
    "External Link Paths": "Technical: TargetMode=\"External\" relationships in rels. Forensic relevance: exposes file paths, UNC shares, or URLs.\nForensic notes: Relationship targets marked TargetMode=External can expose network shares, file paths, or URLs even if visible links were removed.",
    "Image EXIF Data": "Technical: EXIF/XMP metadata within embedded images. Forensic relevance: can reveal device, timestamps, or GPS.\nForensic notes: EXIF/XMP can include camera model, software, timestamps, and GPS coordinates. Word typically preserves this metadata when embedding images.",
    "Nuclear Option: Custom XML Parts": "Technical: removes /customXml parts and related properties. Forensic relevance: eliminates hidden structured data.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Nuclear Option: Non-Standard XML Namespaces": "Technical: removes elements/attributes from unknown namespaces. Forensic relevance: strips vendor/add-in data that can carry identifiers.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Nuclear Option: Microsoft Extension Namespaces": "Technical: removes Microsoft extension namespaces (e.g., word/2010/2012). Forensic relevance: aggressive removal of extended features that may carry metadata.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Nuclear Option: Unknown Relationships": "Technical: removes relationships not on the allowlist. Forensic relevance: eliminates unknown links or add-in artifacts.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Nuclear Option: Orphaned Package Parts": "Technical: deletes unreferenced parts left in the ZIP. Forensic relevance: removes hidden payloads not linked by the document.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Nuclear Option: Alternate Content Blocks": "Technical: removes mc:AlternateContent blocks and fallbacks. Forensic relevance: strips compatibility payloads that may hide content.\nForensic notes: Nuclear options are aggressive removals of entire parts or namespaces. They are designed for maximum privacy but can degrade fidelity or compatibility in advanced Word features.",
    "Non-Standard Fields": "Technical: unexpected XML elements or attributes in standard parts. Forensic relevance: can hide identifiers or vendor metadata.\nForensic notes: When populated, compare against other fields to spot inconsistencies or automation artifacts.",
}

def _describe_metadata_field(group_name: str, field_name: str) -> str:
    if field_name in _FIELD_GLOSSARY:
        return _FIELD_GLOSSARY[field_name]
    source = _GROUP_SOURCE_MAP.get(group_name, "the DOCX package")
    return (
        f"{field_name} — extracted from {source}. "
        "This is the raw value found in the document package and can reveal toolchains, "
        "hidden identifiers, workflow artifacts, or embedded references even when not visible in the document. "
        "Marcut shows pre/post values so you can confirm what changed during scrubbing."
    )


def _describe_file_info_field(key: str, label: str) -> str:
    return _FILE_INFO_GLOSSARY.get(
        key,
        f"{label} — a macOS file-system or Spotlight metadata field. It is recorded outside the DOCX package "
        "and reflects how the file is stored or indexed on this machine."
    )


def _get_file_info_value(info: Dict[str, Any], key: str) -> Any:
    if not info:
        return None
    return info.get(key)


def _info_icon_html(description: str) -> str:
    return f'<button type="button" class="info-icon" data-tooltip="{escape_html(description)}">ⓘ</button>'


def _render_file_info_comparison_block(
    input_info: Dict[str, Any],
    output_info: Dict[str, Any],
    is_metadata_only: bool = False
) -> str:
    """Render file info in two-column comparison format like other metadata groups."""
    if not input_info and not output_info:
        return ""

    ordered_fields = [
        ("sha256", "SHA-256"),
        ("file_name", "File Name"),
        ("file_extension", "Extension"),
        ("mime_type", "MIME Type"),
        ("size_bytes", "Size (Bytes)"),
    ]

    rows: List[str] = []
    for key, label in ordered_fields:
        input_val = _get_file_info_value(input_info, key) if input_info else None
        output_val = _get_file_info_value(output_info, key) if output_info else None

        if input_val in (None, "", [], {}) and output_val in (None, "", [], {}):
            continue

        missing_label = '<span class="empty">Nothing reported by macOS</span>'
        input_html = _format_file_info_value(input_val) if input_val not in (None, "", [], {}) else missing_label
        output_html = _format_file_info_value(output_val) if output_val not in (None, "", [], {}) else missing_label

        # Determine status based on value comparison
        if input_val == output_val:
            status = "unchanged"
        else:
            status = "observed"

        value_columns = f'<div class="field-value">{input_html}</div>'
        if not is_metadata_only:
            value_columns += f'<div class="field-value after-value">{output_html}</div>'

        info_icon = _info_icon_html(_describe_file_info_field(key, label))
        rows.append(f'''
            <div class="field-row {status}">
                <div class="field-name">{escape_html(label)}{info_icon}</div>
                {value_columns}
                <span class="status-badge {status}">{status}</span>
            </div>
        ''')

    if not rows:
        return ""

    label_row = ""
    if not is_metadata_only:
        label_row = '''
            <div class="file-info-labels">
                <div></div>
                <div class="file-info-label">Pre-Metadata Scrub</div>
                <div class="file-info-label">Post-Metadata Scrub</div>
                <div></div>
            </div>
        '''
    else:
        label_row = '''
            <div class="file-info-labels">
                <div></div>
                <div class="file-info-label">Pre-Metadata Scrub</div>
                <div></div>
            </div>
        '''
    rows_html = label_row + "\n".join(rows)
    return f'''
    <div class="group">
        <div class="group-header">
            <h2>File Info (macOS file-system data, not inside the DOCX)</h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
            {rows_html}
        </div>
    </div>
'''










def generate_html_report(
    json_data: Dict[str, Any],
    json_path: str,
    output_path: str,
    report_dir: Optional[str] = None,
) -> str:
    """
    Generate an HTML report from the JSON scrub report data.
    
    Args:
        json_data: The parsed JSON scrub report
        json_path: Path to the JSON file (for linking)
        output_path: Path to write the HTML file
        report_dir: Directory containing binary exports (for image previews)
    
    Returns:
        The path to the generated HTML file
    """
    summary = json_data.get('summary', {})
    groups = json_data.get('groups', {})
    file_info = json_data.get('file_info', {}) or {}
    input_file_info = file_info.get("input") or {}
    output_file_info = file_info.get("output") or {}
    binary_exports = json_data.get('binary_exports', [])
    large_exports = json_data.get('large_exports', [])
    deep_explorer = json_data.get('deep_explorer', {}) or {}
    forensic = json_data.get('forensic_findings', {}) or {}
    forensic_findings = forensic.get('findings', []) or []
    forensic_count = forensic.get('count', len(forensic_findings))
    forensic_error = forensic.get('error')
    forensic_flag_display = "Failed" if forensic_error else str(forensic_count)
    preset_key = (summary.get("metadata_preset") or "custom").strip().lower()
    preset_map = {
        "maximum": "Maximum Privacy",
        "balanced": "Balanced",
        "none": "None",
        "custom": "Custom",
    }
    preset_label = preset_map.get(preset_key, preset_key.title())
    report_type = summary.get('report_type', 'scrub')
    is_metadata_only = report_type == 'metadata_only'
    observed_total = summary.get('total_observed')
    if observed_total is None:
        observed_total = sum(len(fields or []) for fields in groups.values())
    warnings = json_data.get("warnings") or []
    warnings_html = ""
    if warnings:
        warning_rows = []
        for w in warnings[:50]:
            detail = w.get("details")
            detail_html = f'<div class="notice-detail">{escape_html(str(detail))}</div>' if detail else ""
            warning_rows.append(
                f"<li><strong>{escape_html(str(w.get('code', 'WARNING')))}</strong> "
                f"{escape_html(str(w.get('message', '')))}{detail_html}</li>"
            )
        warnings_html = f'''
        <div class="notice warning">
            <h2>Warnings</h2>
            <ul class="notice-list">
                {''.join(warning_rows)}
            </ul>
        </div>
'''

    def _sanitize_export_path(raw_path: Any) -> str:
        path_text = str(raw_path or "").strip().replace("\\", "/")
        if not path_text:
            return ""
        normalized = os.path.normpath(path_text).replace("\\", "/")
        if normalized in ("", "."):
            return ""
        if os.path.isabs(normalized):
            return os.path.basename(normalized)
        if normalized == ".." or normalized.startswith("../"):
            return os.path.basename(normalized)
        return normalized.lstrip("./")

    if is_metadata_only and deep_explorer:
        pre_only = deep_explorer.get("pre")
        deep_explorer = {"pre": pre_only} if pre_only else {}

    size_bytes = summary.get("size_bytes")
    try:
        size_display = format_file_size(int(size_bytes))
    except Exception:
        size_display = "unknown size"
    
    # Build HTML
    html_parts = [f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Metadata {"Snapshot" if is_metadata_only else "Scrub Report"} - {escape_html(summary.get('file_name', 'Document'))}</title>
    <style>{_get_css()}</style>
</head>
<body class="{ 'metadata-only' if is_metadata_only else ''}">
    <div class="search-overlay" id="report-search-overlay">
        <input type="search" id="report-search-input" placeholder="Find in report…" />
        <button type="button" id="report-search-next">Find</button>
        <button type="button" class="close" id="report-search-close">×</button>
    </div>
    <div class="report-hero">
        <div class="report-summary">
            <div class="summary-title">Marcut Forensic Metadata {'Snapshot' if is_metadata_only else 'Scrub Report'}: {escape_html(summary.get('file_name', 'Document'))}</div>
            <div class="summary-meta">Report date: {escape_html(summary.get('scrub_datetime', '')[:10])} • File size: {escape_html(size_display)} • {'Read-only metadata inventory' if is_metadata_only else 'Pre/Post scrub comparison'} • <a href="https://www.linkedin.com/in/marcmandel/" target="_blank" rel="noopener noreferrer">Authored by Marc Mandel</a></div>
        </div>
''']

    # Forensic analysis block
    if forensic_error:
        html_parts.append(f'''
    <div class="forensic-card">
        <h2>⚠️ Forensic Analysis: Unable to evaluate</h2>
        <div class="forensic-subtitle">Marcut App Scrub preset: {escape_html(preset_label)}</div>
        <div class="forensic-items">
            <div class="forensic-item medium">
                <strong>Forensic analysis error</strong>
                <div>{escape_html(str(forensic_error))}</div>
            </div>
        </div>
        {warnings_html}
    </div>
    </div>
''')
    elif forensic_findings:
        html_parts.append(f'''
    <div class="forensic-card">
        <h2>🚩 Forensic Analysis: {forensic_count} finding{"s" if forensic_count != 1 else ""}</h2>
        <div class="forensic-subtitle">Based on Pre-scrub metadata only • Naive timestamps (i.e. lacking time zone info) are assumed to be in your local time</div>
        <div class="forensic-subtitle">Marcut App Scrub preset: {escape_html(preset_label)}</div>
        <div class="forensic-items">
''')
        for finding in forensic_findings:
            sev = finding.get('severity', 'medium')
            title = finding.get('title', 'Finding')
            detail = finding.get('detail', '')
            evidence = finding.get('evidence') or []
            evidence_html = ''.join(f'<div class="forensic-evidence">• {escape_html(str(ev))}</div>' for ev in evidence)
            html_parts.append(f'''
            <div class="forensic-item {escape_html(sev)}">
                <strong>{escape_html(title)}</strong>
                <div>{escape_html(detail)}</div>
                {evidence_html}
            </div>
''')
        html_parts.append(f'        </div>\n{warnings_html}    </div>\n    </div>\n')
    else:
        html_parts.append(f'''    <div class="forensic-card">
        <h2>✅ Forensic Analysis: No anomalies detected</h2>
        <div class="forensic-subtitle">Based on Pre-scrub metadata only • Naive timestamps (i.e. lacking time zone info) are assumed to be in your local time</div>
        <div class="forensic-subtitle">Marcut App Scrub preset: {escape_html(preset_label)}</div>
        {warnings_html}
    </div>
    </div>
''')

    if is_metadata_only:
        html_parts.append(f'''
    <div class="summary-cards">
        <div class="summary-card cleaned">
            <div class="label">Observed Fields</div>
            <div class="value">{observed_total}</div>
        </div>
        <div class="summary-card preserved">
            <div class="label">Extracted Binaries</div>
            <div class="value">{len(binary_exports) + len(large_exports)}</div>
        </div>
        <div class="summary-card unchanged">
            <div class="label">Forensic Flags</div>
            <div class="value">{forensic_flag_display}</div>
        </div>
    </div>
''')
    else:
        html_parts.append(f'''
    <div class="summary-cards">
        <div class="summary-card cleaned">
            <div class="label">Cleaned</div>
            <div class="value">{summary.get('total_cleaned', 0)}</div>
        </div>
        <div class="summary-card preserved">
            <div class="label">Preserved</div>
            <div class="value">{summary.get('total_preserved', 0)}</div>
        </div>
        <div class="summary-card unchanged">
            <div class="label">Unchanged</div>
            <div class="value">{summary.get('total_unchanged', 0)}</div>
        </div>
    </div>
''')

    file_info_html = _render_file_info_comparison_block(
        input_file_info,
        output_file_info,
        is_metadata_only=is_metadata_only,
    )
    if file_info_html:
        html_parts.append(file_info_html)

    if deep_explorer:
        deep_payload = json.dumps(deep_explorer).replace("</", "<\\/")
        pre_section_title = "Document Package" if is_metadata_only else "Pre‑Scrub Package"
        post_section_html = ""
        if deep_explorer.get("post") and not is_metadata_only:
            post_section_html = '''
                    <div class="deep-explorer-section" data-scope="post">
                        <h3>Post‑Scrub Package</h3>
                        <div class="deep-explorer-links" id="deep-explorer-post-links"></div>
                        <div class="deep-explorer-tree" id="deep-explorer-post-tree"></div>
                    </div>'''
        html_parts.append(f'''
    <div class="group">
        <div class="group-header">
            <h2>🧭 Forensic Deep Explorer</h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
            <div class="deep-explorer">
                <div class="deep-explorer-controls">
                    <input type="search" id="deep-explorer-search" placeholder="Search selected package text…" />
                    <div class="deep-explorer-count" id="deep-explorer-count"></div>
                </div>
                <div class="deep-explorer-grid">
                    <div class="deep-explorer-section active" data-scope="pre">
                        <h3>{pre_section_title}</h3>
                        <div class="deep-explorer-links" id="deep-explorer-pre-links"></div>
                        <div class="deep-explorer-tree" id="deep-explorer-pre-tree"></div>
                    </div>
                    {post_section_html}
                </div>
                <div class="deep-explorer-results" id="deep-explorer-results"></div>
            </div>
            <script id="deep-explorer-data" type="application/json">{deep_payload}</script>
        </div>
    </div>
''')

    # Add groups
    for group_name, fields in groups.items():
        if not fields:
            continue
        
        html_parts.append(f'''
    <div class="group">
        <div class="group-header">
            <h2>{escape_html(group_name)}</h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
''')
        
        for field in fields:
            field_name = field.get('field', '')
            before_val = field.get('before', '')
            after_val = field.get('after', '')
            status = field.get('status', 'unchanged')
            
            before_html, _ = _format_value(before_val)
            after_html, _ = _format_value(after_val)
            value_columns = f'<div class="field-value">{before_html}</div>'
            after_class = "field-value after-value"
            if not is_metadata_only:
                value_columns += f'<div class="{after_class}">{after_html}</div>'
            
            html_parts.append(f'''
            <div class="field-row {status}">
                <div class="field-name">{escape_html(field_name)}{_info_icon_html(_describe_metadata_field(group_name, field_name))}</div>
                {value_columns}
                <span class="status-badge {status}">{status}</span>
            </div>
''')
        
        html_parts.append('        </div>\n    </div>\n')
    
    # Add binary exports section (combined)
    if binary_exports or large_exports:
        html_parts.append('''
    <div class="group">
        <div class="group-header">
            <h2>📦 Extracted Files & Large Embedded Parts</h2>
            <span class="toggle">▼</span>
        </div>
        <div class="group-content">
            <div class="binary-grid">
''')

        if binary_exports:
            for binary in binary_exports:
                name = binary.get('name', '') if isinstance(binary, dict) else str(binary)
                path = binary.get('path', name) if isinstance(binary, dict) else name
                safe_path = _sanitize_export_path(path)
                file_type = binary.get('type', 'other') if isinstance(binary, dict) else 'other'
                size = binary.get('size', 0) if isinstance(binary, dict) else 0
                
                icon = get_binary_icon(file_type)
                size_str = format_file_size(size) if size else ''
                
                is_image = file_type == 'image' or safe_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))
                
                if is_image and report_dir:
                    full_path = os.path.normpath(os.path.join(report_dir, safe_path))
                    if os.path.exists(full_path):
                        try:
                            with open(full_path, 'rb') as f:
                                img_data = base64.b64encode(f.read()).decode('utf-8')
                            mime = get_mime_type(safe_path)
                            preview_html = f'<img src="data:{mime};base64,{img_data}" alt="{escape_html(name)}">'
                        except Exception:
                            preview_html = icon
                    else:
                        preview_html = icon
                else:
                    preview_html = icon

                link_path = safe_path or os.path.basename(str(name or ""))
                link_href = url_quote(link_path, safe="/")
                html_parts.append(f'''
                <a href="{escape_html(link_href)}" target="_blank" rel="noopener noreferrer" class="binary-card" data-file-path="{escape_html(link_path)}">
                    <div class="binary-preview">{preview_html}</div>
                    <div class="binary-info">
                        <div class="binary-tag">Extracted</div>
                        <div class="binary-name">{escape_html(os.path.basename(name))}</div>
                        <div class="binary-size">{size_str}</div>
                    </div>
                </a>
''')

        if large_exports:
            for binary in large_exports:
                name = binary.get('name', '') if isinstance(binary, dict) else str(binary)
                path = binary.get('path', name) if isinstance(binary, dict) else name
                safe_path = _sanitize_export_path(path)
                file_type = binary.get('type', 'other') if isinstance(binary, dict) else 'other'
                size = binary.get('size', 0) if isinstance(binary, dict) else 0

                icon = get_binary_icon(file_type)
                size_str = format_file_size(size) if size else ''
                preview_html = icon

                link_path = safe_path or os.path.basename(str(name or ""))
                link_href = url_quote(link_path, safe="/")

                html_parts.append(f'''
                <a href="{escape_html(link_href)}" target="_blank" rel="noopener noreferrer" class="binary-card" data-file-path="{escape_html(link_path)}">
                    <div class="binary-preview">{preview_html}</div>
                    <div class="binary-info">
                        <div class="binary-tag">Large Embedded</div>
                        <div class="binary-name">{escape_html(os.path.basename(name))}</div>
                        <div class="binary-size">{size_str}</div>
                    </div>
                </a>
''')
        html_parts.append('            </div>\n        </div>\n    </div>\n')
    
    # Add JSON link and footer
    json_basename = os.path.basename(json_path)
    html_parts.append(f'''
    <a href="{escape_html(json_basename)}" class="json-link" target="_blank" rel="noopener noreferrer">
        📄 View Raw JSON Data
    </a>
    
    <div class="footer">
        Generated by Marcut Forensic Metadata Scrubber (c) 2026 <a href="https://www.linkedin.com/in/marcmandel/" target="_blank" rel="noopener noreferrer">Marc Mandel</a>
    </div>
    
    <script>{_get_js()}</script>
</body>
</html>
''')
    
    # Write HTML file
    html_content = ''.join(html_parts)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return output_path


def generate_report_from_json_file(json_path: str) -> str:
    """
    Generate an HTML report from a JSON scrub report file.
    
    The HTML file will be created alongside the JSON file with .html extension.
    
    Args:
        json_path: Path to the JSON scrub report file
        
    Returns:
        Path to the generated HTML file
    """
    html_path = os.path.splitext(json_path)[0] + '.html'
    report_dir = os.path.dirname(json_path)
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    return generate_html_report(json_data, json_path, html_path, report_dir)
