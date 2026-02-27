# Release Checklist

This checklist ensures a consistent, high-quality release process for Marcut.

## 1. Pre-Release Checks
- [ ] **Clean Build**: Run `./build_tui.py` and choose **Build Workflows → Full Release Build (Clean & Archive)**.
- [ ] **Tests Pass**: Verify all unit tests pass (`python3 run_tests.py`).
- [ ] **Integrity Guards**: Confirm build logs include:
    - [ ] `python_site source verified against repo`
    - [ ] `python_site marcut package verified`
    - [ ] No `Nested runtime remains inside resource bundle` errors
- [ ] **Quick Look**: Launch the built app (`build_swift/MarcutApp.app`).
    - [ ] App opens without crashing.
    - [ ] "About" window shows correct version.
    - [ ] Python environment loads (check logs for `PK_INIT_COMPLETE`).
- [ ] **Functionality**:
    - [ ] Run a Rules-Only redaction.
    - [ ] Run an Enhanced (Ollama) redaction.
    - [ ] Verify `excluded-words.txt` overrides work.

## 2. Security & Compliance
- [ ] **Entitlements**: Verify `MarcutApp.entitlements` has NO `disable-library-validation` or JIT keys.
- [ ] **Signing**: Verify recursive signing.
    ```bash
    codesign -dv --verbose=4 build_swift/MarcutApp.app
    ```
- [ ] **Secrets Check**: Ensure `config.json` is NOT present/tracked (use `config.example.json`).

## 3. Packaging
- [ ] **Version Sync**: Keep `build-scripts/config.json` `version` and `build_number` identical for release builds.
- [ ] **Optional Auto-Bump**: Use `scripts/sh/build_appstore_release.sh --auto-bump` only when you explicitly want the next release number generated.
- [ ] **DMG Creation**: Ensure DMG is generated and signed.
- [ ] **Notarization**: (Optional for local/test, Mandatory for Release) Run notarization script.

## 4. Release Assets
- [ ] **Tag**: Create git tag (e.g., `v0.5.32`).
- [ ] **Draft Release**: On GitHub.
- [ ] **Upload**:
    - `.dmg` installer.
    - `checksums.txt` (SHA256 of the DMG).
- [ ] **Changelog**: Update `CHANGELOG.md` with features and fixes.

## 5. Post-Release
- [ ] **Verify Download**: Download the released DMG on a fresh machine (or VM).
- [ ] **Launch**: Ensure Gatekeeper passes (if notarized) or run `xattr -cr` (if ad-hoc).
