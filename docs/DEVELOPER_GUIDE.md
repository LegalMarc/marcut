# Marcut Developer Guide

## 🚨 MANDATORY ARCHITECTURE REQUIREMENT

**MarcutApp MUST use the PythonKit + BeeWare Python framework architecture.** This is not optional - all development must continue using this approach.

### ❌ PROHIBITED: Legacy Subprocess Architecture
The following approaches are **FORBIDDEN** and must not be used:
- `python_launcher.sh` subprocess calls
- `run_python.sh` subprocess execution
- System Python dependency (python3, python3.11, etc.)
- PyInstaller or py2app bundles
- Any subprocess-based Python execution

### ✅ MANDATORY: PythonKit + BeeWare Framework
All Python execution **MUST** use:
- **PythonKit** for Swift-Python integration
- **BeeWare Python.framework** (Python 3.11) for embedded runtime
- **Direct PythonKit calls** with no subprocess dependencies
- **Consolidated pathways** for CLI and GUI (same underlying architecture)

---

## Architecture Overview

### Core Design Principles
MarcutApp must always be:
- **App Store safe**: No subprocess execution, proper sandboxing
- **Self-contained**: Works without user-installed Python or Ollama
- **Apple Silicon native**: ARM64-optimized with no Rosetta dependency
- **Robust**: Fail-fast error handling with comprehensive logging
- **Performant**: Fast startup and processing times

### PythonKit + BeeWare Framework Architecture

#### 1. Swift Integration Layer
```swift
// PythonKitRunner - Core Python execution interface
public final class PythonKitRunner {
    // Direct Python execution via PythonKit
    func runEnhancedOllama(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        model: String,
        debug: Bool,
        mode: String,
        llmSkipConfidence: Double = 0.95,
        llmConcurrency: Int = 2,
        chunkTokens: Int = 500,
        overlap: Int = 120,
        temperature: Double = 0.1,
        seed: Int = 42,
        processingStepTimeout: TimeInterval? = nil,
        cancellationChecker: @escaping () -> Bool,
        heartbeat: ((PythonRunnerProgressUpdate) -> Void)? = nil
    ) -> PythonRunOutcome
}
```
(See `src/swift/MarcutApp/Sources/MarcutApp/PythonKitBridge.swift`. The function returns a `PythonRunOutcome`, not a `Bool` - it now also carries a `cancellationChecker` for cooperative cancellation and an optional `heartbeat` callback for progress updates, and `mode` selects between rules-only and the various rules+AI pipelines described in `docs/USER_GUIDE.md`.)

#### 2. Python Runtime Layer
```python
# Embedded Python 3.11 runtime (BeeWare framework)
# Location: Contents/Frameworks/Python.framework/Versions/3.11/
# Dependencies: Contents/Resources/python_site/
```

#### 3. Consolidated Processing Pipeline
```python
# Unified redaction pipeline for both CLI and GUI
marcut.pipeline.run_redaction_enhanced(
    input_path, output_path, report_path, model, debug
)
```

## Build System Architecture

### Development Build (Debug)
```bash
# Fast iteration development build (canonical via TUI)
./build_tui.py
# Choose: Build Workflows → Quick Debug Build (or “Dev Fast” preset)
# Uses: System Python for Swift compilation only
# Runtime: PythonKit with BeeWare framework (when available)
```

For everyday debugging you can skip the BeeWare refresh and keep turnaround under a minute by using the “Dev Fast” preset in `build_tui.py`.

### Production Build (Release)
```bash
# Complete production build with embedded framework (via TUI)
./build_tui.py
# Choose: Distribution & Notarization → Build App Store DMG
# Runtime: PythonKit with fully embedded BeeWare framework
```

Release policy:
- Use `scripts/sh/build_appstore_release.sh` as the only App Store build pipeline.
- `src/swift/MarcutApp/build_appstore.sh` is a compatibility wrapper and must not be treated as an independent build path.
- Keep `build-scripts/config.json` as the single source of truth for `version` and `build_number`.

### Critical: Framework Embedding
Production builds **MUST** include:
- **BeeWare Python.framework** (101MB) in `Contents/Frameworks/`
- **Python dependencies** (71MB) in `Contents/Resources/python_site/`
- **Deep code signing** for all .so/.dylib files
- **App Store entitlements** and sandbox compliance

## Implementation Details

### Swift-Python Integration
```swift
// AppDelegate.swift - Python runtime initialization
func applicationDidFinishLaunching(_ notification: Notification) {
    // Initialize PythonKit + BeeWare framework early
    AppDelegate.pythonRunner = try PythonKitRunner(logger: { msg in
        DebugLogger.shared.log(msg, component: "PythonRuntime")
    })
}

// CLI Processing
await appDelegate.runCLIMode(args: args)  // Uses PythonKit directly

// GUI Processing
bridge.processDocument(item, settings: settings)  // Uses PythonKit directly
```

### Python Execution Worker
- `PythonKitRunner` launches a dedicated `PythonWorkerThread` on startup. All CPython calls (`PyGILState_Ensure`, imports, pipeline work) are funneled through this thread so the interpreter is initialized and used on a single owner thread.
- The GUI queues documents sequentially: a document’s `Task` must finish before the next one starts. This prevents the serial BeeWare runtime from processing two jobs at once and eliminates the cancellation race we saw when multiple detached tasks tried to enter the GIL.
- The CLI uses the same runner so headless processing and the GUI stay in lockstep.

### Metadata-Only Scrub Stability
- The metadata-only path now clears any pending Python interrupts before invoking `pipeline.scrub_metadata_only(...)`. This avoids `swift_unexpectedError` crashes when a previous cancel left a pending `PyErr_SetInterrupt`.
- `DocumentRedactionViewModel` resets cancellation state at the start of a metadata-only run and only calls `cancelCurrentOperation()` when there are active processing tasks. This prevents spurious interrupts when users clear the list and immediately scrub the same file again.

### Processing Pipeline
```python
# src/python/marcut/pipeline.py - Core redaction logic
def run_redaction_enhanced(input_path, output_path, report_path, model, debug=False):
    """Unified pipeline for both CLI and GUI pathways"""
    # 1. Rule-based PII detection (marcut.rules)
    # 2. Enhanced LLM extraction via Ollama
    # 3. Overlap merging and entity clustering
    # 4. Track changes generation (DOCX)
    # 5. JSON audit report creation
```

### Python Reporting Modules

The reporting system uses shared utilities to generate interactive HTML reports.

#### Module Structure
```
src/python/marcut/
├── report.py          # Audit report (redaction results)
├── report_html.py     # Scrub report (metadata extraction)
└── report_common.py   # Shared utilities (imported by both)
```

#### Shared Utilities (`report_common.py`)
```python
from marcut.report_common import (
    escape_html,        # XSS-safe HTML escaping
    get_mime_type,      # Uses Python mimetypes module
    format_file_size,   # Human-readable sizes (e.g., "1.5 KB")
    get_binary_icon,    # Emoji icons by file type
    get_base_css,       # Dark/light theme CSS variables
    get_base_js,        # Collapsible section JavaScript
)
```

#### Unit Tests
```bash
# Run report utility tests (39 tests)
python3 -m pytest tests/test_report_common.py -v
```

### Runtime Overrides
- The macOS app now ships with an override manager (`UserOverridesManager`). Editors in the Settings sheet let users modify `excluded-words.txt` and the LLM system prompt.
- Overrides are stored under Application Support (`~/Library/Application Support/MarcutApp/Overrides/`) and mirrored via `MARCUT_EXCLUDED_WORDS_PATH` / `MARCUT_SYSTEM_PROMPT_PATH`. If App Group entitlements are enabled (custom builds), the overrides can live in the group container instead. Both the in-process PythonKit runner and CLI inherit these env vars so the same list/prompt applies everywhere.
- Python code watches the override files: if the timestamp changes, the regex cache and prompt string reload automatically without restarting the app.

### Cancellation & Processing Deadlines
`src/python/marcut/cancellation.py` provides a small cooperative-cancellation helper used to bound long-running Ollama HTTP calls and interrupt hanging extraction work:

```python
class ProcessingDeadlineExceeded(TimeoutError):
    """Raised when a configured processing deadline has elapsed."""

def processing_deadline() -> Optional[float]:
    """Reads MARCUT_PROCESSING_DEADLINE_MONOTONIC (a time.monotonic() timestamp)."""

def remaining_seconds(default: float, *, minimum: float = 0.25) -> float:
    """Returns min(default, time left until the deadline), raising
    ProcessingDeadlineExceeded if the deadline has already passed."""

def check_processing_deadline() -> None:
    """Raises ProcessingDeadlineExceeded if the deadline has elapsed; no-op otherwise."""
```

- The deadline is communicated via the `MARCUT_PROCESSING_DEADLINE_MONOTONIC` environment variable, expressed in `time.monotonic()` units (not wall-clock time), so it survives across the Swift/Python boundary without clock-skew issues.
- `remaining_seconds()` is used to size individual Ollama HTTP request timeouts so a single slow request cannot outlive the overall processing budget; `check_processing_deadline()` is called at safe checkpoints in the extraction loop so a stuck or slow model doesn't hang the app indefinitely.
- When no deadline is set (the env var is empty/unset), `processing_deadline()` returns `None` and the helpers behave as if there is no budget - existing callers without a caller-supplied deadline are unaffected.

### Streaming Progress (Intra-Chunk)
The progress bar advances at three layered granularities (whole-phase jumps, whole-chunk jumps, and token-level updates streamed from Ollama's streaming API during a single chunk's generation). The design, its interaction with the cancellation/deadline system, and the word-count-weighted batch ETA are documented in the design spike `docs/design/streaming_progress.md` (Option B shipped under issue #54). Read that doc rather than re-deriving the flow before touching the heartbeat/progress plumbing in `model.py`, `PythonKitBridge.swift`, or `DocumentRedactionViewModel`; it also covers the downstream heartbeat-timeout validation for issue #49.

### Model Catalog (`models.json`)
The list of supported/recommended Ollama models and their default parameters (temperature, validation skip-confidence, display metadata, etc.) lives in a single `models.json` file that is shipped in **three mirrored locations** which must stay byte-identical:
- `assets/models.json` - canonical source checked into the repo
- `src/python/marcut/models.json` - bundled resource for the Python package
- `src/swift/MarcutApp/Sources/MarcutApp/Resources/models.json` - bundled resource for the Swift app

Each side loads its own copy independently:
- **Python**: `src/python/marcut/model_config.py` loads and validates the catalog (`ModelConfig` dataclass, `list_models()`, `get_model()`, `default_model_id()`, `default_temperature()`, `default_skip_confidence()`). It raises `ModelCatalogError` if the file is missing, malformed, or the `defaultModel` doesn't match a listed model id.
- **Swift**: `ModelCatalog.swift` (`ModelCatalogEntry`, `ModelCatalogFile`, `ModelCatalog`) loads the same schema and exposes `entry(for:)` plus accent-color resolution for the UI. `BundleResourceLocator.swift` (`resolveDefaultResourceURL`) is what finds the bundled resource file at runtime, handling both the production app bundle and Swift Package/dev layouts.
- If you change the `models.json` schema, update the loader on **both** sides (`model_config.py` and `ModelCatalog.swift`) and keep all three copies in sync the same way `excluded-words.txt` is kept in sync - there is no automated sync step, so a diff of the three files should always be empty.

### Release Preflight
`scripts/release_preflight.sh` is the single script that gates release-readiness. It wraps the automatable subset of `docs/RELEASE_CHECKLIST.md`'s "Pre-Release Checks" into one command that fails fast on the first broken step:
1. Python test suite (`pytest`)
2. Swift test suite (`swift test`)
3. SBOM generate + check (`scripts/generate_python_sbom.py`)
4. Dependency vulnerability audit (`scripts/check_dependency_vulnerabilities.py`)
5. Markdown link check (`scripts/check_markdown_links.py`)
6. Version-sync check (`build-scripts/config.json` vs. the last tagged release)
7. Secrets check (`build-scripts/config.json` must not be tracked by git)

Run it with `bash scripts/release_preflight.sh`. By default the SBOM step is derived from the staged repo checkout; set `RELEASE_PREFLIGHT_BUNDLE_ROOT=/path/to/MarcutApp.app` to instead derive the SBOM from an actual built `.app` (passed through as `--bundle-root`), matching the release checklist's guidance to validate against the real bundle before shipping.

#### SBOM from a built bundle
`scripts/generate_python_sbom.py` accepts an optional `--bundle-root /path/to/MarcutApp.app`. When provided, the script reads the Python framework's `Info.plist`, the embedded `ollama` binary, and `Contents/Resources/python_site` from inside the built app bundle instead of the staged checkout paths, so the SBOM reflects exactly what got shipped (including any bundle-time transformations). Without `--bundle-root`, it falls back to the repo's staged `python_site` directory - useful for fast iteration, but not a substitute for a bundle-derived SBOM before a release.

### New Swift Support Files
A few small, focused Swift files back the newer app-level features described in `docs/USER_GUIDE.md`:
- **`DefaultsKey.swift`** - Centralizes `UserDefaults` key names (including the notification-preference flag) so call sites don't hand-roll string keys.
- **`BatchETACalculator.swift`** - `BatchETASample` + `BatchETACalculator.estimate(samples:remainingSizes:)` computes the batch "estimated time remaining" shown in the UI once enough documents have completed to produce a reliable estimate.
- **`PendingBatchJobStore.swift`** - `PendingBatchJobRecord` (Codable) plus `save`/`load`/`clear` persist the in-flight batch (document paths + settings) to `UserDefaults` so a mid-batch app quit can offer to resume on next launch.
- **`ExcludedWordMatcher.swift`** - A Swift port of `marcut.rules._is_excluded`'s matching logic (`CompiledEntry`, `MatchResult`, `compileEntries`/`compileAllEntries`, `match`) used to power the live excluded-word match preview in the Settings editor without round-tripping into Python.
- **`RedactionProfile`** (defined in `DocumentModels.swift`) - Codable bundle of `MetadataCleaningSettings` + redaction settings, with `RedactionProfile.decoded(from:)` for the Settings "Export Profile.../Import Profile..." JSON save/load feature.

### Error Handling & Logging
```swift
// Comprehensive timeout system with phase markers
PK_INIT_START → PK_FRAMEWORK_FOUND → PK_ENV_SET → PK_LIB_LOADED → PK_IMPORT_OK → PK_INIT_COMPLETE

// Fail-fast error handling
guard let cfg = locateFramework() else {
    throw PythonInitError.notFound  // Immediate failure, no retries
}
```

## Sandbox Compliance

### App Storage Container Usage
```
~/Library/Application Support/MarcutApp/
├── models/         # Ollama models
├── ollama/
│   ├── ollama-data/ # Ollama data files
│   └── tmp/        # Ollama temp files
├── Work/
│   └── Staging/    # CLI processing workspace
├── Input/          # Optional CLI input staging
├── Overrides/      # User override files
└── logs/           # App + Ollama logs
```
If App Group entitlements are enabled (custom builds), these paths can be mirrored under the group container; otherwise Application Support is used.

### File Access Requirements
- **App CLI inputs** (`MarcutApp --redact`): Must be placed under the app support container so the sandboxed helper can read them.
- **Python CLI inputs** (`marcut redact`): Read directly from the paths you pass in.
- **GUI inputs**: Accessed via security-scoped bookmarks when users select files.
- **Outputs**: Written to user-selected locations (GUI) or explicit output paths (CLI).

## Testing & Validation

### Test Suite Notes
- `python3 run_tests.py` uses the repo `venv/` interpreter if present; install pytest in the venv for full coverage: `venv/bin/python -m pip install pytest`.
- Metadata scrubbing coverage now includes a redaction-path scrub report check via `MARCUT_SCRUB_REPORT_PATH`.
- The metadata matrix script (`scripts/run_metadata_matrix.py`) auto-generates a minimal DOCX if `sample-files/Sample 123 Consent.docx` is missing; keep real sample files locally for higher-fidelity validation.
- The build TUI “Run Tests” menu delegates to `run_tests.py`, so the same behaviors apply there.

### PII Detection Accuracy (Precision/Recall) Eval
Detection-quality regressions are caught by an automated per-entity-type precision/recall
harness, in addition to the existing manual LLM benchmark tooling:

- **`tests/test_pii_eval_harness.py`** — builds a small synthetic, labeled DOCX corpus at
  test time (`tests/pii_eval/corpus.py` + `tests/pii_eval/labels.json`; nothing binary is
  committed) covering EMAIL, PHONE, SSN, CARD, MONEY, DATE, ORG, LOC, and NAME across the
  document body, a table cell, the header, and the footer. It runs the corpus through the
  **rules-only** pipeline (`mode="rules"`, no Ollama needed) and asserts per-type
  precision/recall against regression floors, printing a per-type table. This is the test
  that runs in CI (see the "smoke" job in `.github/workflows/ci.yml` and the full-suite
  `pytest -q` job in `.github/workflows/macos-build-verify.yml`).
- **`tests/pii_eval/run_eval.py`** — standalone runner for the *same* corpus, usable
  locally to eval the full two-pass LLM pipeline against a real Ollama model (not run in
  CI: it needs Ollama installed locally and isn't deterministic run-to-run):
  ```bash
  ollama serve &
  ollama pull qwen2.5:14b
  PYTHONPATH=src/python python3 -m tests.pii_eval.run_eval --mode llm --model qwen2.5:14b
  ```
  Run `--mode rules` (the default) to reproduce the CI gate locally without Ollama.
- **`tests/pii_eval/scoring.py`** — the shared scorer both the CI test and the standalone
  runner use. It matches gold entities against predicted audit-report spans by `(label, text)`
  using bidirectional substring containment (not exact offsets or exact string equality, which
  are too fragile for a synthetically-generated corpus), greedily so N identical expected
  entities require N distinct predicted spans, and emits per-label plus OVERALL
  precision/recall/F1 (`score_entities()` / `format_score_table()`).
- **`tests/benchmark/model_benchmark.py`** — pre-existing, broader model speed-vs-accuracy
  comparison tool (Ollama or GGUF, aggregate precision/recall/F1 against a hand-labeled
  real document); still the right tool for comparing models/prompts against a realistic
  document rather than the synthetic per-type corpus above.

### Malformed-DOCX Corpus & Property-Based Tests
Robustness against broken input and offset/merge invariants is covered by a generated corpus
of corrupt DOCX files plus Hypothesis-driven property tests. Nothing binary is committed — the
CI hygiene job forbids any tracked `.docx`/`.doc`/`.pdf`/`.dmg`, so both suites build their
inputs at test time.

- **`tests/malformed_docx_corpus.py`** — generator (no test cases of its own). Builds a small
  valid DOCX in memory with python-docx, then applies ZIP/XML-level corruption to produce a
  fixed set of variants: `truncated_zip`, `bad_content_types`, `mismatched_relationship_target`,
  and `undeclared_xml_entity`. `generate_corpus()` returns `{variant_name: bytes}`.
- **`tests/test_malformed_docx_corpus.py`** — feeds every variant through both
  `DocxMap.load_accepting_revisions` and the real `run_redaction()` entry point and asserts the
  pipeline fails *cleanly*: a classified `RedactionError` surfaced as a non-zero `(code, timings)`
  return with a `"status": "error"` / `"error_code": "DOC_LOAD_FAILED"` report, no partial/
  misleading output DOCX, no leftover staging temp files, no uncaught exception, and bounded
  wall-clock time (never hangs).
- **`tests/test_property_based.py`** — Hypothesis-based invariants over random text, random span
  placements, and random chunk sizes/overlaps: every `_merge_overlaps()` output span still
  satisfies `text[start:end] == span["text"]`, merged spans never overlap, and `make_chunks()`
  round-trips offsets and fully covers the input with no gaps. It `pytest.importorskip`s
  hypothesis, so it self-skips when the dev extra isn't installed.

Run them with:
```bash
# Hypothesis is a dev-only dependency (never shipped in the bundle); install the dev extra:
pip install -e ".[dev]"
PYTHONPATH=src/python python3 -m pytest tests/test_malformed_docx_corpus.py tests/test_property_based.py
```
The Hypothesis profile is selected via the `HYPOTHESIS_PROFILE` env var (see `tests/conftest.py`):
the default `ci` profile is derandomized (fixed seed, 100 examples) so property runs are
reproducible/flake-free; set `HYPOTHESIS_PROFILE=dev` for a faster, non-derandomized run (25
examples) while iterating.

### Continuous Integration Gates
Two workflows gate PRs; keep new tests wired into the right one:
- **`.github/workflows/ci.yml`** — a `hygiene` job (forbids committed `.docx`/`.doc`/`.pdf`/`.dmg`
  and `sample-files/` contents, checks `pyproject.toml` ↔ `build-scripts/config.example.json`
  version sync, and runs a Ruff error-tier lint gate `E9,F63,F7,F82` over `src/python tests`),
  plus a `smoke` job that runs the rules-only Python tests **including
  `tests/test_pii_eval_harness.py`** and a compile-only Swift build.
- **`.github/workflows/macos-build-verify.yml`** — installs the dev extra (`pip install -e ".[dev]"`,
  which pulls in hypothesis so the property tests actually run), then runs the dependency
  vulnerability scan, SBOM check, markdown-link check, and the full `pytest -q` suite plus Swift
  tests.

### CLI Testing
```bash
# Test CLI functionality (uses PythonKit directly)
swift run --package-path src/swift/MarcutApp MarcutApp --help
swift run --package-path src/swift/MarcutApp MarcutApp --diagnose
swift run --package-path src/swift/MarcutApp MarcutApp --redact --in file.docx --outdir output/
```

### Build Script Testing (Unified Runtime)
```bash
# Use the TUI to run the same test harness
./build_tui.py
# Choose: Run Tests → Full / Quick / URL suites
```

### Production Validation
```bash
# Validate production build includes BeeWare framework (via TUI)
./build_tui.py
# Choose: Distribution & Notarization → Build App Store DMG
```

## Development Workflow

### 1. Code Development
```bash
# Swift changes
cd src/swift/MarcutApp && swift build

# Python changes
# Test with system Python, but production uses BeeWare framework
```

### 2. Local Testing
```bash
# Debug build testing (PythonKit integration)
./build_tui.py
# Choose: Build Workflows → Quick Debug Build
```

### 3. Integration Testing
```bash
# Full pathway testing
./build_tui.py
# Choose: Run Tests → Full Test Suite
```

### 4. Production Validation
```bash
# Production build with embedded framework
./build_tui.py
# Choose: Distribution & Notarization → Build App Store DMG
```

## Framework Management

### BeeWare Framework Setup (One-time)
```bash
./setup_beeware_framework.sh
# Downloads: Python-3.11-macOS-support.b7.tar.gz (29MB)
# Compiles: All dependencies against BeeWare framework
# Installs: 101MB framework + 71MB python_site
# Signs: All native extensions for App Store distribution
```

### Framework Locations
- **Development**: `Contents/Frameworks/Python.framework/`
- **Production**: `build_swift/MarcutApp.app/Contents/Frameworks/Python.framework/`
- **Dependencies**: `Contents/Resources/python_site/` (lxml, numpy, python-docx, etc.)

## Ollama Integration

### LLM Processing Architecture
```swift
// OllamaService - Manages embedded Ollama binary
class OllamaService {
    // Embedded Ollama binary (no system dependency)
    // Pre-signed runner binary (extracted at build time)
    // Application Support container for models and data
    // HTTP API communication on localhost:11434
    // Automatic model download and management
}
```

### Pre-Signed Runner Architecture
To avoid macOS quarantine issues with runtime-extracted binaries, the Ollama runner is handled specially:
1. **Build Time**: The `ollama_llama_server` runner is extracted from the Ollama binary, signed with an ad-hoc signature, and bundled in `Contents/Resources/ollama_runners/metal/`.
2. **Runtime**: The app sets `OLLAMA_RUNNERS_DIR` to point to this bundled directory.
3. **Execution**: Ollama uses the pre-signed runner directly instead of trying to extract it to a temporary location, bypassing sandbox restrictions and "Operation not permitted" errors.
```

### Model Management
```bash
# Model download (uses embedded Ollama)
./MarcutApp --cli --download-model qwen2.5:14b

# Model storage (Application Support)
~/Library/Application Support/MarcutApp/models/
```

## Performance Considerations

### Optimization Requirements
- **Startup time**: PythonKit initialization < 1 second
- **Processing time**: Document redaction < 30 seconds for typical files
- **Memory usage**: Efficient Python object management
- **Disk space**: Complete package < 200MB (including models)

### Benchmarks
- **PythonKit initialization**: 0.12s (from PK_INIT_START to PK_INIT_COMPLETE)
- **Enhanced redaction**: 0.41s total processing time
- **Model download**: Variable depending on model size and network

## Troubleshooting

### Common Issues and Solutions

#### Signal 9 (SIGKILL) - RESOLVED
**Problem**: Subprocess-based architecture causing crashes
**Solution**: Use PythonKit + BeeWare framework (mandatory)

#### Framework Not Found - Expected in Debug
**Problem**: "Python.framework not found" in debug builds
**Solution**: This is expected - debug builds use system Python for compilation, runtime uses PythonKit when available

#### Sandbox Violations
**Problem**: File access outside Application Support container
**Solution**: Copy input files to the app support container before processing

#### Model Download Issues
**Problem**: Ollama connection failures
**Solution**: Check Application Support container permissions and network connectivity

## Security & App Store Compliance

### Mandatory Requirements
- ✅ **No subprocess execution** (uses PythonKit exclusively)
- ✅ **Sandbox compliance** (Application Support container usage)
- ✅ **Code signing** (deep signing of all frameworks)
- ✅ **Entitlements** (proper App Store sandbox entitlements)
- ✅ **No system dependencies** (completely self-contained)

### Prohibited Patterns
- ❌ System Python calls (`python3`, `/usr/bin/python`)
- ❌ Subprocess execution (`Process`, `NSTask`)
- ❌ External binary dependencies
- ❌ File system access outside sandbox
- ❌ Network calls beyond Ollama API

## Maintenance & Updates

### Framework Updates
```bash
# Update BeeWare framework when needed
./setup_beeware_framework.sh  # Re-downloads and recompiles
```

### Dependency Management
```bash
# Python dependencies managed in python_site/
# All native extensions compiled against BeeWare framework
# Universal2 (ARM64/x86_64) compatibility maintained
```

### Code Signing
```bash
# All frameworks and dependencies must be signed
# Production builds include deep signing of .so/.dylib files
# App Store distribution requires proper entitlements
```

---

**CRITICAL**: This PythonKit + BeeWare framework architecture is **MANDATORY** for all MarcutApp development. Any deviation from this architecture will break App Store compliance and must be avoided. The consolidated pathway approach ensures consistent behavior across CLI and GUI interfaces while maintaining the self-contained, robust nature of the application.

#### Runtime embedding rules (self-contained, App Store safe)
- Always resolve the embedded runtime via `Contents/Frameworks/Python.framework/Versions/Current` (no hard-coded 3.11/3.10 paths); ship only the active version in the bundle.
- Set `PYTHONHOME` to the bundled framework and `PYTHONPATH` only to bundled `Resources/python_site` (and `python_stdlib` if present). Never fall back to system Python.
- Enforce isolation flags everywhere (`PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`, ignore host env) so runtime never writes outside the bundle or uses user/site packages.
- Ollama: use the app’s own `OLLAMA_HOME`/`OLLAMA_MODELS` under `~/Library/Application Support/MarcutApp`; reuse an existing service if present but do not mutate system installs.
