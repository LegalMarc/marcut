# Design Spike: Replacing Unstructured JSON State on the Swift-Python Bridge

Status: Design spike (no code changes). Companion to issue #26. Addresses the
`backlog.md` tech-debt note: *"Fragile Swift-to-Python Bridge: Transition away
from parsing unstructured JSON state files to a stricter schema like
Protobuf, FlatBuffers, or strict OpenAPI JSON specs."*

## Goal

The Swift side and the Python side of Marcut agree on message shapes today
purely by convention: a Python function returns a tuple whose position N
means one thing, or a dict whose keys are read with `as? String` and a
silent fallback string if the key is missing or the wrong type. Nothing
enforces that the two sides agree, so a rename or reorder on the Python side
is a silent runtime bug on the Swift side, not a build error. This doc
inventories every such shape actually in the codebase today, compares
Protobuf/FlatBuffers/OpenAPI-style schema validation as replacements, and
proposes a migration plan that is explicit about how it interacts with the
T6 cancellation/deadline system and the T7 transactional-artifact-write
system, both of which communicate their own state across this same bridge.

## Current State Inventory

The bridge is **not** file-polling IPC — `PythonKitBridge.swift` embeds
CPython in-process via PythonKit and calls Python functions directly on a
dedicated worker thread (`PythonWorkerThread`, `PythonKitBridge.swift:249-309`).
There is no serialization boundary in the traditional sense (no socket, no
pipe) — but there *is* still an untyped-data boundary, because PythonKit
objects are dynamically typed (`PythonObject`) and every value crossing from
Python into Swift is manually downcast with `as?`/`Bool(...)`/`Int(...)`/
`String(...)`, all of which silently produce `nil`/`false`/wrong-shape data
on mismatch rather than failing loudly. Four distinct shapes exist:

### 1. Env-var JSON blobs (Swift → Python, in)

Swift sets process-wide environment variables that Python parses as JSON or
CLI-arg strings before each call:

- `MARCUT_METADATA_SETTINGS_JSON` — a JSON object read by
  `MetadataCleaningSettings.from_environment()` (`docx_io.py:302-310`), which
  does `json.loads(raw_json)` inside a bare `except Exception: decoded = None`
  and then only applies it `if isinstance(decoded, dict)` — a malformed or
  differently-shaped payload is silently dropped, not rejected.
- `MARCUT_METADATA_ARGS` — a space-separated CLI-arg string (not JSON) parsed
  by the same settings class via `metadata_args_str.split()`
  (`pipeline.py:1367,4033,4137`), read independently in three call sites
  (`run_redaction`, `scrub_metadata_only`, `metadata_report_only`) with no
  shared decode helper.
- `MARCUT_PROCESSING_DEADLINE_MONOTONIC` — a single float-as-string consumed
  by `cancellation.py`'s `processing_deadline()` (`cancellation.py:12-20`).
  This one is simple by construction (single scalar) and is exactly the T6
  primitive called out below.
- `PythonKitBridge.swift:730-732` maintains the list of env vars it clears/
  sets before each run (`"MARCUT_METADATA_ARGS"`, `"MARCUT_METADATA_SETTINGS_JSON"`,
  plus the deadline var) — the list itself is the only place that documents
  which env vars are part of the bridge's "API surface," and nothing
  verifies Python doesn't silently start reading a new one without Swift
  being told to set it.

### 2. Progress callback payloads (Python → Swift, in-process, per-call)

Progress crosses the bridge as a live Python-to-Swift function call, not a
file. `PythonKitBridge.swift:1267-1305` builds a `PythonFunction` closure and
branches on `args.count` to decide which of *two incompatible shapes* it
received:

- **Rich shape**: a single `ProgressUpdate` dataclass instance
  (`progress.py:113-122`: `phase`, `phase_progress`, `overall_progress`,
  `phase_name`, `estimated_remaining`, `elapsed_time`, `message`). Swift reads
  each attribute off the `PythonObject` by name (`update.phase`,
  `update.overall_progress`, ...) with no compile-time or runtime check that
  the Python object actually is a `ProgressUpdate` — any Python object with
  matching attribute names would be silently accepted, and a typo'd
  attribute name is read as `Python.None` and coerced away rather than
  raising.
- **Simple shape**: a positional `(chunk: int, total: int, message: str)`
  tuple, used as a fallback path when `ProgressTracker.__init__` detects (via
  `inspect.signature`) that the callback takes three parameters instead of
  one (`progress.py:128-144`). Which shape gets sent is decided at runtime by
  Python introspecting the *Swift* closure's declared arity
  (`PythonKitBridge.swift`'s closure is variadic, so it always presents as
  matching whichever branch), which is itself a fragile way to pick a wire
  format.
- **A third, overlapping channel layered on top of both**: `emit_mass_event()`
  (`model_enhanced.py:852-872`) `json.dumps()`s an ad-hoc dict
  (`{"type": "mass_total", "value": ...}`, `{"type": "chunk_start", ...}`,
  `{"type": "chunk_end", ...}`, `{"type": "keepalive", ...}` — see
  `model_enhanced.py:899,997,1079,1141,1150`) and stuffs the JSON string into
  whichever channel is available: `tracker.update_phase(..., message=json_string)`
  if a rich tracker exists, or `progress_callback(0, 0, json_string)` via the
  simple-shape path otherwise, with a nested `try/except TypeError` fallback
  to `progress_callback(0, 0)` with no message at all if even *that* arity is
  wrong (`model_enhanced.py:858-865`). So a single logical event (e.g.
  "chunk 3 of 10 finished") can arrive at Swift three different ways
  depending on which callback shape was negotiated, and the JSON-in-a-string
  is invisible to the two typed fields (`chunk`, `total`) that exist right
  next to it in `PythonRunnerProgressUpdate` (`PythonKitBridge.swift:6-13`).

### 3. Return-tuple results (Python → Swift, in-process, per-call)

Every pipeline entry point returns a Python tuple whose *position* is the
only contract:

- `run_redaction()` / `run_redaction_enhanced()` return
  `Tuple[int, Dict[str, float]]` (exit code, phase timings) — Swift reads it
  positionally: `if Bool(Python.isinstance(rawResult, Python.tuple)) ... return Int(rawResult[0])`
  (`PythonKitBridge.swift:1321-1324`), silently defaulting to `1` (failure)
  if the shape doesn't match rather than surfacing *why*.
- `scrub_metadata_only()` returns `Tuple[bool, str, Optional[dict]]`
  (`pipeline.py:4023-4027`); Swift unpacks `rawResult[0]`, `rawResult[1]`,
  `rawResult[2]` positionally (`PythonKitBridge.swift:1540-1561`), then
  re-serializes the dict at index 2 to a JSON *string* via Python's `json`
  module and immediately re-parses it with Foundation's
  `JSONSerialization` to get a `[String: Any]` (`PythonKitBridge.swift:1549-1552`)
  — a round-trip through text purely to cross a boundary that is otherwise
  already in-process and typed.
- `metadata_report_only()` returns a *5-tuple*,
  `Tuple[bool, str, dict, str, str]` (`pipeline.py:4125-4129`), one field
  longer than the 3-tuple above, unpacked the same positional way
  (`PythonKitBridge.swift:1620-1638`). Nothing prevents these two "returns a
  status tuple" functions from drifting to different, incompatible
  shapes over time — which they already have.

### 4. On-disk JSON report files (Python writes, Swift/user reads later)

Unlike the above three, these genuinely are files, written with an atomic
temp-then-`os.replace()` pattern (`_sibling_temp_path()` /
`_replace_existing_temp()`, `pipeline.py:1251-1266`, and see the T7 section
below):

- **Audit report** — `write_report()` (`report.py:50-100`) builds an ad-hoc
  dict (`created_at`, `input_sha256`, `model`, `spans`, optionally `warnings`/
  `suppressed`/`settings`) and hands it to `write_json_file()`
  (`report.py:15-31`), which does a raw `json.dumps(data, indent=2)` with no
  schema validation before the `os.open(..., 0o600)` write.
- **Scrub/metadata report** — built by `_build_scrub_report()` and written
  the same way (`pipeline.py:1450-1460`), a structurally different dict
  (different keys entirely) that happens to share the same untyped
  `write_json_file()` helper.
- **Failure report** — `_write_failure_report()` (`pipeline.py:1637-1661`)
  writes yet another shape: `{"status": "error", "input_file", "error_code",
  "message", "technical_details"}`. Swift's only reader of any on-disk report
  today is `loadFailureReport()` (`DocumentRedactionViewModel.swift:2105-2121`),
  which does `JSONSerialization.jsonObject(...) as? [String: Any]` and then
  reads `json["error_code"] as? String ?? json["status"] as? String ?? "unknown"`
  — i.e. it doesn't even commit to one key name, it guesses between two
  possible shapes with a string literal as the last-resort default. This is
  the clearest concrete evidence in the codebase of exactly the fragility
  problem this ticket is about: two independently-evolving dict-builders
  (`write_report` vs. `_write_failure_report`) whose consumer has to
  defensively probe for whichever one actually wrote the file.
- The full audit report (with `groups`) is also read back into Swift via
  the same tuple + `json.dumps`/`JSONSerialization` round-trip described
  above for `scrub_metadata_only()`/`metadata_report_only()`
  (`PythonKitBridge.swift:1544-1558,1623-1636`), so the same report shape is
  both a return-tuple payload *and*, independently, a file on disk — two
  representations of the same data with no shared schema tying them
  together.

### Summary of the fragility

None of these four shapes has a single source of truth. Each is defined
implicitly by "whatever the Python dict-literal / tuple-literal currently
contains," and each Swift consumer independently re-guesses the shape with
`as?` casts and string-literal fallbacks. A Python-side rename (e.g.
`error_code` → `code`) or a reordered tuple compiles fine on both sides and
fails only at runtime, in production, as a misrouted error message or a
progress bar that silently stops updating.

## Approach Comparison

### Protobuf

- **Build tooling cost**: High relative to the other two, for this specific
  stack. Swift Package Manager has no first-party protobuf plugin; the
  project would need to either vendor `protoc` + `swift-protobuf` as a build
  step invoked from the existing `scripts/sh/build_*.sh` scripts, or check in
  generated `.pb.swift`/`_pb2.py` files and regenerate manually. Python side
  is easy (`protobuf` pip package, already schema-driven). The real cost is
  that protobuf's canonical use case is a *serialized wire format*, and this
  bridge, per the inventory above, is mostly **not** serialized — it's
  in-process PythonKit calls. Using protobuf would mean either (a)
  serializing every progress callback and return value to bytes and back for
  no networking benefit, purely to get schema validation, or (b) using
  protobuf-generated classes as plain in-memory structs on both sides and
  never actually serializing them, which works but pays protobuf's full
  codegen/toolchain cost for a benefit (schema-checked in-memory structs)
  that a much lighter mechanism also provides.
- **Runtime cost**: Low once built, but non-zero — encode/decode on every
  progress tick (which fires far more often than once per document; see the
  chunk- and mass-level granularity in `model_enhanced.py`) is wasted work if
  the boundary never actually leaves process memory.
- **Migration risk**: Medium-high. Requires the widest blast-radius change
  of the three options — every message shape becomes a `.proto` file, every
  Python dict-builder becomes a generated-class construction, every Swift
  `as?` cast becomes a generated-class field access. Good for cross-language,
  cross-network contracts; overkill for this project's actual topology.

### FlatBuffers

- **Build tooling cost**: Similar toolchain burden to protobuf (a `flatc`
  codegen step for both Swift and Python), with a smaller and less
  actively maintained Swift binding ecosystem than `swift-protobuf`. The
  zero-copy read benefit FlatBuffers is designed for matters when you're
  deserializing large buffers received over a wire; it does not matter here
  because there is no wire — PythonKit already hands over live Python
  objects with zero serialization. Adopting FlatBuffers would add its build
  complexity while using none of its actual value proposition for this
  bridge's four message shapes (small dicts/tuples, not bulk binary data).
- **Runtime cost**: Lowest of the three *if* messages were actually
  serialized, but that advantage is moot for an in-process boundary.
- **Migration risk**: Similar to Protobuf, plus a smaller ecosystem/less
  precedent to lean on if something goes wrong mid-migration. Weakest fit of
  the three for this codebase.

### OpenAPI-style JSON Schema validation

- **Build tooling cost**: Lowest by a wide margin. The four message shapes
  above are *already* JSON-shaped in the cases that actually cross a real
  serialization boundary (the on-disk report files, the env-var JSON blobs)
  and are Python-native dicts/dataclasses/tuples for the in-process cases.
  JSON Schema needs no code generation step at all to start paying off:
  Python already has `pydantic` as a direct dependency
  (`pyproject.toml`/CLAUDE.md's dependency list — `pydantic>=2.6.4`, unused
  for this purpose today but already vendored and signed into the BeeWare
  `python_site` bundle), so defining each shape as a `pydantic.BaseModel`
  and calling `.model_validate()` before writing/returning it is close to
  zero marginal build cost. Swift needs a JSON Schema *validator* only for
  the on-disk file shapes (report/failure JSON); the in-process tuple/dict
  shapes don't need schema validation on the Swift side at all if Python
  validates before crossing — Swift just needs typed `Decodable` structs
  matching the now-guaranteed-valid shape, which is a small, incremental,
  file-by-file change (already partially true: `PythonRunnerProgressUpdate`
  is already a typed Swift struct, it's just populated by hand-rolled
  `as?`/`toOptionalString()` casts instead of `Decodable`).
- **Runtime cost**: Negligible. `pydantic` validation on a handful of dicts
  per document is far below the cost of a single LLM chunk call. No new
  serialization step is introduced for the in-process cases — validation can
  happen on the existing dict/dataclass before it's handed across, and
  `Decodable` decoding on the Swift side replaces manual casts with
  equivalent-or-cheaper `JSONDecoder` calls for the file-shaped cases that
  already round-trip through `JSONSerialization` today.
- **Migration risk**: Lowest. This is additive and incremental by
  construction — a `pydantic.BaseModel` (or a hand-written JSON Schema
  checked with `jsonschema.validate()`) can be introduced for *one* message
  shape at a time (e.g. start with the failure report, since it's the
  shape with a documented, reproducible symptom today — the dual
  `error_code`/`status` guessing in `loadFailureReport()`) without touching
  the other three. Each shape's validation can run in shadow mode
  (validate, log a warning on mismatch, but still send the legacy payload)
  before Swift is switched to trust the validated shape, which directly
  satisfies the "no big-bang cutover" requirement below.

### Recommendation

**OpenAPI/JSON-Schema-style validation (via `pydantic` on the Python side,
`Decodable` structs on the Swift side), not Protobuf or FlatBuffers.**

The deciding factor is topology, not general schema-technology merit:
Protobuf and FlatBuffers are both optimized for *wire* efficiency across a
real serialization boundary, and three of this bridge's four message shapes
never serialize at all — they're live Python objects read directly by
Swift through PythonKit. Paying a codegen-toolchain cost (new to both the
Swift Package Manager build and the BeeWare Python packaging pipeline) to
get a wire-format benefit the bridge doesn't need is the wrong trade here.
The one shape category that *does* genuinely serialize — the on-disk JSON
report files — is already JSON today, so JSON Schema validation is a
strict, low-risk tightening of the existing format rather than a format
change, and `pydantic` is already an approved, signed, bundled dependency
per this repo's own dependency list, meaning zero new supply-chain surface
to review or notarize.

## Migration Plan (no big-bang cutover)

Ordered by risk, cheapest/lowest-risk first, each step independently
shippable and independently revertable:

1. **Define `pydantic` models for the on-disk report shapes first** (audit
   report, scrub report, failure report — the three dict shapes described in
   Inventory §4). Add `model_validate()` calls immediately before each
   `write_json_file()` call site (`report.py:83,97`; `pipeline.py:1460,1480`;
   `pipeline.py:1658`) so malformed reports fail loudly in Python (where a
   stack trace is diagnosable) instead of silently on the Swift side (where
   today's failure mode is a wrong-guessed string like `"unknown"`). This
   step touches Python only — zero Swift changes, zero behavior change for
   well-formed reports, and directly fixes the concrete
   `error_code`/`status` ambiguity in `loadFailureReport()` by making the
   failure-report shape a single named model with one canonical field.
2. **Add matching `Decodable` Swift structs and switch the report *readers*
   (not writers) to `JSONDecoder`**, starting with `loadFailureReport()`
   (`DocumentRedactionViewModel.swift:2105-2121`) since it already has the
   clearest bug (dual-key guessing). Keep the existing `as? [String: Any]`
   path as a fallback for one release behind a debug log line ("legacy
   report shape encountered") so an unexpected old-format file from a
   previous app version doesn't hard-fail — this *is* the "validate in
   parallel before switching" pattern the ticket asks for, scoped to the
   lowest-risk shape first.
3. **Extend the same pattern to the return-tuple shapes** (Inventory §3):
   define `pydantic` models for `scrub_metadata_only`'s and
   `metadata_report_only`'s return payloads, validate before return, and on
   the Swift side replace the positional `rawResult[0]`/`rawResult[1]`/
   `rawResult[2]` indexing with a single `Decodable` decode of the
   `json.dumps()`'d dict — this is nearly free because
   `PythonKitBridge.swift:1549-1552` (and the `metadata_report_only`
   equivalent) *already* round-trips through `json.dumps()` +
   `JSONSerialization`; the only change is decoding into a named
   `Decodable` type instead of `[String: Any]`, so the runtime cost is
   unchanged and the type safety is strictly additive. `run_redaction`'s
   `(code, timings)` tuple is simple enough (an int and a flat
   `Dict[str, float]`) that it's lowest priority in this group — revisit
   only if it drifts in shape.
4. **Progress callback shapes last, and partially (Inventory §2)**. This is
   the highest-risk shape category because it's the hottest path
   (fires many times per document, see the streaming-progress design doc's
   Option B discussion of per-token frequency) and because it currently has
   *three* overlapping mechanisms (rich `ProgressUpdate`, simple 3-tuple,
   and JSON-string-stuffed-into-message). Rather than unify all three into
   one schema in this migration, the concrete recommendation is:
   - Formalize `ProgressUpdate` (already a `@dataclass`, `progress.py:113-122`)
     with a `pydantic.dataclasses.dataclass` or paired `BaseModel` and use it
     as the *only* rich-path shape (already true in practice — the simple
     3-tuple path exists purely as a fallback for callbacks with a different
     declared arity, and no current Swift call site actually registers a
     3-arg callback; confirm this with a grep-based audit as the first task
     of this step before removing the branch).
   - Fold `emit_mass_event()`'s ad-hoc `{"type": ..., ...}` dicts into a
     small closed set of `pydantic` models (`MassTotalEvent`, `ChunkStartEvent`,
     `ChunkEndEvent`, `KeepaliveEvent`), validated before `json.dumps()`, so
     the JSON string Swift currently receives inside `message` is at least
     guaranteed well-formed and schema-stable — this does *not* require
     changing the Swift side to parse it structurally in this migration
     (Swift today only displays `message` as text), just stops the "guess
     the shape" failure mode from being possible on the Python side.
   - Do **not** attempt to collapse the rich/simple/mass-event three-way
     split into a single new channel as part of this migration — that's a
     larger behavioral change (it would touch `ProgressTracker.__init__`'s
     signature-detection logic, `progress.py:132-144`) better scoped as its
     own follow-up once steps 1–3 have proven the pattern in production.
5. **Env-var JSON blobs (Inventory §1) are explicitly out of scope for a
   schema migration** — they're small enough (one JSON object, one CLI-arg
   string, one float scalar) that the existing `isinstance(decoded, dict)`
   guard plus a `pydantic` validation *inside* `from_environment()`
   (`docx_io.py:302-310`) is a one-line addition once step 1's pattern
   exists, but there's no reader/writer split to stage here (Python is both
   writer-of-contract and sole reader), so it can be folded into whichever
   of steps 1–3 touches `MetadataCleaningSettings` incidentally rather than
   scheduled as its own step.

Each step is independently shippable: steps 1–2 touch only the failure/audit/
scrub report path, step 3 touches only the two metadata tuple-returning
functions, and step 4 touches only the progress channel — none depend on the
others being complete, and each can be verified with the existing test
suites (`tests/test_pipeline.py`, `tests/test_cli.py`,
`MarcutAppTests.swift`) plus one new schema-violation test per model (feed a
deliberately malformed dict/tuple through and assert it's rejected before
crossing the boundary, rather than silently passed through with a wrong
guess on the far side).

## Cancellation/Deadline and Transactional-Write Interaction

This migration must not risk the invariants established by the T6
cancellation/deadline work (`731fc605`, `b0699afb`, `c5ce474e`,
`src/python/marcut/cancellation.py`) or the T7 transactional-artifact-write
work (`8e91eb18`, `pipeline.py`'s `_sibling_temp_path()` /
`_replace_existing_temp()` / `_cleanup_temp_artifacts()`,
`pipeline.py:1251-1277`), both of which communicate state across the exact
same bridge this doc is proposing to change.

**Cancellation/deadline (T6):**

- `MARCUT_PROCESSING_DEADLINE_MONOTONIC` (Inventory §1) is explicitly
  excluded from schema formalization in step 5 above, and that exclusion is
  deliberate: T6 depends on this env var being read with the specific
  fail-open behavior in `processing_deadline()` (`cancellation.py:12-20`) —
  an absent or unparseable value means "no deadline," not "invalid input,
  reject." Wrapping this in strict `pydantic` validation that raises on a
  missing/malformed value would invert that fail-open contract into
  fail-closed, which is a behavior change T6 did not sign up for and this
  ticket does not authorize. If this env var is ever touched by a future
  step, the validator must preserve "absent or malformed → no deadline,"
  not "absent or malformed → error."
- The progress-callback formalization in step 4 must not add any new
  validation-driven exception path that can be *raised from inside* the
  progress-callback closure. Today, `emit_mass_event()`'s `except Exception:
  pass` (`model_enhanced.py:871-872`) deliberately swallows progress-emission
  errors so a progress-reporting glitch never aborts the actual redaction
  work; T6's deadline/cancellation checks are separate, explicit calls
  (`check_processing_deadline()`, `cancel_event.is_set()`) that are not
  routed through the progress channel. A `pydantic.ValidationError` raised
  inside a `pydantic`-wrapped `emit_mass_event()` must be caught at least as
  defensively as today's bare `except Exception: pass` — schema validation
  failures on a progress *event* should degrade to "drop this one progress
  tick" (or fall back to the pre-migration untyped payload, per the
  parallel-validation approach in step 2), never to "abort the chunk" or
  "abort the document," since that would let a cosmetic schema mismatch
  silently promote itself into a functional regression indistinguishable
  from an actual deadline expiry or a user-initiated Stop.
- Conversely, the *existing* timeout/deadline error classification
  (`pipeline.py:1883-1886` matching `"timeout"`/`"deadline"` in the error
  string to produce `AI_PROCESSING_TIMEOUT`) must keep working once the
  failure-report shape is formalized in step 1. The `pydantic` model for the
  failure report must keep `message`/`technical_details` as free-form
  strings (not enums or constrained patterns) specifically so a deadline
  exception's message text still contains the substrings this classifier
  greps for — over-constraining that field to "known error shapes" would
  break deadline-classification silently, in the same "compiles fine, wrong
  at runtime" way this whole migration is trying to eliminate elsewhere.

**Transactional artifact writes (T7):**

- T7's atomicity guarantee — write to a sibling temp path, `os.replace()`
  into the final path only after every artifact in the batch is ready,
  clean up temp files on any exception (`pipeline.py:1513-1529`) — operates
  at the *file* level, one level above the JSON *shape* inside each file.
  Schema validation from step 1 must happen **before** `write_json_file()`
  is called on the temp path (i.e. validate the in-memory dict/model, then
  write already-valid JSON to the temp file), not after. Validating
  post-write against the temp file would mean a schema-invalid report could
  still reach `_replace_existing_temp()` and get atomically promoted to the
  final path — atomic promotion of bad data is not a fix, it's the same bug
  with extra ceremony. Concretely: the `model_validate()` call from step 1
  belongs immediately before `write_json_file(scrub_report_temp_path,
  report)` (`pipeline.py:1460`) and immediately before `write_report(...)`
  (`pipeline.py:1496`), not as a separate post-hoc read-back-and-check pass.
- A validation failure at that point must raise the *same*
  `RedactionError`-based failure path T7 already uses
  (`pipeline.py:1518-1528`'s `except Exception as e: _cleanup_temp_artifacts(...); raise RedactionError(...)`),
  so an invalid report is treated exactly like today's "failed to finalize
  output artifacts" case — temp files get cleaned up, no partial/invalid
  artifact is left at the final path, and the user sees the existing
  `ARTIFACT_FINALIZE_FAILED` error code rather than a new, unclassified
  crash. This is a natural fit, not a new failure mode: T7's cleanup path
  already exists precisely to make "something went wrong while building the
  report" safe, and schema validation is just one more way that can happen.
- No change is needed to `_sibling_temp_path()` / `_replace_existing_temp()`
  / `_cleanup_temp_artifacts()` themselves (`pipeline.py:1251-1277`) — they
  operate on file paths and are agnostic to what's inside the file. This
  migration is purely about tightening what's written *before* those
  functions are called, which keeps the file-level atomicity guarantee and
  the payload-level schema guarantee as cleanly separated concerns, matching
  how they're already separated in the code today (`_finalize_and_write()`
  builds content, then a distinct block of the same function handles
  temp-path staging and atomic replace).

## Out of Scope (per ticket)

- No code changes in this ticket — the above is a plan, not a patch.
- No single approach is fully implemented or prototyped here; step 1 above
  is the recommended starting point for a future implementation ticket, not
  something this spike builds.
