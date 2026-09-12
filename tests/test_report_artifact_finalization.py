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


def test_post_scrub_explorer_and_encryption_reflect_delivered_docx_not_stale(tmp_path, monkeypatch):
    """Regression for #83.

    The redaction path saves to a staging temp path and only renames it onto
    ``output_path`` after the scrub report is built. If the report's
    post-scrub deep-explorer / encryption sections read ``output_path``
    directly, an output path that already holds a different, pre-existing
    file (e.g. from a prior run) leaks stale content into the report instead
    of describing what is actually delivered.
    """
    monkeypatch.setenv("MARCUT_ENABLE_DEEP_EXPLORER", "1")

    input_path = tmp_path / "input.docx"
    _make_input(input_path)

    output_path = tmp_path / "out.docx"
    # Pre-existing file at the final output path: not even a valid zip/docx,
    # so a buggy implementation that inspects it directly either blows up
    # into a silent "unknown"/None result or reports on the wrong container
    # -- neither of which describes the document that gets delivered below.
    output_path.write_bytes(b"STALE PRIOR RUN, NOT A DOCX CONTAINER")

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

    # The final output path must now hold the newly delivered DOCX, not the
    # stale placeholder.
    delivered = output_path.read_bytes()
    assert delivered != b"STALE PRIOR RUN, NOT A DOCX CONTAINER"

    scrub = json.loads((tmp_path / "out_scrub_report.json").read_text(encoding="utf-8"))

    # Encryption detection on the delivered document must reflect the real,
    # unencrypted DOCX zip -- not the stale non-zip placeholder that used to
    # sit at output_path when the report was built.
    encryption_field = next(
        field
        for field in scrub["groups"]["Embedded Content"]
        if field["field"] == "Package Encryption"
    )
    assert encryption_field["after"]["status"] == "none"

    # Deep explorer must have actually parsed a real DOCX package for the
    # post-scrub side, not silently degraded to None because it tried to
    # open the stale placeholder as a zip.
    post_explorer = scrub.get("deep_explorer", {}).get("post")
    assert post_explorer is not None, "post-scrub deep explorer silently degraded on stale output path"
    assert post_explorer["parts"], "post-scrub deep explorer produced no parts"
    part_names = {part["name"] for part in post_explorer["parts"]}
    assert "word/document.xml" in part_names

    document_xml = next(
        part["text"] for part in post_explorer["parts"] if part["name"] == "word/document.xml"
    )
    assert "STALE PRIOR RUN" not in document_xml
