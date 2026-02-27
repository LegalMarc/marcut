#!/usr/bin/env python3
"""
Render help markdown in assets/ into static HTML for the app bundle.
Keeps markdown as source of truth and emits styled HTML with table support.
"""
from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path
from typing import List, Tuple


CSS = r"""
:root {
  color-scheme: light dark;
}
body {
  font-family: -apple-system, "SF Pro Text", "SF Pro Display", system-ui, sans-serif;
  line-height: 1.55;
  margin: 0;
  padding: 20px 22px 28px 22px;
  background: #ffffff;
  color: #111111;
}
h1, h2, h3, h4, h5, h6 {
  margin: 18px 0 8px 0;
  line-height: 1.25;
}
h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
p {
  margin: 0 0 12px 0;
}
ul, ol {
  margin: 0 0 12px 22px;
  padding: 0;
}
li { margin: 4px 0; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.95em;
  background: rgba(0,0,0,0.06);
  padding: 1px 4px;
  border-radius: 4px;
}
pre {
  background: rgba(0,0,0,0.06);
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 0 0 14px 0;
}
pre code {
  background: transparent;
  padding: 0;
}
a {
  color: #0a66c2;
  text-decoration: underline;
}
table {
  border-collapse: collapse;
  margin: 8px 0 16px 0;
  width: 100%;
}
th, td {
  border: 1px solid rgba(0,0,0,0.12);
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
thead th {
  background: rgba(0,0,0,0.05);
}
blockquote {
  border-left: 3px solid rgba(0,0,0,0.18);
  padding: 2px 10px;
  margin: 0 0 12px 0;
  color: #444;
}
hr {
  border: none;
  border-top: 1px solid rgba(0,0,0,0.12);
  margin: 16px 0;
}
@media (prefers-color-scheme: dark) {
  body {
    background: #0f1115;
    color: #e6e6e6;
  }
  code, pre { background: rgba(255,255,255,0.08); }
  a { color: #7db6ff; }
  th, td { border-color: rgba(255,255,255,0.2); }
  thead th { background: rgba(255,255,255,0.08); }
  blockquote { border-left-color: rgba(255,255,255,0.25); color: #cfcfcf; }
  hr { border-top-color: rgba(255,255,255,0.2); }
}
"""


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text


def inline_format(text: str) -> str:
    text = html.escape(text)

    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", text)

    # Italic (simple)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)

    # Images
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2" />', text)

    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    return text


def parse_table(lines: List[str], start: int) -> Tuple[str, int]:
    header = lines[start]
    separator = lines[start + 1]
    if "|" not in header or not re.search(r"-{3,}", separator):
        return "", start

    def split_row(row: str) -> List[str]:
        row = row.strip().strip("|")
        return [cell.strip() for cell in row.split("|")]

    head_cells = split_row(header)
    body_rows = []
    i = start + 2
    while i < len(lines) and "|" in lines[i] and lines[i].strip():
        body_rows.append(split_row(lines[i]))
        i += 1

    thead = "<thead><tr>" + "".join(f"<th>{inline_format(c)}</th>" for c in head_cells) + "</tr></thead>"
    tbody_rows = []
    for row in body_rows:
        cells = "".join(f"<td>{inline_format(c)}</td>" for c in row)
        tbody_rows.append(f"<tr>{cells}</tr>")
    tbody = "<tbody>" + "".join(tbody_rows) + "</tbody>"
    return f"<table>{thead}{tbody}</table>", i


def markdown_to_html_fallback(md_text: str) -> str:
    lines = md_text.splitlines()
    html_out: List[str] = []
    in_code = False
    code_lines: List[str] = []
    paragraph: List[str] = []
    list_stack: List[dict] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            html_out.append(f"<p>{inline_format(' '.join(paragraph))}</p>")
            paragraph = []

    def close_current_li() -> None:
        if list_stack and list_stack[-1]["li_open"]:
            html_out.append("</li>")
            list_stack[-1]["li_open"] = False

    def close_lists_to_indent(target_indent: int) -> None:
        while list_stack and list_stack[-1]["indent"] > target_indent:
            close_current_li()
            html_out.append(f"</{list_stack[-1]['type']}>")
            list_stack.pop()

    def close_all_lists() -> None:
        while list_stack:
            close_current_li()
            html_out.append(f"</{list_stack[-1]['type']}>")
            list_stack.pop()

    def ensure_list(list_type: str, indent: int) -> None:
        if not list_stack:
            html_out.append(f"<{list_type}>")
            list_stack.append({"type": list_type, "indent": indent, "li_open": False})
            return

        top = list_stack[-1]
        if indent > top["indent"]:
            html_out.append(f"<{list_type}>")
            list_stack.append({"type": list_type, "indent": indent, "li_open": False})
        elif indent == top["indent"] and top["type"] != list_type:
            close_current_li()
            html_out.append(f"</{top['type']}>")
            list_stack.pop()
            html_out.append(f"<{list_type}>")
            list_stack.append({"type": list_type, "indent": indent, "li_open": False})

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            if in_code:
                html_out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                flush_paragraph()
                close_all_lists()
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        # Table
        if i + 1 < len(lines) and "|" in line and re.search(r"-{3,}", lines[i + 1]):
            flush_paragraph()
            close_all_lists()
            table_html, next_i = parse_table(lines, i)
            if table_html:
                html_out.append(table_html)
                i = next_i
                continue

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        if line.startswith("#"):
            flush_paragraph()
            close_all_lists()
            match = re.match(r"^(#{1,6})\s+(.*)$", line)
            if match:
                level = len(match.group(1))
                title = match.group(2).strip()
                anchor = slugify(title)
                html_out.append(f"<h{level} id=\"{anchor}\">{inline_format(title)}</h{level}>")
            i += 1
            continue

        if line.startswith(">"):
            flush_paragraph()
            close_all_lists()
            quote = line.lstrip("> ").strip()
            html_out.append(f"<blockquote>{inline_format(quote)}</blockquote>")
            i += 1
            continue

        list_match = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if list_match:
            flush_paragraph()
            indent = len(list_match.group(1).replace("\t", "    "))
            marker = list_match.group(2)
            content = list_match.group(3).strip()
            list_type = "ol" if marker.endswith(".") and marker[:-1].isdigit() else "ul"

            close_lists_to_indent(indent)
            ensure_list(list_type, indent)

            if list_stack and list_stack[-1]["indent"] == indent:
                close_current_li()

            html_out.append(f"<li>{inline_format(content)}")
            list_stack[-1]["li_open"] = True
            i += 1
            continue

        if list_stack and list_stack[-1]["li_open"] and line.startswith(" "):
            html_out.append("<br>" + inline_format(line.strip()))
            i += 1
            continue

        flush_paragraph()
        close_all_lists()
        paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    close_all_lists()
    return "\n".join(html_out)


def add_heading_ids(html_text: str) -> str:
    def repl(match: re.Match) -> str:
        level = match.group(1)
        inner = match.group(2)
        plain = re.sub(r"<[^>]+>", "", inner)
        anchor = slugify(plain)
        return f'<h{level} id="{anchor}">{inner}</h{level}>'

    return re.sub(r"<h([1-6])>(.*?)</h\1>", repl, html_text, flags=re.IGNORECASE | re.DOTALL)


def render_markdown(md_text: str) -> str:
    try:
        import markdown  # type: ignore

        html_body = markdown.markdown(
            md_text,
            extensions=["tables", "fenced_code"],
            output_format="html5",
        )
        html_body = add_heading_ids(html_body)
        return html_body
    except Exception:
        return markdown_to_html_fallback(md_text)


def wrap_html(body: str, title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


def render_file(src: Path, dst: Path) -> None:
    md_text = src.read_text(encoding="utf-8")
    title = src.stem.replace("-", " ").title()
    html_body = render_markdown(md_text)
    html_text = wrap_html(html_body, title)
    dst.write_text(html_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", default="assets")
    parser.add_argument("--output-dir", default="src/swift/MarcutApp/Sources/MarcutApp/Resources")
    args = parser.parse_args()

    assets_dir = Path(args.assets_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    mapping = {
        "help": assets_dir / "help.md",
        "forensics-guide": assets_dir / "forensics-guide.md",
    }

    for name, src in mapping.items():
        if not src.exists():
            raise SystemExit(f"Missing markdown source: {src}")
        dst_html = output_dir / f"{name}.html"
        render_file(src, dst_html)
        # Keep markdown sources in sync for fallback rendering.
        dst_md = output_dir / f"{name}.md"
        dst_md.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
