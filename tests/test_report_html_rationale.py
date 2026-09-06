"""
HTML rendering tests for redaction-rationale reporting (issue #69).

Issue #68 landed the JSON data layer (`SpanRationale`, the `origin` enum).
This covers the presentation half: each span's `rationale` object must
render in the HTML audit report with an origin-appropriate badge, and the
"AI-inferred, not verified" caveat on `llm_validation` rows must be real
text (not a CSS-only cue) so it survives copy/print/export.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'python'))

from marcut import report


def _make_input(tmp_path):
    input_path = tmp_path / "input.txt"
    input_path.write_text("dummy input for hashing")
    return str(input_path)


def _write_and_read_html(tmp_path, spans, rationale_generation=None):
    input_path = _make_input(tmp_path)
    report_path = str(tmp_path / "out.json")
    report.write_report(
        report_path,
        input_path,
        model="mock-model",
        spans=spans,
        rationale_generation=rationale_generation,
    )
    html_path = str(tmp_path / "out.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


def _span(**overrides):
    base = {
        "text": "Acme Holdings LLC",
        "label": "ORG",
        "source": "rule",
        "confidence": 0.95,
        "start": 0,
        "end": 17,
    }
    base.update(overrides)
    return base


class TestRationaleHtmlRendering:
    def test_llm_validation_row_carries_persistent_not_verified_caveat(self, tmp_path):
        spans = [_span(
            source="model",
            rationale={
                "text": "Identifies the acquiring entity in this agreement.",
                "origin": "llm_validation",
                "model": "qwen2.5:14b",
            },
        )]
        html = _write_and_read_html(tmp_path, spans)

        assert "AI-inferred, not verified" in html
        assert "Identifies the acquiring entity in this agreement." in html
        # Badge reuses the existing source-badge pattern, not a new class.
        assert 'class="source-badge llm"' in html

    def test_rule_deterministic_row_gets_neutral_rule_match_badge_no_caveat(self, tmp_path):
        spans = [_span(
            source="rule",
            rationale={
                "text": "Matched a deterministic ORG detection rule.",
                "origin": "rule_deterministic",
            },
        )]
        html = _write_and_read_html(tmp_path, spans)

        assert "Rule match" in html
        assert "Matched a deterministic ORG detection rule." in html
        assert "AI-inferred" not in html
        assert 'class="source-badge rule"' in html

    def test_unavailable_origin_renders_explicit_visible_state(self, tmp_path):
        spans = [_span(
            source="model",
            rationale={"text": "", "origin": "unavailable"},
        )]
        html = _write_and_read_html(tmp_path, spans)

        assert "No rationale recorded for this entity." in html
        assert 'class="source-badge unavailable"' in html

    def test_missing_rationale_field_degrades_without_crash_or_blank(self, tmp_path):
        """A pre-#68 report (or one generated with the feature disabled)
        has no `rationale` key on the span at all -- rendering must not
        crash and must not leave a misleading blank cell."""
        spans = [_span(source="rule")]
        assert "rationale" not in spans[0]

        html = _write_and_read_html(tmp_path, spans)

        assert "No rationale recorded for this entity." in html
        assert '<td class="rationale-cell"></td>' not in html

    def test_unrecognized_llm_prefixed_origin_still_carries_caveat(self):
        """Fail safe, not fail open: an origin that is neither
        `rule_deterministic` nor `unavailable` -- including a future `llm_*`
        origin that doesn't exist yet, like the design doc's deferred
        `llm_summary` -- must still render the "not verified" caveat rather
        than silently falling through to the "No rationale" unavailable
        state with no caveat at all.

        Exercises `_render_rationale_cell` directly rather than through
        `write_report`'s `AuditReport` schema validation: the schema's
        `origin` enum rejects any value it doesn't already know about, so a
        genuinely new origin would only ever reach the renderer once the
        schema is updated too -- this pins the renderer's own fallback
        behavior so it fails safe independently of that future update.
        """
        span = _span(
            source="model",
            rationale={
                "text": "A hypothetical future LLM-authored rationale variant.",
                "origin": "llm_summary",
            },
        )
        cell_html = report._render_rationale_cell(span)

        assert "AI-inferred, not verified" in cell_html
        assert "A hypothetical future LLM-authored rationale variant." in cell_html
        assert 'class="source-badge llm"' in cell_html

    def test_rule_like_consistency_pass_source_gets_rule_badge_not_llm(self, tmp_path):
        """Regression: the old `source == 'rule'` exact-match predicate
        missed `consistency_pass*`/`rule_signature`/etc. spans, so a
        rule_deterministic rationale rendered next to a contradictory 'llm'
        source badge in the same row."""
        spans = [_span(
            source="consistency_pass_fuzzy",
            rationale={
                "text": "Matched an earlier redacted ORG mention via the document consistency pass.",
                "origin": "rule_deterministic",
            },
        )]
        html = _write_and_read_html(tmp_path, spans)

        # The Source column badge must be 'rule', not 'llm', for this span.
        idx = html.find("consistency_pass_fuzzy")
        assert idx != -1
        row_start = html.rfind("<tr>", 0, idx)
        row_end = html.find("</tr>", idx)
        row_html = html[row_start:row_end]
        assert 'source-badge rule' in row_html
        assert 'source-badge llm' not in row_html
