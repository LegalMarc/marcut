# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Marcut is a local-first DOCX redaction tool that produces Microsoft Word documents with track changes. It uses a hybrid approach combining rules-based detection and LLM analysis for high-precision PII redaction. The application is packaged as a native macOS app with embedded Python runtime and Ollama AI service.

## Agent Rules

- Never push or offer to push to any remote unless explicitly asked by the user.

## Current Status (September 2024)

### ✅ RESOLVED: PythonKit + BeeWare Architecture Implementation (September 18, 2024)

**Major Architecture Change**: Successfully transitioned from subprocess-based Python execution to direct PythonKit integration using BeeWare Python framework. This eliminates all spawn/signing/entitlement issues and provides robust, fail-fast Python execution within the Swift process.

#### Implementation Completed:

**Core Architecture Transition**:
- ✅ **PythonKit Integration** - Direct Swift-Python integration without subprocess
- ✅ **BeeWare Python.framework** - Universal2 framework (Python 3.11-b7) with App Store compatibility
- ✅ **Deterministic Initialization** - Phase markers (PK_INIT_START → PK_INIT_COMPLETE) with strict timeouts
- ✅ **Bundle Structure** - Production (Contents/Frameworks/) vs Development (MarcutApp_MarcutApp.bundle/) path resolution
- ✅ **Deep Code Signing** - All .so/.dylib files in framework and python_site properly signed

#### Working Status (September 18, 2024):
- ✅ **Swift-Python Integration** - Direct Python execution via PythonKit (0.41s end-to-end)
- ✅ **Framework Detection** - Automatic dev/production bundle path resolution
- ✅ **Timeout System** - 10s per phase, 30s total with deterministic logging
- ✅ **End-to-End Processing** - Successfully generates test_redacted.docx + test_report.json
- ✅ **Dependency Resolution** - Python 3.11 compatibility for lxml/docx/numpy
- ✅ **Build Pipeline** - Updated scripts/sh/build_appstore_release.sh for BeeWare framework integration

#### Design Goals Achieved:

**Robust**: Comprehensive timeout system with phase markers prevents hangs
```swift
// 10s per step, 30s total timeout with deterministic logging
PK_INIT_START → PK_FRAMEWORK_FOUND → PK_ENV_SET → PK_LIB_LOADED → PK_IMPORT_OK → PK_INIT_COMPLETE
```

**Fail Fast**: Immediate errors on framework missing, import failures, or timeouts
```swift
guard let cfg = locateFramework() else {
    throw PythonInitError.notFound  // Immediate failure, no retries
}
```

**No Fallbacks**: Single code path using PythonKit only (subprocess support removed during transition)
```swift
// Direct PythonKit execution - no subprocess fallback
let pipeline = try Python.attemptImport("marcut.pipeline")
let code = Int(pipeline.run_redaction_enhanced(...))
```

**Speedy**: 0.41s end-to-end processing, well under timeout limits
```
PK_INIT_COMPLETE: 0.12s
PK_ENHANCED_OLLAMA_COMPLETE: exit_code=0 total=0.41s
```

**App Store Compatible**: BeeWare Universal2 framework with proper deep signing
- No subprocess execution (avoiding sandbox restrictions)
- All native extensions properly code signed
- Framework structure follows Apple guidelines

#### Technical Implementation:

**PythonKit Bridge** (`Sources/MarcutApp/PythonKitBridge.swift`):
```swift
final class PythonKitRunner {
    private func withTimeout<T>(operation: String, stepTimeout: TimeInterval = 10.0, totalTimeout: TimeInterval = 30.0) throws -> T
    func runEnhancedOllama(inputPath: String, outputPath: String, reportPath: String, model: String, debug: Bool) -> Bool
}
```

**Framework Integration** (`setup_beeware_framework.sh`):
```bash
# Downloads BeeWare Python 3.11-b7 (101MB framework)
# Installs dependencies to python_site (81MB)
# Deep signs all .so/.dylib files for App Store compatibility
```

**Production Build** (`scripts/sh/build_appstore_release.sh`):
```bash
# Copies framework to Contents/Frameworks/ (production structure)
# Signs BeeWare framework and python_site dependencies
# Verifies framework presence before final packaging
```

### Investigation History (September 15-16, 2024)

#### Problem Discovery:
- User reported documents immediately showing "[Failed]" status after "Redact Documents" button
- Initial assumption: Document processing pipeline failure
- Debugging approach: Added comprehensive logging system

#### Debugging Journey (Versions 0.2.9 → 0.3.7):

**v0.2.9-v0.3.0**: Added logging to DocumentRedactionViewModel and PythonBridge
- Result: No log files created, suggesting app not launching

**v0.3.1**: Added DebugLogger centralized logging system with Settings toggle
- Result: App crashed during initialization due to assertion failure in main app init

**v0.3.2**: Fixed critical crash by removing problematic init() method
- Result: App launched but still no logs, AttributeGraph cycles discovered

**v0.3.3-v0.3.4**: Added console debugging and direct logging fallbacks
- Result: Found AttributeGraph cycles preventing normal execution

**v0.3.5**: Attempted to break cycles by removing @Published properties and init dependencies
- Result: Cycles persisted, issue deeper in UI architecture

**v0.3.6**: Simplified UI to isolate cycle sources
- Result: Even minimal UI showed cycles, issue in core binding system

**v0.3.7**: Implemented comprehensive SwiftUI debugging with environment variables
- Result: **BREAKTHROUGH** - App actually works! Console shows full functionality

#### Key Findings from v0.3.7 Analysis:
```
✅ App launched successfully - AppDelegate and ContentView both executed
✅ Environment detected correctly - "Environment ready: false" (expected for first run)
✅ Ollama functionality working - Model download completed successfully
✅ UI responsive - "Button clicked" shows interaction works
✅ No crashes - App ran stable until killed
```

**AttributeGraph cycles are warnings, not blocking errors** - the app is fully functional despite the cycles.

### Debugging Approaches Evaluated:

#### Approach 1: Progressive Feature Addition ✅ COMPLETED
**Strategy**: Add logging incrementally to isolate failure point
**Implementation**: Added logging to ViewModel → PythonBridge → AppDelegate → ContentView
**Result**: Successfully identified that app was not launching, then discovered cycles were cosmetic

#### Approach 2: Architecture Simplification ⏸️ PARTIALLY TESTED
**Strategy**: Strip complex UI to isolate cycle sources
**Implementation**: Replaced full UI with minimal components in v0.3.6
**Result**: Cycles persisted even with minimal UI, indicating deeper architectural issue

#### Approach 3: Direct Binary Analysis ✅ SUCCESSFUL
**Strategy**: Use SwiftUI debugging tools to trace AttributeGraph cycles
**Implementation**: v0.3.7 with environment variables and console monitoring
**Tools Used**:
- `SWIFTUI_DEBUG_ATTRIBUTE_GRAPH=1`
- `SWIFTUI_DEBUG_UPDATES=1`
- `SWIFTUI_DEBUG_LAYOUT=1`
- `SWIFTUI_DEBUG_IDENTITY=1`
**Result**: **BREAKTHROUGH** - Discovered app works despite warning cycles

#### Approach 4: Revert to Known Good State ⏳ PENDING
**Strategy**: Start from cd9ac23 and add features incrementally
**Status**: Not yet attempted, may be unnecessary given Approach 3 success

### Current Recommendations (September 16, 2024):

#### Option 1: Test Document Processing (RECOMMENDED)
**Rationale**: App is functional, test core feature before optimizing warnings
**Next Steps**:
- Test document drag-and-drop functionality
- Verify end-to-end redaction pipeline
- Confirm original "[Failed]" issue is resolved

#### Option 2: AttributeGraph Cycle Cleanup
**Rationale**: Professional polish, potential performance improvements
**Approach**: Target specific attribute IDs (176748, 181112, 215632) identified in logs
**Priority**: Medium (after core functionality confirmed)

#### Option 3: Production Debug System
**Rationale**: Maintain debugging capabilities for production issues
**Tasks**:
- Refine DebugLogger integration
- Default debug mode to OFF for production
- Add debug toggle UI functionality

#### Option 4: Accept Cycles and Ship
**Rationale**: Cycles are cosmetic warnings, focus on user value
**Approach**: Document known issue, prioritize feature completion

### Technical Debt Notes:

#### Known Issues:
- SwiftUI AttributeGraph cycles (cosmetic warnings)
- DebugLogger initialization timing
- Complex UI binding patterns in DocumentRow/DocumentListView

#### Future Improvements:
- Cycle elimination for performance optimization
- Streamlined debug system
- UI component refactoring

### Historical Working State (Commit cd9ac23)

#### 1. Fixed Ollama Timeout Issue
```python
# marcut/model_enhanced.py - Line 147
# Replaced complex enhanced extraction with simple extraction
from .model import ollama_extract
try:
    simple_spans = ollama_extract(
        self.model_id,
        chunk_text,
        self.temperature,
        seed=42  # Fixed seed for consistency
    )
except Exception as e:
    print(f"Error extracting entities from chunk: {e}")
    simple_spans = []
```

#### 2. Increased Timeouts
```python
# marcut/model.py - Lines 248, 261
timeout=60  # Increased from 30 seconds for larger chunks
```

#### 3. Disabled JSON Format Constraint
```python
# marcut/model.py - Lines 242, 258
# "format": "json",  # Disabled - causes hangs with llama3.1:8b
```

### Test Results
Successfully processed multiple documents:
- **Compliance-Cert.docx**: 46 entities detected, track changes generated
- **loan-term-sheeet.docx**: 30 entities detected, successful redaction
- **Sample files**: All test documents process without timeouts

## Core Architecture

### Main Components
- **marcut/pipeline.py** - Core redaction pipelines (`run_redaction()` for classic, `run_redaction_enhanced()` for two-pass LLM)
- **marcut/model.py** - LLM extraction via Ollama API (fixed timeout issues)
- **marcut/model_enhanced.py** - Enhanced two-pass LLM extractor/validator with document-level context
- **marcut/rules.py** - Rule-based structured PII detection (emails, phones, credit cards, dates, money)
- **marcut/docx_io.py** - Microsoft Word track changes writer using revision elements
- **marcut/gui.py** - Tkinter GUI for the desktop application
- **marcut/cli.py** - Command-line interface with `marcut` script entry point
- **marcut/bootstrapper.py** - Application bootstrapping and embedded Ollama management
- **marcut/ollama_manager.py** - Ollama lifecycle management and model download
- **MarcutApp/Sources/MarcutApp/PythonKitBridge.swift** - PythonKit integration with BeeWare framework and timeout system
- **MarcutApp/Sources/MarcutApp/PythonBridge.swift** - Legacy subprocess wrapper (transition period only)

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
  --in sample-files/Shareholder-Consent.docx \
  --out runs/out.docx \
  --report runs/out.json \
  --backend ollama \
  --model llama3.1:8b \
  --enhanced \
  --debug
```

### Ollama Setup
```bash
# Install and start Ollama
brew install ollama
ollama serve &
ollama pull llama3.1:8b
```

### Swift App Building
```bash
# Set up BeeWare Python framework (one-time setup)
./setup_beeware_framework.sh

# Build Swift app
cd MarcutApp
swift build

# Create production DMG with embedded framework
cd ..
./scripts/sh/build_appstore_release.sh

# Output: MarcutApp-Production-v0.3.x.dmg (~200MB with BeeWare framework)
```

### BeeWare Framework Setup
```bash
# Download and configure BeeWare Python 3.11 framework
./setup_beeware_framework.sh

# Installs:
# - MarcutApp/Frameworks/Python.framework (101MB Universal2 framework)
# - MarcutApp/python_site/ (81MB Python dependencies)
# - Proper code signing for all native extensions
```


## Configuration

### Project Structure
- **pyproject.toml** - Python project configuration with dependencies
- **setup.py** - py2app configuration for macOS app bundle
- **packaging/** - Build scripts and app bundle configurations
- **docs/** - Comprehensive documentation including USER_GUIDE.md and DEVELOPER_GUIDE.md
- **sample-files/** - Test DOCX files for validation
- **excluded-words.txt** - Legal/business terms to exclude from redaction

### Key Dependencies

**Swift Framework Integration**:
- **PythonKit** - Swift-Python interoperability (via Swift Package Manager)
- **BeeWare Python.framework** - Universal2 Python 3.11 runtime for macOS
- **Deep Code Signing** - All .so/.dylib files signed for App Store distribution

**Python Dependencies** (installed to python_site):
- python-docx>=1.1.0 - DOCX document manipulation
- rapidfuzz>=3.6.1 - Fast string matching
- pydantic>=2.6.4 - Data validation
- requests>=2.31.0 - HTTP client for Ollama API
- dateparser>=1.2.0 - Date parsing
- tqdm>=4.66.0 - Progress bars
- lxml>=5.0.0 - XML processing (Python 3.11 compatible wheels)
- numpy>=1.24.0 - Numerical operations

## Testing and Validation

### ⚠️ CRITICAL RULE: Test-Driven Development
**MANDATORY: When adding ANY new feature, you MUST update corresponding tests.**

**Required test updates for every feature addition:**
1. **Swift Features** → Update `MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`
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
# Run complete test suite before committing any feature
python3 run_tests.py

# Run Swift tests only
python3 run_tests.py --swift-only

# Run Python tests only
python3 run_tests.py --python-only
```

### Current Test Coverage
- **Swift UI Tests**: 12 test methods covering all UI improvements and state management
- **Python Logic Tests**: URL redaction, entity detection, sequential ID assignment
- **Integration Tests**: End-to-end pipeline validation with sample documents

### Running Tests
Check for existing test files and run with standard Python testing tools. The project includes sample files in `sample-files/` for validation.

### Integration Testing
```bash
# Build with integration tests
./build_master.sh --test
```

### Model Testing
Use `marcut/model_mock_llm.py` for testing without requiring live Ollama service.

## Important Notes

### LLM Requirements
- LLM detection is **required** for legal documents - rules alone miss names and organizations
- Recommended model: llama3.1:8b
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
- **User data** stored in `~/.marcut/`
- **Models cached** in `~/.marcut/models/`
- **App Support logs** in `~/Library/Application Support/MarcutApp/` (GUI app logs)
- **Legacy logs** in `~/.marcut/logs/` (CLI/development logs)
- **Configuration** in `~/.marcut/config.json`
