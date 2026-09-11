# CONTEXT — Marcut domain vocabulary

This file is a glossary only: the terms and concepts specific to this repo's
domain, not implementation details. It grows lazily, one entry at a time, as
terms get resolved in conversation.

**Span** — a character range in the extracted document text, carrying a label, a
confidence and a source. The unit everything downstream operates on. Offsets are
into the flattened text built by the document scan, not into any one XML part.

**Label** — the category a span was detected as: NAME, ORG, LOC, and the
structured types the rules engine finds (email, phone, credit card, date, money).
Labels are ranked, and the higher-ranked label wins when two spans overlap.

**Entity** — a real-world subject a span refers to. Several spans across a
document can be mentions of one entity.

**Cluster** — the grouping of NAME and ORG mentions judged to be the same entity,
maintained by the cluster table. A cluster owns a stable entity ID, which is what
makes the replacement text consistent across a document, so the same person is
`[NAME_3]` everywhere rather than a different number per mention.

**Mention** — one span belonging to a cluster. The distinction matters because
rationale is canonicalised per entity ID, not per mention.

**Rationale** — a short plain-English explanation of why a span was redacted,
attached to the span in the audit report. Every rationale carries a mandatory
origin: LLM validation, rule-deterministic, or unavailable. Off by default.

**Leak** — a rationale that restates another entity's literal text, which would
defeat the redaction it is explaining. Checked both within a validation batch and
across the whole document. An entity's own name appearing inside its own
rationale is self-naming, not a leak.

**Redaction** — replacing a span's text with a bracketed placeholder while
recording the change as a native Word revision, so a reviewer sees tracked
changes rather than a flattened document.

**Scrub** — removing metadata and hidden content from the DOCX container itself,
independent of any span. Comments, mail-merge sources, hidden text, watermarks,
EXIF in embedded images, custom style names, chart labels.

**Hardening** — the in-memory XML passes that perform scrubbing, as distinct from
the raw ZIP post-processing pass that rewrites parts, relationships and the
content-types map after the document has been saved.

**Consistency pass** — a second sweep that re-matches already-identified entity
text elsewhere in the document, catching mentions the first pass missed. Bounded
by a candidate limit so a large document cannot make it quadratic.

**Dispatch** — the decision of which backend runs a given step, Ollama or
llama.cpp. Deliberately separated from the model value displayed in reports, so
sanitising a filesystem path out of a report cannot change which backend runs.

**Deadline** — the shared processing budget for a run. Exceeding it raises rather
than truncating, so a partial result is never mistaken for a complete one.

**Transactional write** — the staging pattern for output. Artifacts are written to
a sibling temporary path and atomically renamed, so a crashed run never leaves a
half-written DOCX or report where a complete one is expected.
