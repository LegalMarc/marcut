from lxml import etree

from marcut.docx_revisions import WORD_NS, accept_revisions_in_xml_bytes


def _text_content(root):
    parts = []
    for node in root.findall(f".//{{{WORD_NS}}}t"):
        if node.text:
            parts.append(node.text)
    return "".join(parts)


def test_accept_revisions_strips_ins_del():
    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:t>Keep </w:t></w:r>
      <w:ins w:id="1"><w:r><w:t>Added</w:t></w:r></w:ins>
      <w:del w:id="2"><w:r><w:delText>Removed</w:delText></w:r></w:del>
      <w:r><w:t> End</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

    cleaned, changed = accept_revisions_in_xml_bytes(xml_bytes)
    assert changed is True

    root = etree.fromstring(cleaned)
    assert root.findall(f".//{{{WORD_NS}}}ins") == []
    assert root.findall(f".//{{{WORD_NS}}}del") == []
    assert root.findall(f".//{{{WORD_NS}}}moveFrom") == []
    assert root.findall(f".//{{{WORD_NS}}}moveTo") == []

    text = _text_content(root)
    assert "Added" in text
    assert "Removed" not in text


def test_accept_revisions_strips_move_ranges():
    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:r><w:t>Prefix </w:t></w:r>
      <w:moveFromRangeStart w:id="5"/>
      <w:moveFrom>
        <w:r><w:t>Old</w:t></w:r>
      </w:moveFrom>
      <w:moveFromRangeEnd w:id="5"/>
      <w:moveToRangeStart w:id="5"/>
      <w:moveTo>
        <w:r><w:t>New</w:t></w:r>
      </w:moveTo>
      <w:moveToRangeEnd w:id="5"/>
      <w:r><w:t> Suffix</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""

    cleaned, changed = accept_revisions_in_xml_bytes(xml_bytes)
    assert changed is True

    root = etree.fromstring(cleaned)
    assert root.findall(f".//{{{WORD_NS}}}moveFrom") == []
    assert root.findall(f".//{{{WORD_NS}}}moveTo") == []
    assert root.findall(f".//{{{WORD_NS}}}moveFromRangeStart") == []
    assert root.findall(f".//{{{WORD_NS}}}moveFromRangeEnd") == []
    assert root.findall(f".//{{{WORD_NS}}}moveToRangeStart") == []
    assert root.findall(f".//{{{WORD_NS}}}moveToRangeEnd") == []

    text = _text_content(root)
    assert "Old" not in text
    assert "New" in text


def test_accept_revisions_noop_when_no_revisions():
    xml_bytes = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Plain text</w:t></w:r></w:p>
  </w:body>
</w:document>
"""

    cleaned, changed = accept_revisions_in_xml_bytes(xml_bytes)
    assert changed is False
    assert cleaned == xml_bytes
