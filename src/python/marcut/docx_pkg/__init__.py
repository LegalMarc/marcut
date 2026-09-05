"""Package split of ``marcut.docx_io`` (see docs/design/docx_io_package_split.md).

Named ``docx_pkg`` rather than ``docx`` to avoid sitting next to the
third-party ``python-docx`` import (``from docx import Document``) used
throughout the sibling ``docx_io`` module -- a same-named sibling package is
technically safe under Python 3 absolute imports, but it is a readability
footgun for anyone skimming import lines, so this slice deliberately picks a
less collision-prone name. Apply this same name consistently in the later
slices of the split.
"""
