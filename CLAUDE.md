# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Marcut is a local-first DOCX redaction tool that produces Microsoft Word documents with track changes. It uses a hybrid approach combining rules-based detection and LLM analysis for high-precision PII redaction. The application is packaged as a native macOS app with embedded Python runtime and Ollama AI service.

## Agent Rules

- Never push or offer to push to any remote unless explicitly asked by the user.

## Current Status (July 2026)

Version `0.5.97`. The PythonKit + BeeWare architecture (see `docs/historical/claude_md_status_september_2024.md` for the original migration/debugging history) has been stable in production since; a real Developer ID signed, notarized, stapled, Gatekeeper-verified DMG has been built and verified end to end.

The pre-public-beta remediation stack (T0-T14, see `docs/backlog/pre_public_beta_audit_remediation_2026-05-13.md`) is complete: DOCX send-choice consolidation, remote-Ollama lockdown, owner-only report permissions, `--llm-detail` parity, GGUF/`--threads` forwarding, a cancellation/deadline system (`marcut/cancellation.py`), transactional artifact writes, model-download readiness checks, metadata/report size budgets, large-DOCX consistency-pass limits, fail-closed notarization, shipped-bundle SBOM coverage, and entitlement/governance verification.

13 additional features have also shipped: settings search bar, native download-completion notifications, redaction-settings profile export/import, a "Retry Failed" button, an in-app log viewer, a live excluded-word match preview, batch ETA display, batch job persistence/resume, a centralized `DefaultsKey` UserDefaults enum, unified model-name-parsing between `gui.py` and `PythonBridge.swift`, and a `models.json` model catalog (see Core Architecture below).

See `docs/CHANGELOG.md` for the full history and `docs/BACKLOG.md` for what's still open (several items have design-spike docs under `docs/design/` that should be read before implementation — a few carry real correctness/privacy risk if built without that analysis).

## Core Architecture

### Main Components

All Python sources live under `src/python/marcut/`, all Swift sources under `src/swift/MarcutApp/Sources/MarcutApp/`.

- **pipeline.py** - Core redaction pipeline (`run_redaction()`), transactional artifact staging, metadata/report size budgets, consistency-pass candidate limits
- **model.py** - Ollama extraction helpers; deadline-bounded HTTP requests
- **model_enhanced.py** - Enhanced two-pass LLM extractor/validator with document-level context, cancellation-aware
- **cancellation.py** - Shared processing-deadline primitive (`ProcessingDeadlineExceeded`, `MARCUT_PROCESSING_DEADLINE_MONOTONIC`)
- **rules.py** - Rule-based structured PII detection (emails, phones, credit cards, dates, money)
- **docx_io.py** - Microsoft Word track changes writer, metadata scrubbing/hardening using revision elements
- **model_config.py** - Loader for the shared `models.json` model catalog
- **gui.py** - Tkinter GUI (still used by `bootstrapper.py`/`native_setup.py`, not the primary macOS app UI)
- **cli.py** - Command-line interface with `marcut` script entry point
- **unified_redactor.py** - Shared entry point used by both the CLI and the Swift app
- **bootstrapper.py** - Application bootstrapping and embedded Ollama management
- **ollama_manager.py** - Ollama lifecycle management and model download
- **PythonKitBridge.swift** - PythonKit integration: BeeWare framework init, timeout system, deadline-marker env var
- **PythonBridge.swift** - Ollama process management, model download/readiness, notifications; used alongside PythonKit, not a legacy fallback
- **ModelCatalog.swift** / **BundleResourceLocator.swift** - Swift-side loader for the shared `models.json` catalog

### Processing Pipeline
1. Rule-based detection for structured PII
2. Text chunking and enhanced LLM analysis via Ollama
3. Filtering entities where `needs_redaction=true`
4. Overlap merging with `_merge_overlaps()` preferring higher-ranked labels
5. NAME/ORG clustering via `ClusterTable` for stable entity IDs
6. Track changes generation with replacements like `[NAME_3]`, `[ORG_1]`
7. DOCX output and JSON audit report generation

## Development Commands

### Python Environment Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### CLI Usage
```bash
# Enhanced pipeline (recommended)
marcut redact \
  --in "sample-files/Consent.docx" \
  --out runs/out.docx \
  --report runs/out.json \
  --backend ollama \
  --model qwen2.5:14b \
  --enhanced \
  --debug
```

### Ollama Setup
```bash
# Install and start Ollama
brew install ollama
ollama serve &
ollama pull qwen2.5:14b
```

### Swift App Building
```bash
# Set up BeeWare Python framework (one-time setup)
bash build-scripts/setup_beeware_framework.sh

# Build Swift app
swift build --package-path src/swift/MarcutApp

# Release preflight (tests, SBOM, dependency audit, markdown links, version-sync, secrets check)
bash scripts/release_preflight.sh

# Create a Developer ID signed, notarized DMG (requires a Developer ID
# Application cert and notarization credentials at ~/.config/marcut/notarize.env)
bash scripts/sh/build_devid_release.sh

# Output: .marcut_artifacts/ignored-resources/MarcutApp-v<version>-AppStore.dmg
```

Canonical entrypoint for humans (menu-driven, not scriptable): `python3 build_tui.py`.

### BeeWare Framework Setup
```bash
# Download and configure BeeWare Python 3.11 framework
bash build-scripts/setup_beeware_framework.sh

# Installs:
# - src/swift/MarcutApp/Sources/MarcutApp/Frameworks/Python.framework (Universal2 framework)
# - src/swift/MarcutApp/Sources/MarcutApp/python_site/ (Python dependencies)
# - Proper code signing for all native extensions
```


## Configuration

### Project Structure
- **pyproject.toml** - Python project configuration with dependencies
- **setup.py** - legacy py2app configuration; not the shipped packaging path (PythonKit + BeeWare is primary, see Packaging Specifics below)
- **build-scripts/** - Build scripts, entitlements, and app bundle configuration (`config.json`, gitignored; copy from `config.example.json`)
- **docs/** - Documentation, including USER_GUIDE.md, DEVELOPER_GUIDE.md, TECHNICAL_ARCHITECTURE.md, and design spikes under `docs/design/`
- **sample-files/** - Test DOCX files for validation
- **assets/excluded-words.txt** and **assets/help.md** - canonical sources mirrored into both the Python package and the Swift app bundle (see `assets/models.json` for the same pattern with the model catalog)

### Key Dependencies

**Swift Framework Integration**:
- **PythonKit** - Swift-Python interoperability (via Swift Package Manager)
- **BeeWare Python.framework** - Universal2 Python 3.11 runtime for macOS
- **Deep Code Signing** - All .so/.dylib files signed for App Store distribution

**Python Dependencies** (see `pyproject.toml` for constraints, `requirements-pinned.txt` for the exact shipped versions):
- python-docx - DOCX document manipulation
- rapidfuzz - Fast string matching
- pydantic - Data validation
- requests - HTTP client for Ollama API
- dateparser - Date parsing
- tqdm - Progress bars
- lxml - XML processing
- numpy - Numerical operations
- regex - Extended regex support

## Testing and Validation

### ⚠️ CRITICAL RULE: Test-Driven Development
**MANDATORY: When adding ANY new feature, you MUST update corresponding tests.**

**Required test updates for every feature addition:**
1. **Swift Features** → Update `src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`
2. **Python Features** → Update appropriate test files in `tests/` directory
3. **New Rules/Entities** → Update `tests/test_url_redaction.py` or create new test files
4. **Pipeline Changes** → Add integration tests and update existing test coverage
5. **UI Changes** → Add Swift unit tests for new UI components and state management

**Test Requirements:**
- All new functions must have corresponding unit tests
- UI changes must include tests for user interactions and state transitions
- New entity types must include detection, extraction, and redaction tests
- Performance-critical code must include performance regression tests
- Error handling paths must be tested with appropriate failure scenarios

**Test Execution:**
```bash
# Python test suite (463+ tests)
PYTHONPATH=src/python python3 -m pytest -q

# Swift test suite
swift test --package-path src/swift/MarcutApp

# Full release-readiness gate (both suites plus SBOM, dependency audit,
# markdown links, version-sync, secrets check)
bash scripts/release_preflight.sh
```

### Current Test Coverage
- **Swift Tests**: `src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`
- **Python Tests**: `tests/` -- rules, model/cancellation behavior, pipeline (including transactional writes and large-DOCX performance), metadata scrubbing, CLI, unified redactor, and more

### Integration Testing
`bash scripts/verify_bundle.sh <path-to-dmg>` runs artifact checks, embedded-spawn verification, and a mock redaction against a built DMG.

### Model Testing
Use `marcut/model_mock_llm.py` for testing without requiring live Ollama service.

## Important Notes

### LLM Requirements
- LLM detection is **required** for legal documents - rules alone miss names and organizations
- Recommended model: qwen2.5:14b
- Enhanced pipeline provides two-pass validation for higher precision
- All processing is local-first with no external API calls

### Packaging Specifics
- **Primary Architecture**: PythonKit + BeeWare Python.framework for App Store compatibility
- **Legacy Support**: py2app and PyInstaller approaches (deprecated in favor of PythonKit)
- **Embedded Ollama binary** for self-contained AI processing
- **Universal2 Framework**: ARM64/x86_64 native for Apple Silicon with no Rosetta dependency
- **Deep Code Signing**: All .so/.dylib files signed for macOS Gatekeeper and App Store
- **Professional DMG creation** with code signing and notarization support

### File Locations

The macOS app (sandboxed) and the source CLI use different locations:

- **macOS app**: `~/Library/Application Support/MarcutApp/` -- `models/`, `Overrides/` (excluded-words.txt, system-prompt.txt), `logs/`, `Work/Staging/`
- **Source CLI** (`marcut` installed via `pip install -e .`): `~/.marcut/` -- `config.json`, `models/`, `logs/`

Notarization credentials for release builds live at `~/.config/marcut/notarize.env` (owner-only permissions, gitignored, never committed).
