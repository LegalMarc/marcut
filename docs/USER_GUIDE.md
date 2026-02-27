# User Guide

This guide explains how to run Marcut to produce Word documents with track changes and JSON audit reports.

## macOS App (Embedded Runtime)
- The signed macOS app ships with an embedded Python 3.11 runtime (BeeWare) and an embedded Ollama service. No system Python or Ollama install is required.
- Enhanced mode downloads a local model on first use (Settings > Manage Models). Rules Only works immediately.
- CLI example:
  `/Applications/MarcutApp.app/Contents/MacOS/MarcutApp --cli --redact --in <doc> --out <doc> --report <json> --mode enhanced --model llama3.1:8b`
- Outputs are written to user-selected locations; the CLI defaults to the input directory when sandbox permissions allow it.
- If the sandbox blocks app-CLI file access, copy inputs into `~/Library/Application Support/MarcutApp/` (for example `Work/Input/`) before invoking the CLI.
- GUI startup runs an embedded-interpreter smoke test and will display a blocking alert if the runtime cannot load, keeping failures obvious.

### Redaction Settings
- **Rules Only vs Enhanced** - The mode picker determines whether documents pass through just the deterministic rules engine or the full rules+LLM pipeline.
- **Rules Engine tweaks** - In any mode you can click **Edit Excluded Terms...** to edit the boilerplate list (`excluded-words.txt`). Changes save under Application Support and apply to both CLI and GUI immediately.
- **Advanced AI settings** - When Enhanced is selected, the "Advanced AI Settings" card appears with sliders for temperature, chunk size/overlap, processing timeout, and seed. There is also an **Edit System Prompt...** button for customizing the LLM instruction template. The card is hidden in Rules Only mode to avoid confusion but your values are preserved when you switch back.
- **Future preference** - Consider adding a toggle to default excluded-term spans to "do not redact" in Enhanced, with the validator opting in to redaction when needed.
- New overrides do not require an app restart; both GUI and CLI read the updated files automatically.

## Source / CLI (from repo)

### Requirements
- Python 3.9+ (3.11 recommended)
- Ollama running locally (http://localhost:11434) for enhanced modes
- Model pulled in Ollama (recommended: `llama3.1:8b`)

### Install
```
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

### Start Ollama
```
ollama serve &
ollama pull llama3.1:8b
```

### Run redaction (CLI)
```
marcut redact \
  --in sample-files/Sample 123 Consent.docx \
  --out runs/out.docx \
  --report runs/out.json \
  --mode enhanced \
  --backend ollama \
  --model llama3.1:8b \
  --debug
```

Notes:
- Use `--mode rules` for rules-only processing (no Ollama required).
- Use `--mode enhanced` for the two-pass LLM pipeline.
- Use `--backend llama_cpp` with `--llama-gguf <path>` to run a local GGUF model.
- If the CLI preflight says Ollama is not installed but the server is running, add the `ollama` binary to PATH.

### Run redaction (programmatically)
```python
from marcut.pipeline import run_redaction

exit_code, timings = run_redaction(
    input_path='sample-files/Sample 123 Consent.docx',
    output_path='runs/out.docx',
    report_path='runs/out.json',
    mode='enhanced',
    model_id='llama3.1:8b',
    chunk_tokens=1000,
    overlap=150,
    temperature=0.1,
    seed=42,
    debug=True,
)
```

## Outputs
- Track-changes DOCX with redactions applied
- JSON report with spans, labels, entity IDs (for NAME/ORG/BRAND), confidence, and sources
- Optional metadata scrub report (`*_scrub_report.json`) with before/after values

## Troubleshooting
- "Ollama not installed": The CLI checks for the `ollama` binary in PATH. If your server is running but the binary is missing, install Ollama or fix PATH.
- Empty/low ORG or NAME detection: Ensure the model is running and selected (e.g., `--model llama3.1:8b`).
- Excessive ORG detections: Use `--mode enhanced` and tune excluded words and system prompt.
