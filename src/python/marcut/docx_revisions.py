from __future__ import annotations

import io
import re
import zipfile
from typing import Dict, Optional, Tuple

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

REVISION_DROP_TAGS = {
    f"{{{WORD_NS}}}del",
    f"{{{WORD_NS}}}moveFrom",
}
REVISION_STRIP_TAGS = {
    f"{{{WORD_NS}}}ins",
    f"{{{WORD_NS}}}moveTo",
}
REVISION_MARKER_TAGS = {
    f"{{{WORD_NS}}}moveFromRangeStart",
    f"{{{WORD_NS}}}moveFromRangeEnd",
    f"{{{WORD_NS}}}moveToRangeStart",
    f"{{{WORD_NS}}}moveToRangeEnd",
    # Formatting revisions
    f"{{{WORD_NS}}}rPrChange",
    f"{{{WORD_NS}}}pPrChange",
    f"{{{WORD_NS}}}sectPrChange",
    f"{{{WORD_NS}}}tblPrChange",
    f"{{{WORD_NS}}}tblGridChange",
    f"{{{WORD_NS}}}tcPrChange",
}

REVISION_PART_NAMES = {
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/comments.xml",
}
REVISION_PART_PATTERNS = (
    re.compile(r"^word/header\d+\.xml$"),
    re.compile(r"^word/footer\d+\.xml$"),
)


class DocxRevisionError(RuntimeError):
    pass


def _is_revision_part(name: str) -> bool:
    res = False
    if name in REVISION_PART_NAMES:
        res = True
    elif any(pattern.match(name) for pattern in REVISION_PART_PATTERNS):
        res = True
    return res


def _safe_fromstring(xml_bytes: bytes):
    """Safe XML parsing that disables entity resolution to prevent XXE attacks."""
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False)
    return etree.fromstring(xml_bytes, parser)


def accept_revisions_in_xml_bytes(xml_bytes: bytes) -> Tuple[bytes, bool]:
    from lxml import etree

    try:
        root = _safe_fromstring(xml_bytes)
    except etree.XMLSyntaxError as exc:
        raise DocxRevisionError("Malformed WordprocessingML in revision part") from exc

    has_revisions = False
    for node in root.iter():
        if (
            node.tag in REVISION_DROP_TAGS
            or node.tag in REVISION_STRIP_TAGS
            or node.tag in REVISION_MARKER_TAGS
        ):
            has_revisions = True
            break

    if not has_revisions:
        return xml_bytes, False

    # Smart cleanup: Detect and remove "Zombie Paragraphs"
    metadata_tags = {
        f"{{{WORD_NS}}}pPr",
        f"{{{WORD_NS}}}proofErr",
        f"{{{WORD_NS}}}bookmarkStart",
        f"{{{WORD_NS}}}bookmarkEnd",
        f"{{{WORD_NS}}}commentRangeStart",
        f"{{{WORD_NS}}}commentRangeEnd",
    }
    
    zombie_paragraphs = []
    # Identify zombies
    for p in root.iter(f"{{{WORD_NS}}}p"):
        has_rev_content = False
        has_real_content = False
        
        for child in p:
            if child.tag in metadata_tags:
                continue
            
            if child.tag in REVISION_DROP_TAGS or child.tag in REVISION_MARKER_TAGS:
                has_rev_content = True
            else:
                has_real_content = True
                break
        
        if has_rev_content and not has_real_content:
            zombie_paragraphs.append(p)

    if zombie_paragraphs:
        for p in zombie_paragraphs:
            parent = p.getparent()
            if parent is not None:
                parent.remove(p)

    # Heuristic Spacing Injection: Prevent "WordAWordB" scars
    count_injected = 0
    
    def _get_nearest_text_node(start_node, direction="prev"):
        """
        Walk siblings in direction ('prev' or 'next') skipping revisions/metadata
        to find the nearest w:r containing w:t.
        Returns (node, text_content).
        """
        curr = start_node
        while True:
            if direction == "prev":
                curr = curr.getprevious()
            else:
                curr = curr.getnext()
            
            if curr is None:
                return None, ""
            
            # Skip ignored tags and other revisions
            if (curr.tag in REVISION_DROP_TAGS or 
                curr.tag in REVISION_MARKER_TAGS or 
                curr.tag in metadata_tags):
                continue
            
            # Found a run?
            if curr.tag == f"{{{WORD_NS}}}r":
                # Check for text inside
                ts = list(curr.iter(f"{{{WORD_NS}}}t"))
                if ts:
                    # For prev, we want the LAST text node. For next, the FIRST.
                    target = ts[-1] if direction == "prev" else ts[0]
                    return target, target.text or ""
            
            # If we hit a hard break type tag (p, tbl), stop.
            if curr.tag == f"{{{WORD_NS}}}p" or curr.tag == f"{{{WORD_NS}}}tbl":
                 return None, ""
            
            if curr.tag != f"{{{WORD_NS}}}r":
                 return None, ""
        return None, ""

    for node in root.iter():
        if node.tag in REVISION_DROP_TAGS:
            # Check content of deletion for separator
            deleted_text = "".join(node.itertext())
            has_separator = any(c.isspace() for c in deleted_text)
            
            if has_separator:
                # Find preceding text
                prev_text_node, prev_text = _get_nearest_text_node(node, "prev")
                
                # Find succeeding text
                next_text_node, next_text = _get_nearest_text_node(node, "next")
                
                # Check boundaries
                if prev_text_node is not None and next_text_node is not None:
                    if prev_text and next_text: 
                        # Check: Prev doesn't end in space AND Next doesn't start with space
                        if not prev_text[-1].isspace() and not next_text[0].isspace():
                            prev_text_node.text = prev_text + " "
                            count_injected += 1

    etree.strip_elements(root, *REVISION_DROP_TAGS, *REVISION_MARKER_TAGS, with_tail=True)
    etree.strip_tags(root, *REVISION_STRIP_TAGS)

    # Spacing Scars Fix: Normalize Whitespace
    count_spaced_nodes = 0
    for t_node in root.iter(f"{{{WORD_NS}}}t"):
        if t_node.text and "  " in t_node.text:
            original = t_node.text
            normalized = re.sub(r'[ \t]{2,}', ' ', original)
            if normalized != original:
                t_node.text = normalized
                count_spaced_nodes += 1
    
    cleaned = etree.tostring(root, xml_declaration=True, encoding="UTF-8")
    return cleaned, True


def accept_revisions_in_docx_bytes(input_path: str, debug: bool = False) -> Tuple[Optional[bytes], bool]:
    try:
        # Check lxml availability early
        try:
            import lxml.etree
        except ImportError:
            return None, False

        with zipfile.ZipFile(input_path, "r") as zin:
            revision_parts = [name for name in zin.namelist() if _is_revision_part(name)]
            if not revision_parts:
                return None, False

            updated_parts: Dict[str, bytes] = {}
            for name in revision_parts:
                data = zin.read(name)
                try:
                    cleaned, changed = accept_revisions_in_xml_bytes(data)
                except DocxRevisionError as exc:
                    raise DocxRevisionError(f"Revision XML parse failed in {name}") from exc
                if changed:
                    updated_parts[name] = cleaned

            if not updated_parts:
                return None, False

            out = io.BytesIO()
            with zipfile.ZipFile(out, "w") as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename in updated_parts:
                        data = updated_parts[item.filename]
                    zout.writestr(item, data)

            return out.getvalue(), True
    except zipfile.BadZipFile as exc:
        raise DocxRevisionError("Invalid DOCX container (ZIP) for revision processing") from exc
    except OSError as exc:
        raise DocxRevisionError("Failed to read DOCX for revision processing") from exc
    except DocxRevisionError:
        raise
    except Exception as exc:
        raise DocxRevisionError(f"Unexpected failure while accepting track changes: {exc}") from exc
