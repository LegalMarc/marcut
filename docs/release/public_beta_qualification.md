# Public Beta Qualification

Date: 2026-05-13
Branch: `codex/prebeta-stack-a-docx-sharing`
Source version: `0.5.96`
Configured public DMG target: `.marcut_artifacts/ignored-resources/MarcutApp-v0.5.96-AppStore.dmg`

## Scope

This qualification refresh supersedes the 2026-05-12 `0.5.95` ad-hoc artifact note. It covers the current pre-public-beta remediation stack for confidential legal documents and PII, including DOCX send semantics, remote-Ollama defaults, report privacy, cancellation/deadline behavior, transactional artifacts, large-DOCX gates, notarization fail-closed behavior, and shipped-component SBOM coverage.

## Current Artifact Status

- Source/config version: `0.5.96`
- Public DMG target from `build-scripts/config.json`: `.marcut_artifacts/ignored-resources/MarcutApp-v0.5.96-AppStore.dmg`
- Developer ID notarized DMG: not produced in this local pass
- External public-beta distribution status: blocked until a Developer ID signed DMG is built, notarized, stapled, and Gatekeeper-verified

## Verification Results

Passed in this remediation pass:

- `PYTHONPATH=src/python python3 -m pytest tests/test_cli.py tests/test_model.py tests/test_model_enhanced.py tests/test_pipeline.py tests/test_metadata_scrubbing.py tests/test_unified_redactor.py tests/test_large_docx_performance.py -q`
  - Result: `198 passed`
- `swift test --package-path src/swift/MarcutApp`
  - Result: `24 tests, 0 failures`
- `python3 scripts/check_markdown_links.py`
  - Result: `21 files`
- `PYTHONPATH=src/python python3 -m pytest tests/test_metadata_scrubbing.py::TestScrubReportPrePostValues tests/test_metadata_scrubbing.py::TestMetadataScrubReport::test_custom_xml_report_details tests/test_metadata_scrubbing.py::TestMetadataScrubReport::test_redaction_writes_scrub_report tests/test_pipeline.py::TestTransactionalArtifacts::test_finalize_cleans_docx_when_audit_report_fails -q`
  - Result: `9 passed`
- `PYTHONPATH=src/python python3 -m pytest tests/test_pipeline.py::TestApplyConsistencyPass::test_candidate_limit_bounds_consistency_work tests/test_large_docx_performance.py -q`
  - Result: `2 passed`
- `bash -n scripts/notarize_macos.sh scripts/sh/build_appstore_release.sh scripts/sh/build_devid_release.sh`
  - Result: passed
- Workflow YAML parse for `.github/workflows/macos-full-e2e.yml`, `.github/workflows/ci.yml`, and `.github/workflows/macos-build-verify.yml`
  - Result: passed
- `python3 scripts/generate_python_sbom.py --output docs/release/python-sbom.json`
  - Result: regenerated SBOM
- `python3 scripts/generate_python_sbom.py --check`
  - Result: `covers 23 shipped components`
- `python3 scripts/check_dependency_vulnerabilities.py --sbom docs/release/python-sbom.json`
  - Result: passed for `20` shipped PyPI packages; manual review still required for BeeWare `Python.framework` and embedded Ollama
- `python3 -m py_compile scripts/generate_python_sbom.py scripts/check_dependency_vulnerabilities.py`
  - Result: passed
- `python3 -m py_compile build_tui.py`
  - Result: passed

Full final distribution verification still requires the signed/notarized DMG artifact.

## DOCX Send Semantics

Marcut intentionally creates Track Changes proposals so the user can inspect and accept or reject reductions. The completed DOCX in the work queue is a review artifact until finalized.

The app now exposes two logical send paths:

- **Send Final Redacted Copy**: creates a separate final copy, accepts Marcut redaction Track Changes in that copy, runs maximum-privacy metadata scrubbing, and shares the finalized copy.
- **Send Review Copy**: shares the DOCX with Track Changes and metadata preserved only after explicit confirmation that original text and metadata may remain recoverable.

This preserves the mission-critical proposal workflow while reducing accidental sharing of review artifacts as if they were final sanitized documents.

## Dependency Qualification

The current SBOM is generated from staged shipped components instead of direct requirements only:

- Transitive PyPI packages from staged `python_site` `*.dist-info/METADATA`
- SwiftPM dependencies from `src/swift/MarcutApp/Package.resolved`
- Manual-review components for BeeWare `Python.framework` and embedded Ollama when a concrete release bundle is not scanned

The OSV gate passed for all shipped PyPI components in the regenerated SBOM. SwiftPM Git revisions, BeeWare Python, and embedded Ollama remain explicit manual-review items until a release-bundle scan and/or ecosystem-specific scanner covers them.

## Signing And Notarization

Public external distribution is fail-closed:

- `scripts/notarize_macos.sh` fails without credentials unless `MARCUT_ALLOW_NOTARIZATION_SKIP=1` is explicitly set for local/test use.
- `scripts/notarize_macos.sh` now fails if stapled Gatekeeper assessment fails.
- `scripts/sh/build_appstore_release.sh` fails on app code-signature verification failure.
- Missing notarytool keychain profiles fail unless the local/test skip override is set.
- Tag CI requires signing identity, Developer ID Application identity, and App Store Connect notarization secrets before proceeding.
- `build_tui.py` now runs final entitlement, bundle-SBOM, vulnerability, stapler, and Gatekeeper evidence checks after successful Developer ID DMG builds or existing-DMG notarization.

The configured `0.5.96` public DMG must still be built with a real Developer ID identity, notarized, stapled, and Gatekeeper-verified before public beta distribution.

## Remaining Release Blockers

- Run final full Python, Swift, markdown, SBOM, and release-script verification after all open remediation tickets are closed.
- Produce the Developer ID signed `0.5.96` DMG from the final stack.
- Notarize with real credentials, staple the accepted ticket, and run Gatekeeper assessment on the notarized DMG.
- Review unsupported SBOM components for the exact release bundle: BeeWare `Python.framework` and embedded Ollama.

## Acceptable Based On This Pass

- DOCX send/share semantics now distinguish final sanitized copies from intentional review copies.
- Remote Ollama is disabled by default unless the explicit developer-unsafe override is set.
- Metadata/report outputs are owner-only and now have bounded report/capture paths.
- Python processing cancellation/deadline behavior is bounded through Ollama requests and enhanced-thread waits.
- Final DOCX names are populated only after staged reports are written.
- Large-DOCX and consistency-pass performance gates are present.
- SBOM and vulnerability checks cover the staged shipped Python dependency graph.
