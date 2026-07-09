# User Guide

This guide explains how to run Marcut to produce Word documents with track changes and JSON audit reports.

## macOS App (Embedded Runtime)
- The signed macOS app ships with an embedded Python 3.11 runtime (BeeWare) and an embedded Ollama service. No system Python or Ollama install is required.
- Enhanced mode downloads a local model on first use (Settings > Manage Models). Rules Only works immediately.
- CLI example:
  `/Applications/MarcutApp.app/Contents/MacOS/MarcutApp --cli --redact --in <doc> --out <doc> --report <json> --mode enhanced --model qwen2.5:14b`
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
- Model pulled in Ollama (recommended: `qwen2.5:14b`)

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
ollama pull qwen2.5:14b
```

### Run redaction (CLI)
```
marcut redact \
  --in sample-files/Sample 123 Consent.docx \
  --out runs/out.docx \
  --report runs/out.json \
  --mode enhanced \
  --backend ollama \
  --model qwen2.5:14b \
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
    model_id='qwen2.5:14b',
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

### Redaction coverage by document part

The rules/LLM detection pipeline scans -- and, when a match is found, writes
track changes (`w:ins`/`w:del`) into -- every part of the DOCX that can carry
running text:

| Document part | Scanned for PII | Redacted with track changes |
| --- | --- | --- |
| Main body (paragraphs) | Yes | Yes |
| Tables (including nested tables, and tables inside headers/footers/footnotes/endnotes) | Yes | Yes |
| Headers and footers (default, first-page, even-page) | Yes | Yes |
| Footnotes | Yes | Yes |
| Endnotes | Yes | Yes |
| Textboxes / drawings (legacy VML and modern DrawingML) | Yes | Yes |
| Content controls / structured document tags (block-level and inline) | Yes | Yes |
| Review comments (`word/comments.xml`) | No | No (see below) |

**Review comments are a documented exception.** Comment text itself (as
opposed to the body text a comment is anchored to) is never scanned by the
redaction pipeline. By default this is safe: the metadata-cleaning defaults
(`clean_review_comments_visible` and `clean_review_comments_hidden`, both
`True`) remove the entire comments part from the output, so no comment text
-- redacted or not -- ships at all. If you explicitly retain comments (for
example with `--no-clean-review-comments-visible`), any PII inside a
retained comment is **not** redacted and ships verbatim. In that case the
JSON report includes a `REVIEW_COMMENTS_NOT_SCANNED` warning so the gap is
disclosed rather than silent -- treat retained comments as unreviewed and
redact them manually in Word if they may contain sensitive information.

Similarly, `clean_headers_footers` (`True` by default) wholesale-removes
headers/footers as a metadata-hardening measure (a common letterhead/
branding leakage vector). If you disable it with `--no-clean-headers-footers`
to keep a required legend or page-numbering header, the table above applies:
any PII in the retained header/footer is redacted with track changes like
any other part.

### AI extraction failures fail the run closed

In `enhanced` (and other LLM-using) modes, long documents are split into
overlapping chunks and each chunk is analyzed by the local model
independently. If the model extraction for a chunk never succeeds -- after
its automatic retries -- Marcut does **not** fall back to redacting only
what the other chunks found. The entire run fails closed: no output DOCX is
written, and the JSON report is a failure report (`"status": "error"`) with
`"error_code": "AI_CHUNK_EXTRACTION_INCOMPLETE"` whose `technical_details`
names the exact document character range(s) that were never analyzed. This
is deliberate: for a privacy tool, silently shipping a "redacted" document
that skipped an unanalyzed range would be worse than failing the run --
retry with a smaller chunk size, a different model, or check that Ollama is
reachable, then re-run. This is separate from a processing-deadline abort
(`AI_PROCESSING_TIMEOUT`), which continues to fail the run the same way it
always has.

## Troubleshooting
- "Ollama not installed": The CLI checks for the `ollama` binary in PATH. If your server is running but the binary is missing, install Ollama or fix PATH.
- Empty/low ORG or NAME detection: Ensure the model is running and selected (e.g., `--model qwen2.5:14b`).
- Excessive ORG detections: Use `--mode enhanced` and tune excluded words and system prompt.
