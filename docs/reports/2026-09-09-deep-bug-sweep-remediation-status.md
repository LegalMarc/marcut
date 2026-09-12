# Deep Bug Sweep (2026-08-29) — Remediation Status

**Verified:** 2026-09-09, against `main` at `93991d4f`.
**Source audit:** `docs/audits/deep_bug_sweep_2026-08-29.md` (untracked working file) and its companion
`docs/audits/deep_bug_sweep_implementation_plan_2026-08-29.md`.

## Summary

All 10 findings from the August 29 sweep are now closed. Nine were resolved by work that landed
between the audit date and today — chiefly the `docx_pkg/` package split (#72-#76) and the #83-#88
follow-up batch — without the implementation plan ever being executed as written. The tenth
(finding 9) was still open and is fixed by the commit that carries this report.

The audit documents are therefore **spent**. They should not be used to schedule further work.
This file exists so a later session does not re-derive that conclusion from scratch.

## Finding-by-finding

| # | Severity | Finding | Status | Where it was resolved |
|---|---|---|---|---|
| 1 | HIGH | Metadata hardening bypassed by an early `continue` in the DOCX ZIP rewrite | Closed | `docx_pkg/zip_postprocess.py`: the `clean_language_settings` branch no longer writes-and-continues; data flows through `clean_form_defaults`, `clean_nonstandard_xml`, `clean_microsoft_extension_xml` and `clean_alternate_content`, then writes once at the end of the loop |
| 2 | HIGH | Corporate officer titles redacted as person names in signature blocks | Closed | `rules.py`: the `SIGNATURE_LINE` loop calls `_is_excluded(potential_name)` before emitting a NAME span |
| 3 | MEDIUM-HIGH | Defined-term extraction bypassed `MARCUT_RULE_FILTER` and exclusions; missed single quotes | Closed | `rules.py`: loop is gated on `_rule_enabled("NAME", selected)`, both emit sites are guarded by `_is_excluded`, and `_DEFINED_TERM_NAME` accepts `["""''']` |
| 4 | MEDIUM | ORG prefix trimming desynchronised character slice offsets | Closed | `rules.py`: trimming uses direct slicing (`sub = sub[trim_start:]`, `s = s + trim_start`) instead of recomputing a length from a re-joined string |
| 5 | MEDIUM | Top-level JSON array from the LLM crashed `parse_llm_response` callers | Closed | `model.py`: `isinstance(loaded, list)` normalises to `{"entities": loaded}` |
| 6 | MEDIUM | Swift excluded-word matcher lacked possessive normalisation | Closed | `ExcludedWordMatcher.swift`: `trailingPossessiveRegex` strips `'s` / `'` (straight and curly) |
| 7 | MEDIUM | App Store build script rejected an explicit `--skip-notarization` | Closed | `scripts/sh/build_appstore_release.sh`: `APPSTORE_IDENTITY_DETECTED=true` now sits outside the `SKIP_NOTARIZATION = false` guard, exactly the fix the plan proposed |
| 8 | LOW-MEDIUM | `make_chunks` infinite loop when `max_len <= 0` | Closed | `chunker.py`: raises `ValueError("max_len must be positive")`, and separately guards `overlap >= max_len` |
| 9 | LOW | `FileAccessCoordinator` dead session-tracking branch | **Closed by this commit** | See below |
| 10 | LOW | Tracked SBOM recorded charset-normalizer 3.4.7 against a shipped 3.4.9 | Closed | #86, commit `32387eac` |

## Finding 9, in detail

`FileAccessCoordinator` is a `private init()` singleton (`static let shared`), so it is constructed
exactly once per process launch. `initializeSessionTracking()` generated a fresh
`UUID().uuidString` and compared it against a UUID persisted in UserDefaults under
`MarcutApp_PermissionSessionUUID`. Because the UUID was minted immediately before the comparison,
the two values could never be equal:

- the `else` branch ("Continuing existing session") was unreachable;
- the resets of `hasRequestedPermissionsThisSession` and `sessionPermissionsEstablished` were
  redundant, since both already initialise to `false`;
- the persisted key was written on every launch and never meaningfully read.

Behaviour was correct by accident, because once-per-launch construction is what the flags wanted
anyway. The fix removes the unreachable branch, the redundant resets and the unused key, and
replaces the method with a `logSessionStart()` that just records the launch. No behavioural change.
`MarcutApp_PermissionSessionUUID` is no longer written; nothing else in the codebase read it.

## Verification

```
ruff check src/python tests                                  # All checks passed
swiftformat --lint src/swift/MarcutApp/Sources .../Tests      # 0/32 files require formatting
PYTHONPATH=src/python python3 -m pytest -q                   # 790 passed, 6 skipped
swift test --package-path src/swift/MarcutApp                # 109 executed, 0 failures
```

## Related

- `docs/BACKLOG.md` §2 — the "God Module in Python" item is now marked shipped; the remaining
  technical-debt entries are the view-controller decomposition and the bridge schema migration.
- `docs/design/bridge_schema_migration.md` — step 1 landed as `report_schema.py` (#67); later steps
  are the next open body of work.
