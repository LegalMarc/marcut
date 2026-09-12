"""Golden-file characterization harness for `docx_io.py` (issue #70).

This is the prerequisite gate for the entire docx_io.py package split
(docs/design/docx_io_package_split.md, §3.2 item 1): it must be green
against the CURRENT, unsplit `docx_io.py` before any extraction slice
(#72-#76) begins, and every slice re-runs it and expects an unchanged
result. See tests/docx_io_golden/harness.py for the full design rationale
(what gets snapshotted, how non-determinism is handled, and how to
re-baseline a golden file after a deliberate behavior change).

Run just this suite with:

    PYTHONPATH=src/python python3 -m pytest tests/test_docx_io_golden.py -q

This test module makes no edits to docx_io.py -- tests and fixtures only.
"""
import os
import tempfile

import pytest

from marcut.docx_io import MetadataCleaningSettings

from tests.docx_io_golden import fixtures as fx
from tests.docx_io_golden import harness

# (golden snapshot name, MetadataCleaningSettings variant) -- two variants
# so the harness exercises both the aggressive default pipeline (nearly
# every clean_* flag True) and the "none" preset (minimal mutation, so the
# scan/index layer's fidelity is characterized with almost nothing else
# disturbing the document structure).
_VARIANTS = [
    ("kitchen_sink_default", MetadataCleaningSettings()),
    ("kitchen_sink_none", MetadataCleaningSettings.from_preset("none")),
]


@pytest.fixture(scope="module")
def kitchen_sink_path(tmp_path_factory):
    work_dir = tmp_path_factory.mktemp("docx_io_golden_kitchen_sink")
    path = str(work_dir / "kitchen_sink.docx")
    fx.build_kitchen_sink_docx(path)
    return path


@pytest.mark.parametrize("golden_name,settings", _VARIANTS, ids=[v[0] for v in _VARIANTS])
def test_kitchen_sink_matches_golden(kitchen_sink_path, golden_name, settings, tmp_path):
    out_path = str(tmp_path / f"{golden_name}_output.docx")
    snapshot = harness.run_characterization(kitchen_sink_path, out_path, settings)
    harness.assert_matches_golden(golden_name, snapshot)


def test_fixture_is_byte_deterministic(tmp_path):
    """The fixture builder itself must be deterministic, or the harness
    above is meaningless (a "diff" could just be fixture jitter)."""
    path_a = str(tmp_path / "a.docx")
    path_b = str(tmp_path / "b.docx")
    fx.build_kitchen_sink_docx(path_a)
    fx.build_kitchen_sink_docx(path_b)
    with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
        assert fa.read() == fb.read()


def test_all_redactable_markers_present_in_built_text():
    """Guards the harness's own span-finding logic: every marker listed as
    redactable must actually appear in DocxMap.text, or the golden
    snapshot would silently stop exercising apply_replacements() for it."""
    from marcut.docx_io import DocxMap

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "kitchen_sink.docx")
        fx.build_kitchen_sink_docx(path)
        dm = DocxMap.load(path)
        for key in fx.REDACTABLE_MARKERS:
            marker = fx.MARKERS[key]
            assert marker in dm.text, f"marker {marker!r} ({key}) missing from DocxMap.text"
