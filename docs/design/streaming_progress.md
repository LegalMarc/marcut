# Design Spike: Streaming LLM Progress from Python to Swift for a Fractional Progress Bar

Status: Design spike (no code changes). Companion to issue #23.

## Goal

Today the progress bar advances at three granularities layered on top of each
other: whole-phase jumps, whole-chunk jumps, and a client-side "fake it"
animation that fills the gaps. The actual LLM generation call inside a chunk
is a black box from the moment the HTTP request is sent until Ollama returns
the full response — the UI has no signal for what's happening during that
window, which is normally the single largest contributor to wall-clock time.
This doc proposes closing that last gap with token-level progress from
Ollama's streaming API, and is explicit about how the proposal must coexist
with the T6 cancellation/deadline hardening that just landed on this branch.

## Current State

### What granularity already exists

The premise that progress is *purely* phase-jumping is only partly true.
Reading the current implementation top to bottom:

1. **Phase-level** — `marcut.progress.ProgressTracker` (`src/python/marcut/progress.py`)
   assigns each `ProcessingPhase` (`PREFLIGHT`, `RULE_DETECTION`,
   `DOCUMENT_ANALYSIS`, `LLM_EXTRACTION`, `VALIDATION`, `MERGING`,
   `TRACK_CHANGES`, `COMPLETE`) a weight derived from
   `TimeEstimator.estimate_phase_duration()`, which is seeded by a rough
   document-complexity heuristic (`estimate_document_complexity()`). Calling
   `tracker.update_phase(phase, progress, message)` produces an
   `overall_progress` in `[0, 1]` that's a weighted blend of "phases fully
   done" plus "fractional progress within the current phase." This is called
   from `pipeline.py` at each phase boundary (e.g.
   `pipeline.py:1571` constructs the tracker; `model_enhanced.py:1199`
   calls `tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 1.0, ...)`
   when extraction finishes).

2. **Chunk-level, within `LLM_EXTRACTION`** —
   `IntelligentRedactionPipeline.process_document()` in
   `model_enhanced.py` (the class backing the enhanced/two-pass pipeline)
   dispatches each chunk to a `ThreadPoolExecutor` and, as each
   `process_single_chunk()` future completes, updates a shared `current_chunk`
   counter under `result_lock` and calls
   `tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, chunk_progress, ...)`
   (`model_enhanced.py:1068-1070`), where `chunk_progress = current_chunk /
   total_chunks`. So progress *does* move chunk-by-chunk, not just
   phase-by-phase — but a chunk only reports progress when it *finishes*.
   While a chunk's `ollama_extract()` HTTP call is in flight, nothing moves.

3. **A parallel "mass" (character-count) protocol** — `emit_mass_event()`
   (`model_enhanced.py:852`) emits JSON payloads (`mass_total`, `chunk_start`,
   `chunk_end`, `keepalive`) either through the rich `tracker` path or, if the
   caller's callback doesn't match the rich signature, by calling
   `progress_callback(0, 0, json_string)` and letting the Swift side parse
   the JSON out of the message field. `DocumentModels.swift`'s
   `ingestProgressPayload()` (`DocumentModels.swift:442`) parses these events
   and does its own character-mass-based fractional estimate
   (`isMassTrackingActive`, `updateMassBasedEstimate`) so the bar can creep
   forward proportionally to how many characters' worth of chunks have
   started/ended, independent of chunk count. This is a second, overlapping
   progress channel already doing character-granularity, not token-granularity.

4. **A live keepalive heartbeat** — a daemon thread
   (`send_keepalive()`, `model_enhanced.py:986-1026`) fires every 3s while
   any progress callback is registered, emitting a "still running, Ns
   elapsed" status message via `emit_mass_event()`. This is a liveness signal,
   not a progress signal — it tells the UI the process hasn't hung, but
   carries no information about how close the current chunk is to finishing.

5. **Client-side animation on top of all of the above** —
   `DocumentModels.swift` never simply displays whatever fraction Python
   reports. `applyStageProgressFraction()` / `setExplicitProgress()`
   (`DocumentModels.swift:195-211`) set a `targetProgress`, and a 60fps timer
   (`startMomentumAnimation()`/`startSmoothAnimation()`,
   `DocumentModels.swift:257-335`) eases the visible `progress` toward that
   target with velocity/easing curves, plus a `startMicroProgress()` ticker
   (`DocumentModels.swift:339-372`) that creeps the bar forward on its own
   between real updates so it never looks frozen. This is deliberately
   compensating for exactly the gap this spike is about: there's a long dead
   zone (one Ollama call) with no real signal, so the client fabricates
   motion.

### The actual gap

The bridge mechanism itself is *not* file-polling — it's a direct callback
registered through PythonKit. `PythonKitBridge.swift`'s
`runEnhancedOllama()` builds a `PythonFunction` (`PythonKitBridge.swift:1267-1305`)
and passes it to `pipeline.run_redaction(..., progress_callback:
progressCallback)`. Every Python-side `progress_callback(...)` invocation
crosses straight into Swift synchronously, on the single dedicated
`PythonWorkerThread` (`PythonKitBridge.swift:249-309`, `perform()`), and the
result is forwarded into an `AsyncStream` (`heartbeat` closure,
`PythonKitBridge.swift:1426-1432`) that `DocumentRedactionViewModel.swift`
consumes on a detached `Task` (`applyPythonKitProgress`, around
`DocumentRedactionViewModel.swift:2521-2557`). So the boundary-crossing
mechanism this ticket asks about ("a callback registered through PythonKit")
already exists and already works for phase/chunk/mass granularity.

What's missing is a signal *inside* a single chunk's LLM call. Both
`ollama_extract()` (`model.py:585`) and `ollama_extract_with_timing()`
(`llm_timing.py:21`) call Ollama's `/api/generate` with `"stream": False`,
explicitly commented `# CRITICAL: Disable streaming to get single JSON
response` (`model.py:613`). That means: the HTTP call blocks until Ollama has
generated the *entire* response, and nothing progress-related happens for
the whole duration of prompt eval + token generation for that chunk — this
is precisely the black box the client-side momentum/micro-progress code is
built to paper over.

## Proposed Mechanism

Three options, in increasing order of change and payoff.

### Option A — Shared state file polling

Python writes progress state (chunk index, phase, tokens generated so far)
to a JSON file under a per-run temp directory; Swift polls it on a timer.

- **Latency**: bounded by poll interval (e.g. 250ms–1s); adds a full extra
  hop vs. the existing direct callback.
- **Complexity**: low to add, but it's a *second* progress channel alongside
  the PythonKit callback that already exists — two mechanisms to keep in
  sync, two failure modes.
- **Failure modes**: file write races, stale reads if the poll fires between
  write and rename, orphaned files if the phase changes take control paths (
  Actually, other progress signals could go stale if a step throws before it
  writes) needs an atomic write (write-tmp + rename) to avoid partial reads.
- **Verdict**: strictly worse than the existing PythonKit callback for this
  codebase — we already pay the cost of a direct in-process callback with
  zero serialization/IPC overhead. Reintroducing polling with a file would
  be a regression in both latency and architecture cleanliness. Rejected.

### Option B — Ollama's native streaming API (`stream: true`), token deltas surfaced through the existing PythonKit callback

Flip `stream: False` to `stream: True` on the `/api/generate` call inside
`ollama_extract()` / `ollama_extract_with_timing()`. Ollama then returns a
sequence of newline-delimited JSON chunks, each with a `response` delta and
a final `done: true` object carrying the same `eval_count` /
`prompt_eval_count` / `eval_duration` totals already captured today in
`llm_timing.py:75-82`. Iterate `resp.iter_lines()` inside `_request()`,
accumulate the `response` text, and call a new intra-chunk progress hook —
reusing the *existing* `emit_mass_event()` / `tracker.update_phase()` path,
not a new channel — approximately every N tokens or every M milliseconds,
using `eval_count` so far vs. `num_predict` (the request's own output-token
cap, already read from `MARCUT_OLLAMA_NUM_PREDICT`, `model.py:598`) as the
fractional-progress denominator for that chunk.

- **Latency**: near-zero — same in-process callback boundary that already
  exists, just invoked more often, from inside the token loop instead of
  once at HTTP-call completion.
- **Complexity**: moderate. `stream: True` changes response parsing (NDJSON
  instead of one JSON object) in exactly two call sites (`model.py`,
  `llm_timing.py`), both of which already have a single `_request()` /
  inline `requests.post()` chokepoint, so the blast radius is contained.
  `parse_llm_response()` / entity-span logic downstream is unaffected — it
  still operates on the fully-accumulated `response` text once the stream's
  `done: true` line arrives.
  Structured-output mode (`format: json` / `format_schema`, used by
  `ollama_extract_with_timing` when `format_schema` is passed,
  `llm_timing.py:59-60`) is compatible with `stream: True` in Ollama, so
  the two features don't conflict.
- **Failure modes**: a dropped/truncated stream (connection reset mid-generation)
  needs to be handled distinctly from today's single-shot request failure —
  today a `requests.exceptions.RequestException` cleanly fails the whole
  call; with streaming, a partial `response` accumulated before a mid-stream
  drop must be discarded rather than treated as a valid (truncated) LLM
  answer, or the existing self-correction retry (`model.py`'s "single
  self-correction retry on malformed JSON") will get inconsistent input.
  Needs an explicit "stream ended without `done: true`" error path that maps
  to the same retry logic already used for malformed JSON, not a new one.
- **Verdict**: recommended direction. It reuses the mechanism that's already
  proven (PythonKit callback → AsyncStream → `DocumentModels.swift`
  animation layer) and only changes *how often* and *from where* Python
  calls it, which keeps the Swift side essentially untouched — the existing
  `applyStageProgressFraction()` consumer doesn't care whether the fraction
  moved because a chunk finished or because 40% of its tokens streamed in.

### Option C — Full duplex streaming with mid-generation cancellation

Same as Option B, but additionally use the token-level checkpoint to allow
*aborting* a single in-flight generation early (closing the HTTP connection)
rather than waiting for the whole response, layering token-granularity
directly into the cancellation path itself rather than keeping it purely
additive to progress reporting.

- **Latency / responsiveness**: best possible — cancellation could act
  within one token-emission interval instead of waiting for
  `check_processing_deadline()` to be reached at the next chunk/request
  boundary.
- **Complexity**: high, and it means the progress feature and the
  cancellation feature stop being independent — a bug in the streaming loop
  now risks the deadline-hardening guarantees T6 just established, not just
  a cosmetic progress-bar stall.
- **Verdict**: deferred. The marginal responsiveness gain over Option B
  (which still checks the deadline at each streamed-token callback, see
  below — it doesn't need connection-abort to be *fast*, just to be
  *correct*) is not worth coupling two features whose current separation of
  concerns is exactly what made T6 tractable to land and verify in isolation.
  Worth revisiting once Option B has shipped and the streaming code path is
  trusted.

**Recommendation: Option B.**

## Cancellation / Deadline Interaction (T6)

This is the load-bearing constraint on this whole proposal, per the ticket.
The T6 work (`src/python/marcut/cancellation.py`;
`731fc605`, `b0699afb`, `c5ce474e`, plus the `model_enhanced.py`/`model.py`/
`llm_timing.py` wiring) established these invariants, and Option B must
preserve every one of them:

1. **`MARCUT_PROCESSING_DEADLINE_MONOTONIC` is checked before each network
   round-trip, and the HTTP timeout itself is bounded to the remaining
   budget** (`check_processing_deadline()` + `timeout=remaining_seconds(...)`
   at `model.py:606,622` and `llm_timing.py:54,65`). A streaming
   `requests.post(..., stream=True)` call still has exactly one
   `remaining_seconds(request_timeout)` value passed as the connect/read
   timeout at the *start* of the call — but with `stream=False` that timeout
   bounds "time to receive the entire response," whereas with `stream=True`,
   `requests`' timeout applies per socket read, not to the whole streamed
   duration. That's actually an *improvement* for deadline enforcement (today
   a slow-but-not-hung generation could run right up to the full
   `request_timeout` with zero visibility; streamed reads let us check
   `check_processing_deadline()` between chunks) but it must be done
   deliberately: **the token-iteration loop itself needs its own
   `check_processing_deadline()` call on every N-th streamed line**, not just
   once before the request is opened. Otherwise a long generation could
   silently run past the deadline between the initial check and the (now
   effectively unbounded, since `iter_lines()` has no aggregate deadline)
   final chunk — this would be a *regression* versus today's behavior, where
   the single `timeout=` kwarg at least bounds worst-case wall time. The
   concrete requirement: call `check_processing_deadline()` inside the
   `for line in resp.iter_lines():` loop (e.g. every line, since NDJSON
   lines arrive at token-batch granularity, not per-token), and additionally
   pass a per-read timeout via `remaining_seconds()` re-evaluated per
   iteration (or a slightly-relaxed fixed per-line timeout, since `requests`
   doesn't cleanly support a rolling deadline on `iter_lines()` — needs a
   spike of its own, flagged below) so a connection that goes silent
   mid-stream is still caught.

2. **Cancellation must not emit progress after cancel.** T6's remediation
   notes explicitly call out: *"Deadline cancellation sets an internal
   worker cancellation event, avoids post-cancel progress emission..."*
   (`pre_public_beta_audit_remediation_2026-05-13.md` T6 section). Today
   `process_single_chunk()` checks `cancel_event.is_set()` before and after
   the (blocking) `ollama_extract()` call (`model_enhanced.py:1038-1050`).
   With streaming, the loop needs the *same* check on every iteration of the
   token-consumption loop — if `cancel_event` fires mid-stream, the
   in-flight streamed request must stop emitting progress callbacks
   immediately (not just at the next chunk boundary) and the partial
   response must be discarded rather than fed into `parse_llm_response()`.
   Concretely: `_request()` (or its streaming replacement) needs a
   `cancel_event` parameter (currently `process_single_chunk` has it in
   closure scope but `ollama_extract()` in `model.py` does not take
   `cancel_event` at all — it only checks the module-level
   `MARCUT_PROCESSING_DEADLINE_MONOTONIC` env var via
   `check_processing_deadline()`). This is a real gap to close: the deadline
   check catches *expiry*, but `cancel_event` (user-initiated Stop) is
   currently only checked by the caller (`process_single_chunk`), not deep
   inside the HTTP call. For a long single-chunk generation with streaming,
   that means a user-initiated Stop wouldn't interrupt token consumption any
   faster than it does today (still bounded by request timeout) unless we
   either (a) thread `cancel_event` down into the streaming loop so it can
   break out and close the connection, or (b) accept that Stop
   responsiveness for a single streaming call is unchanged from today and
   rely on the deadline/interrupt mechanism (`PyErr_SetInterrupt()` from
   `PythonKitBridge.swift`'s stop handling, `c5ce474e`) to unwind the thread.
   Given KeyboardInterrupt via `PyErr_SetInterrupt()` already propagates
   into whatever Python bytecode is executing (including inside
   `requests`/`urllib3` read loops), (b) is likely sufficient and no new
   plumbing is strictly required — but this needs to be verified with a
   targeted test (hanging streaming mock + Stop) before shipping, mirroring
   the existing `test_intelligent_pipeline_deadline_interrupts_hanging_extraction`
   coverage in `tests/test_model_enhanced.py`.

3. **Non-blocking executor shutdown must still hold.** `finally:
   executor.shutdown(wait=False, cancel_futures=True)`
   (`model_enhanced.py:1192`) must continue to return immediately on
   cancellation. Streaming doesn't change this — an in-flight streaming
   `requests.post` inside a worker thread is not force-killable by
   `cancel_futures=True` any more than a blocking one is (Python threads
   can't be killed from outside); the thread will run to completion or to
   its own exception/interrupt regardless. This is already true today for
   the non-streaming call, so streaming introduces no new regression here —
   just worth stating explicitly since it's easy to assume streaming
   ends this problem. It doesn't; only interrupt-based unwinding
   (`PyErr_SetInterrupt`) or the request's own timeout ends a truly stuck
   worker thread either way.

4. **Timeout failure classification must still say "timeout."**
   `pipeline.py`'s error classification matches `"timeout" in error_str or
   "deadline" in error_str` to produce `AI_PROCESSING_TIMEOUT`
   (`pipeline.py:1883-1886`). A streaming-specific failure (e.g. "stream
   ended without done:true", a `ChunkedEncodingError` from `requests` on a
   dropped connection) must still surface an error string containing
   "timeout" or "deadline" when it's deadline-driven, or route through the
   *existing* `ProcessingDeadlineExceeded` exception type rather than
   inventing a new exception class that this classifier doesn't recognize.
   Concretely: any new streaming-only exception type should either subclass
   `ProcessingDeadlineExceeded` when it's deadline-caused, or be caught and
   re-raised as one, so it doesn't silently fall through to the generic
   "processing error" bucket and confuse users about what happened.

5. **No new progress channel, no new env var.** All of the above should ride
   on the *existing* `MARCUT_PROCESSING_DEADLINE_MONOTONIC` /
   `check_processing_deadline()` / `remaining_seconds()` primitives from
   `cancellation.py`, and the *existing* `progress_callback` /
   `emit_mass_event()` plumbing. Introducing a second deadline mechanism or
   a second progress-callback shape (beyond the streaming-frequency change)
   would fragment the surface T6 just consolidated and double the code paths
   future cancellation work has to reason about.

## MVP Recommendation

**Build first (Option B, minimal slice):**

1. Add `stream: bool = False` parameter to the internal `_request()` helper
   in `model.py` (default `False`, so all existing callers/tests are
   unaffected) and a parallel change in `llm_timing.py`. Only
   `IntelligentRedactionPipeline`'s per-chunk extraction call opts into
   `stream=True`; the validation/classification calls
   (`model_enhanced.py:543,786`, which return small yes/no-shaped responses
   where sub-second latency makes streaming pointless) stay non-streaming.
2. Inside the streaming branch, iterate NDJSON lines, accumulate `response`
   text, call `check_processing_deadline()` and check `cancel_event` (a new
   parameter threaded down from `process_single_chunk`) every line, and
   invoke a new optional `on_token_progress(chars_so_far, eval_count_so_far)`
   callback that `process_single_chunk` wires to a *finer-grained* call into
   the existing `emit_mass_event()` — e.g. treat it as intra-chunk mass
   progress within the chunk's already-known character budget, so it's
   additive to the existing `mass_total`/`chunk_start`/`chunk_end` protocol
   rather than a new one.
3. On the final NDJSON line (`done: true`), extract the same
   `eval_count`/`prompt_eval_count`/durations already parsed in
   `llm_timing.py:75-82` so timing telemetry is preserved unchanged.
4. Add a test mirroring
   `test_intelligent_pipeline_deadline_interrupts_hanging_extraction`
   (`tests/test_model_enhanced.py`, from the T5/T6 test commit) but using a
   fake streaming response that yields a few NDJSON lines then hangs, to
   prove the deadline check inside the streaming loop actually fires instead
   of waiting for the whole (now potentially unbounded) response.
5. No Swift changes required for the MVP — the existing
   `progressCallback` PythonFunction bridge and
   `applyStageProgressFraction()` consumer already handle arbitrary-frequency
   fractional updates. Verify empirically that the existing momentum/easing
   animation in `DocumentModels.swift` looks reasonable at the new update
   frequency (likely need to rate-limit the Python-side callback, e.g. every
   250ms or every K tokens, so we don't flood the AsyncStream / MainActor
   with an update per NDJSON line for fast models).

**Explicitly deferred:**

- Option C (streaming-driven mid-generation connection abort for faster
  Stop responsiveness) — revisit after Option B has real production mileage
  and the streaming code path itself is trusted.
- Any new Swift-side visualization of "tokens/sec" or model-generation
  telemetry in the UI — the MVP only needs the fraction to move smoothly;
  surfacing raw token throughput as user-facing text is a separate, smaller
  follow-up once the data is flowing.
- Rolling per-line deadline enforcement inside `iter_lines()` beyond the
  per-line `check_processing_deadline()` call — if a connection goes
  perfectly silent (no bytes, not even a keepalive newline) mid-stream,
  `requests`' timeout as currently configured is a single value evaluated at
  request start, not a true rolling idle-timeout. Whether that's sufficient
  or needs `stream=True` combined with a lower per-socket-read timeout is a
  small follow-on spike, not part of this MVP.
- Streaming for the validation/classification Ollama calls — not worth it
  given their response sizes are small and latency is already low.
