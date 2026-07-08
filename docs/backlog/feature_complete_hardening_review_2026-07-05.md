# Feature-Complete Hardening Review — 2026-07-05

Status: **unvalidated candidate list.** Produced by a code survey (three parallel read-only
agents over the Python core, Swift app, and repo/OSS hygiene). File/line references are
approximate and every claim needs confirmation against the code before acting — that
confirmation is the first task for whoever picks an item up. Items already tracked in
`docs/BACKLOG.md` or `docs/design/` are referenced, not re-derived (see final section).

For each item: **Claim** (what's believed wrong or missing), **Where** (starting point),
**Validate** (how to confirm or refute it cheaply). If validation refutes the claim, close
the item with a note rather than forcing a fix.

Suggested order of attack: A1 → A2 → A4 → E1/E2 (pre-publication, time-sensitive) → D1.

**GitHub issues filed 2026-07-05** (labeled `afk` for the workflow-loop): A1 #36, A2 #37,
A3 #38, A4 #39, A5 #40, A6 #41, A7 #42, B1 #43, B2 #44, B3 #45, B4 #46, B5 #47, B6 #48,
B7 #49, B8 #50, C1 #51, C2 #52, C3 #53, D2 #54. Section E was resolved directly (see
below); D1/D3–D5 have no issues yet — D1's design spike is
`docs/design/interactive_redaction_mode.md`.

---

## A. Redaction accuracy & correctness (highest stakes — missed PII is product failure)

### A1. Build a precision/recall evaluation harness
- **Claim:** Nothing in `tests/` or `scripts/` measures detection quality. Every other
  accuracy item below is unfalsifiable without this.
- **Shape:** Small synthetic labeled DOCX corpus (per entity type, per document part),
  a scorer comparing pipeline output spans to labels, per-type precision/recall report,
  CI gate with regression thresholds.
- **Validate:** Confirm absence of any eval harness; then confirm the JSON audit report
  contains enough span data to score against labels without pipeline changes.

### A2. Verify redaction coverage of all DOCX document parts
- **Claim:** `apply_replacements()` in `docx_io.py` (~line 1363) may apply track changes
  only to the main document body; tables/headers/footers may be scanned at build time but
  not written back, and footnotes/endnotes/comments/textboxes/content controls may not be
  scanned at all. Any unscanned part is silent PII leakage.
- **Validate:** Craft one DOCX with distinct PII in body, table cell, header, footer,
  footnote, comment, and textbox; run redaction; inspect the output XML per part for
  `w:ins`/`w:del` revision elements. Document confirmed coverage in USER_GUIDE either way.

### A3. Chunk-boundary entity handling in enhanced extraction
- **Claim:** Offset adjustment at `model_enhanced.py:1087–1120` can drop or mis-offset
  entities that straddle the chunk overlap window.
- **Validate:** Unit test placing a known name exactly across the boundary; assert it is
  detected once with `text[start:end] == entity_text`.

### A4. Fail-open behavior on partial chunk failure
- **Claim:** If chunk N errors (`model_enhanced.py:1055–1082`), chunks N+1..M are skipped
  and output is still written without telling the user which text ranges went un-analyzed.
  A privacy tool should fail closed, or at minimum disclose unprocessed ranges prominently
  in the report **and** the app UI.
- **Validate:** Inject a timeout on chunk 2 of 5 (mock LLM); inspect report and Swift-side
  status for any disclosure.

### A5. Bounds/consistency guard on LLM spans before applying replacements
- **Claim:** `pipeline.py:1336–1363` applies spans without checking `0 <= start < end <= len(text)`
  or that `text[start:end]` matches the entity text; drifted offsets corrupt output silently.
- **Validate:** Feed out-of-range and drifted spans via the mock LLM; observe behavior.
  Fix shape: drop-and-log mismatches, count them in the report.

### A6. Rules-layer accuracy batch (small regex/test fixes in `rules.py`)
- SSN pattern (~line 289) misses undashed 9-digit SSNs ("SSN: 123456789").
- Phone pattern (~279–286) can swallow account numbers ("Account 1234567890 balance").
- Address matcher (~610–696) accepts invalid state codes ("123 Main St ZZ 12345").
- Exclusion normalization (`_is_excluded`, ~95–130) may miss possessives ("Company's").
- **Also:** make an explicit, documented scope decision on international IDs (UK NI, IBAN,
  passport numbers) vs. US-only — either add patterns or state the limitation in docs.
- **Validate:** Each with its cited counter-example as a new test.

### A7. LLM JSON-response parsing robustness
- **Claim:** `model.py:84–103` extracts JSON by regex; after one self-correction attempt a
  RuntimeError is raised (~706–711) with no tolerant fallback.
- **Shape:** Use Ollama structured outputs (`format` with a JSON schema) to eliminate the
  failure class at the source; add tolerant repair as a fallback.
- **Validate:** Replay a corpus of malformed outputs through `parse_llm_response`; confirm
  the shipped Ollama version supports schema-constrained output.

---

## B. App robustness (Swift side)

### B1. Watchdog for the embedded Python worker
- **Claim:** A segfault/hang in embedded Python (e.g., lxml on a corrupt DOCX) leaves the
  worker thread (`PythonKitBridge.swift:249–314`) hung and the UI frozen; only force-quit
  recovers.
- **Validate:** Confirm no watchdog/crash-handler exists; reproduce with a deliberately
  hung Python call. Fix shape: watchdog timer + user-facing "processing stalled" recovery.

### B2. Pre-flight checks before long runs
- **Claim:** `validateDestination()` (`DocumentRedactionViewModel.swift:~853`) checks
  existence only — not writability or free disk space — so a 30-minute run can fail at the
  final write. Same for model downloads (no free-space check before a multi-GB pull).
- **Validate:** Read `validateDestination`; test against a read-only destination.
  Fix shape: test-write to destination + free-space estimate before starting.

### B3. Ollama port conflict with a user-installed Ollama
- **Claim:** `findFreePort` (`PythonBridge.swift:~722–731`) bind-tests at selection time
  but a user's own Ollama racing onto the port yields silent inference failures against
  the wrong server.
- **Validate:** Reproduce with a second Ollama; fix shape: post-spawn identity check
  (canary request verifying it's our instance/model set) + a specific error message.

### B4. Sanitize user-facing error messages
- **Claim:** Raw strings like `PK_ENHANCED_OLLAMA_PYERROR: type=NameError message=…` and
  truncated tracebacks (`PythonKitBridge.swift:~1338–1348`) reach ContentView alerts.
- **Validate:** Grep alert paths for raw error interpolation. Fix shape: error-code →
  friendly-message map, with a "Show details" disclosure and a pointer to the in-app log
  viewer (which already exists).

### B5. Sleep/wake handling and power assertion during processing
- **Claim:** No `IOPMAssertionCreateWithName` or wake observer exists; closing the lid
  mid-batch hangs processing with no recovery.
- **Validate:** Grep for IOPM/NSWorkspace wake notifications; reproduce with a lid-close.
  Fix shape: hold a power assertion while processing; on wake, health-check and resume/fail
  cleanly.

### B6. Resume-after-quit output integrity
- **Claim:** The resume path (`ContentView.swift:~475–494`, `PendingBatchJobStore`) offers
  to resume without verifying whether the in-flight document's output was partially
  written. (Python-side writes are transactional — verify whether that guarantee actually
  extends through the Swift resume path, or whether stale staged artifacts can surface.)
- **Validate:** Kill the app mid-document in a 5-doc batch; resume; audit outputs.

### B7. Heartbeat timeout hard-fails without retry
- **Claim:** `heartbeatTimeout = 120s` (`DocumentRedactionViewModel.swift:~186`) fails the
  document permanently; heavy LLM inference can legitimately stall heartbeats that long.
- **Validate:** Check whether heartbeats are emitted *during* a long single Ollama call or
  only between steps — if the latter, either emit finer-grained heartbeats (pairs with the
  `streaming_progress.md` spike) or add a grace/retry path.

### B8. Error-path test coverage (both suites)
- **Claim:** `MarcutAppTests.swift` (~25 tests) covers catalogs/settings/UI state but no
  failure scenarios (disk full, port conflict, crash recovery, resume integrity). Python
  tests lack a malformed-DOCX corpus and property-based tests for chunk/offset invariants.
- **Validate:** Enumerate tests; confirm gaps. Fix shape: failure-injection tests around
  `PythonBridge`/view-model; `hypothesis` tests asserting span invariants across random
  chunkings; a small corpus of deliberately malformed DOCX files.

---

## C. Performance

### C1. Consistency pass is O(candidates × document length)
- **Claim:** `pipeline.py:~730–772` runs `regex.finditer` over the full document once per
  candidate; 200 ORG candidates → 200 full-document scans.
- **Validate:** Profile a synthetic 200-ORG document. Fix shape: single pass with a
  combined alternation or Aho–Corasick over all candidates.

### C2. Metadata scrub rewrites the whole ZIP in memory
- **Claim:** `docx_io.py:~735–955` loads all parts into memory to rewrite the archive;
  peak RSS blows up on very large DOCX files.
- **Validate:** Measure peak RSS scrubbing a 100 MB DOCX. Fix shape: stream part-by-part
  to the staged output ZIP.

### C3. Verify LLM request concurrency actually parallelizes
- **Claim:** The futures pool (`model_enhanced.py:~909–975`) may serialize at the Ollama
  server (Ollama queues per-model unless `OLLAMA_NUM_PARALLEL` is set), making the pool
  cosmetic. Also check the validation buffer (~:902) actually flushes in bounded batches.
- **Validate:** Profile a 50-chunk run at concurrency 1 vs 4; inspect what env/config the
  embedded Ollama is launched with. Note: raising parallelism raises memory; needs a
  documented trade-off, not just a flag flip.

---

## D. Customer experience

### D1. Interactive review/approve before writing output — **promote the existing spike**
- Already designed: `docs/design/interactive_redaction_mode.md`. One-shot redaction is the
  single biggest CX limitation (over-redaction forces full batch re-runs). Recommend this
  as the first post-feature-complete feature; the review task is to pressure-test the
  spike, not redesign it.

### D2. Real fractional progress + honest ETAs — **existing spike**
- `docs/design/streaming_progress.md` covers token-stream progress. Pair with fixing
  `BatchETACalculator`'s linear extrapolation from early samples (small fast docs first →
  wildly optimistic ETA for the rest). Validate the extrapolation claim by reading the
  calculator, then weight by per-document size.

### D3. Accessibility labels on progress/status views
- **Claim:** `BatchETAView` (`ContentView.swift:~325`) and `HeartbeatStatusView`/progress
  rows (~1410–1430) have `accessibilityIdentifier` but no `.accessibilityLabel`/`Hint`;
  VoiceOver users can't follow processing state.
- **Validate:** VoiceOver pass over the main flow. Cheap, high-polish-signal fix for OSS.

### D4. Update mechanism for a DMG-distributed app
- **Claim:** No Sparkle and no launch-time version check exist; users outside the App
  Store never learn about security/bug-fix releases — notable for a privacy tool.
- **Validate:** Confirm absence. Fix shape: Sparkle 2 (sandbox-compatible) or a minimal
  signed check against GitHub Releases with a notification. Flag: adds a network call to a
  "local-first, no external calls" app — must be opt-in/documented and off by default.

### D5. Localization — deliberate deferral
- All UI strings are hardcoded English. Recommend explicitly deferring, but wrap new
  strings in `String(localized:)` going forward so the door stays open. Document
  "English-only UI" as a known limitation in the README.

---

## E. OSS publication readiness — ✅ RESOLVED 2026-07-05 (repo was already public; verified clean)

The repo (github.com/LegalMarc/marcut) was already public when this section was actioned.
Exposure audit result: **no confidential files were ever published.** The public tree
(254 files, ~3.7 MB) contains no .docx/.doc/.pdf; no commit reachable from any GitHub ref
ever touched `sample-files/`; the three old local commits that did commit sample files
exist only on local `backup-*`/`codex/beta-audit-*` branches and GitHub returns
"no commit found" for their hashes (which covers deleted-branch leftovers).

### E1. Confidential test files — ✅ verified never public; guard added
- `sample-files/` is gitignored (plus a global `*.docx` ignore) and untracked. A CI
  `hygiene` job now fails any push/PR that tracks `*.docx/doc/pdf/dmg` or `sample-files/`
  (defense in depth against `git add -f`). Real confidential test files stay local-only.
- Residual (local machine only, not public): local packs are ~18 GiB and local backup
  branches still contain the old sample-file commits — optional local cleanup, owner's call.

### E2. Author identities — ✅ no rewrite needed; .mailmap added
- Public `main` contains only `mhm/apps@marclaw.com` + the LegalMarc noreply address (all
  "Marc Mandel"); laptop-hostname emails exist only on local branches. Root `.mailmap` now
  unifies all identities to the LegalMarc noreply address for git tooling. Optional: add
  `mhm/apps@marclaw.com` as a verified email on the GitHub account so those commits link
  to the profile (GitHub does not read .mailmap).

### E3. Licensing/attribution — ✅ done
- Added `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, contact security@marclaw.com) and
  `THIRD_PARTY_LICENSES.md` (BeeWare/PSF, Ollama/MIT, PythonKit/Apache-2.0, all pinned
  Python deps). Verified `docs/release/python-sbom.json` contains the BeeWare
  manual-review entries claimed in the T12 changelog note.

### E4. CI lint gates — ◐ partial
- Added a ruff error-tier gate (`--select E9,F63,F7,F82`) to `ci.yml`; it passes after
  fixing two real F821 bugs in `gui.py` (lambdas capturing an out-of-scope `except` var —
  the download-error dialog would have raised NameError). Migrated the deprecated
  top-level ruff keys in pyproject.toml to `[tool.ruff.lint]`.
- **Remaining:** burn down the 276 outstanding E/F/B violations (119 auto-fixable via
  `ruff check --fix`) then tighten the CI gate to the full rule set; add
  SwiftFormat/SwiftLint for the Swift side (neither is configured yet).

### E5. README landing page — ✅ mostly done
- Added a prominent macOS-only platform callout, a Distribution section (DMG via GitHub
  Releases; Homebrew/PyPI explicitly "not yet available"), CoC and third-party-license
  links, and fixed the license badge owner path (`marclaw` → `LegalMarc` — this makes the
  unmerged `fix/badge-owner-path` remote branch redundant; it can be deleted).
- **Remaining:** screenshots/demo GIF of the app.

### E6. Version-sync CI check — ✅ done
- The `hygiene` CI job now compares `pyproject.toml` version against
  `build-scripts/config.example.json` (both 0.5.97) on every push/PR.

---

## Already tracked — deliberately excluded here

These are in `docs/BACKLOG.md` / `docs/design/` with spikes and should be picked up from
those docs, not re-derived: docx_io package split, SettingsView/DocumentRedactionViewModel
decomposition, bridge schema migration, multi-model orchestration, local RAG across
document sets, WASM/browser deployment, incremental track-changes, redaction rationale
reporting. (D1 and D2 above intentionally *promote* two of the spikes rather than restate
them.)
