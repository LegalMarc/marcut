# Entitlement And Governance Verification

Date: 2026-05-14
Branch: `codex/prebeta-stack-a-docx-sharing`
Status: source-level review and GitHub governance setup complete; final artifact verification blocked until the Developer ID beta DMG exists

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

- Capture or retain `scripts/verify_entitlements.sh` output from the final Developer ID signed app and helper.
