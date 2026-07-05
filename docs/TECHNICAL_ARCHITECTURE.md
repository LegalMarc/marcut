# Marcut Technical Architecture Documentation

## System Overview

Marcut is a native macOS redaction application that combines a deterministic rules engine with optional local AI (Ollama) to identify sensitive information in DOCX documents. The macOS app runs in a sandbox, embeds its own Python runtime, and performs all processing on-device. A separate source/CLI distribution is also supported for development and automation.

### Core Architecture Principles

1. **Local-First Processing**: Document content stays on the device; rules-only mode requires no network.
2. **Self-Contained Runtime**: Embedded Python.framework (BeeWare, Python 3.11) and bundled dependencies.
3. **Hybrid Detection**: Deterministic rules for structured PII + optional LLM for names/orgs.
4. **Auditability**: Track Changes output plus JSON redaction and scrub reports.
5. **Sandbox Compliance**: Application Support storage, user-selected file access, minimal entitlements.
6. **Apple Silicon Native**: ARM64-first build and performance profile.

---

## Application Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Marcut.app (SwiftUI)                  │
├─────────────────────────────────────────────────────────────┤
│ SwiftUI App + CLI Entry Points                              │
│ ├── Drag/Drop UI, Settings, Onboarding                       │
│ ├── PythonKitRunner + PythonWorkerThread                     │
│ ├── PythonBridgeService (env + logging + model mgmt)         │
│ └── File access + sandbox coordination                       │
├─────────────────────────────────────────────────────────────┤
│ Embedded Python Runtime (BeeWare, CPython 3.11, ARM64)       │
│ ├── python_stdlib (stdlib overlay)                           │
│ ├── python_site (deps + marcut package)                      │
│ └── marcut pipeline (docx_io, rules, model, report)          │
├─────────────────────────────────────────────────────────────┤
│ Local LLM Service (Ollama)                                  │
│ ├── Embedded ollama binary (Contents/MacOS/ollama)           │
│ ├── Metal runners (Resources/ollama_runners/metal)           │
│ └── Local HTTP API (127.0.0.1:11434)                         │
└─────────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

#### 1. SwiftUI App + PythonKit Layer
- **Purpose**: App lifecycle, UI, CLI entry point, and sandbox-safe orchestration.
- **Key components**:
  - `PythonKitRunner` initializes the embedded interpreter and executes the pipeline in-process.
  - `PythonWorkerThread` serializes CPython calls on a single owner thread (GIL safety).
  - `PythonBridgeService` prepares environment variables, manages Ollama, and centralizes logs.
  - `DocumentRedactionViewModel` controls queueing, progress, and error handling.

#### 2. Embedded Python Runtime
- **Purpose**: Self-contained execution environment for all redaction logic.
- **Key components**:
  - BeeWare Python.framework (CPython 3.11) under `Contents/Frameworks/`.
  - `python_site/` contains dependencies and the `marcut` package.
  - `python_stdlib/` is included as a controlled stdlib overlay.
- **Pinned dependencies** (see `requirements-pinned.txt`): python-docx, lxml, regex, requests, numpy, dateparser, pydantic, rapidfuzz, tqdm.

#### Model Catalog
- The recommended-models list and their parameters (temperature, skip-confidence, display metadata) live in a single `models.json`, mirrored byte-identically across three locations that must stay in sync: `assets/models.json`, `src/python/marcut/models.json`, and `src/swift/MarcutApp/Sources/MarcutApp/Resources/models.json` (the same pattern used for `excluded-words.txt`).
- `marcut/model_config.py` (Python) and `ModelCatalog.swift`/`BundleResourceLocator.swift` (Swift) are mirrored loaders that resolve the bundled resource path in both dev and production bundle layouts.

#### 3. Local LLM Service (Ollama)
- **Purpose**: Local inference for entity extraction in enhanced mode.
- **Key components**:
  - Embedded `ollama` binary (ARM64) launched by the app.
  - Metal runner binaries bundled in `ollama_runners/metal` to avoid sandbox extraction issues.
  - Local HTTP API on `127.0.0.1:11434` (loopback enforced; port may vary).

#### 4. Storage + Overrides Layer
- **Purpose**: Stable, sandbox-safe storage for models, logs, and user overrides.
- **Key components**:
  - Application Support container for Ollama models and staging.
  - Overrides folder for excluded words and LLM system prompt.
  - Application Support logs for diagnostics.

---

## Data Flow Architecture

### Document Processing Pipeline

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   DOCX      │───▶│  DocxMap     │───▶│ Rule Engine │
│   Input     │    │  (XML map)   │    │  (regex)    │
└─────────────┘    └──────────────┘    └──────┬──────┘
                                              │
                           ┌──────────────────┴─────────────────┐
                           │ Optional LLM Extraction (Ollama)     │
                           └──────────────────┬─────────────────┘
                                              │
                                        ┌─────▼─────┐
                                        │ Post-Proc │
                                        │ Merge/ID  │
                                        └─────┬─────┘
                                              │
                           ┌──────────────────┴─────────────────┐
                           │ Track Changes + Reports + Scrub     │
                           └──────────────────┬─────────────────┘
                                              │
                                        ┌─────▼─────┐
                                        │   Output  │
                                        └───────────┘
```

### Processing Stages

#### Stage 1: Document IO
1. **DOCX Load**: `DocxMap.load_accepting_revisions()` parses the DOCX ZIP in memory.
2. **XML Safety**: XML parsing is done with entity resolution disabled (XXE-safe).
3. **Text Mapping**: Runs/paragraphs are mapped back to original XML for precise edits.
4. **Metadata Snapshot**: Existing document properties are captured for scrub reports.

#### Stage 2: Rules Engine (Always On)
1. **Regex Detection**: Structured PII detection via `rules.py` (email, phone, SSN, money, etc.).
2. **Validators**: Extra checks for cards (Luhn), URLs, IPs, and addresses.
3. **Exclusion Logic**: User and system exclusion lists prevent boilerplate redaction.

#### Stage 3: Local AI (Optional)
1. **Chunking**: `chunker.py` splits text into overlapping segments for long documents.
2. **Ollama Extraction**: `model_enhanced.py` prompts a local model and parses JSON output.
3. **Validation Pass**: Suspicious candidates may be re-validated to reduce false positives.
4. **Backend Options**: Ollama is default; `llama_cpp` GGUF backend is available in CLI/dev.

#### Stage 4: Post-Processing
1. **Boundary Snapping**: Expand spans to full tokens (avoid mid-word redactions).
2. **Consistency Pass**: Re-scan for exact matches to keep redactions consistent.
3. **Overlap Merge**: Combine spans with priority ranking by label.
4. **Entity Clustering**: Stable entity IDs created for NAME/ORG/BRAND tagging.

#### Stage 5: Output + Audit
1. **Track Changes**: Redactions are applied as Word revisions for review; the DOCX output is a review artifact until changes are accepted or otherwise finalized.
2. **JSON Report**: Spans, labels, confidence, and sources are written to report JSON; reports may include original detected text and document metadata.
3. **Metadata Scrub**: Optional removal of hidden document metadata with a scrub report.
4. **Failure Reports**: Pipeline errors emit a minimal JSON report for UI/CLI surfacing.

---

## File System Architecture

### Application Bundle Structure (macOS App)

```
Marcut.app/
└── Contents/
    ├── MacOS/
    │   ├── MarcutApp            # SwiftUI executable
    │   └── ollama               # Embedded Ollama binary
    ├── Frameworks/
    │   └── Python.framework/    # BeeWare CPython 3.11
    └── Resources/
        ├── python_site/         # Bundled deps + marcut package
        ├── python_stdlib/       # Stdlib overlay
        ├── ollama_runners/      # Metal runners for Ollama
        ├── excluded-words.txt   # Default exclusions
        ├── system-prompt.txt    # Default LLM prompt
        └── help.md              # In-app help content
```

### Application Support / User Data (Sandboxed)

```
~/Library/Application Support/MarcutApp/
├── models/                  # Ollama models
├── ollama/
│   ├── ollama-data/         # Ollama internal data
│   └── tmp/                 # Ollama temp files
├── Work/
│   ├── Staging/             # Temp workspace (cleaned after run)
│   └── Output/              # CLI output staging (optional)
├── Input/                   # Optional CLI input staging
├── Overrides/
│   ├── excluded-words.txt   # User overrides
│   └── system-prompt.txt    # User overrides
└── logs/
    ├── marcut.log
    ├── ollama.log
    └── python.log
```

**Output paths**: Redacted documents and reports are written to user-selected locations. The CLI defaults to the input directory when sandbox permissions allow it.

**Log location note**: The primary log path is `~/Library/Application Support/MarcutApp/logs/`. If Application Support is unavailable, logs fall back to a temporary directory; App Group mirroring is only used in custom builds with those entitlements.

### Standalone / CLI Distribution (Source)

```
~/.marcut/
├── config.json                  # CLI config
├── bin/                         # Local helper binaries
├── models/                      # Optional LLM assets
└── logs/                        # CLI logs
```

---

## Network Architecture

### Localhost-Only Inference (Default)
- **Ollama API**: `http://127.0.0.1:11434/api/...` for on-device inference.
- **No document uploads**: Content is only sent to the local service.

### Model Downloads (User-Initiated)
- **Ollama registry**: Model downloads occur over HTTPS when the user requests a model.
- **Caching**: Models are stored in the Application Support container for offline use.

### Loopback Enforcement
- **Host**: `OLLAMA_HOST` / `MARCUT_OLLAMA_HOST` are sanitized to `127.0.0.1`.
- **Port**: The port may vary, but inference remains on the local loopback interface.
- **Public runtime lockdown**: Public app/CLI runs ignore the legacy `MARCUT_ALLOW_REMOTE_OLLAMA` variable entirely. A source-developer-only `MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA=1` override exists for local development against a remote host; it must never be used with confidential documents and is stripped from the environment before any packaged/public build launches Python.

---

## Performance Architecture

### Resource Management
- **Rules-only mode**: Fast and low-memory, no model loading.
- **Enhanced mode**: Dominated by model load time and inference latency.
- **Chunking**: Large documents are processed in overlapping segments for stability.
- **Reuse**: Ollama stays warm between runs for faster subsequent processing.

### Performance Characteristics (Qualitative)
- **Startup**: PythonKit init is a short one-time cost on cold launch.
- **Rules pass**: Typically sub-second for small docs; scales with document length.
- **LLM pass**: Varies with model size, system load, and document length.
- **Output**: Track changes and report generation scale with span count.

### Instrumentation
- `--llm-detail` provides sub-phase timing (load, prompt eval, generation) for Ollama; it wraps the same production extraction path rather than replacing it, so enabling it never changes what gets redacted.
- Phase timings are returned by the pipeline for diagnostics and UI progress.

### Cancellation and Deadlines
- `marcut/cancellation.py` provides a shared deadline primitive (`ProcessingDeadlineExceeded`, `check_processing_deadline()`, `remaining_seconds()`) read from the `MARCUT_PROCESSING_DEADLINE_MONOTONIC` environment variable.
- `PythonKitRunner` sets this deadline marker for each timed processing phase and clears it on completion, cancellation, or before a new run.
- Ollama HTTP requests, the enhanced extraction/validation thread pool, and chunk-processing waits all check the deadline and bound their own timeouts to the remaining time, so a hung request or a user-initiated Stop is bounded rather than left to run to completion.

### Reliability: Transactional Artifact Writes
- Final redaction artifacts (DOCX, audit report JSON/HTML, scrub report JSON/HTML) are staged to same-directory hidden temp files and only renamed into their final names after the full artifact set writes successfully.
- A failure or cancellation after partial staging cleans up the temp files rather than leaving a misleading final DOCX with no matching report.

---

## Security Architecture

### Data Protection
- **Sandboxed file access**: Only user-selected files are accessed.
- **In-memory DOCX parsing**: No full extraction to disk; ZIP members are read/written in memory.
- **Staging isolation**: Temporary work files live in the Application Support workspace and are cleaned.

### Privacy Model
- **No telemetry**: No analytics or usage tracking in the app.
- **Local processing**: Default processing is on-device only.

### Audit Trail
- **Track Changes output**: Word-native review workflow; not a destructively sanitized final-share file by default.
- **JSON report**: Span-level details, sources, and confidence values.
- **Metadata scrub report**: Before/after values for scrubbed fields.

---

## Integration Architecture

### macOS Integration
- **SwiftUI UI**: Drag/drop, file dialogs, progress tracking.
- **CLI mode**: `MarcutApp --cli ...` uses the same PythonKit pipeline.
- **Sandbox coordination**: File bookmarks and Application Support storage keep access compliant.

### Document Formats
- **DOCX**: Primary format; edits written as Track Changes for auditability and review.
- **JSON**: Redaction and scrub reports for downstream tooling; handle as sensitive because raw detected text and metadata can appear in reports.

---

## Deployment Architecture

### Build Pipeline (macOS)

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Source Code    │───▶│  Swift Build    │───▶│  Bundle Assembly│
│  (Swift/Python) │    │  + PythonKit    │    │  + Signing      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ BeeWare Setup   │    │ Ollama Embed    │    │ DMG / App Store │
│ + python_site   │    │ + Runners       │    │ Packaging       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Key Build Scripts
Canonical entrypoint for humans: `build_tui.py`.
- `scripts/sh/build_swift_only.sh`: Swift build, bundle assembly, and optional DMG creation.
- `setup_beeware_framework.sh`: Creates the embedded Python.framework + python_site.
- `scripts/sh/build_appstore_release.sh`: App Store archive build with signing and entitlements.

### Signing + Notarization
- **Deep signing**: Python.framework, python_site extensions, and Ollama binary.
- **Entitlements**: App Sandbox, local network (Ollama), user-selected file access.
- **DMG notarization**: Mandatory for public direct distribution builds; local/test skips require the explicit `MARCUT_ALLOW_NOTARIZATION_SKIP=1` override and are not releasable artifacts.
- **`scripts/verify_entitlements.sh`**: prints app/helper entitlements from a built bundle and fails on forbidden debug/runtime-bypass entitlements (`disable-library-validation`, `allow-jit`, `get-task-allow`). `build_tui.py` runs it automatically after a Developer ID DMG build or existing-DMG notarization.

### Dependency and SBOM Governance
- `scripts/generate_python_sbom.py` builds a CycloneDX-style SBOM from either the staged repo checkout (default; matches CI's per-PR gate) or `--bundle-root /path/to/MarcutApp.app` (a real built bundle, used for final release verification), including transitive PyPI packages, SwiftPM dependencies from `Package.resolved`, and manual-review entries for the BeeWare `Python.framework` and embedded Ollama binary.
- `scripts/check_dependency_vulnerabilities.py --sbom docs/release/python-sbom.json` scans shipped PyPI components against OSV.
- `scripts/release_preflight.sh` gates a release on tests, SBOM freshness, the vulnerability scan, markdown links, version-sync against the last git tag, and a secrets check, in one command.

---

*Marcut Technical Architecture v0.5.x*
*SwiftUI + PythonKit + BeeWare + Local Ollama*
