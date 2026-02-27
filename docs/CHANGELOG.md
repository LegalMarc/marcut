# Changelog

All notable changes to this project will be documented in this file.

## 2025-12-28
- **Docs**: Refine changelog style to use category prefixes
- **Docs**: Update changelog with full history back to origin
- **Refactor**: Move project docs to docs/ directory
- **Docs**: Docs cleanup: Update Changelog and remove redundant help file
- **Refactor**: Cleanup project root and ignore test artifacts

## 2025-12-26
- **Fix**: Fix regex performance: Implement O(N) Linear Token Scanning
- **Fix**: Fix regex: restore Company suffix, fix trailing space for connector patterns
- **Fix**: Fix regex over-redaction & enhance exclusions
- **Fix**: Fix unescaped quotes in DATE rule description
- **Fix**: Fix deinit actor isolation: move log cleanup to OllamaLogger.deinit
- **Refactor**: Refactor Ollama logging to use thread-safe OllamaLogger class
- **Fix**: Fix Swift actor isolation error in Ollama log writing
- **Fix**: Fix Address regex failure on multi-word capitalized street names
- **Update**: Extend Rule #4 to treat excluded words as generic in ORG detection
- **Fix**: Fix generic over-redaction of defined terms like 'The Company'
- **Fix**: Expand ORG pattern with comprehensive entity suffixes
- **Feature**: Add Trust and related entity types to ORG pattern
- **Feature**: Add PERCENT as separate GUI rule checkbox
- **Feature**: Add PERCENT pattern for numeric and spelled-out percentages
- **Fix**: Fix spelled-out money pattern to match multi-word amounts
- **Fix**: Fix startup hang and bundle help.md
- **Update**: Revert to altool for App Store submission (notarytool is for Developer ID only)

## 2025-12-25
- **Fix**: Fix code signing for App Store: sign all dylibs including llama_cpp
- **Update**: Successful app store upload 12.25.25
- **Fix**: New excluded words logic + ollama logging works
- **Security**: Post-security review hardening
- **Update**: Sync HELP.md and excluded-words.txt from assets/
- **Fix**: Fix DMG output path to .marcut_artifacts/ignored-resources/
- **Ui**: Rename main action button to 'Redact & Scrub'
- **Fix**: Fix Ollama log capture + scrub report status logic
- **Fix**: Fix Ollama streaming JSON + comprehensive test suite
- **Fix**: Add Info.plist generation and AppIcon copying
- **Fix**: Handle absolute paths in Ollama extraction and update resource paths

## 2025-12-24
- **Fix**: Correct paths in build scripts for new directory structure
- **Refactor**: Update build config for src/ layout
- **Refactor**: Final cleanup of root directory
- **Refactor**: Reorganize project structure for GitHub publication
- **Refactor**: Pre-cleanup file reorg
- **Fix**: Fix LLM debug logging to use _log_app_event instead of stderr
- **Feature**: Add sync_python_sources to all TUI build presets
- **Fix**: Fix ollama.log to actually capture Ollama output
- **Fix**: Sync root marcut/ folder with Sources fixes
- **Fix**: Fix scrub report icon detection with fuzzy filename matching
- **Fix**: Fix processing timeouts and encoding errors
- **Fix**: Fixing redaction bugs

## 2025-12-23
- **Update**: Good progress but action buttons missing
- **Update**: Metadata scrub no longer corrupting

## 2025-12-22
- **Fix**: Fix None preset corruption and missing report values
- **Feature**: Implement accurate before/after values for newly exposed settings
- **UI**: Expose 6 hidden metadata settings in UI, Presets, and Report
- **Feature**: Improve None preset detection and add before/after scrub report
- **Fix**: Fix corrupt output with None preset and improve report
- **Feature**: Add metadata scrub report icon and file output
- **Update**: Apply conditional hardening to main redact flow too
- **Fix**: Fix corrupt output when None preset selected
- **Fix**: Fix crash: Use safe .get() for Python dict access
- **Fix**: Fix crash: Python scrub_metadata_only return signature mismatch
- **Fix**: Fix unzip glob pattern for [Content_Types].xml
- **Feature**: Add secure zero-then-delete for temp validation files
- **Fix**: Fix false corrupt DOCX detection in sandbox
- **Refactor**: Wire all tests into TUI menu + cleanup legacy files
- **Feature**: Add comprehensive test suite for metadata scrubbing
- **Fix**: Metadata scrubbing overhaul + critical bug fixes (UNTESTED)
- **Feature**: Add enhanced DOCX validation, build caching, and dependency version checker
- **Fix**: Revert metadata scrub to worker.perform - fix deadlock regression
- **Fix**: Fix metadata scrub crash, comprehensive help.md rewrite with section numbers
- **Feature**: Metadata scrubbing implemented submission to App Store ready

## 2025-12-21
- **Feature**: Comprehensive metadata UI improvements and hyperlink fix
- **Fix**: Add clear BUILD COMPLETE banner with DMG path at end of TUI builds
- **Wire**: Connect metadata settings from Swift UI to Python pipeline
- **Feature**: Add granular metadata cleaning settings
- **Chore**: Expand .gitignore to reduce VS Code warnings
- **Chore**: Cleanup obsolete files and scripts
- **Chore**: Add ollama_binary to Git LFS for faster clones
- **Fix**: App Store and DMG builds working - Ollama signing fixed
- **Compliance**: Fix Ollama sandbox crash, update paths, and enable strict address detection

## 2025-12-20
- **Feature**: Release 2.1: Performance Boost & Address Detection
- **Feature**: Add GGUF auto-discovery to model benchmark
- **Feature**: Add model benchmark test rig for speed vs accuracy comparison
- **Feature**: Add performance optimization documentation with profiling insights
- **Feature**: Add --llm-detail flag for detailed LLM sub-phase timing
- **Feature**: Add --timing flag to CLI for phase-by-phase performance profiling
- **Fix**: Help window path lookup and redaction label fonts
- **Performance**: Everything working and we are going to update the health file now and then commence performance upgrades
- **Feature**: Excellent progress toward completion security implemented and knits remain remaining

## 2025-12-19
- **Update**: Notice banner working
- **Update**: All redaction tags firing
- **Fix**: Headers and footnotes working: Fix XML redaction persistence and resolve Swift build issues
- **Fix**: Fix UI clicks, formatting leaks, and enable Header/Footer redaction
- **Update**: Working again, formatting edge cases remain
- **Fix**: Acceptance of changes is now fixed

## 2025-12-18
- **Feature**: Accept tracked changes and stabilize progress
- **Feature**: Add Reveal Models button (halfway implemented, except track changes)
- **Docs**: Add notarization + sharing notes
- **Test**: Will tested and all is working

## 2025-11-30
- **Chore**: Skip URL/rule suites when marcut deps unavailable
- **Chore**: Remove backup and simplify ollama logging

## 2025-11-29
- **Update**: Everything working all at once leaving only fine-tuning of the reduction model itself as the next step
- **Update**: Far afield and redaction still failing

## 2025-11-27
- **Fix**: Fix XPC integration: resolve duplicate executionStrategy property and bridgeLog scope issue

## 2025-11-25
- **Fix**: Drop numpy dependency and simplify enhanced model
- **Chore**: Fix Python stub linking for arm64
- **Chore**: Relocate legacy runtime blobs to old-and-cold
- **Chore**: Quarantine legacy artifacts
- **Chore**: Point python payload to bundled sources
- **Fix**: Honor custom host and drop numpy dependency
- **UI**: Stuck on downloads and rules redaction requiring a model in place.
- **Chore**: Prune build artifacts and vendor bundles
- **Update**: Download working, redection fails

## 2025-11-24
- **UI**: Stuck on downloads and rules redaction requiring a model in place

## 2025-11-21
- **Feature**: Prepare App Store distribution for external LLM review
- **Build**: Trying to get an app store build
- **Fix**: Simplify signing process by skipping problematic framework signing
- **Fix**: Resolve codesign syntax errors and improve Python framework handling
- **Fix**: Resolve codesign bundle format ambiguous error for Python framework
- **Feature**: Wire up actual App Store certificate and provisioning profile
- **Fix**: Add certificate detection and validation for App Store signing

## 2025-11-20
- **Fix**: Add robust error handling for framework and resource copying
- **Feature**: Add Swift Package Manager App Store distribution to build TUI
- **Fix**: Good enough progress bar

## 2025-11-19
- **Fix**: Smooth chunk progress updates
- **Update**: Solid save point
- **Fix**: Make ProgressTracker compatible with simple Swift heartbeat callbacks

## 2025-11-18
- **Feature**: Eliminate repeated permission dialogs with session-based management
- **Chore**: Remove backup zip
- **Update**: Permissions good, progress bar goes backwards
- **Feature**: Implement permission system that requests access only when files are accessed

## 2025-11-16
- **Fix**: Ensure rule filters sync to python
- **Fix**: Good GUI and checkboxes unwired - fixed cancellation flag persistence issue
- **UI**: GUI good, checkboxes unwired, 1st document still cancels

## 2025-11-15
- **Docs**: Add override + dev_fast notes
- **UI**: GUI with serial pipeline working

## 2025-11-14
- **UI**: GUI working again, Rules only and AI

## 2025-11-07
- **Fix**: Implement hybrid CLI subprocess + AsyncStream solution - beachball fixed, progress stuck
- **UI**: GUI Working again but beachball while working
- **Feature**: Implement descriptive filename scheme for unified testing
- **Feature**: Implement unified subprocess pipeline architecture for CLI and GUI
- **Feature**: Add flexible test mode infrastructure for MarcutApp

## 2025-11-06
- **Feature**: Add comprehensive test suite and documentation for Marcut redaction pathways

## 2025-11-04
- **Feature**: Add memory management improvements and enhanced error recovery
- **Fix**: Fix GUI 30-second timeout issue and critical bugs preventing full redaction functionality

## 2025-11-03
- **Baseline**: Commit broken state with 30s GUI timeout issue

## 2025-11-01
- **Fix**: Gui loads but ollama times out after 30s
- **Chore**: Cleanup

## 2025-10-31
- **Chore**: Refresh embedded python runtime
- **Chore**: Snapshot working helper build

## 2025-10-30
- **Docs**: Capture macOS app architecture
- **Docs**: Note embedded interpreter diagnostics
- **Chore**: Drop pythonkit warm-up diagnostics
- **Chore**: Gate pythonkit diagnostics behind flag

## 2025-10-25
- **Fix**: Apply final architectural corrections to PythonBridge

## 2025-10-24
- **Feature**: Add log cleanup to App Store build script
- **Feature**: Add automatic log file cleanup to build script
- **Fix**: Apply corrected XPC architectural patches to resolve bind errors
- **Feature**: Complete XPC architectural implementation to resolve network binding issues
- **Fix**: Remove nested git repository and add .build/ to .gitignore
- **Feature**: XPC service fully functional - command line version is fully redacting

## 2025-10-23
- **Fix**: Resolve critical Ollama startup crashes and implement robust process management
- **Fix**: Resolve compilation errors for singleton pattern
- **Feature**: Add thread-safe singleton pattern to PythonKitRunner

## 2025-10-12
- **UI**: GUI working. Yay!

## 2025-10-11
- **Update**: Model loads but AI redaction stalls

## 2025-09-27
- **Chore**: Last version before bee packaging
- **Fix**: Ensure embedded Python framework loads again

## 2025-09-22
- **Fix**: Fix Python framework placement and add diagnostic logging - ensure Python.framework is in Contents/Frameworks and improve error reporting
- **Fix**: Fix Python dependencies and improve error logging - add llama-cpp-python with Metal support and better Python error reporting

## 2025-09-21
- **Update**: Model download and framework working again but redaction fails
- **Update**: Ollama still broke; trying load the .gguf model file directly from a path

## 2025-09-20
- **Fix**: Comprehensive LLM connectivity and model download fixes
- **Feature**: Struggling with LLM connection failure - model download failing

## 2025-09-18
- **Build**: Swift UI, DMG build, redactions not failed

## 2025-09-14
- **Update**: Swift and redaction working, tweaks next

## 2025-09-01
- **Feature**: Beautiful SwiftUI interface ready for demo (track changes needs work)

## 2025-08-30
- **Refactor**: 🧹 MAJOR CLEANUP: Organized project structure with archive
- **UI**: 🎉 WORKING GUI: Deterministic startup with embedded Ollama
- **Update**: Final version before DMG bundling attempt
- **Update**: Enhanced signature block detection for consistent name extraction
- **Feature**: Improve MONEY detection for bracketed amounts; introduce NUMBER label and rules; enhance prompt to differentiate MONEY vs NUMBER
- **Update**: Incremental progress towards accuracy
- **Feature**: Initial working enhanced redaction (two-pass LLM + rules) with track-changes DOCX output, CLI flag, and docs

## [0.2.3] - 2024-09-14

### Fixed
- **Critical**: Resolved Ollama API timeout issue that was blocking all document redaction
  - Root cause: Complex `ollama_extract_enhanced()` prompts were overwhelming the model
  - Solution: Modified `model_enhanced.py` to use simpler `ollama_extract()` function
  - Increased timeouts from 30s to 60s for larger document chunks
  - Disabled JSON format constraint that was causing llama3.1:8b model to hang

### Changed
- Updated progress tracking to show all 7 processing phases correctly
- Enhanced error handling in model extraction pipeline
- Improved Swift-Python bridge with proper environment configuration

### Added
- Comprehensive test suite (`test_like_swift.py`) for validating pipeline functionality
- DMG packaging script (`scripts/sh/build_swift_only.sh`) for distribution
- Progress tracking across all redaction phases

### Working Features
- ✅ Swift GUI processes documents successfully with progress tracking
- ✅ Python CLI full redaction pipeline operational
- ✅ Ollama integration stable with 60-second timeouts
- ✅ All 7 progress phases display correctly
- ✅ DMG packaging (MarcutApp-Swift-v0.2.3.dmg) ready for distribution
- ✅ Microsoft Word track changes generation
- ✅ Both rule-based and LLM entity extraction functional

### Test Results
- Successfully processed Compliance-Cert.docx: 46 entities detected
- Successfully processed loan-term-sheeet.docx: 30 entities detected
- All sample documents process without timeouts

## [0.2.2] - 2024-09-13

### Added
- SwiftUI native macOS application
- Embedded Ollama binary for self-contained distribution
- Professional DMG creation with code signing support

## [0.2.1] - 2024-08-30

### Added
- Enhanced two-pass LLM validation pipeline
- Document-level context analysis
- Selective entity validation based on confidence scores

## [0.2.0] - 2024-08-17

### Added
- Track changes support for Microsoft Word documents
- JSON audit reports with entity details
- Rule-based detection for structured PII

## [0.1.0] - 2024-07-28

### Initial Release
- Basic redaction functionality
- CLI interface
- Ollama integration for LLM-based detection
