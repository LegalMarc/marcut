# Design Spike: Multi-Model Orchestration (Fast First-Pass + Escalation)

Status: Design spike (no code changes). Companion to issue #30.

## Goal

`backlog.md`'s "Major New Directions" section lists: *"Multi-Model
Orchestration Workflow: Use a smaller model like `phi4-mini` for a fast
first pass, and route only low-confidence sentence chunks to a larger model
like `qwen3.5:9b`."* This doc proposes how that would work, framed
explicitly as an extension of the existing two-pass extractor/validator in
`src/python/marcut/model_enhanced.py`, not a new pipeline. Per the ticket,
this doc does not implement anything and does not run new benchmarks.

## 1. Integration with the Existing Two-Pass Pipeline

The framing in the ticket — "this is an extension of an existing pattern,
not a new one" — is accurate and worth being precise about, because Marcut
already has a two-model-role architecture today, just not across two
differently-*sized* models:

- **Pass 1 (extraction):** `IntelligentRedactionPipeline.process_document()`
  (`model_enhanced.py:838`) calls `ollama_extract()` (from `.model`) once
  per chunk, using a single configured `self.model_id` for every chunk. All
  extracted spans get a fixed `confidence=0.7` (`model_enhanced.py:1117`) —
  extraction itself does not currently produce a real per-entity confidence
  signal, it's a placeholder.
- **Pass 2 (validation):** `needs_validation()` (`model_enhanced.py:351`)
  decides, per entity, whether it should be sent to `ollama_validate_batch()`
  (`model_enhanced.py:495`) for a second LLM call — using the *same*
  `self.model_id` again. The routing signal for "does this need a second
  look" already exists: exclusion-list membership, uncertainty phrases in
  the rationale, label-specific heuristics (`the Company`, `board of`,
  etc.), span length, and a **dynamic confidence threshold**
  (`DocumentContext.get_confidence_threshold()`, `model_enhanced.py:237`,
  bottom-quartile-of-observed-confidence per label).
- **The existing `skip_confidence` mechanism** (default `0.95`,
  `IntelligentRedactionPipeline.__init__`, `model_enhanced.py:823`) gates
  the *output* of Pass 2: `ollama_validate_batch()` only lets the model
  clear an entity (`needs_redaction=False`) when its self-reported
  `confidence >= skip_confidence` (`model_enhanced.py:585-593`). Below that
  bar, the result defaults to `needs_redaction=True` regardless of what the
  model classified — the code comment calls this "Bias Towards Retention."
  This is a fail-closed, redact-when-unsure design, and it is the
  precedent this proposal must not weaken.

**What multi-model orchestration changes:** today, both passes use the
same `model_id` throughout a run — the "escalation" is only in *whether* a
second LLM call happens, never in *which model* handles it. This proposal
adds a second, larger model as an option for one specific hop: when
Pass 2's validation call itself returns low confidence, instead of only
defaulting to "keep/redact" as it does today, optionally re-run that one
validation call on the larger model before falling back to the retention
default. It does **not** touch Pass 1's chunk extraction — see the
"routing signal" discussion below for why.

**What is reused as-is, unchanged:**
- `needs_validation()`'s routing heuristics (unchanged — they decide
  whether *any* validation call happens at all, independent of model size).
- `skip_confidence` and the retention-bias default in
  `ollama_validate_batch()` (unchanged — see MVP recommendation for the
  one narrow addition).
- `ValidationCache` (`model_enhanced.py:84`) — cache key is
  `text.lower():label`, model-agnostic by construction, so a cached
  decision from either model still short-circuits repeat lookups.
- `DocumentContext` and its dynamic per-label confidence threshold
  (`model_enhanced.py:237`) — this stays the trigger for "does this entity
  need validation at all"; it is upstream of, and independent from, which
  model handles the validation call itself.
- The `ThreadPoolExecutor`-based concurrency model
  (`self.llm_concurrency`, `model_enhanced.py:832,917`) — escalation calls
  would be submitted through the same executor, not a separate one, to
  avoid a second uncoordinated concurrency knob (see Section 3).

## 2. Routing Rule Proposal

### Why the escalation point is Pass 2, not Pass 1

The ticket's phrasing ("route only low-confidence chunks to a larger
model") suggests escalating extraction itself. This doc recommends
against that, for a concrete reason grounded in the current code: **Pass 1
extraction does not produce a real confidence signal to route on.** Every
extracted span gets a hardcoded `confidence=0.7`
(`model_enhanced.py:1117`) — there is no per-span extraction confidence
from the model today, only from the *validation* call's self-reported
`confidence` field, which is a real (if self-reported) LLM output already
parsed by `parse_llm_response()`. Building a first-pass extraction router
would require first adding meaningful extraction-time confidence, which is
a separate, larger, and unscoped piece of work — and Pass 1 already runs
concurrently across chunks with `self.llm_concurrency` workers, so a
faster first-pass model mainly buys wall-clock speed on a stage that's
already parallelized, not the accuracy improvement the ticket's spirit
(catch what the small model is unsure about) is really asking for.

Pass 2 validation, by contrast, already has:
- A real per-call confidence value from the model's own output.
- An existing "what happens when confidence is low" branch — currently it
  just defaults to retention (`model_enhanced.py:593-599`) rather than
  trying harder.
- A per-entity (or per-batch) granularity that maps cleanly onto "escalate
  this specific ambiguous item," rather than "re-run an entire chunk."

**Recommended routing rule:** in `ollama_validate_batch()`
(`model_enhanced.py:495`), after receiving the small model's batch
validation response, partition results by the *existing* `skip_confidence`
threshold — but instead of the two-way split that exists today (skip if
confident enough, else retain-by-default), add a third band:

```
confidence >= skip_confidence                    -> SKIP (unchanged, small model)
escalation_floor <= confidence < skip_confidence  -> escalate to larger model
confidence < escalation_floor                     -> FULL_REDACT (unchanged, small model, retention bias)
```

`escalation_floor` is a new, separate, lower threshold (e.g. `0.60`,
tunable) — the point is that entities the small model is *moderately*
unsure about (not "confidently generic" and not "confidently don't know")
are exactly the ambiguous middle where a bigger model's judgment is worth
the extra latency. Entities the small model is very unsure about
(`confidence < escalation_floor`) skip straight to the existing
retain-by-default behavior rather than paying for an escalation call that
is unlikely to change the outcome — the large model gets called only when
it's plausibly going to change the decision, not as a blanket second
opinion.

### What happens if the larger model is also low-confidence

The escalation call reuses `ollama_validate_batch()` (or the single-entity
`ollama_validate()`) with the larger `model_id`, gated by the *same*
`skip_confidence` bar — there is no separate, lower bar for the escalated
model. If the large model's result is still below `skip_confidence`:

- **Default to retention** (`needs_redaction=True`), identical to today's
  behavior for any low-confidence result. This is a direct extension of
  the existing "Bias Towards Retention" comment in
  `ollama_validate_batch()` (`model_enhanced.py:588-591`) — the code
  already documents that this bias is deliberate and must not be
  weakened, and a design that let two uncertain models talk each other
  into skipping a redaction would be exactly the kind of weakening that
  comment warns against.
- No further escalation tier. A third, even-larger model is out of scope
  for the MVP (see Section 4) and would compound the latency risk
  discussed in Section 3 for diminishing accuracy return — the "Bias
  Towards Retention" fallback is a legitimate terminal state, not a gap
  to be engineered away.
- The final result should record *which* model(s) were consulted (e.g.
  extend the existing `rationale` field, currently
  `f"Batch Validation: {final_classification} ({confidence})"` at
  `model_enhanced.py:605`, to include the model tier) so the audit report
  can show "escalated, still uncertain, retained" as a distinct outcome
  from "not escalated, retained" — useful both for debugging and for the
  kind of transparency `docs/SECURITY.md`/audit-report conventions favor
  elsewhere in this codebase.

## 3. Latency/Throughput Tradeoff Analysis

### Baseline: what the current benchmark data actually shows

`scripts/run_qwen_experiment.py` and `experiment_results.csv` are cited in
the ticket as prior art. Reading the actual data before proposing a
latency budget matters here: **the existing results show flat F1 (0.941)
and flat latency (0.43–0.44s) across all four `qwen3.5` sizes tested
(4b/9b/27b/35b) and all three prompt configs (Standard/Constraint/
Thinking).** That is almost certainly a placeholder/fixture run (identical
F1 to three decimal places across a 4b→35b size range is not a realistic
accuracy curve, and sub-half-second latency for a 35b model is not
plausible for real inference), not a real benchmark of model-size tradeoffs.
This doc treats that CSV as evidence the tooling exists, not as evidence of
the actual latency/accuracy curve — a real experiment run is a prerequisite
before committing to specific thresholds like `escalation_floor`, and is
flagged as the first step of the MVP in Section 4.

### The real constraint: T6's deadline system

The ticket's Notes are explicit that this must interact correctly with
the T6 cancellation/deadline hardening
(`docs/backlog/pre_public_beta_audit_remediation_2026-05-13.md`, T6
section; `src/python/marcut/cancellation.py`). This is the load-bearing
constraint on the whole proposal, for a concrete structural reason:

**T6's deadline today is a single flat budget for the entire processing
phase, not a per-stage budget.** `PythonKitBridge.swift` sets
`MARCUT_PROCESSING_DEADLINE_MONOTONIC` exactly once per run, before
`run_redaction_enhanced()` is invoked (`PythonKitBridge.swift:1247-1249`,
`resolvedProcessingStepTimeout`, default 600s from
`PythonTimeoutOverrides.step(for: "PROCESSING", default: 600.0)`), and
clears it in a `defer` block after processing completes. Every downstream
`check_processing_deadline()` / `remaining_seconds()` call — in
`model.py`, `model_enhanced.py`, `llm_timing.py` — checks against that
*same* absolute deadline. There is currently no concept of "Pass 1 gets N
seconds, Pass 2 gets M seconds" — it's one shared clock, and whichever
stage is running when the clock runs out is the one that raises
`ProcessingDeadlineExceeded`.

**Adding an escalation tier makes this worse, not just "one more thing
that could time out,"** for a specific reason: escalation calls are
*sequential-dependent* on the small-model call's result, not concurrent
with it. Today, `flush_validation()` submits a batch validation call to
the executor and moves on; with escalation, a subset of that batch's
results now trigger a *second* round-trip (small model result received →
decide to escalate → call large model → wait for that result too) before
the entity's final `needs_redaction` is settled. Each escalated entity
effectively pays for two sequential LLM calls instead of one, and the
large model is, by the ticket's own premise, slower per-call than the
small one. Under a shared, already-tight deadline, a document with many
ambiguous (escalation-band) entities could burn a disproportionate share
of the remaining budget on escalation calls, potentially starving later
chunks' extraction or validation of their share of `remaining_seconds()`
— which today would surface as `LLM_CHUNK_FAILED` warnings
(`model_enhanced.py:1072-1077`) or a hard `ProcessingDeadlineExceeded` for
chunks that simply hadn't been scheduled yet, not necessarily related to
the escalation stage itself. That failure would be confusing to debug
because it wouldn't obviously trace back to "too many entities were
ambiguous," it would just look like a generic timeout.

**Recommended budget allocation for the MVP:** do not introduce per-stage
sub-deadlines (that's a bigger change to T6's model and out of scope here)
— instead, bound the escalation tier's *blast radius* within the existing
single shared deadline:

1. **Every escalation call still goes through the existing
   `check_processing_deadline()` / `remaining_seconds()` machinery
   unchanged** — an escalation call that would run past the shared
   deadline is skipped (falls through to the existing retain-by-default
   behavior) rather than attempted. This requires no new deadline
   plumbing, only a guard at the escalation call site identical in shape
   to the guards already present in `flush_validation()`'s `do_validate()`
   closure (`model_enhanced.py:936-939`).
2. **Cap the fraction of a validation batch eligible for escalation** (a
   config value, not a hard-coded constant) so a document that is
   unusually ambiguous end-to-end degrades gracefully — falling back to
   today's retain-by-default behavior for entities beyond the cap — rather
   than a single bad document silently reallocating the entire deadline
   budget to escalation calls at the expense of extraction chunks that
   haven't run yet. This is a simple, auditable circuit breaker, not
   proper budget accounting, and should be labeled as an MVP simplification
   in code comments so it isn't mistaken for a real per-stage scheduler.
3. **Escalation calls share the existing `self.llm_concurrency` executor**
   rather than getting a separate worker pool. A second concurrency knob
   would let the two model tiers compete for Ollama's own request
   concurrency (Ollama serializes or queues requests per loaded model on
   typical single-GPU/CPU dev hardware) in a way that's hard to reason
   about and easy to mis-tune; reusing the existing pool keeps the
   existing `max(1, min(5, requested_concurrency))` bound
   (`model_enhanced.py:829-832`) as the single place total in-flight LLM
   calls are capped.
4. **Model load time is a first-run tax the budget must absorb, not
   ignore.** Switching between two different Ollama models mid-run means
   the *first* escalation call in a session pays Ollama's model-load
   latency (visible today via `ollama_model_load` /
   `payload.get("load_duration")` in `llm_timing.py:77`) — that is not
   negligible if the large model isn't already resident in memory next to
   the small one. Whether both models can be kept warm simultaneously
   depends on available memory on the user's machine, which is exactly
   the kind of hardware-dependent variable that argues for measuring
   actual load/inference time for the target model pair (Section 4) before
   fixing an escalation-floor threshold or a per-call timeout budget.

## 4. MVP Recommendation

**Scope the MVP to Pass 2 (validation) escalation only, behind a flag,
with retention-bias as the terminal fallback everywhere.** Concretely, in
priority order:

1. **Run a real benchmark first**, using the existing
   `scripts/run_qwen_experiment.py` tooling as a starting point (it
   already computes precision/recall/F1 against ground-truth spans and
   captures latency — it just needs to be run for real against a
   representative small/large model pair on this project's actual sample
   documents; the current `experiment_results.csv` cannot be used to pick
   `escalation_floor` or `skip_confidence` values as-is per Section 3).
   This is a prerequisite, not a nice-to-have — every threshold in this
   doc (`escalation_floor`, the escalation-batch cap) is a placeholder
   until real numbers exist.
2. **Add the third confidence band (`escalation_floor`) to
   `ollama_validate_batch()` only** — do not touch Pass 1 extraction, for
   the reasons in Section 2. This is the smallest change that delivers
   the ticket's actual intent (send the LLM's genuinely-ambiguous cases to
   a better model) without requiring new confidence infrastructure.
3. **Reuse everything listed as "reused as-is" in Section 1** — no new
   cache, no new concurrency pool, no change to `needs_validation()`'s
   routing into Pass 2, no change to `skip_confidence`'s meaning (it still
   means "the bar to SKIP," now checked against whichever model produced
   the final confidence value).
4. **New `model_id` for the escalation tier is a required, explicit
   config value with no default** (mirrors how `model_id` for the primary
   pipeline is already required and validated —
   `run_enhanced_model()` raises `ValueError("model_id required for
   Ollama backend")` when absent, `model_enhanced.py:1246-1247`). If the
   escalation model isn't configured, escalation is simply disabled and
   behavior is byte-for-byte identical to today — this keeps the MVP
   strictly additive and opt-in, consistent with this being a design
   spike for a new capability rather than a change to default behavior.
5. **Do not build a third tier, streaming, or cross-run model-warm-keeping
   in the MVP.** Each is a legitimate future direction but adds either
   latency-budget complexity (Section 3) or overlaps with other in-flight
   design work (`docs/design/streaming_progress.md` already scopes
   streaming's own T6 interaction in detail — bolting escalation onto a
   streaming response body at the same time would compound two hard
   problems instead of landing one).
6. **Surface escalation in the audit report**, per the rationale-tagging
   note in Section 2 — this is low-cost (a string field) and directly
   supports the kind of auditability legal users of this tool expect from
   the existing report/warnings/suppressed-entities structure already in
   `IntelligentRedactionPipeline.process_document()`.

This keeps the MVP to one bounded change (a third confidence band in one
function), makes the deadline-safety behavior a strict fallback to
already-shipped, already-tested T6 semantics rather than new timeout
logic, and defers the harder unscoped question (real per-stage deadline
budgeting, if a future iteration needs it) to a follow-up rather than
solving it speculatively here.
