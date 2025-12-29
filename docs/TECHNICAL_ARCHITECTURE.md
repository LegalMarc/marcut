# Marcut Technical Architecture Documentation

## System Overview

Marcut is a native macOS redaction application that combines a deterministic rules engine with optional local AI (Ollama) to identify sensitive information in DOCX documents. The macOS app runs in a sandbox, embeds its own Python runtime, and performs all processing on-device. A separate source/CLI distribution is also supported for development and automation.

### Core Architecture Principles

1. **Local-First Processing**: Document content stays on the device; rules-only mode requires no network.
2. **Self-Contained Runtime**: Embedded Python.framework (BeeWare, Python 3.11) and bundled dependencies.
3. **Hybrid Detection**: Deterministic rules for structured PII + optional LLM for names/orgs.
4. **Auditability**: Track Changes output plus JSON redaction and scrub reports.
5. **Sandbox Compliance**: App Group storage, user-selected file access, minimal entitlements.
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

#### 3. Local LLM Service (Ollama)
- **Purpose**: Local inference for entity extraction in enhanced mode.
- **Key components**:
  - Embedded `ollama` binary (ARM64) launched by the app.
  - Metal runner binaries bundled in `ollama_runners/metal` to avoid sandbox extraction issues.
  - Local HTTP API on `127.0.0.1:11434` (host configurable via `OLLAMA_HOST`).

#### 4. Storage + Overrides Layer
- **Purpose**: Stable, sandbox-safe storage for models, logs, and user overrides.
- **Key components**:
  - App Group container for Ollama models and staging.
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
1. **Track Changes**: Redactions are applied as Word revisions for review.
2. **JSON Report**: Spans, labels, confidence, and sources are written to report JSON.
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
        └── Help.md              # In-app help content
```

### App Group / User Data (Sandboxed)

```
~/Library/Group Containers/group.com.marclaw.marcutapp/
├── MarcutOllama/
│   ├── models/                  # Ollama models
│   ├── ollama-data/             # Ollama internal data
│   ├── Work/Staging/            # Temp workspace (cleaned after run)
│   └── Input/                   # Optional CLI input staging
├── MarcutOverrides/
│   ├── excluded-words.txt       # User overrides
│   └── system-prompt.txt        # User overrides
└── Library/Application Support/MarcutApp/logs/
    ├── marcut.log
    ├── ollama.log
    └── python.log
```

**Output paths**: Redacted documents and reports are written to user-selected locations. The CLI defaults to the input directory when sandbox permissions allow it.

**Log location note**: The primary log path is `~/Library/Application Support/MarcutApp/logs/`, with an App Group fallback under the same path inside the container if needed.

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
- **Caching**: Models are stored in the App Group container for offline use.

### Optional Remote Hosts (Explicit Only)
- **Override**: `OLLAMA_HOST` / `MARCUT_OLLAMA_HOST` can point to a remote Ollama server.
- **Note**: Remote hosts will receive document content; use only if policy allows.

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
- `--llm-detail` provides sub-phase timing (load, prompt eval, generation) for Ollama.
- Phase timings are returned by the pipeline for diagnostics and UI progress.

---

## Security Architecture

### Data Protection
- **Sandboxed file access**: Only user-selected files are accessed.
- **In-memory DOCX parsing**: No full extraction to disk; ZIP members are read/written in memory.
- **Staging isolation**: Temporary work files live in the App Group workspace and are cleaned.

### Privacy Model
- **No telemetry**: No analytics or usage tracking in the app.
- **Local processing**: Default processing is on-device only.
- **Remote AI caution**: Only occurs if the user configures a remote Ollama host.

### Audit Trail
- **Track Changes output**: Word-native review workflow.
- **JSON report**: Span-level details, sources, and confidence values.
- **Metadata scrub report**: Before/after values for scrubbed fields.

---

## Integration Architecture

### macOS Integration
- **SwiftUI UI**: Drag/drop, file dialogs, progress tracking.
- **CLI mode**: `MarcutApp --cli ...` uses the same PythonKit pipeline.
- **Sandbox coordination**: File bookmarks and App Group storage keep access compliant.

### Document Formats
- **DOCX**: Primary format; edits written as Track Changes for auditability.
- **JSON**: Redaction and scrub reports for downstream tooling.

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
- `build_swift_only.sh`: Swift build, bundle assembly, and optional DMG creation.
- `setup_beeware_framework.sh`: Creates the embedded Python.framework + python_site.
- `build_appstore_release.sh`: App Store archive build with signing and entitlements.

### Signing + Notarization
- **Deep signing**: Python.framework, python_site extensions, and Ollama binary.
- **Entitlements**: App Sandbox, App Group, local network (Ollama), user-selected file access.
- **DMG notarization**: Optional for direct distribution builds.

---

*Marcut Technical Architecture v0.5.x*
*SwiftUI + PythonKit + BeeWare + Local Ollama*
