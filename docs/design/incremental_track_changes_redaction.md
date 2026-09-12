# Design Spike: Incremental (Diff-Only) Track-Changes Redaction for Revised Documents

Status: Design spike (no code changes). Companion to issue #31, item "Incremental
Track-Changes Support" in `backlog.md`'s "Major New Directions" section.

## Goal

Contract revisions are usually small: a redline round-trips with a handful of
paragraphs touched out of dozens or hundreds. Today, every redaction run —
including a re-run on v2 of a document that's 95% identical to v1 — re-chunks
and re-sends the *entire* document text through the LLM extraction pipeline
(`IntelligentRedactionPipeline.process_document()` in `model_enhanced.py`,
fed by `chunker.make_chunks()`). For a large contract, that's minutes of
Ollama wall-clock time spent re-discovering entities that were already found
and redacted in the previous pass. This doc evaluates whether we can instead
identify only the paragraphs that changed between two versions and run LLM
extraction on those alone, and — because this is a redaction tool, not a
diffing tool — spends most of its length on what happens if that
identification is wrong.

## Current State (what a "diff-only" feature would sit on top of)

Two facts about the existing pipeline are load-bearing for this whole
proposal:

1. **The pipeline already destructively flattens track changes before doing
   anything else.** `DocxMap.load_accepting_revisions()`
   (`docx_io.py:347-353`) calls `accept_revisions_in_docx_bytes()`
   (`docx_revisions.py:200`), which walks `word/document.xml` (and headers,
   footers, footnotes, endnotes, comments) and does the equivalent of Word's
   "Accept All Changes": `w:del`/`w:moveFrom` content is dropped entirely,
   `w:ins`/`w:moveTo` wrapper tags are stripped (their content kept), and
   formatting-only revision markers (`w:rPrChange`, `w:pPrChange`, etc.) are
   removed (`docx_revisions.py:10-30, 183-184`). It also does "zombie
   paragraph" cleanup (removing paragraphs that only ever contained deleted
   content, `docx_revisions.py:85-118`) and whitespace-scar repair around
   deletion boundaries. **The accept/reject distinction — i.e., which text is
   "new" versus "always there" — is discarded at load time**, before
   `DocxMap._build()` ever constructs the flattened `text` string that
   `_collect_rule_spans()` / `_collect_enhanced_spans()` operate on
   (`pipeline.py:1532-1618`). This means the one place in the codebase that
   already parses `w:ins`/`w:del` is explicitly built to erase the
   information this feature would need, not preserve it.

2. **Chunking is already a flat, offset-based operation over that flattened
   text**, independent of paragraph structure. `chunker.make_chunks()`
   (`chunker.py:13-44`) takes `text: str` and returns
   `[{'start', 'end', 'text'}]` slices with `max_len=2500` chars and
   `overlap=400` chars, falling back to a single whole-document chunk under
   `SMALL_DOC_THRESHOLD=4000` chars. Chunks have no concept of "paragraph"
   or "section" — they're pure character windows. This is actually
   favorable for a diff-only feature: swapping in a smaller, sparser set of
   character ranges (only the changed spans, each padded with enough
   context) is a drop-in replacement for the *input* to
   `IntelligentRedactionPipeline.process_document()`, not a rearchitecture
   of the chunking or extraction machinery itself.

Two DOCX-level facts about what "the DOCX's own Track Changes/revision
metadata" actually is, worth being precise about since the ticket poses it as
an alternative to text-diffing:

- Track changes in an OOXML `.docx` are an **edit log relative to a single
  base document**, authored by whoever had Word's "Track Changes" toggle on
  while editing. They are not automatically "diff of v1.docx vs v2.docx" —
  they only exist, and only reflect the *intended* set of changes, if the
  editor (a) started from the prior version, (b) had track changes enabled
  for the entire editing session, and (c) didn't accept/reject and re-edit
  in ways that collapse the log. In legal practice this frequently breaks:
  redlines get accepted and a fresh round of changes started, changes get
  made with tracking off then tracking re-enabled, or the "v2" a client
  sends back was retyped from a clean copy rather than edited in Word at
  all.
- `docx_revisions.py` already demonstrates one failure mode concretely: the
  "zombie paragraph" and whitespace-scar handling exist *because* raw
  `w:ins`/`w:del` markup doesn't map cleanly onto "paragraph X is new" —
  insertions and deletions can be sub-paragraph, span paragraph boundaries
  (a deletion that removes a paragraph break, merging two paragraphs), or
  leave paragraphs that are structurally present but semantically dead. Any
  "added paragraph" detector built on this markup inherits all of that
  complexity, not a clean paragraph-level in/out list.

## Change-Detection Approach

Two independent mechanisms could identify "added paragraphs"; they are not
mutually exclusive; a real implementation likely needs both with metadata as
opportunistic fast-path and text-diff as the mandatory fallback.

### Option A — Trust the DOCX's own Track Changes metadata

Parse `w:ins` (and, more carefully, partial insertions inside otherwise
unchanged paragraphs) directly from `word/document.xml` — this time to
*extract* which paragraphs contain insertions, rather than to flatten them
away as `docx_revisions.py` does today. A paragraph (`w:p`) whose only
content changes are wrapped in `w:ins`, or that is entirely new (every run
inside it is `w:ins`), is a candidate "added paragraph."

- **Preconditions for correctness**: the document must actually carry
  track-changes markup (many client-returned "v2" files don't — they're a
  clean re-save), and that markup must reflect a real diff against the
  specific v1 the user is comparing against, not against some other base or
  a partially-accepted intermediate state.
- **Failure modes**:
  - **No revisions present at all** — the common case for a document that
    was edited with tracking off, or accepted-and-resaved. Silently falls
    back to "nothing changed" if not explicitly detected and rejected as a
    signal.
  - **Moved paragraphs** (`w:moveFrom`/`w:moveTo`): Word represents a moved
    paragraph as a deletion at the old location and an insertion at the new
    one. A naive "insertions are new content" reading would flag the moved
    text as "added" (harmless — it gets re-scanned, which is safe) but a
    *reject*-oriented variant that trusted deletions as "this text still
    needs no attention because it hasn't changed" would be wrong: moved text
    is bit-for-bit identical to text already redacted elsewhere, so this
    specific failure mode is low-risk for under-redaction, but is exactly
    the kind of "looks like new logic, actually silently changes classifier
    behavior" trap this feature is prone to.
  - **Partial-paragraph insertions**: a single new sentence pasted into an
    otherwise-untouched paragraph (e.g., "The Buyer shall pay $500,000 to
    **Jane Doe, Account #4471-2290,** on Closing.") is exactly the case the
    issue text calls out — new PII arriving in a paragraph that is *mostly*
    old. This is actually the easy case for Option A specifically, since the
    `w:ins` wrapper marks the exact inserted run — *if* the metadata is
    trustworthy. The risk is elsewhere: reviewers frequently retype a whole
    sentence instead of doing a minimal edit, in which case the "paragraph
    changed" signal is right but a run/sentence-level "only rescan the
    literal inserted characters" optimization would be wrong, because
    surrounding untouched words can combine with the new text to form PII
    that wasn't previously flagged (e.g., inserting "Doe" next to
    already-present, previously-unredacted "Jane" that wasn't PII-shaped on
    its own).
  - **Nested/overlapping revisions, multi-author documents, revision IDs
    that don't correspond to a clean "insert vs. unchanged" partition** —
    `docx_revisions.py`'s existing zombie-paragraph and whitespace-repair
    logic exists precisely because the raw markup is messier than a clean
    per-paragraph tag.
  - **Trust boundary**: this metadata is *author-supplied*. Nothing stops a
    document from having `w:ins`/`w:del` markup that doesn't correspond to
    the actual diff versus the file the user believes is "v1" — e.g., the
    user selects the wrong "previous version" file, or the DOCX was hand-
    edited to add spurious tracked-insertion wrappers around unchanged text
    (accidentally or, in an adversarial-input sense, deliberately) while
    leaving genuinely new PII outside any `w:ins` wrapper entirely. Trusting
    embedded revision metadata as the *sole* signal for "what to scan" means
    trusting a signal that was never designed to be consumed by a security-
    relevant redaction decision.

### Option B — Text-level diff between two DOCX versions

Extract flattened, paragraph-segmented text from both the prior and current
DOCX (reusing `DocxMap._build()`'s existing text-extraction path — the same
one `_collect_rule_spans`/`_collect_enhanced_spans` already consume) and run
a standard diff algorithm (e.g., Python's `difflib.SequenceMatcher`, or a
paragraph-level LCS) to classify each paragraph in v2 as unchanged,
modified, or newly added.

- **Preconditions for correctness**: requires the caller to actually supply
  the correct prior version — this is a UX/product requirement (the app
  needs a "compare to previous version" file-picker or a content-addressed
  cache of prior runs), not a technical one, but it's a hard requirement:
  without a trustworthy v1, there is no diff.
  It also requires that paragraph boundaries survive whatever authoring
  happened between v1 and v2 — usually true, but track-changes-driven
  paragraph merges/splits (see Option A's moved-paragraph case) can desync
  a naive line-oriented diff.
- **Failure modes**:
  - **Diff-algorithm edge cases named explicitly by the ticket**: a
    paragraph that moved (same content, different position) will typically
    be recognized as "unchanged" by a good LCS-based diff (its content
    matches something in v1), which is the *safe* direction — worst case it
    gets redundantly rescanned, not skipped. But a paragraph that moved
    *and* was edited in the same round trip can confuse a diff into
    reporting the wrong span as "added," e.g. attributing an edit to the
    paragraph it displaced rather than itself, depending on the matching
    algorithm's tie-breaking. `difflib.SequenceMatcher` in particular uses a
    heuristic (`autojunk`) that behaves surprisingly on documents with many
    repeated boilerplate lines (numbered clauses, repeated "IN WITNESS
    WHEREOF"-style boilerplate across sections) — repeated near-identical
    paragraphs are common in contracts and are exactly the input class
    generic text-diff tools handle worst.
  - **Formatting-only changes that also carry new PII**: the ticket calls
    this out explicitly — a paragraph where only run-level formatting
    changed (e.g., bolding) is not required to appear as a text diff at all
    if formatting is stripped before comparison, and *if* new PII was
    additionally pasted into that paragraph in the same edit, a
    formatting-blind text diff could correctly detect the paragraph as
    "changed" (text differs) — this specific combination is actually safe
    under Option B precisely because the plain-text extraction path
    (`DocxMap._build()`) already discards run-level formatting, so any
    *content* change, formatting-adjacent or not, shows up as a text diff.
    The genuinely dangerous variant is the reverse: a paragraph whose
    *visible* text is byte-identical between v1 and v2 but which contains
    new PII purely through a formatting/field/metadata channel a plain-text
    diff can't see — e.g., new PII added as document metadata (already
    handled separately by the metadata-scrubbing path in
    `unified_redactor.py`, out of scope here), a hidden `w:instrText`
    field code (mail-merge / cross-reference fields; note `docx_io.py:1166`
    already special-cases `w:instr` field parsing, meaning field-derived
    text is a known sharp edge in this codebase), or content added inside a
    header/footer/textbox that the paragraph-level diff doesn't traverse
    into with the same fidelity as the main body. Any of these would show
    "no diff" for a paragraph that in fact needs scanning.
  - **Encoding/whitespace noise**: minor whitespace or smart-quote
    normalization differences between how v1 and v2 were saved (different
    Word versions, different platforms) can make textually-identical
    content diff as "changed" (safe — over-inclusion) but can also, in
    principle, mask a true one-character change if normalization is applied
    too aggressively before comparing (e.g., collapsing whitespace could
    make an inserted single space adjacent to new text look like no change
    occurred if the diff isn't char-precise). Needs to diff on a
    consistently-normalized-both-sides basis, matching whatever
    normalization `DocxMap._build()`/`normalize_unicode()` (`pipeline.py:37`)
    already applies today, not inventing new normalization only for the
    diff path.
  - **No prior version available at all** (first pass on a document, or the
    user doesn't have/can't locate v1) — must degrade to full-document
    scanning, not silently skip everything.

### Verdict on detection approach

Neither option is independently trustworthy enough to gate *which text gets
scanned* at redaction time. Option A (track-changes metadata) is attractive
because it's precise when present and correctly authored, but is frequently
absent or stale in real legal workflows and is fundamentally an
author-supplied signal that the redaction tool would be trusting for a
security-relevant decision. Option B (text diff) is more universally
applicable (works on any two versions regardless of how they were edited)
but inherits classic diff-algorithm edge cases and has real blind spots
around non-body-text content (fields, headers, hidden text).

**Recommendation: if built, use Option B (text diff) as the sole
change-detection signal for deciding what to scan**, because it doesn't
require trusting embedded document metadata that the tool has no way to
verify was authored faithfully, and its failure modes bias toward
over-inclusion (rescanning unchanged-but-diff-flagged text) rather than
under-inclusion, which is the safe direction for a redaction tool. Track-
changes metadata (Option A) can still be read and used as an *opportunistic
speed hint* — e.g., to pre-sort which chunks are likely to be skippable — but
never as the sole authority for skipping a scan. This distinction (hint vs.
authority) is the crux of the correctness section below.

## Correctness / Under-Redaction Risk Analysis

This is the central risk of the feature, and the reason the scoped-down
recommendation below is conservative. The tool's entire value proposition is
"we found the PII so you don't have to." A diff-only mode that skips
scanning some text is a mode where the tool's own logic — not the LLM's
imperfect recall, which is already an accepted, disclosed limitation — is the
reason PII goes unredacted. That is a materially worse failure than a missed
entity from an LLM false negative, because it's systematic and silent: the
same bug will reproduce on every revision of every document, and nothing
about the failure looks anomalous in the output (the doc simply has fewer
redactions than expected, which looks like "clean revision," not "bug").

**Concrete under-redaction failure mode #1 — cross-paragraph entity
completion.** A person's full name is introduced in v1 as "Jane" (first name
only, in a paragraph that doesn't independently look like PII to the rules
engine and that the LLM, with correctly conservative recall, doesn't flag as
`needs_redaction` because a bare first name in isolation is ambiguous). In
v2, an *unrelated, later* paragraph is edited to add "...as agreed with Ms.
Doe on the call..." A diff-only scan correctly identifies the second
paragraph as changed and sends it to the LLM. But the LLM's entity-clustering
logic (`ClusterTable`, referenced in `pipeline.py`'s "NAME/ORG clustering...
for stable entity IDs") and the consistency pass (`_apply_consistency_pass`,
`pipeline.py:538-778`) are both designed to work *document-wide*: today,
`_apply_consistency_pass` builds a corpus-wide regex of every entity text
found anywhere in the document and rescans the *entire* `text` string for
exact/case-insensitive/fuzzy matches (`pipeline.py:659-768`), which is how
"Jane" mentioned only once near the start gets correctly tied to "Jane Doe"
mentioned once near the end. If the LLM extraction pass itself only ever
*sees* the changed paragraph, "Jane" in the untouched v1 paragraph is never a
candidate the consistency pass even knows to look for, because the candidate
list is built from spans the LLM found — and the LLM never saw the paragraph
containing "Jane" in this run. Net effect: "Jane" stays unredacted forever,
even though "Jane Doe" is now known to be a real name — the exact silent,
systematic leak this analysis is meant to catch.

**Concrete under-redaction failure mode #2 — moved-and-merged paragraph
desync.** A paragraph containing an account number is moved from Section 4
to Section 9 and lightly reworded in the same edit (see Option A/B's
moved-paragraph discussion above). A text-diff-based detector, depending on
matching heuristics, can attribute the "add" to the new location correctly
— but if the *old* location's removal isn't symmetrically understood as "no
longer present, nothing to do" versus "replaced by boilerplate that happens
to look similar," a partial/ambiguous diff match can leave both the old and
new locations unscanned in the pathological case (diff reports "modified in
place" against the wrong pairing). This is a diff-algorithm-precision risk
distinct from failure mode #1's clustering-scope risk, and is exactly the
"diff algorithm edge case" the ticket names as a required consideration.

**Concrete under-redaction failure mode #3 — chunk-boundary context loss for
the LLM itself, even *within* a correctly-identified changed span.** Today's
non-incremental pipeline already relies on `chunker.make_chunks()`'s
400-character overlap (`chunker.py:13,43`) to give the LLM enough
surrounding context that entities split across a chunk boundary are still
recognizable. If a diff-only mode extracts *only* the changed paragraph text
(without generous padding from the surrounding unchanged document), the LLM
loses exactly the kind of document-level context (e.g., "the Buyer" resolved
elsewhere to a named individual, a defined term established earlier) that
the *existing* two-pass enhanced pipeline is specifically designed to
provide via document-level context in `model_enhanced.py`. A changed
paragraph containing only "the Buyer shall also provide his passport number
to the Escrow Agent" has no PII-shaped text in isolation, but is a definite
redaction target once "the Buyer" is known to resolve to a named person
elsewhered in the (unscanned, in this failure mode) document.

**Required safeguard (the one the ticket explicitly calls for): always run
the full consistency pass over the entire document, every time, regardless
of which paragraphs were sent to the LLM for fresh extraction.** Concretely:

- `_apply_consistency_pass()` must always be called with the *complete*
  flattened document text (`pipeline.py`'s existing `text` variable used by
  `_collect_rule_spans`/`_collect_enhanced_spans` today), not a
  reconstructed "changed paragraphs only" text. This is already how the
  function is invoked today (`pipeline.py:1797, 1936` both pass the
  full-document `text`) — a diff-only mode must not regress this by
  accidentally narrowing the consistency-pass input to match the narrowed
  LLM-extraction input. This directly closes failure mode #1: even if "Jane"
  was never sent to the LLM in this run, once "Jane Doe" is discovered as a
  span from the *changed* paragraph, the consistency pass's full-document
  rescan will still catch the earlier bare "Jane" mention, because it scans
  the whole document's text for that string, not just the newly-scanned
  region.
- The rules-based structured-PII pass (`_collect_rule_spans`, emails,
  phones, SSNs, credit cards, dates, money — all regex/format-driven, not
  LLM-driven) should also always run over the full document on every
  revision. This pass is already cheap (no LLM call), so there's no
  performance argument for narrowing it, and structured PII (an SSN pasted
  into an "unchanged" paragraph as a formatting-only edit, or present in a
  header/footer the diff didn't traverse) is exactly the class of content
  Option B's blind spots (headers, fields, footnotes) can miss.
- The feature must therefore be honestly scoped as **"skip the *expensive
  LLM extraction call* on unchanged paragraphs," not "skip scanning
  unchanged paragraphs."** Every other pass in the pipeline (rules,
  consistency, overlap-merging, clustering) still sees, and must still
  operate on, the full document. This is a much narrower and safer
  optimization than "diff-only redaction" as a phrase suggests, and the
  achievable speedup is correspondingly smaller than "only send changed
  paragraphs" implies — the LLM call is the dominant cost, so this still
  captures most of the time savings, but the doc should not oversell it as
  eliminating full-document processing.
- Even with that safeguard, failure mode #2 (moved-paragraph diff
  mis-attribution) and the field/header blind spots under Option B are not
  fully closed by "always run the consistency pass" — the consistency pass
  only re-finds entities *already discovered somewhere*; it cannot discover
  a *wholly new* entity that exists only in a paragraph that both (a) the
  diff failed to flag as changed and (b) shares no matchable substring with
  anything the LLM did see. This residual risk is real and is the reason
  the MVP recommendation below stays conservative.

**Testing required before shipping to real legal documents:**

1. **Golden-file regression harness comparing diff-only output to
   full-rescan output** on a corpus of realistic revision pairs (at minimum:
   a single-paragraph edit, an added paragraph, a moved paragraph, a
   moved-and-edited paragraph, a formatting-only change, a change inside a
   footnote/header, and a document with no prior version). For every pair,
   assert the diff-only run's final entity set is a **superset-or-equal**
   of, never a subset of, the full-rescan run's entity set on the *same*
   v2 document — i.e., diff-only mode is allowed to be redundant but never
   allowed to redact less than a cold full scan would.
2. **A dedicated test mirroring `tests/test_docx_revisions.py`'s existing
   coverage** (`test_accept_revisions_strips_ins_del`,
   `test_accept_revisions_strips_move_ranges`,
   `test_accept_revisions_noop_when_no_revisions`) but for whatever new
   diff/paragraph-classification code this feature adds — specifically a
   test using a document with real `w:moveFrom`/`w:moveTo` pairs, since
   that's the existing test file's own acknowledgment that move-tracking is
   a known sharp edge in this codebase.
3. **An explicit test for failure mode #1** (entity fragment introduced in
   an unchanged paragraph, completed/clarified in a changed one) verifying
   the consistency-pass safeguard actually catches it — this should be a
   permanent regression test, not a one-time manual check, since it's the
   specific scenario this whole design doc's risk analysis is worried
   about.
4. **Fuzz/property testing on the diff step itself** against a corpus of
   real contract-revision pairs (if available from `sample-files/` or
   similar) comparing paragraph-classification output against manual
   ground truth, before trusting it on any real client document.
5. **A kill switch**: even after shipping, diff-only mode should be
   possible to disable per-run (env var or CLI flag, consistent with the
   existing `MARCUT_*` env var pattern used elsewhere in `pipeline.py`,
   e.g. `MARCUT_CONSISTENCY_MAX_CANDIDATES`) so a suspicious result can
   always be re-verified with a guaranteed full LLM rescan without a code
   change, and so this can be rolled out gradually / rolled back instantly
   if a real-world under-redaction is ever reported.

## MVP Recommendation

**Recommendation: pursue only with the safeguards above as non-negotiable,
and scope the MVP much narrower than "diff-only redaction" implies.**

A full "skip everything about unchanged paragraphs" implementation is not
recommended — the residual risk from diff-algorithm edge cases (moved
paragraphs, field/header blind spots) is real, hard to fully close, and the
consequence of getting it wrong (silent PII leakage in a confidentiality
tool) is severe enough that the burden of proof before shipping should be
high. If pursued, MVP should be:

1. **Optimization target: skip the LLM extraction call, never skip the
   rules pass or the consistency pass.** As established above, the rules
   pass and consistency pass already operate on the full document text
   cheaply; only the LLM call (`IntelligentRedactionPipeline.process_document()`)
   is expensive enough to be worth narrowing, and narrowing only that call
   keeps the existing document-wide safety nets (`_apply_consistency_pass`,
   `_collect_rule_spans`) fully intact with zero behavior change to them.
2. **Detection: Option B (text diff) only, not Option A (track-changes
   metadata) as an authority** — track-changes metadata, if present, may be
   used only as a hint to order/prioritize which chunks to diff-check first,
   never as a substitute for the text diff itself.
3. **Generous padding around each diff-detected "changed" region** before
   handing it to the LLM as a synthetic chunk — reuse the existing
   `chunker.make_chunks()` overlap concept (400 chars today) but likely
   needs to be paragraph-aware (pad to the nearest N whole paragraphs of
   context on each side, not just N characters) so cross-sentence context
   like defined terms and pronoun antecedents survives, directly mitigating
   failure mode #3.
4. **Require an explicit, user-visible opt-in** (not a silent default) —
   e.g., a "Compare to previous version" action distinct from ordinary
   "Redact," so a user always knows when they're trading rescan certainty
   for speed, and the failure mode ("this ran in diff mode against the file
   I picked as v1") is visible and auditable in the JSON report rather than
   an invisible pipeline internal. The audit report should record which
   mode ran and which paragraphs were sent to the LLM vs. skipped, so a
   post-hoc review can always tell whether a given redacted document went
   through full or diff-only extraction.
5. **Ship behind the kill-switch env var from day one**, not added later,
   given this is explicitly the highest-correctness-risk item in the
   backlog's "Major New Directions" section.

**A valid alternative outcome, if the above is judged too much complexity
for the payoff: do not pursue this feature at all**, and instead rely on the
existing, much lower-risk performance levers already in the codebase — the
small-document single-chunk bypass (`chunker.py:31-32`), the
per-chunk `ThreadPoolExecutor` parallelism already in
`IntelligentRedactionPipeline.process_document()`, and the deferred
streaming-progress work in `docs/design/streaming_progress.md` (which
improves perceived latency without changing what gets scanned at all). Those
levers get some of the same UX benefit (a revision "feels" fast) with none
of the under-redaction risk profile, since they never skip scanning any
document text.

**Explicitly deferred / out of scope for this doc:**

- Any UI/UX design for how a user selects "the previous version" to diff
  against (file picker vs. content-addressed run history) — a real
  prerequisite for Option B but a product-design question, not a redaction-
  correctness one.
- Building a paragraph-aware move-detector as a first-class feature (rather
  than accepting the residual risk and relying on the consistency-pass
  safeguard) — worth a follow-up spike only if this feature is greenlit and
  failure mode #2 proves common enough in practice to need closing directly.
- Optimizing the rules pass or consistency pass themselves for speed on
  large documents — both are already regex-batched
  (`_apply_consistency_pass`'s bounded pattern-budget logic,
  `pipeline.py:576-578, 661-675`) and are not the bottleneck this feature is
  aimed at.
