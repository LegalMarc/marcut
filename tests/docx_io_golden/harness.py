"""Golden-file characterization harness for `marcut.docx_io.DocxMap`
(issue #70 / docs/design/docx_io_package_split.md §3.2 item 1).

This is the "prerequisite gate for the entire docx_io.py package split"
called for by the design doc: it runs the current, unsplit `DocxMap`
end-to-end and snapshots everything the design doc's extraction slices
must not silently change.

## What it snapshots, per fixture

1. `(DocxMap.text, DocxMap.index)` as built by `_build()` at `load()` time
   -- i.e. before any scrub/harden/replace mutation touches the document.
   `index` entries are not JSON-serializable as-is (they hold live
   python-docx `Paragraph`/`Run` proxies), so `snapshot_index()` replaces
   each distinct paragraph/run element with a stable per-snapshot id and
   its canonicalized outer XML, then records the index as a list of
   `[paragraph_id, run_id, char_offset]` triples (or `["break", None,
   None]`). Two builds of the same fixture assign ids in the same order
   (traversal is deterministic), so this is diff-stable.
2. The full output `.docx` part listing after
   `scrub_metadata() -> harden_document() -> apply_replacements() ->
   save()`, with every XML part canonicalized (`lxml` C14N, not raw bytes
   -- avoids false diffs from ZIP member ordering, compression, or
   whitespace) and every binary part reduced to a `sha256` + byte length.
3. `DocxMap.warnings` after the full run.

## Non-determinism handled here (not in the fixtures)

`DocxMap.apply_replacements()` stamps every `w:ins`/`w:del` it writes with
`datetime.now(timezone.utc)` (`docx_io.py` `_insert_deletion_after`/
`_insert_insertion_after`). `_normalize_dynamic_attrs()` blanks every
`w:date` attribute in every part before canonicalization so the snapshot
is stable across runs. This is the *only* source of non-determinism in
the current codebase (grep for `datetime.now`/`utcnow`/`uuid`/`random` in
`docx_io.py` if that ever needs re-verifying) -- everything else in the
fixtures (author names, dates, ids) is a fixed literal.

## Running it

    PYTHONPATH=src/python python3 -m pytest tests/test_docx_io_golden.py -q

Every later `docx_io.py` extraction slice (issues #72-#76) must run this
exact command before and after its change and get the same "0 failed".
That is the whole point of this harness: it is the single artifact that
proves an extraction slice moved code without moving behavior.

## Updating the golden snapshots

The golden snapshots under `tests/docx_io_golden/golden/*.json` are
committed fixtures capturing CURRENT `DocxMap` behavior -- they are not
meant to change during an extraction slice (a diff there means the slice
broke parity, full stop). If a *future*, deliberate behavior change to
docx_io.py needs the golden re-baselined, regenerate with:

    MARCUT_GOLDEN_UPDATE=1 PYTHONPATH=src/python python3 -m pytest \\
        tests/test_docx_io_golden.py -q

then diff the regenerated JSON by hand before committing it -- this
should be a rare, deliberate act, never a reflex to make a failing test
pass.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

from lxml import etree

from marcut.docx_io import DocxMap, MetadataCleaningSettings

from . import fixtures as fx

GOLDEN_DIR = Path(__file__).parent / "golden"

# Every part whose bytes are valid standalone XML in a DOCX package. Parts
# outside this set (media, embedded objects, thumbnails, ...) are hashed
# instead of canonicalized.
_XML_SUFFIXES = (".xml", ".rels")


def _normalize_dynamic_attrs(root: etree._Element) -> None:
    """Blank every `w:date` attribute in-place. See module docstring:
    this is the one non-deterministic value `DocxMap` writes itself."""
    date_attr = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}date"
    for el in root.iter():
        if date_attr in el.attrib:
            el.attrib[date_attr] = "NORMALIZED_DATE"


def canonicalize_xml_bytes(xml_bytes: bytes) -> str:
    """Parse + C14N-serialize an XML part, after normalizing the one
    dynamic attribute DocxMap itself introduces. Raises ValueError (never
    silently passes through raw bytes) if the part doesn't parse, so a
    corrupt-XML regression fails loudly instead of comparing garbage."""
    parser = etree.XMLParser(resolve_entities=False)
    root = etree.fromstring(xml_bytes, parser=parser)
    _normalize_dynamic_attrs(root)
    return etree.tostring(root, method="c14n").decode("utf-8")


def canonicalize_element(el: etree._Element) -> str:
    """Canonicalize a single in-memory element (used for the text/index
    snapshot, which is taken before any part is re-serialized to bytes)."""
    return etree.tostring(el, method="c14n").decode("utf-8")


def snapshot_index(dm: DocxMap) -> Dict[str, Any]:
    """Convert `DocxMap.index` (live python-docx proxy objects) into a
    JSON-serializable, diff-stable structure. See module docstring."""
    para_ids: Dict[int, str] = {}
    run_ids: Dict[int, str] = {}
    paragraphs: Dict[str, str] = {}
    runs: Dict[str, str] = {}
    entries = []
    for item in dm.index:
        if item[0] == "break":
            entries.append(["break", None, None])
            continue
        para, run, char_index = item
        pkey = id(para._element)
        if pkey not in para_ids:
            pid = f"P{len(para_ids)}"
            para_ids[pkey] = pid
            paragraphs[pid] = canonicalize_element(para._element)
        rkey = id(run._element)
        if rkey not in run_ids:
            rid = f"R{len(run_ids)}"
            run_ids[rkey] = rid
            runs[rid] = canonicalize_element(run._element)
        entries.append([para_ids[pkey], run_ids[rkey], char_index])
    return {"entries": entries, "paragraphs": paragraphs, "runs": runs}


def _spans_for_markers(text: str) -> list:
    spans = []
    for key in fx.REDACTABLE_MARKERS:
        marker = fx.MARKERS[key]
        start = text.index(marker)  # raises ValueError -- a missing marker is a build bug
        spans.append({
            "start": start,
            "end": start + len(marker),
            "replacement": f"[REDACTED_{key.upper()}]",
            "label": "GOLDEN_HARNESS",
        })
    return spans


def run_characterization(docx_path: str, out_path: str, settings: MetadataCleaningSettings) -> Dict[str, Any]:
    """Run the full `load -> scrub_metadata -> harden_document ->
    apply_replacements -> save` pipeline against one fixture and return
    the JSON-serializable snapshot described in the module docstring."""
    dm = DocxMap.load(docx_path)

    text_index_snapshot = {"text": dm.text, "index": snapshot_index(dm)}
    spans = _spans_for_markers(dm.text)

    dm.scrub_metadata(settings)
    dm.harden_document(settings=settings)
    dm.apply_replacements(spans, track_changes=True)
    dm.save(out_path)

    parts: Dict[str, Any] = {}
    import zipfile
    with zipfile.ZipFile(out_path) as zf:
        names = sorted(zf.namelist())
        for name in names:
            data = zf.read(name)
            if name.lower().endswith(_XML_SUFFIXES):
                parts[name] = {"kind": "xml", "content": canonicalize_xml_bytes(data)}
            else:
                parts[name] = {
                    "kind": "binary",
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "length": len(data),
                }

    return {
        "text_index": text_index_snapshot,
        "part_names": names,
        "parts": parts,
        "warnings": dm.warnings,
    }


def golden_path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def load_golden(name: str) -> Dict[str, Any]:
    with open(golden_path(name), "r", encoding="utf-8") as f:
        return json.load(f)


def write_golden(name: str, snapshot: Dict[str, Any]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with open(golden_path(name), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def assert_matches_golden(name: str, snapshot: Dict[str, Any]) -> None:
    """Compare `snapshot` against the committed golden file, or (only when
    MARCUT_GOLDEN_UPDATE=1 is set) write/overwrite it -- see the "Updating
    the golden snapshots" section of the module docstring."""
    if os.environ.get("MARCUT_GOLDEN_UPDATE") == "1":
        write_golden(name, snapshot)
        return
    if not golden_path(name).exists():
        raise AssertionError(
            f"No golden snapshot at {golden_path(name)}. Generate it once with "
            f"MARCUT_GOLDEN_UPDATE=1 PYTHONPATH=src/python python3 -m pytest "
            f"tests/test_docx_io_golden.py -q, review the diff, then commit it."
        )
    expected = load_golden(name)
    assert snapshot == expected, (
        f"Golden snapshot mismatch for '{name}'. DocxMap's behavior changed. "
        f"If this is an intentional, reviewed change, regenerate with "
        f"MARCUT_GOLDEN_UPDATE=1 (see harness.py docstring); otherwise this is "
        f"exactly the regression this harness exists to catch."
    )
