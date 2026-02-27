# Metadata Hardening Implementation Guide

> **Version:** 1.0  
> **Date:** December 2024  
> **Status:** Complete (104 fixes implemented)

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

All settings can be controlled via CLI flags:

```bash
# Full metadata scrub (all enabled)
marcut --scrub-metadata input.docx output.docx

# Disable specific operations
marcut --scrub-metadata \
  --no-clean-exif \
  --no-clean-style-names \
  input.docx output.docx
```

Available flags include:
- `--no-clean-company`, `--no-clean-author`
- `--no-clean-exif`, `--no-clean-thumbnails`
- `--no-clean-ext-links`, `--no-clean-unc-paths`
- `--no-clean-style-names`, `--no-clean-chart-labels`
- And 96 more...

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
