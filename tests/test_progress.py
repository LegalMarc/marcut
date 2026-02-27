"""
Tests for the progress.py module - progress tracking and time estimation.
"""

import pytest
import time
from marcut.progress import (
    ProcessingPhase, PhaseInfo, PHASE_INFO,
    TimeEstimator, ProgressUpdate, ProgressTracker,
    create_progress_callback
)


class TestProcessingPhaseEnum:
    """Test ProcessingPhase enum."""
    
    def test_all_phases_defined(self):
        """Test that all expected phases are defined."""
        expected = [
            'PREFLIGHT', 'RULE_DETECTION', 'DOCUMENT_ANALYSIS',
            'LLM_EXTRACTION', 'VALIDATION', 'MERGING', 
            'TRACK_CHANGES', 'COMPLETE'
        ]
        actual = [p.name for p in ProcessingPhase]
        
        assert set(expected) == set(actual)
    
    def test_phase_values_are_strings(self):
        """Test that phase values are strings."""
        for phase in ProcessingPhase:
            assert isinstance(phase.value, str)


class TestPhaseInfo:
    """Test PhaseInfo dataclass and PHASE_INFO dictionary."""
    
    def test_all_phases_have_info(self):
        """Test that all non-COMPLETE phases have info."""
        for phase in ProcessingPhase:
            if phase != ProcessingPhase.COMPLETE:
                assert phase in PHASE_INFO
    
    def test_phase_info_structure(self):
        """Test that PhaseInfo has correct structure."""
        for phase, info in PHASE_INFO.items():
            assert isinstance(info.name, str)
            assert isinstance(info.display_name, str)
            assert isinstance(info.base_duration, (int, float))
            assert isinstance(info.complexity_factor, (int, float))
            assert info.base_duration > 0
            assert info.complexity_factor >= 0
    
    def test_llm_extraction_longest(self):
        """Test that LLM extraction has longest base duration."""
        llm_duration = PHASE_INFO[ProcessingPhase.LLM_EXTRACTION].base_duration
        
        for phase, info in PHASE_INFO.items():
            if phase != ProcessingPhase.LLM_EXTRACTION:
                assert info.base_duration <= llm_duration


class TestTimeEstimator:
    """Test TimeEstimator class."""
    
    def test_initialization(self):
        """Test that TimeEstimator initializes correctly."""
        estimator = TimeEstimator()
        
        assert hasattr(estimator, 'base_times')
        assert hasattr(estimator, 'complexity_factors')
    
    def test_estimate_simple_document(self):
        """Test complexity estimation for simple document."""
        estimator = TimeEstimator()
        
        simple_text = "This is a very simple document with few words."
        complexity = estimator.estimate_document_complexity(simple_text)
        
        # Simple docs should have low complexity
        assert complexity < 1.0
    
    def test_estimate_complex_document(self):
        """Test complexity estimation for complex document."""
        estimator = TimeEstimator()
        
        complex_text = """
        WHEREAS the party of the first part agrees to the contract.
        The Corporation and the Shareholder hereby agree to the following terms.
        This Agreement shall be governed by the laws of the State of Delaware.
        """ * 50  # Make it long enough to trigger complex threshold
        
        complexity = estimator.estimate_document_complexity(complex_text)
        
        # Complex docs should have higher complexity
        assert complexity >= 1.0
    
    def test_complexity_bounds(self):
        """Test that complexity is bounded."""
        estimator = TimeEstimator()
        
        # Very short
        simple = estimator.estimate_document_complexity("hi")
        assert simple >= 0.3
        assert simple <= 3.0
        
        # Very long with many legal terms
        long_legal = "Whereas the agreement contract shareholder corporation " * 1000
        complex_val = estimator.estimate_document_complexity(long_legal)
        assert complex_val >= 0.3
        assert complex_val <= 3.0
    
    def test_estimate_phase_duration(self):
        """Test phase duration estimation."""
        estimator = TimeEstimator()
        
        # Normal complexity
        duration = estimator.estimate_phase_duration(ProcessingPhase.PREFLIGHT, 1.0)
        assert duration > 0
        
        # Higher complexity should give longer duration
        duration_complex = estimator.estimate_phase_duration(ProcessingPhase.LLM_EXTRACTION, 2.0)
        duration_simple = estimator.estimate_phase_duration(ProcessingPhase.LLM_EXTRACTION, 0.5)
        assert duration_complex > duration_simple
    
    def test_estimate_total_duration(self):
        """Test total duration estimation."""
        estimator = TimeEstimator()
        
        total = estimator.estimate_total_duration(1.0)
        assert total > 0
        
        # Sum of individual phases should equal total
        phase_sum = sum(
            estimator.estimate_phase_duration(phase, 1.0)
            for phase in ProcessingPhase
            if phase != ProcessingPhase.COMPLETE
        )
        assert abs(total - phase_sum) < 0.001


class TestProgressUpdate:
    """Test ProgressUpdate dataclass."""
    
    def test_create_update(self):
        """Test creating a progress update."""
        update = ProgressUpdate(
            phase=ProcessingPhase.PREFLIGHT,
            phase_progress=0.5,
            overall_progress=0.1,
            phase_name="Loading Document",
            estimated_remaining=30.0,
            elapsed_time=5.0,
            message="Loading..."
        )
        
        assert update.phase == ProcessingPhase.PREFLIGHT
        assert update.phase_progress == 0.5
        assert update.overall_progress == 0.1
        assert update.estimated_remaining == 30.0
    
    def test_optional_message(self):
        """Test that message is optional."""
        update = ProgressUpdate(
            phase=ProcessingPhase.COMPLETE,
            phase_progress=1.0,
            overall_progress=1.0,
            phase_name="Complete",
            estimated_remaining=0.0,
            elapsed_time=60.0
        )
        
        assert update.message is None


class TestProgressTracker:
    """Test ProgressTracker class."""
    
    def test_initialization(self):
        """Test ProgressTracker initialization."""
        updates = []
        tracker = ProgressTracker(
            callback=lambda u: updates.append(u),
            text="Sample document text",
            word_count=100
        )
        
        assert tracker.current_phase == ProcessingPhase.PREFLIGHT
        assert hasattr(tracker, 'complexity')
        assert tracker.complexity > 0
    
    def test_simple_callback_detection(self):
        """Test that simple callbacks are detected correctly."""
        # Simple callback (3 params)
        def simple_cb(chunk, total, message):
            pass
        
        tracker = ProgressTracker(simple_cb, "test", 10)
        assert tracker.is_simple_callback == True
    
    def test_rich_callback_detection(self):
        """Test that rich callbacks are detected correctly."""
        # Rich callback (1 param)
        def rich_cb(update):
            pass
        
        tracker = ProgressTracker(rich_cb, "test", 10)
        assert tracker.is_simple_callback == False
    
    def test_update_phase(self):
        """Test phase updates."""
        updates = []
        tracker = ProgressTracker(
            callback=lambda u: updates.append(u),
            text="Test document",
            word_count=50
        )
        
        tracker.update_phase(ProcessingPhase.RULE_DETECTION, 0.5, "Detecting...")
        
        assert len(updates) == 1
        assert updates[0].phase == ProcessingPhase.RULE_DETECTION
        assert updates[0].phase_progress == 0.5
    
    def test_phase_switching_records_duration(self):
        """Test that switching phases records duration."""
        tracker = ProgressTracker(
            callback=lambda u: None,
            text="Test",
            word_count=10
        )
        
        tracker.update_phase(ProcessingPhase.PREFLIGHT, 1.0)
        time.sleep(0.05)  # 50ms
        tracker.update_phase(ProcessingPhase.RULE_DETECTION, 0.0)
        
        assert ProcessingPhase.PREFLIGHT in tracker.phase_durations
        assert tracker.phase_durations[ProcessingPhase.PREFLIGHT] >= 0.04
    
    def test_complete_marks_done(self):
        """Test that complete() properly marks as done."""
        updates = []
        tracker = ProgressTracker(
            callback=lambda u: updates.append(u),
            text="Test",
            word_count=10
        )
        
        tracker.complete()
        
        assert any(u.phase == ProcessingPhase.COMPLETE for u in updates)
        assert any(u.overall_progress == 1.0 for u in updates)
    
    def test_progress_bounded(self):
        """Test that progress values are bounded 0-1."""
        updates = []
        tracker = ProgressTracker(
            callback=lambda u: updates.append(u),
            text="Test",
            word_count=10
        )
        
        # Try to set invalid progress
        tracker.update_phase(ProcessingPhase.PREFLIGHT, 1.5)  # > 1.0
        tracker.update_phase(ProcessingPhase.PREFLIGHT, -0.5)  # < 0.0
        
        for update in updates:
            assert 0.0 <= update.overall_progress <= 1.0


class TestCreateProgressCallback:
    """Test create_progress_callback helper."""
    
    def test_callback_wrapper(self):
        """Test that callback wrapper works."""
        updates = []
        
        def gui_update(update):
            updates.append(update)
        
        callback = create_progress_callback(gui_update)
        
        update = ProgressUpdate(
            phase=ProcessingPhase.COMPLETE,
            phase_progress=1.0,
            overall_progress=1.0,
            phase_name="Complete",
            estimated_remaining=0.0,
            elapsed_time=10.0
        )
        
        callback(update)
        
        assert len(updates) == 1
    
    def test_callback_handles_exceptions(self):
        """Test that callback wrapper handles exceptions gracefully."""
        def failing_update(update):
            raise ValueError("Test error")
        
        callback = create_progress_callback(failing_update)
        
        update = ProgressUpdate(
            phase=ProcessingPhase.COMPLETE,
            phase_progress=1.0,
            overall_progress=1.0,
            phase_name="Complete",
            estimated_remaining=0.0,
            elapsed_time=10.0
        )
        
        # Should not raise - error is caught internally
        callback(update)
