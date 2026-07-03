# Design Spike: LLM-Generated Plain-English Redaction Rationale in the Audit Log

Status: Design spike (no code changes). Companion to issue #32, item "Automated
'Redaction Rationale' Reporting" in `backlog.md`'s "Major New Directions" section.

## Goal

Today's JSON/HTML audit reports (`marcut/report.py`) tell a reviewer *what*
was redacted, *where*, and with what numeric confidence, but not *why* — a
line like `{"label": "ORG", "text": "Acme Corp", "confidence": 0.95, "source":
"llm"}` gives no human-readable justification a paralegal could paste into a
privilege log ("redacted because it identifies the acquiring entity"). This
doc evaluates using the LLM to generate that plain-English justification,
covers where in the pipeline it would run and its cost against the existing
deadline budget, what report-schema changes it implies, and — because the
ticket is explicit that this is the central risk — an accuracy/hallucination
analysis of presenting LLM-authored text as if it were a verified fact in a
document that may end up supporting a privilege-log claim.

## Current State (what this feature would sit on top of)

Three facts about the existing code are load-bearing for this whole proposal.

**1. A "rationale" field already exists on `Entity`, and is already
partially populated, but never reaches the audit report.**
`model_enhanced.py:78` defines `Entity.rationale: Optional[str] = None`. It is
set in a few places today:
- `model_enhanced.py:670` — `rationale="Rule span override check"` (a fixed,
  non-LLM string, when a rule span is overridden by an LLM check).
- `model_enhanced.py:1119` — `rationale="Extracted by model"` (a fixed
  string, in the single-entity extraction path).
- `model_enhanced.py:1379` — `rationale=item.get("rationale")`, pulled from
  the raw extraction JSON if the model happened to include one (it isn't
  asked to; see below).
- `model_enhanced.py:605` — `rationale=f"Batch Validation: {final_classification}
  ({confidence})"`, set inside `ollama_validate_batch()` (the function that
  is actually invoked by the production `IntelligentRedactionPipeline.
  process_document()` chunk-processing loop, `model_enhanced.py:917-974`).
  This string is **not** LLM-authored prose — it's a Python f-string built
  from the classification label and confidence score the LLM already
  returned. It reads like an explanation but is really a restatement of two
  fields already in the report.

Despite existing on `Entity`, **`rationale` never survives into the JSON/HTML
report**. The span dicts actually assembled by the production pipeline
(`pipeline.py`'s span-building code, feeding `report.write_report()`) have
zero references to `rationale` — confirmed by grep; the only place a
`"rationale"` key is attached to a span dict is the *legacy*, unused-by-
production `IntelligentRedactionPipeline.process_document()` in
`model_enhanced.py:1421-1465` (distinct from the batch-oriented
`process_document` that chunk extraction actually calls). This means the
groundwork (a named field, a place to put a short string) already exists in
the domain model but was never wired through to what a user actually sees —
which is itself informative: this is a "plumb an existing field," not a
"invent a new concept," change, at least for the mechanical part.

**2. The two-pass architecture already makes one LLM call per candidate
entity that classifies *whether* to redact — this is the natural hook for
*why*, not a new call.** `IntelligentRedactionPipeline.process_document()`
(`model_enhanced.py:838-1204`) runs chunked extraction (`ollama_extract`,
cheap, name/org/loc spans only) followed by **batched validation**
(`ollama_validate_batch`, `model_enhanced.py:495-608`) for any entity that
`needs_validation()` flags (`model_enhanced.py:351-431` — roughly: low
confidence, matches an excluded-word/boilerplate pattern, or an ambiguous
rationale from extraction). The validation call already sends the model a
batch prompt (`get_batch_validation_prompt`, `model_enhanced.py:434-492`)
asking for `classification` (`FULL_REDACT`/`SKIP`) and `confidence` per item,
and the model is *already reading* the surrounding context needed to justify
a decision — it just isn't currently asked to state one in the batch path.
(The older single-entity prompt, `get_validation_prompt`,
`model_enhanced.py:281-348`, *does* ask for `"explanation": "brief
explanation of your decision"` — proving the model can produce this in the
same call shape already used elsewhere in this file — but that prompt isn't
the one the production batch loop sends.) This is the central fact shaping
the recommendation below: the marginal cost of a rationale is extending an
**existing, already-budgeted** LLM call's prompt and expected JSON shape,
not adding a new call.

**3. Not every span goes through an LLM call at all, so "explain every
redaction" cannot mean "every explanation is LLM-authored."**
`needs_validation()` explicitly bypasses validation for
high-precision structured types (`EMAIL`, `PHONE`, `SSN`, `MONEY`, `NUMBER`,
`model_enhanced.py:360-361`) and for any NAME/ORG/LOC candidate confident
and clean enough to skip the LLM's second look (`model_enhanced.py:424-429`).
Those spans are matched by the deterministic regex/format rules in
`rules.py` and never touch the LLM — their `source` field is already `"rule"`
(`pipeline.py:1536` defaults unlabeled spans to `"rule"`; see also the
`"defined_term"`, `"consistency_pass"`, `"consistency_pass_ci"`,
`"consistency_pass_fuzzy"` source values other pipeline stages set,
`pipeline.py:531,698,724,768`). A "rationale" feature has to produce a
truthful explanation for these spans too (a reviewer reading a privilege log
doesn't care that the mechanism differed), but it must not silently
fabricate an LLM-style narrative for a decision the LLM never made — this is
elaborated in the Risk Analysis section below, because it's the sharpest
version of the hallucination-adjacent risk the ticket asks about.

## Pipeline Integration Point

Three options, evaluated against `MARCUT_PROCESSING_DEADLINE_MONOTONIC`
(`cancellation.py:12-19` — a monotonic wall-clock deadline threaded through
the whole run via `remaining_seconds()`/`check_processing_deadline()`, which
every Ollama HTTP call already respects via `timeout=remaining_seconds(...)`,
e.g. `model.py:543,786`, and which raises `ProcessingDeadlineExceeded` the
moment the budget is exhausted, aborting the run rather than silently
truncating work).

### Option A — A new LLM call per redacted span

Fire a dedicated "explain this redaction" prompt for every span in the final
report, after redaction decisions are finalized.

- **Cost**: one full LLM round-trip per span, unbatched. A document with
  ~150 entities (not unusual for the `sample-files/` contracts referenced
  elsewhere in this codebase's docs) means ~150 additional serialized-ish
  HTTP calls to Ollama (bounded in parallelism only by whatever executor is
  used) on top of the extraction and validation calls that already run.
  Given the existing batch-validation call for ~20-item batches
  (`model_enhanced.py:927`, the flush threshold) already represents a
  meaningful fraction of total wall-clock time in the two-pass pipeline, a
  *fully unbatched* per-span call is the most expensive option by a wide
  margin and the one most likely to blow the processing deadline on larger
  documents, especially since it runs strictly *after* extraction+validation
  rather than overlapping with it.
- **Verdict**: Rejected as the primary mechanism. The cost is disproportionate
  to the value for spans where a one-line explanation is genuinely
  unambiguous (an SSN is an SSN), and it's the only option requiring a
  wholly new call type with no code reuse from the existing validation-batch
  machinery.

### Option B — Extend the existing per-entity/batch validation call

Add a `rationale` (or reuse/repurpose the existing `explanation` field name
already present in the *unused* single-entity prompt) to the JSON shape
`get_batch_validation_prompt()` already asks for, and thread the returned
string through `ollama_validate_batch()`'s `final_results` dict
(`model_enhanced.py:601-606`) in place of today's synthetic
`f"Batch Validation: {classification} ({confidence})"` string.

- **Cost**: marginal. The batch validation call already happens for every
  entity `needs_validation()` flags; asking the model to also emit one more
  short string field per item in a JSON array it's already constructing adds
  output tokens (proportional to explanation length × batch size) but no
  additional round trips. This is the only option whose cost scales with
  "how much text the model must additionally generate," not "how many extra
  network calls happen," which is the right cost axis given
  `MARCUT_PROCESSING_DEADLINE_MONOTONIC` is a wall-clock budget dominated by
  round-trip latency more than token-generation time for the batch sizes
  this pipeline already uses.
- **Coverage gap**: this only covers spans that went through validation.
  High-confidence rule-matched structured PII (EMAIL/PHONE/SSN/MONEY/NUMBER)
  and high-confidence NAME/ORG spans that `needs_validation()` correctly
  decided not to bother the LLM about (`model_enhanced.py:424-429`) get no
  LLM-authored rationale under this option alone. See Option C-lite below
  for how this doc proposes closing that gap safely.
- **Verdict**: Recommended as the primary mechanism for the (majority)
  subset of spans that already go through LLM validation.

### Option C — A single summarization pass over the finished audit report

After the full report (`spans`, `warnings`, `suppressed`) is assembled, send
one (or a handful of batched) LLM call(s) that reads the finished entity list
plus surrounding document context and generates one rationale string per
entity, decoupled from the extraction/validation calls entirely.

- **Cost**: better than Option A (can be batched, one call covers many
  spans) but strictly worse than Option B for the LLM-validated subset,
  because it duplicates work the validation call already did — the model
  already read the surrounding context and decided FULL_REDACT/SKIP once;
  asking a *second*, later call to re-derive "why" from scratch (now
  disconnected from the exact classification reasoning that produced the
  decision) risks the rationale and the decision drifting apart — precisely
  the "does the stated rationale actually match why the span was redacted"
  failure mode the ticket calls out by name.
- **Where it's actually useful**: as a *targeted* pass over only the spans
  Option B's coverage gap leaves unexplained — i.e., not "summarize
  everything again," but "for the subset of spans that were never sent to
  the LLM at all (pure rule/consistency-pass matches), optionally run one
  batched call at report-assembly time that explains *why the rule fired*"
  (which is a different, more constrained task than "why should this be
  redacted" — see MVP recommendation).
- **Verdict**: Rejected as a *replacement* for Option B (redundant, risks
  decision/rationale drift); retained as a scoped-down, optional
  supplementary pass — "C-lite" — for the coverage gap, discussed in the MVP
  section.

### Recommendation on integration point

**Primarily Option B** — extend the existing batch validation prompt/response
shape in `model_enhanced.py` to carry a genuine rationale string, replacing
the synthetic `f"Batch Validation: ..."` placeholder at
`model_enhanced.py:605` with the model's actual stated reasoning (falling
back to today's synthetic string, clearly labeled as non-LLM-authored, if the
model's response omits the field or fails to parse — never silently reusing
one entity's explanation for another). This is the only option whose
marginal cost rides on infrastructure the pipeline is already paying for on
every run that has validation-eligible entities, and it directly attaches
the explanation to the exact same model call that produced the redact/skip
decision, minimizing decision/rationale drift. Deterministic rule-only spans
are handled separately (never through an LLM call inventing a story after
the fact) — see Report Schema and Risk Analysis below.

## Report Schema Changes

Current per-span shape written by `report.write_report()` (via whatever span
dicts `pipeline.py` assembles — confirmed fields in practice: `start`, `end`,
label`, `text`, `confidence`, `source`, plus ad hoc fields like
`needs_redaction` depending on pipeline stage). Proposed additions:

```jsonc
{
  "start": 1204,
  "end": 1213,
  "label": "ORG",
  "text": "Acme Corp",
  "confidence": 0.95,
  "source": "llm",              // existing field; already distinguishes rule vs llm vs consistency_pass*
  "needs_redaction": true,

  // NEW fields:
  "rationale": {
    "text": "Redacted because it identifies the acquiring entity named earlier in Section 2.",
    "origin": "llm_validation",  // enum, see below — REQUIRED, drives report rendering
    "model": "qwen2.5:14b"       // optional; omit if origin != llm_*, since a rule has no model
  }
}
```

**`rationale.origin` enum** (this is the field the Risk Analysis section
below treats as non-negotiable, not a nice-to-have):

- `"llm_validation"` — a genuine model-authored explanation returned by the
  extended batch-validation call (Option B), tied to the exact call that
  produced the redact/skip decision for this span.
- `"llm_summary"` — a model-authored explanation produced by a *separate*,
  later pass (Option C-lite) that did not itself make the redaction
  decision — necessarily a slightly weaker guarantee (see Risk Analysis) and
  must be visually/textually distinguished from `llm_validation` in the
  report, not merged into one undifferentiated "AI explanation" bucket.
- `"rule_deterministic"` — a template-generated, non-LLM string describing
  *which rule fired* (e.g., `"Matches SSN pattern (rules.py: SSN_REGEX)"`),
  used for spans whose `source` is `"rule"` or one of the
  `consistency_pass*` values. Never model-authored; safe to state as fact.
  This closes Option B's coverage gap for the majority of rule-only spans
  cheaply (string templating, zero LLM cost) rather than paying for
  Option C-lite on every run.
- `"unavailable"` — validation/rationale was skipped, failed to parse, hit
  the processing deadline mid-batch, or the entity predates this feature
  (e.g., a cached `ValidationCache` entry from before this schema existed —
  `ValidationCache` already exists at `model_enhanced.py` and would need a
  cache-key/version bump so that stale cached validations without a
  rationale don't silently masquerade as ones that considered it). The
  report and HTML renderer must treat `"unavailable"` as an explicit,
  visible state ("No rationale recorded for this entity") rather than
  omitting the field, so its absence is never ambiguous with "the redaction
  needed no justification."

**Report-level additions** (`report.py`'s top-level `data` dict,
`report.py:69-81`):
- `"rationale_generation": {"enabled": true/false, "model": "...", "mode":
  "validation_extended"}` — a single top-level flag recording whether this
  run generated rationale at all (see "opt-in" discussion below) and which
  mechanism produced it, so a reviewer opening an *older* report (generated
  before this feature existed, or with it disabled) can immediately tell
  "no rationale" means "not requested" rather than "requested and silently
  failed for every span."

**HTML report** (`report.py`'s `_generate_html_audit_report()`,
`report.py:163-470`): each entity-table row would need a rationale
cell/expandable detail, visually distinct by `origin` — this doc recommends
a small badge (e.g., "AI-inferred" for `llm_*` origins vs. "Rule match" for
`rule_deterministic`) directly adjacent to the explanation text itself, not
just in a legend elsewhere on the page, since the explanation is most
dangerous exactly where a reader's eye actually lands. The existing
`source-badge rule`/`source-badge llm` CSS classes (`report.py:743-751`,
`.source-badge.rule` / `.source-badge.llm`) are a reasonable visual
precedent to extend rather than invent a new badge language from scratch.

**Opt-in vs. always-on**: the ticket explicitly asks whether this should be
opt-in given added LLM calls/processing time. Given Option B's marginal-cost
argument above (extending an existing call, not adding one), the
`llm_validation` origin's cost is low enough that always-on is defensible
*for validated spans*. However, this doc recommends **opt-in at the run
level regardless** (a flag analogous to existing `MARCUT_*` env vars /
CLI flags), for two reasons independent of raw cost: (1) rationale text
increases the audit report's information surface — some users may
specifically not want additional LLM-generated narrative text about their
document's contents persisted to disk, which is a data-handling preference
distinct from a performance one; (2) it lets the accuracy/labeling machinery
in this doc ship and be validated against real documents before it's on by
default for every user, consistent with how a security/legal-adjacent
feature with a real hallucination risk should be rolled out incrementally
rather than silently turned on for everyone at once.

## Accuracy / Hallucination Risk Analysis

This is the section the ticket treats as mandatory, and for good reason: an
audit report in this tool is not a casual UI nicety — it's positioned
(per the ticket itself) to "assist automated privilege-log generation," i.e.
its output may end up quoted or relied on in an actual legal context where
the boundary between "the tool's verified finding" and "the tool's guess
about why" matters a great deal to whoever relies on it later.

**Core problem: an LLM-generated rationale is not a verified fact, and nothing
about its presentation in a table row next to `confidence: 0.95` currently
signals that.** The existing report already blends two categories that read
identically to a user (a `confidence` bar renders the same way whether the
span came from a regex or a model), but with a rationale, the risk compounds:
a redaction rationale is *prose*, and prose reads as more authoritative,
more "reasoned," than a bare confidence float — a paralegal skimming a
privilege log is more likely to accept "redacted because it identifies the
acquiring entity" as established fact than they are to over-trust a `0.95`.
This is a UI/presentation risk as much as a model-accuracy one.

**Failure mode 1 — plausible-sounding but wrong rationale for a correct
decision.** The model classifies "Acme Corp" as `FULL_REDACT` (correct — it
is genuinely the acquiring entity) but justifies it with an invented detail
not actually in the document ("...because it is headquartered in Delaware
and was the subject of the 2019 merger...") — the redaction decision is
right, but the *stated reason* contains fabricated specifics. If this text
is ever pasted into an actual privilege log or produced in discovery as
supporting documentation for *why* something was withheld, a fabricated
justification is now itself a false statement of fact in a legal work
product, independent of whether the underlying redaction was correct. This
is the sharpest version of the risk and the reason `origin` labeling (above)
alone is necessary-but-not-sufficient — the report must not just say
"AI-inferred," it should also make clear via copy/UI language that inferred
explanations are unverified prose, not extracted facts, even when correctly
labeled as AI-generated.

**Failure mode 2 — rationale/decision mismatch (the ticket's explicit
question: "what happens if the LLM's stated rationale doesn't actually match
why the span was redacted — was it rules-based, not LLM-based, for that
span?").** Two distinct sub-cases:
  - *Wrong-mechanism attribution*: if a rule-matched span (e.g., an SSN
    caught by `rules.py`'s regex, never seen by any LLM call) were ever run
    through a summarization pass (Option C-lite) that generates rationale by
    asking an LLM "why would this be redacted," the model will confabulate a
    plausible-sounding semantic reason ("this appears to be a sensitive
    identifier associated with an individual") for a decision that was, in
    truth, "it matched `\d{3}-\d{2}-\d{4}`." The explanation isn't
    necessarily *false* in outcome, but it misattributes the mechanism,
    which matters if anyone later audits *how* the tool made its decisions
    (e.g., investigating a false negative — "why didn't the tool catch this
    other SSN-like string" is only answerable if the report honestly
    distinguishes rule-pattern-match spans from model-judgment spans). This
    is exactly why `rationale.origin: "rule_deterministic"` must be a
    template string describing the actual rule, never an LLM call, for
    spans whose `source` is `"rule"`/`consistency_pass*` — closing this
    failure mode by construction rather than by hoping the model is honest
    about its own non-involvement.
  - *Stale-cache mismatch*: `ValidationCache` (`model_enhanced.py`) caches
    validation results across entities/runs by `(text, label)`. If rationale
    generation is added without a cache-key or schema version bump, a cached
    hit could return `needs_redaction`/`classification` from a fresh call
    but a rationale string cached from a differently-worded historical
    prompt (or `None`, if cached before this feature existed) — silently
    pairing a decision with an unrelated or missing explanation. The MVP
    must bump the cache schema (or key) alongside this feature so a cache
    hit either returns a rationale generated by the *same* prompt version or
    is treated as a cache miss for the rationale field specifically.

**Failure mode 3 — inconsistent rationale across a clustered entity's
mentions.** `pipeline.py`'s `ClusterTable`/consistency-pass logic already
gives every mention of "Acme Corp" across a document a single stable ID
(`[ORG_1]`) regardless of which specific occurrence triggered LLM validation
first. If rationale is generated per-span rather than per-cluster, different
mentions of the same entity could receive different (possibly
contradictory) rationale strings depending on which surrounding sentence
each occurrence happened to sit in when validated — one reads "the acquiring
entity," another reads "the entity providing financing." Neither is
necessarily wrong in isolation (both could be true facts about the same
company from different parts of the document) but presenting them
side-by-side under the same cluster ID without reconciliation looks like an
inconsistency bug to a reviewer, eroding trust in the whole report. MVP
scope note: generate/display rationale at the cluster level (one rationale
per stable entity ID, from its first/highest-confidence validated mention),
not per raw span, specifically to avoid this.

**Failure mode 4 — rationale leaking content that should itself have been
redacted.** Because the rationale is free-form generated text, nothing stops
the model from including *other* sensitive spans inside its own explanation
("redacted because it's the co-signer alongside [other unredacted PII])")
— i.e., the explanation text is a fresh, unredacted output channel the
existing pipeline's overlap-merging/redaction machinery never sees or
processes, since it's generated *after* redaction decisions are finalized.
This must be treated as seriously as the primary redaction task: rationale
text should either be run back through the rules pass (cheap, already
available) before being written to the report, or the prompt should be
constrained (e.g., "refer to other entities only by their already-assigned
`[LABEL_N]` placeholder, never restate their text") — this doc recommends
the latter as primary defense (cheaper, and avoids a second redaction pass
on LLM output racing the deadline) with the former as a defense-in-depth
backstop given the stakes.

**Mitigations required before shipping (non-negotiable, not aspirational):**

1. **Mandatory, non-omittable `origin` labeling** on every rationale
   (`llm_validation` / `llm_summary` / `rule_deterministic` / `unavailable`),
   enforced at the schema level (report writer should refuse/warn rather
   than write a rationale object missing `origin`), not left to rendering
   code to infer.
2. **Explicit "unverified inference" language in the report UI itself**,
   adjacent to each `llm_*`-origin rationale, not just in a one-time legend —
   e.g., a persistent small-caps "AI-INFERRED, NOT VERIFIED" label directly
   on the badge (extending the existing `source-badge` CSS pattern), so the
   caveat travels with the text if a row is copied/screenshotted/printed
   individually (the report already supports a print action,
   `report.py:227,419-428` — printed/exported output must retain the
   labeling, not silently drop styling-only cues that don't survive to
   print).
3. **Rule-matched spans get template-generated, non-LLM rationale only**
   (`rule_deterministic`), never routed through an LLM summarization pass,
   closing failure mode 2's wrong-mechanism-attribution case by construction.
4. **Cluster-level rationale, not per-span**, closing failure mode 3.
5. **Placeholder-only cross-referencing in generated rationale text**
   (never restating another entity's actual text), closing failure mode 4,
   validated by a regression test asserting no other known entity span's
   literal text appears inside a generated rationale string.
6. **Cache-schema/version bump for `ValidationCache`** so stale cache hits
   cannot pair a fresh decision with a mismatched or absent rationale
   (failure mode 2's stale-cache case).
7. **A golden-file regression suite** (mirroring the testing rigor of
   `docs/design/incremental_track_changes_redaction.md`'s own recommended
   test plan) asserting: every `llm_*`-origin rationale entity has a
   non-empty `origin`; every `rule_deterministic` entity's rationale was
   never sent through an LLM call (assert via mock/call-count, not just
   output inspection); no rationale string contains another span's literal
   `text`; disabling the feature (`rationale_generation.enabled: false`)
   produces byte-identical spans/decisions to today's output (i.e., the
   feature is additive to the report and never changes what gets redacted).

## MVP Recommendation

**Recommendation: pursue, opt-in, scoped as follows** — this is a lower-risk
feature than some of the codebase's other design-spike proposals (e.g.
`incremental_track_changes_redaction.md`'s diff-only scanning, which risks
*under-redaction* — actual PII leakage) because a wrong or low-quality
rationale does not, by itself, cause any PII to go unredacted; the entity is
still redacted or not exactly as it would be today. The risk here is
reputational/legal-work-product accuracy (a fabricated or misattributed
*explanation*), which is real and must be taken seriously per the Risk
Analysis above, but is a different and more containable risk class than
silently skipping a scan.

1. **Integration point: Option B only for v1** — extend the existing batch
   validation prompt/response in `model_enhanced.py` to request and carry a
   genuine rationale string, replacing the synthetic
   `f"Batch Validation: ..."` placeholder. Do not build Option A (per-span
   calls, too expensive) or Option C/C-lite (summarization pass) in v1;
   defer C-lite (rule-span rationale) to a fast-follow once the
   llm_validation path has proven the labeling/UI machinery is solid on
   real documents, and use cheap template strings
   (`rule_deterministic`, described above) for rule-matched spans from day
   one instead — this gets every span *some* rationale field in v1 without
   needing the more failure-prone summarization pass.
2. **Schema: `rationale: {text, origin, model?}` on every span**, plus
   report-level `rationale_generation` metadata, exactly as specified above.
   `origin` is mandatory at write time.
3. **Granularity: per stable entity cluster, not per raw span offset**
   (failure mode 3), sourced from the first successfully-validated mention.
4. **Opt-in via an explicit flag** (env var or CLI flag consistent with
   existing `MARCUT_*` naming, e.g. `MARCUT_GENERATE_RATIONALE`), defaulting
   off, so the accuracy-labeling UI and the mitigations above can be
   validated against real redacted documents before this is ever the
   default experience.
5. **UI**: extend the existing `source-badge` visual language in the HTML
   report with a distinct, persistent "AI-inferred, not verified" treatment
   for `llm_*` origins vs. a neutral "rule match" treatment for
   `rule_deterministic`, and ensure the distinction survives print/export.
6. **Testing**: implement the full mitigation list above as permanent
   regression tests (not one-time manual checks) before enabling by default
   for any user, given this doc's own conclusion that prose rationale
   carries a materially higher "reads as authoritative" risk than the
   numeric confidence scores the report already displays.

**Explicitly deferred / out of scope for this doc:**

- Actually rewriting `get_batch_validation_prompt()`'s prompt text or JSON
  schema (a code change, out of scope per the ticket).
- Any UI mockup beyond the badge-language extension described above — full
  visual design of the rationale display is a product-design question.
- Option C/C-lite's summarization-pass implementation details, deferred as
  a fast-follow per the MVP recommendation above.
- Localization of generated rationale text (the existing report is
  English-only throughout; no reason to scope differently here, but noting
  it's untouched by this doc).
