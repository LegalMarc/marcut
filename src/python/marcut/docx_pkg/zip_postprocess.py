"""Raw ZIP/XML post-processing pass ("hardening at the package level").

Slice 3 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Extracted from ``DocxMap._rewrite_docx_zip`` in ``docx_io.py``:
relationship-target sanitization, JPEG/PNG binary metadata stripping,
namespace/element pruning, custom-style renaming, chart-label redaction,
``.rels``/``[Content_Types].xml`` rewriting, and the orphan-detection +
ZIP-rewrite loop.

This module operates only on raw bytes / ``zipfile.ZipFile`` / ``lxml.etree``
-- it must never import ``docx.Document``. ``rewrite_docx_zip()`` takes a
file ``path`` and a ``MetadataCleaningSettings`` and mutates the file on
disk; it has no dependency on any ``DocxMap`` instance state.

The ~20 helper closures the original method nested inside itself are
promoted here to module-level functions taking explicit parameters
(``settings``, ``removed_parts``, the style-rename maps, ...) instead of
closing over method-local state.
"""

import os
import posixpath
import re
import zipfile
from typing import Dict, Iterable, Tuple

from docx.oxml.ns import qn
from lxml import etree

from .settings import MetadataCleaningSettings
from .xml_utils import _safe_fromstring

STANDARD_REL_PREFIXES = (
    "http://schemas.openxmlformats.org/",
    "http://schemas.microsoft.com/office/",
)

KNOWN_NAMESPACES = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "http://purl.org/dc/elements/1.1/",
    "http://purl.org/dc/terms/",
    "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "http://www.w3.org/XML/1998/namespace",
    "http://www.w3.org/2001/XMLSchema-instance",
}
KNOWN_NAMESPACE_PREFIXES = (
    "http://schemas.microsoft.com/office/word/",
    "http://schemas.microsoft.com/office/",
)


def _rels_source_dir(rels_path: str) -> str:
    if rels_path == "_rels/.rels":
        return ""
    if "/_rels/" not in rels_path:
        return posixpath.dirname(rels_path)
    source_path = rels_path.replace("/_rels/", "/")
    if source_path.endswith(".rels"):
        source_path = source_path[:-5]
    return posixpath.dirname(source_path)


def _resolve_target(rels_path: str, target: str) -> str:
    base_dir = _rels_source_dir(rels_path)
    return posixpath.normpath(posixpath.join(base_dir, target))


def _is_unc_path(target: str) -> bool:
    return target.startswith("\\\\") or (target.startswith("//") and not target.startswith("http"))


def _is_user_path(target: str) -> bool:
    for sep in ("\\", "/"):
        if f"{sep}Users{sep}" in target or f"{sep}home{sep}" in target:
            return True
    return "%USERPROFILE%" in target


def _is_file_path(target: str) -> bool:
    if target.startswith("file:"):
        return True
    if re.match(r"^[A-Za-z]:[\\\\/]", target):
        return True
    return target.startswith("/") or target.startswith("./") or target.startswith("../")


def _is_internal_url(target: str) -> bool:
    if not target.startswith(("http://", "https://")):
        return False
    try:
        host = target.split("//", 1)[1].split("/", 1)[0]
    except Exception:
        return False
    if host.startswith(("127.", "10.", "192.168.", "169.254.")):
        return True
    if host.endswith(".local") or host.endswith(".lan"):
        return True
    return "." not in host


def _sanitize_target(target: str, r_type: str, settings: MetadataCleaningSettings) -> str:
    if settings.clean_ole_sources and "oleObject" in r_type:
        return "urn:marcut:redacted"
    if settings.clean_unc_paths and _is_unc_path(target):
        return "urn:marcut:redacted"
    if settings.clean_user_paths and _is_user_path(target):
        return "urn:marcut:redacted"
    if settings.clean_internal_urls and _is_internal_url(target):
        return "urn:marcut:redacted"
    if settings.clean_external_links and _is_file_path(target):
        return "urn:marcut:redacted"
    return target


def _strip_jpeg_metadata(data: bytes) -> Tuple[bytes, bool]:
    if not data.startswith(b"\xFF\xD8"):
        return data, False
    out = bytearray(b"\xFF\xD8")
    i = 2
    changed = False
    while i + 1 < len(data):
        if data[i] != 0xFF:
            out.extend(data[i:])
            break
        # Skip fill bytes
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker == 0xDA:  # SOS
            out.extend(b"\xFF\xDA")
            out.extend(data[i:])
            break
        if i + 1 >= len(data):
            break
        length = (data[i] << 8) + data[i + 1]
        segment_end = min(i + length, len(data))
        if marker in (0xE1, 0xED):  # APP1/APP13
            changed = True
        else:
            out.extend(b"\xFF" + bytes([marker]))
            out.extend(data[i:segment_end])
        i = segment_end
    return bytes(out), changed


def _strip_png_metadata(data: bytes) -> Tuple[bytes, bool]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, False
    out = bytearray(data[:8])
    i = 8
    changed = False
    while i + 8 <= len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        chunk_type = data[i + 4:i + 8]
        chunk_end = i + 12 + length
        chunk = data[i:chunk_end]
        if chunk_type in (b"tEXt", b"iTXt", b"zTXt", b"eXIf"):
            changed = True
        else:
            out.extend(chunk)
        i = chunk_end
    return bytes(out), changed


def _remove_lang_elements(root: etree._Element) -> bool:
    changed = False
    for el in list(root.iter()):
        if el.tag == qn("w:lang"):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                changed = True
    return changed


def _strip_form_defaults(root: etree._Element) -> bool:
    changed = False
    for tag in (qn("w:default"), qn("w:result")):
        for el in list(root.iter(tag)):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                changed = True
    return changed


def _strip_alternate_content(root: etree._Element) -> bool:
    changed = False
    ns = {"mc": "http://schemas.openxmlformats.org/markup-compatibility/2006"}
    for ac in list(root.findall(".//mc:AlternateContent", namespaces=ns)):
        parent = ac.getparent()
        if parent is None:
            continue
        fallback = ac.find("mc:Fallback", namespaces=ns)
        if fallback is not None:
            insert_index = parent.index(ac)
            for child in list(fallback):
                parent.insert(insert_index, child)
                insert_index += 1
        parent.remove(ac)
        changed = True
    return changed


def _strip_nonstandard_elements(root: etree._Element, *, remove_unknown: bool, remove_ms: bool) -> bool:
    if not remove_unknown and not remove_ms:
        return False
    changed = False
    for el in list(root.iter()):
        if el.attrib:
            for attr_name in list(el.attrib):
                if "}" not in attr_name:
                    continue
                ns = attr_name.split("}", 1)[0][1:]
                if ns in KNOWN_NAMESPACES:
                    continue
                is_ms = any(ns.startswith(prefix) for prefix in KNOWN_NAMESPACE_PREFIXES)
                if (is_ms and remove_ms) or ((not is_ms) and remove_unknown):
                    del el.attrib[attr_name]
                    changed = True
        if "}" not in el.tag:
            continue
        ns = el.tag.split("}", 1)[0][1:]
        if ns in KNOWN_NAMESPACES:
            continue
        is_ms = any(ns.startswith(prefix) for prefix in KNOWN_NAMESPACE_PREFIXES)
        if (is_ms and remove_ms) or ((not is_ms) and remove_unknown):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                changed = True
    return changed


def _update_style_references(root: etree._Element, style_map: Dict[str, str]) -> bool:
    changed = False
    tags = [qn("w:pStyle"), qn("w:rStyle"), qn("w:tblStyle"), qn("w:basedOn"), qn("w:link"), qn("w:next")]
    for tag in tags:
        for el in root.iter(tag):
            val = el.get(qn("w:val") if ":" in qn("w:val") else "val")
            if val in style_map:
                el.set(qn("w:val"), style_map[val])
                changed = True
    return changed


def _rename_custom_styles(root: etree._Element, style_id_map: Dict[str, str], style_name_map: Dict[str, str]) -> bool:
    changed = False
    idx = 1
    for style in root.findall(".//w:style", namespaces=root.nsmap):
        if style.get(qn("w:customStyle")) != "1":
            continue
        new_name = f"CustomStyle{idx}"
        new_id = f"Style{idx}"

        name_el = style.find("w:name", namespaces=root.nsmap)
        old_name = None
        if name_el is not None:
            old_name = name_el.get(qn("w:val"))
            name_el.set(qn("w:val"), new_name)
            changed = True

        old_id = style.get(qn("w:styleId"))
        style.set(qn("w:styleId"), new_id)
        changed = True

        if old_id:
            style_id_map[old_id] = new_id
        if old_name:
            style_name_map[old_name] = new_name

        aliases = style.find("w:aliases", namespaces=root.nsmap)
        if aliases is not None:
            style.remove(aliases)
            changed = True
        idx += 1
    if style_id_map:
        changed = _update_style_references(root, style_id_map) or changed
    if style_name_map:
        for lsd in root.findall(".//w:lsdException", namespaces=root.nsmap):
            val = lsd.get(qn("w:name"))
            if val in style_name_map:
                lsd.set(qn("w:name"), style_name_map[val])
                changed = True
    return changed


def _clean_chart_labels(root: etree._Element) -> bool:
    changed = False
    for el in root.iter():
        if el.tag.endswith("}v") or el.tag.endswith("}t"):
            if el.text:
                el.text = "[REDACTED]"
                changed = True
    return changed


def _scrub_rels(
    xml_bytes: bytes,
    rels_path: str,
    settings: MetadataCleaningSettings,
    removed_parts: Iterable[str],
) -> Tuple[bytes, bool]:
    root = _safe_fromstring(xml_bytes)
    changed = False
    if rels_path == "_rels/.rels":
        core_type = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
        legacy_core_type = "http://schemas.openxmlformats.org/officedocument/2006/relationships/metadata/core-properties"
        core_rels = [
            rel for rel in list(root)
            if rel.get("Type") in (core_type, legacy_core_type)
        ]
        if core_rels:
            has_correct = any(rel.get("Type") == core_type for rel in core_rels)
            if has_correct:
                for rel in core_rels:
                    if rel.get("Type") == legacy_core_type:
                        root.remove(rel)
                        changed = True
            else:
                primary = core_rels[0]
                primary.set("Type", core_type)
                changed = True
                for rel in core_rels[1:]:
                    root.remove(rel)
                    changed = True
    for rel in list(root):
        r_type = rel.get("Type") or ""
        target = rel.get("Target") or ""
        target_mode = rel.get("TargetMode") or ""
        resolved = _resolve_target(rels_path, target)

        if resolved in removed_parts:
            root.remove(rel)
            changed = True
            continue
        if (settings.clean_custom_properties or settings.clean_custom_xml_parts) and "customXml" in r_type:
            root.remove(rel)
            changed = True
            continue
        if settings.clean_unknown_relationships and not r_type.startswith(STANDARD_REL_PREFIXES):
            root.remove(rel)
            changed = True
            continue
        if settings.clean_digital_signatures and "signature" in r_type:
            root.remove(rel)
            changed = True
            continue
        if settings.clean_printer_settings and "printerSettings" in r_type:
            root.remove(rel)
            changed = True
            continue
        if settings.clean_document_versions and "versions" in r_type:
            root.remove(rel)
            changed = True
            continue
        if settings.clean_ink_annotations and "ink" in r_type:
            root.remove(rel)
            changed = True
            continue
        if settings.clean_headers_footers and ("header" in r_type or "footer" in r_type):
            root.remove(rel)
            changed = True
            continue
        if settings.clean_activex and ("control" in r_type or "activeX" in r_type):
            root.remove(rel)
            changed = True
            continue

        if target_mode == "External":
            sanitized = _sanitize_target(target, r_type, settings)
            if sanitized != target:
                rel.set("Target", sanitized)
                changed = True
    if changed:
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True), True
    return xml_bytes, False


def _update_content_types(xml_bytes: bytes, removed: Iterable[str]) -> Tuple[bytes, bool]:
    root = _safe_fromstring(xml_bytes)
    removed_parts = {f"/{name}" for name in removed}
    changed = False
    for override in list(root.findall("Override")):
        if override.get("PartName") in removed_parts:
            root.remove(override)
            changed = True
    if changed:
        return etree.tostring(root, encoding="UTF-8", xml_declaration=True), True
    return xml_bytes, False


def rewrite_docx_zip(path: str, settings: MetadataCleaningSettings) -> None:
    """Rewrite the DOCX ZIP package at ``path`` in place per ``settings``.

    Raw-bytes/``zipfile``/``lxml`` post-processing pass: relationship-target
    sanitization, image EXIF stripping, namespace/element pruning, custom
    style renaming, chart-label redaction, ``.rels``/``[Content_Types].xml``
    rewriting, and orphaned-part removal. Never touches a ``python-docx``
    ``Document`` object -- ``path`` in, ``path`` out.
    """
    clean_comments_all = settings.clean_review_comments_visible and settings.clean_review_comments_hidden
    style_id_map: Dict[str, str] = {}
    style_name_map: Dict[str, str] = {}

    # NOTE ON MEMORY: the pre-scan passes below (removed-parts / orphan detection,
    # style-ID pre-scan) only ever read small package-internal XML parts (*.rels,
    # [Content_Types].xml, word/styles.xml) — never large binary media — so their
    # memory footprint is bounded regardless of document size. The subsequent
    # transform-and-write pass streams the archive entry-by-entry (read one part,
    # transform if needed, write immediately, discard) instead of buffering every
    # changed part in memory for the lifetime of the rewrite, so peak memory stays
    # O(largest single part) rather than O(total archive size).
    temp_path = path + ".tmp_harden"
    any_change = False
    with zipfile.ZipFile(path, "r") as zin:
        items = zin.infolist()
        last_index = {item.filename: idx for idx, item in enumerate(items)}
        removed_parts = set()
        remove_custom_xml = settings.clean_custom_properties or settings.clean_custom_xml_parts
        for item in items:
            name = item.filename
            if settings.clean_thumbnail and name.startswith("docProps/thumbnail"):
                removed_parts.add(name)
            if settings.clean_custom_properties and name == "docProps/custom.xml":
                removed_parts.add(name)
            if remove_custom_xml and name.startswith("customXml/"):
                removed_parts.add(name)
            if clean_comments_all and name.startswith("word/comments"):
                removed_parts.add(name)
            if settings.clean_ole_objects and name.startswith("word/embeddings/"):
                removed_parts.add(name)
            if settings.clean_activex and (name.startswith("word/activeX/") or name.startswith("word/controls/")):
                removed_parts.add(name)
            if settings.clean_embedded_fonts and name.startswith("word/fonts/"):
                removed_parts.add(name)
            if settings.clean_headers_footers and (name.startswith("word/header") or name.startswith("word/footer")):
                removed_parts.add(name)
            if settings.clean_document_versions and name.startswith("word/versions"):
                removed_parts.add(name)
            if settings.clean_ink_annotations and name.startswith("word/ink"):
                removed_parts.add(name)

        orphaned_parts = set()
        if settings.clean_orphaned_parts:
            referenced_parts = set()
            for item in items:
                name = item.filename
                if not name.endswith(".rels"):
                    continue
                try:
                    data = zin.read(name)
                except Exception:
                    continue
                try:
                    rel_root = _safe_fromstring(data)
                except Exception:
                    continue
                for rel in list(rel_root):
                    r_type = rel.get("Type") or ""
                    target = rel.get("Target") or ""
                    target_mode = rel.get("TargetMode") or ""
                    if settings.clean_unknown_relationships and not r_type.startswith(STANDARD_REL_PREFIXES):
                        continue
                    if (settings.clean_custom_properties or settings.clean_custom_xml_parts) and "customXml" in r_type:
                        continue
                    if settings.clean_digital_signatures and "signature" in r_type:
                        continue
                    if settings.clean_printer_settings and "printerSettings" in r_type:
                        continue
                    if settings.clean_document_versions and "versions" in r_type:
                        continue
                    if settings.clean_ink_annotations and "ink" in r_type:
                        continue
                    if settings.clean_headers_footers and ("header" in r_type or "footer" in r_type):
                        continue
                    if settings.clean_activex and ("control" in r_type or "activeX" in r_type):
                        continue
                    if target_mode == "External" or not target:
                        continue
                    resolved = _resolve_target(name, target).lstrip("/")
                    if resolved in removed_parts:
                        continue
                    referenced_parts.add(resolved)
            for item in items:
                name = item.filename
                if name == "[Content_Types].xml" or name.endswith(".rels"):
                    continue
                if name in removed_parts:
                    continue
                if name not in referenced_parts:
                    orphaned_parts.add(name)
            removed_parts.update(orphaned_parts)

        if removed_parts:
            any_change = True

        # PRE-SCAN Styles to build ID mapping before general file processing
        if settings.clean_style_names:
            try:
                for item in items:
                    if item.filename == "word/styles.xml":
                        data = zin.read(item.filename)
                        root = _safe_fromstring(data)
                        idx = 1
                        for style in root.findall(".//w:style", namespaces=root.nsmap):
                            if style.get(qn("w:customStyle")) == "1":
                                old_id = style.get(qn("w:styleId"))
                                if old_id:
                                    style_id_map[old_id] = f"Style{idx}"
                                idx += 1
                        break
            except Exception:
                pass

        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for idx, item in enumerate(items):
                name = item.filename
                if name in removed_parts:
                    continue
                if idx != last_index.get(name, idx):
                    # Earlier occurrence of a duplicate entry name; only the
                    # last occurrence is kept, so skip reading/writing this one.
                    continue

                data = zin.read(name)

                if name.endswith(".rels"):
                    updated, changed = _scrub_rels(data, name, settings, removed_parts)
                    if changed:
                        any_change = True
                    zout.writestr(item, updated if changed else data)
                    continue

                if name == "[Content_Types].xml":
                    updated, changed = _update_content_types(data, removed_parts)
                    if changed:
                        any_change = True
                    zout.writestr(item, updated if changed else data)
                    continue

                if settings.clean_image_exif and name.startswith("word/media/"):
                    lower = name.lower()
                    if lower.endswith((".jpg", ".jpeg")):
                        updated, changed = _strip_jpeg_metadata(data)
                        if changed:
                            any_change = True
                        zout.writestr(item, updated if changed else data)
                        continue
                    if lower.endswith(".png"):
                        updated, changed = _strip_png_metadata(data)
                        if changed:
                            any_change = True
                        zout.writestr(item, updated if changed else data)
                        continue

                if settings.clean_embedded_fonts and name == "word/fontTable.xml":
                    root = _safe_fromstring(data)
                    changed = False
                    for tag in ("embedRegular", "embedBold", "embedItalic", "embedBoldItalic"):
                        for el in list(root.findall(f".//w:{tag}", namespaces=root.nsmap)):
                            parent = el.getparent()
                            if parent is not None:
                                parent.remove(el)
                                changed = True
                    if changed:
                        data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                        any_change = True
                    zout.writestr(item, data)
                    continue

                if name == "word/styles.xml" and (settings.clean_style_names or settings.clean_language_settings):
                    root = _safe_fromstring(data)
                    changed = False
                    if settings.clean_style_names:
                        changed = _rename_custom_styles(root, style_id_map, style_name_map) or changed
                    if settings.clean_language_settings:
                        changed = _remove_lang_elements(root) or changed
                    if changed:
                        data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                        any_change = True
                    zout.writestr(item, data)
                    continue

                if settings.clean_chart_labels and name.startswith("word/charts/") and name.endswith(".xml"):
                    root = _safe_fromstring(data)
                    if _clean_chart_labels(root):
                        data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                        any_change = True
                    zout.writestr(item, data)
                    continue

                if settings.clean_style_names and name.startswith("word/") and name.endswith(".xml") and name != "word/styles.xml":
                    # Update references in all document parts
                    try:
                        root = _safe_fromstring(data)
                        if _update_style_references(root, style_id_map):
                            data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                            any_change = True
                            # Update data reference so subsequent lang/form cleaners use the new XML
                    except Exception:
                        pass

                if settings.clean_language_settings and name.startswith("word/") and name.endswith(".xml"):
                    try:
                        root = _safe_fromstring(data)
                        if _remove_lang_elements(root):
                            data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                            any_change = True
                    except Exception:
                        pass

                if settings.clean_form_defaults and name.startswith("word/") and name.endswith(".xml"):
                    try:
                        root = _safe_fromstring(data)
                        if _strip_form_defaults(root):
                            data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                            any_change = True
                    except Exception:
                        pass

                if (settings.clean_nonstandard_xml or settings.clean_microsoft_extension_xml or settings.clean_alternate_content) and name.endswith(".xml"):
                    try:
                        root = _safe_fromstring(data)
                        changed = False
                        if settings.clean_alternate_content:
                            changed = _strip_alternate_content(root) or changed
                        if settings.clean_nonstandard_xml or settings.clean_microsoft_extension_xml:
                            changed = _strip_nonstandard_elements(
                                root,
                                remove_unknown=settings.clean_nonstandard_xml,
                                remove_ms=settings.clean_microsoft_extension_xml,
                            ) or changed
                        if changed:
                            data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
                            any_change = True
                    except Exception:
                        pass

                zout.writestr(item, data)

    if not any_change:
        os.remove(temp_path)
        return

    os.replace(temp_path, path)
