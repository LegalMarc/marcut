# Performance Optimization Guide

This document captures performance profiling data and optimization recommendations for Marcut's LLM-based redaction pipeline.

## Quick Summary

**Bottom Line**: For LLM-enhanced redaction, **token generation is 81% of processing time**. Optimizations should focus on reducing output tokens and using faster models, rather than caching or parallelization alone.

---

## Profiling Tools

Marcut includes built-in timing instrumentation accessible via CLI flags:

### Basic Phase Timing
```bash
marcut redact --in doc.docx --out out.docx --report report.json --timing
```

Shows time spent in each processing phase:
- `DOCX_LOAD` - Document loading and revision acceptance
- `RULES` - Rule-based entity detection
- `LLM` - AI model inference (enhanced mode only)
- `POST_PROCESS` - Boundary snapping, consistency pass, merge
- `DOCX_SAVE` - Track changes, hardening, file write

### Detailed LLM Timing
```bash
marcut redact --in doc.docx --out out.docx --report report.json --llm-detail
```

Breaks down the LLM phase into sub-components:
- `ollama_model_load` - Time loading model into GPU memory
- `ollama_prompt_eval` - Processing input tokens
- `ollama_generation` - Generating output tokens
- `network_overhead` - HTTP latency minus Ollama processing
- `response_parse` - JSON parsing of LLM response
- `entity_locate` - Finding entity positions in document text

---

## Profiling Results

### Test Configuration
- **Model**: qwen2.5:14b (Q4_K_M quantization)
- **Document**: Sample 123 Consent.docx (sample legal document)
- **Hardware**: Apple Silicon Mac
- **Mode**: Enhanced (rules + LLM)

### Phase-Level Breakdown

| Phase | Time | Percentage |
|-------|------|------------|
| DOCX_LOAD | 0.004s | 0.4% |
| RULES | 0.000s | <0.1% |
| **LLM** | **1.091s** | **97.9%** |
| POST_PROCESS | 0.000s | <0.1% |
| DOCX_SAVE | 0.019s | 1.7% |

**Key Finding**: LLM processing dominates at ~98% of total time.

### LLM Sub-Phase Breakdown

| Sub-Phase | Time | Percentage | Notes |
|-----------|------|------------|-------|
| ollama_model_load | 0.059s | 5.4% | Model was warm (already in GPU) |
| ollama_prompt_eval | 0.116s | 10.6% | Processing 458 input tokens |
| **ollama_generation** | **0.883s** | **81.1%** | Generating 56 output tokens |
| network_overhead | 0.007s | 0.6% | HTTP latency |
| response_parse | 0.000s | <0.1% | JSON parsing |
| entity_locate | 0.001s | 0.1% | Finding spans in text |

**Key Finding**: Token generation (81%) is the dominant factor, not model loading or prompt processing.

### Cold Start vs Warm Model

When the model is **not** already loaded in GPU memory:

| Metric | Cold Start | Warm |
|--------|-----------|------|
| Model Load | ~3.0s | ~0.06s |
| Total LLM | ~4.5s | ~1.1s |

First-run latency is 4x higher due to model loading.

---

## Token Statistics

For the test document:
- **Input tokens**: 458 (prompt + document text)
- **Output tokens**: 56 (entity JSON response)
- **Generation speed**: ~63 tokens/sec on Apple Silicon

---

## Optimization Recommendations

Based on profiling data, prioritized by expected impact:

### Tier 1: High Impact, Low Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Shorter prompts** | 10-15% | Low - Reduce system prompt size |
| **Lower `num_predict`** | 5-20% | Low - Cap max output tokens |
| **Smaller model** (3B vs 8B) | 50-70% | Low - Config change |

### Tier 2: Medium Impact, Low Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Cache/dedupe decisions** | 5-20x (repetitive docs) | Medium |
| **Parallelize chunks** | ~1.05-1.25x measured, not 2-4x (see [LLM Request Concurrency](#llm-request-concurrency-issue-53)) | N/A - already implemented, do not invest further here |

### Tier 3: Medium Impact, Medium Risk

| Optimization | Expected Speedup | Implementation Effort |
|--------------|------------------|----------------------|
| **Quantized model** (Q4 vs Q8) | 20-40% | Low - Model swap |
| **Two-pass triage** | Variable | High - Threshold tuning |

---

## Implementation Notes

### Prompt Optimization

Current prompt is ~400 tokens. Potential reductions:
- Remove verbose entity type descriptions
- Use few-shot examples efficiently
- Consider instruction-tuned models that need less prompting

### Output Token Limits

Current `num_predict: 512` is generous. Consider:
- Reducing to 256 for typical documents
- Implementing streaming to detect early completion

### Model Selection Trade-offs

| Model | Speed | Accuracy | Size |
|-------|-------|----------|------|
| llama3.2:1b | Fastest | Acceptable | 1.3GB |
| llama3.2:3b | Fast | Good | 2.0GB |
| qwen2.5:14b | Moderate | Best | 4.9GB |

For most legal documents, 3B provides good accuracy/speed balance.

### Caching Strategy

Hash key should include:
- Normalized text (stripped whitespace)
- Model identifier
- Prompt version hash

Invalidation: Clear cache when model or prompt changes.

---

## Monitoring

For ongoing performance monitoring:

```python
# Enable timing in Python code
from marcut.pipeline import run_redaction

exit_code, timings = run_redaction(
    input_path="doc.docx",
    output_path="out.docx",
    report_path="report.json",
    mode="enhanced",
    model_id="qwen2.5:14b",
    timing=True,
    llm_detail=True,
    # ... other params
)

# Access timing data
print(f"LLM time: {timings['LLM']:.2f}s")
if 'llm_timing' in timings:
    print(f"Generation: {timings['llm_timing']['ollama_generation']:.2f}s")
```

---

## Large-Document Consistency-Pass Budgets (T10 Remediation)

The `POST_PROCESS` phase includes a "consistency pass" (`_apply_consistency_pass` in `src/python/marcut/pipeline.py`) that rescans the full document text for additional exact/fuzzy matches of entities already found by rules/LLM (e.g. a name found once gets consistently redacted everywhere it recurs). On documents with thousands of unique ORG/PERSON candidates, the naive version of this pass can degrade badly: building huge alternation regexes and running per-candidate fuzzy matching against every ORG candidate is O(candidates) or worse against document length.

Three environment variables bound this work so a single pathological document can't turn `POST_PROCESS` into the new bottleneck:

| Env Var | Default | Effect |
|---------|---------|--------|
| `MARCUT_CONSISTENCY_MAX_CANDIDATES` | 1,500 | Caps the total number of candidate spans (across all safe labels: ORG, PERSON, NAME, EMAIL, SSN, PHONE, ACCOUNT, CARD, BRAND) collected for the consistency rescan. Once reached, remaining spans are skipped for consistency purposes (they keep whatever redaction they already have from rules/LLM - this only limits *additional* consistency-pass matches). |
| `MARCUT_CONSISTENCY_MAX_FUZZY_ORG_CANDIDATES` | 250 | Caps how many ORG candidates go through the expensive per-candidate fuzzy/token-based scan (step 3 of the pass, needed to catch reworded/partial company names). Exact and case-insensitive regex matching (steps 1-2) still runs for all collected candidates; only the fuzzy fallback is capped. |
| `MARCUT_CONSISTENCY_MAX_PATTERN_CHARS` | 120,000 chars | Caps the total escaped-pattern length used when building the case-insensitive alternation regex, so an enormous number of distinct candidate strings can't produce a regex so large it stalls the regex engine. Once the budget is hit, remaining candidates are excluded from that regex pass. |

All three are read via the same bounded-int helper as the metadata size budgets in `docs/METADATA_HARDENING.md` (a limit of `0` disables that particular cap), and each one logs a one-line notice when `--debug` is enabled and the limit is actually hit (e.g. `Consistency Pass: Candidate limit reached (1500); skipping remaining candidates.`), so a slow run can be diagnosed from `--debug` output rather than silent truncation.

These budgets only affect the consistency-pass *rescan* - they never remove or weaken a redaction that rules or the LLM already produced directly; they only bound how much extra rescanning work is done to catch additional occurrences of already-found entities.

## LLM Request Concurrency (Issue #53)

**Origin**: hardening review 2026-07-05 flagged that `IntelligentRedactionPipeline.process_document`
(`src/python/marcut/model_enhanced.py`) submits chunk extraction through a
`ThreadPoolExecutor` (`self.llm_concurrency`, default 2, clamped to `[1, 5]`), but Ollama
serializes inference per model unless `OLLAMA_NUM_PARALLEL` is raised — so the client-side
pool could be purely cosmetic (same wall-clock, just queued requests).

### 1. What the embedded Ollama is launched with today

Neither the Python launcher (`ollama_manager.py::start_service`) nor the Swift launcher
(`PythonBridge.swift::getOllamaEnvironment`) sets `OLLAMA_NUM_PARALLEL`. `PythonBridge.swift`
does explicitly set `OLLAMA_MAX_LOADED_MODELS=1` "to reduce memory pressure." With
`OLLAMA_NUM_PARALLEL` unset, current Ollama (0.24.0, the version available for this
investigation) auto-resolves its parallel-slot count from local hardware/memory - on the
machine used for this benchmark (Apple M3 Max, 64GB RAM) it resolved to **1** (confirmed via
the `"server config"` log line printed by `ollama serve` on startup:
`OLLAMA_NUM_PARALLEL:1`). So today, out of the box, Ollama itself already serializes
inference for a given model - independent of anything Marcut sets.

### 2. Benchmark: client concurrency x `OLLAMA_NUM_PARALLEL`

**Method**: A private, isolated `ollama serve` instance was started on `127.0.0.1:11500`
(separate `OLLAMA_HOME`, read-only pointed at an already-populated model store) so this
never touched the developer's own always-on Ollama service. A synthetic 51-chunk
legal-style document (~80k chars, chunked with the pipeline's real default settings:
`max_len=2000`, `overlap=400`) was run chunk-by-chunk through the *actual* production
call path (`marcut.model.ollama_extract`), driven by a `ThreadPoolExecutor` at client
concurrency 1 and 4, for each of `OLLAMA_NUM_PARALLEL` unset (default), `2`, and `4`.
`OLLAMA_MAX_LOADED_MODELS=1` was kept to mirror the shipped Swift setting.

Model: `llama3.2:3b` (Q4_K_M) - substituted for the production-recommended `qwen2.5:14b`
purely so iteration fit the investigation's time budget; the parallelization behavior
being measured (server request scheduling) is a property of the Ollama runtime, not of
which model is loaded. Peak RSS is the whole `ollama serve` process tree, sampled every
0.5s, starting after model warm-up (so warm-up's cold-load allocation doesn't pollute the
figure).

| `OLLAMA_NUM_PARALLEL` | client concurrency=1 | client concurrency=4 | speedup | peak RSS |
|---|---|---|---|---|
| unset (resolves to 1) | 178.0s | 142.1s | 1.25x | 3.9 GB |
| 2 | 176.7s | 170.4s | 1.04x | 5.3 GB |
| 4 | 159.4s | 150.7s | 1.06x | 8.2 GB |

**Findings**:
- Raising `OLLAMA_NUM_PARALLEL` did **not** produce a meaningful additional wall-clock win
  over the already-serialized default - concurrency=4 wall-clock stayed in a tight 142-170s
  band regardless of whether the server had 1, 2, or 4 parallel slots available. This is
  consistent with a single Apple Silicon GPU/ANE being compute-bound on token generation:
  extra parallel *slots* let the runner batch multiple in-flight requests, but aggregate
  throughput is capped by the one accelerator, so batching buys a little (better slot
  utilization) but nowhere near linear scaling.
- The ~25% win at concurrency=4 with the *default* (1 parallel slot) setting is
  real but comes from the **client-side** pool, not server parallelism: keeping the request
  queue full removes Python-thread/HTTP round-trip idle gaps between sequential requests.
  That's the `ThreadPoolExecutor`'s actual, legitimate contribution - it is not purely
  cosmetic, but its ceiling is dispatch-latency hiding, not parallel inference.
  Interestingly this benefit did not compound with an actually-enabled `OLLAMA_NUM_PARALLEL`
  (4 slots gave 150.7s vs. the default's 142.1s at the same client concurrency) - noise on a
  shared dev machine is a plausible confound (see Caveats), but there is no evidence that
  raising `OLLAMA_NUM_PARALLEL` beats simply queuing client-side.
- Memory scales close to linearly with parallel slots for a fixed context length
  (`num_ctx=12288` here, matching `model.py::ollama_extract`): roughly +1.5-1.7 GB of KV
  cache per additional slot for this 3B model. Extrapolated to the production default
  `qwen2.5:14b` (~5x the parameters, larger hidden dimension), the per-slot KV cache cost
  would be substantially larger - plausibly several GB per slot - which is a real risk on
  8-16GB Macs, the exact machines this concern was raised for. (Not measured directly with
  qwen2.5:14b - extrapolated from the measured 3B-model scaling - flagged here rather than
  asserted as fact.)

**Caveats** (why these are directional, not lab-grade):
- Single-shot runs per configuration (no repeated trials/averaging) on a shared development
  machine that also had an unrelated, always-on personal Ollama service resident in memory
  the whole time; the 159-178s spread across nominally-equivalent concurrency=1 baselines
  illustrates the noise floor.
- 3B stand-in model, not the shipped `qwen2.5:14b` default, and 64GB-RAM test hardware, not
  a representative low-memory Mac.

### 3. Validation buffer batching (`to_validate_buffer`)

Confirmed by code inspection (`model_enhanced.py` `flush_validation`, ~line 1032): the
buffer is checked for a flush after **every** completed chunk (called from inside
`process_single_chunk`, itself serialized per-chunk by `result_lock`), and flushes
everything currently buffered once it holds >= 20 items (or when `force=True` at the end
of the document). Because the check runs after each individual chunk rather than only at
the end, the buffer cannot grow past roughly "20 + one chunk's worth of validation
candidates" before being flushed (and dispatched asynchronously via the same executor) -
it does not balloon across an entire entity-dense document. It's not a hard-capped batch
size (a single unusually entity-dense chunk could still push one flush above 20+n), but
growth is bounded per-chunk, not accumulated document-wide, matching the intent.

### 4. Decision

**No configuration change ships.** The data does not show a wall-clock win from raising
`OLLAMA_NUM_PARALLEL` on Apple Silicon that would justify its measured, roughly-linear
memory cost - the opposite of what a low-memory-Mac-constrained app wants to trade into.
The existing client-side `ThreadPoolExecutor` (`llm_concurrency`, default 2) is retained
as-is: it provides a real, if modest, dispatch-latency-hiding benefit independent of server
parallelism, and does not by itself increase Ollama's memory footprint (no extra parallel
slots are requested by the client - Ollama still runs `OLLAMA_NUM_PARALLEL` slots
regardless of how many concurrent HTTP requests are queued against it).

**Suggested follow-up (not implemented here)**: pin `OLLAMA_NUM_PARALLEL=1` explicitly in
both `ollama_manager.py::start_service` and `PythonBridge.swift::getOllamaEnvironment`
rather than relying on Ollama's implicit auto-detection, so future Ollama versions or
higher-memory Macs can't silently auto-select a higher slot count (and therefore a larger,
unbudgeted memory footprint) than what was benchmarked here. This is a small, low-risk
change but was left out of this investigation since it has no measured "win" attached to
it (the whole point of this issue was to decide whether to *increase* parallelism) and
touches both the Python and Swift launch paths.

## Related Files

- [`src/python/marcut/llm_timing.py`](../src/python/marcut/llm_timing.py) - LLM timing instrumentation
- [`src/python/marcut/cli.py`](../src/python/marcut/cli.py) - CLI flag handling
- [`src/python/marcut/pipeline.py`](../src/python/marcut/pipeline.py) - Main processing pipeline
- [`src/python/marcut/model.py`](../src/python/marcut/model.py) - Ollama integration

---

*Last updated: July 2026*
