#!/usr/bin/env python3
"""Validate local markdown links used by docs and help resources."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def iter_markdown_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file() and path.suffix.lower() in {".md", ".markdown"}:
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.md")))
    return sorted(set(files))


def local_target_exists(markdown_file: Path, raw_target: str) -> bool:
    target = raw_target.strip()
    if not target or target.startswith("#"):
        return True
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    parsed = urlparse(target)
    if parsed.scheme in {"http", "https", "mailto"}:
        return True
    if parsed.scheme and parsed.scheme != "file":
        return True

    path_text = unquote(parsed.path if parsed.scheme == "file" else target.split("#", 1)[0])
    if not path_text:
        return True
    if path_text.startswith("//"):
        return True

    candidate = Path(path_text)
    if not candidate.is_absolute():
        candidate = (markdown_file.parent / candidate).resolve()
    return candidate.exists()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["README.md", "docs", "assets"])
    args = parser.parse_args()

    root = Path.cwd()
    markdown_files = iter_markdown_files([root / path for path in args.paths])
    failures: list[str] = []
    for markdown_file in markdown_files:
        text = markdown_file.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if not local_target_exists(markdown_file, target):
                rel_file = os.path.relpath(markdown_file, root)
                failures.append(f"{rel_file}: missing link target {target}")

    if failures:
        print("Markdown link check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print(f"Markdown link check passed for {len(markdown_files)} files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
