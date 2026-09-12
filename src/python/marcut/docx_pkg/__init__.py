"""Package split of ``marcut.docx_io`` (see docs/design/docx_io_package_split.md).

Named ``docx_pkg`` rather than ``docx`` to avoid sitting next to the
third-party ``python-docx`` import (``from docx import Document``) used
throughout the sibling ``docx_io`` module -- a same-named sibling package is
technically safe under Python 3 absolute imports, but it is a readability
footgun for anyone skimming import lines, so this slice deliberately picks a
less collision-prone name. Apply this same name consistently in the later
slices of the split.

Deliberately empty otherwise: the design doc's Section 2 layout calls for
this file to re-export ``DocxMap``/``MetadataCleaningSettings``/the
``CLI_ARG_*`` surface, but doing so here would import ``.document`` (and
transitively ``python-docx``/``lxml``) as a side effect of importing this
*package*, at all -- breaking the Section 2 invariant that
``marcut.docx_pkg.settings`` (and only it) stays importable without those
heavy dependencies
(``tests/test_docx_io.py::TestSettingsModuleBoundary::test_settings_imports_without_docx_lxml_zipfile``,
which runs in a subprocess specifically to catch this). Import from the
submodules directly instead (``from marcut.docx_pkg.document import
DocxMap``, ``from marcut.docx_pkg.settings import MetadataCleaningSettings``
-- the pattern ``pipeline.py``/``cli.py`` already use), or via
``marcut.docx_io``'s backward-compatibility shim.
"""
