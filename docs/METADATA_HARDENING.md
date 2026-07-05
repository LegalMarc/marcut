# Metadata Hardening Implementation Guide

> **Version:** 1.1  
> **Date:** July 2026  
> **Status:** Complete (104 fixes implemented); size-budget hardening added under the T9 remediation ticket

## Overview

This document describes the comprehensive metadata redaction and hardening system implemented in Marcut. The system provides 104 distinct metadata cleaning operations to protect document privacy and prevent information leakage.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    scrub_metadata()                          │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           MetadataCleaningSettings                   │    │
│  │  (104 boolean flags controlling each operation)      │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │             104 Helper Methods                       │    │
│  │  _clean_author(), _clean_exif(), _clean_paths()...  │    │
│  └─────────────────────────────────────────────────────┘    │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           MetadataCleaningReport                     │    │
│  │  - items_cleaned, items_remaining                    │    │
│  │  - embedded_docs_found, warnings                     │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Cleaning Categories

### Tier 1: Core Metadata (Fixes 1-8)
| Fix | Target | Description |
|-----|--------|-------------|
| 1 | Footnotes/Endnotes | Extend hyperlink flattening to footnotes |
| 2 | Header/Footer rels | Clean relationships in headers/footers |
| 3 | Alt Text | Remove descriptive text from images |
| 4 | Comment refs | Remove comment reference elements |
| 5 | Doc Variables/GUID | Clean document variables and unique ID |
| 6 | Proof State | Deduplicate spell/grammar state elements |
| 7 | OLE rels | Collect and remove OLE object relationships |
| 8 | Track Changes | Make track change acceptance configurable |

### Tier 2: Advanced (Fixes 9-16)
- Image relationship removal
- Footnote hyperlink flattening
- Alt text in footnotes/endnotes
- Custom XML extension cleanup
- Template attachment removal
- Embedded fonts removal
- Printer settings cleanup
- Fast save data handling

### Tier 3: Expert (Fixes 17-24)
- Field codes (AUTHOR, FILENAME, etc.)
- People.xml removal
- WebSettings cleanup
- Document protection hash removal
- Extended properties cleanup
- Bookmark name anonymization
- Form field cleanup
- Custom style handling

### Tier 4: Deep (Fixes 25-32)
- Numbering definitions
- Comments Extended/IDs
- Chart data cleanup
- Compatibility settings
- Data bindings
- Mail merge cleanup
- Theme names
- Latent styles

### Tier 5: Forensic (Fixes 33-40)
- Section properties
- Document grid
- Font table
- Footnote/Endnote properties
- Settings RSIDs
- Active writing style
- Zoom/view settings
- Default tab stops

### Tier 6: ID Fingerprint (Fixes 41-48)
- Paragraph IDs
- Text IDs
- SDT IDs
- Drawing IDs
- Annotation IDs
- Custom XML item props
- Footnote separators
- Move tracking

### Tier 7: Content Cache (Fixes 49-56)
- SEQ fields
- TOC cached data
- Cross-reference cached text
- Bibliography sources
- Document defaults
- Style hierarchy references
- Alternate content fallbacks
- Math equation IDs

### Tier 8: Document Structure (Fixes 57-64)
- Glossary document entries
- Subdocument references
- Frame properties
- Table properties
- List override IDs
- Smart tag data
- Document background
- VBA project references

### Tier 9: High-Risk Path Leakage (Fixes 65-72)
| Fix | Target | Risk Level |
|-----|--------|------------|
| 65 | External link paths | 🔴 High |
| 66 | UNC network paths | 🔴 High |
| 67 | User profile paths | 🔴 High |
| 68 | Internal URLs | 🔴 High |
| 69 | OLE source paths | 🔴 High |
| 70 | Data connection files | 🟠 Medium |
| 71 | Custom XML schema URIs | 🟠 Medium |
| 72 | Recent files tracking | 🟠 Medium |

### Tier 10: Security & Classification (Fixes 73-76)
- Digital signature remnants
- Encryption properties
- Document classification labels (MSIP)
- Rights management data (IRM/DRM)

### Tier 11: Document Origin (Fixes 77-80)
- Source URL (HyperlinkBase)
- Original filename tracking
- Creation location metadata
- Version/revision history

### Tier 12: Embedded Content (Fixes 81-84)
- Embedded spreadsheet metadata
- Embedded presentation metadata
- Embedded diagram attributes
- Ink annotation data

### Tier 13: Formatting (Fixes 85-88)
- Conditional formatting rules
- Data validation formulas
- Named range definitions
- Pivot cache data

### Tier 14: Miscellaneous (Fixes 89-96)
- Document thumbnail
- Custom ribbon/UI extensions
- Keyboard customizations
- Macro button bindings
- Content type normalization
- Relationship ordering
- XML declaration cleanup
- Zip file comments

### Tier 15: Critical Risk (Fixes 97-104)
| Fix | Target | Implementation |
|-----|--------|----------------|
| 97 | **Image EXIF/XMP** | Strips GPS, camera serial, author from JPEG/PNG |
| 98 | Revision authors | Anonymizes w:author attributes |
| 99 | Style names | Renames identifying style names |
| 100 | Hyperlink tooltips | Removes tooltip attributes |
| 101 | Chart labels | Cleans identifying patterns only |
| 102 | Language settings | Removes locale fingerprints |
| 103 | Form defaults | Clears pre-filled values |
| 104 | ActiveX | Removes control elements |

## Presets

### Maximum Privacy
All 104 cleaning operations enabled. Use for documents requiring complete metadata removal.

### Balanced (Recommended)
Cleans identifying metadata while preserving document formatting and functionality.

**Cleaned (ON):**
- Author, company, manager, last modified by
- Comments, keywords, subject, title
- Custom properties, document GUID, RSIDs
- Track changes, review comments
- Digital signatures, VBA macros
- Image EXIF data
- External paths, UNC paths, user paths

**Preserved (OFF):**
- Statistics (word/page counts)
- Created/modified dates
- Alt text (accessibility)
- Embedded fonts (appearance)
- Style names (formatting hierarchy)
- Chart labels (readability)
- Form defaults (functionality)
- Hyperlink URLs (navigation)
- Language settings (spell-check)
- Glossary (building blocks)

### None
No metadata cleaning. Document preserved as-is.

## Image EXIF Stripping

### JPEG Processing
The system removes APP1 (EXIF/XMP) and APP13 (IPTC) markers while preserving:
- SOI (Start of Image)
- DQT (Quantization tables)
- DHT (Huffman tables)
- SOF (Frame markers)
- SOS (Start of Scan)
- Image data

### PNG Processing
Removes text metadata chunks:
- tEXt, iTXt, zTXt (text metadata)
- eXIf (EXIF data)

**Preserves color management:**
- sRGB (color space)
- gAMA (gamma)
- iCCP (color profile)
- cHRM (chromaticity)

## Metadata Cleaning Report

The `scrub_metadata()` function returns a `MetadataCleaningReport` object:

```python
@dataclass
class MetadataCleaningReport:
    items_cleaned: List[str]        # What was cleaned
    items_remaining: List[str]      # What couldn't be cleaned
    embedded_docs_found: List[str]  # Docs needing recursive cleaning
    warnings: List[str]             # Issues encountered
```

### Output Formats

**JSON (for API integration):**
```python
report.to_dict()
```

**Human-readable text:**
```python
report.to_text()
```

Example output:
```
=== Metadata Cleaning Report ===

✅ CLEANED (14 items):
   • Author info
   • Company
   • Manager
   • Image EXIF data

📎 EMBEDDED DOCUMENTS (need recursive cleaning):
   • Embedded Excel Spreadsheet at document body

Summary: 14 cleaned, 0 remaining, 1 embedded docs
```

## CLI Arguments

Metadata cleaning is **not** a standalone top-level CLI command - there is no `marcut --scrub-metadata` flag. Metadata cleaning always runs as part of `marcut redact`, and is controlled by one of three mutually-reinforcing options on that subcommand (see `src/python/marcut/cli.py`):

```bash
# Use a named preset (maximum / balanced / none / custom)
marcut redact --in input.docx --out output.docx --report report.json \
  --mode rules \
  --metadata-preset balanced

# Pass exact per-field checkbox state as JSON (field name -> bool)
marcut redact --in input.docx --out output.docx --report report.json \
  --mode rules \
  --metadata-settings-json '{"clean_author": true, "clean_exif": false}'

# Pass raw override flags as a single string (parsed with shlex)
marcut redact --in input.docx --out output.docx --report report.json \
  --mode rules \
  --metadata-args "--no-clean-exif --no-clean-style-names"
```

Under the hood, `cli.py` collects `--metadata-args`, `--metadata-preset`, and `--metadata-settings-json`, plus any of the individual `--no-clean-*` / `--clean-*` override flags passed directly (these are hidden/`argparse.SUPPRESS`'d convenience flags, not documented top-level switches), joins them, and exports the result as the `MARCUT_METADATA_ARGS` (and `MARCUT_METADATA_PRESET` / `MARCUT_METADATA_SETTINGS_JSON`) environment variable(s) before invoking the redaction pipeline. The pipeline and `docx_io.py` read those environment variables, not command-line flags directly.

Available `--no-clean-*` / `--clean-*` override flags include:
- `--no-clean-company`, `--no-clean-author`
- `--no-clean-exif`, `--no-clean-thumbnails`
- `--no-clean-ext-links`, `--no-clean-unc-paths`
- `--no-clean-style-names`, `--no-clean-chart-labels`
- And more, one pair per entry in `docx_io.py`'s `CLI_ARG_PAIRS` (which backs all 104 settings)

## Metadata & Report Size Budgets (T9 Remediation)

To prevent pathologically large or adversarial documents (e.g. huge embedded binaries, enormous XML text runs, or thousands of custom properties) from producing unbounded memory usage or multi-hundred-MB JSON/HTML reports, `src/python/marcut/pipeline.py` enforces a set of size budgets during metadata capture and report generation. All limits are configurable via environment variables and default to sane, generous values; a limit of `0` disables that particular cap.

| Env Var | Default | Effect |
|---------|---------|--------|
| `MARCUT_METADATA_CAPTURE_MAX_STRING_CHARS` | 20,000 chars | Caps the length of any single metadata text/XML value captured for before/after forensic comparison. Longer values are stored as a truncated `{preview, truncated, original_chars, limit_chars}` object instead, and a `METADATA_CAPTURE_TEXT_TRUNCATED` warning is recorded. |
| `MARCUT_METADATA_REPORT_MAX_STRING_CHARS` | 20,000 chars | Same truncation behavior, applied when serializing values into the final JSON/HTML report (`_serialize_value`), recorded as `METADATA_REPORT_VALUE_TRUNCATED`. |
| `MARCUT_METADATA_REPORT_MAX_LIST_ITEMS` | 200 items | Caps how many items from a list-valued metadata field are serialized into the report. |
| `MARCUT_METADATA_REPORT_MAX_DICT_ITEMS` | 200 items | Caps how many key/value pairs from a dict-valued metadata field are serialized into the report. |
| `MARCUT_REPORT_EXPORT_MAX_PART_BYTES` | 2 MiB (2 * 1024 * 1024) | Skips exporting/capturing any single embedded binary part (image, font, OLE object, etc.) larger than this, recording a `FORENSIC_BINARY_EXPORT_PART_LIMIT` warning. |
| `MARCUT_REPORT_EXPORT_MAX_BYTES` | 10 MiB (10 * 1024 * 1024) | Caps the total bytes of embedded binaries exported to the report's `binaries/` directory across the whole document; export stops once the running total would exceed this, recording `FORENSIC_BINARY_EXPORT_TOTAL_LIMIT`. |

Binary/forensic exports are opt-in and gated separately from the size budgets above:

| Env Var | Default | Effect |
|---------|---------|--------|
| `MARCUT_ENABLE_FORENSIC_EXPORTS` | disabled | Enables writing embedded binary parts (images, fonts, OLE objects, etc.) and the forensic "deep explorer" view to disk under the report directory. |
| `MARCUT_ENABLE_BINARY_EXPORTS` | disabled | Alias/equivalent trigger for binary export - either variable being truthy enables binary export (`_metadata_env_enabled("MARCUT_ENABLE_FORENSIC_EXPORTS") or _metadata_env_enabled("MARCUT_ENABLE_BINARY_EXPORTS")`). |

When binary parts exist but forensic/binary exports are **not** enabled, the report records a `FORENSIC_BINARY_EXPORTS_DISABLED` informational warning instead of silently dropping the data, so it's clear from the report itself that binaries were present but not written to disk.

Related, less commonly needed knobs also gated by the same forensic-export flags: `MARCUT_REPORT_EXPORT_MAX_COUNT` (default 50 - max number of exported binary parts) and the deep-explorer-specific `MARCUT_ENABLE_DEEP_EXPLORER`, `MARCUT_DEEP_EXPLORER_MAX_PARTS` (100), `MARCUT_DEEP_EXPLORER_MAX_BYTES` (10 MiB), `MARCUT_DEEP_EXPLORER_MAX_PART_BYTES` (512 KiB), and `MARCUT_DEEP_EXPLORER_MAX_TEXT_CHARS` (20,000).

## Safety Measures

### Corruption Prevention
1. **PNG color profiles preserved** - sRGB, gAMA, iCCP chunks kept
2. **Chart labels pattern-based** - Only identifying text replaced
3. **Ink annotations namespace-specific** - Uses proper MS Ink namespace
4. **Style names preserve styleId** - Only display name changed
5. **All operations wrapped in try/except** - Failures don't crash

### Word Compatibility Safeguards (2025-12)
1. **Core properties normalized** - cleaned core fields are removed from `docProps/core.xml` instead of leaving empty nodes that trigger repair prompts.
2. **App properties removed, not blanked** - `Template`, `Application`, `AppVersion`, `Company`, and `Manager` are deleted when cleaned to avoid invalid extended-property states.
3. **Root relationships normalized** - `_rels/.rels` now enforces the canonical core-properties relationship and removes legacy duplicates.
4. **Duplicate ZIP parts removed** - the post-save rewrite keeps only the last entry for each part name (fixes duplicate `docProps/core.xml` entries seen in LibreOffice-origin files).

### Validation
- Embedded document detection (XLSX, PPTX, DOCX)
- Remaining metadata detection
- Warning collection for issues

## Files Modified

| File | Changes |
|------|---------|
| `docx_io.py` | 104 settings, 106 helper methods, report class |
| `MetadataCleaningSettings.swift` | Swift settings mirror, CLI mappings, presets |

## Future Considerations

### Not Yet Implemented
- Recursive cleaning of embedded Office documents
- GIF/TIFF/BMP metadata stripping
- EMF/WMF vector metadata

### Recommended Testing
1. Run on various real-world documents
2. Verify visual appearance unchanged
3. Check Word can open without repair prompts
4. Validate with Office file validators
