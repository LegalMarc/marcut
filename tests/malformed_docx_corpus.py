"""
Generator for a malformed-DOCX test corpus (issue #50 / B8).

Builds a small, valid DOCX in memory via python-docx, then applies zip/XML-level
corruption to produce a fixed set of broken variants:

  - truncated_zip: the archive is cut off partway through (corrupts the ZIP
    central directory).
  - bad_content_types: word/document.xml's declared content type in
    [Content_Types].xml is mislabeled, so the main document part can't be
    recognized.
  - mismatched_relationship_target: word/_rels/document.xml.rels points a
    relationship at a part that does not exist in the archive.
  - undeclared_xml_entity: word/document.xml references an XML entity that is
    never declared, breaking well-formedness.

Nothing here is written to the repo -- callers write the returned bytes to a
pytest tmp_path. CI's hygiene job (.github/workflows/ci.yml) forbids any
committed .docx, so this corpus must always be generated at test time.
"""

from __future__ import annotations

import io
import zipfile
from typing import Callable, Dict, Optional

from docx import Document

DEFAULT_TEXT = "Hello Marcut corpus. John Smith works at Example Corp in Springfield."


def build_valid_docx_bytes(text: str = DEFAULT_TEXT) -> bytes:
    """Build a small, valid DOCX entirely in memory (never touches disk)."""
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _rewrite_zip(data: bytes, transforms: Dict[str, Callable[[bytes], bytes]]) -> bytes:
    """Return a copy of the zip `data` with named members rewritten by `transforms`."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            content = src.read(item.filename)
            transform = transforms.get(item.filename)
            if transform is not None:
                content = transform(content)
            out.writestr(item, content)
    return out_buf.getvalue()


def _truncate_zip(data: bytes) -> bytes:
    return data[: len(data) // 2]


def _bad_content_types(data: bytes) -> bytes:
    def _wrong_type(content: bytes) -> bytes:
        text = content.decode("utf-8")
        text = text.replace(
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"',
            'ContentType="image/png"',
        )
        return text.encode("utf-8")

    return _rewrite_zip(data, {"[Content_Types].xml": _wrong_type})


def _mismatched_relationship_target(data: bytes) -> bytes:
    def _retarget(content: bytes) -> bytes:
        text = content.decode("utf-8")
        text = text.replace('Target="styles.xml"', 'Target="styles_MISSING.xml"')
        return text.encode("utf-8")

    return _rewrite_zip(data, {"word/_rels/document.xml.rels": _retarget})


def _undeclared_xml_entity(data: bytes) -> bytes:
    def _inject(content: bytes) -> bytes:
        text = content.decode("utf-8")
        # Every DOCX from build_valid_docx_bytes() contains this marker text.
        text = text.replace("Hello Marcut", "Hello &undeclaredentity; Marcut", 1)
        return text.encode("utf-8")

    return _rewrite_zip(data, {"word/document.xml": _inject})


# Name -> corruptor. Iteration order is insertion order (Python 3.7+), and callers
# that need a stable order sort the keys explicitly.
CORRUPTORS: Dict[str, Callable[[bytes], bytes]] = {
    "truncated_zip": _truncate_zip,
    "bad_content_types": _bad_content_types,
    "mismatched_relationship_target": _mismatched_relationship_target,
    "undeclared_xml_entity": _undeclared_xml_entity,
}


def generate_corpus(base_text: Optional[str] = None) -> Dict[str, bytes]:
    """Return {variant_name: corrupted_docx_bytes} for the full malformed corpus."""
    valid = build_valid_docx_bytes(base_text) if base_text else build_valid_docx_bytes()
    return {name: corruptor(valid) for name, corruptor in CORRUPTORS.items()}
