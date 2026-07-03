"""Cooperative cancellation and deadline helpers for long-running processing."""

import os
import time
from typing import Optional


class ProcessingDeadlineExceeded(TimeoutError):
    """Raised when a configured processing deadline has elapsed."""


def processing_deadline() -> Optional[float]:
    raw = os.environ.get("MARCUT_PROCESSING_DEADLINE_MONOTONIC", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def remaining_seconds(default: float, *, minimum: float = 0.25) -> float:
    deadline = processing_deadline()
    if deadline is None:
        return max(minimum, float(default))
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProcessingDeadlineExceeded("Processing deadline exceeded")
    return max(minimum, min(float(default), remaining))


def check_processing_deadline() -> None:
    deadline = processing_deadline()
    if deadline is not None and time.monotonic() >= deadline:
        raise ProcessingDeadlineExceeded("Processing deadline exceeded")
