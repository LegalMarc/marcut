# Design Spike: Interactive Redaction Mode with LLM Ambiguity Flagging

Status: Design spike (no code changes). Companion to issue #27.

## Goal

Today's pipeline is fully automatic: the enhanced two-pass extractor
(`marcut/model_enhanced.py`) decides `needs_redaction` for every entity, the
document is written straight to Track Changes, and the human's only recourse
is to accept/reject individual redactions after the fact inside Word, with no
visibility into *why* the model was or wasn't confident. This doc proposes an
interactive review step — surfaced before the DOCX is finalized — where spans
the pipeline is genuinely unsure about are grouped and presented to the user
for an explicit redact/skip decision, per `backlog.md`'s "Major New
Directions" item: *"On-the-fly 'Interactive Redaction' Mode: Offer an
interactive diff viewer where the LLM flags ambiguous spans (e.g., 'I found
12 references to Project Phoenix, should I redact them?') for user
approval."*

This is explicitly a UX layer on top of signal that already exists in the
pipeline. It does not propose a new detection mechanism, a new model call, or
new scoring math.

## What "ambiguous" already means in the pipeline

The two-pass extractor already computes exactly the signal this feature
needs; nothing here has to be invented.

1. **`Entity.confidence` and `Entity.needs_redaction`**
   (`model_enhanced.py:70-81`) — every extracted span carries a `0.0-1.0`
   confidence and a boolean redaction decision from the first extraction
   pass.

2. **`DocumentContext.get_confidence_threshold(label)`**
   (`model_enhanced.py:237-257`) — a per-label dynamic threshold computed as
   the bottom quartile of that label's confidence distribution in the current
   document (falls back to a flat `0.7` when fewer than 5 same-label entities
   exist). This is already a document-relative, not a global, notion of "low
   confidence" — an important property to preserve rather than replace.

3. **`needs_validation(entity, doc_context)`** (`model_enhanced.py:351-431`)
   — decides whether an entity is sent to the second (validation) pass at
   all. It forces validation when: the rationale contains hedging language
   ("might be", "possibly", "unclear", ...); the surface text matches the
   excluded-words list (a validation trigger, not an auto-skip, per the
   "Option A" comment in that function); the confidence falls below the
   dynamic threshold from #2; the span matches known problematic
   boilerplate patterns for ORG/NAME (`"the company"`, `"whereas"`,
   `"agreement"`, etc.); or the span is unusually long (>60 chars). Entities
   that are high-confidence and consistent with their `needs_redaction` value
   skip validation.

4. **`Entity.validation_result`** (`model_enhanced.py:81`, populated at
   `model_enhanced.py:957-958` and `1131-1132`) — for entities that *do* go
   through validation, this holds the second pass's classification:
   `FULL_REDACT | SKIP | PARTIAL_REDACT | CONTEXT_DEPENDENT` (see the
   validation prompt at `model_enhanced.py:332-338`), plus an updated
   `confidence` and `needs_redaction`.

5. **`Entity.validated`** (`model_enhanced.py:80`) — whether a second-pass
   validation call actually ran for this entity, as opposed to it being kept
   at its first-pass confidence.

6. **Cross-mention clustering** (`marcut/cluster.py`, wired up in
   `pipeline.py:_finalize_and_write` at `pipeline.py:1298-1322`) — every
   NAME/ORG/BRAND span is linked via `ClusterTable.link()` (fuzzy
   `token_set_ratio` matching, threshold `0.82`) to a stable `entity_id` like
   `ORG_1`, shared across every mention of the same entity in the document.
   `combine()` (`marcut/confidence.py`) bumps confidence slightly
   (`+0.07`) for each repeated agreeing mention. This is precisely the
   mechanism behind the backlog's "12 references to Project Phoenix" example:
   grouping is not something new to build — it already happens, and all 12
   spans already carry the same `entity_id`.

7. **`low_conf(confidence)`** (`marcut/confidence.py`) — a fixed `< 0.88`
   cutoff already used today to flag spans in the DOCX track-change metadata
   (`pipeline.py:1358`, `replacements[...]["low_confidence"]`) and to color
   the confidence bar in the existing read-only HTML audit report
   (`report.py:284`, `report.py:345`).

**Ambiguity, for this feature, is therefore defined as**: any span where
`validated=True` and `validation_result in {PARTIAL_REDACT,
CONTEXT_DEPENDENT}`, OR `low_conf(confidence)` is true, OR the span's
`needs_redaction` flipped between the first and second pass (i.e. the model
itself disagreed with itself). No new classifier, prompt, or model call is
required — this is a filter/grouping predicate over fields the pipeline
already emits per span.

## Proposed UI flow

### Where it sits in the existing review flow

Today: **Drop documents → pipeline runs → DOCX with Track Changes is
written → user opens DOCX in Word → accepts/rejects changes manually.**

Proposed: insert an optional interactive step *before* the DOCX is
finalized, between LLM extraction/validation and `_finalize_and_write()`
(`pipeline.py:1280`):

**Drop documents → pipeline runs extraction + validation → [NEW] Ambiguity
Review screen (in-app, not Word) → user resolves each ambiguous group →
pipeline resumes at `_finalize_and_write()` with the user's decisions baked
into each span's `needs_redaction` → DOCX with Track Changes is written →
user opens DOCX in Word for final accept/reject as today.**

This keeps Word's own Track Changes UI as the mechanism of record for the
*final* accept/reject decision (required for redline audit trails and
because Word's UI is well understood by legal reviewers) and adds a
lightweight *pre-filter* so the model isn't guessing silently on the hard
cases. It does not change what a "redaction" is or how Track Changes are
applied — it changes one input to `_finalize_and_write()`: the boolean
`needs_redaction` on ambiguous spans, moving from "the model guessed" to
"the user decided."

### Screen shape (MVP)

- One row per **ambiguity group**, not per span. A group is: the `entity_id`
  for NAME/ORG/BRAND (all 12 "Project Phoenix" mentions collapse to one
  row), or an individual span for other labels which aren't clustered
  (DATE, MONEY, PHONE, etc. — though per `needs_validation`,
  EMAIL/PHONE/SSN/MONEY/NUMBER never reach validation and so never appear
  here at all).
- Each row shows: the entity text, its label, one representative sentence of
  surrounding context (reuse the highlighting logic already built for the
  single-entity validation prompt, `model_enhanced.py:295-308`, rather than
  building new snippet extraction), the mention count within its cluster,
  and the model's own uncertainty in plain language sourced from
  `validation_result` / `rationale` (e.g. "Classified CONTEXT_DEPENDENT —
  could be a generic role or a specific person depending on context").
- Two actions per row: **Redact all N mentions** / **Skip all N mentions**.
  A "view individual mentions" expansion is a stretch goal, not MVP — see
  Scope below.
- A running counter ("3 of 8 ambiguous groups resolved") and a single
  "Apply and continue" action that's disabled until all groups are resolved
  or explicitly deferred to a safe default.
- Default-safe behavior: if the user closes the screen without deciding,
  unresolved groups keep the pipeline's original `needs_redaction` value
  (i.e. this feature can only be a no-op vs. today's automatic behavior — it
  never silently becomes *more* permissive by timing out to "skip").

### Non-goals for the UI (MVP)

- No free-text editing of the redaction boundaries in this screen (span
  start/end are not adjustable here — that's what the Word Track Changes
  step remains for).
- No per-mention override within a cluster in the MVP; that's the natural v2
  once the group-level flow is validated with real users.

## Changes needed in the JSON audit report / pipeline output

The audit array built in `_finalize_and_write()` (`pipeline.py:1483-1493`)
already contains every field the UI needs per span: `start`, `end`, `label`,
`entity_id`, `confidence`, `source`, `text`, `validated`,
`validation_result`. No new per-span field is required.

What's missing is a **grouping and gating layer** between "spans exist" and
"DOCX gets written," because today `_finalize_and_write()` runs straight
through with no pause point:

1. **A pre-finalize hook.** `run_redaction_enhanced()` (`pipeline.py`, the
   enhanced entry point) currently calls straight through from LLM
   extraction to `_finalize_and_write()`. This needs a new optional
   suspend point after spans are collected (`_collect_enhanced_spans`,
   `pipeline.py:1545`) and before finalize, gated behind a flag (e.g.
   `interactive_review: bool`) so the CLI/batch path is completely
   unaffected by default.

2. **An ambiguity-group payload**, derived purely from existing span fields
   — no pipeline computation changes, just a new aggregation function
   (e.g. `_group_ambiguous_spans(spans) -> List[Dict]`) that:
   - Filters spans matching the ambiguity predicate defined above.
   - Groups by `entity_id` where present, else treats the span as its own
     group.
   - Emits `{group_id, label, sample_text, mention_count, span_indices:
     [...], confidence, validation_result, rationale}` — `span_indices`
     referencing back into the original `spans` list so the resolution step
     can flip `needs_redaction` on exactly those entries without
     re-deriving anything.
   - This payload is what would cross the Swift/Python bridge (via the
     same JSON-over-stdio / PythonKit call convention already used for
     progress and results elsewhere in `PythonKitBridge.swift`) for the new
     SwiftUI review screen to render, and — for CLI/headless use — can
     optionally be written to a sidecar file (e.g.
     `<report>.ambiguities.json`) so the JSON audit report format itself
     stays unchanged and backward compatible.

3. **A resolution intake.** After the user acts, the UI returns
   `{group_id: "redact" | "skip"}` decisions. The pipeline applies each
   decision to every span index in that group's `span_indices`, setting
   `sp["needs_redaction"]` and appending a `sp["validation_result"] =
   "USER_REDACT"` / `"USER_SKIP"` marker (new enum values, additive, not
   replacing the existing `FULL_REDACT|SKIP|PARTIAL_REDACT|
   CONTEXT_DEPENDENT` set) so the final audit report — and any future
   privilege-log tooling — can distinguish a human decision from a model
   decision. This is the one genuinely new field value; everything else in
   this section is aggregation over existing data.

4. **Report settings flag.** `_build_report_settings()`
   (`pipeline.py:1189`) already threads UI-configured settings
   (`llm_skip_confidence`, etc.) into the report; add
   `interactive_review_used: bool` and `ambiguous_group_count: int` there so
   the audit report records whether/how much human-in-the-loop review
   happened on a given run — useful for compliance narratives ("N ambiguous
   entities were reviewed and confirmed by a human").

No change is proposed to `Entity`, to the extraction/validation prompts, to
`ClusterTable`, or to `combine()`/`low_conf()`. This keeps the spike scoped
to plumbing and UI, consistent with the ticket's framing.

## MVP recommendation

Ship in this order, each independently useful and independently shippable:

1. **Sidecar ambiguity file + CLI flag only** (no Swift UI yet):
   `--interactive-preview` writes `<report>.ambiguities.json` using the
   grouping function in step 2 above, pipeline continues automatically as
   today. Validates the grouping predicate and payload shape against real
   documents before investing in UI, and is useful on its own for a
   reviewer scanning a JSON/HTML summary of "here's what the model was
   unsure about" even without a click-through workflow.
2. **Read-only ambiguity summary in the existing HTML audit report**
   (`report_html.py`) — a new section listing ambiguous groups with their
   context and mention counts, using the same confidence-bar CSS classes
   already defined (`report.py:723-733`). Still no interactivity, but closes
   the loop from "data exists" to "human can see it" cheaply.
3. **Interactive SwiftUI review screen** wired to the pre-finalize
   suspend point (item 1 in the previous section) — the actual feature
   described in the backlog item. This is the largest slice: it requires
   the Swift/Python bridge to support a request/response round trip mid-
   pipeline (today's bridge calls are fire-and-forget until completion),
   which is the main open architecture question and should be scoped as
   its own ticket once 1–2 have validated the underlying data model.
4. **Per-mention override within a cluster** (v2, explicitly out of MVP
   scope per the "Non-goals" section above).

Steps 1–2 require no changes to the Swift/Python bridge and can land
independently of any decision about how mid-pipeline round trips work
architecturally. Step 3 is the one that should get its own design/scoping
pass before implementation, since "pause a running Python pipeline call and
resume it with new input" is a different shape of problem than anything the
current bridge does today.
