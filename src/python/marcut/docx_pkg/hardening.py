"""In-memory XML hardening and metadata scrubbing, extracted from
``marcut.docx_io``.

Slice 5 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Moved verbatim: ``harden_document()``, ``scrub_metadata()``, and
their private helpers (``_unlink_hyperlinks``, ``_strip_comment_markers*``,
``_comment_visibility_map``, ``_remove_comment_entries``, mail-merge/
data-binding/hidden-text/invisible-object/header-footer/watermark/
ink-annotation removal).

``MetadataHardener`` operates on the live ``python-docx`` object graph and
needs the same part-iteration helper ``scan.py``'s ``DocumentIndex`` owns
(``_iter_part_elements``); per the design doc, that stays one method owned
by ``DocumentIndex`` and is injected here rather than duplicated -- the
constructor takes an ``iter_part_elements`` callable and stores it under
the same attribute name the moved method bodies already call
(``self._iter_part_elements()``), so those bodies did not need to change at
all to move.

``DocxMap`` (now in ``document.py``) composes a ``MetadataHardener`` in
``__init__`` and keeps thin delegating methods for ``harden_document``,
``scrub_metadata``, and ``_comment_visibility_map`` (the last is called
directly in tests). The ``_metadata_settings`` -> ``save()`` order-dependency
contract is preserved by ``DocxMap.scrub_metadata()`` copying
``self._metadata_settings`` off of this class back onto itself after
delegating -- see ``document.py``.
"""

import copy
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from .settings import MetadataCleaningSettings


class MetadataHardener:
    def __init__(
        self,
        doc: Any,
        warnings: List[Dict[str, Any]],
        iter_part_elements: Callable[[], Iterable[Any]],
    ):
        self.doc = doc
        self.warnings = warnings
        self._iter_part_elements = iter_part_elements

    def _append_warning(self, code: str, message: str, details: Optional[str] = None) -> None:
        warning: Dict[str, Any] = {"code": code, "message": message}
        if details:
            warning["details"] = details
        self.warnings.append(warning)

    def _unlink_hyperlinks(self) -> None:
        for root in self._iter_part_elements():
            for hyperlink in list(root.iter(qn("w:hyperlink"))):
                parent = hyperlink.getparent()
                if parent is None:
                    continue
                idx = parent.index(hyperlink)
                for child in list(hyperlink):
                    parent.insert(idx, child)
                    idx += 1
                parent.remove(hyperlink)

    def _strip_comment_markers(self) -> None:
        tags = [qn("w:commentRangeStart"), qn("w:commentRangeEnd"), qn("w:commentReference")]
        for root in self._iter_part_elements():
            for tag in tags:
                for el in list(root.iter(tag)):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)

    def _strip_comment_markers_by_ids(self, ids: set) -> None:
        if not ids:
            return
        tags = [qn("w:commentRangeStart"), qn("w:commentRangeEnd"), qn("w:commentReference")]
        for root in self._iter_part_elements():
            for tag in tags:
                for el in list(root.iter(tag)):
                    cid = el.get(qn("w:id")) or ""
                    if cid in ids:
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)

    def _comment_visibility_map(self) -> Dict[str, str]:
        from lxml import etree
        comment_ids = set()
        status_map: Dict[str, str] = {}

        try:
            for part in self.doc.part.package.parts:
                if str(part.partname) == "/word/comments.xml":
                    blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
                    if not blob:
                        break
                    comments_xml = etree.fromstring(blob)
                    for comment in comments_xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}comment'):
                        cid = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id') or comment.get('id', '')
                        if cid:
                            comment_ids.add(cid)
                    break
        except Exception:
            return status_map

        def _has_ancestor(elem, tag) -> bool:
            return any(a.tag == tag for a in elem.iterancestors())

        def _is_hidden_run(elem) -> bool:
            for run in elem.iterancestors(qn('w:r')):
                rpr = run.find(qn('w:rPr'))
                if rpr is None:
                    continue
                if rpr.find(qn('w:vanish')) is not None:
                    return True
                if rpr.find(qn('w:webHidden')) is not None:
                    return True
                if rpr.find(qn('w:specVanish')) is not None:
                    return True
            return False

        comment_anchors: Dict[str, Dict[str, Any]] = {}
        try:
            for root in self._iter_part_elements():
                active: Dict[str, bool] = {}
                for elem in root.iter():
                    tag = elem.tag
                    if tag == qn('w:commentRangeStart'):
                        cid = elem.get(qn('w:id')) or ''
                        if not cid:
                            continue
                        info = comment_anchors.setdefault(cid, {"contexts": set(), "has_start": False})
                        info["has_start"] = True
                        if _has_ancestor(elem, qn('w:del')) or _has_ancestor(elem, qn('w:moveFrom')):
                            info["contexts"].add("deleted")
                        active[cid] = True
                        continue
                    if tag == qn('w:commentRangeEnd'):
                        cid = elem.get(qn('w:id')) or ''
                        if cid in active:
                            del active[cid]
                        continue
                    if not active:
                        continue
                    if tag in (qn('w:t'), qn('w:delText'), qn('w:instrText')) and elem.text:
                        is_hidden = _is_hidden_run(elem)
                        is_deleted = _has_ancestor(elem, qn('w:del')) or _has_ancestor(elem, qn('w:moveFrom'))
                        for cid in active:
                            info = comment_anchors.setdefault(cid, {"contexts": set(), "has_start": False})
                            if is_hidden:
                                info["contexts"].add("hidden")
                            if is_deleted:
                                info["contexts"].add("deleted")
        except Exception:
            return status_map

        for cid in comment_ids:
            anchor_info = comment_anchors.get(cid) or {}
            contexts = anchor_info.get("contexts", set())
            if not anchor_info or not anchor_info.get("has_start"):
                status = "deleted"
            elif "deleted" in contexts:
                status = "deleted"
            elif "hidden" in contexts:
                status = "hidden"
            else:
                status = "visible"
            status_map[cid] = status

        return status_map

    def _remove_comment_entries(self, ids: set) -> None:
        if not ids:
            return
        from lxml import etree
        for part in self.doc.part.package.parts:
            if str(part.partname) != "/word/comments.xml":
                continue
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if not blob:
                return
            try:
                comments_xml = etree.fromstring(blob)
                for comment in list(comments_xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}comment')):
                    cid = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id') or comment.get('id', '')
                    if cid in ids:
                        parent = comment.getparent()
                        if parent is not None:
                            parent.remove(comment)
                new_blob = etree.tostring(comments_xml, encoding="UTF-8", xml_declaration=True)
                part._blob = new_blob
                if hasattr(part, "_element"):
                    part._element = comments_xml
            except Exception:
                return

    def _parse_merge_field_name(self, instr_text: str) -> Optional[str]:
        if not instr_text:
            return None
        normalized = " ".join(instr_text.replace("\u00a0", " ").split())
        if "MERGEFIELD" not in normalized.upper():
            return None
        parts = re.split(r"MERGEFIELD", normalized, flags=re.IGNORECASE, maxsplit=1)
        if len(parts) < 2:
            return None
        remainder = parts[1].strip()
        if remainder.startswith('"'):
            end_quote = remainder.find('"', 1)
            if end_quote != -1:
                return remainder[1:end_quote].strip()
        name = remainder.split("\\", 1)[0].strip()
        name = name.strip('"')
        return name or None

    def _build_merge_field_run(self, text: str, template_run=None):
        run = OxmlElement("w:r")
        if template_run is not None:
            rpr = template_run.find(qn("w:rPr"))
            if rpr is not None:
                run.append(copy.deepcopy(rpr))
        t = OxmlElement("w:t")
        t.text = text
        run.append(t)
        return run

    def _convert_mail_merge_fields(self) -> None:
        def _replace_simple_fields(root):
            for fld in list(root.iter(qn("w:fldSimple"))):
                instr = fld.get(qn("w:instr")) or ""
                name = self._parse_merge_field_name(instr)
                if not name:
                    continue
                template_run = None
                for child in fld.iter(qn("w:r")):
                    template_run = child
                    break
                new_run = self._build_merge_field_run(f"<<{name}>>", template_run)
                parent = fld.getparent()
                if parent is None:
                    continue
                idx = parent.index(fld)
                parent.remove(fld)
                parent.insert(idx, new_run)

        def _replace_complex_fields(root):
            for para in list(root.iter(qn("w:p"))):
                runs = list(para.findall(qn("w:r")))
                i = 0
                while i < len(runs):
                    run = runs[i]
                    fld_char = run.find(qn("w:fldChar"))
                    if fld_char is None or fld_char.get(qn("w:fldCharType")) != "begin":
                        i += 1
                        continue
                    instr_text = ""
                    display_text = ""
                    template_run = None
                    end_idx = None
                    in_result = False
                    j = i + 1
                    while j < len(runs):
                        current = runs[j]
                        instr_el = current.find(qn("w:instrText"))
                        if instr_el is not None and instr_el.text:
                            instr_text += instr_el.text
                        fld_mid = current.find(qn("w:fldChar"))
                        if fld_mid is not None:
                            fld_type = fld_mid.get(qn("w:fldCharType"))
                            if fld_type == "separate":
                                in_result = True
                            elif fld_type == "end":
                                end_idx = j
                                break
                        if in_result:
                            t_el = current.find(qn("w:t"))
                            if t_el is not None and t_el.text:
                                display_text += t_el.text
                                if template_run is None:
                                    template_run = current
                        j += 1

                    name = self._parse_merge_field_name(instr_text)
                    if name is None and display_text:
                        trimmed = display_text.strip()
                        trimmed = trimmed.replace("\u00ab", "").replace("\u00bb", "")
                        trimmed = trimmed.strip("<>").strip()
                        name = trimmed if trimmed else None

                    if name and end_idx is not None:
                        new_run = self._build_merge_field_run(f"<<{name}>>", template_run or run)
                        for k in range(end_idx, i - 1, -1):
                            para.remove(runs[k])
                        para.insert(i, new_run)
                        runs = list(para.findall(qn("w:r")))
                        i += 1
                        continue
                    i += 1

        for root in self._iter_part_elements():
            _replace_simple_fields(root)
            _replace_complex_fields(root)

    def _remove_data_bindings(self) -> None:
        for root in self._iter_part_elements():
            for sdt_pr in list(root.iter(qn("w:sdtPr"))):
                for binding in list(sdt_pr.iter(qn("w:dataBinding"))):
                    parent = binding.getparent()
                    if parent is not None:
                        parent.remove(binding)

    def _remove_hidden_text(self) -> None:
        hidden_tags = [qn("w:vanish"), qn("w:specVanish"), qn("w:webHidden")]
        for root in self._iter_part_elements():
            for run in list(root.iter(qn("w:r"))):
                rpr = run.find(qn("w:rPr"))
                if rpr is None:
                    continue
                if any(rpr.find(tag) is not None for tag in hidden_tags):
                    parent = run.getparent()
                    if parent is not None:
                        parent.remove(run)

    def _remove_invisible_objects(self) -> None:
        for root in self._iter_part_elements():
            for el in list(root.iter()):
                style = (el.get("style") or "").lower()
                visibility = (el.get("visibility") or "").lower()
                display = (el.get("display") or "").lower()
                if ("visibility:hidden" in style
                        or "visibility: hidden" in style
                        or "display:none" in style
                        or "mso-hide:all" in style
                        or visibility == "hidden"
                        or display == "none"):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)

    def _remove_headers_footers(self) -> None:
        try:
            for sect_pr in list(self.doc.element.iter(qn("w:sectPr"))):
                for tag in (qn("w:headerReference"), qn("w:footerReference")):
                    for el in list(sect_pr.iter(tag)):
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)
        except Exception:
            pass

        try:
            rels = self.doc.part.rels
            for r_id, rel in list(rels.items()):
                if "header" in rel.reltype or "footer" in rel.reltype:
                    del rels[r_id]
        except Exception:
            pass

    def _remove_watermarks(self) -> None:
        def _is_watermark_candidate(el) -> bool:
            attrs = " ".join(str(v) for v in el.attrib.values()).lower()
            if "powerpluswatermarkobject" in attrs or "watermark" in attrs:
                return True
            if "mso-position-horizontal:center" in attrs and "mso-position-vertical:center" in attrs and "z-index" in attrs:
                return True
            return False

        for rel in self.doc.part.rels.values():
            if "header" not in rel.reltype:
                continue
            if not hasattr(rel.target_part, "element"):
                continue
            root = rel.target_part.element
            for el in list(root.iter()):
                if _is_watermark_candidate(el):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)

    def _remove_ink_annotations(self) -> None:
        for root in self._iter_part_elements():
            for el in list(root.iter()):
                tag = el.tag
                if not isinstance(tag, str):
                    continue
                local = tag.split("}", 1)[-1].lower()
                if local.startswith("ink"):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)

    def harden_document(
        self,
        scrub_all_images: bool = False,
        settings: Optional[MetadataCleaningSettings] = None
    ):
        """
        Apply security hardening measures:
        1. Remove Hyperlinks (convert to plain text by deleting relationships).
        2. Clear RSIDs (Revision Save IDs) to prevent fingerprinting.
        3. Replace Embedded Objects with placeholders.
        4. (Optional) Delete all images if enabled.
        5. (Implicit) Thumbnail deletion is best done on file save/zip level, but we can try removing the package rel.
        """
        if settings is None:
            settings = MetadataCleaningSettings()

        # 1. Remove Hyperlinks (delete relationships to convert links to plain text)
        if settings.clean_hyperlink_urls:
            try:
                self._unlink_hyperlinks()
                # Collect hyperlink relationship IDs to remove
                hyperlink_rel_ids = []
                for rel_id, rel in self.doc.part.rels.items():
                    if "hyperlink" in rel.reltype:
                        hyperlink_rel_ids.append(rel_id)

                # Remove the hyperlink relationships
                # This converts the hyperlinks to plain text in the document
                for rel_id in hyperlink_rel_ids:
                    del self.doc.part.rels[rel_id]
            except Exception as exc:
                self._append_warning(
                    "HARDEN_HYPERLINK_CLEAN_FAILED",
                    "Hyperlink hardening could not be completed.",
                    str(exc),
                )

        # 2. Hardening Pass (RSID, Objects, Images)
        # We need to traverse Body, Headers, Footers, Footnotes, Endnotes

        def _harden_element(element):
            # A. Clear RSID attributes
            if settings.clean_rsids:
                for key in list(element.attrib.keys()):
                    if "rsid" in key.lower():
                        del element.attrib[key]

            # B. Check contents
            # We must iterate a copy of children to modify structure safely
            for child in list(element):
                tag = child.tag

                # Embedded Objects
                if tag == qn('w:object') or tag == qn('w:control'):
                    if settings.clean_ole_objects or settings.clean_activex:
                        parent = element
                        if parent.tag == qn('w:r'):
                            parent.remove(child)
                            if len(parent) == 0:
                                t_repl = OxmlElement('w:t')
                                t_repl.text = "[REDACTED DATA OBJECT]"
                                parent.append(t_repl)
                        else:
                            replacement_run = OxmlElement('w:r')
                            t_repl = OxmlElement('w:t')
                            t_repl.text = "[REDACTED DATA OBJECT]"
                            replacement_run.append(t_repl)
                            index = parent.index(child)
                            parent.insert(index, replacement_run)
                            parent.remove(child)
                        continue

                # Images (Drawings)
                if scrub_all_images:
                    if tag == qn('w:drawing') or tag == qn('w:pict'):
                         # Delete image
                         element.remove(child)
                         continue

                # Recurse
                _harden_element(child)
        # Apply to all document parts (Body, Headers, Footers, Footnotes, Endnotes, etc.)
        for root in self._iter_part_elements():
            # If it's the main document, start from body
            if root.tag == qn('w:document') and hasattr(root, 'body'):
                if root.body is not None:
                    _harden_element(root.body)
            else:
                _harden_element(root)

    def scrub_metadata(self, settings: Optional[MetadataCleaningSettings] = None):
        """
        Wipes document metadata based on user-configurable settings.
        If no settings provided, uses defaults (all ON except created/modified dates).
        Values are deleted (set to empty) rather than replaced with placeholder text.
        """
        if settings is None:
            settings = MetadataCleaningSettings()

        cp = self.doc.core_properties

        # Core Properties - delete values (use empty strings)
        if settings.clean_author:
            cp.author = ""
        if settings.clean_last_modified_by:
            cp.last_modified_by = ""
        if settings.clean_comments:
            cp.comments = ""
        if settings.clean_title:
            cp.title = ""
        if settings.clean_subject:
            cp.subject = ""
        if settings.clean_keywords:
            cp.keywords = ""
        if settings.clean_category:
            try:
                cp.category = ""
            except Exception:
                pass
        if settings.clean_content_status:
            try:
                cp.content_status = ""
            except Exception:
                pass
        if settings.clean_revision_number:
            cp.revision = 1
        if settings.clean_identifier:
            try:
                cp.identifier = ""
            except Exception:
                pass
        if settings.clean_language:
            try:
                cp.language = ""
            except Exception:
                pass
        if settings.clean_version:
            try:
                cp.version = ""
            except Exception:
                pass
        if settings.clean_last_printed:
            try:
                cp.last_printed = None
            except Exception:
                pass
        if settings.clean_created_date:
            try:
                cp.created = None
            except Exception:
                pass
        if settings.clean_modified_date:
            try:
                cp.modified = None
            except Exception:
                pass

        # Remove empty core property elements to keep schema-valid content
        try:
            from lxml import etree

            core_part = None
            for rel in self.doc.part.package.rels.values():
                if "core-properties" in rel.reltype:
                    core_part = rel.target_part
                    break

            if core_part is not None:
                root = core_part.element if hasattr(core_part, "element") else etree.fromstring(core_part._blob)
                ns = {
                    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                    "dc": "http://purl.org/dc/elements/1.1/",
                    "dcterms": "http://purl.org/dc/terms/",
                }

                def _remove(tag: str) -> None:
                    for elem in root.findall(tag, namespaces=ns):
                        parent = elem.getparent()
                        if parent is not None:
                            parent.remove(elem)

                if settings.clean_author:
                    _remove("dc:creator")
                if settings.clean_last_modified_by:
                    _remove("cp:lastModifiedBy")
                if settings.clean_title:
                    _remove("dc:title")
                if settings.clean_subject:
                    _remove("dc:subject")
                if settings.clean_keywords:
                    _remove("cp:keywords")
                if settings.clean_comments:
                    _remove("dc:description")
                if settings.clean_category:
                    _remove("cp:category")
                if settings.clean_content_status:
                    _remove("cp:contentStatus")
                if settings.clean_identifier:
                    _remove("dc:identifier")
                if settings.clean_language:
                    _remove("dc:language")
                if settings.clean_version:
                    _remove("cp:version")
                if settings.clean_last_printed:
                    _remove("cp:lastPrinted")
                if settings.clean_created_date:
                    _remove("dcterms:created")
                if settings.clean_modified_date:
                    _remove("dcterms:modified")

                if settings.clean_revision_number:
                    for elem in root.findall("cp:revision", namespaces=ns):
                        elem.text = "1"

                core_part._blob = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
        except Exception as e:
            print(f"[MARCUT] Warning: core.xml cleaning failed: {e}")

        # 1. Disable Spell Check/Grammar
        if settings.clean_spell_grammar_state:
            try:
                doc_settings = self.doc.settings.element
                proof_states = list(doc_settings.findall(qn('w:proofState')))
                if proof_states:
                    # Keep the first proofState, normalize attributes, drop extras
                    primary = proof_states[0]
                    primary.set(qn('w:spelling'), 'clean')
                    primary.set(qn('w:grammar'), 'clean')
                    for attr in list(primary.attrib.keys()):
                        if attr not in (qn('w:spelling'), qn('w:grammar')):
                            del primary.attrib[attr]
                    for extra in proof_states[1:]:
                        doc_settings.remove(extra)
                else:
                    proof_state = OxmlElement('w:proofState')
                    proof_state.set(qn('w:spelling'), 'clean')
                    proof_state.set(qn('w:grammar'), 'clean')
                    doc_settings.append(proof_state)
            except Exception as exc:
                self._append_warning(
                    "SPELL_GRAMMAR_CLEAN_FAILED",
                    "Spell/grammar state cleanup failed.",
                    str(exc),
                )

        # 2. Remove Comments and Custom Properties parts via Relationships
        try:
            clean_comments_all = settings.clean_review_comments_visible and settings.clean_review_comments_hidden
            rels = self.doc.part.rels
            ids_to_remove = []

            for r_id, rel in rels.items():
                should_remove = False

                # Comments
                if clean_comments_all and "comments" in rel.reltype:
                    should_remove = True
                # Custom XML (custom properties store here)
                if settings.clean_custom_properties and ("customXml" in rel.reltype or "custom-properties" in rel.reltype):
                    should_remove = True
                # Glossary
                if settings.clean_glossary and "glossary" in rel.reltype:
                    should_remove = True
                # VBA Macros
                if settings.clean_vba_macros and "vbaProject" in rel.reltype:
                    should_remove = True
                # Digital Signatures
                if settings.clean_digital_signatures and "signature" in rel.reltype:
                    should_remove = True

                if should_remove:
                    ids_to_remove.append(r_id)
                    try:
                        if hasattr(rel.target_part, 'element'):
                            rel.target_part.element.clear()
                    except Exception:
                        pass

            for r_id in ids_to_remove:
                del rels[r_id]
        except Exception as exc:
            self._append_warning(
                "RELATIONSHIP_CLEAN_FAILED",
                "Relationship cleanup failed for one or more metadata parts.",
                str(exc),
            )

        try:
            clean_visible = settings.clean_review_comments_visible
            clean_hidden = settings.clean_review_comments_hidden
            retained_count = 0
            if clean_visible or clean_hidden:
                if clean_comments_all:
                    self._strip_comment_markers()
                else:
                    visibility_map = self._comment_visibility_map()
                    ids_to_remove = set()
                    for cid, status in visibility_map.items():
                        if status == "visible" and clean_visible:
                            ids_to_remove.add(cid)
                        if status in ("hidden", "deleted") and clean_hidden:
                            ids_to_remove.add(cid)
                    self._remove_comment_entries(ids_to_remove)
                    self._strip_comment_markers_by_ids(ids_to_remove)
                    retained_count = len(set(visibility_map) - ids_to_remove)
            else:
                # Both visibility classes are being kept: nothing is removed,
                # so every existing comment (if any) survives untouched.
                retained_count = len(self._comment_visibility_map())

            # Review comment text is never scanned by the redaction pipeline
            # (rules/LLM only see word/document.xml + headers/footers/
            # footnotes/endnotes/textboxes/content controls -- comments.xml
            # paragraph content is out of scope). When settings fully remove
            # comments this is moot; but when any comment is retained, its
            # text -- including any PII it contains -- ships unredacted.
            # Disclose that loudly rather than leaking it silently.
            if retained_count:
                self._append_warning(
                    "REVIEW_COMMENTS_NOT_SCANNED",
                    f"{retained_count} review comment(s) were kept per your metadata "
                    "settings. Comment text is not scanned for PII by the redaction "
                    "pipeline and may contain unredacted sensitive information.",
                )
        except Exception as exc:
            self._append_warning(
                "COMMENT_MARKER_CLEAN_FAILED",
                "Comment marker cleanup failed.",
                str(exc),
            )

        # 3. Clean app.xml properties (Company, Manager, Application, etc.)
        # These require direct XML access via the package parts
        try:
            from lxml import etree

            # Access the app.xml part through document relationships
            for rel in self.doc.part.package.rels.values():
                if "extended-properties" in rel.reltype or "app" in rel.reltype:
                    app_part = rel.target_part
                    if hasattr(app_part, '_blob') and app_part._blob:
                        # Parse the app.xml content
                        app_xml = etree.fromstring(app_part._blob)

                        # Define namespace
                        ns = {'ep': 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'}

                        def _remove_elements(tag: str, app_xml=app_xml, ns=ns) -> None:
                            for elem in app_xml.findall(f'.//ep:{tag}', namespaces=ns):
                                parent = elem.getparent()
                                if parent is not None:
                                    parent.remove(elem)

                        # Clean Company
                        if settings.clean_company:
                            _remove_elements("Company")

                        # Clean Manager
                        if settings.clean_manager:
                            _remove_elements("Manager")

                        # Clean Application
                        if settings.clean_application:
                            _remove_elements("Application")

                        # Clean AppVersion
                        if settings.clean_app_version:
                            _remove_elements("AppVersion")

                        # Clean Template
                        if settings.clean_template:
                            _remove_elements("Template")

                        if settings.clean_hyperlink_base:
                            _remove_elements("HyperlinkBase")

                        # Clean TotalTime (editing time)
                        if settings.clean_total_editing_time:
                            for elem in app_xml.findall('.//ep:TotalTime', namespaces=ns):
                                elem.text = "0"

                        # Clean Statistics (Words, Characters, Lines, Paragraphs, Pages)
                        if settings.clean_statistics:
                            for tag in ['Words', 'Characters', 'CharactersWithSpaces', 'Lines', 'Paragraphs', 'Pages']:
                                for elem in app_xml.findall(f'.//ep:{tag}', namespaces=ns):
                                    elem.text = "0"

                        # Clean DocSecurity
                        if settings.clean_doc_security:
                            for elem in app_xml.findall('.//ep:DocSecurity', namespaces=ns):
                                elem.text = "0"

                        # Clean ScaleCrop
                        if settings.clean_scale_crop:
                            for elem in app_xml.findall('.//ep:ScaleCrop', namespaces=ns):
                                elem.text = "false"

                        # Clean LinksUpToDate
                        if settings.clean_links_up_to_date:
                            for elem in app_xml.findall('.//ep:LinksUpToDate', namespaces=ns):
                                elem.text = "false"

                        # Clean SharedDoc
                        if settings.clean_shared_doc:
                            for elem in app_xml.findall('.//ep:SharedDoc', namespaces=ns):
                                elem.text = "false"

                        # Clean HyperlinksChanged
                        if settings.clean_hyperlinks_changed:
                            for elem in app_xml.findall('.//ep:HyperlinksChanged', namespaces=ns):
                                elem.text = "false"

                        # Write back the modified XML
                        app_part._blob = etree.tostring(app_xml, encoding='UTF-8', xml_declaration=True)
                        break
        except Exception as e:
            # Log but don't fail - app.xml cleaning is best-effort
            print(f"[MARCUT] Warning: app.xml cleaning failed: {e}")

        # 4. Clean document settings (GUID, docVars, language, forms)
        try:
            doc_settings = self.doc.settings.element
            if settings.clean_document_guid:
                for el in list(doc_settings.iter(qn('w14:docId'))):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)
            if settings.clean_document_variables:
                doc_vars = doc_settings.find(qn('w:docVars'))
                if doc_vars is not None:
                    doc_settings.remove(doc_vars)
            if settings.clean_fast_save_data:
                for tag in (qn('w:savePreviewPicture'), qn('w:saveThroughXslt')):
                    el = doc_settings.find(tag)
                    if el is not None:
                        doc_settings.remove(el)
            if settings.clean_mail_merge:
                mail_merge = doc_settings.find(qn('w:mailMerge'))
                if mail_merge is not None:
                    doc_settings.remove(mail_merge)
            if settings.clean_rsids:
                rsids = doc_settings.find(qn('w:rsids'))
                if rsids is not None:
                    doc_settings.remove(rsids)
        except Exception as exc:
            self._append_warning(
                "DOC_SETTINGS_CLEAN_FAILED",
                "Document settings cleanup failed.",
                str(exc),
            )

        if settings.clean_mail_merge:
            try:
                self._convert_mail_merge_fields()
            except Exception as exc:
                self._append_warning(
                    "MAIL_MERGE_FIELDS_CLEAN_FAILED",
                    "Mail merge field cleanup failed.",
                    str(exc),
                )

        if settings.clean_data_bindings:
            try:
                self._remove_data_bindings()
            except Exception as exc:
                self._append_warning(
                    "DATA_BINDINGS_CLEAN_FAILED",
                    "Data binding cleanup failed.",
                    str(exc),
                )

        if settings.clean_hidden_text:
            try:
                self._remove_hidden_text()
            except Exception as exc:
                self._append_warning(
                    "HIDDEN_TEXT_CLEAN_FAILED",
                    "Hidden text cleanup failed.",
                    str(exc),
                )

        if settings.clean_invisible_objects:
            try:
                self._remove_invisible_objects()
            except Exception as exc:
                self._append_warning(
                    "INVISIBLE_OBJECTS_CLEAN_FAILED",
                    "Invisible object cleanup failed.",
                    str(exc),
                )

        if settings.clean_ink_annotations:
            try:
                self._remove_ink_annotations()
            except Exception as exc:
                self._append_warning(
                    "INK_ANNOTATIONS_CLEAN_FAILED",
                    "Ink annotation cleanup failed.",
                    str(exc),
                )

        if settings.clean_watermarks:
            try:
                self._remove_watermarks()
            except Exception as exc:
                self._append_warning(
                    "WATERMARK_CLEAN_FAILED",
                    "Watermark cleanup failed.",
                    str(exc),
                )

        if settings.clean_headers_footers:
            try:
                self._remove_headers_footers()
            except Exception as exc:
                self._append_warning(
                    "HEADERS_FOOTERS_CLEAN_FAILED",
                    "Header/footer cleanup failed.",
                    str(exc),
                )

        if settings.clean_alt_text:
            try:
                for root in self._iter_part_elements():
                    for el in root.iter():
                        if el.tag == '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr':
                            if 'descr' in el.attrib:
                                el.attrib['descr'] = ""
                            if 'title' in el.attrib:
                                el.attrib['title'] = ""
            except Exception as exc:
                self._append_warning(
                    "ALT_TEXT_CLEAN_FAILED",
                    "Alt-text cleanup failed.",
                    str(exc),
                )

        if settings.clean_language_settings:
            try:
                for root in self._iter_part_elements():
                    for el in list(root.iter(qn('w:lang'))):
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)
            except Exception as exc:
                self._append_warning(
                    "LANGUAGE_SETTINGS_CLEAN_FAILED",
                    "Language settings cleanup failed.",
                    str(exc),
                )

        if settings.clean_form_defaults:
            try:
                for root in self._iter_part_elements():
                    for tag in (qn('w:default'), qn('w:result')):
                        for el in list(root.iter(tag)):
                            parent = el.getparent()
                            if parent is not None:
                                parent.remove(el)
            except Exception as exc:
                self._append_warning(
                    "FORM_DEFAULTS_CLEAN_FAILED",
                    "Form-default cleanup failed.",
                    str(exc),
                )

        if settings.clean_hyperlink_urls:
            try:
                self._unlink_hyperlinks()
            except Exception as exc:
                self._append_warning(
                    "HYPERLINK_UNLINK_FAILED",
                    "Hyperlink unlinking failed during metadata cleanup.",
                    str(exc),
                )

        # Store settings for potential later use
        self._metadata_settings = settings
