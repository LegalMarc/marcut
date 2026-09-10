# Changelog

All notable changes to this project will be documented in this file.

## 2026-09-10

### Fix
- Decode `ReportViewer.collectBinaryExportURLs(from:)`'s `binary_exports`/`large_exports` report arrays through `JSONDecoder` against new `BinaryExportEntry`/`BinaryExportManifest` `Decodable` types, instead of `JSONSerialization.jsonObject` cast through `as? [String: Any]` / `as? [[String: Any]]` / `entry["path"] as? String`. The decode is a new pure `static func parseBinaryExportRelativePaths(from:)` helper (mirroring the `parseFailureReport`/`loadFailureReport` split from #89) that merges both arrays' relative paths and returns `nil` on decode failure so `collectBinaryExportURLs` can log `Failed to parse binary export manifest at <path>` via `DebugLogger` and return `[]`, exactly as the prior guard chain did silently. `BinaryExportEntry` decodes only the `path` field this file ever reads, dropping the `name`/`type`/`size` keys `pipeline.py`'s `export_entry` literal also writes; `Decodable` ignores unknown keys so the shape can grow. The directory-containment check (`candidatePath == rootPath || candidatePath.hasPrefix(rootPath + "/")`) is untouched. `collectBinaryExportURLs(from:)` becomes internal (not private) for the same unit-testability reason as `loadFailureReport`. Step 2b of the bridge-schema migration in `docs/design/bridge_schema_migration.md`, extending the pattern to the second on-disk report reader the doc's "Current State Inventory" item 4 had missed (#90). Fix round 1: `name`/`type`/`size` were initially declared required, but `JSONDecoder` fails an entire array when any one element is missing a required key, so one older or hand-edited export entry lacking any of those three unused fields silently erased every export from the Burn/secure-erase path; decoding `path` only (the only field this file reads, matching `report_html.py`'s own `.get(key, default)` treatment of the same three fields) makes one malformed entry's absent fields harmless. The doc's Status block and its stale "Swift's only reader ... is `loadFailureReport()`" claim (Current State Inventory item 4) are also corrected in this commit to name `ReportViewer.collectBinaryExportURLs(from:)` as the second on-disk report reader.
- Validate `MARCUT_METADATA_SETTINGS_JSON` against a new `_MetadataSettingsPayload` pydantic model in `docx_pkg/settings.py` instead of silently dropping a malformed or wrong-shaped payload (`json.loads()` inside a bare `except`, applied only `if isinstance(decoded, dict)`). Warn-and-default was chosen over raising: `MetadataCleaningSettings` is constructed on the redaction path, and the macOS app runs Python in-process, reusing one interpreter across an entire batch job, so an exception here would fail every remaining document in the batch rather than the one document with the bad payload -- the requirement is that the failure become visible, not fatal. Malformed JSON and a well-formed payload of the wrong shape (a top-level array/scalar, or a `"settings"` key that isn't itself an object) now both emit a `RuntimeWarning` naming the variable and fall back to defaults; a valid payload (flat or `{"settings": {...}}`-wrapped) applies exactly as before; an absent variable still yields defaults with no diagnostic. `MARCUT_METADATA_ARGS`'s `from_cli_args()` loop gets the same treatment: an unrecognised flag now warns (naming the flag) instead of disappearing silently, while the three non-field sentinels (`--preset-none`, `--no-clean-review-comments`, `--clean-review-comments`) stay silent since they are handled elsewhere by design. Also folds `pipeline.py`'s three duplicate `MARCUT_METADATA_ARGS` decode-and-parse call sites (`run_redaction`, `scrub_metadata_only`, `metadata_report_only`) into one shared `_metadata_settings_from_env()` helper, with no behavior change at any of the three. `MARCUT_PROCESSING_DEADLINE_MONOTONIC` is untouched, per the design doc's explicit fail-open exclusion. Step 5 of the bridge-schema migration in `docs/design/bridge_schema_migration.md` (#94). Fix round 1: `warnings.warn` alone under-delivered on "instead of being silently ignored" for a batch job, because Python's default warning filter shows a given (message, category, module, lineno) only once per process and the macOS app reuses one interpreter across an entire batch with an identical bad payload -- documents 2..N produced no diagnostic. All three diagnostics (malformed JSON, wrong-shape JSON, unrecognised `MARCUT_METADATA_ARGS` flag) now also go through the module logger (`logging.getLogger(__name__).warning()`, which does not deduplicate) and through the `MARCUT_LOG_PATH` app-log channel that the shipped in-app log viewer reads, since `PythonKitBridge.swift` never captures Python's stderr and `warnings.warn` alone would otherwise be invisible in the packaged app.
- Validate every `emit_mass_event()` payload (`model_enhanced.py`) against one of five new closed pydantic models in `progress.py` -- `MassTotalEvent`, `ChunkStartEvent`, `ChunkEndEvent`, `KeepaliveEvent`, `TokenProgressEvent` (a discriminated union on `type`, each `extra="forbid"`) -- via a new `validate_mass_event()` helper, called before `emit_mass_event`'s existing `try`/`except Exception: pass` guard so a malformed payload (unknown `type`, missing/mistyped field, unexpected extra field) raises immediately in Python instead of being silently dropped or reaching the Swift bridge as wrong data. Resolves the `token_progress` gap noted in `docs/design/bridge_schema_migration.md`'s step 4b: `DocumentModels.swift`'s `ingestProgressPayload` switch previously fell through to `default: return false` for `token_progress`, an undocumented omission; it now has an explicit, commented no-op case, deliberate rather than accidental, and does not change what drives the progress bar. A parity test parses that switch out of `DocumentModels.swift` and asserts the model set, the readability mirror `SWIFT_HANDLED_MASS_EVENT_TYPES` in `progress.py`, and the parsed Swift set are all identical, so the two sides cannot silently drift apart again. `TokenProgressEvent.eval_count` is `Optional[int]`, matching the producing callback's `Callable[[int, Optional[int]], None]` contract: Ollama reports `eval_count` only on the stream's final `done: true` line, so requiring it would have rejected every intermediate intra-chunk progress event -- silently, since `model.py` invokes that callback inside a `try`/`except Exception: pass`. That swallowing is now documented at the emit site and covered by a test, alongside the keepalive thread's downgrade to an `LLM_KEEPALIVE_FAILED` warning: only the `mass_total`/`chunk_start`/`chunk_end` call sites propagate a validation failure to the caller. Step 4b of the bridge-schema migration (#93).

## 2026-09-09

### Fix
- Guard `model_enhanced.py`'s `emit_mass_event()` tracker dispatch (`tracker.update_phase(...)`) in its own `try`/`except` so a `ValidationError` raised by the now-pydantic `ProgressUpdate` (step 4a, above) cannot also skip the function's `print(message, flush=True)` -- the stdout mass-event line the Swift bridge parses independently of the tracker. Adds regression coverage in `tests/test_model_enhanced.py` for the three-argument `progress_callback(0, 0, display)` dispatch path used by the shipping Swift app (the bridge's `PyCFunction` callback is unintrospectable, so `accepts_progress_update` is always False and `tracker` stays `None`), its two-argument `TypeError` fallback, and the print-survives-a-raising-tracker case. Follow-up to #92's review round 1.
- Convert `ProgressUpdate` (`progress.py`) from a plain `@dataclass` to a `pydantic.dataclasses.dataclass` so a malformed progress update (e.g. a non-numeric progress value) raises immediately on construction instead of silently crossing the Swift bridge as wrong data; `phase` stays a `ProcessingPhase` enum member rather than widening to a string. Also removes `ProgressTracker`'s `inspect.signature`-based dispatch that special-cased a callback declaring exactly three parameters as a legacy `(chunk, total, message)` shape, plus the `is_simple_callback` flag it set -- a repo-wide audit (recorded on issue #92) found no such callback registered anywhere: the CLI and GUI both register a one-parameter rich callback via `create_progress_callback`, and the Swift bridge's `PythonKitBridge.swift` callback is a `PyCFunction` (`METH_VARARGS | METH_KEYWORDS`, no `__text_signature__`) that `inspect.signature` cannot introspect at all, so it already took the rich path unconditionally. Every callback now always receives the single `ProgressUpdate` object. `model_enhanced.py`'s separate `emit_mass_event()` fallback (a direct `progress_callback(0, 0, display)` call with its own arity check) is unrelated and untouched -- out of scope per the ticket, tracked separately. Step 4a of the bridge-schema migration in `docs/design/bridge_schema_migration.md` (#92).
- Validate `pipeline.scrub_metadata_only()`'s and `pipeline.metadata_report_only()`'s tuple-index-2 report payload against two new pydantic models, `MetadataScrubPayload`/`MetadataReportPayload` in `report_schema.py` (subclasses of the existing `ScrubReport`, one per function so each function's return boundary is guarded independently), immediately before each function returns -- `metadata_report_only()`'s existing pre-write `ScrubReport.model_validate()` call (#67) is retargeted to `MetadataReportPayload`, and `scrub_metadata_only()` gains a validation call it previously had none of. On the Swift side, `PythonKitBridge.swift`'s `scrubMetadataOnlyAsync`/`metadataReportOnlyAsync` replace their `JSONSerialization.jsonObject(...) as? [String: Any]` cast of the round-tripped `json.dumps()` string with a `JSONDecoder` decode into a new shared `MetadataReportBridgePayload` `Decodable` struct (backed by a small recursive `JSONValue` type for the payload's intentionally loosely-typed nested fields), then reconstructs the `[String: Any]` shape existing downstream consumers expect via `asDictionary` -- no downstream call site changes. Tuple arity/order is unchanged on both ends. Step 3 of the bridge-schema migration in `docs/design/bridge_schema_migration.md` (#91).
- Decode the on-disk failure report through `JSONDecoder` against a new `FailureReportPayload` `Decodable` struct in `DocumentRedactionViewModel.swift`, instead of `loadFailureReport(at:)` always probing an untyped dictionary via `error_code ?? status ?? "unknown"`. The decode itself is a new pure `static func parseFailureReport(_:)` helper returning `(code, message, details, usedLegacyPath)`, so tests can assert which path actually ran rather than only the output tuple (which the two paths can produce identically for a fixture carrying all five keys). A well-formed report (matching the pydantic `FailureReport` model from step 1) now resolves through the typed path (`usedLegacyPath == false`); a legacy-shaped report (missing `error_code`) falls back to the existing `JSONSerialization` dictionary read for one release (`usedLegacyPath == true`), now logging `legacy report shape encountered` so the fallback's use is observable; a corrupt/non-JSON file still returns `nil`. `message`/`technical_details` stay free-form `String` so the `AI_PROCESSING_TIMEOUT` classifier's `"timeout"`/`"deadline"` substring grep in `pipeline.py` keeps working. `loadFailureReport(at:)` becomes internal (not private) so it is directly unit-testable via `@testable import`, matching the existing `PythonWorkerThread` precedent. Step 2 of the bridge-schema migration in `docs/design/bridge_schema_migration.md`, whose Status header is updated in this commit to record it (#89).
- Clear the four pre-existing lint errors that had kept CI's `hygiene` and `smoke` jobs red on `main` since 2026-09-05, leaving the ruleset's two required status checks failing across the whole #67-#88 campaign (last green run was 2026-07-16). Drop an unused `rationale_mentions_text` import in `pipeline.py` (F401); split `import random, string, time` in `tests/test_rationale.py` (E401); make the repair-fallback re-raise in `model.py` an explicit `raise decode_error from None` (B904), which is what the surrounding comment already describes -- surface the original decode error, not the repair artifact; and wrap a 126-character `stringByReplacingMatches` call in `ExcludedWordMatcher.swift` to the configured 120 `maxwidth`, applied by SwiftFormat 0.62.1, the version CI pins. No behavioural change.
- Remove the unreachable session-tracking branch in `FileAccessCoordinator.swift`. The type is a `private init()` singleton, so `initializeSessionTracking()` ran once per process launch and compared a `UUID().uuidString` minted immediately beforehand against one persisted under `MarcutApp_PermissionSessionUUID`; the two could never be equal, making the `else` branch dead, the resets of `hasRequestedPermissionsThisSession`/`sessionPermissionsEstablished` redundant against their `false` initialisers, and the persisted key write-only. Replaced with a `logSessionStart()` that just records the launch, and dropped the unused key. Behaviour was already correct by accident and is unchanged. Closes the last open finding (9) of the 2026-08-29 deep bug sweep; see `docs/reports/2026-09-09-deep-bug-sweep-remediation-status.md` for the status of all ten.

### Feature
- Make `MARCUT_GENERATE_RATIONALE` a first-class `run_redaction()` setting instead of a process-global env var read independently at two points in the run (`_finalize_and_write` and `_collect_enhanced_spans`). `run_redaction()` gains an optional `generate_rationale` parameter, resolved exactly once (falling back to the env var only when the caller leaves it `None`), recorded in `report_settings["generate_rationale"]`, and threaded to both former read sites so a report's spans and its `rationale_generation.enabled` flag can no longer disagree with each other -- a real hazard for the macOS app, which runs Python in-process via PythonKit and reuses the interpreter across batch jobs. `_finalize_and_write` still falls back to reading the env var directly when called without a `report_settings` dict carrying the key, preserving existing direct-call test behavior. Adds a `--rationale` CLI flag (defaulting to `None`, not `False`, so omitting it still defers to the env var) and a matching `unified_redactor.run_unified_redaction()` passthrough (#88).

## 2026-09-05

### Fix
- Validate the three on-disk report shapes (audit, scrub, failure) against new Pydantic models in `report_schema.py` immediately before every write -- including `pipeline.metadata_report_only()`'s read-only scrub report, which the ticket's original diff had missed -- so a schema-invalid report fails loudly in Python instead of reaching the Swift bridge. Step 1 of the bridge-schema migration in `docs/design/bridge_schema_migration.md` (#67).
- Extract the CLI/settings configuration surface (`MetadataCleaningSettings`, `CLI_ARG_PAIRS` and friends) out of `docx_io.py` into `docx_pkg/settings.py`, moved verbatim with `docx_io.py` re-exporting the same names for backward compatibility. Slice 1 of the package split in `docs/design/docx_io_package_split.md` (#72).
- Extract the XXE-hardened `_safe_fromstring()` XML parser out of `docx_io.py` into `docx_pkg/xml_utils.py`, moved verbatim with `docx_io.py` re-exporting the same name for backward compatibility. Slice 2 of the package split in `docs/design/docx_io_package_split.md` (#73).
- Extract `_rewrite_docx_zip()` and its ~20 nested closures out of `docx_io.py` into `docx_pkg/zip_postprocess.py` as explicit-parameter module-level functions, with `DocxMap._rewrite_docx_zip` kept as a thin delegating method so existing call sites are unaffected. Slice 3 of the package split in `docs/design/docx_io_package_split.md` (#74).
- Extract the document scanning/indexing layer (`_iter_part_elements`, `_iter_part_elements_with_parts`, the `_scan_*` family, `_build()`) out of `docx_io.py` into `docx_pkg/scan.py` as a new `DocumentIndex` type, moved verbatim and composed by `DocxMap` in `__init__`, which re-exposes `.text`/`.index`/`.detached_parts` and keeps thin delegating methods for `_iter_part_elements`/`_iter_part_elements_with_parts` (still called by the hardening/revision-writing code pending Slice 5). Slice 4 of the package split in `docs/design/docx_io_package_split.md` (#75).
- Point both HTML reports' "View Raw JSON Data" link at the final JSON basename instead of the transactional staging temp name. `report.write_report()` and `report_html.generate_report_from_json_file()` now take an optional `json_link_path`, which `pipeline.run_redaction()` passes as the post-rename report path; previously the audit HTML linked to `.out.<random>.tmp.json` and the scrub HTML to `.out_scrub_report.<random>.tmp.json`, both of which are deleted during finalization, leaving every generated report with a dangling link.
- Compute the scrub report's `file_info.output` sha256/size from the staged output bytes that are actually delivered, via a new `pipeline._final_output_file_info()`, naming them by the final output path. The report previously hashed the final path before the rename had happened, so its integrity claim about the redacted DOCX was stale or missing entirely. The audit report records only `input_sha256` and is unaffected.
- Extract the remaining hardening/revision-authoring code out of `docx_io.py` into `docx_pkg/hardening.py` (`MetadataHardener`: `harden_document()`, `scrub_metadata()` and their private helpers) and `docx_pkg/revision_writer.py` (`RevisionWriter`: `apply_replacements()` and the track-changes element builders), both moved verbatim and injected with `DocumentIndex`'s part-iteration methods rather than duplicating them; `DocxMap` (now `docx_pkg/document.py`) is a thin coordinator composing all three and preserving its full pre-split public method surface, and `docx_io.py` becomes a backward-compatibility shim re-exporting the complete `docx_pkg` public surface. The `_metadata_settings` -> `save()` order-dependency contract (#71) is preserved exactly. `pipeline.py`/`cli.py` now import from `docx_pkg` directly. Slice 5 (final) of the package split in `docs/design/docx_io_package_split.md` (#76).
- Unify the five hand-rolled copies of the "does this run dispatch to llama.cpp rather than Ollama" test into one shared predicate, `uses_llama_cpp_backend()` (built on `is_gguf_model_path()`), in the leaf module `model_config.py` -- the one module `model_enhanced.py`, `pipeline.py` and `unified_redactor.py` can all import without a cycle. Every site now adopts the `llama_gguf or model_id` precedence that real dispatch already used, which changes two behaviours: `--backend llama_cpp --llama-gguf /x.gguf --model qwen2.5:14b` previously handed the Ollama tag (`model_id`) to `LlamaCppRedactionPipeline` in `apply_llm_overrides_to_rule_spans`, whose load failure was swallowed by that function's `except Exception: return rule_spans` handler and silently skipped the entire rule-override validation pass; and `--llama-gguf x.gguf` left at the default `--backend ollama` now dispatches that same pass to llama.cpp, where it previously went to Ollama. `pipeline._uses_llama_cpp_backend` becomes a thin re-export of the shared name, and `pipeline._sanitize_model_for_report`'s display-side "names a file on disk" test now calls `is_gguf_model_path()` instead of its own `os.path.isabs(...) or endswith(".gguf")` copy. The two `unified_redactor.py` call sites keep their extra `"/" in model` / `os.path.sep in model` arm on top of the shared predicate so a separator-bearing path with no `.gguf` suffix is still accepted, exactly as before. Display and dispatch stay separated per #68: `settings["llama_cpp_dispatch"]` is still recorded from the full path, so sanitising the displayed value cannot change which backend runs (#87).

### Feature
- Add a `rationale: {text, origin, model?}` field to every audit-report span, opt-in via `MARCUT_GENERATE_RATIONALE` (off by default; disabling is byte-identical to today's output). `origin` is a mandatory 3-value enum (`llm_validation`/`rule_deterministic`/`unavailable`) enforced by a new `SpanRationale` pydantic model in `report_schema.py`. The real `llm_validation` text extends the existing batch-validation call in `model_enhanced.py` (`get_batch_validation_prompt`/`ollama_validate_batch`) rather than adding a new LLM call; rule-matched spans get a template-generated `rule_deterministic` string and never touch an LLM (verified by a mock call-count test). Rationale is canonicalized per stable `ClusterTable` entity_id (not per raw span mention) among LLM-path mentions -- rule-like re-matches of the same entity (`consistency_pass*`/`defined_term`) keep their own template -- and a rationale that restates another entity's literal text is withheld rather than shipped, checked both within a validation batch and across the whole document by one shared `rationale.rationale_mentions_text` check (an item's own text, including a same-text duplicate in the batch, is not a leak). `ValidationCache`'s key is schema-versioned so a pre-feature cache hit can never pair a fresh decision with a stale/missing rationale. New `rationale.py` module holds the shared `RationaleOrigin` enum, rule-template text, and the leak check; a report-level `rationale_generation: {enabled, model, mode}` block on every report (present even when disabled) distinguishes "not requested" from "requested and failed for every span" -- `mode` is `validation_extended` for an Ollama-backed LLM run, `unsupported_backend` for a llama.cpp/GGUF run (its validation path is not extended), or `rule_deterministic_only`. Data/correctness layer only -- HTML report rendering is `#69` (`docs/design/redaction_rationale_reporting.md`, #68).
  Post-review hardening: the cross-reference leak check is boundary-aware
  (entity texts edged with punctuation -- `Acme Inc.`, `$500,000`,
  `(555) 123-4567` -- were previously invisible to it) and no longer withholds
  an item's own rationale when a shorter cluster-mate is a substring of its
  text; `num_predict` scales with batch size when rationale is enabled so a
  truncated batch cannot flip every item to FULL_REDACT; a constrained
  `--format-schema` gains a `rationale` property instead of silently making
  the field impossible; and `rationale_generation.model` is null unless a
  model actually authored rationale.
- Render each entity-table row's `rationale` in the HTML audit report (#69, the rendering half of #68's data layer): an origin-appropriate badge (`AI-inferred` / `Rule match` / `No rationale`, reusing the existing `.source-badge` CSS) plus the explanation text, with a persistent "AI-inferred, not verified" caveat rendered as real text -- not a CSS-only cue -- next to any non-`rule_deterministic`, non-`unavailable` rationale, so the caveat survives copy/print/export and fails safe on an unrecognized or future `llm_*` origin rather than silently dropping the label. `unavailable` and a missing/malformed `rationale` field (a pre-#68 report, or the feature disabled) both render an explicit "No rationale recorded for this entity." state instead of a blank cell. Also replaces the Source column's exact `source == 'rule'` badge predicate with `rationale.is_rule_like_source()`, fixing a `consistency_pass*`/`rule_signature` span rendering a contradictory `llm` source badge next to a `rule_deterministic` rationale in the same row.

## 2026-07-14

### Feature-complete hardening review (issues #36-#54)
All 19 items from `docs/backlog/feature_complete_hardening_review_2026-07-05.md` were validated (survey file/line references were approximate, so several claims were refuted rather than fixed) and closed, each via its own PR with independent review.
- **Feature**: Add a PII detection precision/recall evaluation harness — a synthetic DOCX corpus generated at test time, a per-entity-type scorer, and a CI-gated rules-only test, with `DEVELOPER_GUIDE.md` instructions for running the full-LLM eval locally (A1, #36, PR #55).
- **Fix**: Verify DOCX redaction coverage across document parts — tables, headers/footers, footnotes/endnotes, textboxes, and content controls were already scanned (claim refuted), but review comments were found unscanned for PII and are now covered; also stop ORG-suffix regexes bridging paragraph/cell boundaries (A2, #37, PR #56).
- **Fix**: Eliminate chunk-boundary entity duplication and offset drift in enhanced LLM extraction by enforcing an offset invariant and deduping overlapping cross-chunk entities (A3, #38, PR #57).
- **Fix**: Fail closed on partial LLM chunk extraction failures — previously a failed chunk failed open silently, leaving unscanned text ranges undisclosed; now surfaced as a hard failure. Extended the same day to the `llama_cpp` backend, which had the identical gap (A4, #39, PRs #58 and #59).
- **Fix**: Validate LLM-derived spans (bounds + text match) before applying them as redactions, dropping invalid or drifted spans instead of silently corrupting output (A5, #40).
- **Fix**: Correct rules-layer accuracy — undashed SSN detection, phone/account-number false-positive disambiguation, and possessive-form exclusion matching; the address state-code validation claim was investigated and refuted (it already worked correctly) (A6, #41).
- **Fix**: Harden LLM JSON response parsing with a tolerant bracket/string repair fallback that recovers truncated responses (A7, #42).
- **Reliability**: Add bridge-level and heartbeat watchdogs so a wedged embedded Python worker fails fast with a recovery path instead of freezing the UI (B1, #43).
- **Reliability**: Add destination-writability and free-disk-space pre-flight checks before long processing runs and model downloads (B2, #44).
- **Reliability**: Detect and report a foreign process holding Marcut's expected Ollama port instead of silently talking to the wrong server (B3, #45).
- **Fix**: Sanitize user-facing failure alerts via a new `FailureMessagePresenter` so raw Python tracebacks no longer surface in the UI (B4, #46).
- **Reliability**: Hold a power assertion and health-check Ollama on system wake during long processing runs (B5, #47).
- **Reliability**: Verify (with a Swift test) that resume-after-kill never resurrects a partially-written document as complete (B6, #48).
- **Docs**: Re-evaluate the heartbeat timeout after the D2 streaming fix landed and close as a no-op — #54's intra-chunk token streaming (layered on the pre-existing keepalive thread) already keeps the heartbeat fresh through a single long Ollama chunk, so no new retry mechanism was needed; documented in `docs/design/streaming_progress.md` (B7, #49).
- **Test**: Expand failure-path coverage — Swift error-flow tests, a Python malformed-DOCX corpus, and property-based offset-invariant tests (hypothesis) (B8, #50).
- **Performance**: Profile the consistency pass and close as a no-op — the exact-match path is already single-pass and the fuzzy ORG scan is already bounded by the large-DOCX candidate limit (~134ms at realistic scale), so the O(candidates × doc length) concern was already mitigated by prior work; documented for re-open if a larger profile shows otherwise (C1, #51).
- **Performance**: Stream the DOCX metadata-scrub ZIP rewrite part-by-part instead of buffering all changed parts in memory (C2, #52).
- **Performance**: Benchmark LLM request concurrency and close as a no-op — raising server-side `OLLAMA_NUM_PARALLEL` gave no meaningful wall-clock win on Apple Silicon versus its near-linear memory cost, and the client-side thread pool's benefit is dispatch-latency hiding, not true parallel inference; no config change ships, findings recorded in `docs/PERFORMANCE_OPTIMIZATION.md` (C3, #53).
- **Feature**: Provide real fractional progress via Ollama token streaming (intra-chunk progress) plus a word-count-weighted batch ETA calculator (D2, #54).

### Additional fixes found during the review
- **Fix**: Perturb the seed on Ollama extraction self-correction retries so an empty model response can't deterministically repeat — root cause of a 5-day CI failure streak (#61).
- **Test**: Widen an overly-tight CI memory-threshold test bound that was flaking on measurement noise (#63).

## 2026-07-04
- **Release**: Produce a real Developer ID DMG (`MarcutApp-v0.5.96-AppStore.dmg`, later reconciled to `0.5.97`) via `scripts/sh/build_devid_release.sh` against a freshly-provisioned BeeWare `Python.framework`: signed with a Developer ID Application identity, submitted to Apple's notary service (accepted), stapled, and Gatekeeper-verified (`spctl` reports `accepted`/`source=Notarized Developer ID`). Full evidence, entitlement dump, and SBOM cross-check recorded in `docs/release/entitlement_governance_verification.md`'s Final Artifact Verification section.
- **Fix**: Give `scripts/release_preflight.sh`'s version-sync and secrets-check steps the same `config.json` → `config.example.json` fallback already used elsewhere, so the preflight gate can actually run on a fresh CI checkout where the untracked local signing config doesn't exist.
- **Chore**: Bump the interim project version to `0.5.97` to unblock the preflight version-sync gate after reconciling stacked remediation branches; the real product version/App Store number bump is deferred to upcoming release-prep work.
- **Chore**: Reconcile the pre-public-beta remediation stack's conflict resolutions (model catalog architecture, PythonBridge injection fix, unredacted-path-logging fix, and related Python/Swift merges) cleanly onto this branch's own history.

## 2026-07-03

### Pre-public-beta remediation (T0-T14)
Full ticket detail in `docs/backlog/pre_public_beta_audit_remediation_2026-05-13.md` and `docs/backlog/pre_public_beta_audit_tickets.md`.
- **Feature**: Replace the single DOCX `ShareLink` with an explicit choice between **Send Final Redacted Copy** (creates a separate copy, accepts Marcut's redaction Track Changes into it, and runs maximum-privacy metadata scrubbing before sharing) and **Send Review Copy** (requires explicit confirmation that Track Changes and metadata may still contain recoverable original text) (T1).
- **Security**: Replace the legacy `MARCUT_ALLOW_REMOTE_OLLAMA` override with an explicitly-named `MARCUT_DEVELOPER_UNSAFE_ALLOW_REMOTE_OLLAMA` developer-only escape hatch; public runtime paths (Swift subprocess/environment sync and Python's `get_ollama_base_url`) now strip or ignore both variable names so inference stays loopback-only by default and can't be silently redirected to a remote host (T2).
- **Security**: Apply owner-only `0o600` permissions to all sensitive report artifacts — JSON and HTML audit/scrub/metadata reports from both the Python writers and Swift-side writes/exports (T3).
- **Fix**: Make `--llm-detail` observe the actual production enhanced extraction path (instead of a separate non-chunked extractor) so detail mode no longer changes redaction output, while still emitting timing metadata and preserving normal failure semantics (T4).
- **Feature**: Forward `--backend llama_cpp --llama-gguf <path> --threads <n>` end-to-end into the unified redaction pipeline and the enhanced GGUF backend, fail clearly when no GGUF path is provided, and thread the configured seed/temperature through Ollama chunk-extraction and validation requests instead of hardcoding them (T5).
- **Reliability**: Add a cancellation/deadline system — `marcut/cancellation.py` (`ProcessingDeadlineExceeded`, `processing_deadline()`, `check_processing_deadline()`) reads `MARCUT_PROCESSING_DEADLINE_MONOTONIC`; Ollama HTTP requests, LLM timing, validation, and enhanced thread-pool waits now check the deadline and bound their timeouts to remaining processing time. Swift's `PythonKitRunner` sets/clears the deadline marker per phase and now calls `PyErr_SetInterrupt()` immediately on user stop instead of waiting on the async cancellation path (T6).
- **Reliability**: Make redaction finalization transactional — DOCX, audit JSON/HTML, and scrub JSON/HTML are staged to same-directory hidden temp files first and only `os.replace()`d into final names once the whole artifact set is written successfully, with temp files cleaned up on any failure or cancellation (T7).
- **Reliability**: Add an idle-output watchdog to the `ollama pull` CLI fallback (terminates stalled pulls with an actionable error) and wait for `/api/show` readiness after a model appears on disk, both at download-completion time and again before processing starts, closing a race where a model looks installed but isn't yet ready to serve requests (T8).
- **Security**: Bound metadata capture and report serialization sizes — embedded binary parts are summarized by default instead of retaining raw bytes, custom XML/fast-save/unknown-namespace previews are truncated under `MARCUT_METADATA_CAPTURE_MAX_STRING_CHARS`, and report JSON now applies string/list/dict budgets (`MARCUT_METADATA_REPORT_MAX_STRING_CHARS`, `MARCUT_METADATA_REPORT_MAX_LIST_ITEMS`, `MARCUT_METADATA_REPORT_MAX_DICT_ITEMS`) with warning codes for truncated values; explicit forensic/binary export remains available but bounded and owner-only (T9).
- **Performance**: Bound consistency-pass candidate/pattern scans with explicit environment-configurable budgets (total candidates, fuzzy ORG candidates, regex pattern text size) to prevent pathological unique-ORG scans on large documents, and add a synthetic large-DOCX production-path performance gate exercising body text, tables, headers/footers, comments, and metadata through `pipeline.run_redaction(..., mode="rules")` (T10).
- **Security**: Make release notarization fail closed — `scripts/notarize_macos.sh` no longer treats a pending notarytool status as success or swallows a failed post-staple Gatekeeper check with `|| true`; `build_appstore_release.sh` exits on code-signature verification failure; all notarization-skip paths (missing keychain profile, explicit skip) now require an explicit `MARCUT_ALLOW_NOTARIZATION_SKIP=1` override; the tag/nightly E2E workflow gained a fail-closed prerequisite step requiring signing identity and notarization secrets before a release-tag job can proceed (T11).
- **Security**: Generate the Python SBOM from actual shipped bundle components rather than direct dependency pins — `scripts/generate_python_sbom.py` now walks the staged `python_site` (or a built `MarcutApp.app` via `--bundle-root`) for transitive PyPI packages, SwiftPM dependencies from `Package.resolved`, and manual-review entries for the BeeWare `Python.framework` and embedded Ollama binary; `docs/release/python-sbom.json` regenerated (23 shipped components); `check_dependency_vulnerabilities.py` gained `--sbom` to scan shipped components via OSV (T12).
- **Docs**: Refresh `docs/release/public_beta_qualification.md` with current `0.5.96`+ evidence (superseding the stale `0.5.95` note), document the two DOCX send paths, and update release-checklist/SBOM guidance to point at the actual built app bundle (T13).
- **Security**: Add `scripts/verify_entitlements.sh` and `docs/release/entitlement_governance_verification.md` to verify built app/helper entitlements contain no forbidden debug/runtime-bypass entries, and wire final entitlement/SBOM/vulnerability/stapler/Gatekeeper checks into `build_tui.py` after Developer ID builds; document repository governance evidence (CODEOWNERS, PR template, CI workflows, branch protection ruleset) (T14).

### New features
- **Feature**: Add a search bar to `SettingsView` to filter settings sections and redaction rules.
- **Feature**: Add a native macOS notification when a model download completes.
- **Feature**: Add a "Retry Failed" button to re-queue only failed documents in a batch.
- **Feature**: Add an in-app log viewer sheet to Settings.
- **Feature**: Add export/import of redaction settings as a JSON profile.
- **Feature**: Add a live match preview to the excluded-words editor.
- **Feature**: Show estimated time remaining during batch redaction.
- **Feature**: Persist pending batch jobs and offer to resume them after an app restart.
- **Refactor**: Centralize UserDefaults keys into a typed `DefaultsKey` enum.
- **Refactor**: Unify model-name parsing between `gui.py` and `PythonBridge.swift`.
- **Refactor**: Move hardcoded Ollama model tags/parameters into a shared `models.json`, mirrored across `assets/`, `src/python/marcut/`, and Swift resources, with `model_config.py`/`ModelCatalog.swift` loaders and a `BundleResourceLocator.swift` helper for dev/production bundle resolution — pure data-location change, no recommendation-behavior change.
- **Build**: Add `scripts/release_preflight.sh`, gating automatable `RELEASE_CHECKLIST` steps (Python/Swift tests, SBOM generate+check, dependency vulnerability audit, markdown link check, version-sync, secrets check) into CI ahead of `macos-build-verify` and the release checklist.

## 2026-05-13
- **Fix**: Stop treating plain legal terms such as `Agreement` as `DOCID` redactions.
- **Fix**: Preserve specific legal entities such as `TIME USA, LLC` through ORG filtering instead of suppressing them as generic contract wording.
- **Fix**: Add derived alias redaction for entity-name aliases such as `TIME` while preserving generic roles such as `Publisher`.
- **Performance**: Align LLM timing benchmark extraction with the production Ollama context, prediction, and timeout budget.
- **Build**: Update App Store packaging for embedded Ollama 0.23.2 runtime bundling and helper signing.

## 2025-12-28
- **Docs**: Refine changelog style to use category prefixes
- **Docs**: Update changelog with full history back to origin
- **Refactor**: Move project docs to docs/ directory
- **Docs**: Docs cleanup: Update Changelog and remove redundant help file
- **Refactor**: Cleanup project root and ignore test artifacts

## 2025-12-26
- **Fix**: Fix regex performance: Implement O(N) Linear Token Scanning
- **Fix**: Fix regex: restore Company suffix, fix trailing space for connector patterns
- **Fix**: Fix regex over-redaction & enhance exclusions
- **Fix**: Fix unescaped quotes in DATE rule description
- **Fix**: Fix deinit actor isolation: move log cleanup to OllamaLogger.deinit
- **Refactor**: Refactor Ollama logging to use thread-safe OllamaLogger class
- **Fix**: Fix Swift actor isolation error in Ollama log writing
- **Fix**: Fix Address regex failure on multi-word capitalized street names
- **Update**: Extend Rule #4 to treat excluded words as generic in ORG detection
- **Fix**: Fix generic over-redaction of defined terms like 'The Company'
- **Fix**: Expand ORG pattern with comprehensive entity suffixes
- **Feature**: Add Trust and related entity types to ORG pattern
- **Feature**: Add PERCENT as separate GUI rule checkbox
- **Feature**: Add PERCENT pattern for numeric and spelled-out percentages
- **Fix**: Fix spelled-out money pattern to match multi-word amounts
- **Fix**: Fix startup hang and bundle help.md
- **Update**: Revert to altool for App Store submission (notarytool is for Developer ID only)

## 2025-12-25
- **Fix**: Fix code signing for App Store: sign all dylibs including llama_cpp
- **Update**: Successful app store upload 12.25.25
- **Fix**: New excluded words logic + ollama logging works
- **Security**: Post-security review hardening
- **Update**: Sync HELP.md and excluded-words.txt from assets/
- **Fix**: Fix DMG output path to .marcut_artifacts/ignored-resources/
- **Ui**: Rename main action button to 'Redact & Scrub'
- **Fix**: Fix Ollama log capture + scrub report status logic
- **Fix**: Fix Ollama streaming JSON + comprehensive test suite
- **Fix**: Add Info.plist generation and AppIcon copying
- **Fix**: Handle absolute paths in Ollama extraction and update resource paths

## 2025-12-24
- **Fix**: Correct paths in build scripts for new directory structure
- **Refactor**: Update build config for src/ layout
- **Refactor**: Final cleanup of root directory
- **Refactor**: Reorganize project structure for GitHub publication
- **Refactor**: Pre-cleanup file reorg
- **Fix**: Fix LLM debug logging to use _log_app_event instead of stderr
- **Feature**: Add sync_python_sources to all TUI build presets
- **Fix**: Fix ollama.log to actually capture Ollama output
- **Fix**: Sync root marcut/ folder with Sources fixes
- **Fix**: Fix scrub report icon detection with fuzzy filename matching
- **Fix**: Fix processing timeouts and encoding errors
- **Fix**: Fixing redaction bugs

## 2025-12-23
- **Update**: Good progress but action buttons missing
- **Update**: Metadata scrub no longer corrupting

## 2025-12-22
- **Fix**: Fix None preset corruption and missing report values
- **Feature**: Implement accurate before/after values for newly exposed settings
- **UI**: Expose 6 hidden metadata settings in UI, Presets, and Report
- **Feature**: Improve None preset detection and add before/after scrub report
- **Fix**: Fix corrupt output with None preset and improve report
- **Feature**: Add metadata scrub report icon and file output
- **Update**: Apply conditional hardening to main redact flow too
- **Fix**: Fix corrupt output when None preset selected
- **Fix**: Fix crash: Use safe .get() for Python dict access
- **Fix**: Fix crash: Python scrub_metadata_only return signature mismatch
- **Fix**: Fix unzip glob pattern for [Content_Types].xml
- **Feature**: Add secure zero-then-delete for temp validation files
- **Fix**: Fix false corrupt DOCX detection in sandbox
- **Refactor**: Wire all tests into TUI menu + cleanup legacy files
- **Feature**: Add comprehensive test suite for metadata scrubbing
- **Fix**: Metadata scrubbing overhaul + critical bug fixes (UNTESTED)
- **Feature**: Add enhanced DOCX validation, build caching, and dependency version checker
- **Fix**: Revert metadata scrub to worker.perform - fix deadlock regression
- **Fix**: Fix metadata scrub crash, comprehensive help.md rewrite with section numbers
- **Feature**: Metadata scrubbing implemented submission to App Store ready

## 2025-12-21
- **Feature**: Comprehensive metadata UI improvements and hyperlink fix
- **Fix**: Add clear BUILD COMPLETE banner with DMG path at end of TUI builds
- **Wire**: Connect metadata settings from Swift UI to Python pipeline
- **Feature**: Add granular metadata cleaning settings
- **Chore**: Expand .gitignore to reduce VS Code warnings
- **Chore**: Cleanup obsolete files and scripts
- **Chore**: Add ollama_binary to Git LFS for faster clones
- **Fix**: App Store and DMG builds working - Ollama signing fixed
- **Compliance**: Fix Ollama sandbox crash, update paths, and enable strict address detection

## 2025-12-20
- **Feature**: Release 2.1: Performance Boost & Address Detection
- **Feature**: Add GGUF auto-discovery to model benchmark
- **Feature**: Add model benchmark test rig for speed vs accuracy comparison
- **Feature**: Add performance optimization documentation with profiling insights
- **Feature**: Add --llm-detail flag for detailed LLM sub-phase timing
- **Feature**: Add --timing flag to CLI for phase-by-phase performance profiling
- **Fix**: Help window path lookup and redaction label fonts
- **Performance**: Everything working and we are going to update the health file now and then commence performance upgrades
- **Feature**: Excellent progress toward completion security implemented and knits remain remaining

## 2025-12-19
- **Update**: Notice banner working
- **Update**: All redaction tags firing
- **Fix**: Headers and footnotes working: Fix XML redaction persistence and resolve Swift build issues
- **Fix**: Fix UI clicks, formatting leaks, and enable Header/Footer redaction
- **Update**: Working again, formatting edge cases remain
- **Fix**: Acceptance of changes is now fixed

## 2025-12-18
- **Feature**: Accept tracked changes and stabilize progress
- **Feature**: Add Reveal Models button (halfway implemented, except track changes)
- **Docs**: Add notarization + sharing notes
- **Test**: Will tested and all is working

## 2025-11-30
- **Chore**: Skip URL/rule suites when marcut deps unavailable
- **Chore**: Remove backup and simplify ollama logging

## 2025-11-29
- **Update**: Everything working all at once leaving only fine-tuning of the reduction model itself as the next step
- **Update**: Far afield and redaction still failing

## 2025-11-27
- **Fix**: Fix XPC integration: resolve duplicate executionStrategy property and bridgeLog scope issue

## 2025-11-25
- **Fix**: Drop numpy dependency and simplify enhanced model
- **Chore**: Fix Python stub linking for arm64
- **Chore**: Relocate legacy runtime blobs to old-and-cold
- **Chore**: Quarantine legacy artifacts
- **Chore**: Point python payload to bundled sources
- **Fix**: Honor custom host and drop numpy dependency
- **UI**: Stuck on downloads and rules redaction requiring a model in place.
- **Chore**: Prune build artifacts and vendor bundles
- **Update**: Download working, redection fails

## 2025-11-24
- **UI**: Stuck on downloads and rules redaction requiring a model in place

## 2025-11-21
- **Feature**: Prepare App Store distribution for external LLM review
- **Build**: Trying to get an app store build
- **Fix**: Simplify signing process by skipping problematic framework signing
- **Fix**: Resolve codesign syntax errors and improve Python framework handling
- **Fix**: Resolve codesign bundle format ambiguous error for Python framework
- **Feature**: Wire up actual App Store certificate and provisioning profile
- **Fix**: Add certificate detection and validation for App Store signing

## 2025-11-20
- **Fix**: Add robust error handling for framework and resource copying
- **Feature**: Add Swift Package Manager App Store distribution to build TUI
- **Fix**: Good enough progress bar

## 2025-11-19
- **Fix**: Smooth chunk progress updates
- **Update**: Solid save point
- **Fix**: Make ProgressTracker compatible with simple Swift heartbeat callbacks

## 2025-11-18
- **Feature**: Eliminate repeated permission dialogs with session-based management
- **Chore**: Remove backup zip
- **Update**: Permissions good, progress bar goes backwards
- **Feature**: Implement permission system that requests access only when files are accessed

## 2025-11-16
- **Fix**: Ensure rule filters sync to python
- **Fix**: Good GUI and checkboxes unwired - fixed cancellation flag persistence issue
- **UI**: GUI good, checkboxes unwired, 1st document still cancels

## 2025-11-15
- **Docs**: Add override + dev_fast notes
- **UI**: GUI with serial pipeline working

## 2025-11-14
- **UI**: GUI working again, Rules only and AI

## 2025-11-07
- **Fix**: Implement hybrid CLI subprocess + AsyncStream solution - beachball fixed, progress stuck
- **UI**: GUI Working again but beachball while working
- **Feature**: Implement descriptive filename scheme for unified testing
- **Feature**: Implement unified subprocess pipeline architecture for CLI and GUI
- **Feature**: Add flexible test mode infrastructure for MarcutApp

## 2025-11-06
- **Feature**: Add comprehensive test suite and documentation for Marcut redaction pathways

## 2025-11-04
- **Feature**: Add memory management improvements and enhanced error recovery
- **Fix**: Fix GUI 30-second timeout issue and critical bugs preventing full redaction functionality

## 2025-11-03
- **Baseline**: Commit broken state with 30s GUI timeout issue

## 2025-11-01
- **Fix**: Gui loads but ollama times out after 30s
- **Chore**: Cleanup

## 2025-10-31
- **Chore**: Refresh embedded python runtime
- **Chore**: Snapshot working helper build

## 2025-10-30
- **Docs**: Capture macOS app architecture
- **Docs**: Note embedded interpreter diagnostics
- **Chore**: Drop pythonkit warm-up diagnostics
- **Chore**: Gate pythonkit diagnostics behind flag

## 2025-10-25
- **Fix**: Apply final architectural corrections to PythonBridge

## 2025-10-24
- **Feature**: Add log cleanup to App Store build script
- **Feature**: Add automatic log file cleanup to build script
- **Fix**: Apply corrected XPC architectural patches to resolve bind errors
- **Feature**: Complete XPC architectural implementation to resolve network binding issues
- **Fix**: Remove nested git repository and add .build/ to .gitignore
- **Feature**: XPC service fully functional - command line version is fully redacting

## 2025-10-23
- **Fix**: Resolve critical Ollama startup crashes and implement robust process management
- **Fix**: Resolve compilation errors for singleton pattern
- **Feature**: Add thread-safe singleton pattern to PythonKitRunner

## 2025-10-12
- **UI**: GUI working. Yay!

## 2025-10-11
- **Update**: Model loads but AI redaction stalls

## 2025-09-27
- **Chore**: Last version before bee packaging
- **Fix**: Ensure embedded Python framework loads again

## 2025-09-22
- **Fix**: Fix Python framework placement and add diagnostic logging - ensure Python.framework is in Contents/Frameworks and improve error reporting
- **Fix**: Fix Python dependencies and improve error logging - add llama-cpp-python with Metal support and better Python error reporting

## 2025-09-21
- **Update**: Model download and framework working again but redaction fails
- **Update**: Ollama still broke; trying load the .gguf model file directly from a path

## 2025-09-20
- **Fix**: Comprehensive LLM connectivity and model download fixes
- **Feature**: Struggling with LLM connection failure - model download failing

## 2025-09-18
- **Build**: Swift UI, DMG build, redactions not failed

## 2025-09-14
- **Update**: Swift and redaction working, tweaks next

## 2025-09-01
- **Feature**: Beautiful SwiftUI interface ready for demo (track changes needs work)

## 2025-08-30
- **Refactor**: 🧹 MAJOR CLEANUP: Organized project structure with archive
- **UI**: 🎉 WORKING GUI: Deterministic startup with embedded Ollama
- **Update**: Final version before DMG bundling attempt
- **Update**: Enhanced signature block detection for consistent name extraction
- **Feature**: Improve MONEY detection for bracketed amounts; introduce NUMBER label and rules; enhance prompt to differentiate MONEY vs NUMBER
- **Update**: Incremental progress towards accuracy
- **Feature**: Initial working enhanced redaction (two-pass LLM + rules) with track-changes DOCX output, CLI flag, and docs

## [0.2.3] - 2024-09-14

### Fixed
- **Critical**: Resolved Ollama API timeout issue that was blocking all document redaction
  - Root cause: Complex `ollama_extract_enhanced()` prompts were overwhelming the model
  - Solution: Modified `model_enhanced.py` to use simpler `ollama_extract()` function
  - Increased timeouts from 30s to 60s for larger document chunks
  - Disabled JSON format constraint that was causing llama3.1:8b model to hang

### Changed
- Updated progress tracking to show all 7 processing phases correctly
- Enhanced error handling in model extraction pipeline
- Improved Swift-Python bridge with proper environment configuration

### Added
- Comprehensive test suite (`test_like_swift.py`) for validating pipeline functionality
- DMG packaging script (`scripts/sh/build_swift_only.sh`) for distribution
- Progress tracking across all redaction phases

### Working Features
- ✅ Swift GUI processes documents successfully with progress tracking
- ✅ Python CLI full redaction pipeline operational
- ✅ Ollama integration stable with 60-second timeouts
- ✅ All 7 progress phases display correctly
- ✅ DMG packaging (MarcutApp-Swift-v0.2.3.dmg) ready for distribution
- ✅ Microsoft Word track changes generation
- ✅ Both rule-based and LLM entity extraction functional

### Test Results
- Successfully processed Compliance-Cert.docx: 46 entities detected
- Successfully processed loan-term-sheeet.docx: 30 entities detected
- All sample documents process without timeouts

## [0.2.2] - 2024-09-13

### Added
- SwiftUI native macOS application
- Embedded Ollama binary for self-contained distribution
- Professional DMG creation with code signing support

## [0.2.1] - 2024-08-30

### Added
- Enhanced two-pass LLM validation pipeline
- Document-level context analysis
- Selective entity validation based on confidence scores

## [0.2.0] - 2024-08-17

### Added
- Track changes support for Microsoft Word documents
- JSON audit reports with entity details
- Rule-based detection for structured PII

## [0.1.0] - 2024-07-28

### Initial Release
- Basic redaction functionality
- CLI interface
- Ollama integration for LLM-based detection
