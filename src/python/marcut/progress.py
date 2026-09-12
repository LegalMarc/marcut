"""
Progress tracking and time estimation for Marcut redaction pipeline.
"""

import json
import time
from typing import Annotated, Any, Callable, Dict, Literal, Optional, Union
from dataclasses import dataclass
from enum import Enum

import pydantic.dataclasses
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ProcessingPhase(Enum):
    """Processing phases for document redaction."""
    PREFLIGHT = "preflight"
    RULE_DETECTION = "rule_detection"
    DOCUMENT_ANALYSIS = "document_analysis"
    LLM_EXTRACTION = "llm_extraction"
    VALIDATION = "validation"
    MERGING = "merging"
    TRACK_CHANGES = "track_changes"
    COMPLETE = "complete"


@dataclass
class PhaseInfo:
    """Information about a processing phase."""
    name: str
    display_name: str
    base_duration: float  # Base duration in seconds
    complexity_factor: float  # Multiplier based on document complexity


# Phase definitions with timing estimates
PHASE_INFO = {
    ProcessingPhase.PREFLIGHT: PhaseInfo(
        "preflight", "Loading Document", 2.5, 0.1
    ),
    ProcessingPhase.RULE_DETECTION: PhaseInfo(
        "rule_detection", "Detecting Structured Data", 4.0, 0.2
    ),
    ProcessingPhase.DOCUMENT_ANALYSIS: PhaseInfo(
        "document_analysis", "Analyzing Document", 3.0, 0.15
    ),
    ProcessingPhase.LLM_EXTRACTION: PhaseInfo(
        "llm_extraction", "AI Entity Extraction", 22.5, 1.0
    ),
    ProcessingPhase.VALIDATION: PhaseInfo(
        "validation", "Validating Entities", 7.5, 0.3
    ),
    ProcessingPhase.MERGING: PhaseInfo(
        "merging", "Merging & Clustering", 2.5, 0.1
    ),
    ProcessingPhase.TRACK_CHANGES: PhaseInfo(
        "track_changes", "Generating Track Changes", 4.0, 0.2
    ),
}


class TimeEstimator:
    """Estimates processing time based on document characteristics."""
    
    def __init__(self):
        self.base_times = {phase: info.base_duration for phase, info in PHASE_INFO.items()}
        self.complexity_factors = {phase: info.complexity_factor for phase, info in PHASE_INFO.items()}
    
    def estimate_document_complexity(self, text: str, word_count: Optional[int] = None) -> float:
        """Estimate document complexity factor (0.5 = simple, 1.0 = normal, 2.0 = complex)."""
        if word_count is None:
            word_count = len(text.split())
        
        # Base complexity on word count
        if word_count < 500:
            base_complexity = 0.6
        elif word_count < 2000:
            base_complexity = 1.0
        elif word_count < 5000:
            base_complexity = 1.4
        else:
            base_complexity = 2.0
        
        # Adjust based on content characteristics
        text_lower = text.lower()
        
        # Legal document complexity indicators
        legal_terms = ["whereas", "party", "agreement", "contract", "shareholder", "corporation"]
        legal_score = sum(1 for term in legal_terms if term in text_lower) / len(legal_terms)
        
        # Entity density (rough estimate)
        potential_names = len([w for w in text.split() if w[0].isupper() if len(w) > 2])
        name_density = potential_names / word_count if word_count > 0 else 0
        
        # Adjust complexity
        complexity = base_complexity * (1.0 + legal_score * 0.3 + name_density * 0.2)
        return min(max(complexity, 0.3), 3.0)  # Clamp between 0.3 and 3.0
    
    def estimate_phase_duration(self, phase: ProcessingPhase, complexity: float) -> float:
        """Estimate duration for a specific phase."""
        if phase not in self.base_times:
            return 1.0
        
        base_time = self.base_times[phase]
        factor = self.complexity_factors[phase]
        return base_time + (base_time * factor * (complexity - 1.0))
    
    def estimate_total_duration(self, complexity: float) -> float:
        """Estimate total processing duration."""
        total = 0.0
        for phase in ProcessingPhase:
            if phase != ProcessingPhase.COMPLETE:
                total += self.estimate_phase_duration(phase, complexity)
        return total


@pydantic.dataclasses.dataclass
class ProgressUpdate:
    """Progress update information.

    A ``pydantic`` dataclass rather than a plain one (bridge schema
    migration step 4a, docs/design/bridge_schema_migration.md, #92) so a
    malformed update (e.g. a non-numeric progress value) raises immediately
    on construction instead of crossing the Swift bridge as silently wrong
    data. ``phase`` stays a ``ProcessingPhase`` enum member, not a string --
    pydantic validates and coerces into the enum without widening it.
    """
    phase: ProcessingPhase
    phase_progress: float  # 0.0 to 1.0
    overall_progress: float  # 0.0 to 1.0
    phase_name: str
    estimated_remaining: float  # seconds
    elapsed_time: float  # seconds
    message: Optional[str] = None


# --- Mass-event models (bridge schema migration step 4b, issue #93) -------
#
# `IntelligentRedactionPipeline.process_document`'s `emit_mass_event()`
# (model_enhanced.py) prints one JSON object per line on stdout -- the
# channel `PythonKitBridge.swift` reads and `DocumentModels.swift`'s
# `ingestProgressPayload` parses structurally to drive the enhanced-
# detection progress bar (see the Notes on issue #93: the design doc's
# claim that Swift only displays these as text was verified false on
# 2026-09-09). Each dict `emit_mass_event` is handed must validate against
# exactly one of these five models -- keyed on `type`, `extra="forbid"` so
# an unexpected field is caught at the same point a missing/mistyped one
# would be -- before it is serialized, so a producer-side typo or shape
# drift raises in Python instead of crossing the bridge as silently wrong
# or dropped data.
#
# Field sets below are copied from each emit site, not inferred from the
# Swift consumer, per the ticket's instruction.


class MassTotalEvent(BaseModel):
    """Emitted once before extraction begins, with the document's total
    character count across all chunks."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["mass_total"] = "mass_total"
    value: int


class ChunkStartEvent(BaseModel):
    """Emitted immediately before a chunk is dispatched to the extractor."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["chunk_start"] = "chunk_start"
    size: int
    estimated_time: float


class ChunkEndEvent(BaseModel):
    """Emitted when a chunk's extraction finishes, successfully or not."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["chunk_end"] = "chunk_end"
    size: int


class KeepaliveEvent(BaseModel):
    """Emitted every ~3s while extraction is in flight so a slow model call
    doesn't look hung. `chunk`/`total` are only attached once at least one
    chunk has started, so both stay optional."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["keepalive"] = "keepalive"
    message: str
    chunk: Optional[int] = None
    total: Optional[int] = None


class TokenProgressEvent(BaseModel):
    """Intra-chunk streaming progress emitted as an Ollama chunk extraction
    call streams NDJSON response lines (docs/design/streaming_progress.md,
    Option B).

    `eval_count` is `Optional` because Ollama only reports it on the final
    `done: true` line of the stream: `model.py`'s streaming loop passes
    `event.get("eval_count")` straight through on every emission, its
    callback contract is `Callable[[int, Optional[int]], None]`
    (model.py, llm_timing.py), and the guard around that call deliberately
    fires when a response `piece` arrived *without* an `eval_count`. So
    `None` here is the normal case, not a malformation -- typing it `int`
    made validation reject every intermediate event and, because the
    callback is invoked inside a `try: ... except Exception: pass`, drop
    intra-chunk progress silently.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["token_progress"] = "token_progress"
    chunk_index: int
    chars: int
    eval_count: Optional[int] = None


MassEvent = Annotated[
    Union[
        MassTotalEvent,
        ChunkStartEvent,
        ChunkEndEvent,
        KeepaliveEvent,
        TokenProgressEvent,
    ],
    Field(discriminator="type"),
]

_MASS_EVENT_ADAPTER: TypeAdapter = TypeAdapter(MassEvent)

# The exact `type` strings `DocumentModels.swift`'s `ingestProgressPayload`
# switch recognizes, readable from Python without opening the Swift source.
# This is a mirror, so it is never the authority: the parity test
# (`test_emitted_type_strings_match_swift_handled_set`) parses the switch out
# of DocumentModels.swift and asserts models == this constant == the parsed
# Swift set, so drift on any of the three sides fails the suite (issue #93).
# `token_progress` is handled there via an explicit no-op case (deliberately
# ignored, not decoded into the progress bar) rather than driving progress --
# see the switch's own comment.
SWIFT_HANDLED_MASS_EVENT_TYPES = frozenset(
    {"mass_total", "chunk_start", "chunk_end", "keepalive", "token_progress"}
)


def validate_mass_event(payload: Dict[str, Any]) -> MassEvent:
    """Validate one `emit_mass_event` payload dict against the closed set
    of mass-event models above.

    Raises `pydantic.ValidationError` on an unknown `type`, a missing or
    mistyped field, or an unexpected extra field. Deliberately not caught
    here -- the caller decides how a malformed event (a programming error)
    should surface; see `emit_mass_event`'s own docstring/comments in
    model_enhanced.py. This path fires many times per document, so it stays
    a plain function around a cached `TypeAdapter` rather than doing any
    per-call model construction beyond what validation itself requires.
    """
    return _MASS_EVENT_ADAPTER.validate_python(payload)


def serialize_mass_event(event: MassEvent) -> str:
    """Serialize an already-validated `MassEvent` for the stdout mass-event
    channel the Swift bridge reads.

    Callers used to serialize the raw input dict they handed to
    `validate_mass_event` instead of the validated model it returned (#95).
    Pydantic's default coercion is lax -- a payload like
    `{"type": "mass_total", "value": "4200"}` validates cleanly (the string
    coerces to an int) -- so serializing the original dict let an
    uncoerced value cross the bridge even though validation "passed".
    Serializing the model here closes that gap.

    `exclude_unset=True` reproduces `json.dumps(payload)`'s behavior of
    omitting fields the caller never included (e.g. `KeepaliveEvent`'s
    optional `chunk`/`total` when no chunk is in flight yet) rather than
    emitting them as explicit `null`s that were never in the original
    payload.
    """
    return json.dumps(event.model_dump(exclude_unset=True))


class ProgressTracker:
    """Tracks progress through processing phases with time estimation."""

    def __init__(self, callback, text: str, word_count: Optional[int] = None):
        # Every registered callback receives a single rich ProgressUpdate
        # object (bridge schema migration step 4a, #92). A parallel
        # `(chunk, total, message)` three-argument shape used to be
        # dispatched to callbacks `inspect.signature` reported as taking
        # exactly three parameters; the audit for #92 found no such
        # callback registered anywhere in the codebase (CLI and GUI both
        # register a one-parameter rich callback via
        # `create_progress_callback`, and the Swift bridge's callback is an
        # unintrospectable `PyCFunction` that `inspect.signature` cannot
        # read the arity of, so it always took the rich path too) and
        # removed the branch. See the audit comment on issue #92 for the
        # full trace.
        self.callback = callback
        self.estimator = TimeEstimator()
        self.complexity = self.estimator.estimate_document_complexity(text, word_count)
        self.start_time = time.time()
        self.phase_start_time = time.time()
        self.current_phase = ProcessingPhase.PREFLIGHT
        self.phase_durations = {}
        
        # Calculate phase weights for overall progress
        total_estimated = self.estimator.estimate_total_duration(self.complexity)
        self.phase_weights = {}
        self.phase_cumulative = {}
        cumulative = 0.0
        
        for phase in ProcessingPhase:
            if phase == ProcessingPhase.COMPLETE:
                self.phase_weights[phase] = 0.0
                self.phase_cumulative[phase] = 1.0
            else:
                duration = self.estimator.estimate_phase_duration(phase, self.complexity)
                weight = duration / total_estimated if total_estimated > 0 else 0.0
                self.phase_weights[phase] = weight
                self.phase_cumulative[phase] = cumulative + weight
                cumulative += weight
    
    def update_phase(self, phase: ProcessingPhase, progress: float = 0.0, message: Optional[str] = None):
        """Update current phase and progress."""
        now = time.time()
        
        # Record phase duration if switching phases
        if phase != self.current_phase:
            if self.current_phase in PHASE_INFO:
                self.phase_durations[self.current_phase] = now - self.phase_start_time
            self.phase_start_time = now
            self.current_phase = phase
        
        # Calculate overall progress
        phase_weight = self.phase_weights.get(phase, 0.0)
        cumulative_before = self.phase_cumulative.get(phase, 0.0) - phase_weight
        overall_progress = cumulative_before + (phase_weight * progress)
        overall_progress = min(max(overall_progress, 0.0), 1.0)
        
        # Estimate remaining time
        elapsed = now - self.start_time
        if overall_progress > 0.01:
            estimated_total = elapsed / overall_progress
            estimated_remaining = max(estimated_total - elapsed, 0.0)
        else:
            estimated_remaining = self.estimator.estimate_total_duration(self.complexity)
        
        # Create update
        phase_info = PHASE_INFO.get(phase, PhaseInfo(phase.value, phase.value.replace('_', ' ').title(), 1.0, 0.0))
        update = ProgressUpdate(
            phase=phase,
            phase_progress=progress,
            overall_progress=overall_progress,
            phase_name=phase_info.display_name,
            estimated_remaining=estimated_remaining,
            elapsed_time=elapsed,
            message=message
        )
        
        # Send the rich ProgressUpdate object -- the only shape this
        # tracker dispatches (see __init__).
        self.callback(update)
    
    def complete(self):
        """Mark processing as complete."""
        self.update_phase(ProcessingPhase.COMPLETE, 1.0, "Redaction complete!")


# Convenience function for creating progress callbacks
def create_progress_callback(gui_update_func: Callable[[ProgressUpdate], None]) -> Callable[[ProgressUpdate], None]:
    """Create a progress callback that safely updates the GUI."""
    def callback(update: ProgressUpdate):
        try:
            gui_update_func(update)
        except Exception as e:
            print(f"Progress callback error: {e}")
    return callback
