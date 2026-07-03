# Marcut-2 Backlog

This document tracks upcoming features, Quality of Life (QoL) improvements, technical debt, and new architecture directions discovered during system audits.

## 1. Quality of Life (QoL) Improvements
- **Settings Search Bar**: Add a `.searchable()` modifier to `SettingsView.swift` to allow lawyers to quickly find specific redaction rule toggles among the many settings.
- **Settings Profiles/Export**: Allow exporting `MetadataCleaningSettings` and `RedactionSettings` as a shareable JSON/Plist profile to maintain standard configurations across legal teams.
- **Estimated Time Remaining (ETA)**: Add ETA calculations based on token lengths processed to `DocumentRedactionViewModel` to improve the UX during large batch jobs.
- **Pause/Resume Batch Jobs**: Save pending job IDs to `UserDefaults` (or disk) to allow resuming batch jobs later, protecting against app crashes or interruptions.
- **Granular Progress Indications**: Bridge the LLM token stream back to Swift to show a true fractional progress bar, rather than jumping from phase to phase.
- **Native System Notifications on Model Download**: Add a system alert upon successful completion of multi-gigabyte Ollama model downloads.
- **Interactive Excluded Word Sandbox**: Let the user type a phrase in `OverrideEditorSheet` and see instantly if it matches an excluded term rule before running it on a real document.
- **Failed File Retry Action**: Provide a "Retry Failed" button in the GUI that specifically re-queues only documents marked as `.failed`, skipping success items.
- **Log Viewer UI**: Add a "View Logs" modal inside `SettingsView` so users don't have to manually navigate the Finder to `~/Library/Application Support/MarcutApp/logs`.

## 2. Maintainability & Technical Debt
- **Massive View Controllers**: Split `SettingsView.swift` (1,726+ lines) and `DocumentRedactionViewModel.swift` (2,600+ lines) into smaller, single-responsibility components (e.g., `BatchCoordinator`, `ProcessRunner`).
- **God Module in Python**: Refactor `docx_io.py` (2,400+ lines) into a formal python package (e.g., `marcut.docx.io`, `marcut.docx.scrub`) separating concerns like ZIP handling, XML manipulations, and CLI processing.
- **Stringly-Typed Defaults**: Refactor hardcoded strings for `UserDefaults` (e.g. `"MarcutApp.AdvancedModeEnabled"`) into a centralized `@AppStorage` enum or wrapper structure in Swift.
- **Mixed Subprocess Logics**: Normalize Model parsing rules (duplicated between `gui.py` and `PythonBridge.swift`) into a shared API layer.
- **Fragile Swift-to-Python Bridge**: Transition away from parsing unstructured JSON state files to a stricter Schema like Protobuf, FlatBuffers, or strict OpenAPI JSON specs.
- **Hardcoded Model Data**: Move hardcoded model tags (like `qwen3.5:9b` and their parameters) out of Swift/Python code and into a remote or local JSON config file for easier over-the-air updates.

## 3. Major New Directions (Innovation)
- **On-the-fly "Interactive Redaction" Mode**: Offer an interactive diff viewer where the LLM flags ambiguous spans (e.g., "I found 12 references to 'Project Phoenix', should I redact them?") for user approval.
- **Local RAG across Document Sets**: Implement a local Vector DB to store client references cross-document. If "John Doe" is redacted in Doc A, automatically pre-redact "Mr. Doe" in Doc B using graph clustering.
- **WebAssembly / Browser Deployment**: Compile the deterministic Python rule engine to WASM using Pyodide to create a fully in-browser, zero-install offline redaction fallback.
- **Multi-Model Orchestration Workflow**: Use a smaller model like `phi4-mini` for a fast first pass, and route only low-confidence sentence chunks to a larger model like `qwen3.5:9b`.
- **Incremental Track-Changes Support**: Support diff-only redaction by sending only the *added* paragraphs in a subsequent version of a contract to the LLM to drastically reduce processing time.
- **Automated "Redaction Rationale" Reporting**: Use the LLM to generate plain-English explanations in the audit log (e.g., "Redacted 'Acme Corp' because it represents the acquiring entity") to assist in automated privilege log generation.
