"""Shared Ollama model-name/tag parsing rules.

This module is the single authoritative implementation of the model-name
parsing and matching rules used across Marcut. It mirrors the canonical
behavior implemented on the Swift side in
`PythonBridge.swift`'s `ModelPromotion.manifestInfo` / `normalizedModelIdentifier`:

- An identifier is `[library/]model[:tag]`.
- A missing library defaults to `"library"` (Ollama's default registry
  namespace); a missing tag defaults to `"latest"`.
- Two identifiers match only if their resolved library, model, and tag are
  all equal after normalization (no substring/prefix matching).

Callers that previously did ad hoc substring containment checks (e.g.
`self.model_name in n or n.startswith(base)`) should use `models_match`
instead: that pattern has a false-positive risk (a requested `"llama3"`
would incorrectly match an installed `"llama3.2:latest"` or
`"llama3-custom-eval:7b"`), which this module does not reproduce.
"""

from __future__ import annotations

from typing import NamedTuple

DEFAULT_LIBRARY = "library"
DEFAULT_TAG = "latest"


class ParsedModelName(NamedTuple):
    """A normalized `library/model:tag` identifier."""

    library: str
    model: str
    tag: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.library}/{self.model}:{self.tag}"


def _strip_registry_host(cleaned: str) -> str:
    """Collapse a `host/library/model` or bare `library/model` prefix.

    Mirrors Swift's `PythonBridgeService.normalizedModelIdentifier`: when an
    identifier has 3+ `/`-separated segments (e.g.
    `registry.ollama.ai/library/llama3.2:3b`), only the last two segments
    are kept (dropping the registry host), and if those two segments are
    `library/<model>`, the leading `library/` is collapsed away so it falls
    through to the default-library handling in `parse_model_identifier`.
    """
    parts = [p for p in cleaned.split("/") if p != ""]
    if len(parts) >= 3:
        parts = parts[-2:]
    if len(parts) == 2 and parts[0] == DEFAULT_LIBRARY:
        return parts[1]
    return "/".join(parts)


def parse_model_identifier(name: str) -> ParsedModelName:
    """Parse a raw Ollama model identifier into library/model/tag parts.

    Mirrors Swift's `normalizedModelIdentifier` + `ModelPromotion.manifestInfo`
    parsing:
    - Input `"llama3.2"` -> library="library", model="llama3.2", tag="latest"
    - Input `"llama3.2:3b"` -> library="library", model="llama3.2", tag="3b"
    - Input `"user/llama3.2:3b"` -> library="user", model="llama3.2", tag="3b"
    - Input `"registry.ollama.ai/library/llama3.2:3b"` -> library="library",
      model="llama3.2", tag="3b" (registry host dropped, then the explicit
      `library/` segment collapses to the default)
    """
    cleaned = (name or "").strip()
    cleaned = _strip_registry_host(cleaned)

    library = DEFAULT_LIBRARY
    model = cleaned
    tag = DEFAULT_TAG

    if "/" in model:
        prefix, rest = model.split("/", 1)
        library = prefix
        model = rest

    if ":" in model:
        model, explicit_tag = model.split(":", 1)
        if explicit_tag:
            tag = explicit_tag

    return ParsedModelName(library=library, model=model, tag=tag)


def models_match(requested: str, candidate: str) -> bool:
    """Return True if `requested` and `candidate` resolve to the same model.

    Matching is exact on the normalized (library, model, tag) triple -- a
    bare `"llama3.2"` resolves to `library/llama3.2:latest` and matches an
    installed `"llama3.2:latest"`, but does NOT match `"llama3.2:3b"` or
    any other differently-tagged install, and never does substring
    matching against unrelated model names.
    """
    return parse_model_identifier(requested) == parse_model_identifier(candidate)


def find_matching_model(requested: str, candidates) -> bool:
    """Return True if any name in `candidates` matches `requested`."""
    return any(models_match(requested, candidate) for candidate in candidates)
