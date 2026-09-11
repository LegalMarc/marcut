# Deep Bug Sweep Audit Report — August 29, 2026

> [!NOTE]
> **Superseded as of 2026-09-09 — do not schedule work from this document.**
> All 10 findings are closed. Nine were resolved by the `docx_pkg/` package split (#72-#76) and the
> #83-#88 batch without this plan being executed as written; finding 9 (the `FileAccessCoordinator`
> dead branch) was fixed on 2026-09-09. Finding-by-finding evidence, with the file and mechanism
> that closed each one, is in `docs/reports/2026-09-09-deep-bug-sweep-remediation-status.md`.

**Target Codebase:** Marcut-2 (`LegalMarc/marcut`)  
**Scope:** Core Python redaction pipeline, rules engine, DOCX track changes / XML rewriting, LLM response parsing & error recovery, Swift / PythonKit interop, Settings preview, build & distribution scripts.  
**Methodology:** Static code inspection, control flow analysis, regex grammar inspection, and live reproduction tests against the sandbox environment.

---

## Executive Summary

This deep bug sweep identified **10 concrete defects** across 4 functional areas:
1. **Critical/High Severity (3)**:
   - Metadata hardening bypass in DOCX ZIP rewrite (`clean_form_defaults`, `clean_nonstandard_xml`, `clean_microsoft_extension_xml`, `clean_alternate_content` completely short-circuited).
   - Corporate executive titles ("Authorized Representative", "Managing Director", "General Counsel") erroneously redacted as person names in signature blocks due to missing exclusion check.
   - Defined-term name extraction bypassing `MARCUT_RULE_FILTER` and exclusion lists, and failing on single-quoted legal defined terms.
2. **Medium Severity (4)**:
   - Organization prefix trimming desynchronizing character slice offsets, causing truncated redactions or silent span drops.
   - LLM JSON array responses crashing `parse_llm_response` callers with `AttributeError`.
   - Swift `ExcludedWordMatcher.swift` missing possessive normalization (`'s` / `'`), causing divergent live preview behavior in Settings.
   - App Store build script (`build_appstore_release.sh`) rejecting builds when `--skip-notarization` is explicitly passed.
3. **Low Severity / Hygiene (3)**:
   - `make_chunks` infinite loop hazard when `max_len <= 0`.
   - `FileAccessCoordinator.swift` dead session tracking branch.
   - Discrepancy between `docs/release/python-sbom.json` and staged `python_site`.

---

## Detailed Findings

### 1. [HIGH] Metadata Hardening Bypassed in `_rewrite_docx_zip`
* **File:** [`src/python/marcut/docx_io.py:932-973`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/docx_io.py#L932-L973)
* **Root Cause:**
  Inside `_rewrite_docx_zip`, each `word/*.xml` part undergoes sequential scrubbing passes. However, lines 941–942 inside the `clean_language_settings` block write the entry and issue an early `continue`:
  ```python
  if settings.clean_language_settings and name.startswith("word/") and name.endswith(".xml"):
      try:
          root = _safe_fromstring(data)
      except Exception:
          zout.writestr(item, data)
          continue
      if _remove_lang_elements(root):
          data = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
          any_change = True
      zout.writestr(item, data)
      continue  # <--- Bypasses all subsequent checks for word/*.xml
  ```
* **Impact:**
  Because `clean_language_settings: bool = True` is enabled by default across all presets, the following subsequent blocks are **never executed** on any `word/*.xml` file (including `word/document.xml`, headers, footers):
  - `if settings.clean_form_defaults and name.startswith("word/") and name.endswith(".xml"):` (line 944)
  - `if (settings.clean_nonstandard_xml or settings.clean_microsoft_extension_xml or settings.clean_alternate_content) and name.endswith(".xml"):` (line 954)
  Form defaults, non-standard XML tags, Microsoft extension XML, and alternate content containing potentially sensitive tracking or user metadata are silently left in the output document.
* **Fix:**
  Remove `zout.writestr(item, data)` and `continue` from line 941–942 (and remove the redundant write from the `except` block). Let `data` flow through form defaults, alternate content, and nonstandard XML transformations before the single final `zout.writestr(item, data)` call at line 973.

---

### 2. [HIGH] Corporate Titles Redacted as Person Names in Signature Blocks
* **File:** [`src/python/marcut/rules.py:1096-1134`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/rules.py#L1096-L1134)
* **Root Cause:**
  When parsing signature lines (`SIGNATURE_LINE` loop), any line matching `Name: ...` is tested with `INDIVIDUAL_NAME.match(potential_name)`. When matched, a `NAME` span is appended with high confidence (`0.95`). However, unlike the rest of `rules.py` (lines 1020, 1049, 1070), this block **never calls `_is_excluded()`**:
  ```python
  if potential_name and INDIVIDUAL_NAME.match(potential_name):
      name_pos = line_text.find(potential_name, current_pos)
      if name_pos != -1:
          absolute_start = line_start + name_pos
          absolute_end = absolute_start + len(potential_name)
          original_name = text[absolute_start:absolute_end]

          out.append({
              "start": absolute_start,
              "end": absolute_end,
              "label": "NAME",
              "confidence": 0.95,
              "source": "rule_signature",
              "text": original_name
          })
  ```
* **Reproduction:**
  ```python
  run_rules("\nName: Authorized Representative\n")
  # Returns: [{'label': 'NAME', 'confidence': 0.95, 'text': 'Authorized Representative'}]
  ```
* **Impact:**
  Common legal signature block titles like `"Authorized Representative"`, `"Managing Director"`, and `"General Counsel"` (all explicitly listed in [`assets/excluded-words.txt`](file:///Users/mhm/dev/Marcut-2/assets/excluded-words.txt)) are classified as person names with 0.95 confidence and redacted.
* **Fix:**
  Add `if _is_excluded(potential_name) or _is_excluded(original_name): continue` before emitting the span.

---

### 3. [MEDIUM-HIGH] Defined-Term Name Extraction Bypasses Filter and Exclusions
* **File:** [`src/python/marcut/rules.py:428-435`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/rules.py#L428-L435), [`src/python/marcut/rules.py:1058-1095`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/rules.py#L1058-L1095)
* **Root Cause:**
  1. `_DEFINED_TERM_NAME` execution is located after the main `RULES` loop but fails to check `_rule_enabled("NAME", selected)`.
  2. It fails to check `_is_excluded(full_text)` or `_is_excluded(short_text)`.
  3. The regex pattern `\s*\(\s*["“”](?P<short>[A-Z][A-Za-z'\-\.]+)["”]\s*\)` only matches double quotation marks, completely ignoring single-quoted legal defined terms like `John Doe ('Doe')` or `John Doe (‘Doe’)`.
* **Reproduction:**
  ```python
  import os
  os.environ["MARCUT_RULE_FILTER"] = ""  # Disable all rules
  from marcut.rules import run_rules
  run_rules('Agreement between John Doe ("Doe")')
  # Returns NAME spans for 'John Doe' and 'Doe' despite all rules being disabled!
  ```
* **Impact:**
  - `MARCUT_RULE_FILTER` cannot suppress defined-term name detection.
  - Excluded terms are not honored.
  - Defined terms formatted with single quotes in legal contracts are never detected.
* **Fix:**
  - Check `if not _rule_enabled("NAME", selected): continue`.
  - Check `if _is_excluded(full_text) or _is_excluded(short_text): continue`.
  - Update `_DEFINED_TERM_NAME` to accept single quotes `["“”'‘’]`.

---

### 4. [MEDIUM] Organization Excluded Prefix Trimming Desynchronizes Slices
* **File:** [`src/python/marcut/rules.py:1040-1046`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/rules.py#L1040-L1046)
* **Root Cause:**
  When trimming excluded prefixes (e.g. `"FOR VALUE RECEIVED,"`) from an `ORG` candidate, the code splits on commas, filters segments, and rebuilds the string:
  ```python
  trimmed_text = ", ".join(segments[trim_count:])
  trim_start = sub.find(segments[trim_count])
  if trim_start > 0:
      s = s + trim_start
      e = s + len(trimmed_text)
      sub = trimmed_text
  ```
  If the original text contains extra spaces, tabs, or newlines after commas (e.g., `"FOR VALUE RECEIVED, Acme Holdings,   LLC"`), `len(trimmed_text)` does not equal the character count in `text`.
* **Impact:**
  `text[s:e]` becomes misaligned (e.g., cutting off the end of `"LLC"`). Downstream in [`pipeline.py:1368`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/pipeline.py#L1368), `_drop_invalid_spans` detects `text[start:end] != expected_text` and silently drops the redaction with `invalid_span_text_mismatch`, leaving the entity unredacted.
* **Fix:**
  Since only leading prefix segments are stripped, `s` advances by `trim_start`, `sub = sub[trim_start:]`, and `e` remains unchanged.

---

### 5. [MEDIUM] Unhandled JSON Array in `parse_llm_response`
* **File:** [`src/python/marcut/model.py:190-230`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/model.py#L190-L230), [`src/python/marcut/model.py:977`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/model.py#L977), [`src/python/marcut/model_enhanced.py:1541`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/model_enhanced.py#L1541)
* **Root Cause:**
  `parse_llm_response` is annotated as `Dict[str, Any]`. If the LLM returns a markdown block containing a JSON array (e.g., ````json\n[{"text": "John Doe", "type": "NAME"}]\n````), `json.loads` returns a `list`.
  The calling code in `model.py:977` and `model_enhanced.py:1541` immediately calls `parsed.get("entities", [])`, which crashes with:
  `AttributeError: 'list' object has no attribute 'get'`
* **Impact:**
  A completely valid entity extraction fails with an unhandled exception instead of being processed.
* **Fix:**
  In `parse_llm_response`, if the parsed object is a `list`, normalize it to `{"entities": loaded}`.

---

### 6. [MEDIUM] `ExcludedWordMatcher.swift` Missing Possessive Normalization
* **File:** [`src/swift/MarcutApp/Sources/MarcutApp/ExcludedWordMatcher.swift:139-148`](file:///Users/mhm/dev/Marcut-2/src/swift/MarcutApp/Sources/MarcutApp/ExcludedWordMatcher.swift#L139-L148)
* **Root Cause:**
  The Python reference implementation in [`src/python/marcut/model.py:368`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/model.py#L368) normalizes candidates by stripping trailing possessives via `_TRAILING_POSSESSIVE_RE.sub("", text)`. The Swift port in `ExcludedWordMatcher.normalizeForExclusion` strips determiners, punctuation, and whitespace, but omitted possessive stripping.
* **Impact:**
  The live preview sandbox in the Settings sheet reports "no match" when testing possessive forms (e.g., `"Company's"`, `"Borrower's"`), diverging from the production redaction engine.
* **Fix:**
  Add possessive regex stripping in `normalizeForExclusion` matching Python's `_TRAILING_POSSESSIVE_RE`.

---

### 7. [MEDIUM] App Store Release Script Rejects Explicit `--skip-notarization`
* **File:** [`scripts/sh/build_appstore_release.sh:1819-1832`](file:///Users/mhm/dev/Marcut-2/scripts/sh/build_appstore_release.sh#L1819-L1832)
* **Root Cause:**
  In commit `018634c6`, `APPSTORE_IDENTITY_DETECTED=true` was placed inside `if [ "$SKIP_NOTARIZATION" = false ]; then`.
  If a caller passes `--skip-notarization` on the CLI (setting `SKIP_NOTARIZATION=true`), the block is skipped.
  Subsequently, `final_validation` sees `SKIP_NOTARIZATION=true` but `APPSTORE_IDENTITY_DETECTED=false`, causing it to abort with:
  `Refusing to skip notarization validation without MARCUT_ALLOW_NOTARIZATION_SKIP=1`
* **Impact:**
  Calling `build_appstore_release.sh --skip-notarization` for an App Store build fails at the self-check.
* **Fix:**
  Check `if [[ "${DEVELOPER_ID}" != "Developer ID Application"* ]]; then APPSTORE_IDENTITY_DETECTED=true; fi` independently of whether `SKIP_NOTARIZATION` is already true.

---

### 8. [LOW-MEDIUM] `make_chunks` Infinite Loop on `max_len <= 0`
* **File:** [`src/python/marcut/chunker.py:41-49`](file:///Users/mhm/dev/Marcut-2/src/python/marcut/chunker.py#L41-L49)
* **Root Cause:**
  If `max_len <= 0`, `overlap` is clamped to 0, `j = min(n, i + max_len) = i`, and `i = max(0, j - overlap) = i`. `i` never advances, causing an infinite `while i < n:` loop.
* **Impact:**
  Any misconfigured chunk size hangs the process indefinitely.
* **Fix:**
  Validate `max_len`: `if max_len <= 0: raise ValueError("max_len must be positive")`.

---

### 9. [LOW] `FileAccessCoordinator.swift` Dead Branch
* **File:** [`src/swift/MarcutApp/Sources/MarcutApp/FileAccessCoordinator.swift:59-66`](file:///Users/mhm/dev/Marcut-2/src/swift/MarcutApp/Sources/MarcutApp/FileAccessCoordinator.swift#L59-L66)
* **Root Cause:**
  `currentSessionUUID` is generated as `UUID().uuidString` right before comparing to `storedSessionUUID`. It is guaranteed to never equal `storedSessionUUID`, rendering the `else` branch dead code.

---

### 10. [LOW-MAINTENANCE] `docs/release/python-sbom.json` Check Failure
* **File:** [`docs/release/python-sbom.json`](file:///Users/mhm/dev/Marcut-2/docs/release/python-sbom.json)
* **Root Cause:**
  The checked-in SBOM contains `charset-normalizer 3.4.7` and references a developer's old local path, whereas the staged `python_site` has `charset_normalizer-3.4.9`.
* **Impact:**
  Running `python3 scripts/generate_python_sbom.py --check` fails with `SBOM missing shipped components: [('library', 'charset-normalizer', '3.4.9')]`.
* **Fix:**
  Regenerate the tracked SBOM via `python3 scripts/generate_python_sbom.py --output docs/release/python-sbom.json`.
