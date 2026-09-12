"""
Tests for the progress.py module - progress tracking and time estimation.
"""

import json
import os
import re
import time
import typing

import pydantic
import pytest

from marcut.progress import (
    ProcessingPhase, PHASE_INFO,
    TimeEstimator, ProgressUpdate, ProgressTracker,
    create_progress_callback,
    MassEvent, ProgressEvent, SWIFT_HANDLED_MASS_EVENT_TYPES,
    validate_progress_event, serialize_progress_event,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCUMENT_MODELS_SWIFT_PATH = os.path.join(
    REPO_ROOT, "src/swift/MarcutApp/Sources/MarcutApp/DocumentModels.swift"
)


def _swift_handled_mass_event_types():
    """Parse `ingestProgressPayload`'s `switch type { case "...": ... }` out
    of DocumentModels.swift and return the `type` strings it handles.

    Derives the consumer-side set directly from the Swift source -- the same
    style tests/test_model_config.py uses for models.json -- rather than
    restating it as a hand-maintained Python mirror. A hand-maintained
    mirror only catches producer-side drift (a Python model type this
    constant forgets to list); it cannot catch a `case` silently dropped
    from the Swift switch itself, which is exactly the class of bug
    issue #93 exists to fix.
    """
    with open(DOCUMENT_MODELS_SWIFT_PATH, "r", encoding="utf-8") as f:
        source = f.read()

    func_match = re.search(
        r"func ingestProgressPayload\(.*?\n(.*?)\n    (?:private )?func ",
        source,
        re.DOTALL,
    )
    assert func_match, "ingestProgressPayload not found in DocumentModels.swift"

    switch_match = re.search(r"switch type \{(.*?)\n        \}", func_match.group(1), re.DOTALL)
    assert switch_match, "switch type { ... } not found in ingestProgressPayload"

    return set(re.findall(r'case "([a-zA-Z_]+)":', switch_match.group(1)))


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
        for _phase, info in PHASE_INFO.items():
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
    """Test the ProgressUpdate model -- the rich phase_update member of the
    unified `ProgressEvent` union (issue #96)."""

    def test_type_discriminator_defaults_to_phase_update(self):
        """`type` is the discriminator every `ProgressEvent` member carries
        (issue #96's one-channel consolidation); ProgressUpdate defaults it
        so existing call sites that never pass `type=` explicitly still
        produce a correctly-discriminated instance."""
        update = ProgressUpdate(
            phase=ProcessingPhase.PREFLIGHT,
            phase_progress=0.5,
            overall_progress=0.1,
            phase_name="Loading Document",
            estimated_remaining=30.0,
            elapsed_time=5.0,
        )
        assert update.type == "phase_update"

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

    def test_wrong_typed_field_raises(self):
        """ProgressUpdate is a pydantic model (a dataclass as of #92,
        promoted to a `BaseModel` in #96 so it can join the discriminated
        `ProgressEvent` union): a field that cannot be coerced to its
        declared type must raise on construction instead of silently
        crossing the Swift bridge as wrong data."""
        with pytest.raises(pydantic.ValidationError):
            ProgressUpdate(
                phase=ProcessingPhase.PREFLIGHT,
                phase_progress="not-a-number",
                overall_progress=0.1,
                phase_name="Loading Document",
                estimated_remaining=30.0,
                elapsed_time=5.0,
            )

    def test_phase_stays_enum_member(self):
        """phase must stay a ProcessingPhase enum member, not be widened
        to a plain string, per the #92 ticket's explicit constraint."""
        update = ProgressUpdate(
            phase=ProcessingPhase.VALIDATION,
            phase_progress=0.2,
            overall_progress=0.3,
            phase_name="Validating Entities",
            estimated_remaining=10.0,
            elapsed_time=2.0,
        )

        assert update.phase is ProcessingPhase.VALIDATION
        assert isinstance(update.phase, ProcessingPhase)

    def test_unexpected_extra_field_rejected(self):
        """`extra="forbid"` matches the mass-event models it now shares a
        union with -- a stray/renamed field is producer-side drift, not
        data to silently drop."""
        with pytest.raises(pydantic.ValidationError):
            ProgressUpdate(
                phase=ProcessingPhase.PREFLIGHT,
                phase_progress=0.1,
                overall_progress=0.1,
                phase_name="Loading Document",
                estimated_remaining=30.0,
                elapsed_time=5.0,
                unexpected=True,
            )


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
    
    def test_rich_path_taken_for_one_parameter_callback(self):
        """A one-parameter callback -- the shape both the CLI and the GUI
        actually register -- receives the ProgressUpdate object directly."""
        received = []

        def rich_cb(update):
            received.append(update)

        tracker = ProgressTracker(rich_cb, "test", 10)
        tracker.update_phase(ProcessingPhase.RULE_DETECTION, 0.5, "Detecting...")

        assert len(received) == 1
        assert isinstance(received[0], ProgressUpdate)

    def test_three_parameter_callback_also_receives_single_update(self):
        """#92 removed the `inspect.signature`-based dispatch that used to
        call a callback declaring exactly three parameters positionally as
        `(chunk, total, message)`. The audit for #92 found no such callback
        registered anywhere in the codebase, so every callback -- even one
        that happens to declare three parameters -- must now receive the
        single rich ProgressUpdate object instead.

        The three parameters below all default to None so the call succeeds
        under either calling convention, which is what lets this test tell
        the two conventions apart instead of merely erroring out under one
        of them: the pre-#92 code path would populate all three (chunk int,
        total int, message str), while the current code path leaves the
        second and third at their defaults and passes the ProgressUpdate as
        the first argument.
        """
        received = []

        def three_param_cb(a=None, b=None, c=None):
            received.append((a, b, c))

        tracker = ProgressTracker(three_param_cb, "test", 10)
        tracker.update_phase(ProcessingPhase.RULE_DETECTION, 0.5, "Detecting...")

        assert len(received) == 1
        first, second, third = received[0]
        assert isinstance(first, ProgressUpdate)
        assert second is None
        assert third is None

    def test_is_simple_callback_attribute_removed(self):
        """The `is_simple_callback` flag was removed along with the branch
        it gated (#92) -- assert it stays gone rather than silently
        reappearing."""
        tracker = ProgressTracker(lambda update: None, "test", 10)
        assert not hasattr(tracker, "is_simple_callback")
    
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


class TestMassEventModels:
    """Tests for the closed set of `emit_mass_event` payload models -- the
    five non-`phase_update` members of the unified `ProgressEvent` union
    (bridge schema migration step 4b, issue #93; folded into the one
    `ProgressEvent` channel in issue #96). One malformed-payload case per
    event type, plus the Swift-parity pin."""

    def test_mass_total_valid(self):
        validate_progress_event({"type": "mass_total", "value": 4200})

    def test_mass_total_rejects_non_numeric_value(self):
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "mass_total", "value": "a lot"})

    def test_chunk_start_valid(self):
        validate_progress_event({
            "type": "chunk_start", "size": 150, "estimated_time": 30.0,
        })

    def test_chunk_start_rejects_missing_estimated_time(self):
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "chunk_start", "size": 150})

    def test_chunk_start_valid_with_chunk_index_and_total_chunks(self):
        """Populated by `LlamaCppRedactionPipeline.process_document` only
        (issue #96 round-2 fix) -- see `ChunkStartEvent`'s docstring in
        progress.py for why that backend, and only that backend, needs
        these two fields to keep its heartbeat alive."""
        event = validate_progress_event({
            "type": "chunk_start", "size": 150, "estimated_time": 30.0,
            "chunk_index": 2, "total_chunks": 5,
        })
        assert event.chunk_index == 2
        assert event.total_chunks == 5

    def test_chunk_start_valid_without_chunk_index_and_total_chunks(self):
        """The Ollama path never sets these -- both must default to `None`,
        not be required."""
        event = validate_progress_event({
            "type": "chunk_start", "size": 150, "estimated_time": 30.0,
        })
        assert event.chunk_index is None
        assert event.total_chunks is None

    def test_chunk_end_valid(self):
        validate_progress_event({"type": "chunk_end", "size": 150})

    def test_chunk_end_rejects_missing_size(self):
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "chunk_end"})

    def test_chunk_end_valid_with_chunk_index_and_total_chunks(self):
        event = validate_progress_event({
            "type": "chunk_end", "size": 150, "chunk_index": 4, "total_chunks": 5,
        })
        assert event.chunk_index == 4
        assert event.total_chunks == 5

    def test_keepalive_valid_without_chunk_info(self):
        validate_progress_event({"type": "keepalive", "message": "AI processing..."})

    def test_keepalive_valid_with_chunk_info(self):
        validate_progress_event({
            "type": "keepalive", "message": "still running", "chunk": 2, "total": 5,
        })

    def test_keepalive_rejects_missing_message(self):
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "keepalive", "chunk": 2, "total": 5})

    def test_token_progress_valid(self):
        validate_progress_event({
            "type": "token_progress", "chunk_index": 0, "chars": 120, "eval_count": 30,
        })

    def test_token_progress_valid_without_eval_count(self):
        """Ollama reports `eval_count` only on the stream's final
        `done: true` line, so every intermediate emission carries
        `eval_count: None` -- the common case, which must validate."""
        event = validate_progress_event({
            "type": "token_progress", "chunk_index": 0, "chars": 120, "eval_count": None,
        })
        assert event.eval_count is None

    def test_token_progress_rejects_missing_chunk_index(self):
        """`chunk_index` is always supplied at the emit site (it is the
        loop's own index), so its absence is real producer-side drift --
        unlike a missing/None `eval_count`, which is the normal shape of an
        intermediate streaming event."""
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "token_progress", "chars": 120, "eval_count": 30})

    def test_token_progress_rejects_non_numeric_eval_count(self):
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({
                "type": "token_progress", "chunk_index": 0, "chars": 120,
                "eval_count": "seven",
            })

    def test_unknown_type_rejected(self):
        """No sixth event type exists -- an unrecognized `type` value must
        raise, not silently pass through as some best-effort shape."""
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "not_a_real_event"})

    def test_unexpected_extra_field_rejected(self):
        """Every model is `extra="forbid"` -- a stray/renamed field is
        exactly the kind of producer-side drift this validation exists to
        catch, so it must raise rather than be dropped or ignored."""
        with pytest.raises(pydantic.ValidationError):
            validate_progress_event({"type": "chunk_end", "size": 150, "unexpected": True})

    def test_phase_update_shaped_payload_also_validates(self):
        """`validate_progress_event` validates against the full six-member
        `ProgressEvent` union, not just the five mass-event shapes (issue
        #96) -- a `phase_update`-discriminated dict routes to `ProgressUpdate`
        the same way a raw dict would for any other member."""
        event = validate_progress_event({
            "type": "phase_update",
            "phase": "preflight",
            "phase_progress": 0.5,
            "overall_progress": 0.1,
            "phase_name": "Loading Document",
            "estimated_remaining": 30.0,
            "elapsed_time": 5.0,
        })
        assert isinstance(event, ProgressUpdate)
        assert event.phase == ProcessingPhase.PREFLIGHT

    def test_emitted_type_strings_match_swift_handled_set(self):
        """Pin the producer's closed set of `type` discriminator values
        against the set `DocumentModels.swift`'s `ingestProgressPayload`
        switch actually accepts -- parsed from the Swift source itself, not
        a hand-maintained Python mirror of it -- so neither a new Python
        model type nor a `case` dropped from the Swift switch can silently
        drift the two sides apart again (issue #93).

        `SWIFT_HANDLED_MASS_EVENT_TYPES` is asserted here too, as a third
        term rather than as a substitute for the parse: it is itself
        derived from `MassEvent` in `progress.py` (issue #96's Notes:
        "whatever replaces `SWIFT_HANDLED_MASS_EVENT_TYPES`, derive both
        sides") the same way `model_types` below is, so this assertion is
        really "two independent derivations of the same production
        constant agree" -- both are held to the Swift source, which stays
        the sole authority on what Swift accepts."""
        # Derived from the union itself, never restated. A hand-written set
        # here would make the pin one-directional: it would still catch a
        # `case` dropped from the Swift switch, but a sixth member added to
        # `MassEvent` with no Swift `case` would leave this set unchanged and
        # the assertion green -- which is the exact direction issue #93's
        # original bug ran (Python emitted `token_progress`, Swift fell
        # through to `default`).
        model_types = {
            member.model_fields["type"].default
            for member in typing.get_args(typing.get_args(MassEvent)[0])
        }
        swift_types = _swift_handled_mass_event_types()
        assert model_types == swift_types
        assert SWIFT_HANDLED_MASS_EVENT_TYPES == swift_types

    def test_swift_handled_types_excludes_phase_update(self):
        """`phase_update` is a `ProgressEvent` member but never crosses the
        JSON mass-event channel `ingestProgressPayload` parses -- it
        crosses the PythonKit bridge as a live attribute read instead
        (issue #96). `SWIFT_HANDLED_MASS_EVENT_TYPES` must stay scoped to
        the five mass-event shapes, not the full six-member union."""
        assert "phase_update" not in SWIFT_HANDLED_MASS_EVENT_TYPES
        all_progress_event_types = {
            member.model_fields["type"].default
            for member in typing.get_args(typing.get_args(ProgressEvent)[0])
        }
        assert all_progress_event_types - SWIFT_HANDLED_MASS_EVENT_TYPES == {"phase_update"}


class TestSerializeMassEvent:
    """`serialize_progress_event` serializes the *validated* model, not the
    raw input dict `emit_mass_event` was handed (issue #95). Pydantic's
    coercion is lax, so a payload like `{"value": "4200"}` validates but,
    serialized as the original dict, would carry the string across the
    bridge where Swift expects a number.

    One case per real emit site pins that the change is a no-op for every
    payload shape those sites actually produce (`model_enhanced.py`'s
    `emit_mass_event` call sites); the coercion case proves the guard
    actually does something."""

    def test_mass_total_byte_identical(self):
        payload = {"type": "mass_total", "value": 4200}
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_chunk_start_byte_identical(self):
        payload = {"type": "chunk_start", "size": 500, "estimated_time": 30.0}
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_chunk_start_with_chunk_index_byte_identical(self):
        """The llama.cpp emit site (issue #96 round-2 fix) always includes
        both fields together -- confirm that shape round-trips too."""
        payload = {
            "type": "chunk_start", "size": 500, "estimated_time": 30.0,
            "chunk_index": 2, "total_chunks": 5,
        }
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_chunk_end_byte_identical(self):
        payload = {"type": "chunk_end", "size": 500}
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_chunk_end_with_chunk_index_byte_identical(self):
        payload = {
            "type": "chunk_end", "size": 500, "chunk_index": 4, "total_chunks": 5,
        }
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_keepalive_without_chunk_info_byte_identical(self):
        """The keepalive emit site only adds `chunk`/`total` keys once a
        chunk is in flight -- confirm the omitted-key shape round-trips
        without picking up explicit `null`s from the optional fields'
        defaults."""
        payload = {"type": "keepalive", "message": "AI processing..."}
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_keepalive_with_chunk_info_byte_identical(self):
        payload = {
            "type": "keepalive", "message": "still running", "chunk": 2, "total": 5,
        }
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_token_progress_with_eval_count_byte_identical(self):
        payload = {
            "type": "token_progress", "chunk_index": 0, "chars": 120, "eval_count": 30,
        }
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_token_progress_without_eval_count_byte_identical(self):
        """The emit site always passes `eval_count` explicitly (`None` on
        every intermediate streamed line), unlike keepalive's omitted
        optional fields -- confirm that explicit `null` is preserved rather
        than dropped by `exclude_unset`."""
        payload = {
            "type": "token_progress", "chunk_index": 0, "chars": 120, "eval_count": None,
        }
        assert serialize_progress_event(validate_progress_event(payload)) == json.dumps(payload)

    def test_coercible_wrong_typed_value_emits_coerced_value(self):
        """The bug this ticket closes: a numeric string in a field pydantic
        types as `int` validates (lax coercion) but, serialized from the
        original dict, would still carry the string. Serializing the
        validated model must emit the coerced int instead."""
        payload = {"type": "mass_total", "value": "4200"}
        raw = json.dumps(payload)
        coerced = serialize_progress_event(validate_progress_event(payload))
        assert coerced != raw
        assert json.loads(coerced)["value"] == 4200
        assert isinstance(json.loads(coerced)["value"], int)
