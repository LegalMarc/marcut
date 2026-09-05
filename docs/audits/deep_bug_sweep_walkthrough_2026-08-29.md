# Deep Bug Sweep Remediation Walkthrough (2026-08-29)

## Executive Summary

Following a deep codebase audit across the Marcut-2 repository (`src/python`, `src/swift`, `scripts/sh`, and test suites), 6 targeted bug remediations were designed, reviewed, implemented, and verified with comprehensive automated tests across both the Python and Swift test suites.

All 569 Python tests (6 skipped, 0 failures) and all 109 Swift tests (0 failures) passed cleanly.

---

## Remediations Implemented

### 1. `src/python/marcut/docx_io.py:932-973`
- **Issue:** `_rewrite_docx_zip` early `zout.writestr(item, data)` and `continue` inside `clean_language_settings` short-circuited every XML part, completely bypassing downstream cleaners (`clean_form_defaults`, `clean_nonstandard_xml`, `clean_microsoft_extension_xml`, and `clean_alternate_content`).
- **Fix:** Removed the premature `writestr` and `continue`, aligned exception handling with `clean_style_names` (`except Exception: pass`), allowing `data` to flow sequentially through all cleaners, writing once at line 973.
- **Verification:** Added `test_rewrite_docx_zip_cleans_both_lang_and_form_defaults` to `tests/test_metadata_scrubbing.py` verifying that both `<w:lang>` and `<w:default>` form data are stripped simultaneously.

### 2. `src/python/marcut/rules.py:1111-1134` (Signature Line Exclusions)
- **Issue:** The `SIGNATURE_LINE` parser extracted potential person names from `Name:` blocks and emitted `NAME` spans with high confidence (0.95) without checking `_is_excluded()`, causing corporate signatory titles such as "Authorized Representative", "Managing Director", and "General Counsel" to be redacted as individual person names.
- **Fix:** Added `_is_excluded(potential_name)` and `_is_excluded(original_name)` checks to skip excluded corporate titles while advancing the parse offset to prevent duplicate matches.
- **Verification:** Added `TestSignatureLineExclusions` in `tests/test_rules.py` covering single and multiple signatory lines.

### 3. `src/python/marcut/rules.py:429, 1058-1095` (Defined Term Fallback Gate & Quote Expansion)
- **Issue:** The `_DEFINED_TERM_NAME` loop bypassed rule filter selection (`_rule_enabled("NAME", selected)`) and exclusion checking (`_is_excluded()`), and only matched double quote characters `["“”]`, missing single-quoted legal defined terms (`('Doe')`, `(‘Doe’)`).
- **Fix:** Added `if _rule_enabled("NAME", selected):` guard, verified `_is_excluded` on both full and short terms, and expanded quote pattern to `["“”'‘’]`.
- **Verification:** Added `test_single_quote_and_curly_quote_variants` and `test_excluded_terms_not_emitted` in `tests/test_rules.py`, and `test_defined_term_person_rule_toggle` in `tests/test_rule_filter.py`.

### 4. `src/python/marcut/rules.py:1040-1046` (ORG Prefix Trim Offset Preservation)
- **Issue:** When trimming excluded phrase prefixes from `ORG` matches (e.g., `"FOR VALUE RECEIVED,   Acme Corp"`), the trimmer recomputed `e = s + len(trimmed_text)` with `", ".join(...)`. If the original text contained irregular whitespace, `e` desynchronized from the actual document text, causing character truncation or span rejection via `_drop_invalid_spans`.
- **Fix:** Computed `s = s + trim_start` and `sub = sub[trim_start:]`, leaving `e` unchanged, perfectly preserving original character offsets.
- **Verification:** Added `test_irregular_whitespace_preserves_text_and_bounds` in `tests/test_rules.py`.

### 5. `src/python/marcut/model.py:196-230` (LLM JSON Response Normalization)
- **Issue:** When an LLM emitted a raw or code-fenced JSON array `[{"text": "...", "type": "NAME"}]`, `parse_llm_response` returned a `list`. Callers expecting a `dict` crashed with `AttributeError: 'list' object has no attribute 'get'`.
- **Fix:** Detected top-level `[` arrays (both inside and outside code fences), and normalized parsed `list` instances to `{"entities": loaded}`.
- **Verification:** Added unit tests in `tests/test_model.py` for raw arrays, code-fenced arrays, truncated arrays with tolerant repair, and primitive value rejection.

### 6. `src/python/marcut/chunker.py:28-30` (Chunker Non-Positive Input Guard)
- **Issue:** If `make_chunks` was invoked with `max_len <= 0`, the sliding window loop could enter an infinite spin.
- **Fix:** Added validation `if max_len <= 0: raise ValueError("max_len must be positive")`.
- **Verification:** Added `test_max_len_non_positive_raises` in `tests/test_chunker.py`.

### 7. `src/swift/MarcutApp/Sources/MarcutApp/ExcludedWordMatcher.swift:30-36, 136-148` (Possessive Normalization)
- **Issue:** The Swift `ExcludedWordMatcher.normalizeForExclusion` port omitted trailing possessive regex stripping (`['’]s\s*$|['’]\s*$`) present in Python `marcut.model._normalize_for_exclusion`. In the live Settings preview, possessive variations of excluded words (e.g. `Company's`, `Companies'`) failed to match.
- **Fix:** Added `trailingPossessiveRegex` and applied it before trailing punctuation stripping in `normalizeForExclusion`.
- **Verification:** Added `testExcludedWordMatcherMatchesPossessives` in `MarcutAppTests.swift`.

### 8. `scripts/sh/build_appstore_release.sh:1819-1832` (App Store Identity Detection)
- **Issue:** `APPSTORE_IDENTITY_DETECTED=true` was nested inside `if [ "$SKIP_NOTARIZATION" = false ]; then`. If `--skip-notarization` was passed, `APPSTORE_IDENTITY_DETECTED` remained `false`, causing `final_validation` to fail with `Refusing to skip notarization validation without MARCUT_ALLOW_NOTARIZATION_SKIP=1`.
- **Fix:** Detected `APPSTORE_IDENTITY_DETECTED=true` unconditionally from `DEVELOPER_ID`, independent of the initial `SKIP_NOTARIZATION` flag.
- **Verification:** Checked bash syntax validation (`bash -n scripts/sh/build_appstore_release.sh`).

---

## Test Verification Summary

| Test Suite | Result | Details |
|---|---|---|
| **Python Test Suite** | **569 PASSED**, 6 skipped, 0 failures | `PYTHONPATH=src/python .venv/bin/python -m pytest -q` |
| **Swift Test Suite** | **109 PASSED**, 0 failures | `swift test --package-path src/swift/MarcutApp` |
| **Shell Syntax Check** | **PASSED** (exit 0) | `bash -n scripts/sh/build_appstore_release.sh` |
