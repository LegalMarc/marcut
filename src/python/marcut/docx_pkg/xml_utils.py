"""XML parsing helpers extracted from ``marcut.docx_io``.

Slice 2 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Moved verbatim: ``_safe_fromstring()`` is the ``lxml`` parser
configured with ``resolve_entities=False`` (XXE hardening) used by nearly
every other section of the module. ``marcut.docx_io`` re-exports this name
for backward compatibility with existing ``from .docx_io import ...`` call
sites.
"""


def _safe_fromstring(xml_bytes: bytes):
    """Safe XML parsing that disables entity resolution."""
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False)
    return etree.fromstring(xml_bytes, parser)
