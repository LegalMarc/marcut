"""Load the shared `models.json` catalog of supported Ollama models.

`models.json` is the single source of truth for which models Marcut
recommends/supports and their default parameters (temperature, validation
skip-confidence, etc). It is shipped as a bundled resource for both the
Python package and the Swift app (see `assets/models.json`,
`src/python/marcut/models.json`, and
`src/swift/MarcutApp/Sources/MarcutApp/Resources/models.json` -- all three
copies must stay byte-identical, the same way `excluded-words.txt` is kept
in sync across those locations).

This module mirrors the Swift-side loader in `ModelCatalog.swift`: if you
change the schema here, update it there too (and vice versa).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

_MODELS_JSON_PATH = os.path.join(os.path.dirname(__file__), "models.json")


@dataclass(frozen=True)
class ModelConfig:
    """A single supported model entry from `models.json`."""

    id: str
    display_name: str
    description: str
    setup_description: str
    processing_time: str
    size_label: str
    badge: str
    accent_color: str
    temperature: float
    skip_confidence: float


class ModelCatalogError(RuntimeError):
    """Raised when `models.json` is missing or malformed."""


_CACHE: Optional["_Catalog"] = None


@dataclass(frozen=True)
class _Catalog:
    default_model: str
    models: List[ModelConfig]


def _load_catalog(path: str = _MODELS_JSON_PATH) -> _Catalog:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError as e:
        raise ModelCatalogError(f"models.json not found at {path}") from e
    except json.JSONDecodeError as e:
        raise ModelCatalogError(f"models.json at {path} is not valid JSON: {e}") from e

    try:
        default_model = raw["defaultModel"]
        entries = raw["models"]
        models = [
            ModelConfig(
                id=m["id"],
                display_name=m["displayName"],
                description=m["description"],
                setup_description=m["setupDescription"],
                processing_time=m["processingTime"],
                size_label=m["sizeLabel"],
                badge=m["badge"],
                accent_color=m["accentColor"],
                temperature=float(m["temperature"]),
                skip_confidence=float(m["skipConfidence"]),
            )
            for m in entries
        ]
    except (KeyError, TypeError) as e:
        raise ModelCatalogError(f"models.json at {path} is missing expected fields: {e}") from e

    if not models:
        raise ModelCatalogError(f"models.json at {path} has no models")
    if default_model not in {m.id for m in models}:
        raise ModelCatalogError(
            f"models.json defaultModel '{default_model}' is not one of the listed models"
        )

    return _Catalog(default_model=default_model, models=models)


def _catalog() -> _Catalog:
    global _CACHE
    if _CACHE is None:
        _CACHE = _load_catalog()
    return _CACHE


def list_models() -> List[ModelConfig]:
    """Return all supported models, in catalog order."""
    return list(_catalog().models)


def get_model(model_id: str) -> Optional[ModelConfig]:
    """Return the `ModelConfig` for `model_id`, or None if unsupported."""
    for m in _catalog().models:
        if m.id == model_id:
            return m
    return None


def default_model_id() -> str:
    """Return the recommended/default Ollama model tag."""
    return _catalog().default_model


def default_model() -> ModelConfig:
    """Return the `ModelConfig` for the recommended/default model."""
    model = get_model(default_model_id())
    assert model is not None  # guaranteed by _load_catalog validation
    return model


def default_temperature() -> float:
    return default_model().temperature


def default_skip_confidence() -> float:
    return default_model().skip_confidence
