# Release Checklist

This checklist ensures a consistent, high-quality release process for Marcut.

## 1. Pre-Release Checks
- [ ] **Clean Build**: Run `./build_swift_only.sh preset full_release` to ensure a clean slate.
- [ ] **Tests Pass**: Verify all unit tests pass (`python3 run_tests.py`).
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
- [ ] **Version Bump**: Update version in `config.json` and `src/python/marcut/version.py`.
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
