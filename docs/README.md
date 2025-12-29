# Marcut

Local-first DOCX redaction that produces Microsoft Word documents with track changes. Uses a mandatory hybrid approach (rules + LLM) plus an optional enhanced two-pass LLM validation for high precision.

**Status**: ✅ Fully operational (September 2024) - Swift GUI and Python CLI working

Important: LLM detection is REQUIRED for legal documents. Rules alone miss names and organizations.

## What's included
- Track-changes DOCX output and JSON audit reports
- Rule-based detection for structured PII (emails, phones, dates, money, credit cards with Luhn, URLs, IP)
- Enhanced two-pass LLM pipeline for names/organizations with selective validation
- Simple CLI and sample scripts
- Native macOS SwiftUI app with embedded Ollama (MarcutApp-Swift-v0.2.3.dmg)

## Quick start

### macOS App (Recommended)

Download and open `MarcutApp-Swift-v0.2.3.dmg`, drag to Applications. The app includes embedded Ollama and manages everything automatically.

### Command Line

1) Create a virtual env and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

2) Install and run Ollama, and pull a model
- Recommended model: llama3.1:8b

```bash
# macOS
# Install from https://ollama.ai or `brew install ollama`
ollama serve &
ollama pull llama3.1:8b
```

3) Run redaction (enhanced pipeline)

```bash
marcut redact \
  --in sample-files/Shareholder-Consent.docx \
  --out runs/out.docx \
  --report runs/out.json \
  --backend ollama \
  --model llama3.1:8b \
  --enhanced \
  --debug
```

If the CLI preflight complains Ollama isn’t installed but your server is running, run programmatically:

```python
from marcut.pipeline import run_redaction_enhanced
run_redaction_enhanced(
    input_path='sample-files/Shareholder-Consent.docx',
    output_path='runs/out.docx',
    report_path='runs/out.json',
    model_id='llama3.1:8b',
    chunk_tokens=1000, overlap=150, temperature=0.1, seed=42, debug=True
)
```

## Repository structure
- marcut/cli.py – CLI entry
- marcut/pipeline.py – classic and enhanced pipelines (DOCX + report)
- marcut/model_enhanced.py – enhanced two-pass LLM extractor/validator
- marcut/model.py – classic LLM integration
- marcut/rules.py – structured PII
- marcut/docx_io.py – track changes writer
- docs/USER_GUIDE.md – operator instructions
- docs/DEVELOPER_GUIDE.md – architecture and extension notes

## Next steps
- Partial redaction support (subspans when validation returns PARTIAL_REDACT)
- Batch runner using the enhanced pipeline
- Configurable thresholds

## Notarization & distribution (DMG you can share)
- Use the Full Release workflow: `python3 build_tui.py` → Build Workflows → **Full Release Build (Clean & Archive)** (or `./build_swift_only.sh preset full_release`).
- Prereqs: Developer ID Application certificate installed; notarization credentials saved to `~/.config/marcut/notarize.env` (either App Store Connect API key: `ASC_API_KEY_ID/ISSUER/BASE64` or Apple ID + app-specific password).
- The build signs the DMG, submits for notarization, staples the ticket, and then the bundle audit runs Gatekeeper on the notarized DMG.
- Verify locally before sharing: `xcrun stapler validate MarcutApp-Swift-<ver>.dmg` and `spctl -a -t open --context context:primary-signature -v MarcutApp-Swift-<ver>.dmg` should both report “accepted / Notarized Developer ID”.

See docs/USER_GUIDE.md and docs/DEVELOPER_GUIDE.md for details.
