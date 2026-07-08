# Marcut Maintainer Handoff Compendium

Generated: 2026-05-12

This document is a handoff for a new maintainer who has the repository but does not have the project chat history. It focuses on the context, decisions, constraints, and active work that are easy to miss from files alone.

## Scope and Evidence

The accessible project chat history for this run is limited. I searched the local Codex memory store for Marcut-specific history and found no Marcut rollout summaries or durable prior-session notes. This handoff therefore combines:

- The current user-provided project instructions for this repo.
- The current repository state.
- The committed git history visible locally.
- The current dirty worktree and untracked files.
- Existing project docs, especially the Developer Guide and Technical Architecture.

Treat statements about prior discussion as "known from current accessible context," not as a complete transcript of all historic conversations.

## Maintainer Mindset

The owner explicitly values quality over speed and does not want shortcuts. Important implications:

- Do not optimize for brevity at the expense of quality.
- Ask questions about important product or architecture decisions before diving in.
- If there is a logical next step, continue without waiting for permission.
- Use plans and reports liberally, and put durable plans/reports in `docs/`, not in tmp.
- Do not ask the owner to do manual work that can be done through CLI automation.
- Do not implement hacks. Prefer robust fixes even when they take longer.
- Address issues by severity from critical to low/nit, regardless of whether the current task created them.
- The expected bar is "would not embarrass the owner," especially for security, legal/professional workflows, and App Store packaging.

This is a legal/professional document redaction app. Default to conservative privacy, security, auditability, and deterministic behavior.

## Product Summary

Marcut is a local-first macOS application and Python CLI for redacting sensitive information from Microsoft Word `.docx` files. It produces Word Track Changes output plus JSON reports. The core user is a legal or professional user reviewing documents where false negatives can be serious and false positives need to be reviewable.

Core product principles:

- Process documents locally.
- Never upload document contents to cloud services.
- Use deterministic rules for structured PII.
- Use optional local AI through Ollama for context-aware entities such as people, organizations, brands, and other legal-document entities.
- Preserve auditability through Track Changes and structured reports.
- Scrub document metadata where requested.
- Keep the bundled macOS app self-contained and App Store safe.

## Non-Negotiable Architecture

The macOS app must use the PythonKit + BeeWare Python framework architecture. This is explicitly documented as mandatory in `docs/DEVELOPER_GUIDE.md`.

Allowed:

- SwiftUI native app.
- PythonKit for in-process Swift/Python integration.
- BeeWare `Python.framework` with Python 3.11 embedded in the app bundle.
- Direct calls into the Python redaction pipeline.
- A shared underlying pipeline for GUI and CLI paths.

Forbidden:

- Reintroducing subprocess-based Python execution for app processing.
- Depending on system Python for the production app.
- `python_launcher.sh`, `run_python.sh`, PyInstaller, py2app, or similar legacy execution paths as core architecture.
- App Store-hostile process orchestration.

The source Python CLI can be useful for development and automation, but the bundled macOS product must remain self-contained.

## Current Git State

The local repo is on `main`.

Visible commit history:

- `6b6aae1e chore: Apply deep audit bug fixes across Swift bridge, Python lifecycle, and Chunker constraints`
- `a6af9d96 Initial commit`

The latest commit appears to have been a broad audit/fix pass touching Python lifecycle, Swift bridge behavior, model defaults, Ollama handling, docs, tests, and chunking.

At generation time, the worktree is dirty. Do not assume the dirty changes are disposable. They likely represent active development.

Modified files:

- `assets/help.md`
- `scripts/sh/build_swift_only.sh`
- `src/python/marcut/chunker.py`
- `src/python/marcut/cli.py`
- `src/python/marcut/docx_io.py`
- `src/python/marcut/gui.py`
- `src/python/marcut/llm_timing.py`
- `src/python/marcut/model_enhanced.py`
- `src/python/marcut/ollama_manager.py`
- `src/python/marcut/pipeline.py`
- `src/python/marcut/rules.py`
- `src/python/marcut/unified_redactor.py`
- `src/swift/MarcutApp/Sources/MarcutApp/DocumentModels.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/MarcutApp.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/PythonBridge.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/Resources/help.md`
- `src/swift/MarcutApp/Sources/MarcutApp/SettingsView.swift`
- `src/swift/MarcutApp/Tests/MarcutAppTests/MarcutAppTests.swift`
- `test_overlap.py`

Untracked files:

- `scripts/generate_ground_truth.py`
- `scripts/run_qwen_experiment.py`
- `docs/BACKLOG.md`
- `docs/LLM_UPGRADE_EXPERIMENT_RESULTS.csv`
- `docs/LLM_UPGRADE_STABILIZATION_PLAN.md`

Maintenance implication: before committing or rebasing, inspect the dirty diff carefully and separate active experimental work from production-ready changes.

## Repository Shape

Important top-level areas:

- `src/python/marcut/`: Python package for DOCX parsing, redaction logic, reporting, Ollama integration, CLI, and metadata scrubbing.
- `src/swift/MarcutApp/`: Swift Package for the macOS app.
- `src/swift/MarcutApp/Sources/MarcutApp/`: SwiftUI app, Python bridge, settings, app lifecycle, document model/view model, resources.
- `src/swift/MarcutApp/Sources/MarcutApp/Resources/`: bundled app resources such as help, prompts, and exclusions.
- `src/swift/MarcutApp/Sources/MarcutApp/python_site/`: bundled Python dependencies and package material for the app.
- `src/swift/MarcutApp/Sources/MarcutApp/Frameworks/Python.framework/`: embedded BeeWare Python framework in local tree.
- `tests/`: Python tests.
- `tests/scripts/`: integration, app, metadata, GUI, and bundle validation scripts.
- `scripts/` and `scripts/sh/`: build, release, and utility scripts.
- `docs/`: durable project documentation and reports.

Important docs already present:

- `docs/DEVELOPER_GUIDE.md`
- `docs/TECHNICAL_ARCHITECTURE.md`
- `docs/SECURITY.md`
- `docs/METADATA_HARDENING.md`
- `docs/PERFORMANCE_OPTIMIZATION.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/USER_GUIDE.md`
- `docs/CHANGELOG.md`

## Runtime Architecture

Marcut has three major layers:

1. SwiftUI app and PythonKit bridge.
2. Embedded Python runtime and `marcut` package.
3. Local Ollama service for enhanced AI extraction.

The app orchestrates user interactions, file access, settings, logging, model management, and progress display. Python does the heavy document processing.

The app's Python integration uses:

- `PythonKitRunner`
- `PythonWorkerThread`
- `PythonBridgeService`
- `DocumentRedactionViewModel`

Important threading rule: CPython work is serialized through a dedicated owner thread. Do not introduce concurrent CPython entry from random Swift tasks. The GUI queues documents sequentially because the embedded runtime is treated as serial.

The current Python LLM extraction code is experimenting with parallel Ollama HTTP calls inside Python. That is separate from Swift/Python interpreter ownership and needs careful validation.

## Python Pipeline

The main redaction flow is centered on `src/python/marcut/pipeline.py` and `src/python/marcut/unified_redactor.py`.

Typical stages:

1. Load DOCX via `DocxMap`.
2. Build a text/XML mapping.
3. Run deterministic rules from `rules.py`.
4. Optionally chunk text and run local LLM extraction/validation.
5. Snap spans to better word/entity boundaries.
6. Merge overlaps and cluster repeated entities.
7. Write Track Changes redactions back to DOCX.
8. Write JSON redaction report.
9. Optionally scrub metadata and write scrub report.

Key modules:

- `docx_io.py`: DOCX ZIP/XML handling, Track Changes generation, metadata and embedded media hardening. It is large and high risk.
- `rules.py`: deterministic pattern detection and exclusion logic.
- `unified_redactor.py`: unified API/CLI entrypoint for redaction modes.
- `pipeline.py`: orchestration, merging, consistency, progress, scrub integration.
- `model.py`: lower-level Ollama extraction.
- `model_enhanced.py`: enhanced extraction, validation, caching, document context.
- `chunker.py`: chunking strategy for long documents.
- `report.py`, `report_html.py`, `report_common.py`: audit and scrub reports.
- `ollama_manager.py`: local Ollama service and model management.
- `progress.py`, `progress_widgets.py`: progress reporting and UI-facing events.

## Redaction Modes

Documented mode names include:

- `rules`
- `enhanced`
- `rules_override`
- `constrained_overrides`
- `llm_overrides`

In docs and code, `enhanced` maps conceptually to a rules-plus-AI path. `strict` appears as an alias for rules in help text.

Mode meaning to preserve:

- Rules-only must be fast, deterministic, and not require model availability.
- Enhanced modes may use Ollama but must remain local.
- AI should supplement rules, not silently weaken deterministic safety without explicit validation/reporting.

## Model Strategy and Active Model Migration

The codebase is in the middle of a model-default migration.

Old/default model references:

- `qwen3.5:9b`
- `qwen3.5:4b`

New/default model references in dirty worktree:

- `qwen2.5:14b` as the main recommended/default model.
- `qwen2.5:7b` as a balanced option.
- `phi4-mini:3.8b` as lightweight option.
- `qwen3.5:35b` as an ultra/highest-accuracy option requiring much more memory.

Changed defaults appear in:

- `src/python/marcut/cli.py`
- `src/python/marcut/gui.py`
- `src/python/marcut/ollama_manager.py`
- `src/python/marcut/model_enhanced.py`
- `src/swift/MarcutApp/Sources/MarcutApp/DocumentModels.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/MarcutApp.swift`
- `src/swift/MarcutApp/Sources/MarcutApp/PythonBridge.swift`
- `assets/help.md`
- `src/swift/MarcutApp/Sources/MarcutApp/Resources/help.md`

Maintenance risk: hardcoded model lists are duplicated across Swift, Python, docs, and tests. `docs/BACKLOG.md` correctly calls out that model metadata should eventually move into a config file.

## Active LLM Experimentation

The dirty worktree includes several experimental or not-yet-proven LLM changes:

- `llm_concurrency` is being added across Python and Swift.
- `think_mode` and `format_schema` support are being threaded through Python CLI and model calls.
- `model_enhanced.py` now uses `ThreadPoolExecutor` for chunk extraction and asynchronous validation batches.
- `llm_timing.py` now accepts `think_mode` and constrained `format_schema`.
- `unified_redactor.py` has CLI flags `--think` and `--format-schema`.
- `SettingsView.swift` adds an LLM concurrency slider from 1 to 5 workers.
- `PythonBridge.swift` passes `llmConcurrency` through to Python.
- `test_overlap.py` has become an ad hoc async/concurrency overlap experiment.
- `scripts/generate_ground_truth.py` and `scripts/run_qwen_experiment.py` are untracked experiment scripts for Qwen model comparisons.
- `docs/LLM_UPGRADE_EXPERIMENT_RESULTS.csv` currently reports similar F1 and extremely low latency for all models/configurations, which is suspicious and should not be treated as conclusive without validating the experiment inputs and whether real Ollama calls ran.

Critical review needed before shipping these changes:

- Confirm `ThreadPoolExecutor` does not mutate shared lists without locks. The current code introduces locks but still needs careful review around `to_validate_buffer`, `all_entities`, `warnings`, and progress state.
- Confirm chunk completion order does not affect span order or report determinism.
- Confirm parallel Ollama requests do not overload local memory or cause model server instability.
- Confirm `llm_concurrency` from the Swift settings is persisted, bounded, and honored in all processing paths.
- Confirm command-line `--llm-concurrency` actually exists in the relevant parser and is wired consistently. The dirty diff showed `unified_redactor.py` passing a hardcoded default in one CLI flow.
- Confirm `think_mode` parsing is compatible with the target Ollama versions and models. Thinking-model response fields have appeared as both `response` and `thinking`.
- Confirm structured `format_schema` works for both extraction and validation, not just one path.

## Known Build and Packaging Constraints

Primary build entrypoint:

- `./build_tui.py`

Developer docs recommend using the TUI rather than calling many lower-level scripts directly.

Important release policy:

- `scripts/sh/build_appstore_release.sh` is the only App Store build pipeline.
- `src/swift/MarcutApp/build_appstore.sh` is a compatibility wrapper.
- `build-scripts/config.json` is the source of truth for version/build number.

Production app bundle must include:

- BeeWare `Python.framework`.
- `python_site` dependencies.
- bundled `marcut` package.
- embedded Ollama binary.
- Ollama Metal runners.
- entitlements and deep code signing for frameworks/dylibs/so files.

Current dirty packaging work:

- `scripts/sh/build_swift_only.sh` changes DMG creation. It now creates a fixed-size HFS+ DMG, mounts at a custom mount dir, uses `owners off`, copies payload with `ditto`, and cleans up custom mount dirs.
- This should be tested on a clean machine or clean macOS user because DMG creation/mount customization can be brittle.

## Sandbox and File Access

Sandbox compliance is central.

Important storage paths:

- `~/Library/Application Support/MarcutApp/models/`
- `~/Library/Application Support/MarcutApp/ollama/`
- `~/Library/Application Support/MarcutApp/Work/Staging/`
- `~/Library/Application Support/MarcutApp/Input/`
- `~/Library/Application Support/MarcutApp/Overrides/`
- `~/Library/Application Support/MarcutApp/logs/`

GUI file access uses user-selected files/security-scoped access. CLI mode inside the app has stricter sandbox requirements and may require staging under app support.

Do not loosen sandbox access just to make tests easier. Fix staging, bookmarks, or file coordination instead.

## Metadata and Security Context

Metadata scrubbing is a first-class feature, not an afterthought.

Important security behaviors:

- XML parsing should avoid entity resolution and XXE risks.
- DOCX should be processed mostly in memory rather than full untrusted extraction to disk.
- Reports must escape HTML safely.
- Metadata scrub reports should provide before/after visibility.
- Hidden metadata, custom properties, comments, revisions, embedded images/files, thumbnails, and app properties are all relevant.

Current dirty security-related changes:

- `docx_io.py` now re-raises `OSError` and `MemoryError` during DOCX ZIP rewrite instead of swallowing them as best-effort warnings. This is likely correct: storage/memory failures should fail loudly.
- JPEG APP segment parsing now clamps `segment_end` to the data length.
- `PythonBridge.swift` removes a zero-out "secure erase" pass and just deletes files, with a comment noting APFS copy-on-write makes zeroing ineffective and FileVault handles data-at-rest protection. This is technically reasonable, but review whether product/security docs need to explain it.
- `PythonBridge.swift` changes Ollama temp dirs from `0755` to `0700`.
- `PythonBridge.swift` randomizes Ollama port selection within `11434...12434` instead of linear scan.

## UI and Settings Context

The Swift UI is currently concentrated in large files:

- `SettingsView.swift`
- `DocumentRedactionViewModel.swift`
- `PythonBridge.swift`

Known technical debt from `docs/BACKLOG.md`:

- Split `SettingsView.swift` into smaller components.
- Split `DocumentRedactionViewModel.swift` into smaller coordination/services.
- Move hardcoded UserDefaults strings into a central wrapper.
- Move hardcoded model metadata into config.

Active Settings changes:

- Adds direct model download from a model row when the model is not installed.
- Adds a `downloadSpecificModel` first-run entry point.
- Adds model options for `qwen3.5:35b`, `qwen2.5:14b`, `qwen2.5:7b`, and `phi4-mini:3.8b`.
- Adds LLM concurrency slider.

Review needed:

- Ensure the "recommended" default is consistent. Some dirty code uses `qwen2.5:14b` as default, while first-run selection fallback appears to prefer `qwen3.5:35b` when no model is installed.
- Ensure accessibility identifiers remain stable enough for GUI tests.
- Ensure the large 35B model is not promoted as default on machines that cannot support it.

## Progress, Heartbeats, and Long Runs

The app has had issues around long-running LLM calls and perceived hangs. Current architecture uses:

- Progress callbacks from Python.
- Keepalive events during LLM processing.
- Swift heartbeat monitoring.
- Timeout settings.

Active changes:

- `DocumentRedactionViewModel` heartbeat timeout changed from 30 seconds to 120 seconds.
- `model_enhanced.py` keepalive reporting now uses overall elapsed time and chunk counters.
- `PythonBridge.swift` reduces an Ollama streaming request idle timeout from 1 hour to 20 seconds while keeping resource timeout at 1 hour.

Risks:

- Too-short idle timeout can trigger fallback during valid slow local generation.
- Too-long heartbeat masks actual hangs.
- Parallel chunk execution makes progress harder to interpret because chunk completion is not necessarily sequential.

Use real long-document tests before shipping progress/timeout changes.

## DOCX and Boundary Handling

The app's output quality depends on span boundaries being correct in Word XML.

Active boundary/suffix changes:

- `chunker.py` lowers default overlap from 400 to 200.
- `pipeline.py` changes snapping logic to preserve possessive suffix handling and organization suffix periods.
- `pipeline.py` adds/updates organization suffix recognition for many legal/business entity suffixes.
- `rules.py` allows `/` and `-` inside tokens in `_is_excluded_combo`.

Review needed:

- Lower overlap may improve speed but can miss entities split across chunks. Validate on documents with names/orgs crossing chunk boundaries.
- Organization suffix expansion must not over-redact generic words like "Capital," "Trust," "Group," or "Bank" when context is weak.
- Track Changes output should be opened in Word or validated structurally after span-boundary changes.

## Reporting

Reports matter because users need audit trails.

Report modules:

- `report.py`: redaction audit reports.
- `report_html.py`: metadata/scrub report rendering.
- `report_common.py`: shared escaping, CSS, file size, MIME, and UI utilities.

Keep report output deterministic and safe:

- Escape all user/document text in HTML.
- Preserve enough details to explain redaction decisions.
- Avoid leaking unredacted sensitive content where a report is meant to be shareable.
- Be explicit about suppressed/ignored spans and warnings.

## Testing Strategy

Python tests:

- `python3 -m pytest`
- Specific useful suites include:
  - `tests/test_pipeline.py`
  - `tests/test_rules.py`
  - `tests/test_unified_redactor.py`
  - `tests/test_docx_io.py`
  - `tests/test_metadata_scrubbing.py`
  - `tests/test_url_logic.py`
  - `tests/test_model_enhanced.py`
  - `tests/test_report_common.py`

Swift tests:

- `swift test --package-path src/swift/MarcutApp`

Build/test harness:

- `./build_tui.py`
- `python3 run_tests.py` is referenced in docs; check whether it uses the repo venv.
- `tests/scripts/run_full_test_suite.py`
- `tests/scripts/validate_app_environment.py`
- `tests/scripts/run_metadata_matrix.py`
- `tests/scripts/local_e2e.sh`
- `tests/scripts/validate_bundle.sh`

For app release validation, also test:

- App launch.
- First-run model download.
- Rules-only redaction without a model.
- Enhanced redaction with a local model.
- Metadata-only scrub.
- Batch redaction.
- Cancel during long enhanced processing.
- Re-run after cancel.
- CLI mode from app bundle.
- DMG installation on a clean machine/user.

## Experiment Scripts

Experiment scripts currently exist:

- `scripts/generate_ground_truth.py`
- `scripts/run_qwen_experiment.py`
- `docs/LLM_UPGRADE_EXPERIMENT_RESULTS.csv`

The experiment workflow appears to be:

1. Generate ground truth reports from `.docx` files in `.marcut_artifacts/ignored-resources/sample-files-marcut` using a large Qwen model.
2. Run a model/config matrix across Qwen models.
3. Compare extracted spans by lowercased `text|label`.
4. Save average F1 and latency to CSV.

Known weaknesses:

- If the ground truth is generated by another model rather than human review, F1 measures agreement with that model, not correctness.
- Span comparison by exact text/label ignores offset quality and duplicate occurrences.
- Current CSV values are all identical, which suggests the experiment may have run on empty/no-op inputs, cached data, mock behavior, or nonrepresentative docs.
- Temporary outputs go to `/tmp`, while the owner's project instruction says durable reports/plans belong under `docs/`.

Before relying on these numbers, audit the sample set, manually review ground truth, confirm real model calls, and include offset-level scoring.

## Backlog Highlights

`docs/BACKLOG.md` is useful planning input. It lists:

QoL ideas:

- Settings search.
- Settings profiles/export.
- ETA estimates.
- Pause/resume batch jobs.
- Granular token-stream progress.
- Native notifications for model download.
- Interactive excluded-word sandbox.
- Retry failed files.
- Log viewer UI.

Maintainability:

- Split very large Swift view/view-model files.
- Refactor `docx_io.py` into a package.
- Centralize UserDefaults keys.
- Normalize model parsing/metadata.
- Replace fragile state-file/JSON bridge patterns with stricter schemas.
- Move model data into config.

Future product directions:

- Interactive redaction review.
- Local RAG across document sets.
- Browser/WASM rules engine.
- Multi-model orchestration.
- Incremental redaction between document versions.
- Automated redaction rationale.

Treat backlog as planning input, not committed product scope.

## Common Maintenance Risks

1. Reintroducing subprocess Python into the app.

This violates the current architecture direction and App Store safety goals.

2. Breaking rules-only mode while improving enhanced mode.

Rules-only is important because it is deterministic, fast, and model-free.

3. Treating local LLM output as inherently safe.

AI extraction and validation should be bounded, reported, and conservative. Never let AI silently suppress deterministic redactions unless the mode and report make that clear.

4. Changing model defaults in one layer only.

Model ids are duplicated. Check Swift settings, Swift defaults, app CLI help, Python CLI defaults, Ollama manager, docs, and tests.

5. Under-testing DOCX output.

Unit tests are not enough for Word compatibility. Open representative output in Word or validate the actual XML revisions.

6. Swallowing serious IO failures.

Best-effort metadata cleanup warnings are acceptable for some optional hardening, but save failures, memory failures, corrupt output, and permission failures should surface clearly.

7. Assuming App Store sandbox behavior matches source CLI behavior.

Source CLI may work with broad filesystem access while bundled app CLI/GUI needs sandbox-safe staging and bookmarks.

8. Letting experimental scripts or local artifacts drift into release.

There are generated caches, `.DS_Store`, embedded frameworks, sample docs, and experiment outputs in the tree. Be deliberate about what belongs in source control.

## Practical First-Day Checklist for a New Maintainer

1. Read `docs/DEVELOPER_GUIDE.md` and `docs/TECHNICAL_ARCHITECTURE.md`.
2. Inspect `git status --short` and `git diff --stat`.
3. Decide which dirty changes are production work versus experiments.
4. Run the Python tests most relevant to the touched files.
5. Run Swift tests if Swift files are touched.
6. Build the app through `./build_tui.py`.
7. Test one rules-only DOCX and one enhanced DOCX.
8. Open the output DOCX in Word and inspect Track Changes.
9. Check generated JSON reports and scrub reports.
10. Update docs when defaults, model options, or workflows change.

## Commands Worth Knowing

Install/editable Python package:

```bash
python3 -m pip install -e .
```

Run Python tests:

```bash
python3 -m pytest
```

Run a targeted Python test:

```bash
python3 -m pytest tests/test_unified_redactor.py -v
```

Build Swift package:

```bash
swift build --package-path src/swift/MarcutApp
```

Run Swift tests:

```bash
swift test --package-path src/swift/MarcutApp
```

Use build TUI:

```bash
./build_tui.py
```

Source CLI example:

```bash
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode enhanced --model qwen2.5:14b
```

Rules-only CLI example:

```bash
marcut redact --in input.docx --out runs/out.docx --report runs/out_report.json --mode rules
```

App CLI examples:

```bash
MarcutApp --diagnose
MarcutApp --redact --in /path/to/file.docx --outdir /tmp/out --mode enhanced --model qwen2.5:14b
MarcutApp --download-model qwen2.5:14b
```

## Open Questions to Resolve

These are important enough to ask the owner or validate with real tests before shipping related changes:

- Should `qwen2.5:14b` or `qwen3.5:35b` be the true recommended first-run model?
- What minimum RAM/device class is supported for enhanced mode?
- Should `llm_concurrency` be exposed to normal users, hidden in advanced settings, or auto-tuned?
- Is thinking mode intended for production, experimentation, or a hidden diagnostic option?
- Should constrained JSON schema mode be mandatory for validation once proven?
- What is the acceptance benchmark for model quality: human-labeled legal sample set, model-agreement F1, manual review, or all of these?
- Which local/generated artifacts should be removed from version control before release?

## Final Guidance

Marcut's hard parts are not just code mechanics. The maintainer needs to preserve trust: local-only processing, legally reviewable output, deterministic fallback behavior, and robust App Store packaging. When in doubt, choose the change that makes failures visible, reports more auditable, and user data less exposed.
