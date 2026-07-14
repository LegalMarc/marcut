# Changelog

All notable changes to this project will be documented in this file.

## 2026-07-14

### Feature-complete hardening review (issues #36-#54)
All 19 items from `docs/backlog/feature_complete_hardening_review_2026-07-05.md` were validated (survey file/line references were approximate, so several claims were refuted rather than fixed) and closed, each via its own PR with independent review.
- **Feature**: Add a PII detection precision/recall evaluation harness — a synthetic DOCX corpus generated at test time, a per-entity-type scorer, and a CI-gated rules-only test, with `DEVELOPER_GUIDE.md` instructions for running the full-LLM eval locally (A1, #36, PR #55).
- **Fix**: Verify DOCX redaction coverage across document parts — tables, headers/footers, footnotes/endnotes, textboxes, and content controls were already scanned (claim refuted), but review comments were found unscanned for PII and are now covered; also stop ORG-suffix regexes bridging paragraph/cell boundaries (A2, #37, PR #56).
- **Fix**: Eliminate chunk-boundary entity duplication and offset drift in enhanced LLM extraction by enforcing an offset invariant and deduping overlapping cross-chunk entities (A3, #38, PR #57).
- **Fix**: Fail closed on partial LLM chunk extraction failures — previously a failed chunk failed open silently, leaving unscanned text ranges undisclosed; now surfaced as a hard failure. Extended the same day to the `llama_cpp` backend, which had the identical gap (A4, #39, PRs #58 and #59).
- **Fix**: Validate LLM-derived spans (bounds + text match) before applying them as redactions, dropping invalid or drifted spans instead of silently corrupting output (A5, #40).
- **Fix**: Correct rules-layer accuracy — undashed SSN detection, phone/account-number false-positive disambiguation, and possessive-form exclusion matching; the address state-code validation claim was investigated and refuted (it already worked correctly) (A6, #41).
- **Fix**: Harden LLM JSON response parsing with a tolerant bracket/string repair fallback that recovers truncated responses (A7, #42).
- **Reliability**: Add bridge-level and heartbeat watchdogs so a wedged embedded Python worker fails fast with a recovery path instead of freezing the UI (B1, #43).
- **Reliability**: Add destination-writability and free-disk-space pre-flight checks before long processing runs and model downloads (B2, #44).
- **Reliability**: Detect and report a foreign process holding Marcut's expected Ollama port instead of silently talking to the wrong server (B3, #45).
- **Fix**: Sanitize user-facing failure alerts via a new `FailureMessagePresenter` so raw Python tracebacks no longer surface in the UI (B4, #46).
- **Reliability**: Hold a power assertion and health-check Ollama on system wake during long processing runs (B5, #47).
- **Reliability**: Verify (with a Swift test) that resume-after-kill never resurrects a partially-written document as complete (B6, #48).
- **Docs**: Re-evaluate the heartbeat timeout after the D2 streaming fix landed and close as a no-op — #54's intra-chunk token streaming (layered on the pre-existing keepalive thread) already keeps the heartbeat fresh through a single long Ollama chunk, so no new retry mechanism was needed; documented in `docs/design/streaming_progress.md` (B7, #49).
- **Test**: Expand failure-path coverage — Swift error-flow tests, a Python malformed-DOCX corpus, and property-based offset-invariant tests (hypothesis) (B8, #50).
- **Performance**: Profile the consistency pass and close as a no-op — the exact-match path is already single-pass and the fuzzy ORG scan is already bounded by the large-DOCX candidate limit (~134ms at realistic scale), so the O(candidates × doc length) concern was already mitigated by prior work; documented for re-open if a larger profile shows otherwise (C1, #51).
- **Performance**: Stream the DOCX metadata-scrub ZIP rewrite part-by-part instead of buffering all changed parts in memory (C2, #52).
- **Performance**: Benchmark LLM request concurrency and close as a no-op — raising server-side `OLLAMA_NUM_PARALLEL` gave no meaningful wall-clock win on Apple Silicon versus its near-linear memory cost, and the client-side thread pool's benefit is dispatch-latency hiding, not true parallel inference; no config change ships, findings recorded in `docs/PERFORMANCE_OPTIMIZATION.md` (C3, #53).
- **Feature**: Provide real fractional progress via Ollama token streaming (intra-chunk progress) plus a word-count-weighted batch ETA calculator (D2, #54).

### Additional fixes found during the review
- **Fix**: Perturb the seed on Ollama extraction self-correction retries so an empty model response can't deterministically repeat — root cause of a 5-day CI failure streak (#61).
- **Test**: Widen an overly-tight CI memory-threshold test bound that was flaking on measurement noise (#63).

## 2026-07-04
- **Release**: Produce a real Developer ID DMG (`MarcutApp-v0.5.96-AppStore.dmg`, later reconciled to `0.5.97`) via `scripts/sh/build_devid_release.sh` against a freshly-provisioned BeeWare `Python.framework`: signed with a Developer ID Application identity, submitted to Apple's notary service (accepted), stapled, and Gatekeeper-verified (`spctl` reports `accepted`/`source=Notarized Developer ID`). Full evidence, entitlement dump, and SBOM cross-check recorded in `docs/release/entitlement_governance_verification.md`'s Final Artifact Verification section.
- **Fix**: Give `scripts/release_preflight.sh`'s version-sync and secrets-check steps the same `config.json` → `config.example.json` fallback already used elsewhere, so the preflight gate can actually run on a fresh CI checkout where the untracked local signing config doesn't exist.
- **Chore**: Bump the interim project version to `0.5.97` to unblock the preflight version-sync gate after reconciling stacked remediation branches; the real product version/App Store number bump is deferred to upcoming release-prep work.
- **Chore**: Reconcile the pre-public-beta remediation stack's conflict resolutions (model catalog architecture, PythonBridge injection fix, unredacted-path-logging fix, and related Python/Swift merges) cleanly onto this branch's own history.

## 2026-07-03

### Pre-public-beta remediation (T0-T14)
Full ticket detail in `docs/backlog/pre_public_beta_audit_remediation_2026-05-13.md` and `docs/backlog/pre_public_beta_audit_tickets.md`.
- **Feature**: Replace the single DOCX `ShareLink` with an explicit choice between **Send Final Redacted Copy** (creates a separate copy, accepts Marcut's redaction Track Changes into it, and runs maximum-privacy metadata scrubbing before sharing) and **Send Review Copy** (requires explicit confirmation that Track Changes and metadata may still contain recoverable original text) (T1).
- **Security**: Replace the legacy `MARCUT_ALLOW_REMOTE_OLLAMA` override with an explicitly-named `MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA` developer-only escape hatch; public runtime paths (Swift subprocess/environment sync and Python's `get_ollama_base_url`) now strip or ignore both variable names so inference stays loopback-only by default and can't be silently redirected to a remote host (T2).
- **Security**: Apply owner-only `0o600` permissions to all sensitive report artifacts — JSON and HTML audit/scrub/metadata reports from both the Python writers and Swift-side writes/exports (T3).
- **Fix**: Make `--llm-detail` observe the actual production enhanced extraction path (instead of a separate non-chunked extractor) so detail mode no longer changes redaction output, while still emitting timing metadata and preserving normal failure semantics (T4).
- **Feature**: Forward `--backend llama_cpp --llama-gguf <path> --threads <n>` end-to-end into the unified redaction pipeline and the enhanced GGUF backend, fail clearly when no GGUF path is provided, and thread the configured seed/temperature through Ollama chunk-extraction and validation requests instead of hardcoding them (T5).
- **Reliability**: Add a cancellation/deadline system — `marcut/cancellation.py` (`ProcessingDeadlineExceeded`, `processing_deadline()`, `check_processing_deadline()`) reads `MARCUT_PROCESSING_DEADLINE_MONOTONIC`; Ollama HTTP requests, LLM timing, validation, and enhanced thread-pool waits now check the deadline and bound their timeouts to remaining processing time. Swift's `PythonKitRunner` sets/clears the deadline marker per phase and now calls `PyErr_SetInterrupt()` immediately on user stop instead of waiting on the async cancellation path (T6).
- **Reliability**: Make redaction finalization transactional — DOCX, audit JSON/HTML, and scrub JSON/HTML are staged to same-directory hidden temp files first and only `os.replace()`d into final names once the whole artifact set is written successfully, with temp files cleaned up on any failure or cancellation (T7).
- **Reliability**: Add an idle-output watchdog to the `ollama pull` CLI fallback (terminates stalled pulls with an actionable error) and wait for `/api/show` readiness after a model appears on disk, both at download-completion time and again before processing starts, closing a race where a model looks installed but isn't yet ready to serve requests (T8).
- **Security**: Bound metadata capture and report serialization sizes — embedded binary parts are summarized by default instead of retaining raw bytes, custom XML/fast-save/unknown-namespace previews are truncated under `MARCUT_METADATA_CAPTURE_MAX_STRING_CHARS`, and report JSON now applies string/list/dict budgets (`MARCUT_METADATA_REPORT_MAX_STRING_CHARS`, `MARCUT_METADATA_REPORT_MAX_LIST_ITEMS`, `MARCUT_METADATA_REPORT_MAX_DICT_ITEMS`) with warning codes for truncated values; explicit forensic/binary export remains available but bounded and owner-only (T9).
- **Performance**: Bound consistency-pass candidate/pattern scans with explicit environment-configurable budgets (total candidates, fuzzy ORG candidates, regex pattern text size) to prevent pathological unique-ORG scans on large documents, and add a synthetic large-DOCX production-path performance gate exercising body text, tables, headers/footers, comments, and metadata through `pipeline.run_redaction(..., mode="rules")` (T10).
- **Security**: Make release notarization fail closed — `scripts/notarize_macos.sh` no longer treats a pending notarytool status as success or swallows a failed post-staple Gatekeeper check with `|| true`; `build_appstore_release.sh` exits on code-signature verification failure; all notarization-skip paths (missing keychain profile, explicit skip) now require an explicit `MARCUT_ALLOW_NOTARIZATION_SKIP=1` override; the tag/nightly E2E workflow gained a fail-closed prerequisite step requiring signing identity and notarization secrets before a release-tag job can proceed (T11).
- **Security**: Generate the Python SBOM from actual shipped bundle components rather than direct dependency pins — `scripts/generate_python_sbom.py` now walks the staged `python_site` (or a built `MarcutApp.app` via `--bundle-root`) for transitive PyPI packages, SwiftPM dependencies from `Package.resolved`, and manual-review entries for the BeeWare `Python.framework` and embedded Ollama binary; `docs/release/python-sbom.json` regenerated (23 shipped components); `check_dependency_vulnerabilities.py` gained `--sbom` to scan shipped components via OSV (T12).
- **Docs**: Refresh `docs/release/public_beta_qualification.md` with current `0.5.96`+ evidence (superseding the stale `0.5.95` note), document the two DOCX send paths, and update release-checklist/SBOM guidance to point at the actual built app bundle (T13).
- **Security**: Add `scripts/verify_entitlements.sh` and `docs/release/entitlement_governance_verification.md` to verify built app/helper entitlements contain no forbidden debug/runtime-bypass entries, and wire final entitlement/SBOM/vulnerability/stapler/Gatekeeper checks into `build_tui.py` after Developer ID builds; document repository governance evidence (CODEOWNERS, PR template, CI workflows, branch protection ruleset) (T14).

### New features
- **Feature**: Add a search bar to `SettingsView` to filter settings sections and redaction rules.
- **Feature**: Add a native macOS notification when a model download completes.
- **Feature**: Add a "Retry Failed" button to re-queue only failed documents in a batch.
- **Feature**: Add an in-app log viewer sheet to Settings.
- **Feature**: Add export/import of redaction settings as a JSON profile.
- **Feature**: Add a live match preview to the excluded-words editor.
- **Feature**: Show estimated time remaining during batch redaction.
- **Feature**: Persist pending batch jobs and offer to resume them after an app restart.
- **Refactor**: Centralize UserDefaults keys into a typed `DefaultsKey` enum.
- **Refactor**: Unify model-name parsing between `gui.py` and `PythonBridge.swift`.
- **Refactor**: Move hardcoded Ollama model tags/parameters into a shared `models.json`, mirrored across `assets/`, `src/python/marcut/`, and Swift resources, with `model_config.py`/`ModelCatalog.swift` loaders and a `BundleResourceLocator.swift` helper for dev/production bundle resolution — pure data-location change, no recommendation-behavior change.
- **Build**: Add `scripts/release_preflight.sh`, gating automatable `RELEASE_CHECKLIST` steps (Python/Swift tests, SBOM generate+check, dependency vulnerability audit, markdown link check, version-sync, secrets check) into CI ahead of `macos-build-verify` and the release checklist.

## 2026-05-13
- **Fix**: Stop treating plain legal terms such as `Agreement` as `DOCID` redactions.
- **Fix**: Preserve specific legal entities such as `TIME USA, LLC` through ORG filtering instead of suppressing them as generic contract wording.
- **Fix**: Add derived alias redaction for entity-name aliases such as `TIME` while preserving generic roles such as `Publisher`.
- **Performance**: Align LLM timing benchmark extraction with the production Ollama context, prediction, and timeout budget.
- **Build**: Update App Store packaging for embedded Ollama 0.23.2 runtime bundling and helper signing.

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
