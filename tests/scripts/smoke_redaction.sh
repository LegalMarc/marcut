#!/usr/bin/env bash
# Headless smoke test using Python CLI with mock backend (no LLM)
# Creates a tiny DOCX, runs redaction, and checks outputs.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON_EXEC="${ROOT_DIR}/.marcut_artifacts/ignored-resources/temp-venvs/venv/bin/python"
if [[ ! -x "${PYTHON_EXEC}" ]]; then
  PYTHON_EXEC="python3"
fi
export PYTHONPATH="${ROOT_DIR}/src/python:${PYTHONPATH:-}"

TMPDIR=$(mktemp -d 2>/dev/null || mktemp -d -t marcut)
INPUT="$TMPDIR/test.docx"
OUTDOC="$TMPDIR/out.docx"
OUTJSON="$TMPDIR/out.json"

${PYTHON_EXEC} - "$INPUT" << 'PY'
from docx import Document
from pathlib import Path
import os, sys

inp = Path(sys.argv[1])
doc = Document()
doc.add_paragraph('Contact us at info@sample123.com or visit https://example.com')
doc.save(inp)
print('Created', inp)
PY

${PYTHON_EXEC} -m marcut.cli redact --in "$INPUT" --out "$OUTDOC" --report "$OUTJSON" --backend mock --model mock --mode rules --debug || {
  echo "Redaction CLI failed"; exit 1;
}

test -f "$OUTDOC" && echo "✓ DOCX output present: $OUTDOC" || { echo "✗ Missing $OUTDOC"; exit 1; }
test -f "$OUTJSON" && echo "✓ JSON report present: $OUTJSON" || { echo "✗ Missing $OUTJSON"; exit 1; }

echo "Smoke test passed"
echo "$OUTDOC"
echo "$OUTJSON"
