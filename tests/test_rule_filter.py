import os

import pytest

# Skip the entire module if marcut.rules is not importable (e.g., deps not installed).
marcut_rules = pytest.importorskip("marcut.rules", reason="marcut.rules unavailable")
run_rules = marcut_rules.run_rules


@pytest.fixture(autouse=True)
def clear_rule_filter(monkeypatch):
    monkeypatch.delenv("MARCUT_RULE_FILTER", raising=False)
    yield
    monkeypatch.delenv("MARCUT_RULE_FILTER", raising=False)


def test_filter_limits_labels(monkeypatch):
    text = "Email me at jane.doe@example.com or call +1 (555) 222-3333."
    monkeypatch.setenv("MARCUT_RULE_FILTER", "PHONE")
    spans = run_rules(text)
    labels = {span["label"] for span in spans}
    assert "PHONE" in labels
    assert "EMAIL" not in labels


def test_empty_filter_allows_none(monkeypatch):
    text = "Call (555) 111-2222 tomorrow."
    monkeypatch.setenv("MARCUT_RULE_FILTER", "")
    spans = run_rules(text)
    assert spans == []


def test_signature_rule_toggle(monkeypatch):
    text = "Name: John Q. Public"
    # Enabled
    monkeypatch.setenv("MARCUT_RULE_FILTER", "SIGNATURE")
    spans = run_rules(text)
    assert any(span["label"] == "NAME" for span in spans)

    # Disabled
    monkeypatch.setenv("MARCUT_RULE_FILTER", "EMAIL")
    spans_disabled = run_rules(text)
    assert all(span["label"] != "NAME" for span in spans_disabled)
