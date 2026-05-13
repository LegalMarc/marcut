# Public Beta Qualification

Date: 2026-05-12
Branch: `codex/beta-audit-03-release-qualification`

## Scope

This qualification pass covers the non-HIPAA public-beta remediation stack for confidential legal documents and PII. It verifies clean release rebuild behavior, pinned dependency staging, CI/release gates, bundle verification, signing inspection, notarization fail-closed behavior, and local review.

## Build Artifact

- DMG: `.marcut_artifacts/ignored-resources/MarcutApp-Swift-0.5.95.dmg`
- Bundle: `.marcut_artifacts/ignored-resources/builds/build_swift/MarcutApp.app`
- Version observed by bundle verifier: `0.5.95`
- Signing: ad-hoc local signature

## Verification Results

Passed:

- `bash scripts/sh/build_swift_only.sh preset full_release`
- `bash scripts/verify_bundle.sh .marcut_artifacts/ignored-resources/MarcutApp-Swift-0.5.95.dmg`
  - Result: `11 checks passed, 0 failed`
- `hdiutil verify .marcut_artifacts/ignored-resources/MarcutApp-Swift-0.5.95.dmg`
  - Result: checksum valid
- `codesign --verify --deep --strict --verbose=2 .marcut_artifacts/ignored-resources/builds/build_swift/MarcutApp.app`
  - Result: valid on disk and satisfies designated requirement
- `python3 -m pytest -q`
  - Result: `400 passed, 6 skipped`
- `swift test --package-path src/swift/MarcutApp`
  - Result: `20 tests, 0 failures`
- `python3 scripts/generate_python_sbom.py --check`
- `python3 scripts/check_dependency_vulnerabilities.py requirements-pinned.txt`
  - Result: 9 pinned packages passed OSV gate
- `python3 scripts/check_markdown_links.py`
  - Result: 17 markdown files checked
- Workflow YAML parse and `bash -n` checks for all workflow `run` blocks

## Dependency Qualification

Clean release rebuild initially failed on `rapidfuzz==3.10.0` because the sdist no longer prepared metadata under current isolated build tooling. The pin was updated to `rapidfuzz==3.14.5`, which builds from source successfully in the BeeWare staging path and passes the OSV gate.

Embedded package versions observed from the built app:

- `python-docx==1.1.2`
- `rapidfuzz==3.14.5`
- `pydantic==2.10.3`
- `requests==2.33.0`
- `dateparser==1.2.0`
- `tqdm==4.67.1`
- `lxml==6.1.0`
- `numpy==2.2.0`
- `regex==2024.11.6`

## Signing And Entitlements

Observed app entitlements:

- `com.apple.security.app-sandbox`
- `com.apple.security.files.user-selected.read-write`
- `com.apple.security.files.bookmarks.app-scope`
- `com.apple.security.network.client`
- `com.apple.security.network.server`

No Developer ID signature was available in this local build. Gatekeeper assessment of the local DMG was therefore rejected with `source=no usable signature`, which is expected for the ad-hoc artifact and remains a release-blocking step before external beta distribution.

## Notarization Path

Verified:

- Missing credentials fail closed with exit code `1`.
- Explicit local/test skip works only with `MARCUT_ALLOW_NOTARIZATION_SKIP=1` and exits `0`.

The script was fixed to avoid `set -u` unbound-variable failures when credential variables are unset.

## Local Review

Local review was performed by reading the current stack diff and rerunning static gates, unit tests, bundle verification, signing inspection, and notarization-path checks. No additional code findings remain from this local review pass.

Opus review was explicitly waived for this pass.

## Remaining Release Blockers

- Produce a Developer ID signed DMG from the qualified stack.
- Run notarization with real credentials and staple the accepted ticket.
- Re-run Gatekeeper assessment on the notarized DMG.

## Serious Non-Blocking Risks

- The local qualification artifact is ad-hoc signed and should not be distributed externally.
- The current report behavior intentionally preserves raw detected text by default. This is documented and warning-gated, but reports must be treated as sensitive artifacts.

## Acceptable Based On This Pass

- Clean rebuild from pinned dependencies.
- Python and Swift test suites.
- Bundle structure and embedded Python execution.
- Mock redaction from mounted DMG.
- Dependency audit and SBOM gate.
- Markdown link gate.
- Workflow syntax and shell run-block syntax.
