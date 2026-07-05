# Marcut

Local-first DOCX redaction that produces Microsoft Word documents with track changes. Uses a mandatory hybrid approach (rules + LLM) plus an optional enhanced two-pass LLM validation for high precision.

**Status**: Public-beta hardening (T0-T14, see `docs/backlog/pre_public_beta_audit_remediation_2026-05-13.md`) is complete for version `0.5.97`. A Developer ID signed, notarized, stapled, Gatekeeper-verified DMG has been produced and verified (`docs/release/entitlement_governance_verification.md`); remaining pre-release steps are the manual RELEASE_CHECKLIST.md walkthrough (Quick Look launch, functionality spot-check, tagging).

Important: LLM detection is REQUIRED for legal documents. Rules alone miss names and organizations.

## What's included
- Track-changes DOCX output and JSON audit reports
- Rule-based detection for structured PII (emails, phones, dates, money, credit cards with Luhn, URLs, IP)
- Enhanced two-pass LLM pipeline for names/organizations with selective validation
- Simple CLI and sample scripts
- Native macOS SwiftUI app with embedded Ollama. The current configured release target is `MarcutApp-v0.5.97-AppStore.dmg`.

## Quick start

### macOS App (Recommended)

For a notarized release, download and open the current `MarcutApp-v<version>-AppStore.dmg`, then drag the app to Applications. The app includes embedded Ollama and manages local processing automatically.

### Command Line

1) Create a virtual env and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

2) Install and run Ollama, and pull a model
- Recommended model: qwen2.5:14b

```bash
# macOS
# Install from https://ollama.ai or `brew install ollama`
ollama serve &
ollama pull qwen2.5:14b
```

3) Run redaction (enhanced pipeline)

```bash
marcut redact \
  --in sample-files/Sample 123 Consent.docx \
  --out runs/out.docx \
  --report runs/out.json \
  --backend ollama \
  --model qwen2.5:14b \
  --enhanced \
  --debug
```

If the CLI preflight complains Ollama isn’t installed but your server is running, run programmatically:

```python
from marcut.pipeline import run_redaction_enhanced
run_redaction_enhanced(
    input_path='sample-files/Sample 123 Consent.docx',
    output_path='runs/out.docx',
    report_path='runs/out.json',
    model_id='qwen2.5:14b',
    chunk_tokens=1000, overlap=150, temperature=0.1, seed=42, debug=True
)
```

## Repository structure
- src/python/marcut/cli.py – CLI entry
- src/python/marcut/pipeline.py – classic and enhanced pipelines (DOCX + report)
- src/python/marcut/model_enhanced.py – enhanced two-pass LLM extractor/validator
- src/python/marcut/model.py – classic LLM integration
- src/python/marcut/rules.py – structured PII
- src/python/marcut/docx_io.py – track changes writer
- docs/USER_GUIDE.md – operator instructions
- docs/DEVELOPER_GUIDE.md – architecture and extension notes

## Next steps

Batch processing and configurable thresholds (confidence, temperature, chunk size/overlap) already ship in both the CLI and the app. See `docs/BACKLOG.md` for what's actually still open, including design-spike docs under `docs/design/` for the larger architectural ideas (streaming progress, view-controller decomposition, a stricter Swift/Python bridge schema, and others) that need a design decision before implementation.

## Notarization & distribution (DMG you can share)
- Run `bash scripts/release_preflight.sh` first -- it gates tests, SBOM, dependency audit, markdown links, version-sync, and the secrets check in one command; see `docs/RELEASE_CHECKLIST.md`.
- Use the Full Release workflow: `python3 build_tui.py` → Build Workflows → **Full Release Build (Clean & Archive)**.
- Prereqs: Developer ID Application certificate installed; notarization credentials saved to `~/.config/marcut/notarize.env` (either App Store Connect API key: `ASC_API_KEY_ID/ISSUER/BASE64` or Apple ID + app-specific password).
- The build signs the DMG, submits for notarization, staples the ticket, and then the bundle audit runs Gatekeeper on the notarized DMG.
- Verify locally before sharing: `xcrun stapler validate MarcutApp-v<ver>-AppStore.dmg` and `spctl -a -t open --context context:primary-signature -v MarcutApp-v<ver>-AppStore.dmg` should both report accepted/notarized Developer ID status. Public distribution must not use `MARCUT_ALLOW_NOTARIZATION_SKIP=1`; that override is for local/test builds only.

See docs/USER_GUIDE.md and docs/DEVELOPER_GUIDE.md for details.
