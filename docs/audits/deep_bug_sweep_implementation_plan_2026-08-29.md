# Implementation Plan — Deep Bug Sweep Remediation

> [!NOTE]
> **Superseded as of 2026-09-09 — do not schedule work from this document.**
> All 10 findings are closed. Nine were resolved by the `docx_pkg/` package split (#72-#76) and the
> #83-#88 batch without this plan being executed as written; finding 9 (the `FileAccessCoordinator`
> dead branch) was fixed on 2026-09-09. Finding-by-finding evidence, with the file and mechanism
> that closed each one, is in `docs/reports/2026-09-09-deep-bug-sweep-remediation-status.md`.

Fix the 8 concrete functional bugs identified during the August 29, 2026 deep bug sweep across the Python redaction core, rules engine, DOCX ZIP rewrite, and Swift app.

## User Review Required

> [!IMPORTANT]
> - **Metadata Cleaning Fix**: In `_rewrite_docx_zip`, `clean_form_defaults`, `clean_nonstandard_xml`, `clean_microsoft_extension_xml`, and `clean_alternate_content` will now actively run on `word/*.xml` parts as originally specified. Documents scrubbed with the "Maximum" or "Custom" presets with these settings enabled will now have these elements scrubbed rather than silently skipped.
> - **Signature Block Corporate Titles**: Corporate officer titles (like "Authorized Representative", "Managing Director", "General Counsel") appearing in signature blocks (`Name: ...`) will now be excluded if present in `excluded-words.txt`, preventing false-positive redaction of corporate titles.
> - **Defined Term Rule Filtering**: `_DEFINED_TERM_NAME` will now respect `MARCUT_RULE_FILTER` (it will only run if `NAME` is enabled) and will check `_is_excluded()`. It will also recognize single quotes and curly single quotes.

---

## Proposed Changes

### Component 1: DOCX IO (`docx_io.py`)

#### [MODIFY] [docx_io.py](../../src/python/marcut/docx_io.py)
- In `_rewrite_docx_zip`: Remove the premature `zout.writestr(item, data)` and `continue` inside `if settings.clean_language_settings ...:` (lines 941-942 and 936).
- Allow `data` to flow through `clean_form_defaults` and `clean_nonstandard_xml` / `clean_microsoft_extension_xml` / `clean_alternate_content` passes so all active cleaners execute on each `word/*.xml` part.
- Write the final transformed `data` once at line 973.

---

### Component 2: Rules Engine (`rules.py`)

#### [MODIFY] [rules.py](../../src/python/marcut/rules.py)
- **Signature block exclusion check**: In the `SIGNATURE_LINE` loop (lines 1115-1134), add `if _is_excluded(potential_name) or _is_excluded(original_name): continue` before creating the `NAME` span.
- **Defined-term rule gate & exclusions**: In the `_DEFINED_TERM_NAME` loop (lines 1058-1095):
  - Check `if not _rule_enabled("NAME", selected): continue`.
  - Check `if _is_excluded(full_text) or _is_excluded(short_text): continue`.
  - Expand `_DEFINED_TERM_NAME` pattern from `["“”]` to `["“”'‘’]` so single-quoted legal defined terms match.
- **ORG prefix trimming**: In lines 1040-1046, replace the synthetic `", ".join(segments[trim_count:])` length computation with direct slicing `sub = sub[trim_start:]`, advancing `s = s + trim_start` and keeping `e` unmodified.

---

### Component 3: LLM Response Handling (`model.py`)

#### [MODIFY] [model.py](../../src/python/marcut/model.py)
- In `parse_llm_response`: When the parsed JSON object is a `list` (from an LLM that outputs a top-level array of entities), normalize and return `{"entities": loaded}` so callers can safely call `.get("entities", [])`.

---

### Component 4: Chunker (`chunker.py`)

#### [MODIFY] [chunker.py](../../src/python/marcut/chunker.py)
- In `make_chunks`: Add validation `if max_len <= 0: raise ValueError("max_len must be positive")` to prevent infinite loop.

---

### Component 5: Swift Settings Live Preview (`ExcludedWordMatcher.swift`)

#### [MODIFY] [ExcludedWordMatcher.swift](../../src/swift/MarcutApp/Sources/MarcutApp/ExcludedWordMatcher.swift)
- Add trailing possessive regex stripping (`['’]s\s*$|['’]\s*$`) to `normalizeForExclusion` matching Python's `_TRAILING_POSSESSIVE_RE`.

---

### Component 6: Release Build Script (`build_appstore_release.sh`)

#### [MODIFY] [build_appstore_release.sh](../../scripts/sh/build_appstore_release.sh)
- Set `APPSTORE_IDENTITY_DETECTED=true` whenever `DEVELOPER_ID` is not a Developer ID certificate, independent of whether `--skip-notarization` was passed on the CLI.

---

## Verification Plan

### Automated Tests
1. **Python test suite**:
   ```bash
   PYTHONPATH=src/python .venv/bin/python -m pytest -q
   ```
2. **Swift test suite**:
   ```bash
   swift test --package-path src/swift/MarcutApp
   ```
3. **New unit tests**:
   - `test_signature_name_skips_excluded_titles`: Verify "Name: Authorized Representative" is not redacted as a name.
   - `test_defined_term_respects_rule_filter`: Verify defined term is not emitted when `MARCUT_RULE_FILTER="EMAIL"`.
   - `test_defined_term_single_quotes`: Verify `John Doe ('Doe')` is detected.
   - `test_org_prefix_trimming_preserves_spacing`: Verify no offset drift on non-standard whitespace.
   - `test_parse_llm_response_list`: Verify JSON array is normalized to `{"entities": [...]}`.
   - `test_docx_rewrite_runs_all_cleaners`: Verify form defaults and alternate content are scrubbed even when `clean_language_settings=True`.
   - `test_make_chunks_rejects_non_positive_max_len`: Verify `ValueError` on `max_len <= 0`.
   - Swift test in `MarcutAppTests.swift`: Verify `ExcludedWordMatcher` matches possessives like `"Company's"`.
