# Entitlement And Governance Verification

Date: 2026-07-03
Branch: `codex/prebeta-stack-a-docx-sharing`
Status: source-level review, GitHub governance setup, and final Developer ID artifact verification all complete

## Entitlement Sources Reviewed

Release signing uses:

- Main app entitlements: `build-scripts/Marcut.entitlements`
- Ollama helper entitlements: `build-scripts/MarcutOllama.entitlements`
- Build script references: `scripts/sh/build_appstore_release.sh`

Main app source entitlements currently contain:

- `com.apple.security.app-sandbox`
- `com.apple.security.files.user-selected.read-write`
- `com.apple.security.files.bookmarks.app-scope`
- `com.apple.security.network.client`
- `com.apple.security.network.server`

Ollama helper release entitlements currently contain:

- `com.apple.security.app-sandbox`
- `com.apple.security.inherit`

The broader development helper file `src/swift/MarcutApp/OllamaHelperService.entitlements` also includes network and user-selected file entitlements, but the release build script signs the helper with `build-scripts/MarcutOllama.entitlements`. This should be rechecked against the final built helper with `codesign -d --entitlements :-`.

No reviewed release entitlement source contains:

- `com.apple.security.cs.disable-library-validation`
- `com.apple.security.cs.allow-jit`
- `com.apple.security.get-task-allow`

## Repeatable Final Artifact Check

Run after the final `MarcutApp.app` exists:

```bash
bash scripts/verify_entitlements.sh /path/to/MarcutApp.app
```

The script prints the app and helper entitlements and fails if forbidden debug/runtime-bypass entitlements are present.

`python3 build_tui.py` also runs this automatically after:

- `Distribution & Notarization` -> `Build Developer ID DMG`
- `Distribution & Notarization` -> `Notarize Existing DMG`

## Final Artifact Verification (2026-07-03)

Ran `bash scripts/sh/build_devid_release.sh` end-to-end against a freshly-provisioned BeeWare `Python.framework` (`bash build-scripts/setup_beeware_framework.sh`), producing `MarcutApp-v0.5.96-AppStore.dmg` (194 MB), signed with `Developer ID Application: Marc Mandel (QG85EMCQ75)`, then notarized via `scripts/notarize_macos.sh` using credentials stored in `~/.config/marcut/notarize.env` (owner-only, `chmod 600`; not committed).

- Apple notary service: submission `5a2c8f87-038d-4ada-866d-5bf17d01b4dd`, status `Accepted`.
- `xcrun stapler validate`: "The validate action worked!"
- `spctl -a -t open --context context:primary-signature -v`: `accepted`, `source=Notarized Developer ID`.
- `bash scripts/verify_entitlements.sh` against the built `MarcutApp.app`: `ENTITLEMENTS: OK` -- no forbidden debug/runtime-bypass entitlements present, matching the source-level review below.
- App entitlements (`codesign -d --entitlements :-`):
  ```
  com.apple.security.app-sandbox
  com.apple.security.files.bookmarks.app-scope
  com.apple.security.files.user-selected.read-write
  com.apple.security.network.client
  com.apple.security.network.server
  ```
- Ollama helper entitlements: `com.apple.security.app-sandbox`, `com.apple.security.inherit` -- matches the source-level review.
- SBOM regenerated directly from the built bundle (`--bundle-root`): 23 shipped components; `check_dependency_vulnerabilities.py --sbom` passed for 20 shipped PyPI packages, with `Ollama` flagged for the expected manual review (binary version not scannable via PyPI/OSV).
- DMG SHA256: `727af809372cee425529aeb82dd92095244d9b88d2089d803e8801c119dcd856`

## Governance Evidence

Repository-local evidence:

- Pull request template exists at `.github/PULL_REQUEST_TEMPLATE.md`.
- CI workflow exists at `.github/workflows/ci.yml`.
- macOS build verification workflow exists at `.github/workflows/macos-build-verify.yml`.
- tag/nightly full E2E workflow exists at `.github/workflows/macos-full-e2e.yml` and now fails release tags when signing/notarization inputs are missing.
- `CODEOWNERS` exists at `.github/CODEOWNERS` and assigns public-beta critical paths to `@LegalMarc`.

GitHub ruleset evidence:

- Ruleset ID: `16376458`
- Name: `Protect main for public beta`
- Target: branch `refs/heads/main`
- Enforcement: `active`
- Bypass actors: none
- Blocks branch deletion and non-fast-forward pushes.
- Requires a pull request before merge.
- Requires one approving review.
- Requires code-owner review.
- Dismisses stale reviews on push.
- Requires review-thread/conversation resolution.
- Requires status checks `smoke` and `build-verify`.
- Requires branches to be up to date before merge.

## Public-Beta Blockers

None remaining from this ticket. The final Developer ID signed, notarized, stapled, Gatekeeper-verified `0.5.96` DMG now exists with `verify_entitlements.sh` output captured above. The DMG itself is a local build artifact (`.marcut_artifacts/ignored-resources/`, gitignored) and is not part of this repository; it must be re-produced (or retained separately) for actual distribution.
