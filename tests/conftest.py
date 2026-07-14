"""Pytest path setup for src-layout imports."""

from pathlib import Path
import os
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PYTHON = REPO_ROOT / "src" / "python"

if str(SRC_PYTHON) not in sys.path:
    sys.path.insert(0, str(SRC_PYTHON))

# Property-based test profiles (issue #50 / B8): "ci" is derandomized (a fixed seed,
# not a random one per run) so the property tests in tests/test_property_based.py are
# flake-free/reproducible in CI, per that issue's acceptance criteria. Set
# HYPOTHESIS_PROFILE=dev locally for a faster, non-derandomized run while iterating.
try:
    from hypothesis import settings as _hypothesis_settings

    _hypothesis_settings.register_profile(
        "ci", max_examples=100, deadline=None, derandomize=True, print_blob=True
    )
    _hypothesis_settings.register_profile(
        "dev", max_examples=25, deadline=None, print_blob=True
    )
    _hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
except ImportError:
    # hypothesis is a dev-only dependency (pyproject.toml [project.optional-dependencies].dev);
    # tests that need it skip themselves (see tests/test_property_based.py) rather than
    # failing collection for the whole suite when it isn't installed.
    pass
