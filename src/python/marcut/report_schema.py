"""
Pydantic models for the three on-disk JSON report shapes written by the
redaction pipeline: the audit report, the scrub/metadata report, and the
failure report.

This is step 1 of the bridge-schema migration described in
docs/design/bridge_schema_migration.md. It is Python-only: each model
mirrors the *current* dict shape exactly and is validated immediately
before the corresponding write boundary, so a malformed report fails
loudly in Python (where a stack trace is diagnosable) instead of being
silently guessed at on the Swift side.

Design constraints carried over from the design doc (do not relax these
without re-reading "Cancellation/Deadline and Transactional-Write
Interaction" in the design doc first):

- Validation must run on the in-memory dict *before* it is written to the
  temp path, never after. Callers are responsible for calling
  ``model_validate()`` before ``write_json_file()``/``write_report()`` and
  raising ``RedactionError`` (error_code ``ARTIFACT_FINALIZE_FAILED``) on
  failure -- this module does not know about the transactional-write path
  and must not be given that responsibility.
- ``FailureReport.message`` and ``FailureReport.technical_details`` stay
  free-form ``str`` (not enums, not constrained patterns). The deadline/
  timeout error classifier greps these fields for the substrings
  "timeout"/"deadline"; over-constraining them would silently break that
  classifier.
- These models are permissive on unknown top-level keys (``extra="allow"``)
  and on the internal shape of loosely-structured nested data (spans,
  report groups, forensic findings, etc. are typed as ``dict``/``list`` of
  ``Any`` rather than deeply modeled). The goal is to catch *shape drift*
  in the fields callers actually rely on (missing required keys, wrong
  top-level types), not to reject reports that are valid today just
  because a nested value takes a slightly different shape than expected.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class AuditReport(BaseModel):
    """Shape written by ``report.write_report()`` (see report.py)."""

    model_config = ConfigDict(extra="allow")

    created_at: str
    input_sha256: str
    model: str
    spans: List[Dict[str, Any]]
    warnings: Optional[List[Dict[str, Any]]] = None
    suppressed: Optional[List[Dict[str, Any]]] = None
    settings: Optional[Dict[str, Any]] = None


class ScrubReport(BaseModel):
    """Shape built by ``pipeline._build_scrub_report()``.

    This report is a large, heterogeneous forensic document (per-group
    before/after diffs, optional binary export manifests, optional deep
    package exploration, optional forensic findings). Only the top-level
    keys the rest of the codebase relies on are typed; their contents stay
    loosely typed on purpose (see module docstring).
    """

    model_config = ConfigDict(extra="allow")

    summary: Dict[str, Any]
    groups: Dict[str, Any]
    file_info: Optional[Dict[str, Any]] = None
    warnings: Optional[List[Dict[str, Any]]] = None
    forensic_findings: Optional[Dict[str, Any]] = None
    deep_explorer: Optional[Dict[str, Any]] = None
    binary_exports: Optional[List[Dict[str, Any]]] = None
    large_exports: Optional[List[Dict[str, Any]]] = None


class FailureReport(BaseModel):
    """Shape written by ``pipeline._write_failure_report()``.

    ``message`` and ``technical_details`` MUST remain free-form ``str`` --
    see module docstring and the AI_PROCESSING_TIMEOUT classifier in
    pipeline.py, which greps these fields for "timeout"/"deadline".
    """

    model_config = ConfigDict(extra="allow")

    status: str
    input_file: str
    error_code: str
    message: str
    technical_details: str
