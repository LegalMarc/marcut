"""``DocxMap`` -- the thin coordinator, extracted from ``marcut.docx_io``.

Slice 5 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4) -- the final slice. ``DocxMap`` composes:

  - ``DocumentIndex`` (``scan.py``, Slice 4) for the flat ``.text``/
    ``.index``/``.detached_parts`` character-offset index.
  - ``MetadataHardener`` (``hardening.py``) for ``harden_document()``/
    ``scrub_metadata()`` and their private helpers.
  - ``RevisionWriter`` (``revision_writer.py``) for ``apply_replacements()``
    and track-changes authoring.

Per the design doc, ``_iter_part_elements``/``_iter_part_elements_with_parts``
stay one method owned by ``DocumentIndex``; ``MetadataHardener`` and
``RevisionWriter`` receive it as an injected callable rather than a
duplicated implementation. ``DocxMap`` itself keeps thin delegating methods
for ``_iter_part_elements``/``_iter_part_elements_with_parts`` (Slice 4
behavior, preserved) and for ``_comment_visibility_map`` (called directly
in tests), plus its full existing public method surface --
``load``/``load_accepting_revisions``/``save``/``harden_document``/
``scrub_metadata``/``apply_replacements``/``.text``/``.index``/``.warnings``
-- unchanged, so ``pipeline.py`` and ``cli.py`` need no call-site changes
beyond the import path.

The ``_metadata_settings`` -> ``save()`` order-dependency contract
(docs/design/docx_io_package_split.md §3.2 item 5, pinned by
``tests/test_docx_io_characterization.py::TestSaveHardeningOrderDependency``)
is preserved exactly: ``scrub_metadata()`` delegates to
``MetadataHardener.scrub_metadata()`` (which sets ``_metadata_settings`` on
itself, same as the pre-split code did on ``self``), then copies that value
onto ``self`` here -- so ``hasattr(dm, "_metadata_settings")`` stays False
until ``scrub_metadata()`` has actually run, exactly as before, and
``_postprocess_zip()``/``save()``/``_rewrite_docx_zip`` are untouched thin
methods living directly on this class as they did pre-split.
"""

from io import BytesIO
from typing import Any, Dict, Iterable, List, Optional, Tuple

from docx import Document

from .hardening import MetadataHardener
from .revision_writer import RevisionWriter
from .scan import DocumentIndex
from .settings import MetadataCleaningSettings
from .zip_postprocess import rewrite_docx_zip as _rewrite_docx_zip_impl


class DocxMap:
    def __init__(self, doc: Document, author_name: str = "Marcut"):
        self.doc = doc
        self._author_name = author_name
        self.warnings: List[Dict[str, Any]] = []
        self._index = DocumentIndex(self.doc, self.warnings)
        self.text = self._index.text
        self.index = self._index.index
        self.detached_parts = self._index.detached_parts # Track pars that need manual blob update
        self._hardening = MetadataHardener(
            self.doc, self.warnings, self._index._iter_part_elements
        )
        self._revisions = RevisionWriter(
            self.doc,
            self.index,
            self._index._iter_part_elements_with_parts,
            self.warnings,
            self.author_name,
        )

    @property
    def author_name(self) -> str:
        return self._author_name

    @author_name.setter
    def author_name(self, value: str) -> None:
        """Live-forwarded to ``RevisionWriter`` so a post-construction
        assignment (as ``pipeline.py`` does after
        ``load_accepting_revisions()``) still controls the ``w:author``
        stamped on emitted ``w:ins``/``w:del`` elements -- ``RevisionWriter``
        was constructed with a copy of ``author_name``, not a live
        reference, so it must be updated here too."""
        self._author_name = value
        revisions = getattr(self, "_revisions", None)
        if revisions is not None:
            revisions.author_name = value

    def _append_warning(self, code: str, message: str, details: Optional[str] = None) -> None:
        warning: Dict[str, Any] = {"code": code, "message": message}
        if details:
            warning["details"] = details
        self.warnings.append(warning)

    @staticmethod
    def load(path: str) -> "DocxMap":
        return DocxMap(Document(path))

    @staticmethod
    def load_accepting_revisions(path: str, debug: bool = False) -> "DocxMap":
        from ..docx_revisions import accept_revisions_in_docx_bytes

        docx_bytes, changed = accept_revisions_in_docx_bytes(path, debug=debug)
        if not changed or docx_bytes is None:
            return DocxMap.load(path)
        return DocxMap(Document(BytesIO(docx_bytes)))

    def save(self, path: str):
        # Flush detached parts back to blob before saving
        from lxml import etree
        for part, root in self.detached_parts:
            # Manually update the blob because python-docx treats this as a generic Part
            # Ensure proper XML declaration
            part._blob = etree.tostring(root, encoding='UTF-8', xml_declaration=True)

        self.doc.save(path)
        self._postprocess_zip(path)

    def _postprocess_zip(self, path: str):
        settings = getattr(self, "_metadata_settings", None)
        if settings is None:
            return
        try:
            self._rewrite_docx_zip(path, settings)
        except (OSError, MemoryError):
            raise
        except Exception as exc:
            # Best-effort hardening; don't fail save on post-processing errors.
            self._append_warning(
                "POSTPROCESS_ZIP_FAILED",
                "Post-save ZIP hardening encountered an error.",
                str(exc),
            )

    def _rewrite_docx_zip(self, path: str, settings: MetadataCleaningSettings):
        """Raw ZIP/XML post-processing pass, extracted to
        marcut/docx_pkg/zip_postprocess.py (docx_io package split, Slice 3
        -- see docs/design/docx_io_package_split.md). Kept as a DocxMap
        method (rather than removed outright) so existing call sites --
        including tests that call it unbound via
        ``DocxMap._rewrite_docx_zip(None, path, settings)`` -- keep working
        unchanged; it does not use ``self``.
        """
        _rewrite_docx_zip_impl(path, settings)

    def _iter_part_elements(self) -> Iterable[Any]:
        """Extracted to marcut/docx_pkg/scan.py (docx_io package split,
        Slice 4 -- see docs/design/docx_io_package_split.md), owned by
        `DocumentIndex`. Kept as a thin delegating `DocxMap` method for
        backward compatibility (the hardening/revision-writing code now in
        `hardening.py`/`revision_writer.py` calls `DocumentIndex`'s method
        directly, injected at construction time -- see `__init__` above).
        """
        return self._index._iter_part_elements()

    def _iter_part_elements_with_parts(self) -> Iterable[Tuple[Any, Any]]:
        """See `_iter_part_elements` above -- same delegation rationale."""
        return self._index._iter_part_elements_with_parts()

    def _comment_visibility_map(self) -> Dict[str, str]:
        """Extracted to marcut/docx_pkg/hardening.py (docx_io package
        split, Slice 5 -- see docs/design/docx_io_package_split.md), owned
        by `MetadataHardener`. Kept as a thin delegating `DocxMap` method
        since it is called directly in tests
        (tests/test_docx_io_characterization.py::TestCommentVisibilityMap).
        """
        return self._hardening._comment_visibility_map()

    def harden_document(
        self,
        scrub_all_images: bool = False,
        settings: Optional[MetadataCleaningSettings] = None,
    ):
        """Extracted to marcut/docx_pkg/hardening.py (docx_io package
        split, Slice 5 -- see docs/design/docx_io_package_split.md), owned
        by `MetadataHardener`. Kept as a thin delegating `DocxMap` method
        so the public surface is unchanged."""
        return self._hardening.harden_document(scrub_all_images, settings)

    def scrub_metadata(self, settings: Optional[MetadataCleaningSettings] = None):
        """Extracted to marcut/docx_pkg/hardening.py (docx_io package
        split, Slice 5 -- see docs/design/docx_io_package_split.md), owned
        by `MetadataHardener`. Kept as a thin delegating `DocxMap` method;
        `_metadata_settings` is copied back onto `self` after delegating so
        the `_metadata_settings` -> `save()` order-dependency contract
        (docs/design/docx_io_package_split.md §3.2 item 5) is preserved
        exactly -- `hasattr(dm, "_metadata_settings")` is False until this
        method has actually run, same as pre-split.
        """
        self._hardening.scrub_metadata(settings)
        self._metadata_settings = self._hardening._metadata_settings

    def apply_replacements(self, spans: List[Dict[str, Any]], track_changes: bool = True):
        """Extracted to marcut/docx_pkg/revision_writer.py (docx_io
        package split, Slice 5 -- see
        docs/design/docx_io_package_split.md), owned by `RevisionWriter`.
        Kept as a thin delegating `DocxMap` method so the public surface is
        unchanged."""
        return self._revisions.apply_replacements(spans, track_changes)
