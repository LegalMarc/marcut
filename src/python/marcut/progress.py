"""
Progress tracking and time estimation for Marcut redaction pipeline.
"""

import time
from typing import Dict, Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum


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


@dataclass
class ProgressUpdate:
    """Progress update information."""
    phase: ProcessingPhase
    phase_progress: float  # 0.0 to 1.0
    overall_progress: float  # 0.0 to 1.0
    phase_name: str
    estimated_remaining: float  # seconds
    elapsed_time: float  # seconds
    message: Optional[str] = None


class ProgressTracker:
    """Tracks progress through processing phases with time estimation."""

    def __init__(self, callback, text: str, word_count: Optional[int] = None):
        self.callback = callback
        self.is_simple_callback = False

        # Detect callback signature: simple (chunk, total, message) vs rich (ProgressUpdate)
        import inspect
        try:
            sig = inspect.signature(callback)
        except (TypeError, ValueError):
            sig = None

        if sig is not None and len(sig.parameters) == 3:
            # Simple callback: (chunk, total, message)
            self.is_simple_callback = True
        else:
            # Rich callback: (ProgressUpdate)
            self.is_simple_callback = False
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
        
        # Send callback in appropriate format
        if self.is_simple_callback:
            # Convert to simple (chunk, total, message) format
            chunk = int(update.phase_progress * 100)  # 0-100 percentage
            total = 100
            message = f"{update.phase_name}: {update.phase_progress:.0%} - {update.message or ''}"
            self.callback(chunk, total, message)
        else:
            # Send rich ProgressUpdate object
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
