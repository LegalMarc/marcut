"""Backward-compatibility shim for the pre-split ``marcut.docx_io`` module.

The docx_io package split (docs/design/docx_io_package_split.md) is now
complete across five slices, each landed as its own PR:

  1. `docx_pkg/settings.py`   -- CLI/settings configuration surface (#72)
  2. `docx_pkg/xml_utils.py`  -- `_safe_fromstring()` (#73)
  3. `docx_pkg/zip_postprocess.py` -- `_rewrite_docx_zip()` (#74)
  4. `docx_pkg/scan.py`       -- document scanning/indexing (`DocumentIndex`) (#75)
  5. `docx_pkg/hardening.py` (`MetadataHardener`) + `docx_pkg/revision_writer.py`
     (`RevisionWriter`) + `docx_pkg/document.py` (`DocxMap` coordinator) (#76)

This module now re-exports the full public surface from `marcut.docx_pkg`
so any lingering `from .docx_io import ...` reference keeps working during
a deprecation window. New code should import from `marcut.docx_pkg`
directly (`pipeline.py`/`cli.py` already do).
"""

from .docx_pkg.settings import (  # noqa: F401
    CLI_ARG_PAIRS,
    CLI_ARG_MAP,
    CLI_CLEAN_ARG_PAIRS,
    CLI_CLEAN_ARG_MAP,
    FIELD_TO_CLI,
    _normalize_metadata_field_key,
    MetadataCleaningSettings,
)

from .docx_pkg.xml_utils import _safe_fromstring  # noqa: F401

from .docx_pkg.zip_postprocess import rewrite_docx_zip as _rewrite_docx_zip_impl  # noqa: F401

from .docx_pkg.scan import DocumentIndex  # noqa: F401

from .docx_pkg.hardening import MetadataHardener  # noqa: F401

from .docx_pkg.revision_writer import RevisionWriter  # noqa: F401

from .docx_pkg.document import DocxMap  # noqa: F401
