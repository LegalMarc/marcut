# MarcutApp Help

MarcutApp is a local-only DOCX redaction tool for macOS. It generates a redacted Word document with track changes plus a JSON audit report for verification and compliance. The macOS app and the `marcut` CLI share the same Python pipeline, so outputs are consistent across interfaces.

This help file is written for two audiences:
- Novice users who want a guided, reliable redaction workflow.
- Technical users who want a precise reference for settings, outputs, and internals.

If you only need a quick result, read the Start Here section. If you are automating or debugging, read the CLI Guide and Technical Reference.

## How to Use This Help

- New to redaction: read Start Here and the macOS App Guide.
- Automation or scripting: read the CLI Guide and Configuration and Overrides.
- Technical details: read Technical Reference (Developer).
- Terminology questions: see Glossary.

## Table of Contents

- [Start Here](#start-here)
  - [Quickstart (macOS app)](#quickstart-macos-app)
  - [Quickstart (CLI)](#quickstart-cli)
  - [Decide: App or CLI](#decide-app-or-cli)
  - [Choose a Redaction Mode](#choose-a-redaction-mode)
  - [Preflight Checklist](#preflight-checklist)
  - [First-Time Workflow (Novice)](#first-time-workflow-novice)
  - [Review Checklist](#review-checklist)
- [Redaction Basics](#redaction-basics)
  - [Supported Inputs and Outputs](#supported-inputs-and-outputs)
  - [What Gets Scanned](#what-gets-scanned)
  - [What Does Not Get Scanned](#what-does-not-get-scanned)
  - [Redaction Tags and Track Changes](#redaction-tags-and-track-changes)
  - [JSON Audit Report (High Level)](#json-audit-report-high-level)
  - [Metadata Scrub Report (High Level)](#metadata-scrub-report-high-level)
  - [Common Redaction Questions](#common-redaction-questions)
  - [Redaction Label Reference](#redaction-label-reference)
- [macOS App Guide](#macos-app-guide)
  - [Install and First Run](#install-and-first-run)
  - [Import Documents](#import-documents)
  - [Settings Explained](#settings-explained)
  - [Running Redaction](#running-redaction)
  - [Reviewing Results](#reviewing-results)
  - [Output Naming (GUI and headless)](#output-naming-gui-and-headless)
  - [Logs and Diagnostics](#logs-and-diagnostics)
  - [Headless App Commands](#headless-app-commands)
- [CLI Guide](#cli-guide)
  - [Install CLI](#install-cli)
  - [Basic Usage](#basic-usage)
  - [Full Flag Reference](#full-flag-reference)
  - [Timing and Profiling Output](#timing-and-profiling-output)
  - [Progress Output Format](#progress-output-format)
  - [Examples and Automation](#examples-and-automation)
  - [Output Paths and Naming (CLI)](#output-paths-and-naming-cli)
  - [Exit Codes](#exit-codes)
- [Configuration and Overrides](#configuration-and-overrides)
  - [Environment Variables](#environment-variables)
  - [Rule Filter Details](#rule-filter-details)
  - [Excluded Words](#excluded-words)
  - [System Prompt Override](#system-prompt-override)
  - [Metadata Cleaning Controls](#metadata-cleaning-controls)
  - [Metadata Cleaning Flag Reference](#metadata-cleaning-flag-reference)
  - [Metadata Scrub Reports](#metadata-scrub-reports)
- [Technical Reference (Developer)](#technical-reference-developer)
  - [Pipeline Overview](#pipeline-overview)
  - [Step-by-step Pipeline](#step-by-step-pipeline)
  - [Chunking and Overlap](#chunking-and-overlap)
  - [Span Merging and Priority](#span-merging-and-priority)
  - [Token Boundary Snapping](#token-boundary-snapping)
  - [Span Offsets and Text Flattening](#span-offsets-and-text-flattening)
  - [Progress Phases and Estimation](#progress-phases-and-estimation)
  - [Deterministic Rule Engine Details](#deterministic-rule-engine-details)
  - [AI Extraction and Validation](#ai-extraction-and-validation)
  - [Entity IDs and Tag Generation](#entity-ids-and-tag-generation)
  - [JSON Audit Report Schema](#json-audit-report-schema)
  - [Error Report Schema](#error-report-schema)
  - [Scrub Report Schema](#scrub-report-schema)
  - [Scrub Report Field Details](#scrub-report-field-details)
  - [Model and Input Safety](#model-and-input-safety)
  - [Logging and Encoding Details](#logging-and-encoding-details)
  - [Repository Layout (High Level)](#repository-layout-high-level)
  - [Key Python Modules](#key-python-modules)
  - [Swift Integration (High Level)](#swift-integration-high-level)
  - [Sandboxed Paths and App Group](#sandboxed-paths-and-app-group)
- [Security and Privacy](#security-and-privacy)
  - [Local-Only Processing](#local-only-processing)
  - [Network Access Summary](#network-access-summary)
  - [Using Remote Ollama Hosts](#using-remote-ollama-hosts)
  - [Metadata Reduction and Hardening](#metadata-reduction-and-hardening)
  - [Temporary Files](#temporary-files)
  - [Permissions and macOS Prompts](#permissions-and-macos-prompts)
- [Troubleshooting](#troubleshooting)
  - [Common Errors](#common-errors)
  - [Missing Redactions](#missing-redactions)
  - [Over-Redaction](#over-redaction)
  - [Model and Backend Problems](#model-and-backend-problems)
  - [Output and Permission Issues](#output-and-permission-issues)
  - [Performance Tips](#performance-tips)
  - [Report and Log Diagnostics](#report-and-log-diagnostics)
- [FAQ](#faq)
- [Glossary](#glossary)
- [Versioning and Release Notes](#versioning-and-release-notes)
- [Licensing and Third-Party Notices](#licensing-and-third-party-notices)

## Start Here

If you are new to Marcut, start with the macOS app and Enhanced mode. If you are automating, skip to the CLI Guide.

### Quickstart (macOS app)

1. Install the DMG and drag MarcutApp to `/Applications`.
2. Launch the app and download a model when prompted (recommended: `llama3.1:8b`).
3. Drag one or more `.docx` files into the window.
4. Open Settings and choose a mode (Enhanced is recommended).
5. Click Redact Documents and choose an output folder.
6. Open the redacted DOCX in Word and review track changes.
7. Open the JSON audit report to verify what was detected.

What you get:
- A redacted DOCX with track changes you can accept or reject.
- A JSON audit report with offsets, labels, and a SHA256 hash of the input.
- A metadata scrub report that records what metadata was removed.

### Quickstart (CLI)

1. Install and set up a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

2. Start Ollama and download a model (skip if using Rules only):
```bash
ollama serve
ollama pull llama3.1:8b
```

3. Run a redaction:
```bash
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced --model llama3.1:8b
```

4. Review the DOCX track changes and JSON report.

Tip: use a dedicated output directory like `runs/` (ignored by git) to keep artifacts organized.

### Decide: App or CLI

| If you want | Use |
| --- | --- |
| Drag-and-drop, built-in model management, and a GUI | macOS app |
| Automation, batch processing, or CI | CLI |
| Headless operation with the bundled runtime | macOS app headless mode (`MarcutApp --redact`) |

### Choose a Redaction Mode

| Mode | Best for | Model required | Notes |
| --- | --- | --- | --- |
| Rules only | Fast, structured PII only | No | `strict` is an alias for `rules` |
| Enhanced | Highest accuracy and consistency | Yes | Multi-pass with validation and consistency pass (recommended) |
| Balanced | Legacy behavior and compatibility | Yes | Single-pass LLM extraction, no validation |

### Preflight Checklist

- Input is a real `.docx` (not `.doc`, `.pdf`, or a renamed file).
- Output paths are writable (CLI creates parent dirs for `--out` and `--report`).
- Enhanced or Balanced mode: model is installed and the backend is ready.
  - Ollama: `ollama serve` is running and `OLLAMA_HOST` is correct.
  - llama.cpp: `--backend llama_cpp` and `--llama-gguf` are set.
- If you want to keep images, exclude the `IMAGES` rule (App: toggle it off. CLI: set `MARCUT_RULE_FILTER` without `IMAGES`).
- If your organization has a blocklist of terms that should never be redacted, prepare `excluded-words.txt` first.

### First-Time Workflow (Novice)

1. Make a copy of the original DOCX.
2. Run MarcutApp in Enhanced mode with the default model.
3. Review the redacted output in Word using track changes.
4. Cross-check the JSON audit report for any unexpected spans.
5. If you see false positives, reject those track changes in Word.
6. If you see missing redactions, re-run with a larger model or adjust chunk size.
7. Save the final accepted version as a separate file.

### Review Checklist

- Confirm all redaction tags are appropriate (`[NAME_1]`, `[SSN_2]`, etc).
- Review the deletions to ensure the original sensitive text is removed.
- Search for unredacted versions of the same entity elsewhere in the document.
- Check headers, footers, footnotes, and text boxes.
- Confirm that images are removed only if the `IMAGES` rule was enabled.
- Store reports securely; they can contain text snippets.

## Redaction Basics

### Supported Inputs and Outputs

Inputs
- `.docx` only. `.doc`, `.pdf`, scanned images, and other formats are not supported.
- Existing track changes are accepted and flattened before redaction so only new redaction changes remain.

Outputs
- Redacted `.docx` with track changes. Redaction tags are inserted (for example `[NAME_1]`) and originals are marked as deletions.
- JSON audit report with a SHA256 of the input file and detailed span metadata.
- Metadata scrub report that summarizes what metadata was removed or preserved.
- Optional removal of images when the `IMAGES` rule is enabled.

### What Gets Scanned

Text is extracted from:
- Document body, headers, and footers.
- Tables and nested tables.
- Text boxes and drawings.
- Content controls (SDT).
- Footnotes and endnotes.
- Hyperlinks.

### What Does Not Get Scanned

- Images, scanned PDFs, and embedded raster content (no OCR).
- Text hidden inside embedded objects (for example, spreadsheets or OLE packages).
- Metadata fields are cleaned, but they are not treated as a primary redaction target.
- Comments and tracked changes are removed during cleaning, not redacted in place.

### Redaction Tags and Track Changes

- Redactions are applied as track changes so you can accept or reject each change.
- Redaction tags appear as inserted text in red (for example `[NAME_1]`).
- Original content appears as deletions.
- Possessives are preserved (`[NAME_1]'s`).
- Track changes are authored as `Marcut` by default.

### JSON Audit Report (High Level)

The audit report is a machine-readable summary of what was detected.

- Includes `created_at`, `input_sha256`, `model`, and `spans`.
- Each span includes offsets into a flattened document text, not Word XML positions.
- Span text is truncated to 120 characters for privacy and file size control.

### Metadata Scrub Report (High Level)

A metadata scrub report is generated alongside the audit report.

- Records which metadata fields were cleaned, preserved, or unchanged.
- Includes before and after values for many fields (author, title, hyperlinks, etc).
- Useful for compliance audits and internal validation.

### Common Redaction Questions

- Why do I see tags like `[NAME_1]`? These are stable IDs for a single run and help you track repeated entities.
- Are tags stable across documents? No. The numbering restarts for each document.
- Can I accept only some redactions? Yes. Use Word track changes to accept or reject each change.
- Is the JSON report enough for compliance? It is an audit aid. The DOCX output is the source of truth.
- Does Marcut replace metadata? It removes or clears many metadata fields as part of hardening.

### Redaction Label Reference

The labels below appear in the audit report and in redaction tags. Some labels are produced only by AI, while others come from deterministic rules.

- EMAIL: email addresses, for example `jane.doe@example.com`.
- PHONE: phone numbers with separators, for example `+1 (415) 555-0123`.
- SSN: US SSN in `###-##-####` format, for example `123-45-6789`.
- MONEY: currency amounts, for example `$1,200` or `USD 500`.
- NUMBER: bracketed numeric quantities, for example `[1,200]`.
- DATE: numeric, ISO, or written dates, for example `2024-05-16` or `June 5, 2024`.
- ACCOUNT: bank or account digit sequences (8 to 20 digits).
- CARD: credit or debit numbers (13 to 19 digits) that pass Luhn validation.
- URL: HTTP/HTTPS/FTP URLs and mailto links.
- IP: IPv4 addresses, for example `192.168.1.10`.
- ORG: company names with legal suffixes, for example `Acme LLC`.
- LOC: strict address patterns, for example `123 Main St, Springfield, IL 62704`.
- NAME: person names (usually from AI or signature extraction).
- SIGNATURE: rule toggle for `Name:` lines; extracted names are labeled as NAME.
- BRAND: AI-only label for brand or product names.
- IMAGES: rule toggle that removes images; it does not create spans or tags.

## macOS App Guide

### Install and First Run

- macOS 14 or later.
- Apple Silicon (arm64). Non-arm64 builds show an unsupported architecture screen.
- No system Python or external Ollama install is required for the bundled app.
- On first run, the app prompts you to download a model (recommended: `llama3.1:8b`).

Model storage paths:
- App Group path: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/models/`
- Fallback path: `~/Library/Application Support/MarcutApp/models/`

### Import Documents

- Drag and drop `.docx` files into the window or use the file picker.
- The app validates that files are real DOCX packages and marks invalid files with an error.
- Multiple documents can be processed in a batch.

### Settings Explained

Processing Mode
- Rules Only: deterministic PII detection (fast, no model).
- Enhanced (Rules + AI): rules plus LLM extraction and validation (recommended).
- Balanced: legacy hybrid LLM mode.

AI Model (Enhanced or Balanced mode)
- Choose from recommended models (for example `llama3.1:8b`, `mistral:7b`, `llama3.2:3b`).
- Manage Models to download; Reveal Models to open the models directory.
- Larger models are slower but can catch more context-dependent entities.

Rules Engine
- Toggle deterministic rules: EMAIL, PHONE, SSN, MONEY, NUMBER, DATE, ACCOUNT, CARD, URL, IP, ORG, LOC, Signature Names, IMAGES.
- Disabling a rule affects only deterministic scanning, not AI extraction.
- If `IMAGES` is enabled, all images are removed in the output.

Boilerplate Exclusions
- Edit `excluded-words.txt` in an in-app editor.
- Terms or regex patterns in this file are excluded from redaction.
- Exclusions apply to both deterministic rules and AI validation.

Advanced AI Settings (Enhanced mode)
- Temperature (0.0 to 2.0): lower is more deterministic.
- Chunk Size (500 to 2000 tokens): larger uses more context but can be slower.
- Chunk Overlap (50 to 500 tokens): higher reduces boundary misses but costs more.
- Random Seed (1 to 1000): helps reproducibility.
- Edit System Prompt: affects the classic extractor only; Enhanced uses a built-in prompt.

Debug
- Enable Debug Logging.
- Open App Log, Open Ollama Log, Clear Logs.

Notifications
- System notifications can be enabled for completion banners.
- The app may request permission the first time notifications are used.

### Running Redaction

1. Click Redact Documents.
2. Choose an output folder.
3. The app checks the environment (Python runtime and model readiness).
4. Progress stages appear for each document: Loading, Detecting Data, AI Analysis, Validating, Merging, Creating Output.
5. You can cancel processing with Stop.

Metadata-only option
- Use Scrub Metadata to clean metadata without redacting text.
- This produces a scrubbed DOCX plus a scrub report JSON.
- Use it when you only need to remove document properties, comments, hyperlinks, or embedded objects.

Tip: process one document first to confirm the rules and output, then run batches.

### Reviewing Results

Each completed document row includes:
- Open Redacted Document.
- View Audit Report.
- Show in Finder.

Open the DOCX in Word to review track changes and accept or reject redactions.

### Output Naming (GUI and headless)

macOS app (GUI)
- DOCX: `Filename (redacted M-d-yy hmma).docx`
- Report: `Filename (redacted M-d-yy hmma)_report.json`
- Scrub report: `Filename (redacted M-d-yy hmma)_scrub_report.json`

macOS app (GUI, metadata-only)
- DOCX: `Filename (metadata-scrubbed M-d-yy hmma).docx`
- Scrub report: `Filename (scrub-report M-d-yy hmma).json`

macOS app (headless)
- `MarcutApp --redact --outdir <dir>` produces:
  - `Filename_redacted.docx`
  - `Filename_report.json`
  - `Filename_scrub_report.json`
- If `--outdir` is omitted, outputs are written next to the input.

### Logs and Diagnostics

Logs live in:
- `~/Library/Application Support/MarcutApp/logs/`
- App Group path: `~/Library/Group Containers/group.com.marclaw.marcutapp/Library/Application Support/MarcutApp/logs/`

Other logs
- Ollama logs are stored as `ollama.log` in the same log directory.
- Debug logs may include file paths and text snippets; enable only when needed.

### Headless App Commands

```bash
# Headless redaction
MarcutApp --redact --in /path/to/file.docx --outdir /tmp/out --mode enhanced --model llama3.1:8b

# Model download
MarcutApp --download-model llama3.1:8b

# Diagnostics
MarcutApp --diagnose
```

## CLI Guide

### Install CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Optional llama.cpp support:
```bash
pip install -e ".[llama]"
```

### Basic Usage

```bash
marcut redact --in input.docx --out output.docx --report report.json [options]
```

You can also run it as a module:
```bash
python -m marcut redact --in input.docx --out output.docx --report report.json
```

Global options
- `-h`, `--help`: show general help or subcommand help.
- There is no built-in `--version` flag; use `pip show marcut` or `python -c "import marcut; print(marcut.__version__)"`.

### Full Flag Reference

Required
- `--in <path>`: input DOCX.
- `--out <path>`: output redacted DOCX.
- `--report <path>`: JSON audit report.
- Parent directories for `--out` and `--report` are created automatically.

Mode and backend
- `--mode <rules|enhanced|balanced>` (default: `enhanced`, `strict` is an alias for `rules`).
- `--backend <ollama|llama_cpp|mock>` (default: `ollama`).
- `--model <id-or-path>` (default: `llama3.1:8b`).

LLM tuning
- `--chunk-tokens <int>` (default: 1000).
- `--overlap <int>` (default: 150).
- `--temp <float>` (default: 0.1).
- `--seed <int>` (default: 42).

llama.cpp
- `--llama-gguf <path>`: GGUF model path for the `llama_cpp` backend.
- `--threads <int>` (default: 4): llama.cpp CPU threads.

Diagnostics
- `--debug`: verbose logs and error detail; writes a log file to `/tmp`.
- `--timing`: print phase timing breakdown.
- `--llm-detail`: print LLM sub-phase timing (implies `--timing`).
- `--no-qa`: legacy flag kept for compatibility (no effect today).

### Timing and Profiling Output

`--timing` prints a per-phase timing table on success. Phases include:
- DOCX_LOAD
- RULES
- LLM
- POST_PROCESS
- DOCX_SAVE

`--llm-detail` adds a sub-phase breakdown for Ollama (model load, prompt eval, generation, parsing, and entity location). This helps diagnose slowdowns.

### Progress Output Format

The CLI emits structured lines that the macOS app also parses:

```
MARCUT_PROGRESS: <phase> | Stage: <phase_pct> | Overall: <overall_pct> | Remaining: <seconds>s
MARCUT_STATUS: <message>
```

Example:
```
MARCUT_PROGRESS: AI Entity Extraction | Stage: 45.0% | Overall: 62.3% | Remaining: 18s
MARCUT_STATUS: Processing chunk 3 of 6
```

### Examples and Automation

```bash
# Enhanced mode with Ollama (recommended)
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced --model llama3.1:8b

# Rules only (no model calls)
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode rules

# Balanced mode with llama.cpp
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json \
  --mode balanced --backend llama_cpp --llama-gguf /path/to/model.gguf --threads 8

# Debug + phase timing
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced --debug --timing

# Detailed LLM timing
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced --llm-detail

# Restrict deterministic rules (omit IMAGES to keep images)
MARCUT_RULE_FILTER=EMAIL,PHONE,SSN,URL,IP,ORG,LOC \
  marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced
```

Batch processing example:
```bash
mkdir -p runs
for f in *.docx; do
  base="${f%.docx}"
  marcut redact --in "$f" --out "runs/${base}_redacted.docx" --report "runs/${base}_report.json" --mode enhanced
  echo "done: $f"
done
```

Audit report summary example:
```bash
python - <<'PY'
import json
from collections import Counter
data = json.load(open("runs/out_report.json"))
counts = Counter(span["label"] for span in data.get("spans", []))
for label, count in sorted(counts.items()):
    print(f"{label}: {count}")
PY
```

Scrub report quick view:
```bash
sed -n '1,80p' runs/out_scrub_report.json
```

Advanced metadata control example:
```bash
MARCUT_METADATA_ARGS="--no-clean-author --no-clean-title --no-clean-hyperlinks" \
  marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode rules
```

### Output Paths and Naming (CLI)

- `--out` and `--report` are required and fully explicit.
- The scrub report defaults to the same folder as `--report` or `--out`.
- If the report name ends with `_report.json`, the scrub report name becomes `_scrub_report.json`.
- You can override the scrub report location with `MARCUT_SCRUB_REPORT_PATH`.

Example:
```bash
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced
# Scrub report: runs/out_scrub_report.json
```

### Exit Codes

- `0`: success.
- `1`: parameter/validation failure or generic error.
- `2`: pipeline error with an error report JSON.
- `3`: unexpected failure.
- `130`: cancelled by user (Ctrl+C).

## Configuration and Overrides

### Environment Variables

Core runtime
- `OLLAMA_HOST`: host:port for Ollama (CLI and Python pipeline). Default is `127.0.0.1:11434`.
- `MARCUT_OLLAMA_HOST`: host:port used by the macOS app (set alongside `OLLAMA_HOST`).
- `MARCUT_RULE_FILTER`: comma-separated rule labels (see Rule Filter Details).
- `MARCUT_EXCLUDED_WORDS_PATH`: path to excluded words file.
- `MARCUT_SYSTEM_PROMPT_PATH`: path to system prompt file (applies to the classic extractor).
- `MARCUT_METADATA_ARGS`: space-separated metadata cleaning flags (advanced).
- `MARCUT_SCRUB_REPORT_PATH`: override path for the scrub report JSON.
- `MARCUT_DEBUG_PATH=1`: print Python `sys.path` at startup (advanced diagnostics).

App diagnostics
- `MARCUT_USE_PYTHONKIT=false`: force CLI fallback instead of in-process PythonKit.
- `MARCUT_TRACE_PY_SETUP=1`: verbose Python warm-up logging.
- `MARCUT_DISABLE_PY_TIMEOUTS=1`: disable Python warm-up safeguards.
- `MARCUT_FORCE_DIAGNOSTIC_WINDOW=1`: always show launch diagnostics.

### Rule Filter Details

`MARCUT_RULE_FILTER` is a comma-separated list of rule labels. If not set, all rules are enabled.

Deterministic rule labels:
- EMAIL
- PHONE
- SSN
- MONEY
- NUMBER
- DATE
- ACCOUNT
- CARD
- URL
- IP
- ORG
- LOC
- SIGNATURE
- IMAGES

Notes
- The LOC rule is a strict address detector, not a full geo-entity recognizer.
- The SIGNATURE rule extracts names from lines starting with `Name:`.
- Disabling a rule affects only deterministic scanning, not AI extraction.

### Excluded Words

`excluded-words.txt` is a line-based list of terms or regex patterns to exclude from redaction.

Rules
- Lines starting with `#` are comments.
- Each non-empty line is interpreted as a literal term or regex.
- Exclusions apply to deterministic rules and AI validation.

Example file:
```
# Do not redact these terms
Acme Corporation
Project Titan
\bFY2024\b
```

App locations
- App Group path: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOverrides/`
- Fallback path: `~/Library/Application Support/MarcutApp/Overrides/`

Files
- `excluded-words.txt`
- `system-prompt.txt`

### System Prompt Override

- The system prompt override is used by the classic extractor (Balanced mode).
- Enhanced mode uses a built-in prompt and ignores this override.
- Use with care; poorly scoped prompts can increase false positives.

### Metadata Cleaning Controls

Metadata scrubbing is part of every redaction run.

Defaults
- Most metadata fields are cleaned by default.
- Created and modified dates are preserved by default.
- Hardening actions (removing hyperlinks, RSIDs, OLE objects) are enabled by default.

Advanced control
- Use `MARCUT_METADATA_ARGS` to disable specific cleaning actions.
- Flags are in the form `--no-clean-<name>` and are space-separated.
- A special flag `--preset-none` is recognized by the metadata-only scrub path and preserves all metadata.
- For normal redaction runs, disable specific fields instead of using `--preset-none`.

Example:
```bash
MARCUT_METADATA_ARGS="--no-clean-author --no-clean-title --no-clean-hyperlinks" \
  marcut redact --in input.docx --out out.docx --report out_report.json --mode rules
```

### Metadata Cleaning Flag Reference

App Properties (docProps/app.xml)
- `--no-clean-company`: preserve Company field.
- `--no-clean-manager`: preserve Manager field.
- `--no-clean-editing-time`: preserve Total Editing Time.
- `--no-clean-application`: preserve Application name.
- `--no-clean-app-version`: preserve App Version.
- `--no-clean-template`: preserve Template.
- `--no-clean-hyperlink-base`: preserve Hyperlink Base.
- `--no-clean-statistics`: preserve document statistics (words, pages, etc).
- `--no-clean-doc-security`: preserve Document Security flag.
- `--no-clean-scale-crop`: preserve Scale Crop setting.
- `--no-clean-links-up-to-date`: preserve Links Up-to-Date flag.
- `--no-clean-shared-doc`: preserve Shared Document flag.
- `--no-clean-hyperlinks-changed`: preserve Hyperlinks Changed flag.

Core Properties (docProps/core.xml)
- `--no-clean-author`: preserve Author.
- `--no-clean-last-modified-by`: preserve Last Modified By.
- `--no-clean-title`: preserve Title.
- `--no-clean-subject`: preserve Subject.
- `--no-clean-keywords`: preserve Keywords.
- `--no-clean-comments`: preserve Comments.
- `--no-clean-category`: preserve Category.
- `--no-clean-content-status`: preserve Content Status.
- `--no-clean-created-date`: preserve Created date.
- `--no-clean-modified-date`: preserve Modified date.
- `--no-clean-last-printed`: preserve Last Printed.
- `--no-clean-revision`: preserve Revision number.
- `--no-clean-identifier`: preserve Identifier.
- `--no-clean-language`: preserve Language.
- `--no-clean-version`: preserve Version.

Custom Properties
- `--no-clean-custom-props`: preserve Custom Properties and custom XML.

Document Structure
- `--no-clean-review-comments`: preserve review comments.
- `--no-clean-track-changes`: preserve existing track changes.
- `--no-clean-rsids`: preserve RSIDs (revision identifiers).
- `--no-clean-guid`: preserve document GUID.
- `--no-clean-spell-grammar`: preserve spell/grammar state.
- `--no-clean-doc-vars`: preserve document variables.
- `--no-clean-mail-merge`: preserve mail merge data.
- `--no-clean-data-bindings`: preserve data bindings.
- `--no-clean-doc-versions`: preserve document versions.
- `--no-clean-ink-annotations`: preserve ink annotations.
- `--no-clean-hidden-text`: preserve hidden text.
- `--no-clean-invisible-objects`: preserve invisible objects.
- `--no-clean-headers-footers`: preserve headers and footers.
- `--no-clean-watermarks`: preserve watermarks.

Embedded Content
- `--no-clean-thumbnail`: preserve document thumbnail.
- `--no-clean-hyperlinks`: preserve hyperlink URLs.
- `--no-clean-alt-text`: preserve image alt text.
- `--no-clean-ole`: preserve OLE objects.
- `--no-clean-macros`: preserve VBA macros.
- `--no-clean-signatures`: preserve digital signatures.
- `--no-clean-printer`: preserve printer settings.
- `--no-clean-fonts`: preserve embedded fonts.
- `--no-clean-glossary`: preserve glossary/autotext.
- `--no-clean-fast-save`: preserve fast save data.

Advanced Hardening
- `--no-clean-ext-links`: preserve external link paths.
- `--no-clean-unc-paths`: preserve UNC paths.
- `--no-clean-user-paths`: preserve user profile paths.
- `--no-clean-internal-urls`: preserve internal URLs.
- `--no-clean-ole-sources`: preserve OLE source paths.
- `--no-clean-exif`: preserve image EXIF metadata.
- `--no-clean-style-names`: preserve custom style names.
- `--no-clean-chart-labels`: preserve chart labels.
- `--no-clean-form-defaults`: preserve form field defaults.
- `--no-clean-language-settings`: preserve language settings in styles.
- `--no-clean-activex`: preserve ActiveX controls.

### Metadata Scrub Reports

A scrub report is written alongside the audit report:
- If the report path ends with `_report.json`, the scrub report is `*_scrub_report.json` in the same folder.
- If not, the scrub report uses the report file stem plus `_scrub_report.json`.
- You can override the path with `MARCUT_SCRUB_REPORT_PATH`.

The scrub report includes grouped entries with before/after values and status (cleaned, unchanged, preserved).

## Technical Reference (Developer)

### Pipeline Overview

The redaction pipeline applies deterministic rules, optional LLM extraction, and metadata hardening in a single run. The same pipeline is used by the macOS app and the CLI.

### Step-by-step Pipeline

1. Load DOCX and accept existing tracked changes.
2. Extract full text from all supported document parts.
3. Run deterministic rules for structured PII.
4. Run AI extraction (Enhanced or Balanced).
5. Snap spans to token boundaries to avoid mid-word redactions.
6. Apply consistency pass to catch exact repeated entities.
7. Merge overlaps with label priority.
8. Apply track changes with redaction tags.
9. Harden the document (hyperlinks, objects, RSIDs, thumbnails, optional images).
10. Scrub metadata and write JSON reports.

### Chunking and Overlap

- Chunking uses character counts derived from token settings.
- The pipeline converts `chunk_tokens` and `overlap` to characters by multiplying by 4.
- Small documents (currently around 4000 characters) are processed as a single chunk to reduce fragmentation.
- Increasing overlap reduces boundary misses but increases compute time.

### Span Merging and Priority

Overlapping spans are merged using a priority order:
- Highest: EMAIL, PHONE, SSN, CARD, ACCOUNT, URL, IP
- Medium: NAME, ORG, BRAND
- Lower: MONEY, NUMBER, DATE

When overlaps occur:
- The span with higher priority label wins.
- The merged span extends to cover the full union range.
- Entity IDs are preserved if the higher-priority span had one.

### Token Boundary Snapping

Before applying redactions, spans are expanded to alphanumeric boundaries. This avoids partial-word redactions such as `20[DATE]25`.

### Span Offsets and Text Flattening

- The pipeline flattens document text into a single string for scanning.
- Paragraphs and other block elements are separated by newline characters.
- Offsets in the audit report point into this flattened text, not Word XML positions.
- Headers, footers, tables, and text boxes are included in document order.
- Use the span `text` field for quick verification; rely on the DOCX output for exact placement.

### Progress Phases and Estimation

Progress updates are estimated using word count and document complexity. Phase display names include:

- Loading Document
- Detecting Structured Data
- Analyzing Document
- AI Entity Extraction
- Validating Entities
- Merging & Clustering
- Generating Track Changes

Estimated remaining time is heuristic and varies with model size, chunking, and hardware speed.

### Deterministic Rule Engine Details

Deterministic rules are regex-based and high confidence.

Rule labels and notes
- EMAIL: RFC-like email patterns, case-insensitive.
- PHONE: US and international phone patterns with separators.
- SSN: US SSN in `###-##-####` format.
- MONEY: currency amounts, ISO codes, and bracketed dollars.
- NUMBER: bracketed numeric quantities like `[1,200]`.
- DATE: numeric, ISO, and written dates.
- ACCOUNT: bank/account digit sequences (8 to 20 digits).
- CARD: credit/debit numbers (13 to 19 digits) with Luhn validation.
- URL: HTTP/HTTPS/FTP URLs, mailto, and bare domains with paths. Trailing punctuation is trimmed.
- IP: IPv4 addresses.
- ORG: company names ending with legal suffixes (Inc., LLC, Ltd., etc).
- LOC: strict address detector (street number + street type + city/state/zip style patterns).
- SIGNATURE: names extracted from lines starting with `Name:`.
- IMAGES: removes all images in the output (handled during hardening).

Excluded words and regex patterns apply to ORG, NAME, and LOC matches.

### AI Extraction and Validation

Enhanced mode uses a multi-pass pipeline:
- Rule-based detection for structured PII.
- LLM extraction for names, organizations, locations, and context-sensitive entities.
- Selective validation for uncertain spans using surrounding context.
- Consistency pass that rescans for exact matches of confirmed entities.

Balanced mode uses a legacy single-pass LLM detector and does not validate.

LLM tuning controls:
- `temperature`: sampling variability (lower is more deterministic).
- `seed`: helps reproducibility.
- `chunk_tokens` and `overlap`: control chunk size and redundancy.

### Entity IDs and Tag Generation

- Spans are assigned stable IDs like `NAME_1`, `ORG_2`, `EMAIL_1`.
- IDs are stable within a single document run and increment per label.
- Tags are inserted in the DOCX as track change insertions.

### JSON Audit Report Schema

Top level
- `created_at`: ISO UTC timestamp.
- `input_sha256`: SHA256 hash of the input file.
- `model`: model identifier used for the run.
- `spans`: list of redacted spans.

Span object
- `start`: integer offset in flattened text.
- `end`: integer offset in flattened text.
- `label`: label string (EMAIL, NAME, etc).
- `entity_id`: stable ID or null.
- `confidence`: float from 0.0 to 1.0.
- `source`: `rule`, `model`, `rule_signature`, or `consistency_pass`.
- `text`: matched text (truncated to 120 characters).
- `validated`: boolean or null.
- `validation_result`: string or null (for example `FULL_REDACT`).

### Error Report Schema

If redaction fails, the report file contains a minimal error payload:

- `status`: `error`.
- `input`: input file path.
- `error_code`: stable error identifier.
- `message`: human-readable description.
- `technical_details`: extra debugging detail.

Example:
```json
{
  "status": "error",
  "input": "/path/to/input.docx",
  "error_code": "AI_SERVICE_UNAVAILABLE",
  "message": "AI service is not available or cannot be reached",
  "technical_details": "Ollama service error: connection refused"
}
```

### Scrub Report Schema

The scrub report is a structured summary with groups and before/after values.

Top level
- `summary.total_cleaned`: number of fields cleaned.
- `summary.total_preserved`: number of fields preserved.
- `groups`: dictionary of groups.

Group entry
- `field`: human-readable field name.
- `before`: original value (string summary).
- `after`: new value (string summary).
- `status`: `cleaned`, `unchanged`, or `preserved`.

Group names include:
- App Properties
- Core Properties
- Custom Properties
- Document Structure
- Embedded Content
- Advanced Hardening

### Scrub Report Field Details

App Properties fields
- Company
- Manager
- Total Editing Time
- Application
- App Version
- Template
- Hyperlink Base
- Document Statistics
- Document Security
- Thumbnail Settings
- Shared Document Flag
- Links Up-to-Date Flag
- Hyperlinks Changed Flag

Core Properties fields
- Author
- Last Modified By
- Title
- Subject
- Keywords
- Comments
- Category
- Content Status
- Created Date
- Modified Date
- Last Printed
- Revision Number
- Identifier
- Language
- Version

Custom Properties fields
- Custom Properties & Custom XML

Document Structure fields
- Review Comments
- Track Changes
- RSIDs
- Document GUID
- Spell/Grammar State
- Document Variables
- Mail Merge Data
- Data Bindings
- Document Versions
- Ink Annotations
- Hidden Text
- Invisible Objects
- Headers & Footers
- Watermarks

Embedded Content fields
- Thumbnail Image
- Hyperlink URLs
- Alt Text on Images
- OLE Objects
- VBA Macros
- Digital Signatures
- Printer Settings
- Embedded Fonts
- Glossary/AutoText
- Fast Save Data

Advanced Hardening fields
- External Link Paths
- Network (UNC) Paths
- User Profile Paths
- Internal URLs
- OLE Source Paths
- Image EXIF Data
- Custom Style Names
- Chart Labels
- Form Field Defaults
- Language Settings
- ActiveX Controls

### Model and Input Safety

Input validation
- Input file must exist and end with `.docx`.
- Output directories are created if missing.

Model name validation
- Safe characters only for model IDs (letters, numbers, `_`, `-`, `.`, `:`).
- File paths for `.gguf` models are allowed but shell metacharacters are rejected.

Rules-only safety
- Rules-only mode forces a `mock` backend to avoid any model calls.

### Logging and Encoding Details

- The pipeline normalizes some Unicode characters in console output to avoid encoding errors.
- Document content is not modified by logging normalization.
- `--debug` emits additional details, including span counts and pipeline phases.
- Debug logs may contain snippets of document text.

### Repository Layout (High Level)

- `src/python/marcut`: Python redaction pipeline and CLI.
- `src/swift/MarcutApp`: SwiftUI app, PythonKit bridge, and UI.
- `tests`: Python test suite.
- `docs`: developer and release notes.

### Key Python Modules

- `pipeline.py`: core redaction pipeline orchestration.
- `rules.py`: deterministic regex rules and rule filtering.
- `model.py`: classic LLM detector (Balanced mode).
- `model_enhanced.py`: enhanced extraction and validation.
- `docx_io.py`: DOCX I/O, track changes, metadata scrubbing, and hardening.
- `docx_revisions.py`: acceptance of existing revisions.
- `report.py`: JSON audit report writer.
- `chunker.py`: text chunking utilities and small-doc threshold.
- `progress.py`: progress tracking and time estimation.
- `confidence.py`: confidence combination heuristics.
- `cluster.py`: entity clustering helpers.
- `ollama_manager.py`: Ollama model management helpers.
- `preflight.py`: backend readiness checks.
- `llm_timing.py`: LLM sub-phase timing helpers.
- `unified_redactor.py`: shared entry point for CLI and GUI.

### Swift Integration (High Level)

- The macOS app uses PythonKit to call the Python pipeline directly.
- Progress updates are parsed from `MARCUT_PROGRESS` and `MARCUT_STATUS` lines.
- The GUI and CLI both use the same unified redactor entry point.

### Sandboxed Paths and App Group

Common paths used by the app:
- Models: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/models/`
- Overrides: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOverrides/`
- Logs: `~/Library/Group Containers/group.com.marclaw.marcutapp/Library/Application Support/MarcutApp/logs/`
- Staging: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/Work/Staging/`

## Security and Privacy

### Local-Only Processing

- Redaction happens locally on your machine.
- The only network activity is for model downloads or if you explicitly point to a remote Ollama host.

### Network Access Summary

- Model downloads require network access.
- Inference uses a local Ollama server on `127.0.0.1` by default.
- If you configure a remote `OLLAMA_HOST`, document content is sent to that host.

### Using Remote Ollama Hosts

Remote Ollama hosts can be useful in a secure internal network, but they transmit document content over the network. Use only if policy allows it, and consider TLS and firewall rules.

### Metadata Reduction and Hardening

Marcut hardens output documents by:
- Scrubbing hyperlink targets (converted to plain text).
- Removing RSIDs (revision identifiers).
- Replacing embedded objects with placeholder text.
- Removing comments and custom XML parts.
- Resetting core properties (author, title, subject, comments).
- Removing thumbnails from the DOCX package.
- Optionally deleting all images when `IMAGES` is enabled.

### Temporary Files

macOS app
- Uses a staging directory under the app support container (`Work/Staging`).
- Input files are copied into staging for sandbox-safe processing.
- Staging artifacts are removed after each run.

CLI
- Processes input directly and writes only to the output paths you provide.
- Debug logs are written to `/tmp` when `--debug` is enabled.

### Permissions and macOS Prompts

The macOS app may request:
- Access to Documents, Downloads, or Desktop for importing and saving files.
- Notification permission for completion banners.
- Local network access for the embedded Ollama service.

If permission is denied, you can grant it later in macOS System Settings.

## Troubleshooting

### Common Errors

- "Only DOCX files are supported" or "corrupt DOCX package"
  - Ensure the input is a real `.docx` and not a `.doc` or renamed PDF.

- "AI service is not available" or "Ollama not running"
  - Start `ollama serve` (CLI) or relaunch the app (macOS).
  - Check `OLLAMA_HOST` if you use a custom port.

- "AI model is not available"
  - Download the model (`ollama pull <model>` or Manage Models in the app).

- "AI processing timed out"
  - Use a smaller model, reduce `chunk-tokens`, or switch to Rules only.

- "Cannot write to selected destination"
  - Choose a different output folder with write permission.

- "Python runtime unavailable" (macOS app)
  - Restart the app; reinstall if the embedded runtime failed to load.

- "Unsupported backend" (macOS app)
  - The app supports `ollama` and `mock` only; switch backend to Ollama.

### Missing Redactions

If redactions are missing:
- Confirm the rule is enabled (for deterministic rules).
- Use Enhanced mode to add AI extraction.
- Increase `chunk-tokens` or `overlap` if entities cross chunk boundaries.
- Check `excluded-words.txt` for overly broad patterns.
- Try a larger model or a different model family.

### Over-Redaction

If redactions are too aggressive:
- Disable the specific deterministic rule(s).
- Add excluded terms or regex patterns.
- Lower the temperature to reduce creative model outputs.
- Review track changes and reject false positives.

### Model and Backend Problems

- Ollama model downloads fail: verify network access and disk space.
- llama.cpp errors: verify the `.gguf` path and reduce `--threads` if the system is under memory pressure.
- LLM timing is slow: check if the model is still loading on first run.

### Output and Permission Issues

- If output files are empty or missing, verify the output path and permissions.
- If the app cannot access a folder, grant permissions in System Settings.
- For sandboxed app runs, use a folder you have explicitly chosen in the file dialog.

### Performance Tips

- Use smaller models for faster results (`llama3.2:3b` is faster than `llama3.1:8b`).
- Reduce `chunk-tokens` for large documents to avoid timeouts.
- Use Rules only for the fastest deterministic scan.
- Disable `IMAGES` to avoid removing images if you do not need that step.

### Report and Log Diagnostics

- Audit report: check `spans` for label distribution and confidence.
- Scrub report: confirm metadata fields were cleaned as expected.
- Debug log: search for `MARCUT_PIPELINE` and `ERROR` markers.
- Use `--timing` or `--llm-detail` to find bottlenecks.

## FAQ

Q: Can I redact PDFs or scanned documents?
A: No. Only `.docx` is supported. Convert to DOCX first, and note that images are not OCRed.

Q: Are existing track changes preserved?
A: No. Existing track changes are accepted and flattened before redaction.

Q: Does Marcut modify the original file?
A: No. It writes a new output file at the path you specify.

Q: Can I run without any AI?
A: Yes. Use Rules only mode or the `mock` backend.

Q: Does Marcut scan headers, footers, footnotes, and text boxes?
A: Yes. These elements are included in the extracted text and scanned.

Q: Why are images missing in my output?
A: The `IMAGES` rule removes all images. Disable it if you want to keep images.

Q: Why are hyperlinks no longer clickable?
A: Metadata hardening removes hyperlink URLs by default. Use `--no-clean-hyperlinks` to preserve them.

Q: Where do models live in the app?
A: `~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/models/`.

Q: What does it mean when the report contains `"status": "error"`?
A: The run failed. Check `error_code` and `technical_details` and re-run after fixing the cause.

Q: How can I keep author and title metadata?
A: Use `MARCUT_METADATA_ARGS` with `--no-clean-author` and `--no-clean-title`.

Q: Are model outputs deterministic?
A: Lower temperatures and fixed seeds reduce variability, but model versions can still change outputs.

Q: Is the JSON report enough for audit?
A: It is helpful, but the redacted DOCX with track changes is the source of truth.

Q: Does `MARCUT_RULE_FILTER` affect AI extraction?
A: No. It only affects deterministic rules; AI extraction still runs in Enhanced mode.

Q: Can I customize what the AI looks for?
A: You can adjust mode, model, temperature, and exclusions. The system prompt override affects only the classic extractor.

Q: Why are some names missed in Balanced mode?
A: Balanced uses a single-pass model without validation. Enhanced mode is more consistent.

Q: Where is the scrub report stored?
A: By default it sits next to the audit report with a `_scrub_report.json` suffix.

Q: Can I review without Microsoft Word?
A: Any editor that shows track changes can work, but Word is the most reliable.

## Glossary

- DOCX: Microsoft Word OpenXML document format.
- Track Changes: Word feature that records deletions and insertions for review.
- Redaction Tag: Bracketed placeholder inserted in the output (for example `[SSN_1]`).
- Span: A start and end offset into the flattened text.
- LLM: Large language model used for entity extraction.
- Ollama: Local model server used for inference and downloads.
- GGUF: File format for llama.cpp models.
- Rules Only: Deterministic PII detection without model calls.
- Enhanced: Rules plus LLM extraction and validation.
- Balanced: Legacy hybrid mode with a single LLM pass.
- JSON Audit Report: Machine-readable report of detected spans and metadata.
- Scrub Report: Report describing which metadata fields were cleaned.
- Entity ID: Stable identifier such as `NAME_1` or `ORG_2`.
- Consistency Pass: Re-scan to catch repeated exact matches of confirmed entities.
- Security-Scoped Bookmark: macOS permission mechanism for file access.

## Versioning and Release Notes

- macOS app version is shown in About MarcutApp.
- CLI version is defined in `pyproject.toml` (use `pip show marcut`).
- Project history lives in `CHANGELOG.md` and `docs/RELEASE_NOTES_v0.2.2.md`.

## Licensing and Third-Party Notices

- Project license: see `LICENSE`.
- Third-party licenses are stored in the embedded Python packages under `MarcutApp/Sources/MarcutApp/python_site/*/licenses/`.
- Ollama and model licenses are managed by their respective providers.
