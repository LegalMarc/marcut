# Pre-Public-Beta Audit Remediation Backlog

Date: 2026-05-13
Audit report: `docs/audits/pre_public_beta_audit_2026-05-13.md`

This backlog must be stubbed before implementation. Work should proceed on stacked `codex/` branches, with local best-available model reviews after each stack segment. If no automated review integration exists, spawn/manual-run the best available local model review and record findings in the handoff docs. Once the plan is approved, continue autonomously through all open items and leave user review/testing until the full stack is complete.

## Stack Layout

- Stack A: privacy/correctness UX and public behavior.
- Stack B: reliability, cancellation, transactional writes, and scale gates.
- Stack C: release, SBOM, docs, CI, and operational readiness.

## T0 - Review Workflow And Tracking

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Python audit-report and metadata-report HTML writers now set owner-only permissions after writes, matching existing JSON report behavior.
- Swift metadata scrub report writes and exported report copies now apply owner-only permissions to JSON and HTML artifacts.
- Bundled app Python copies were synchronized with the source Python report writers.
- Covered by Swift report permission helper test and Python JSON/HTML/scrub report mode tests.

Scope:

- Keep this backlog as the implementation tracker.
- Use stacked branches rather than one mixed change.
- Run local best-available model review after each stack segment.
- Record review results and any waived items in `docs/`.

Acceptance criteria:

- Every ticket below is either completed, explicitly deferred with rationale, or marked blocked with evidence.
- Each completed stack has tests/gates and a documented local model review result.

## T1 - Consolidate DOCX Send Choices

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Replaced direct completed-DOCX share with two explicit choices: final redacted copy or review copy with Track Changes.
- Final copy uses a separate `Final Redacted.docx` output path, accepts redaction Track Changes through the metadata scrub pipeline, and runs maximum-privacy metadata scrubbing before share.
- Review copy requires explicit confirmation that Track Changes and metadata may preserve recoverable original information.
- Covered by Swift URL collision tests and Python metadata scrub regression for accepting Track Changes.

Scope:

- Preserve Marcut's core Track Changes proposal workflow.
- Replace ambiguous direct DOCX share behavior with exactly two send paths:
  - **Send Final Redacted Copy**: create a new copy, accept Marcut redaction Track Changes in that copy, run metadata scrub on that copy, then share/send the finalized copy.
  - **Send Review Copy**: send the DOCX with Track Changes and metadata preserved only after explicit confirmation that original text and metadata may remain recoverable.
- Do not destructively modify the user's review artifact when creating a final copy.

Acceptance criteria:

- Users cannot accidentally share a Track Changes review DOCX as if it were a finalized redaction.
- The final-copy path proves both redaction changes are accepted and metadata scrub has run.
- The review-copy path uses clear, explicit confirmation.
- Tests or UI automation cover both choices.

## T2 - Public Runtime Remote Ollama Boundary

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Replaced the legacy `MARCUT_ALLOW_REMOTE_OLLAMA` override with the explicitly unsafe source-developer-only `MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA=1` path in Python model resolution.
- Public Swift runtime paths strip both the legacy and developer-unsafe remote Ollama variables before embedded Python sync and subprocess launches.
- Security and help docs now warn that public runtime is loopback-only and that the developer-unsafe override must not be used with confidential documents.
- Covered by focused Python loopback/remote override tests and Swift package compile/test pass.

Scope:

- Decide and enforce the public-beta policy for `MARCUT_ALLOW_REMOTE_OLLAMA`.
- Preferred implementation: rename/guard remote Ollama as an explicit developer-only unsafe mode and clear/reject it in packaged public runtime.
- Align docs, tests, CLI errors, and runtime environment checks.

Acceptance criteria:

- Public app inference remains loopback-only by default and cannot be silently redirected remote.
- Any developer-only remote mode is unmistakably named, documented as unsafe, and excluded from public launch paths.
- Tests cover default loopback, custom loopback port, rejected remote host, and developer-only behavior if retained.

## T3 - Owner-Only Permissions For All Sensitive Reports

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- `--llm-detail` now wraps the production enhanced extraction path and records detail timing metadata instead of invoking a separate non-chunked Ollama extractor.
- Detail mode now preserves the normal enhanced failure semantics rather than continuing with rules-only spans after a timing-specific failure.
- Bundled app Python copies were synchronized with the source pipeline.
- Covered by Python regressions comparing detail and non-detail spans, collector parameters, emitted timing metadata, and failure reports.

Scope:

- Apply owner-only permissions to metadata-only JSON/HTML reports.
- Ensure standard audit reports, scrub reports, metadata-only reports, and failure reports use consistent sensitive-artifact handling.

Acceptance criteria:

- JSON and HTML reports are `0o600` where the platform supports POSIX permissions.
- Metadata report cache directories remain `0o700`.
- Regression tests cover metadata-only direct Swift write paths and Python-generated HTML.

## T4 - `--llm-detail` Must Not Change Redaction Output

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- `--llm-detail` now wraps the production enhanced extraction path and records detail timing metadata instead of invoking a separate non-chunked Ollama extractor.
- Detail mode now preserves the normal enhanced failure semantics rather than continuing with rules-only spans after a timing-specific failure.
- Bundled app Python copies were synchronized with the source pipeline.
- Covered by Python regressions comparing detail and non-detail spans, collector parameters, emitted timing metadata, and failure reports.

Scope:

- Make `--llm-detail` observe the production enhanced path rather than replacing it.
- Keep timing fields useful without bypassing chunking, validation, concurrency, or warnings.

Acceptance criteria:

- Same input/settings produce the same spans with and without `--llm-detail`.
- Timing data is still emitted.
- Regression tests cover normal success and timing failure cases.

## T5 - Advanced LLM Settings And GGUF Backend Consistency

Severity: Medium

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- CLI `--backend llama_cpp --llama-gguf <path> --threads <n>` is now forwarded into unified redaction and the enhanced GGUF backend.
- `llama_cpp` backend now fails clearly when no GGUF path is provided instead of silently using the default Ollama model string.
- Ollama enhanced extraction and validation now receive the configured seed and temperature rather than hard-coded seed behavior in chunk extraction.
- Bundled app Python copies were synchronized with the source Python changes.
- Covered by focused tests for CLI forwarding, GGUF backend path/thread routing, missing-GGUF validation, and Ollama seed/temperature request propagation.

Scope:

- Pass seed, temperature, thread count, and relevant backend settings end-to-end or adjust UI/docs to match actual behavior.
- Wire `--backend llama_cpp --llama-gguf` correctly, or remove the public CLI/docs for that path.

Acceptance criteria:

- Tests prove seed/temperature reach Ollama request bodies where supported.
- Tests prove GGUF path reaches the llama.cpp backend if retained.
- User-facing docs match implementation.

## T6 - Hard Cancellation And Timeout Semantics

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Swift PythonKit processing sets `MARCUT_PROCESSING_DEADLINE_MONOTONIC` for each timed processing phase and clears it after completion or before a new run.
- User stop now requests a Python interrupt immediately and expires the process-level deadline marker.
- Python Ollama extraction, LLM timing, validation, and enhanced thread-pool waits check the processing deadline and bound request timeouts to remaining processing time.
- Deadline cancellation sets an internal worker cancellation event, avoids post-cancel progress emission, uses non-blocking executor shutdown, and preserves timeout failure reporting.
- Tests cover deadline-bounded request timeouts, expired-deadline rejection, hanging extraction returning within the deadline grace window, no final DOCX write on deadline failure, and Swift package behavior.

Scope:

- Make UI Stop and processing timeout actively bound PythonKit/Ollama work.
- Add cooperative cancellation checks through Python redaction phases.
- Bound Ollama HTTP requests, validation retries, chunk futures, and executor shutdown.

Acceptance criteria:

- Hanging fake Ollama test returns cancelled/failed within the configured timeout plus a small grace window.
- Stop during extraction/validation leaves no active worker request and does not write final artifacts.
- UI messaging matches actual cancellation state.

## T7 - Transactional Artifact Writes

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Redaction finalization now writes DOCX, audit JSON/HTML, scrub JSON/HTML to same-directory hidden temp files first.
- Final artifact names are populated only after the staged DOCX and reports are written successfully.
- Temp artifacts are cleaned on failure/cancellation paths.
- Audit-report failure after DOCX staging no longer leaves a misleading final DOCX.
- Bundled app Python copies were synchronized with the source pipeline.
- Covered by transactional finalization regression plus pipeline and metadata scrub suites.

Scope:

- Write DOCX, audit report, scrub report, and related HTML to same-volume temp files.
- Validate the full artifact set, then atomically move complete outputs into final names.
- Clean temp files on failure/cancellation.

Acceptance criteria:

- Failure after DOCX save but before report save does not leave a misleading final DOCX.
- Cancellation does not mark an item completed merely because partial files exist.
- Regression tests cover report-write failure and cancellation timing.

## T8 - Model Download And Readiness Reliability

Severity: Medium

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- CLI `ollama pull` fallback now has an idle-output watchdog and terminates stalled pull processes with an actionable error.
- Download completion now waits for `/api/show` readiness after the model appears on disk.
- Processing now performs the same readiness probe before starting non-rules/non-mock work, reducing post-download `/api/show` races.
- Covered by Swift idle-timeout configuration test and Swift package compile/test pass.

Scope:

- Add deadline and idle watchdog behavior to the `ollama pull` process fallback.
- Unify model readiness checks between preflight and processing.

Acceptance criteria:

- Stalled pull process terminates with actionable UI state.
- Readiness success cannot be immediately followed by avoidable `/api/show` race failure.
- Tests or controlled fakes cover stalled process and delayed model availability.

## T9 - Metadata And Report Expansion Limits

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Metadata capture now summarizes embedded binary parts by default instead of retaining raw bytes unless explicit forensic/binary export mode is enabled.
- Explicit forensic binary capture is bounded by the same per-part and total-byte limits used by export writing, with warning records when raw payloads are skipped.
- Raw custom XML, alternate-content, fast-save XML, and unknown namespace previews are truncated before retention under `MARCUT_METADATA_CAPTURE_MAX_STRING_CHARS`.
- Report JSON serialization now applies string, list, and dictionary budgets under `MARCUT_METADATA_REPORT_MAX_STRING_CHARS`, `MARCUT_METADATA_REPORT_MAX_LIST_ITEMS`, and `MARCUT_METADATA_REPORT_MAX_DICT_ITEMS`, with warning codes for truncated values.
- Bundled app Python copies were synchronized with the source pipeline.
- Covered by report-budget tests, binary-retention default tests, existing forensic-export private-file coverage, and existing custom XML report coverage.

Scope:

- Apply size/count caps before retaining raw binary/custom XML data in memory.
- Ensure default metadata/report generation does not expand unbounded package contents.
- Keep forensic/deep export explicit, bounded, private, and warning-producing.

Acceptance criteria:

- Large DOCX fixtures keep JSON/HTML under explicit budgets by default.
- Large binary/custom XML data is summarized or skipped before raw data retention when exports are disabled.
- Tests cover warning behavior and owner-only export files when forensic mode is enabled.

## T10 - Large-DOCX Performance And Consistency-Pass Gates

Severity: Medium

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- Consistency-pass work now has explicit environment-configurable budgets for total candidates, fuzzy ORG candidates, and regex pattern text size.
- The default budgets preserve normal propagation while preventing pathological thousands-of-unique-ORG scans from constructing unbounded regex/fuzzy work.
- Added a production-path synthetic large-DOCX regression that builds body paragraphs, a table, headers/footers, comment metadata, document metadata, and many sensitive spans, then runs `pipeline.run_redaction(..., mode="rules")`.
- The large-DOCX gate records wall time through assertion, verifies phase timings, output/report sizes, scrub report creation, and a minimum redaction count.
- Bundled app Python copies were synchronized with the source pipeline.
- Covered by consistency-pass budget tests and the synthetic large-DOCX production-path performance test.

Scope:

- Add synthetic large-DOCX performance gates for body text, tables, headers/footers, comments, metadata, and many spans.
- Add microbenchmark/regression coverage for many unique ORG candidates over multi-MB text.
- Bound consistency-pass scan work if benchmarks show nonlinear behavior.

Acceptance criteria:

- Release/nightly gate records wall time, RSS where practical, output size, and redaction counts.
- Candidate/pattern limits or optimized search behavior prevent pathological ORG scans.
- Benchmarks use production `run_redaction`, not timing-only extraction.

## T11 - Release Notarization And CI Fail-Closed Gates

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- `scripts/notarize_macos.sh` now fails if Gatekeeper assessment fails after stapling, and no longer exits success for a non-terminal pending notarization result.
- `scripts/sh/build_appstore_release.sh` now fails on app code-signature verification failure instead of continuing to DMG creation.
- Missing notarytool keychain profiles now fail unless `MARCUT_ALLOW_NOTARIZATION_SKIP=1` is explicitly set for local/test builds.
- Skipped notarization and skipped notarization validation now require `MARCUT_ALLOW_NOTARIZATION_SKIP=1`.
- Build summaries now distinguish a notarized distribution-ready artifact from an intermediate/local build where notarization was explicitly skipped.
- `scripts/sh/build_devid_release.sh` uses the explicit skip override only for its internal build step, then still invokes external notarization through `scripts/notarize_macos.sh`.
- Tag CI now has an explicit fail-closed prerequisite step requiring a signing identity, Developer ID Application identity, and App Store Connect notarization secrets before a release-tag job can proceed.
- The CI build step sets `MARCUT_ALLOW_NOTARIZATION_SKIP=1` only for the intermediate DMG build because the tag workflow notarizes in a later dedicated step.
- Covered by shell syntax validation for release scripts and YAML parse validation for the tag/nightly workflow.

Scope:

- Make all public distribution paths fail closed on missing/failed notarization.
- Remove `|| true` from public Gatekeeper assessment paths.
- Ensure tag CI cannot go green for a public artifact without notarization evidence.

Acceptance criteria:

- Missing credentials fail the public release path unless an explicit local-only override is set.
- Tag workflow proves `stapler validate` and `spctl` for public DMGs.
- Release summary cannot say notarized unless notarization was actually verified.

## T12 - Shipped-Bundle SBOM And Vulnerability Coverage

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- `scripts/generate_python_sbom.py` now generates a shipped-component CycloneDX-style SBOM from the staged app `python_site` by default, or from an actual `MarcutApp.app` via `--bundle-root`.
- The SBOM now includes transitive PyPI packages found from `*.dist-info/METADATA`, SwiftPM dependencies from `Package.resolved`, and explicit manual-review components for BeeWare `Python.framework` and the embedded Ollama binary when not scanned from a concrete release bundle.
- `docs/release/python-sbom.json` was regenerated from the current staged app and covers 23 shipped components.
- `scripts/check_dependency_vulnerabilities.py` now reads the SBOM when present, scans all shipped PyPI components through OSV, and prints unsupported shipped components that still require manual release review.
- Covered by SBOM generation/check, Python syntax compilation, and a live OSV vulnerability gate run against the regenerated SBOM.

Scope:

- Expand SBOM/vulnerability gates beyond direct Python pins.
- Include transitive Python packages from the staged app, Swift dependency metadata, BeeWare Python support, and embedded Ollama binary/version.

Acceptance criteria:

- SBOM is generated from the actual release bundle/staging output.
- Vulnerability gate covers all feasible shipped third-party components.
- Known unsupported components are listed with explicit manual review status.

## T13 - Release Docs And Qualification Refresh

Severity: High

Status: Completed

Implementation notes:

- Completed in stack branch `codex/prebeta-stack-a-docx-sharing`.
- `docs/release/public_beta_qualification.md` now supersedes the stale `0.5.95` ad-hoc artifact note with current `0.5.96` source/config evidence and the exact remediation verification commands/results run in this pass.
- Qualification now states that a Developer ID notarized `0.5.96` DMG was not produced locally and remains a public-beta blocker.
- Public docs now describe the two DOCX send paths: final sanitized copy vs intentional review copy with Track Changes and metadata preserved.
- Release docs now state that public direct distribution requires notarization and that `MARCUT_ALLOW_NOTARIZATION_SKIP=1` is local/test-only.
- Release checklist now directs SBOM generation/checks to the actual built `MarcutApp.app` via `--bundle-root` and runs vulnerability checks against the generated SBOM.
- Stale `MarcutApp-Swift-v0.2.3.dmg` app-install text in `docs/README.md` was replaced with current `0.5.96` release-target wording.

Scope:

- Supersede stale `docs/release/public_beta_qualification.md` with current 0.5.96+ evidence.
- Update stale CLI/build/release docs after implementation.
- Document DOCX send semantics: final sanitized copy vs intentional review copy.

Acceptance criteria:

- Qualification doc names the current version/artifact and exact verification results.
- Public docs no longer reference stale flags, old DMG names, or inaccurate notarization behavior.
- Docs clearly state that Track Changes review artifacts are not final sanitized share copies.

## T14 - Entitlement And Governance Verification

Severity: Medium

Status: Blocked on final Developer ID beta artifact

Implementation notes:

- Added `scripts/verify_entitlements.sh` to print app/helper entitlements from a built `MarcutApp.app` and fail if forbidden debug/runtime-bypass entitlements are present.
- Added `docs/release/entitlement_governance_verification.md` with source-level entitlement evidence, repeatable final-artifact command, repository-local governance evidence, and explicit gaps.
- `build_tui.py` now runs the final entitlement, bundle-SBOM, vulnerability, stapler, and Gatekeeper evidence checks after successful Developer ID DMG builds or existing-DMG notarization.
- `build_tui.py` now passes `MARCUT_ALLOW_NOTARIZATION_SKIP=1` only for the App Store archive path where notarization is intentionally deferred to App Store submission.
- Source-level review found release entitlements in `build-scripts/Marcut.entitlements` and `build-scripts/MarcutOllama.entitlements`; no reviewed release entitlement source contains `disable-library-validation`, `allow-jit`, or `get-task-allow`.
- Repository-local governance evidence includes `CODEOWNERS`, a PR template, and CI/build/full-E2E workflows.
- GitHub ruleset `Protect main for public beta` (ID `16376458`) is active for `refs/heads/main`, requires PRs, one approval, code-owner review, conversation resolution, up-to-date `smoke` and `build-verify` status checks, and blocks deletion/non-fast-forward pushes with no bypass actors.
- Final acceptance remains blocked until the Developer ID beta app/helper are built and final artifact evidence is captured.

Scope:

- Verify final built app/helper entitlements from the actual beta artifact.
- Record branch protection/ruleset/review evidence or explicit gaps.

Acceptance criteria:

- `codesign -d --entitlements :-` output for final app/helper is reviewed and summarized in docs.
- Broad/stale entitlement files are confirmed unused or removed in a code cleanup ticket.
- Branch/review controls are documented before public beta.
