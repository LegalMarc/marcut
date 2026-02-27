"""Pytest path setup for src-layout imports."""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PYTHON = REPO_ROOT / "src" / "python"

if str(SRC_PYTHON) not in sys.path:
    sys.path.insert(0, str(SRC_PYTHON))
