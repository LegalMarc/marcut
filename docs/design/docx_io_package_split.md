# Design Spike: Splitting `docx_io.py` into a Package

Status: Design spike (no code changes). Companion to issue #25.

## Goal

`src/python/marcut/docx_io.py` (2,413 lines) is the single module that reads
DOCX files, mutates their XML/ZIP contents for redaction and metadata
hardening, and writes them back out. It mixes CLI-argument plumbing,
in-memory document scanning/indexing, track-changes revision authoring, and
raw ZIP/XML post-processing in one file with one 2,000+ line class
(`DocxMap`). This doc inventories the distinct responsibilities currently
folded into that file, proposes a package structure that separates them
along real seams, and — because this module sits directly in the
redaction/metadata-scrubbing critical path, where a subtle behavior change
could silently leak unredacted content or leave PII in metadata — lays out a
concrete before/after behavior-parity verification plan. This ticket
produces the design only; it does not touch `docx_io.py`.

## Why this is a design spike, not a direct refactor

`DocxMap` is the sole type `pipeline.py` and `cli.py` depend on
(`from .docx_io import DocxMap, MetadataCleaningSettings` in
`pipeline.py:88`; `from .docx_io import CLI_ARG_PAIRS` in `cli.py:7`), and
its methods share mutable instance state — `self.text`, `self.index`,
`self.detached_parts`, `self._rev_id`, `self.warnings`,
`self._metadata_settings` — across what are logically independent
operations (build a flat text index, apply redaction replacements, harden
XML in memory, rewrite the ZIP post-save). `apply_replacements()` in
particular depends on `self.index` having already been populated by
`_build()` at construction time, and `save()` depends on
`self._metadata_settings` having been set by a prior `scrub_metadata()` call
if ZIP-level hardening (`_rewrite_docx_zip`) is to run at all — an implicit
ordering contract enforced by convention, not the type system. A mechanical
split that gets any of these load-bearing side effects wrong (e.g. moves
`_iter_part_elements()` to a class that no longer shares `detached_parts`
with `save()`) would fail silently: the document would still save, but a
hidden-text run, a comment, or a URL relationship might no longer be
scrubbed. Test coverage today (see Section 3) is real but partial, so this
ticket stops at a plan rather than attempting the split unattended.

---

## 1. Responsibility Inventory

| Responsibility | Evidence (functions/classes) | Approx. lines |
|---|---|---|
| **CLI flag ↔ settings-field mapping** | `CLI_ARG_PAIRS`, `CLI_ARG_MAP`, `CLI_CLEAN_ARG_PAIRS`, `CLI_CLEAN_ARG_MAP`, `FIELD_TO_CLI`, `_normalize_metadata_field_key()` — 68 `--no-clean-*`/`--clean-*` flag pairs generated declaratively | 25–115 (~90) |
| **Metadata-cleaning settings/config model** | `MetadataCleaningSettings` dataclass (68 boolean fields across App/Core/Custom/Structure/Embedded/Advanced groups), `from_preset()` (`maximum`/`balanced`/`none`), `_field_lookup()`, `apply_mapping()`, `from_cli_args()`, `from_environment()` (reads `MARCUT_METADATA_PRESET`/`MARCUT_METADATA_SETTINGS_JSON` env vars), `to_cli_args()` | 117–322 (~205) |
| **Document load/save lifecycle** | `DocxMap.__init__`, `DocxMap.load()`, `DocxMap.load_accepting_revisions()` (delegates to `.docx_revisions`), `DocxMap.save()`, `_postprocess_zip()` | 325–379 (~55) |
| **Raw ZIP/XML post-processing ("hardening at the package level")** | `_rewrite_docx_zip()` — a single ~575-line method with ~20 nested closures: relationship-target sanitization (`_is_unc_path`, `_is_user_path`, `_is_file_path`, `_is_internal_url`, `_sanitize_target`), JPEG/PNG binary metadata stripping (`_strip_jpeg_metadata`, `_strip_png_metadata`), namespace/element pruning (`_remove_lang_elements`, `_strip_form_defaults`, `_strip_alternate_content`, `_strip_nonstandard_elements`), custom-style renaming (`_rename_custom_styles`, `_update_style_references`), chart-label redaction (`_clean_chart_labels`), `.rels`/`[Content_Types].xml` rewriting (`_scrub_rels`, `_update_content_types`), and the final orphan-detection + ZIP-rewrite loop | 380–953 (~575) |
| **Document scanning / flat text index construction** | `_iter_part_elements()`, `_iter_part_elements_with_parts()`, `_scan_drawing_tag()`, `_scan_run_contents()`, `_append_run()`, `_scan_paragraph()`, `_scan_container()`, `_scan_table_xml()`, `_build()` — walks body/headers/footers/footnotes/endnotes/text-boxes/content-controls into `self.text` + `self.index` for character-offset-based span lookups | 955–1612 (~660) |
| **In-memory XML hardening (`harden_document`) and in-place metadata scrub (`scrub_metadata`)** | `_unlink_hyperlinks`, `_strip_comment_markers[_by_ids]`, `_comment_visibility_map`, `_remove_comment_entries`, `_parse_merge_field_name`, `_build_merge_field_run`, `_convert_mail_merge_fields`, `_remove_data_bindings`, `_remove_hidden_text`, `_remove_invisible_objects`, `_remove_headers_footers`, `_remove_watermarks`, `_remove_ink_annotations`, `_ensure_track_revisions_enabled`, `harden_document()`, `scrub_metadata()` — direct core.xml/app.xml/settings.xml element surgery via `doc.part.package.rels` | 989–1327, 1669–2240 (~900) |
| **Track-changes revision writing** | `_make_text_run()`, `_insert_after()` (legacy), `_insert_deletion_after()`, `_insert_insertion_after()`, `apply_replacements()` — builds `w:ins`/`w:del` elements with author/date/id, splits runs at span boundaries, forces label-run color/formatting, and unlinks hyperlink relationships for redacted URLs | 1614–1667, 2243–2414 (~450) |
| **Safe XML parsing utility** | `_safe_fromstring()` — `lxml` parser with `resolve_entities=False` (XXE hardening), used by nearly every other section | 18–22 |

Observation: `docx_io.py` is really **five modules' worth of content** — (a)
a CLI/settings configuration model that has no XML/ZIP dependency at all and
could be imported standalone by `cli.py`, (b) a ZIP-container-level
post-processor that operates on raw bytes/`zipfile`/`lxml` and never touches
`python-docx` objects, (c) an in-memory document scanner that builds the
character-offset index `apply_replacements()` depends on, (d) in-memory
XML/metadata hardening that operates through `python-docx` `Document`/`part`
objects, and (e) track-changes revision authoring that is conceptually
unrelated to metadata cleaning but currently lives in the same class and
shares its `_rev_id` counter and `_iter_part_elements()` helper.

---

## 2. Proposed Package Structure

```
src/python/marcut/docx/
    __init__.py          # re-exports: DocxMap, MetadataCleaningSettings,
                          # CLI_ARG_PAIRS, CLI_ARG_MAP, CLI_CLEAN_ARG_PAIRS,
                          # CLI_CLEAN_ARG_MAP, FIELD_TO_CLI
                          # (preserves `from .docx_io import X` call sites
                          # via a thin `docx_io.py` shim — see Slice 5)
    xml_utils.py          # _safe_fromstring() and any other shared,
                          # dependency-free XML helpers
    settings.py            # MetadataCleaningSettings, CLI_ARG_PAIRS/MAP,
                          # CLI_CLEAN_ARG_PAIRS/MAP, FIELD_TO_CLI,
                          # _normalize_metadata_field_key()
                          # -- zero python-docx/lxml-mutation dependency,
                          # pure dataclass + dict logic
    scan.py                # DocumentIndex (or similar): _iter_part_elements,
                          # _iter_part_elements_with_parts, _scan_* family,
                          # _build(), owns `text`/`index`/`detached_parts`
    revisions.py            # Track-changes authoring: _make_text_run,
                          # _insert_deletion_after, _insert_insertion_after,
                          # apply_replacements(), _ensure_track_revisions_enabled
                          # (NOTE: distinct from the existing top-level
                          # marcut/docx_revisions.py, which handles
                          # *accepting* pre-existing revisions on load —
                          # name this module accordingly, e.g. revision_writer.py,
                          # to avoid confusion)
    hardening.py            # In-memory scrub_metadata()/harden_document() and
                          # their private helpers (_unlink_hyperlinks,
                          # _strip_comment_markers*, _comment_visibility_map,
                          # _remove_comment_entries, mail-merge/data-binding/
                          # hidden-text/invisible-object/header-footer/
                          # watermark/ink-annotation removal)
    zip_postprocess.py      # _rewrite_docx_zip() and its ~20 nested closures,
                          # promoted to module-level functions taking
                          # (settings, ...) explicitly instead of closing
                          # over method-local state
    document.py              # DocxMap: thin coordinator that composes
                          # DocumentIndex + hardening + zip_postprocess +
                          # revisions; owns load()/load_accepting_revisions()/
                          # save()/_postprocess_zip() and delegates the rest
```

Module-boundary rules:
- `settings.py` has no dependency on `python-docx`, `lxml`, or `zipfile` —
  it is pure configuration and can be unit-tested (and imported by `cli.py`)
  without touching a real document.
- `zip_postprocess.py` operates only on raw bytes / `zipfile.ZipFile` /
  `lxml.etree` — it never imports `docx.Document` — matching how it
  already behaves as a `path`-in/`path`-out post-processing pass distinct
  from everything that runs on the live `python-docx` object tree.
- `scan.py`, `hardening.py`, and `revisions.py` all operate on the live
  `python-docx` object graph and currently share `_iter_part_elements()`;
  the split keeps that as one method owned by `scan.py`'s index/traversal
  type, injected into `hardening.py` and `revisions.py` rather than
  duplicated.
- `document.py`'s `DocxMap` keeps its current public surface
  (`load`, `load_accepting_revisions`, `save`, `harden_document`,
  `scrub_metadata`, `apply_replacements`, `.text`, `.index`, `.warnings`)
  unchanged so `pipeline.py` and `cli.py` require no call-site edits beyond
  the import path — which itself is preserved via the `__init__.py`
  re-export (see Slice 5 below).

---

## 3. Behavior-Parity Verification Plan

### 3.1 What today's tests already cover

| Test file | Covers |
|---|---|
| `tests/test_docx_io.py` (221 lines) | `MetadataCleaningSettings` defaults, `from_cli_args()` (including `--no-clean-review-comments`/`--clean-review-comments` combined flags), `to_cli_args()` round-trip, `_safe_fromstring()` XXE-resistance (external entity payload must not resolve), the full `CLI_ARG_PAIRS`/`CLI_CLEAN_ARG_PAIRS` mapping tables, and the `none` preset zeroing every field. **Pure settings/utility coverage — no live `DocxMap` object.** |
| `tests/test_metadata_scrubbing.py` (956 lines) | `MetadataCleaningSettings` preset behavior (`maximum`/`balanced`/`none`) end-to-end against real generated DOCX files, before/after property diffs for core.xml/app.xml fields, and `TestMetadataScrubReport` validating the scrub report pipeline reflects what `scrub_metadata()` actually changed. **Exercises `DocxMap.scrub_metadata()` and the ZIP-level hardening path together, via real files.** |
| `tests/test_pipeline.py` | Exercises `DocxMap` only through a `FakeDocxMap` test double (`apply_replacements`, `scrub_metadata`, `harden_document` are all stubbed — see lines 574–800) for pipeline-orchestration tests, plus real `DocxMap.load_accepting_revisions` integration elsewhere in the suite. **Pipeline wiring is covered; the fake means these tests would NOT catch a behavior regression inside `DocxMap` itself.** |
| `tests/test_url_redaction.py` | `TestURLRedactionIntegration` drives real `DocxMap.apply_replacements()` against generated DOCX fixtures containing hyperlinks, asserting the URL text is replaced AND the hyperlink relationship is removed (the `link_targets`/`link_elements` logic in `apply_replacements()`). |
| `tests/test_failure_scenarios.py::TestCorruptDocxFiles` | Exercises `DocxMap.load()`/`save()` against malformed/truncated DOCX inputs — the load/save lifecycle's error handling. |
| `tests/test_security.py` | XXE and related security-hardening assertions (does not appear to instantiate `DocxMap` directly per file grep — verify at implementation time). |

Net assessment: **`scrub_metadata()` + ZIP hardening and `apply_replacements()`
+ URL unlinking both have real integration coverage against generated
files. `harden_document()` (RSID clearing, OLE/ActiveX object replacement,
`scrub_all_images`) and the document-scanning/indexing layer (`_build()`
and the `_scan_*` family — text boxes, content controls, footnotes,
endnotes, tables) have thin-to-no direct test coverage; they are currently
validated only incidentally through whatever fixtures
`test_metadata_scrubbing.py` and `test_pipeline.py` happen to exercise.**

### 3.2 Characterization tests needed before any extraction PR

1. **Golden-file byte/XML diff harness.** For a small fixed set of
   representative fixture DOCX files (should include: plain paragraphs,
   tables incl. nested tables, headers/footers, footnotes, endnotes, text
   boxes/drawings, content controls (`w:sdt`), tracked-changes already
   present on load, embedded OLE objects, hyperlinks, comments (visible +
   hidden/deleted), and mail-merge fields) run current `DocxMap` end-to-end
   (`load` → `scrub_metadata` → `harden_document` → `apply_replacements` →
   `save`) and snapshot: (a) the extracted `.text`/`.index` from `_build()`,
   (b) the full unzipped part listing + each part's parsed XML (normalized/
   canonicalized, not raw bytes, to avoid false diffs from
   non-deterministic ZIP ordering or timestamps), and (c) `self.warnings`.
   Commit these as golden fixtures. This harness is the single artifact
   that proves parity after each extraction slice — run it before and after
   every slice lands and diff to zero.
2. **`harden_document()` direct unit tests** (currently absent): RSID
   attribute removal, OLE/ActiveX `w:object`/`w:control` → placeholder text
   replacement (both when the object is the run's only child and when
   siblings exist), and `scrub_all_images=True` drawing removal — each
   asserted against parsed output XML, not just "it didn't crash."
3. **Scanning/indexing unit tests** isolating `_build()`/`_scan_*` from
   `apply_replacements()`: assert `.text` and `.index` content directly for
   each container type in the representative-fixture list above (especially
   text boxes via `_scan_drawing_tag`, and nested tables via
   `_scan_table_xml`'s recursion), since these are exactly the code paths
   most likely to be silently altered by a refactor that moves iteration
   helpers between classes.
4. **Comment-visibility-map unit tests**: `_comment_visibility_map()`'s
   hidden/deleted/visible classification (`_is_hidden_run`,
   `w:del`/`w:moveFrom` ancestry) is intricate state-tracking logic with no
   dedicated test today; add direct cases for each of the three states plus
   the "comment start with no matching id in `comments.xml`" edge case.
5. **Order-dependency regression test**: an explicit test that calls
   `scrub_metadata()` then `save()` and asserts ZIP-level hardening
   (`_rewrite_docx_zip`) ran (via `self._metadata_settings` being set), and
   a companion test that calls `save()` *without* a prior `scrub_metadata()`
   call and asserts ZIP hardening is skipped — pinning the implicit
   ordering contract identified above so an extraction can't accidentally
   change when `_metadata_settings` gets attached to `self`.

Only once (1)–(5) are in place and green against the **current**
`docx_io.py` should an extraction PR begin. Each slice below must re-run the
full golden-file harness and diff to zero before merging.

### 3.3 Verification loop per slice

For every slice in Section 4:
1. Run `PYTHONPATH=src/python python3 -m pytest tests/test_docx_io.py tests/test_metadata_scrubbing.py tests/test_pipeline.py tests/test_url_redaction.py tests/test_failure_scenarios.py tests/test_security.py -q` — must stay green with zero test edits other than import-path updates.
2. Run the golden-file characterization harness from 3.2(1) — diff must be empty.
3. Run the full existing pipeline integration path
   (`marcut redact --in <fixture> --out ... --report ...`) against at least
   one real sample from `sample-files/` and diff the resulting `.docx` and
   report JSON against a pre-slice baseline.

---

## 4. Recommended Extraction Order

Smallest/lowest-risk first; each slice is independently landable and
independently revertable.

1. **Slice 1 — `settings.py` (pure config, zero XML dependency).**
   Move `CLI_ARG_PAIRS`/`CLI_ARG_MAP`/`CLI_CLEAN_ARG_PAIRS`/
   `CLI_CLEAN_ARG_MAP`/`FIELD_TO_CLI`, `_normalize_metadata_field_key()`,
   and `MetadataCleaningSettings` verbatim into `docx/settings.py`. No
   behavior touches `python-docx`/`lxml` at all in this class, so risk is
   near-zero; `tests/test_docx_io.py` already gives near-complete coverage
   of this surface. Update `cli.py`'s `from .docx_io import CLI_ARG_PAIRS`
   and `pipeline.py`'s `MetadataCleaningSettings` import (or rely on the
   `docx_io.py` re-export shim from Slice 5, landed first, to avoid
   touching call sites at all).
2. **Slice 2 — `xml_utils.py` (`_safe_fromstring`).** One function, no
   state, used everywhere else — extracting it first unblocks every later
   slice from having to decide where it lives.
3. **Slice 3 — `zip_postprocess.py` (`_rewrite_docx_zip` and its
   closures).** Self-contained: takes a file `path` and a
   `MetadataCleaningSettings`, mutates the file on disk, has no dependency
   on `DocxMap` instance state other than reading `path`/`settings`
   parameters already passed in. Convert the ~20 nested closures to
   module-level (or small-class) functions with explicit parameters instead
   of closure-captured locals — this is the highest line-count slice but
   the most mechanical, and `test_metadata_scrubbing.py` already exercises
   it end-to-end through real files.
4. **Slice 4 — `scan.py` (document indexing/traversal).** Extract
   `_iter_part_elements`, `_iter_part_elements_with_parts`, the `_scan_*`
   family, and `_build()` into a type owned/composed by `DocxMap` (e.g.
   `DocumentIndex`, constructed in `DocxMap.__init__` and exposing
   `.text`/`.index`/`.detached_parts` back onto `DocxMap` for backward
   compatibility). Requires the new characterization tests from 3.2(3)
   landed and green *first*, since this is the least-tested area today.
5. **Slice 5 — `hardening.py` + `revisions.py`, with `document.py`
   coordinating.** The largest behavioral surface (`scrub_metadata`,
   `harden_document`, `apply_replacements` and their private helpers).
   Split into the two modules described in Section 2, with `DocxMap`
   (now in `document.py`) as a thin façade that delegates to both and
   preserves its existing public method signatures exactly. Land the
   order-dependency regression test from 3.2(5) before this slice, since
   it's the slice most likely to disturb the `_metadata_settings` /
   `save()` contract. At the end of this slice, add a compatibility shim
   at the old `marcut/docx_io.py` path
   (`from .docx.document import DocxMap; from .docx.settings import
   MetadataCleaningSettings, CLI_ARG_PAIRS, ...`) so any external or
   test-only `from .docx_io import ...` reference keeps working during a
   deprecation window, and update `pipeline.py`/`cli.py` to import from
   `marcut.docx` directly.

Each slice should ship as its own PR gated on the full verification loop in
3.3, in the order above — later slices depend on the characterization tests
(3.2) being in place, not on earlier slices landing first, so Slice 3 could
in principle land before Slice 1 if scheduling requires it, but Slice 4 and
5 must not begin until the corresponding 3.2 characterization tests are
merged and green against the pre-split code.
