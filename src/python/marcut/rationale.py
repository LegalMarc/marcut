"""
Shared constants for the redaction-rationale reporting feature (issue #68,
data layer of `docs/design/redaction_rationale_reporting.md`, Option B).

This module exists so `model_enhanced.py`, `pipeline.py`, and
`report_schema.py` agree on the same three-value `origin` enum, the same
definition of "this span came from a deterministic rule, not an LLM call",
and the same cross-reference leak check (`rationale_mentions_text`) without
any of those modules importing each other for it.

``RationaleOrigin`` is intentionally exactly the three values the design doc
settled on for v1 -- ``llm_summary`` (a separate summarization pass, Option
C-lite) was explicitly deferred and must not be added here without also
re-reading the design doc's Option C section.
"""
import re
from enum import Enum
from typing import Iterable, Optional


class RationaleOrigin(str, Enum):
    """Where a span's ``rationale.text`` came from.

    - ``LLM_VALIDATION``: a genuine model-authored explanation returned by
      the extended batch-validation call (`model_enhanced.ollama_validate_batch`),
      tied to the exact call that produced the redact/skip decision.
    - ``RULE_DETERMINISTIC``: a template-generated, non-LLM string describing
      which deterministic rule/pass fired. Never model-authored.
    - ``UNAVAILABLE``: rationale generation was skipped, failed to parse,
      hit the processing deadline, predates this feature, or -- for a
      cross-referencing leak (see `pipeline._sanitize_cross_referenced_rationale`)
      -- was withheld after generation. An explicit, visible state, never an
      omitted field.
    """

    LLM_VALIDATION = "llm_validation"
    RULE_DETERMINISTIC = "rule_deterministic"
    UNAVAILABLE = "unavailable"


# `source` values a span can carry that mean "matched by a deterministic
# rule/consistency pass, never seen by an LLM call". Two families:
#
# * Everything `rules.py`'s `run_rules()` emits starts with "rule": "rule"
#   (the generic detectors), "rule_defined_term" (quoted defined-term names),
#   "rule_signature" (signature-block names), and pipeline.py's own
#   "rule_extended_address" (address continuation). Matched by prefix so a
#   new `rule_*` detector can never silently fall into the LLM path -- the
#   round-3 finding on #68 was exactly two of these being missed by an
#   exact-match set.
# * Pipeline-side deterministic passes: "defined_term"
#   (`_attach_defined_term_aliases`) and "consistency_pass"/
#   "consistency_pass_ci"/"consistency_pass_fuzzy" (`_apply_consistency_pass`).
_RULE_LIKE_EXACT_SOURCES = {"defined_term"}
_RULE_LIKE_PREFIXES = ("rule", "consistency_pass")


def is_rule_like_source(source: Optional[str]) -> bool:
    """True if `source` denotes a deterministic, non-LLM detection path.

    Mitigation #1 (docs/design/redaction_rationale_reporting.md): any span
    matched this way must get only a template-generated rationale, and must
    never be routed through an LLM call to "explain" it after the fact.
    """
    if not source:
        return False
    if source in _RULE_LIKE_EXACT_SOURCES:
        return True
    return source.startswith(_RULE_LIKE_PREFIXES)


_RULE_TEMPLATES = {
    "rule": "Matched a deterministic {label} detection rule.",
    "defined_term": "Matched a document-defined term alias for a previously redacted {label}.",
    "rule_extended_address": "Matched a deterministic address-continuation rule.",
    "rule_defined_term": "Matched a quoted defined-term {label} in a definition clause.",
    "rule_signature": "Matched a {label} on a signature-block line.",
}


def rule_deterministic_rationale_text(label: str, source: Optional[str]) -> str:
    """Template rationale text for a rule-matched span. Never LLM-authored."""
    template = _RULE_TEMPLATES.get(source or "")
    if template is not None:
        return template.format(label=label or "entity")
    if source and source.startswith("consistency_pass"):
        return (
            f"Matched an earlier redacted {label or 'entity'} mention "
            "via the document consistency pass."
        )
    return f"Matched a deterministic {label or 'entity'} detection rule."


# Minimum length (after stripping) an entity text must have before it counts
# as a cross-reference leak inside a rationale string. Shorter texts
# (initials, "Co", "LP") would flag incidental substrings of ordinary prose.
RATIONALE_LEAK_MIN_LEN = 3


def _leak_pattern(candidate: str) -> str:
    """Boundary-aware pattern for one candidate.

    A plain ``\\b`` on both sides silently fails whenever the candidate's
    own edge is not a word character: ``\\bAcme Inc.\\b`` can never match
    "Acme Inc." followed by a space, and the same holds for MONEY ("$500"),
    PHONE ("(555) 123-4567") and quoted defined terms. Those are exactly the
    entity shapes `rules.py` emits, so the boundary is applied only on the
    side where it is meaningful (#68 round-4 finding).
    """
    body = re.escape(candidate)
    left = r"(?<!\w)" if candidate[:1].isalnum() or candidate[:1] == "_" else ""
    right = r"(?!\w)" if candidate[-1:].isalnum() or candidate[-1:] == "_" else ""
    return left + body + right


def compile_leak_scanner(texts: Iterable[str]):
    """Compile ONE alternation matching any of `texts`, or None if none qualify.

    The document-level backstop checks every canonical rationale against
    every other entity's text. Compiling per (rationale x candidate) is
    quadratic and, past Python's regex cache size, recompiles every time --
    minutes of pure regex work on a large document, after all LLM work is
    done (#68 round-5 finding). Compiling once per document and scanning
    each rationale with `scan_leaked_texts` removes the recompilation.

    Honest about what remains: scanning is still proportional to
    (number of rationales x alternation size), so it is not linear --
    measured on the order of a few seconds at 2000 distinct entity texts
    and tens of seconds at 5000 on the post-LLM write path (exact figures
    are machine-dependent; treat them as an order of magnitude). That is acceptable for the document sizes this
    tool targets, but it is a real cost, not a free check; a document with
    tens of thousands of distinct entities would want an
    Aho-Corasick-style scanner instead of a regex alternation.
    """
    candidates = sorted(
        {
            stripped
            for raw in texts
            if len(stripped := (raw or "").strip()) >= RATIONALE_LEAK_MIN_LEN
        },
        key=len,
        reverse=True,
    )
    if not candidates:
        return None
    # Lookahead wrapper so matches may OVERLAP. A plain alternation with
    # `finditer` is non-overlapping: an exempted own-text match ("First
    # National Bank") consumes the start of a different entity's name
    # ("National Bank of Springfield") and hides the leak entirely
    # (#68 round-8 finding). A zero-width lookahead reports every start
    # position independently; the captured group carries the actual text.
    return re.compile(
        "(?i)(?=(" + "|".join(_leak_pattern(c) for c in candidates) + "))"
    )


def scan_leaked_texts(scanner, rationale_text: str) -> set:
    """Lower-cased set of candidate texts `scanner` actually found."""
    if scanner is None or not rationale_text:
        return set()
    return {m.group(1).strip().lower() for m in scanner.finditer(rationale_text)}


def rationale_mentions_text(
    rationale_text: str,
    texts: Iterable[str],
    own_text: Optional[str] = None,
) -> bool:
    """True if `rationale_text` restates any of `texts` literally.

    The single definition of the cross-reference leak check behind the
    design doc's mitigation #5 (the ticket's #3, "placeholder-only
    cross-referencing"): the prompt instructs the model not to name other
    entities, but a generated rationale is free-form text and nothing
    enforces that on the model's side, so it is re-checked in Python before
    the text is ever allowed into the report. Applied twice: within one
    validation batch (`model_enhanced.ollama_validate_batch`) and again
    across the whole document once entity_ids exist
    (`pipeline._sanitize_cross_referenced_rationale`).

    ``own_text`` is the text of the entity this rationale belongs to. The
    prompt explicitly allows the model to name its own item, so any
    candidate that is merely a substring of ``own_text`` is not a leak:
    without this, an item whose text is "Acme Corp Ltd" has its correct
    rationale withheld because a shorter cluster-mate "Acme Corp" matches
    inside the item's own name (#68 round-4 finding). The reverse -- a
    longer other-entity text that merely contains ``own_text`` -- is still
    checked, since naming it does leak that other entity.

    Case-insensitive; candidates shorter than ``RATIONALE_LEAK_MIN_LEN``
    after stripping are skipped. All surviving candidates are matched with a
    single compiled alternation rather than one compile per candidate, so a
    document with more distinct entity texts than Python's regex cache holds
    does not fall off that cliff on the post-LLM hot path.
    """
    if not rationale_text:
        return False
    own = (own_text or "").strip()
    own_lower = own.lower()
    candidates = [c for c in ((raw or "").strip() for raw in texts)
                  if len(c) >= RATIONALE_LEAK_MIN_LEN]
    if not candidates:
        return False
    # The item's own text competes in the same alternation. Because the
    # scanner prefers the LONGEST candidate at any position, an item naming
    # itself ("Acme Corp Ltd is the purchaser") matches its own entry
    # instead of a shorter cluster-mate ("Acme Corp") and is correctly not
    # a leak -- while a genuinely different entity that merely happens to
    # sit inside this item's text ("Smith" vs "Smith Holdings LLC") is
    # still caught, which a plain substring exemption would have missed
    # (#68 round-6 finding).
    scanner = compile_leak_scanner(candidates + ([own] if own else []))
    for matched in scan_leaked_texts(scanner, rationale_text):
        if own_lower and matched == own_lower:
            continue
        return True
    return False
