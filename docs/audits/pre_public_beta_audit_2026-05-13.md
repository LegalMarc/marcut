# Pre-Public-Beta Audit

Date: 2026-05-13
Branch inspected: `codex/redaction-intelligence-release-20260512-clean`
Scope: Marcut local-first DOCX redaction app for confidential legal documents and PII.

This audit used separate specialist passes for correctness, security, privacy/data handling, performance, stability/reliability, and operational readiness. It is evidence-bound: findings below are supported by repository files, tests, docs, release scripts, or observed local/release state. No code patches were written as part of this audit.

Local debug logs are not treated as findings when debug logging is off by default and the UI can clear logs.

## Confirmed Findings

### Bugs And Correctness Defects

#### `--llm-detail` changes redaction behavior

Severity: High

Location: `src/python/marcut/cli.py`, `src/python/marcut/pipeline.py`, `src/python/marcut/llm_timing.py`

Evidence: The CLI describes `--llm-detail` as timing detail, but the enhanced path switches to `ollama_extract_with_timing(...)` over the whole document instead of the normal chunked enhanced path. That bypasses chunking/concurrency/validation behavior, and a timing extraction failure falls back to rules-only spans plus a warning.

Impact: A diagnostics flag can materially reduce redaction coverage, creating different output from the same input and settings.

Confidence: High

Suggested next action: Make timing instrumentation observe the production enhanced path without replacing extraction behavior; add a regression test proving `--llm-detail` does not change spans.

#### Advanced LLM controls are not faithfully honored

Severity: Medium

Location: `src/swift/MarcutApp/Sources/MarcutApp/SettingsView.swift`, `src/swift/MarcutApp/Sources/MarcutApp/PythonKitBridge.swift`, `src/python/marcut/model.py`, `src/python/marcut/model_enhanced.py`, `src/python/marcut/llm_timing.py`

Evidence: Swift exposes temperature and seed controls and forwards them into PythonKit, but the main enhanced Ollama path hard-codes or coerces downstream values: chunk extraction hard-codes seed `42`, and some requests coerce `temperature=0.0` to `0.1`.

Impact: User-facing reproducibility/debug settings can be misleading, and benchmark comparisons can be invalid.

Confidence: High

Suggested next action: Carry seed and temperature end-to-end through the production path, or adjust UI/docs to state the actual behavior.

#### Documented `llama_cpp`/GGUF CLI path is not wired through execution

Severity: Medium

Location: `docs/USER_GUIDE.md`, `src/python/marcut/cli.py`, `src/python/marcut/pipeline.py`, `src/python/marcut/model_enhanced.py`

Evidence: The user guide advertises `--backend llama_cpp --llama-gguf <path>`, and the CLI defines those arguments, but the execution call does not forward `--llama-gguf` or `--threads` into the redaction path. Tests cover parsing, not backend execution.

Impact: Public CLI behavior can fail or silently use the wrong model/backend.

Confidence: High

Suggested next action: Either wire the GGUF path into execution and test it, or remove the public interface/docs until supported.

### Security Vulnerabilities

#### Release script can report success when notarization was skipped

Severity: High

Location: `scripts/sh/build_appstore_release.sh`, `scripts/notarize_macos.sh`, `docs/RELEASE_CHECKLIST.md`

Evidence: `scripts/notarize_macos.sh` fails closed without credentials unless an explicit local skip is set, but `scripts/sh/build_appstore_release.sh` can treat missing notary credentials as a warning and later run Gatekeeper assessment with `|| true`.

Impact: A public-beta artifact could be treated as notarized/releasable when the script did not prove notarization.

Confidence: High

Suggested next action: Make all distribution release paths fail closed on missing/failed notarization unless an explicit local-only override is set, and make Gatekeeper assessment mandatory for public artifacts.

#### Metadata-only scrub reports bypass private-file permission hardening

Severity: High

Location: `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`, `src/python/marcut/report_html.py`, `src/python/marcut/report.py`

Evidence: The normal Python report path writes JSON with `0o600` and applies private permissions to generated HTML. The Swift metadata-only flow writes JSON directly with `Data.write`, and the HTML generation path writes with plain `open(...)` without the same permission hardening.

Impact: Metadata-only reports can contain full metadata values and may be more permissively readable than standard audit reports depending on filesystem defaults.

Confidence: High

Suggested next action: Route metadata-only JSON/HTML writes through the same owner-only permission helper or apply equivalent `0o600` handling after each write.

### Privacy And Data Handling Risks

#### DOCX sharing path can expose review artifacts as if they were finalized

Severity: High

Location: `src/swift/MarcutApp/Sources/MarcutApp/ContentView.swift`, `src/python/marcut/pipeline.py`, `src/python/marcut/docx_io.py`, `docs/TECHNICAL_ARCHITECTURE.md`

Evidence: Marcut intentionally writes proposed redactions as Word Track Changes. Deleted text remains recoverable in DOCX XML as `w:del`/`w:delText`, and docs correctly describe the DOCX as a review artifact until changes are finalized. The UI exposes a direct `ShareLink` for the output DOCX.

Impact: A user can accidentally share a review artifact containing recoverable original personal/confidential text.

Confidence: High

Suggested next action: Keep the Track Changes proposal workflow, but consolidate DOCX send choices into exactly two explicit paths: send a final redacted copy that accepts Marcut redaction changes and scrubs metadata, or send a review copy with Track Changes and metadata preserved after explicit confirmation.

#### Remote Ollama escape hatch conflicts with local-only privacy claims

Severity: High

Location: `src/python/marcut/model.py`, `src/python/marcut/network_utils.py`, `tests/test_model.py`, `docs/SECURITY.md`

Evidence: Default normalization forces non-loopback hosts to loopback, but `MARCUT_ALLOW_REMOTE_OLLAMA=1` disables loopback enforcement. The LLM prompt includes document text and is posted to `/api/generate`. Public docs state processing is local and inference stays on localhost.

Impact: A source/CLI run with the unsafe environment variable can transmit confidential document content to a remote Ollama-compatible endpoint.

Confidence: High

Suggested next action: Treat remote Ollama as developer-only unsafe mode with explicit naming, docs, and production environment clearing, or remove the escape hatch from public paths.

#### Tracked benchmark files include exact legal-entity text

Severity: Low

Location: `docs/model-benchmarks/framework_agreement_ground_truth_2026-05-12.json`, `docs/model-benchmarks/framework_agreement_scored_local_llm_benchmark_2026-05-12.md`

Evidence: Benchmark artifacts contain exact organization/location/entity strings from a framework-agreement sample.

Impact: If the source agreement is not synthetic/public/approved, repository publication can disclose sensitive sample data.

Confidence: Medium

Suggested next action: Confirm the sample agreement is synthetic or publication-approved; otherwise replace with sanitized synthetic entities before release.

### Performance And Scalability Risks

#### UI timeout/cancel is not reliably preemptive for blocking LLM work

Severity: High

Location: `src/swift/MarcutApp/Sources/MarcutApp/PythonKitBridge.swift`, `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`, `src/python/marcut/model.py`, `src/python/marcut/model_enhanced.py`

Evidence: PythonKit work is queued onto a single worker thread. Cancellation queues `PyErr_SetInterrupt()` onto that same worker, so it cannot run while the worker is blocked inside Python. Downstream Ollama calls use long non-streaming HTTP requests, and enhanced extraction waits chunk futures without a timeout.

Impact: The UI can show cancellation/timeout while Python/Ollama work continues and may still write outputs.

Confidence: High

Suggested next action: Add cooperative cancellation/timeout propagation into Python and Ollama calls, bound chunk futures, and prove Stop/timeout with a hanging fake Ollama server.

#### Metadata/report generation can expand large DOCX packages in memory before caps apply

Severity: High

Location: `src/python/marcut/pipeline.py`, `src/python/marcut/report_html.py`, `tests/test_metadata_scrubbing.py`

Evidence: Metadata reading captures full values and binary package parts before JSON serialization strips blob data. Existing tests verify small synthetic limits but do not prove large-package memory caps.

Impact: Large DOCX files with media/custom XML/comments can cause high memory use, slow report generation, or crashes.

Confidence: High

Suggested next action: Enforce size/count caps before retaining raw package data; add generated large-DOCX tests for JSON/HTML size, warnings, and memory behavior.

#### DOCX traversal and replacement are per-character

Severity: Medium

Location: `src/python/marcut/docx_io.py`

Evidence: `DocxMap` builds text and maps runs at character granularity, and replacement iterates each character in each redaction span.

Impact: Large documents or many spans can become slow or memory-heavy.

Confidence: Medium

Suggested next action: Add a large synthetic DOCX benchmark gate for body text, tables, headers/footers, comments, and many spans before deciding whether to optimize.

#### Consistency pass can rescan full text per ORG candidate

Severity: Medium

Location: `src/python/marcut/pipeline.py`

Evidence: The consistency pass builds candidate sets and can perform fuzzy full-document regex scans per ORG candidate.

Impact: Long agreements with many organizations/affiliates can trigger nonlinear runtime.

Confidence: Medium

Suggested next action: Add candidate/pattern/time limits and benchmark thousands of unique ORG candidates over multi-MB text.

#### Performance evidence does not cover production-scale behavior

Severity: Medium

Location: `tests/benchmark/model_benchmark.py`, `.github/workflows/macos-full-e2e.yml`, `docs/model-benchmarks/`

Evidence: Current benchmark and CI evidence use timing extraction or tiny generated DOCX inputs rather than full production `run_redaction` over representative multi-chunk documents with repeated runs.

Impact: Public-beta performance and reliability claims can be based on non-representative paths.

Confidence: High

Suggested next action: Add a release/nightly scale job using production redaction paths, representative sanitized fixtures, at least three runs per model, and tracked wall-time/RSS/output-size budgets.

### Stability And Reliability Risks

#### Output/report writes are not transactional

Severity: High

Location: `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`, `src/python/marcut/pipeline.py`, `src/swift/MarcutApp/Sources/MarcutApp/FileAccessCoordinator.swift`

Evidence: The PythonKit UI path writes final output/report paths directly in the selected destination. Python saves the DOCX before scrub/audit report completion, and a later report failure writes a failure report without cleaning up the already-written DOCX.

Impact: Failed or cancelled runs can leave ambiguous partial artifacts that users may mistake for complete redactions.

Confidence: High

Suggested next action: Write the full artifact set to UUID temp files on the same volume, validate, then atomic-move complete outputs into place.

#### CLI model-download fallback can hang indefinitely

Severity: Medium

Location: `src/swift/MarcutApp/Sources/MarcutApp/PythonBridge.swift`

Evidence: HTTP model pull has idle/resource timeouts, but fallback to `ollama pull` relies on `terminationHandler` and lacks an automatic deadline or idle watchdog.

Impact: A stalled model pull can leave setup stuck until manual cancellation.

Confidence: High

Suggested next action: Add a deadline and idle watchdog to the CLI fallback process, and test stalled stdout/stderr/no-exit behavior.

#### Release gates do not cover the Swift/PythonKit lifecycle under audit

Severity: Medium

Location: `.github/workflows/macos-full-e2e.yml`, `scripts/verify_bundle.sh`, `scripts/gui_e2e_watchdog.py`, `docs/DEVELOPER_GUIDE.md`

Evidence: The architecture mandates PythonKit/BeeWare app processing, but tag/nightly E2E redacts through bundled `run_python.sh -m marcut.cli`, and bundle verification checks launcher execution rather than GUI/PythonKit cancellation/timeout behavior. A GUI watchdog exists but is not part of the workflow.

Impact: CI can pass while the production app path has lifecycle bugs.

Confidence: High

Suggested next action: Add Swift app CLI/PythonKit and GUI watchdog E2E gates to release workflows.

#### Model readiness can race after preflight

Severity: Low

Location: `src/swift/MarcutApp/Sources/MarcutApp/PythonBridge.swift`, `src/swift/MarcutApp/Sources/MarcutApp/DocumentRedactionViewModel.swift`

Evidence: Preflight can return true based on model files, then processing separately probes `/api/show` for a bounded number of attempts and may fail with a retry-later message.

Impact: Users can see a readiness-success state followed by an immediate processing failure.

Confidence: Medium

Suggested next action: Use one model-readiness contract across preflight and processing, with consistent retry/backoff and user messaging.

### Maintainability And Operational Readiness Risks

#### Public-beta qualification doc is stale for current release state

Severity: High

Location: `docs/release/public_beta_qualification.md`, `pyproject.toml`, local/release artifact state

Evidence: The qualification doc still qualifies `0.5.95`, describes an ad-hoc artifact, and lists Developer ID/notarization/Gatekeeper as remaining blockers. Current source is `0.5.96`; local and published Developer ID DMG state should be reflected separately from the older qualification text.

Impact: Maintainers and beta decision-makers can rely on stale release-readiness evidence.

Confidence: High

Suggested next action: Replace or supersede the qualification report with current `0.5.96` evidence and clear remaining blockers.

#### Tag CI can go green without proving notarization

Severity: High

Location: `.github/workflows/macos-full-e2e.yml`

Evidence: The notarize/staple step only runs under a narrow condition. A tag run can pass while notarization is skipped.

Impact: Release tags can appear green without proving the final distribution property beta users need.

Confidence: High

Suggested next action: Make tag distribution jobs fail if notarization is skipped for public artifacts, or mark the job explicitly local/unsigned and block release publication.

#### Dependency/SBOM gates do not cover the shipped dependency graph

Severity: High

Location: `requirements-pinned.txt`, `scripts/generate_python_sbom.py`, `build-scripts/setup_beeware_framework.sh`, `src/swift/MarcutApp/Package.swift`

Evidence: Current gates cover nine direct Python pins. Transitive Python packages, Swift `PythonKit`, BeeWare Python support, and the embedded Ollama binary are outside the current SBOM/vulnerability gate.

Impact: Public-beta supply-chain risk is understated.

Confidence: High

Suggested next action: Generate SBOM/vulnerability evidence from the actual staged app bundle and include Swift/BeeWare/Ollama components.

#### Release version/config source-of-truth is fragile in clean clones

Severity: Medium

Location: `docs/DEVELOPER_GUIDE.md`, `.gitignore`, `scripts/sh/build_swift_only.sh`, `scripts/sh/build_appstore_release.sh`, `build-scripts/config.example.json`

Evidence: Docs say `build-scripts/config.json` is the version/build source of truth, but `.gitignore` ignores it. Some scripts fall back to `config.example.json`; the App Store release script can default to `0.0.0`.

Impact: Clean/public clones can build artifacts with wrong version metadata.

Confidence: High

Suggested next action: Make the tracked source-of-truth explicit and enforce version consistency across release scripts.

#### Public docs contain stale operational instructions

Severity: Medium

Location: `docs/README.md`, `src/python/marcut/cli.py`, release docs

Evidence: Docs include old operational claims, stale DMG/version references, and a stale `--enhanced` flag while the CLI now uses `--mode`.

Impact: Beta users or maintainers can run wrong commands or misunderstand release behavior.

Confidence: High

Suggested next action: Update public docs after remediation to match actual CLI, build, notarization, and Track Changes/final-share behavior.

#### Branch/review controls are not public-beta hardened

Severity: Medium

Location: `docs/backlog/pre_public_beta_audit_tickets.md`, `docs/release/public_beta_qualification.md`, repository settings observed by specialist pass

Evidence: Existing backlog records a review-tool caveat, qualification notes waived model review, and prior merged PRs reportedly had no formal review decision. No branch-protection/ruleset evidence was found by the operational pass.

Impact: Release governance is weaker than the risk profile of a confidential-document tool.

Confidence: Medium

Suggested next action: Use stacked branches with local best-available model reviews, record review outputs in docs, and add/verify branch protection before public beta.

## Needs Manual Verification

#### Built helper entitlements from actual beta artifacts

Severity: Medium

Location: `assets/MarcutOllama.entitlements`, `src/swift/MarcutApp/OllamaHelperService.entitlements`, built app/helper signatures

Evidence: The configured helper entitlement file is narrow, but a broader helper entitlement file still exists in the tree. Static inspection did not prove every build lane ignores it.

Impact: A helper could ship with broader file/network access than intended.

Confidence: Medium

Suggested next action: Run `codesign -d --entitlements :-` on the final built app and helper from the beta artifact.

#### Production launch environment never enables remote Ollama

Severity: Medium

Location: packaged app environment and release scripts

Evidence: Static code inspection did not find production code setting `MARCUT_ALLOW_REMOTE_OLLAMA=1`, but the escape hatch exists.

Impact: If present in packaged runtime environment, confidential document text can leave the device.

Confidence: Medium

Suggested next action: Inspect the built artifact and runtime environment for the unsafe variable, and add an assertion/gate.

#### Report UX coverage across all report types

Severity: Low

Location: UI report viewer, metadata-only reports, failure reports

Evidence: Standard audit reports have warning/share/burn UX. Static inspection did not fully verify equivalent warnings for metadata-only and failure report surfaces.

Impact: Users may mishandle sensitive generated reports.

Confidence: Medium

Suggested next action: Walk all report entrypoints and add a UI test or manual checklist for warning coverage.

## Public-Beta Readiness Assessment

Blockers:

- DOCX send/share workflow must avoid accidental external sharing of recoverable Track Changes review artifacts.
- Cancellation/timeouts must become truthful enough that stopped or timed-out runs cannot continue writing artifacts unnoticed.
- Release/notarization gates must fail closed for public artifacts and the qualification doc must reflect current evidence.
- Metadata-only report permissions must match standard sensitive-report permissions.
- Remote Ollama unsafe mode must be removed from public paths or made unmistakably developer-only and production-cleared.

Serious but non-blocking risks:

- Performance and memory behavior need production-scale gates for large DOCX/report scenarios.
- SBOM/vulnerability gates need to cover the actual shipped bundle, not only direct Python pins.
- CLI/backend/docs drift needs cleanup before public beta documentation is trusted.
- Branch/review controls should be hardened for a confidential-document product.

Areas that appear acceptable based on this review:

- Track Changes proposal workflow is intentional and mission-aligned.
- Standard audit report JSON uses owner-only permissions, and standard report UX warns before share/print.
- Forensic exports are disabled by default and tested for private permissions when enabled.
- Local debug logging is off by default and Clear Logs exists.
- DOCX XML parsing has XXE-focused safeguards documented and tested.
- Corrupted DOCX handling has meaningful defenses, though full queue/output failure coverage should be broadened.

Open questions and limits:

- The expected `docs/MAINTAINER_HANDOFF_COMPENDIUM.md` was not present in this checkout, so current repo docs/source were treated as authoritative.
- Some operational observations rely on local/release state from the specialist pass and should be re-run on the final beta artifact.
- The audit was primarily static plus read-only gates; live GUI/runtime behavior still needs verification after fixes.
