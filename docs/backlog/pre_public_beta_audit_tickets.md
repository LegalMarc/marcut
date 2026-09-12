# Pre-Public-Beta Audit Tickets

This backlog tracks the approved remediation scope for public beta. Marcut is treated as a local-first redaction app for confidential legal documents and PII. HIPAA/PHI-specific work is explicitly out of scope.

## T0 - Backlog And Review Workflow

Severity: High
Status: Completed with review-tool caveat

Acceptance criteria:
- This file exists before implementation work begins.
- Each remediation branch is stacked from the previous branch.
- Local review is run after each stack segment. If no automated Opus workflow exists locally, use an available local/manual review pass and record gaps in the final handoff.

Tests/review:
- Confirm `git status --short --branch` shows the intended stacked branch.
- Confirm all implementation tickets below have test coverage or an explicit rationale.
- Opus was not available locally. Existing subagent threads were at capacity and returned no usable redirected diff-review text, so the implementation used manual local diff review plus full Python/Swift verification.

## T1 - Loopback-Only Inference

Severity: High
Status: Completed

Acceptance criteria:
- Python inference uses loopback Ollama hosts by default.
- Remote Ollama hosts require an explicit unsafe override.
- Tests cover default loopback behavior, custom loopback ports, and rejected remote hosts.

Tests/review:
- `python3 -m pytest tests/test_model.py tests/test_failure_scenarios.py tests/test_security.py -q`

## T2 - Generated Python Source Boundary

Severity: High
Status: Completed

Acceptance criteria:
- Swift subprocess/Python execution paths do not interpolate unescaped model or mode values into generated Python source.
- Malicious quote-bearing model/mode values are represented as data, not executable source.

Tests/review:
- Added regression coverage for malicious model/mode validation and verified Swift no longer interpolates model/mode as executable Python source.
- `swift test --package-path src/swift/MarcutApp`

## T3 - Review Artifact Language

Severity: Medium
Status: Completed

Acceptance criteria:
- Product/help/report language clearly says the default DOCX is a Track Changes review artifact.
- No separate sanitized/final output is added.
- Existing Track Changes behavior is preserved.

Tests/review:
- Documentation link/check review.
- Existing DOCX revision tests continue to pass.

## T4 - Report Handling Hardening

Severity: High
Status: Completed

Acceptance criteria:
- Raw report text remains enabled by default.
- Share/print/export surfaces warn that reports may contain original detected text and document metadata.
- App-managed report/cache files use restrictive permissions where practical.
- Metadata report cache cleanup covers the actual report-only cache path.

Tests/review:
- Add tests for report file permissions and cache cleanup path behavior where feasible.
- `python3 -m pytest tests/test_report_common.py tests/test_metadata_scrubbing.py -q`

## T5 - Log And Launch-Argument Redaction

Severity: Medium
Status: Completed

Acceptance criteria:
- Raw LLM responses and document-derived strings are not logged by default.
- Debug/failure paths redact path-valued launch arguments and report/output paths.
- Existing diagnostic usefulness is preserved without exposing sensitive document names or content.

Tests/review:
- Add Python tests for redacted LLM parse failures and failure reports.
- Add Swift/static tests for launch-argument redaction if feasible.

## T6 - Cancellation And Timeout Reliability

Severity: High
Status: Completed

Acceptance criteria:
- LLM requests use bounded, cooperative timeouts instead of one 120-minute non-streaming request.
- Processing and download cancellation paths actively stop the current request/task/process.
- User-visible cancel/timeout behavior matches implementation.

Tests/review:
- Add unit tests around Python timeout settings and Swift cancellation state where feasible.
- Manual review for model download cancellation if UI/runtime testing is not practical in CI.

## T7 - Report Expansion Limits

Severity: High
Status: Completed

Acceptance criteria:
- Normal report generation does not unboundedly export all DOCX parts or inline large images.
- Deep/forensic exploration is explicit and bounded by size/count limits.
- Large report artifacts produce warnings instead of unbounded disk/memory expansion.

Tests/review:
- Add tests for default no deep export and size/count limit behavior.

## T8 - Release And CI Gates

Severity: High
Status: Completed

Acceptance criteria:
- CI no longer calls missing packaging scripts.
- CI runs Swift tests.
- Dependency audit/SBOM or equivalent release gate is available.
- Notarization skip behavior cannot produce a green release/tag result without an explicit local-only override.
- Markdown/public links are checked or corrected.

Tests/review:
- `python3 -m pytest -q`
- `swift test --package-path src/swift/MarcutApp`
- Run the release-gate scripts in dry-run/read-only modes where available.

## T9 - Metadata/Report Expansion Limits

Severity: High
Status: Completed

Acceptance criteria:
- Large DOCX fixtures keep JSON/HTML under explicit budgets by default.
- Large binary/custom XML data is summarized or skipped before raw data retention when exports are disabled.
- Tests cover warning behavior and owner-only export files when forensic mode is enabled.

Tests/review:
- Metadata capture now summarizes embedded binary parts by default instead of retaining raw bytes unless explicit forensic/binary export mode is enabled; explicit forensic capture stays bounded by the same per-part/total-byte limits used by export writing, with warnings when raw payloads are skipped.
- Raw custom XML, alternate-content, fast-save XML, and unknown namespace previews are truncated under `MARCUT_METADATA_CAPTURE_MAX_STRING_CHARS`.
- Report JSON serialization applies string/list/dict budgets under `MARCUT_METADATA_REPORT_MAX_STRING_CHARS`, `MARCUT_METADATA_REPORT_MAX_LIST_ITEMS`, and `MARCUT_METADATA_REPORT_MAX_DICT_ITEMS`, with warning codes for truncated values.
- Covered by report-budget tests, binary-retention default tests, existing forensic-export private-file coverage, and existing custom XML report coverage.

## T10 - Large-DOCX Performance And Consistency-Pass Gates

Severity: Medium
Status: Completed

Acceptance criteria:
- Release/nightly gate records wall time, RSS where practical, output size, and redaction counts.
- Candidate/pattern limits or optimized search behavior prevent pathological ORG scans.
- Benchmarks use production `run_redaction`, not timing-only extraction.

Tests/review:
- Consistency-pass work has explicit environment-configurable budgets for total candidates, fuzzy ORG candidates, and regex pattern text size, preserving normal propagation while preventing pathological thousands-of-unique-ORG scans from constructing unbounded regex/fuzzy work.
- Added a production-path synthetic large-DOCX regression building body paragraphs, a table, headers/footers, comment metadata, document metadata, and many sensitive spans, then running `pipeline.run_redaction(..., mode="rules")`, asserting wall time, phase timings, output/report sizes, scrub report creation, and a minimum redaction count.
- Covered by consistency-pass budget tests and the synthetic large-DOCX production-path performance test.

## T11 - Release Notarization And CI Fail-Closed Gates

Severity: High
Status: Completed

Acceptance criteria:
- Missing credentials fail the public release path unless an explicit local-only override is set.
- Tag workflow proves `stapler validate` and `spctl` for public DMGs.
- Release summary cannot say notarized unless notarization was actually verified.

Tests/review:
- `scripts/notarize_macos.sh` now fails if Gatekeeper assessment fails after stapling, and no longer exits success for a non-terminal pending notarization result.
- `scripts/sh/build_appstore_release.sh` fails on app code-signature verification failure instead of continuing to DMG creation.
- Missing notarytool keychain profiles, and any skipped notarization/skipped notarization validation, now require `MARCUT_ALLOW_NOTARIZATION_SKIP=1` explicitly set for local/test builds.
- Tag CI has an explicit fail-closed prerequisite step requiring a signing identity, Developer ID Application identity, and App Store Connect notarization secrets before a release-tag job can proceed.
- Covered by shell syntax validation for release scripts and YAML parse validation for the tag/nightly workflow.

## T12 - Shipped-Bundle SBOM And Vulnerability Coverage

Severity: High
Status: Completed

Acceptance criteria:
- SBOM is generated from the actual release bundle/staging output.
- Vulnerability gate covers all feasible shipped third-party components.
- Known unsupported components are listed with explicit manual review status.

Tests/review:
- `scripts/generate_python_sbom.py` generates a shipped-component CycloneDX-style SBOM from the staged app `python_site` by default, or from an actual `MarcutApp.app` via `--bundle-root`, including transitive PyPI packages from `*.dist-info/METADATA`, SwiftPM dependencies from `Package.resolved`, and explicit manual-review components for BeeWare `Python.framework` and the embedded Ollama binary.
- `docs/release/python-sbom.json` regenerated from the current staged app, covering 23 shipped components.
- `scripts/check_dependency_vulnerabilities.py` reads the SBOM when present, scans all shipped PyPI components through OSV, and prints unsupported shipped components that still require manual review.
- Covered by SBOM generation/check, Python syntax compilation, and a live OSV vulnerability gate run against the regenerated SBOM.

## T13 - Release Docs And Qualification Refresh

Severity: High
Status: Completed

Acceptance criteria:
- Qualification doc names the current version/artifact and exact verification results.
- Public docs no longer reference stale flags, old DMG names, or inaccurate notarization behavior.
- Docs clearly state that Track Changes review artifacts are not final sanitized share copies.

Tests/review:
- `docs/release/public_beta_qualification.md` supersedes the stale `0.5.95` ad-hoc artifact note with current `0.5.96` source/config evidence and the exact remediation verification commands/results.
- Public docs describe the two DOCX send paths: final sanitized copy vs intentional review copy with Track Changes and metadata preserved.
- Release docs state that public direct distribution requires notarization and that `MARCUT_ALLOW_NOTARIZATION_SKIP=1` is local/test-only.
- Release checklist directs SBOM generation/checks to the actual built `MarcutApp.app` via `--bundle-root` and runs vulnerability checks against the generated SBOM.
- Stale `MarcutApp-Swift-v0.2.3.dmg` app-install text in `docs/README.md` replaced with current release-target wording.

## T14 - Entitlement And Governance Verification

Severity: Medium
Status: Completed

Acceptance criteria:
- `codesign -d --entitlements :-` output for final app/helper is reviewed and summarized in docs.
- Broad/stale entitlement files are confirmed unused or removed in a code cleanup ticket.
- Branch/review controls are documented before public beta.

Tests/review:
- `scripts/verify_entitlements.sh` prints app/helper entitlements from a built `MarcutApp.app` and fails if forbidden debug/runtime-bypass entitlements are present.
- `docs/release/entitlement_governance_verification.md` records source-level entitlement evidence, repository-local governance evidence (CODEOWNERS, PR template, CI/build/full-E2E workflows), and GitHub ruleset evidence (`Protect main for public beta`, ID `16376458`, active on `refs/heads/main`).
- Final Artifact Verification (2026-07-03): `bash scripts/sh/build_devid_release.sh` was run end-to-end against a freshly-provisioned BeeWare `Python.framework`, producing `MarcutApp-v0.5.96-AppStore.dmg`, signed with a Developer ID Application identity, and notarized via `scripts/notarize_macos.sh` (Apple notary submission accepted). `xcrun stapler validate` and `spctl -a -t open --context context:primary-signature -v` both confirm a notarized, Gatekeeper-accepted artifact; `scripts/verify_entitlements.sh` reports `ENTITLEMENTS: OK`; the SBOM regenerated directly from the built bundle covers 23 shipped components with vulnerability checks passing for 20 shipped PyPI packages (Ollama flagged for expected manual review). No public-beta blockers remain from this ticket; see `docs/release/entitlement_governance_verification.md` for full evidence.
