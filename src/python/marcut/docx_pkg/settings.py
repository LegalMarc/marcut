"""CLI/settings configuration surface extracted from ``marcut.docx_io``.

Slice 1 of the docx_io package split (docs/design/docx_io_package_split.md,
Section 4). Moved verbatim: no ``python-docx``/``lxml``/``zipfile``
dependency here, pure dataclass + dict logic, importable without touching a
real document. ``marcut.docx_io`` re-exports these names for backward
compatibility with existing ``from .docx_io import ...`` call sites.
"""

import copy
import json
import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, fields

CLI_ARG_PAIRS: List[Tuple[str, str]] = [
    # App Properties
    ("--no-clean-company", "clean_company"),
    ("--no-clean-manager", "clean_manager"),
    ("--no-clean-editing-time", "clean_total_editing_time"),
    ("--no-clean-application", "clean_application"),
    ("--no-clean-app-version", "clean_app_version"),
    ("--no-clean-template", "clean_template"),
    ("--no-clean-hyperlink-base", "clean_hyperlink_base"),
    ("--no-clean-statistics", "clean_statistics"),
    ("--no-clean-doc-security", "clean_doc_security"),
    ("--no-clean-scale-crop", "clean_scale_crop"),
    ("--no-clean-links-up-to-date", "clean_links_up_to_date"),
    ("--no-clean-shared-doc", "clean_shared_doc"),
    ("--no-clean-hyperlinks-changed", "clean_hyperlinks_changed"),
    # Core Properties
    ("--no-clean-author", "clean_author"),
    ("--no-clean-last-modified-by", "clean_last_modified_by"),
    ("--no-clean-title", "clean_title"),
    ("--no-clean-subject", "clean_subject"),
    ("--no-clean-keywords", "clean_keywords"),
    ("--no-clean-comments", "clean_comments"),
    ("--no-clean-category", "clean_category"),
    ("--no-clean-content-status", "clean_content_status"),
    ("--no-clean-created-date", "clean_created_date"),
    ("--no-clean-modified-date", "clean_modified_date"),
    ("--no-clean-last-printed", "clean_last_printed"),
    ("--no-clean-revision", "clean_revision_number"),
    ("--no-clean-identifier", "clean_identifier"),
    ("--no-clean-language", "clean_language"),
    ("--no-clean-version", "clean_version"),
    # Custom Properties
    ("--no-clean-custom-props", "clean_custom_properties"),
    # Document Structure
    ("--no-clean-review-comments-visible", "clean_review_comments_visible"),
    ("--no-clean-review-comments-hidden", "clean_review_comments_hidden"),
    ("--no-clean-track-changes", "clean_track_changes"),
    ("--no-clean-rsids", "clean_rsids"),
    ("--no-clean-guid", "clean_document_guid"),
    ("--no-clean-spell-grammar", "clean_spell_grammar_state"),
    ("--no-clean-doc-vars", "clean_document_variables"),
    ("--no-clean-mail-merge", "clean_mail_merge"),
    ("--no-clean-data-bindings", "clean_data_bindings"),
    ("--no-clean-doc-versions", "clean_document_versions"),
    ("--no-clean-ink-annotations", "clean_ink_annotations"),
    ("--no-clean-hidden-text", "clean_hidden_text"),
    ("--no-clean-invisible-objects", "clean_invisible_objects"),
    ("--no-clean-headers-footers", "clean_headers_footers"),
    ("--no-clean-watermarks", "clean_watermarks"),
    # Embedded Content
    ("--no-clean-thumbnail", "clean_thumbnail"),
    ("--no-clean-hyperlinks", "clean_hyperlink_urls"),
    ("--no-clean-alt-text", "clean_alt_text"),
    ("--no-clean-ole", "clean_ole_objects"),
    ("--no-clean-macros", "clean_vba_macros"),
    ("--no-clean-signatures", "clean_digital_signatures"),
    ("--no-clean-printer", "clean_printer_settings"),
    ("--no-clean-fonts", "clean_embedded_fonts"),
    ("--no-clean-glossary", "clean_glossary"),
    ("--no-clean-fast-save", "clean_fast_save_data"),
    # Advanced Hardening
    ("--no-clean-ext-links", "clean_external_links"),
    ("--no-clean-unc-paths", "clean_unc_paths"),
    ("--no-clean-user-paths", "clean_user_paths"),
    ("--no-clean-internal-urls", "clean_internal_urls"),
    ("--no-clean-ole-sources", "clean_ole_sources"),
    ("--no-clean-exif", "clean_image_exif"),
    ("--no-clean-style-names", "clean_style_names"),
    ("--no-clean-chart-labels", "clean_chart_labels"),
    ("--no-clean-form-defaults", "clean_form_defaults"),
    ("--no-clean-language-settings", "clean_language_settings"),
    ("--no-clean-activex", "clean_activex"),
    ("--no-clean-custom-xml-parts", "clean_custom_xml_parts"),
    ("--no-clean-nonstandard-xml", "clean_nonstandard_xml"),
    ("--no-clean-microsoft-extensions", "clean_microsoft_extension_xml"),
    ("--no-clean-unknown-rels", "clean_unknown_relationships"),
    ("--no-clean-orphaned-parts", "clean_orphaned_parts"),
    ("--no-clean-alternate-content", "clean_alternate_content"),
]

CLI_ARG_MAP = dict(CLI_ARG_PAIRS)
CLI_CLEAN_ARG_PAIRS: List[Tuple[str, str]] = [
    (flag.replace("--no-clean-", "--clean-", 1), field) for flag, field in CLI_ARG_PAIRS
]
CLI_CLEAN_ARG_MAP = dict(CLI_CLEAN_ARG_PAIRS)
FIELD_TO_CLI = {field: flag for flag, field in CLI_ARG_PAIRS}


def _normalize_metadata_field_key(name: str) -> str:
    return "".join(ch for ch in (name or "") if ch.isalnum()).lower()


@dataclass
class MetadataCleaningSettings:
    """Settings for granular control of which metadata fields are cleaned during redaction."""

    # App Properties (docProps/app.xml)
    clean_company: bool = True
    clean_manager: bool = True
    clean_total_editing_time: bool = True
    clean_application: bool = True
    clean_app_version: bool = True
    clean_template: bool = True
    clean_hyperlink_base: bool = True
    clean_statistics: bool = True  # chars, words, lines, paragraphs, pages
    clean_doc_security: bool = True
    clean_scale_crop: bool = True
    clean_links_up_to_date: bool = True
    clean_shared_doc: bool = True
    clean_hyperlinks_changed: bool = True

    # Core Properties (docProps/core.xml)
    clean_author: bool = True
    clean_last_modified_by: bool = True
    clean_title: bool = True
    clean_subject: bool = True
    clean_keywords: bool = True
    clean_comments: bool = True
    clean_category: bool = True
    clean_content_status: bool = True
    clean_created_date: bool = False  # Default OFF
    clean_modified_date: bool = False  # Default OFF
    clean_last_printed: bool = True
    clean_revision_number: bool = True
    clean_identifier: bool = True
    clean_language: bool = True
    clean_version: bool = True

    # Custom Properties
    clean_custom_properties: bool = True

    # Document Structure
    clean_review_comments_visible: bool = True
    clean_review_comments_hidden: bool = True
    clean_track_changes: bool = True
    clean_rsids: bool = True
    clean_document_guid: bool = True
    clean_spell_grammar_state: bool = True
    clean_document_variables: bool = True
    clean_mail_merge: bool = True
    clean_data_bindings: bool = True
    clean_document_versions: bool = True
    clean_ink_annotations: bool = True
    clean_hidden_text: bool = True
    clean_invisible_objects: bool = True
    clean_headers_footers: bool = True
    clean_watermarks: bool = True

    # Embedded Content
    clean_thumbnail: bool = True
    clean_hyperlink_urls: bool = True
    clean_alt_text: bool = True
    clean_ole_objects: bool = True
    clean_vba_macros: bool = True
    clean_digital_signatures: bool = True
    clean_printer_settings: bool = True
    clean_embedded_fonts: bool = True
    clean_glossary: bool = True
    clean_fast_save_data: bool = True

    # Advanced Hardening
    clean_external_links: bool = True
    clean_unc_paths: bool = True
    clean_user_paths: bool = True
    clean_internal_urls: bool = True
    clean_ole_sources: bool = True
    clean_image_exif: bool = True
    clean_style_names: bool = True
    clean_chart_labels: bool = True
    clean_form_defaults: bool = True
    clean_language_settings: bool = True
    clean_activex: bool = True
    clean_custom_xml_parts: bool = True
    clean_nonstandard_xml: bool = True
    clean_microsoft_extension_xml: bool = True
    clean_unknown_relationships: bool = True
    clean_orphaned_parts: bool = True
    clean_alternate_content: bool = True

    @classmethod
    def from_preset(cls, preset: str) -> "MetadataCleaningSettings":
        normalized = (preset or "").strip().lower()
        settings = cls()
        if normalized == "maximum":
            settings.clean_created_date = True
            settings.clean_modified_date = True
            return settings
        if normalized == "balanced":
            settings.clean_statistics = False
            settings.clean_created_date = False
            settings.clean_modified_date = False
            settings.clean_hyperlinks_changed = False
            settings.clean_embedded_fonts = False
            settings.clean_style_names = False
            settings.clean_chart_labels = False
            settings.clean_form_defaults = False
            settings.clean_language_settings = False
            settings.clean_hyperlink_urls = False
            settings.clean_language = False
            settings.clean_glossary = False
            settings.clean_scale_crop = False
            settings.clean_spell_grammar_state = False
            settings.clean_document_variables = False
            settings.clean_mail_merge = False
            settings.clean_headers_footers = False
            settings.clean_watermarks = False
            settings.clean_ink_annotations = False
            settings.clean_custom_xml_parts = False
            settings.clean_nonstandard_xml = False
            settings.clean_microsoft_extension_xml = False
            settings.clean_unknown_relationships = False
            settings.clean_orphaned_parts = False
            settings.clean_alternate_content = False
            settings.clean_review_comments_visible = False
            settings.clean_review_comments_hidden = True
            settings.clean_track_changes = False
            return settings
        if normalized == "none":
            for f in fields(settings):
                setattr(settings, f.name, False)
            return settings
        return settings

    @classmethod
    def _field_lookup(cls) -> Dict[str, str]:
        return {
            _normalize_metadata_field_key(f.name): f.name
            for f in fields(cls)
        }

    def apply_mapping(self, values: Dict[str, Any]) -> None:
        lookup = self._field_lookup()
        for key, value in values.items():
            field_name = lookup.get(_normalize_metadata_field_key(str(key)))
            if not field_name:
                continue
            if isinstance(value, bool):
                setattr(self, field_name, value)
                continue
            if isinstance(value, (int, float)):
                setattr(self, field_name, bool(value))
                continue
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "on"}:
                    setattr(self, field_name, True)
                elif normalized in {"0", "false", "no", "off"}:
                    setattr(self, field_name, False)

    @classmethod
    def from_cli_args(
        cls,
        args: List[str],
        base: Optional["MetadataCleaningSettings"] = None
    ) -> "MetadataCleaningSettings":
        """Apply CLI metadata overrides to an optional base settings object."""
        settings = copy.deepcopy(base) if base is not None else cls()
        if "--no-clean-review-comments" in args:
            settings.clean_review_comments_visible = False
            settings.clean_review_comments_hidden = False
        if "--clean-review-comments" in args:
            settings.clean_review_comments_visible = True
            settings.clean_review_comments_hidden = True
        for arg in args:
            if arg in CLI_ARG_MAP:
                setattr(settings, CLI_ARG_MAP[arg], False)
            elif arg in CLI_CLEAN_ARG_MAP:
                setattr(settings, CLI_CLEAN_ARG_MAP[arg], True)
        return settings

    @classmethod
    def from_environment(cls, args: Optional[List[str]] = None) -> "MetadataCleaningSettings":
        """Resolve metadata settings from preset, full-settings JSON, then CLI args."""
        parsed_args = args or []
        preset = os.environ.get("MARCUT_METADATA_PRESET", "")
        settings = cls.from_preset(preset)

        raw_json = os.environ.get("MARCUT_METADATA_SETTINGS_JSON", "").strip()
        if raw_json:
            try:
                decoded = json.loads(raw_json)
            except Exception:
                decoded = None
            if isinstance(decoded, dict):
                payload = decoded.get("settings") if isinstance(decoded.get("settings"), dict) else decoded
                settings.apply_mapping(payload)

        return cls.from_cli_args(parsed_args, base=settings)

    def to_cli_args(self) -> List[str]:
        """Generate CLI arguments that disable any settings set to False."""
        args: List[str] = []
        if all(not getattr(self, f.name) for f in fields(self)):
            args.append("--preset-none")
        for field_name, flag in FIELD_TO_CLI.items():
            if hasattr(self, field_name) and not getattr(self, field_name):
                args.append(flag)
        return args
