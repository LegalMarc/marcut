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


def is_gguf_model_path(model_path: str) -> bool:
    """True if `model_path` names a local file on disk that llama.cpp would
    load directly: an absolute path or a `.gguf` file. A namespaced Ollama
    registry id such as `hf.co/bartowski/Qwen2.5-14B-GGUF:Q4_K_M` contains a
    "/" but is neither absolute nor a `.gguf` file, so it does NOT match
    here -- it is still an Ollama model, just one fetched from a registry
    namespace.

    This is the narrower building block `uses_llama_cpp_backend()` is built
    from, exposed separately for the two call sites (`unified_redactor.py`)
    that already know or have already fixed the backend and only need the
    "does this string look like a local GGUF path" half of the question.
    """
    return model_path.endswith(".gguf") or model_path.startswith("/")


def uses_llama_cpp_backend(backend: str, model_path: str) -> bool:
    """Single definition of "this run dispatches to llama.cpp rather than
    Ollama": an explicit `backend="llama_cpp"`, or a `model_path` that names
    a local GGUF file/path (see `is_gguf_model_path`).

    `model_path` should be `llama_gguf or model_id` when the caller has
    both -- `--llama-gguf` overrides the plain model id for dispatch
    purposes even when `--backend` is left at its "ollama" default (#68).

    This mirrors what `pipeline._collect_enhanced_spans` actually dispatches
    on, and what `pipeline._sanitize_model_for_report` classifies "is a
    path" the same way (#85) so a namespaced registry id keeps the
    namespace that distinguishes it from another model. Everything in this
    codebase that needs to answer "will this run use llama.cpp" should call
    this, not re-derive the check.
    """
    return backend == "llama_cpp" or is_gguf_model_path(model_path)
