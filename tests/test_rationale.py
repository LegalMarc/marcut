"""Direct unit tests for `marcut.rationale`'s cross-reference leak check.

The leak check is the load-bearing enforcement behind the redaction-rationale
design doc's mitigation #5 ("placeholder-only cross-referencing", the
ticket's #3): the prompt asks the model not to name other entities, and this
function is the only thing that verifies it before the text reaches the audit
report. It had no direct coverage; these cases pin the boundary behaviour it
gets wrong when the entity text does not begin and end with a word character.
"""
import pytest

from marcut.rationale import (
    compile_leak_scanner,
    scan_leaked_texts,
    RATIONALE_LEAK_MIN_LEN,
    RationaleOrigin,
    is_rule_like_source,
    rationale_mentions_text,
    rule_deterministic_rationale_text,
)


class TestRationaleLeakBoundaries:
    @pytest.mark.parametrize("rationale, leaked", [
        # A plain \b on both sides cannot match any of these, because the
        # candidate's own edge is not a word character (#68 round-4).
        ("He signs on behalf of Acme Inc. in this matter.", "Acme Inc."),
        ("The buyer pays $500,000 at closing.", "$500,000"),
        ("Reachable at (555) 123-4567 during business hours.", "(555) 123-4567"),
        ('Referred to as "Big Co" throughout.', '"Big Co"'),
        ("Counterparty is Widget L.L.C. per section 2.", "Widget L.L.C."),
        # Ordinary word-character-edged text must still be caught.
        ("Signed alongside John Smith yesterday.", "John Smith"),
    ])
    def test_punctuation_edged_entity_text_is_still_detected(self, rationale, leaked):
        assert rationale_mentions_text(rationale, [leaked]) is True

    def test_substring_of_a_longer_word_is_not_a_leak(self):
        # "Acme" inside "Acmecorp" is not a mention of the entity "Acme".
        assert rationale_mentions_text("Employed by Acmecorp Holdings.", ["Acme"]) is False

    def test_candidates_shorter_than_min_len_are_skipped(self):
        short = "x" * (RATIONALE_LEAK_MIN_LEN - 1)
        assert rationale_mentions_text(f"A rationale mentioning {short} here.", [short]) is False

    def test_empty_rationale_and_empty_candidates(self):
        assert rationale_mentions_text("", ["Acme Corp"]) is False
        assert rationale_mentions_text("Some rationale.", []) is False
        assert rationale_mentions_text("Some rationale.", [None, "  "]) is False


class TestRationaleLeakOwnText:
    """The prompt lets the model name its OWN item; only other entities leak."""

    def test_shorter_cluster_mate_inside_own_text_is_not_a_leak(self):
        # Regression (#68 round-4): batch holds both "Acme Corp Ltd" and the
        # short form "Acme Corp". The long-form item naming itself matched
        # \bAcme Corp\b and had its correct rationale withheld.
        assert rationale_mentions_text(
            "Acme Corp Ltd is the named purchaser.",
            ["Acme Corp"],
            own_text="Acme Corp Ltd",
        ) is False

    def test_longer_other_entity_containing_own_text_is_still_a_leak(self):
        # The reverse must NOT be suppressed: own text "Smith" does not
        # license naming the distinct entity "John Smith".
        assert rationale_mentions_text(
            "She co-signed with John Smith.",
            ["John Smith"],
            own_text="Smith",
        ) is True

    def test_unrelated_other_entity_still_leaks_with_own_text_set(self):
        assert rationale_mentions_text(
            "Counterparty to Globex Inc. here.",
            ["Globex Inc."],
            own_text="Acme Corp Ltd",
        ) is True


class TestRuleDeterministicTemplates:
    @pytest.mark.parametrize("source", [
        "rule", "rule_defined_term", "rule_signature", "rule_extended_address",
        "defined_term", "consistency_pass", "consistency_pass_ci", "consistency_pass_fuzzy",
    ])
    def test_every_rule_like_source_has_template_text(self, source):
        assert is_rule_like_source(source) is True
        text = rule_deterministic_rationale_text("ORG", source)
        # Non-empty prose; `rule_extended_address` deliberately does not
        # interpolate the label (the rule is address-specific already).
        assert text and text.endswith(".")

    @pytest.mark.parametrize("source", ["rule_defined_term", "rule_signature"])
    def test_new_rule_sources_get_their_own_text_not_the_generic_fallback(self, source):
        """#68 round-3: these two `rules.py` sources were missing from the
        rule-like set entirely, so they were labelled `unavailable` (or worse,
        inherited an LLM cluster-mate's rationale). They must now be both
        rule-like AND carry source-specific template text."""
        generic = rule_deterministic_rationale_text("NAME", "rule")
        text = rule_deterministic_rationale_text("NAME", source)
        assert is_rule_like_source(source) is True
        assert text != generic and "NAME" in text

    @pytest.mark.parametrize("source", ["llm_extract", "llm", None, "", "unknown"])
    def test_non_rule_sources_are_not_rule_like(self, source):
        assert is_rule_like_source(source) is False

    def test_origin_enum_is_exactly_the_v1_three(self):
        assert {o.value for o in RationaleOrigin} == {
            "llm_validation", "rule_deterministic", "unavailable",
        }


class TestLeakScanner:
    """The document-level backstop compiles one alternation per document
    instead of one regex per (rationale x candidate) pair (#68 round-5)."""

    def test_scanner_finds_all_candidate_forms_including_punctuation_edged(self):
        scanner = compile_leak_scanner(["Acme Inc.", "John Smith", "$500,000"])
        found = scan_leaked_texts(scanner, "Acme Inc. paid $500,000 to the seller.")
        assert "acme inc." in found
        assert "$500,000" in found
        assert "john smith" not in found

    def test_scanner_is_none_when_nothing_qualifies(self):
        assert compile_leak_scanner([]) is None
        assert compile_leak_scanner(["x", "  ", None]) is None
        assert scan_leaked_texts(None, "anything") == set()

    def test_scanner_prefers_the_longest_match(self):
        scanner = compile_leak_scanner(["Acme", "Acme Corporation"])
        assert "acme corporation" in scan_leaked_texts(scanner, "Signed by Acme Corporation today.")

    def test_empty_rationale_scans_to_nothing(self):
        scanner = compile_leak_scanner(["Acme Corp"])
        assert scan_leaked_texts(scanner, "") == set()


class TestDocumentLevelSanitizerScaling:
    """Guards the shape of the fix, not a microbenchmark: the pre-fix code
    recompiled an alternation per canonical rationale, which measured in
    minutes at this size. The bound is deliberately loose so ordinary
    machine noise cannot flake it while a return to quadratic still trips."""

    def test_two_thousand_entities_stays_far_under_quadratic(self):
        import random, string, time
        from marcut import pipeline

        random.seed(7)
        def word():
            return "".join(random.choices(string.ascii_uppercase, k=6))

        spans = []
        for i in range(2000):
            text = f"{word()} {word()}"
            spans.append({
                "start": i * 40, "end": i * 40 + len(text), "label": "ORG",
                "text": text, "entity_id": f"ORG_{i}", "source": "llm_extract",
                "needs_redaction": True,
                "rationale": {"text": "A specific named company party to the agreement.",
                              "origin": "llm_validation", "model": "qwen2.5:14b"},
            })
        started = time.perf_counter()
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert time.perf_counter() - started < 30.0

    def test_leak_is_still_caught_and_innocent_rationale_untouched_at_scale(self):
        from marcut import pipeline

        spans = []
        for i in range(200):
            text = f"Company {i:03d} Holdings"
            spans.append({
                "start": i * 40, "end": i * 40 + len(text), "label": "ORG",
                "text": text, "entity_id": f"ORG_{i}", "source": "llm_extract",
                "needs_redaction": True,
                "rationale": {"text": "A specific named company party to the agreement.",
                              "origin": "llm_validation", "model": "qwen2.5:14b"},
            })
        spans[5]["rationale"]["text"] = f"Counterparty to {spans[9]['text']} in this deal."
        # Naming its own text is not a leak.
        spans[7]["rationale"]["text"] = f"{spans[7]['text']} is the named purchaser."

        pipeline._sanitize_cross_referenced_rationale(spans)

        assert spans[5]["rationale"]["origin"] == "unavailable"
        assert "model" not in spans[5]["rationale"]
        assert spans[7]["rationale"]["origin"] == "llm_validation"
        assert spans[6]["rationale"]["origin"] == "llm_validation"


class TestLeakCheckOwnershipNotSubstring:
    """#68 round-6: an earlier fix exempted any candidate that was a
    substring of the item's own text. That silenced a real leak whenever a
    distinct entity's name happened to sit inside this entity's name."""

    def test_distinct_entity_inside_own_text_is_still_a_leak(self):
        assert rationale_mentions_text(
            "Signed by Smith personally.",
            ["Smith"],
            own_text="Smith Holdings LLC",
        ) is True

    def test_naming_own_full_text_is_not_a_leak_even_with_shorter_mate(self):
        assert rationale_mentions_text(
            "Acme Corp Ltd is the named purchaser.",
            ["Acme Corp"],
            own_text="Acme Corp Ltd",
        ) is False


class TestOverlappingLeakMatches:
    """#68 round-8: `finditer` is non-overlapping, so an exempted own-text
    match could consume the start of a DIFFERENT entity's name and hide the
    leak. The scanner now reports overlapping matches via lookahead."""

    def test_leak_overlapping_the_entitys_own_name_is_caught(self):
        assert rationale_mentions_text(
            "First National Bank of Springfield is the lender under this agreement.",
            ["National Bank of Springfield"],
            own_text="First National Bank",
        ) is True

    def test_document_level_twin_of_the_overlap_case(self):
        from marcut import pipeline

        spans = [
            {"start": 0, "end": 19, "label": "ORG", "text": "First National Bank",
             "entity_id": "ORG_1", "source": "llm_extract", "needs_redaction": True,
             "rationale": {"text": "First National Bank of Springfield is the lender.",
                           "origin": "llm_validation", "model": "qwen2.5:14b"}},
            {"start": 90, "end": 118, "label": "ORG", "text": "National Bank of Springfield",
             "entity_id": "ORG_2", "source": "llm_extract", "needs_redaction": True},
        ]
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == "unavailable"
        assert "model" not in spans[0]["rationale"]


class TestDocumentSanitizerOwnership:
    def test_other_entity_named_inside_own_entity_text_is_withheld(self):
        """Document-level twin of the round-6 case: ORG_1 'Smith Holdings
        LLC' must not keep a rationale naming the distinct person NAME_1
        'Smith'."""
        from marcut import pipeline

        spans = [
            {"start": 0, "end": 18, "label": "ORG", "text": "Smith Holdings LLC",
             "entity_id": "ORG_1", "source": "llm_extract", "needs_redaction": True,
             "rationale": {"text": "Signed by Smith personally.",
                           "origin": "llm_validation", "model": "qwen2.5:14b"}},
            {"start": 40, "end": 45, "label": "NAME", "text": "Smith",
             "entity_id": "NAME_1", "source": "llm_extract", "needs_redaction": True},
        ]
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == "unavailable"
        assert "model" not in spans[0]["rationale"]

    def test_naming_own_full_text_survives(self):
        from marcut import pipeline

        spans = [
            {"start": 0, "end": 18, "label": "ORG", "text": "Smith Holdings LLC",
             "entity_id": "ORG_1", "source": "llm_extract", "needs_redaction": True,
             "rationale": {"text": "Smith Holdings LLC is the named purchaser.",
                           "origin": "llm_validation", "model": "qwen2.5:14b"}},
            {"start": 40, "end": 45, "label": "NAME", "text": "Smith",
             "entity_id": "NAME_1", "source": "llm_extract", "needs_redaction": True},
        ]
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == "llm_validation"

    def test_rules_only_run_skips_the_scanner_entirely(self, monkeypatch):
        """No llm_validation rationale -> no scanner compile at all."""
        from marcut import pipeline, rationale as rationale_mod

        called = []
        monkeypatch.setattr(
            pipeline, "compile_leak_scanner",
            lambda texts: called.append(1) or rationale_mod.compile_leak_scanner(texts),
        )
        spans = [{"start": 0, "end": 5, "label": "NAME", "text": "Smith",
                  "entity_id": "NAME_1", "source": "rule", "needs_redaction": True,
                  "rationale": {"text": "Matched a deterministic NAME detection rule.",
                                "origin": "rule_deterministic"}}]
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert called == []

    def test_shared_literal_across_two_entities_still_allows_self_naming(self):
        """#68 round-7: "Springfield" can legitimately be both a NAME and a
        LOC. Judging leaks purely by entity_id withheld the rationale of an
        entity naming its OWN text, because the same literal also belonged
        to another entity_id."""
        from marcut import pipeline

        spans = [
            {"start": 0, "end": 11, "label": "NAME", "text": "Springfield",
             "entity_id": "NAME_1", "source": "llm_extract", "needs_redaction": True,
             "rationale": {"text": "Springfield is the individual's surname here.",
                           "origin": "llm_validation", "model": "qwen2.5:14b"}},
            {"start": 50, "end": 61, "label": "LOC", "text": "Springfield",
             "entity_id": "LOC_1", "source": "llm_extract", "needs_redaction": True},
        ]
        pipeline._sanitize_cross_referenced_rationale(spans)
        assert spans[0]["rationale"]["origin"] == "llm_validation"


class TestRationaleDoesNotAlterDisabledRunOutput:
    """The opt-in flag must not change the audit JSON of a disabled run."""

    def test_merge_overlaps_preserves_validation_bookkeeping(self):
        """#68 round-7 regression: an interim fix popped
        `validated`/`validation_result` during merge, which changed
        disabled-run reports (validated: true -> absent)."""
        from marcut.pipeline import _merge_overlaps

        llm_span = {"start": 0, "end": 10, "label": "ORG", "text": "Acme Corpor",
                    "confidence": 0.7, "source": "llm_extract",
                    "validated": True, "validation_result": "FULL_REDACT"}
        rule_span = {"start": 0, "end": 6, "label": "ORG", "text": "Acme C",
                     "confidence": 0.98, "source": "rule"}
        merged = _merge_overlaps([llm_span, rule_span], "Acme Corporation signed.")
        assert merged[0]["validated"] is True
        assert merged[0]["validation_result"] == "FULL_REDACT"


class TestGgufPathNotLeakedIntoReport:
    def test_only_the_basename_is_recorded(self):
        """#68 round-7: the audit report carried no filesystem paths; an
        absolute --llama-gguf path would leak the operator's home dir and
        username into an artifact that travels with the document."""
        from marcut import pipeline

        settings = pipeline._build_report_settings(
            mode="llm_overrides", mode_requested="llm_overrides", backend="ollama",
            model_id="qwen2.5:14b", chunk_tokens=250, overlap=50, temperature=0.1,
            seed=42, llm_skip_confidence=0.95,
            llama_gguf="/Users/someone/models/qwen2.5-14b.gguf",
        )
        assert settings["llama_gguf"] == "qwen2.5-14b.gguf"
        assert "/" not in settings["llama_gguf"]

    def test_dispatch_decision_survives_basenaming(self):
        """#68 round-8: basenaming strips the leading '/' and any .gguf
        suffix that `_uses_llama_cpp_backend` keys on, so the decision must
        be recorded from the full path rather than re-derived."""
        from marcut import pipeline

        settings = pipeline._build_report_settings(
            mode="llm_overrides", mode_requested="llm_overrides", backend="ollama",
            model_id="qwen2.5:14b", chunk_tokens=250, overlap=50, temperature=0.1,
            seed=42, llm_skip_confidence=0.95,
            llama_gguf="/Users/alice/models/qwen2.5-14b",
        )
        assert settings["llama_gguf"] == "qwen2.5-14b"
        assert settings["llama_cpp_dispatch"] is True


class TestSelfNamingVersusStandaloneMention:
    """Deliberate semantic, pinned so it is not "fixed" later.

    A shorter entity's text that appears ONLY inside this entity's own name
    is self-naming, which the prompt explicitly permits. The same text
    appearing standalone anywhere in the rationale is a leak, even when the
    own name also appears. #68 round-9 read the first case as a miss; these
    cases record why it is not.
    """

    def test_subsumed_entirely_in_own_name_is_not_a_leak(self):
        assert rationale_mentions_text(
            "Smith Holdings LLC is the counterparty.",
            ["Smith"],
            own_text="Smith Holdings LLC",
        ) is False

    def test_standalone_mention_is_a_leak(self):
        assert rationale_mentions_text(
            "Signed by Smith personally.",
            ["Smith"],
            own_text="Smith Holdings LLC",
        ) is True

    def test_standalone_mention_alongside_own_name_is_still_a_leak(self):
        assert rationale_mentions_text(
            "Smith Holdings LLC; Smith signed personally.",
            ["Smith"],
            own_text="Smith Holdings LLC",
        ) is True
