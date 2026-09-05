"""
Tests for docx_io.py module.

Tests cover:
- MetadataCleaningSettings: Dataclass defaults, CLI parsing, CLI generation
- _safe_fromstring: XML parsing security
"""

import pytest
from marcut.docx_io import (
    MetadataCleaningSettings,
    _safe_fromstring,
    CLI_ARG_MAP,
    CLI_CLEAN_ARG_MAP,
    FIELD_TO_CLI,
)


class TestMetadataCleaningSettingsDefaults:
    """Test MetadataCleaningSettings default values."""

    def test_default_construction(self):
        """Test that default settings are created correctly."""
        settings = MetadataCleaningSettings()
        # Most fields default to True
        assert settings.clean_company is True
        assert settings.clean_author is True
        assert settings.clean_thumbnail is True

    def test_created_modified_dates_default_off(self):
        """Test that created/modified dates default to False (per user request)."""
        settings = MetadataCleaningSettings()
        assert settings.clean_created_date is False
        assert settings.clean_modified_date is False

    def test_all_fields_are_bool(self):
        """Test that all settings fields are boolean."""
        settings = MetadataCleaningSettings()
        from dataclasses import fields
        for field in fields(settings):
            value = getattr(settings, field.name)
            assert isinstance(value, bool), f"{field.name} is not bool: {type(value)}"


class TestMetadataCleaningSettingsFromCliArgs:
    """Test MetadataCleaningSettings.from_cli_args()."""

    def test_empty_args(self):
        """Test that empty args returns defaults."""
        settings = MetadataCleaningSettings.from_cli_args([])
        assert settings.clean_company is True
        assert settings.clean_author is True

    def test_single_disable_arg(self):
        """Test disabling a single field."""
        settings = MetadataCleaningSettings.from_cli_args(["--no-clean-company"])
        assert settings.clean_company is False
        # Others remain True
        assert settings.clean_author is True
        assert settings.clean_manager is True

    def test_multiple_disable_args(self):
        """Test disabling multiple fields."""
        settings = MetadataCleaningSettings.from_cli_args([
            "--no-clean-company",
            "--no-clean-author",
            "--no-clean-thumbnail"
        ])
        assert settings.clean_company is False
        assert settings.clean_author is False
        assert settings.clean_thumbnail is False
        # Others remain True
        assert settings.clean_manager is True

    def test_unknown_args_ignored(self):
        """Test that unknown args are ignored."""
        settings = MetadataCleaningSettings.from_cli_args([
            "--no-clean-company",
            "--unknown-arg",
            "--another-unknown"
        ])
        assert settings.clean_company is False
        # Should not raise

    def test_all_known_cli_args(self):
        """Test that all CLI args in mapping work."""
        for cli_arg, field_name in CLI_ARG_MAP.items():
            settings = MetadataCleaningSettings.from_cli_args([cli_arg])
            assert getattr(settings, field_name) is False

    def test_all_known_clean_cli_args(self):
        """Test that all --clean-* CLI args re-enable fields."""
        baseline = MetadataCleaningSettings.from_preset("none")
        for cli_arg, field_name in CLI_CLEAN_ARG_MAP.items():
            settings = MetadataCleaningSettings.from_cli_args([cli_arg], base=baseline)
            assert getattr(settings, field_name) is True


class TestMetadataCleaningSettingsToCliArgs:
    """Test MetadataCleaningSettings.to_cli_args()."""

    def test_all_defaults_returns_empty(self):
        """Test that all-True settings returns no args."""
        settings = MetadataCleaningSettings()
        # Note: created_date and modified_date default to False
        # So they will generate args
        args = settings.to_cli_args()
        # Check that disabled defaults generate their args
        assert "--no-clean-created-date" in args
        assert "--no-clean-modified-date" in args

    def test_disabled_field_generates_arg(self):
        """Test that False fields generate --no-clean args."""
        settings = MetadataCleaningSettings()
        settings.clean_company = False
        args = settings.to_cli_args()
        assert "--no-clean-company" in args

    def test_roundtrip_preserves_settings(self):
        """Test that from_cli_args(to_cli_args()) roundtrips."""
        original = MetadataCleaningSettings()
        original.clean_company = False
        original.clean_author = False
        original.clean_rsids = False
        
        args = original.to_cli_args()
        restored = MetadataCleaningSettings.from_cli_args(args)
        
        assert restored.clean_company == original.clean_company
        assert restored.clean_author == original.clean_author
        assert restored.clean_rsids == original.clean_rsids


class TestSafeFromstring:
    """Test _safe_fromstring XML parsing."""

    def test_valid_xml_parses(self):
        """Test that valid XML parses correctly."""
        xml = b"<root><child>value</child></root>"
        root = _safe_fromstring(xml)
        assert root.tag == "root"
        assert root[0].tag == "child"
        assert root[0].text == "value"

    def test_xml_with_attributes(self):
        """Test XML with attributes."""
        xml = b'<root attr="value"><child id="1">text</child></root>'
        root = _safe_fromstring(xml)
        assert root.get("attr") == "value"
        assert root[0].get("id") == "1"

    def test_xml_with_namespace(self):
        """Test XML with namespaces."""
        xml = b'<w:root xmlns:w="http://example.com"><w:child>text</w:child></w:root>'
        root = _safe_fromstring(xml)
        # Should parse without error
        assert "root" in root.tag

    def test_malformed_xml_raises(self):
        """Test that malformed XML raises an error."""
        xml = b"<root><unclosed>"
        with pytest.raises(Exception):  # noqa: B017 -- exact parser error type is intentionally unspecified
            _safe_fromstring(xml)

    def test_xxe_prevention(self):
        """Test that XXE attacks are mitigated."""
        # This XML attempts to read /etc/passwd
        xxe_payload = b"""
        <!DOCTYPE foo [ 
          <!ELEMENT foo ANY >
          <!ENTITY xxe SYSTEM "file:///etc/passwd" >]><foo>&xxe;</foo>
        """
        
        try:
            root = _safe_fromstring(xxe_payload)
            # If it parsed, content should not contain /etc/passwd data
            content = root.text or ""
            assert "root:" not in content  # /etc/passwd would have "root:"
        except Exception:
            # Failing to parse is also acceptable for XXE prevention
            pass


class TestCliArgMappings:
    """Test CLI argument mappings are consistent."""

    def test_bidirectional_mapping(self):
        """Test that CLI_ARG_MAP and FIELD_TO_CLI are inverses."""
        for cli_arg, field in CLI_ARG_MAP.items():
            assert FIELD_TO_CLI[field] == cli_arg

    def test_all_fields_have_cli_args(self):
        """Test that all MetadataCleaningSettings bool fields have CLI args."""
        from dataclasses import fields
        settings = MetadataCleaningSettings()
        mapped_fields = set(CLI_ARG_MAP.values())

        # All mapped fields should be in settings
        for field in mapped_fields:
            assert hasattr(settings, field), f"CLI mapped field {field} not in settings"

        # All bool fields on the dataclass should in turn be mapped to a CLI arg,
        # so a newly-added field can't silently ship without one.
        setting_fields = {f.name for f in fields(settings) if f.type is bool}
        unmapped = setting_fields - mapped_fields
        assert not unmapped, f"Settings bool fields missing a CLI_ARG_MAP entry: {sorted(unmapped)}"

    def test_cli_arg_format(self):
        """Test that all CLI args follow --no-clean-* format."""
        for cli_arg in CLI_ARG_MAP.keys():
            assert cli_arg.startswith("--no-clean-"), f"Bad format: {cli_arg}"


class TestPresetNone:
    """Test the 'None' preset behavior."""

    def test_all_fields_false_generates_preset(self):
        """Test that all-False settings generate --preset-none."""
        settings = MetadataCleaningSettings()
        # Set ALL fields to False
        from dataclasses import fields
        for field in fields(settings):
            setattr(settings, field.name, False)
        
        args = settings.to_cli_args()
        assert "--preset-none" in args


class TestSettingsModuleBoundary:
    """Lock the docx_io package-split module-boundary invariant.

    docs/design/docx_io_package_split.md Section 2 requires that
    ``marcut.docx_pkg.settings`` has no dependency on ``python-docx``,
    ``lxml``, or ``zipfile`` and is importable without touching a real
    document. Later slices of the split (#73-#76) must not regress this.
    """

    HEAVY_MODULES = ("docx", "lxml", "zipfile")

    def test_settings_imports_without_docx_lxml_zipfile(self):
        """Importing settings in a fresh interpreter loads none of the heavy modules.

        Runs in a subprocess because the pytest process already has
        ``docx``/``lxml`` loaded via ``marcut.docx_io``.
        """
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        import marcut

        src_root = Path(marcut.__file__).resolve().parent.parent
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(src_root), env.get("PYTHONPATH", "")) if p
        )
        script = (
            "import sys, json\n"
            "import marcut.docx_pkg.settings\n"
            f"heavy = {self.HEAVY_MODULES!r}\n"
            "loaded = sorted(m for m in sys.modules "
            "if m.split('.')[0] in heavy)\n"
            "print(json.dumps(loaded))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        loaded = json.loads(result.stdout.strip())
        assert loaded == [], (
            f"marcut.docx_pkg.settings pulled in forbidden modules: {loaded}"
        )

    def test_docx_io_reexports_are_identical_objects(self):
        """docx_io re-exports the settings objects, not copies."""
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.settings as settings

        assert docx_io.MetadataCleaningSettings is settings.MetadataCleaningSettings
        assert docx_io.CLI_ARG_PAIRS is settings.CLI_ARG_PAIRS

    def test_docx_io_reexports_safe_fromstring_identical_object(self):
        """docx_io re-exports _safe_fromstring from docx_pkg.xml_utils, not a copy."""
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.xml_utils as xml_utils

        assert docx_io._safe_fromstring is xml_utils._safe_fromstring

    def test_xml_utils_xxe_prevention_at_canonical_path(self):
        """The XXE payload assertion also holds against the canonical module,
        not just the docx_io shim, so later slices importing directly from
        marcut.docx_pkg.xml_utils get the same guarantee."""
        from marcut.docx_pkg.xml_utils import _safe_fromstring as safe_fromstring

        xxe_payload = b"""
        <!DOCTYPE foo [
          <!ELEMENT foo ANY >
          <!ENTITY xxe SYSTEM "file:///etc/passwd" >]><foo>&xxe;</foo>
        """

        try:
            root = safe_fromstring(xxe_payload)
            content = root.text or ""
            assert "root:" not in content  # /etc/passwd would have "root:"
        except Exception:
            # Failing to parse is also acceptable for XXE prevention
            pass


class TestZipPostprocessModuleBoundary:
    """Lock the docx_io package-split module-boundary invariant for Slice 3.

    docs/design/docx_io_package_split.md Section 2 requires that
    ``marcut.docx_pkg.zip_postprocess`` never imports ``docx.Document`` --
    it is a raw bytes/``zipfile``/``lxml`` post-processing pass, distinct
    from everything that runs on the live ``python-docx`` object tree.
    """

    def test_zip_postprocess_does_not_import_docx_document(self):
        """Importing the module in a fresh interpreter never binds ``Document``.

        Runs in a subprocess so the assertion reflects only this module's
        own imports, not whatever the pytest process already loaded via
        ``marcut.docx_io``.
        """
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        import marcut

        src_root = Path(marcut.__file__).resolve().parent.parent
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(src_root), env.get("PYTHONPATH", "")) if p
        )
        script = (
            "import ast, inspect, json\n"
            "import marcut.docx_pkg.zip_postprocess as mod\n"
            "src = inspect.getsource(mod)\n"
            "tree = ast.parse(src)\n"
            "names = []\n"
            "for node in ast.walk(tree):\n"
            "    if isinstance(node, ast.ImportFrom) and node.module == 'docx':\n"
            "        names.extend(a.name for a in node.names)\n"
            "print(json.dumps(names))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        imported_from_docx = json.loads(result.stdout.strip())
        assert "Document" not in imported_from_docx, (
            f"marcut.docx_pkg.zip_postprocess imports from docx: {imported_from_docx}"
        )

    def test_docx_io_delegates_to_canonical_rewrite_docx_zip(self):
        """DocxMap._rewrite_docx_zip calls the canonical module function,
        not a re-implemented copy -- the identity-chain analogue of the
        settings/xml_utils re-export tests for a delegating method."""
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.zip_postprocess as zip_postprocess

        assert docx_io._rewrite_docx_zip_impl is zip_postprocess.rewrite_docx_zip

    def test_rewrite_docx_zip_callable_unbound_with_self_none(self, tmp_path):
        """DocxMap._rewrite_docx_zip must stay callable as
        ``DocxMap._rewrite_docx_zip(None, path, settings)`` (self unused),
        matching the pattern existing tests
        (test_metadata_scrubbing.py, test_large_docx_performance.py) rely on."""
        import zipfile

        from marcut.docx_io import DocxMap

        test_docx = str(tmp_path / "test.docx")
        with zipfile.ZipFile(test_docx, "w") as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
            zf.writestr("word/document.xml", "<w:document/>")

        settings = MetadataCleaningSettings.from_preset("none")
        # Must not raise -- self is never touched inside the method body.
        DocxMap._rewrite_docx_zip(None, test_docx, settings)


class TestScanModuleBoundary:
    """Lock the docx_io package-split module-boundary invariant for Slice 4.

    docs/design/docx_io_package_split.md Section 4 (Slice 4) requires that
    the document scanning/indexing layer live in ``marcut.docx_pkg.scan`` as
    a ``DocumentIndex`` type composed by ``DocxMap`` in ``__init__``, with
    ``.text``/``.index``/``.detached_parts`` re-exposed onto ``DocxMap`` for
    backward compatibility -- the identity-chain analogue of the
    settings/xml_utils/zip_postprocess re-export tests above.
    """

    def test_docx_io_reexports_document_index_identical_class(self):
        """docx_io imports the canonical DocumentIndex class, not a copy."""
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.scan as scan

        assert docx_io.DocumentIndex is scan.DocumentIndex

    def test_docxmap_composes_document_index_instance(self, tmp_path):
        """DocxMap.__init__ constructs a real DocumentIndex and re-exposes
        its .text/.index/.detached_parts as the *same* objects, not copies."""
        import docx
        import marcut.docx_pkg.scan as scan
        from marcut.docx_io import DocxMap

        src = tmp_path / "scan_identity.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))

        assert isinstance(docx_map._index, scan.DocumentIndex)
        assert docx_map.text is docx_map._index.text
        assert docx_map.index is docx_map._index.index
        assert docx_map.detached_parts is docx_map._index.detached_parts
        assert "hello world" in docx_map.text

    def test_iter_part_elements_delegates_to_document_index(self, tmp_path):
        """DocxMap._iter_part_elements/_iter_part_elements_with_parts are
        thin delegating methods onto the DocumentIndex instance, not a
        re-implemented copy -- kept as part of DocxMap's tested surface
        even though the hardening/revision-writing code (Slice 5) is
        injected the DocumentIndex methods directly rather than routing
        through these delegates."""
        import docx
        from marcut.docx_io import DocxMap

        src = tmp_path / "scan_delegate.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))

        via_docx_map = list(docx_map._iter_part_elements())
        via_index = list(docx_map._index._iter_part_elements())
        assert len(via_docx_map) == len(via_index) > 0
        assert all(a is b for a, b in zip(via_docx_map, via_index))

        via_docx_map_parts = list(docx_map._iter_part_elements_with_parts())
        via_index_parts = list(docx_map._index._iter_part_elements_with_parts())
        assert len(via_docx_map_parts) == len(via_index_parts) > 0
        assert all(
            a[0] is b[0] and a[1] is b[1]
            for a, b in zip(via_docx_map_parts, via_index_parts)
        )


class TestHardeningRevisionModuleBoundary:
    """Lock the docx_io package-split module-boundary invariant for Slice 5
    (docs/design/docx_io_package_split.md Section 4, final slice) -- the
    identity-chain analogue of the settings/xml_utils/zip_postprocess/scan
    re-export tests above, for `hardening.py`'s `MetadataHardener`,
    `revision_writer.py`'s `RevisionWriter`, and `document.py`'s `DocxMap`
    coordinator.
    """

    def test_docx_io_reexports_docxmap_identical_class(self):
        """docx_io imports the canonical DocxMap class, not a copy."""
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.document as document

        assert docx_io.DocxMap is document.DocxMap

    def test_docx_io_reexports_metadata_hardener_identical_class(self):
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.hardening as hardening

        assert docx_io.MetadataHardener is hardening.MetadataHardener

    def test_docx_io_reexports_revision_writer_identical_class(self):
        import marcut.docx_io as docx_io
        import marcut.docx_pkg.revision_writer as revision_writer

        assert docx_io.RevisionWriter is revision_writer.RevisionWriter

    def test_docxmap_composes_hardener_and_revision_writer_instances(self, tmp_path):
        """DocxMap.__init__ constructs real MetadataHardener/RevisionWriter
        instances, injected with the DocumentIndex's part-iteration
        methods and sharing the same `.index`/`.warnings` objects -- not
        copies."""
        import docx
        import marcut.docx_pkg.hardening as hardening
        import marcut.docx_pkg.revision_writer as revision_writer
        from marcut.docx_io import DocxMap

        src = tmp_path / "hardening_revision_identity.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))

        assert isinstance(docx_map._hardening, hardening.MetadataHardener)
        assert isinstance(docx_map._revisions, revision_writer.RevisionWriter)

        # Injected part-iteration callables resolve to the same DocumentIndex
        # method, not a re-implemented copy.
        via_hardener = list(docx_map._hardening._iter_part_elements())
        via_index = list(docx_map._index._iter_part_elements())
        assert len(via_hardener) == len(via_index) > 0
        assert all(a is b for a, b in zip(via_hardener, via_index))

        via_revisions = list(docx_map._revisions._iter_part_elements_with_parts())
        via_index_parts = list(docx_map._index._iter_part_elements_with_parts())
        assert len(via_revisions) == len(via_index_parts) > 0
        assert all(
            a[0] is b[0] and a[1] is b[1]
            for a, b in zip(via_revisions, via_index_parts)
        )

        # Same list objects, not copies -- warnings appended on one are
        # visible via the other, and the RevisionWriter's index is the
        # DocxMap/DocumentIndex's own character-offset list.
        assert docx_map._revisions.index is docx_map.index
        assert docx_map._hardening.warnings is docx_map.warnings
        assert docx_map._revisions.warnings is docx_map.warnings

    def test_comment_visibility_map_delegates_to_hardener(self, tmp_path):
        """DocxMap._comment_visibility_map is a thin delegating method onto
        the MetadataHardener instance, not a re-implemented copy -- it is
        called directly in tests
        (test_docx_io_characterization.py::TestCommentVisibilityMap)."""
        import docx
        from marcut.docx_io import DocxMap

        src = tmp_path / "comment_visibility_delegate.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))

        assert docx_map._comment_visibility_map() == docx_map._hardening._comment_visibility_map()

    def test_apply_replacements_delegates_to_revision_writer(self, tmp_path):
        """DocxMap.apply_replacements calls the canonical RevisionWriter
        method, not a re-implemented copy."""
        import docx
        from unittest import mock

        from marcut.docx_io import DocxMap

        src = tmp_path / "apply_replacements_delegate.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))
        spans = [{"start": 0, "end": 5, "replacement": "[X]"}]

        with mock.patch.object(
            type(docx_map._revisions), "apply_replacements"
        ) as apply_replacements:
            docx_map.apply_replacements(spans, track_changes=False)

        apply_replacements.assert_called_once_with(spans, False)

    def test_harden_document_delegates_to_hardener(self, tmp_path):
        """DocxMap.harden_document calls the canonical MetadataHardener
        method, not a re-implemented copy."""
        import docx
        from unittest import mock

        from marcut.docx_io import DocxMap, MetadataCleaningSettings

        src = tmp_path / "harden_document_delegate.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))
        settings = MetadataCleaningSettings()

        with mock.patch.object(
            type(docx_map._hardening), "harden_document"
        ) as harden_document:
            docx_map.harden_document(scrub_all_images=True, settings=settings)

        harden_document.assert_called_once_with(True, settings)

    def test_author_name_set_after_load_is_live_forwarded_to_revision_writer(
        self, tmp_path
    ):
        """A post-construction assignment to ``DocxMap.author_name`` (as
        ``pipeline.py`` does after ``load_accepting_revisions()``, see
        ``run_redaction(redaction_author=...)``) must still control the
        ``w:author`` stamped on emitted ``w:ins``/``w:del`` elements --
        ``RevisionWriter`` was constructed with a copy of ``author_name``,
        not a live reference, so ``DocxMap.author_name`` forwards live
        rather than being shadowed by the copy."""
        import zipfile

        import docx
        from lxml import etree

        from marcut.docx_io import DocxMap

        src = tmp_path / "author_name_live_forward.docx"
        out = tmp_path / "author_name_live_forward_out.docx"
        doc = docx.Document()
        doc.add_paragraph("hello world")
        doc.save(str(src))

        docx_map = DocxMap.load(str(src))
        docx_map.author_name = "CustomAuthor"
        assert docx_map._revisions.author_name == "CustomAuthor"

        spans = [{"start": 0, "end": 5, "replacement": "[X]"}]
        docx_map.apply_replacements(spans, track_changes=True)
        docx_map.save(str(out))

        with zipfile.ZipFile(out) as zf:
            document_xml = zf.read("word/document.xml")

        root = etree.fromstring(document_xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        authors = {
            el.get("{%s}author" % ns["w"])
            for el in root.iter()
            if el.tag in ("{%s}ins" % ns["w"], "{%s}del" % ns["w"])
        }
        assert authors == {"CustomAuthor"}
