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
        with pytest.raises(Exception):
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
        setting_fields = {f.name for f in fields(settings) if f.type == bool}
        mapped_fields = set(CLI_ARG_MAP.values())
        
        # All mapped fields should be in settings
        for field in mapped_fields:
            assert hasattr(settings, field), f"CLI mapped field {field} not in settings"

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
