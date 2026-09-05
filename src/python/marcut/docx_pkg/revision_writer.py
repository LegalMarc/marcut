"""Track-changes revision authoring, extracted from ``marcut.docx_io``.

Slice 5 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Moved verbatim: ``_make_text_run``, ``_insert_after`` (legacy),
``_insert_deletion_after``, ``_insert_insertion_after``,
``apply_replacements()``, and ``_ensure_track_revisions_enabled``.

Named ``revision_writer.py`` rather than ``revisions.py`` (per the design
doc's Slice 5 note) to avoid confusion with the existing top-level
``marcut/docx_revisions.py``, which handles *accepting* pre-existing
revisions on load -- a different concern from authoring new ones here.

``RevisionWriter`` operates on the live ``python-docx`` object graph and
needs the same part-iteration helper ``scan.py``'s ``DocumentIndex`` owns
(``_iter_part_elements_with_parts``); per the design doc, that stays one
method owned by ``DocumentIndex`` and is injected here rather than
duplicated -- the constructor takes an ``iter_part_elements_with_parts``
callable and stores it under the same attribute name the moved
``apply_replacements()`` body already calls
(``self._iter_part_elements_with_parts()``), so that body did not need to
change at all to move. Similarly, ``index`` and ``warnings`` are the same
list objects ``DocumentIndex``/``DocxMap`` already own -- shared by
reference, not copied -- so appends and the character-offset index stay in
sync with the rest of ``DocxMap``.

``DocxMap`` (now in ``document.py``) composes a ``RevisionWriter`` in
``__init__`` and keeps a thin delegating method for ``apply_replacements``.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Tuple

from docx.enum.text import WD_COLOR_INDEX
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.run import Run


class RevisionWriter:
    def __init__(
        self,
        doc: Any,
        index: List[Any],
        iter_part_elements_with_parts: Callable[[], Iterable[Tuple[Any, Any]]],
        warnings: List[Dict[str, Any]],
        author_name: str = "Marcut",
    ):
        self.doc = doc
        self.index = index
        self._iter_part_elements_with_parts = iter_part_elements_with_parts
        self.warnings = warnings
        self.author_name = author_name
        self._rev_id = 1

    def _make_text_run(self, text: str, rPr=None, source_run=None) -> OxmlElement:
        r = OxmlElement("w:r")
        if source_run is not None:
            # Copy attributes (like rsidR) from source to preserve identity
            for key, value in source_run.attrib.items():
                r.set(key, value)

        if rPr is not None:
            from copy import deepcopy
            r.append(deepcopy(rPr))

        t = OxmlElement("w:t")
        # Preserve spaces so replacements aren't collapsed
        t.set(qn('xml:space'), 'preserve')
        t.text = text
        r.append(t)
        return r

    def _insert_after(self, run: Run, text: str, highlight: bool) -> Run:
        # Legacy highlighter insertion; kept for compatibility
        r = self._make_text_run(text)
        run._element.addnext(r)
        new = Run(r, run._parent)
        if highlight:
            new.font.highlight_color = WD_COLOR_INDEX.YELLOW
        return new

    def _insert_deletion_after(self, anchor_el, text: str, rPr=None):
        del_el = OxmlElement('w:del')
        del_el.set(qn('w:id'), str(self._rev_id))
        self._rev_id += 1
        del_el.set(qn('w:author'), self.author_name)
        del_el.set(qn('w:date'), datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))

        # Create run for deleted text, retaining original formatting
        r = self._make_text_run(text, rPr)

        # Change w:t to w:delText
        t_el = r.find(qn('w:t'))
        if t_el is not None:
            t_el.tag = qn('w:delText')

        del_el.append(r)
        anchor_el.addnext(del_el)
        return del_el

    def _insert_insertion_after(self, anchor_el, text: str, rPr=None):
        ins_el = OxmlElement('w:ins')
        ins_el.set(qn('w:id'), str(self._rev_id))
        self._rev_id += 1
        ins_el.set(qn('w:author'), self.author_name)
        ins_el.set(qn('w:date'), datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        r = self._make_text_run(text, rPr)
        ins_el.append(r)
        anchor_el.addnext(ins_el)
        return ins_el

    def _ensure_track_revisions_enabled(self) -> None:
        try:
            settings = getattr(self.doc, "settings", None)
            if settings is None or settings.element is None:
                return
            root = settings.element
            track_el = root.find(qn("w:trackRevisions"))
            if track_el is None:
                root.append(OxmlElement("w:trackRevisions"))
        except Exception:
            pass

    def apply_replacements(self, spans: List[Dict[str,Any]], track_changes: bool = True):
        if track_changes:
            self._ensure_track_revisions_enabled()
        spans = sorted(spans, key=lambda s: s["start"], reverse=True)
        part_by_root: Dict[int, Any] = {}
        for part, root in self._iter_part_elements_with_parts():
            part_by_root[id(root)] = part
        link_targets: Dict[int, set] = {}
        link_elements: List[Any] = []
        for sp in spans:
            s, e, repl = sp["start"], sp["end"], sp["replacement"]
            if not (0 <= s < len(self.index)):
                continue
            start_idx = self.index[s]
            if start_idx[0] == "break":
                continue
            para0, run0, ci0 = start_idx

            # Collect affected characters per run
            buckets: Dict[tuple, List] = {}
            for pos in range(s, min(e, len(self.index))):
                idx = self.index[pos]
                if idx[0] == "break":
                    continue
                key = (id(idx[0]), id(idx[1]))
                buckets.setdefault(key, []).append(idx)

            if sp.get("label") == "URL":
                for _, chars in buckets.items():
                    r = chars[0][1]
                    node = r._element
                    while node is not None and node.tag != qn("w:hyperlink"):
                        node = node.getparent()
                    if node is None:
                        continue
                    if node not in link_elements:
                        link_elements.append(node)
                    rel_id = node.get(qn("r:id"))
                    if rel_id:
                        root = node.getroottree().getroot()
                        part = part_by_root.get(id(root))
                        if part is not None:
                            link_targets.setdefault(id(part), set()).add(rel_id)
                        else:
                            self.warnings.append({
                                "code": "URL_LINK_TARGET_UNRESOLVED",
                                "message": "Unable to resolve hyperlink target for a redacted URL.",
                                "details": f"Relationship id: {rel_id}"
                            })

            if not track_changes:
                # Legacy: remove and optionally highlight insert
                for _, chars in buckets.items():
                    r = chars[0][1]
                    buf = list(r.text or "")
                    for _, _, ci in chars:
                        if 0 <= ci < len(buf):
                            buf[ci] = ""
                    r.text = "".join(buf)
                before = run0.text[:ci0]
                after = run0.text[ci0:]
                run0.text = before
                tag = self._insert_after(run0, repl, False)
                self._insert_after(tag, after, False)
                continue

            # Track changes mode: wrap deletions and add insertion
            # First, process each run that intersects with the span
            processed_first = False
            for _, chars in buckets.items():
                r = chars[0][1]
                original = r.text or ""
                cis = sorted(ci for _, _, ci in chars if ci is not None)
                if not cis:
                    continue
                start_ci = cis[0]
                end_ci = cis[-1]
                pre = original[:start_ci]
                mid = original[start_ci:end_ci+1]
                post = original[end_ci+1:]

                # Grab the run properties to preserve formatting
                rPr = r._element.find(qn('w:rPr'))

                # Set the run to pre-text only
                r.text = pre

                # Insert deletion for removed text (preserving formatting)
                del_el = self._insert_deletion_after(r._element, mid, rPr)

                if not processed_first and r is run0:
                    # Insert the replacement as an insertion after the deletion
                    # Preserve the original run's formatting (font, size, bold, italic) so that
                    # redaction labels match the surrounding text. We pass rPr and then strip
                    # only problematic properties (hidden, shading) while keeping visual styling.
                    # ALSO: Force RED color to ensure visibility against any background.
                    ins_el = self._insert_insertion_after(del_el, repl, rPr)
                    try:
                         # Find w:r inside w:ins
                         r_el = ins_el.find(qn('w:r'))
                         if r_el is not None:
                             rPr_el = r_el.find(qn('w:rPr'))
                             if rPr_el is None:
                                 rPr_el = OxmlElement('w:rPr')
                                 r_el.insert(0, rPr_el)

                             # Strip problematic properties that could hide or obscure the label
                             # while preserving font, size, bold, italic, underline
                             STRIP_PROPS = ['w:vanish', 'w:webHidden', 'w:shd', 'w:highlight',
                                           'w:effect', 'w:specVanish', 'w:oMath']
                             for prop in STRIP_PROPS:
                                 el = rPr_el.find(qn(prop))
                                 if el is not None:
                                     rPr_el.remove(el)

                             # Force Color Red for visibility
                             # First remove any existing color to avoid duplicates
                             existing_color = rPr_el.find(qn('w:color'))
                             if existing_color is not None:
                                 rPr_el.remove(existing_color)
                             color_el = OxmlElement('w:color')
                             color_el.set(qn('w:val'), 'FF0000')
                             rPr_el.append(color_el)
                    except Exception:
                        pass

                    # Append the remainder of this run after the insertion
                    if post:
                        # CRITICAL FIX: Use rPr for the post-split run so it doesn't lose formatting
                        # AND pass source run element to preserve attributes (rsid) so it's not seen as new insert
                        ins_el.addnext(self._make_text_run(post, rPr, r._element))
                    processed_first = True
                else:
                    # For other runs, just append the remainder after deletion
                    if post:
                        # CRITICAL FIX: Use rPr for the post-split run
                        del_el.addnext(self._make_text_run(post, rPr, r._element))

        # Unlink hyperlink elements for redacted URLs and remove rel targets
        if link_elements:
            for hyperlink in link_elements:
                parent = hyperlink.getparent()
                if parent is None:
                    continue
                idx = parent.index(hyperlink)
                for child in list(hyperlink):
                    parent.insert(idx, child)
                    idx += 1
                parent.remove(hyperlink)
            for part_id, rel_ids in link_targets.items():
                part = None
                for candidate in self.doc.part.package.parts:
                    if id(candidate) == part_id:
                        part = candidate
                        break
                if part is None:
                    self.warnings.append({
                        "code": "URL_LINK_TARGET_UNRESOLVED",
                        "message": "Unable to resolve hyperlink target for a redacted URL.",
                        "details": "Target relationship could not be located."
                    })
                    continue
                for rel_id in rel_ids:
                    try:
                        if rel_id in part.rels:
                            del part.rels[rel_id]
                    except Exception:
                        self.warnings.append({
                            "code": "URL_LINK_TARGET_REMOVE_FAILED",
                            "message": "Failed to remove hyperlink target for a redacted URL.",
                            "details": f"Relationship id: {rel_id}"
                        })
