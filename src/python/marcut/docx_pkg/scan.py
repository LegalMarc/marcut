"""Document scanning/indexing layer extracted from ``marcut.docx_io``.

Slice 4 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Moved verbatim: ``_iter_part_elements``,
``_iter_part_elements_with_parts``, the ``_scan_*`` family
(``_scan_drawing_tag``, ``_scan_run_contents``, ``_append_run``,
``_scan_paragraph``, ``_scan_container``, ``_scan_table_xml``), and
``_build()``. This is the layer that walks
body/headers/footers/footnotes/endnotes/text-boxes/content-controls into a
flat ``text`` + ``index`` pair (plus any ``detached_parts`` picked up along
the way) that ``DocxMap.apply_replacements()`` depends on for
character-offset span lookups.

``DocxMap`` composes a ``DocumentIndex`` in ``__init__`` and re-exposes
``.text``/``.index``/``.detached_parts`` back onto itself for backward
compatibility. ``_iter_part_elements``/``_iter_part_elements_with_parts``
are also called by the hardening/revision-writing code that still lives in
``docx_io.py`` (Slice 5 moves it), so ``DocxMap`` keeps thin delegating
methods for those two rather than duplicating them here.
"""

from typing import Any, Dict, Iterable, List, Tuple


class DocumentIndex:
    def __init__(self, doc: Any, warnings: List[Dict[str, Any]]):
        self.doc = doc
        self.text = ""
        self.index = []
        self.detached_parts = []  # Track pars that need manual blob update
        self.warnings = warnings
        self._build()

    def _iter_part_elements(self) -> Iterable[Any]:
        seen = set()
        if self.doc.element is not None:
            seen.add(id(self.doc.element))
            yield self.doc.element
        for rel in self.doc.part.rels.values():
            if any(key in rel.reltype for key in ("header", "footer", "footnotes", "endnotes", "settings", "styles")):
                if hasattr(rel.target_part, "element"):
                    root = rel.target_part.element
                    if id(root) not in seen:
                        seen.add(id(root))
                        yield root
        for _, root in self.detached_parts:
            if id(root) not in seen:
                seen.add(id(root))
                yield root

    def _iter_part_elements_with_parts(self) -> Iterable[Tuple[Any, Any]]:
        seen = set()
        if self.doc.element is not None:
            seen.add(id(self.doc.element))
            yield self.doc.part, self.doc.element
        for rel in self.doc.part.rels.values():
            if any(key in rel.reltype for key in ("header", "footer", "footnotes", "endnotes", "settings", "styles")):
                if hasattr(rel.target_part, "element"):
                    root = rel.target_part.element
                    if id(root) not in seen:
                        seen.add(id(root))
                        yield rel.target_part, root
        for part, root in self.detached_parts:
            if id(root) not in seen:
                seen.add(id(root))
                yield part, root

    def _scan_drawing_tag(self, drawing_element):
        """Deep traversal for Text Boxes inside w:drawing or w:pict."""
        from docx.text.paragraph import Paragraph
        from docx.oxml.ns import qn

        # w:drawing -> ... -> w:txbxContent -> w:p
        for txbx in drawing_element.iter(qn('w:txbxContent')):
            for content_node in txbx:
                if content_node.tag == qn('w:p'):
                    p = Paragraph(content_node, self.doc)
                    self._scan_paragraph(p)
                elif content_node.tag == qn('w:tbl'):
                     # recursive scan for table inside text box
                     self._scan_table_xml(content_node)

    def _scan_run_contents(self, run_element):
        """Scan a w:r element for nested drawings."""
        from docx.oxml.ns import qn
        # w:r -> w:drawing | w:pict
        for tag_name in ['w:drawing', 'w:pict']:
             for drawing in run_element.iter(qn(tag_name)):
                 self._scan_drawing_tag(drawing)

    def _append_run(self, para, run):
        t = run.text or ""
        for i, ch in enumerate(t):
            self.text += ch
            self.index.append((para, run, i))

    def _scan_paragraph(self, para):
        from docx.text.run import Run
        from docx.oxml.ns import qn

        # Iterate over children to catch runs inside hyperlinks AND drawings (text boxes)
        for child in para._element:
            if child.tag == qn('w:r'):
                run = Run(child, para)
                self._append_run(para, run)
                self._scan_run_contents(child)
            elif child.tag == qn('w:hyperlink'):
                for subchild in child:
                    if subchild.tag == qn('w:r'):
                        run = Run(subchild, para)
                        self._append_run(para, run)
                        self._scan_run_contents(subchild)
                    elif subchild.tag == qn('w:ins'):
                        for node in subchild:
                            if node.tag == qn('w:r'):
                                run = Run(node, para)
                                self._append_run(para, run)
                                self._scan_run_contents(node)
            elif child.tag == qn('w:drawing') or child.tag == qn('w:pict'):
                # Direct child drawings (less common but supported)
                self._scan_drawing_tag(child)
            elif child.tag == qn('w:fldSimple'):
                # Simple Field (scan runs inside)
                for subchild in child:
                    if subchild.tag == qn('w:r'):
                        run = Run(subchild, para)
                        self._append_run(para, run)
                        self._scan_run_contents(subchild)
                    elif subchild.tag == qn('w:ins'):
                        for node in subchild:
                            if node.tag == qn('w:r'):
                                run = Run(node, para)
                                self._append_run(para, run)
                                self._scan_run_contents(node)
            elif child.tag == qn('w:sdt'):
                # Inline Content Control
                # w:sdt -> w:sdtContent -> w:r
                for sdt_content in child.iter(qn('w:sdtContent')):
                    for subchild in sdt_content:
                        if subchild.tag == qn('w:r'):
                            run = Run(subchild, para)
                            self._append_run(para, run)
                            self._scan_run_contents(subchild)
                        elif subchild.tag == qn('w:ins'):
                            for node in subchild:
                                if node.tag == qn('w:r'):
                                    run = Run(node, para)
                                    self._append_run(para, run)
                                    self._scan_run_contents(node)
                        # Could recursively support other inline content here
            elif child.tag == qn('w:ins'):
                # Tracked Changes Insertion -> w:r
                for subchild in child:
                    if subchild.tag == qn('w:r'):
                        run = Run(subchild, para)
                        self._append_run(para, run)
                        self._scan_run_contents(subchild)

        self.text += "\n"
        self.index.append(("break", None, None))

    def _scan_container(self, container):
        from docx.text.paragraph import Paragraph
        from docx.oxml.ns import qn

        # Robustly get XML element to iterate
        element = getattr(container, 'element', getattr(container, '_element', None))
        if element is None:
            return

        # Handle Document object which wraps w:document -> w:body
        if element.tag == qn('w:document'):
            element = element.body

        # Iterate all children to catch w:sdt (Content Controls)
        for child in element:
            if child.tag == qn('w:p'):
                p = Paragraph(child, self.doc)
                self._scan_paragraph(p)
            elif child.tag == qn('w:tbl'):
                self._scan_table_xml(child)
            elif child.tag == qn('w:sdt'):
                # Block Level Content Control
                # w:sdt -> w:sdtContent -> (w:p | w:tbl | w:sdt)
                for sdt_content in child.iter(qn('w:sdtContent')):
                    for node in sdt_content:
                        if node.tag == qn('w:p'):
                            p = Paragraph(node, self.doc)
                            self._scan_paragraph(p)
                        elif node.tag == qn('w:tbl'):
                            self._scan_table_xml(node)
                        # We could recurse for nested SDTs, but 1 level deep often suffices.
                        # For true recursion we'd need a helper, but this covers 99%.

    def _scan_table_xml(self, tbl_element):
        """Recursively scan a table element (w:tbl) found inside another container."""
        from docx.text.paragraph import Paragraph
        from docx.oxml.ns import qn

        # w:tbl -> w:tr -> w:tc -> (w:p | w:tbl)
        for tr in tbl_element.iter(qn('w:tr')):
            for tc in tr.iter(qn('w:tc')):
                for child in tc:
                    if child.tag == qn('w:p'):
                        p = Paragraph(child, self.doc)
                        self._scan_paragraph(p)
                    elif child.tag == qn('w:tbl'):
                        # Nested table inside a cell
                        self._scan_table_xml(child)
                    elif child.tag == qn('w:sdt'):
                        # Sdt inside table cell?
                         # w:sdt -> w:sdtContent -> (w:p | w:r)
                        for sdt_content in child.iter(qn('w:sdtContent')):
                            for node in sdt_content:
                                if node.tag == qn('w:p'):
                                    p = Paragraph(node, self.doc)
                                    self._scan_paragraph(p)
                                elif node.tag == qn('w:r'):
                                    # Scan runs inside table/SDT for drawings too
                                    self._scan_run_contents(node)


    def _build(self):
        # Scan headers and footers first (to ensure they are indexed)
        # Use set of ELEMENT IDs to avoid duplicates (proxy objects have different IDs)
        scanned_elements = set()

        for section in self.doc.sections:
            # Check Headers
            for header in [section.header, section.first_page_header, section.even_page_header]:
                if header and not header.is_linked_to_previous:
                    # Deduplicate based on the XML element ID
                    el_id = id(header._element)
                    if el_id not in scanned_elements:
                        self._scan_container(header)
                        scanned_elements.add(el_id)

            # Check Footers
            for footer in [section.footer, section.first_page_footer, section.even_page_footer]:
                if footer and not footer.is_linked_to_previous:
                    el_id = id(footer._element)
                    if el_id not in scanned_elements:
                        self._scan_container(footer)
                        scanned_elements.add(el_id)

        # Scan footnotes
        try:
            part = self.doc.part
            footnote_part = None
            for rel in part.rels.values():
                if "footnotes" in rel.reltype:
                    footnote_part = rel.target_part
                    break

            if footnote_part:
                from docx.text.paragraph import Paragraph
                from docx.oxml.ns import qn
                from docx.oxml import parse_xml

                # Check if we have a live element or need to parse from blob
                root = None
                try:
                    if hasattr(footnote_part, 'element'):
                        root = footnote_part.element
                except Exception:
                    # Accessing .element failed (likely generic Part)
                    root = None

                if root is None:
                    root = parse_xml(footnote_part.blob)
                    # Register for saving later
                    self.detached_parts.append((footnote_part, root))

                # Iterate w:footnote elements
                for fn in root.findall(qn('w:footnote')):
                    for child in fn:
                        if child.tag == qn('w:p'):
                            # Wrap and scan
                            p = Paragraph(child, self.doc)
                            self._scan_paragraph(p)
                        elif child.tag == qn('w:tbl'):
                            self._scan_table_xml(child)
                        elif child.tag == qn('w:sdt'):
                            # SDT in Footnote
                            for sdt_content in child.iter(qn('w:sdtContent')):
                                for node in sdt_content:
                                    if node.tag == qn('w:p'):
                                        p = Paragraph(node, self.doc)
                                        self._scan_paragraph(p)
                                    elif node.tag == qn('w:tbl'):
                                        self._scan_table_xml(node)
        except Exception as exc:
            self.warnings.append({
                "code": "FOOTNOTE_SCAN_FAILED",
                "message": "Footnote content could not be scanned for redaction.",
                "details": str(exc)
            })

        # Scan endnotes
        try:
            part = self.doc.part
            endnote_part = None
            for rel in part.rels.values():
                if "endnotes" in rel.reltype:
                    endnote_part = rel.target_part
                    break

            if endnote_part:
                from docx.text.paragraph import Paragraph
                from docx.oxml.ns import qn
                from docx.oxml import parse_xml

                # Robustly get the root element
                root = None
                try:
                    if hasattr(endnote_part, 'element'):
                        root = endnote_part.element
                except Exception:
                    root = None

                if root is None:
                    root = parse_xml(endnote_part.blob)
                    # Register for saving later
                    self.detached_parts.append((endnote_part, root))

                # Iterate w:endnote elements
                for en in root.findall(qn('w:endnote')):
                    for child in en:
                        if child.tag == qn('w:p'):
                            # Wrap and scan
                            p = Paragraph(child, self.doc)
                            self._scan_paragraph(p)
                        elif child.tag == qn('w:tbl'):
                            self._scan_table_xml(child)
                        elif child.tag == qn('w:sdt'):
                            # SDT in Endnote
                            for sdt_content in child.iter(qn('w:sdtContent')):
                                for node in sdt_content:
                                    if node.tag == qn('w:p'):
                                        p = Paragraph(node, self.doc)
                                        self._scan_paragraph(p)
                                    elif node.tag == qn('w:tbl'):
                                        self._scan_table_xml(node)
        except Exception as exc:
            self.warnings.append({
                "code": "ENDNOTE_SCAN_FAILED",
                "message": "Endnote content could not be scanned for redaction.",
                "details": str(exc)
            })

        # Scan main document body
        self._scan_container(self.doc)
