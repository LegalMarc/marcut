"""End-to-end regression tests for report artifact finalization.

Both reports are rendered from transactional staging temp paths and only
renamed onto their final names afterwards. These tests pin the two things
that must survive that rename:

1. Each HTML report's "View Raw JSON Data" link points at the final JSON
   basename, not at the temp name that gets removed.
2. The scrub report's ``file_info.output`` sha256/size describe the DOCX
   the user actually receives.
"""

import hashlib
import json
import os
import re

import pytest

from marcut import pipeline

docx = pytest.importorskip("docx")


HREF_RE = re.compile(r'href="([^"]*\.json)"')


def _make_input(path):
    document = docx.Document()
    document.add_paragraph("Prepared for John Smith at Acme Holdings LLC.")
    document.add_paragraph("Contact john.smith@example.com or 415-555-0134.")
    document.save(str(path))


def _run(tmp_path):
    input_path = tmp_path / "input.docx"
    _make_input(input_path)
    output_path = tmp_path / "out.docx"
    report_path = tmp_path / "out.json"
    code, _timings = pipeline.run_redaction(
        str(input_path),
        str(output_path),
        str(report_path),
        mode="rules",
        model_id="mock",
        chunk_tokens=250,
        overlap=50,
        temperature=0.1,
        seed=42,
        debug=False,
        backend="mock",
        do_qa=False,
    )
    assert code == 0, f"redaction failed with exit code {code}"
    return output_path, report_path


def _json_links(html_path):
    return HREF_RE.findall(html_path.read_text(encoding="utf-8"))


def test_audit_html_links_final_json_name(tmp_path):
    _output_path, report_path = _run(tmp_path)
    html_path = tmp_path / "out.html"
    assert html_path.exists()
    assert report_path.exists()

    links = _json_links(html_path)
    assert links, "audit HTML has no JSON link"
    for link in links:
        assert link == report_path.name
        assert (tmp_path / link).exists()


def test_scrub_html_links_final_json_name(tmp_path):
    _run(tmp_path)
    scrub_json = tmp_path / "out_scrub_report.json"
    scrub_html = tmp_path / "out_scrub_report.html"
    assert scrub_json.exists() and scrub_html.exists()

    links = _json_links(scrub_html)
    assert links, "scrub HTML has no JSON link"
    for link in links:
        assert link == scrub_json.name
        assert (tmp_path / link).exists()


def test_no_report_links_to_a_staging_temp_path(tmp_path):
    _run(tmp_path)
    for name in ("out.html", "out_scrub_report.html"):
        for link in _json_links(tmp_path / name):
            assert ".tmp." not in link
            assert not link.startswith(".")


def test_scrub_report_output_hash_matches_delivered_docx(tmp_path):
    output_path, _report_path = _run(tmp_path)
    scrub = json.loads((tmp_path / "out_scrub_report.json").read_text(encoding="utf-8"))
    output_info = scrub["file_info"]["output"]

    delivered = output_path.read_bytes()
    assert output_info["sha256"] == hashlib.sha256(delivered).hexdigest()
    assert output_info["size_bytes"] == len(delivered)
    assert output_info["size_bytes"] == os.path.getsize(output_path)
    assert output_info["file_name"] == output_path.name
