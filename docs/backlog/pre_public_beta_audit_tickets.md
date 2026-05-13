# Pre-Public-Beta Audit Tickets

This backlog tracks the approved remediation scope for public beta. Marcut is treated as a local-first redaction app for confidential legal documents and PII. HIPAA/PHI-specific work is explicitly out of scope.

## T0 - Backlog And Review Workflow

Severity: High
Status: Completed with review-tool caveat

Acceptance criteria:
- This file exists before implementation work begins.
- Each remediation branch is stacked from the previous branch.
- Local review is run after each stack segment. If no automated Opus workflow exists locally, use an available local/manual review pass and record gaps in the final handoff.

Tests/review:
- Confirm `git status --short --branch` shows the intended stacked branch.
- Confirm all implementation tickets below have test coverage or an explicit rationale.
- Opus was not available locally. Existing subagent threads were at capacity and returned no usable redirected diff-review text, so the implementation used manual local diff review plus full Python/Swift verification.

## T1 - Loopback-Only Inference

Severity: High
Status: Completed

Acceptance criteria:
- Python inference uses loopback Ollama hosts by default.
- Remote Ollama hosts require an explicit unsafe override.
- Tests cover default loopback behavior, custom loopback ports, and rejected remote hosts.

Tests/review:
- `python3 -m pytest tests/test_model.py tests/test_failure_scenarios.py tests/test_security.py -q`

## T2 - Generated Python Source Boundary

Severity: High
Status: Completed

Acceptance criteria:
- Swift subprocess/Python execution paths do not interpolate unescaped model or mode values into generated Python source.
- Malicious quote-bearing model/mode values are represented as data, not executable source.

Tests/review:
- Added regression coverage for malicious model/mode validation and verified Swift no longer interpolates model/mode as executable Python source.
- `swift test --package-path src/swift/MarcutApp`

## T3 - Review Artifact Language

Severity: Medium
Status: Completed

Acceptance criteria:
- Product/help/report language clearly says the default DOCX is a Track Changes review artifact.
- No separate sanitized/final output is added.
- Existing Track Changes behavior is preserved.

Tests/review:
- Documentation link/check review.
- Existing DOCX revision tests continue to pass.

## T4 - Report Handling Hardening

Severity: High
Status: Completed

Acceptance criteria:
- Raw report text remains enabled by default.
- Share/print/export surfaces warn that reports may contain original detected text and document metadata.
- App-managed report/cache files use restrictive permissions where practical.
- Metadata report cache cleanup covers the actual report-only cache path.

Tests/review:
- Add tests for report file permissions and cache cleanup path behavior where feasible.
- `python3 -m pytest tests/test_report_common.py tests/test_metadata_scrubbing.py -q`

## T5 - Log And Launch-Argument Redaction

Severity: Medium
Status: Completed

Acceptance criteria:
- Raw LLM responses and document-derived strings are not logged by default.
- Debug/failure paths redact path-valued launch arguments and report/output paths.
- Existing diagnostic usefulness is preserved without exposing sensitive document names or content.

Tests/review:
- Add Python tests for redacted LLM parse failures and failure reports.
- Add Swift/static tests for launch-argument redaction if feasible.

## T6 - Cancellation And Timeout Reliability

Severity: High
Status: Completed

Acceptance criteria:
- LLM requests use bounded, cooperative timeouts instead of one 120-minute non-streaming request.
- Processing and download cancellation paths actively stop the current request/task/process.
- User-visible cancel/timeout behavior matches implementation.

Tests/review:
- Add unit tests around Python timeout settings and Swift cancellation state where feasible.
- Manual review for model download cancellation if UI/runtime testing is not practical in CI.

## T7 - Report Expansion Limits

Severity: High
Status: Completed

Acceptance criteria:
- Normal report generation does not unboundedly export all DOCX parts or inline large images.
- Deep/forensic exploration is explicit and bounded by size/count limits.
- Large report artifacts produce warnings instead of unbounded disk/memory expansion.

Tests/review:
- Add tests for default no deep export and size/count limit behavior.

## T8 - Release And CI Gates

Severity: High
Status: Completed

Acceptance criteria:
- CI no longer calls missing packaging scripts.
- CI runs Swift tests.
- Dependency audit/SBOM or equivalent release gate is available.
- Notarization skip behavior cannot produce a green release/tag result without an explicit local-only override.
- Markdown/public links are checked or corrected.

Tests/review:
- `python3 -m pytest -q`
- `swift test --package-path src/swift/MarcutApp`
- Run the release-gate scripts in dry-run/read-only modes where available.
