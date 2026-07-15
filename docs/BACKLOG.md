# Marcut-2 Backlog

This document tracks upcoming features, Quality of Life (QoL) improvements, technical debt, and new architecture directions discovered during system audits.

## 1. Quality of Life (QoL) Improvements

All items originally listed here have shipped. See `docs/CHANGELOG.md` for details.

- ~~Settings Search Bar~~ — shipped (`.searchable()` in `SettingsView.swift`).
- ~~Settings Profiles/Export~~ — shipped as `RedactionProfile` export/import (`DocumentModels.swift`, `SettingsView.swift`).
- ~~Estimated Time Remaining (ETA)~~ — shipped (`BatchETACalculator.swift`).
- ~~Pause/Resume Batch Jobs~~ — shipped as pending-batch persistence/resume (`PendingBatchJobStore.swift`).
- ~~Native System Notifications on Model Download~~ — shipped (`modelDownloadCompletionNotifier` in `PythonBridge.swift`).
- ~~Interactive Excluded Word Sandbox~~ — shipped as a live match preview in the excluded-words editor (`ExcludedWordMatcher.swift`).
- ~~Failed File Retry Action~~ — shipped ("Retry Failed" button, `DocumentRedactionViewModel.swift`).
- ~~Log Viewer UI~~ — shipped (`LogViewerSheet.swift`).
- ~~Granular Progress Indications~~ — shipped as intra-chunk progress via Ollama token streaming plus a word-count-weighted batch ETA (`DocumentRedactionViewModel.swift`, `BatchETACalculator.swift`; Python side in `model.py`, `model_enhanced.py`, `llm_timing.py`). See `docs/design/streaming_progress.md`.

## 2. Maintainability & Technical Debt

- ~~Stringly-Typed Defaults~~ — shipped (centralized `DefaultsKey` enum, `DefaultsKey.swift`).
- ~~Mixed Subprocess Logics~~ — shipped (unified model-name-parsing between `gui.py` and `PythonBridge.swift`).
- ~~Hardcoded Model Data~~ — shipped (`models.json` catalog, `model_config.py`/`ModelCatalog.swift`/`BundleResourceLocator.swift`).

**Still open (design spikes exist, not yet implemented — see the referenced docs before starting):**

- **Massive View Controllers**: Split `SettingsView.swift` and `DocumentRedactionViewModel.swift` into smaller, single-responsibility components. See `docs/design/view_controller_decomposition.md` for a responsibility inventory, target structure, and a behavior-parity verification plan (required reading before touching either file — this app's redaction correctness is the reason a blind refactor is out of scope for an unattended pass).
- **God Module in Python**: Refactor `docx_io.py` into a formal python package. See `docs/design/docx_io_package_split.md` for the same kind of behavior-parity analysis.
- **Fragile Swift-to-Python Bridge**: Transition away from parsing unstructured JSON state files to a stricter schema. See `docs/design/bridge_schema_migration.md`, which also covers interaction with the cancellation/deadline and transactional-write systems.

## 3. Major New Directions (Innovation)

Each of these has a design-spike doc under `docs/design/` — read the linked doc before implementing; several carry meaningful correctness or privacy risk if built without the analysis there.

- **On-the-fly "Interactive Redaction" Mode**: Offer an interactive diff viewer where the LLM flags ambiguous spans for user approval. See `docs/design/interactive_redaction_mode.md`.
- **Local RAG across Document Sets**: Cross-document entity graph so redacting an entity in one document pre-redacts it elsewhere. See `docs/design/local_rag_cross_document.md` (covers cross-matter/cross-client privacy isolation, the central risk of this idea).
- **WebAssembly / Browser Deployment**: Compile the deterministic rules engine to WASM for an in-browser fallback. See `docs/design/wasm_browser_deployment.md` (concludes this would be rules-only and changes the threat model — read before pursuing).
- **Multi-Model Orchestration Workflow**: Fast first-pass model with escalation to a larger model for low-confidence chunks. See `docs/design/multi_model_orchestration.md`.
- **Incremental Track-Changes Support**: Diff-only redaction of newly-added paragraphs in a revised document. See `docs/design/incremental_track_changes_redaction.md` — flags a real under-redaction risk that needs a mitigation plan before implementation.
- **Automated "Redaction Rationale" Reporting**: LLM-generated plain-English explanations in the audit log. See `docs/design/redaction_rationale_reporting.md` (covers how to label LLM-generated rationale as inference, not verified fact).

## 4. CI / Infrastructure

- **Self-Hosted GitHub Actions Runner** ([PR #34](https://github.com/LegalMarc/Marcut/pull/34), open, deferred): Points `ci.yml`, `macos-build-verify.yml`, and `macos-full-e2e.yml` at a local `[self-hosted, marcut-local]` runner instead of GitHub-hosted `macos-14`. Deferred during the 2026-07-15 release-readiness pass: the nightly/tag E2E red streak that motivated looking at this again turned out to have a deterministic root cause unrelated to runner choice (a `//`-comment-stripping regex in `parse_llm_response()` corrupting any LLM-extracted entity containing a URL — fixed on `fix/json-comment-strip-url-corruption`), so switching runners isn't needed to restore green CI. Revisit only if GitHub-hosted runner cost/queue-time/resource limits become a concrete problem — the security tradeoff noted in the PR (self-hosted runners execute arbitrary code from workflow-triggering events on the host machine) means it shouldn't be merged just because it's sitting there.
