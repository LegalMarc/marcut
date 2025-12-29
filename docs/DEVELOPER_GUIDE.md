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
final class PythonKitRunner {
    // Direct Python execution via PythonKit
    func runEnhancedOllama(inputPath: String, outputPath: String, reportPath: String, model: String, debug: Bool) -> Bool
}
```

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
# Fast iteration development build
./build.sh dev
# Output: MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp
# Uses: System Python for Swift compilation only
# Runtime: PythonKit with BeeWare framework (when available)
```

For everyday debugging you can skip the BeeWare refresh and keep turnaround under a minute by using the new preset:

```bash
./build_swift_only.sh preset dev_fast
```

The interactive `build_tui.py` menu exposes the same option (“Dev Fast”) so the GUI bundle plus signing can be produced without re-downloading runtimes.

### Production Build (Release)
```bash
# Complete production build with embedded framework
./build.sh dev  # or ./build_appstore_release.sh
# Output: build_swift/MarcutApp.app (with embedded BeeWare framework)
# Runtime: PythonKit with fully embedded BeeWare framework
```

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
# marcut/pipeline.py - Core redaction logic
def run_redaction_enhanced(input_path, output_path, report_path, model, debug=False):
    """Unified pipeline for both CLI and GUI pathways"""
    # 1. Rule-based PII detection (marcut.rules)
    # 2. Enhanced LLM extraction via Ollama
    # 3. Overlap merging and entity clustering
    # 4. Track changes generation (DOCX)
    # 5. JSON audit report creation
```

### Runtime Overrides
- The macOS app now ships with an override manager (`UserOverridesManager`). Editors in the Settings sheet let users modify `excluded-words.txt` and the LLM system prompt.
- Overrides are stored under the App Group (`~/Library/Group Containers/.../MarcutOverrides/`) and mirrored via `MARCUT_EXCLUDED_WORDS_PATH` / `MARCUT_SYSTEM_PROMPT_PATH`. Both the in-process PythonKit runner and CLI inherit these env vars so the same list/prompt applies everywhere.
- Python code watches the override files: if the timestamp changes, the regex cache and prompt string reload automatically without restarting the app.

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

### App Group Container Usage
```
~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/
├── Work/           # CLI processing workspace
├── models/         # Ollama models
├── ollama-data/    # Ollama data files
└── Input/          # User input files (GUI drag-and-drop)
```

### File Access Requirements
- **CLI inputs**: Must be copied to App Group container before processing
- **GUI inputs**: Automatically handled by sandboxed file access
- **Outputs**: Generated in App Group container or user-selected locations

## Testing & Validation

### Test Suite Notes
- `python3 run_tests.py` uses the repo `venv/` interpreter if present; install pytest in the venv for full coverage: `venv/bin/python -m pip install pytest`.
- Metadata scrubbing coverage now includes a redaction-path scrub report check via `MARCUT_SCRUB_REPORT_PATH`.
- The metadata matrix script (`scripts/run_metadata_matrix.py`) auto-generates a minimal DOCX if `sample-files/Shareholder-Consent.docx` is missing; keep real sample files locally for higher-fidelity validation.
- The build TUI “Run Tests” menu delegates to `run_tests.py`, so the same behaviors apply there.

### CLI Testing
```bash
# Test CLI functionality (uses PythonKit directly)
./MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp --help
./MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp --diagnose
./MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp --redact --in file.docx --outdir output/
```

### Build Script Testing (Unified Runtime)
```bash
# Test consolidated pathways
./build.sh test --source --cli --llm     # CLI pathway (dev uses venv; prod defers to app CLI)
./build.sh test --source --gui --llm     # GUI pathway (always in‑process)
./build.sh test --source --both --llm    # Both pathways
```

### Production Validation
```bash
# Validate production build includes BeeWare framework
./build_appstore_release.sh
# Test: build_swift/MarcutApp.app should work without system Python
```

## Development Workflow

### 1. Code Development
```bash
# Swift changes
cd MarcutApp && swift build

# Python changes
# Test with system Python, but production uses BeeWare framework
```

### 2. Local Testing
```bash
# Debug build testing (PythonKit integration)
./build.sh dev
./MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp --cli --diagnose
```

### 3. Integration Testing
```bash
# Full pathway testing
./build.sh test --source --both --llm
```

### 4. Production Validation
```bash
# Production build with embedded framework
./build.sh dev  # Creates build_swift/MarcutApp.app (dev launcher uses venv; prod launcher uses app CLI)
# Test App Store compliance and standalone operation
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
    // App Group container for models and data
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
./MarcutApp --cli --download-model llama3.1:8b

# Model storage (App Group container)
~/Library/Group Containers/group.com.marclaw.marcutapp/MarcutOllama/models/
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
**Problem**: File access outside App Group container
**Solution**: Copy input files to container directory before processing

#### Model Download Issues
**Problem**: Ollama connection failures
**Solution**: Check App Group container permissions and network connectivity

## Security & App Store Compliance

### Mandatory Requirements
- ✅ **No subprocess execution** (uses PythonKit exclusively)
- ✅ **Sandbox compliance** (App Group container usage)
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
