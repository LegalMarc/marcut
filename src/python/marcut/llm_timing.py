"""
LLM Timing Instrumentation Module
"""
import time
import json
import sys
import requests
from typing import List, Dict, Any, Tuple, Optional

from .model import (
    get_ollama_base_url,
    build_extraction_prompt,
    parse_llm_response,
    _map_label,
    _find_entity_spans,
)


def ollama_extract_with_timing(
    model: str,
    text: str,
    temperature: float = 0.0,
    seed: int = 42,
    context: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Extract entities with detailed timing. Returns (spans, timing_dict)."""
    base_url = get_ollama_base_url()
    timing = {
        "prompt_build": 0.0, "http_request": 0.0, "ollama_model_load": 0.0,
        "ollama_prompt_eval": 0.0, "ollama_generation": 0.0, "network_overhead": 0.0,
        "response_parse": 0.0, "entity_locate": 0.0, "prompt_tokens": 0, "output_tokens": 0,
    }

    # Build prompt
    t0 = time.perf_counter()
    base_prompt = build_extraction_prompt(text, context)
    timing["prompt_build"] = time.perf_counter() - t0

    # Make HTTP request
    t1 = time.perf_counter()
    try:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model, "prompt": base_prompt, "stream": False,
                "options": {"temperature": max(temperature, 0.1), "seed": seed, "num_ctx": 4096, "num_predict": 512, "top_p": 0.9}
            },
            timeout=60
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama not reachable at {base_url}") from e

    http_elapsed = time.perf_counter() - t1
    payload = resp.json()

    # Extract Ollama internal timing (nanoseconds -> seconds)
    ollama_total = payload.get("total_duration", 0) / 1e9
    timing["http_request"] = http_elapsed
    timing["ollama_model_load"] = payload.get("load_duration", 0) / 1e9
    timing["ollama_prompt_eval"] = payload.get("prompt_eval_duration", 0) / 1e9
    timing["ollama_generation"] = payload.get("eval_duration", 0) / 1e9
    timing["network_overhead"] = max(0, http_elapsed - ollama_total)
    timing["prompt_tokens"] = payload.get("prompt_eval_count", 0)
    timing["output_tokens"] = payload.get("eval_count", 0)

    # Parse response
    t2 = time.perf_counter()
    response_text = payload.get("response", "")
    try:
        parsed = parse_llm_response(response_text)
    except json.JSONDecodeError:
        parsed = {"entities": []}
    timing["response_parse"] = time.perf_counter() - t2

    # Find entity positions
    t3 = time.perf_counter()
    entities = parsed.get("entities", [])
    all_spans = []
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        entity_text = ent.get("text", "").strip()
        entity_type = ent.get("type", "").strip().upper()
        if not entity_text or not entity_type:
            continue
        label = _map_label(entity_type)
        if not label:
            continue
        spans = _find_entity_spans(text, entity_text, label)
        # Add text field to each span (required by post-processing)
        for sp in spans:
            sp['text'] = text[sp['start']:sp['end']]
        all_spans.extend(spans)
    timing["entity_locate"] = time.perf_counter() - t3

    # Deduplicate
    seen = set()
    unique_spans = []
    for sp in sorted(all_spans, key=lambda x: (x["start"], x["end"])):
        key = (sp["start"], sp["end"], sp["label"])
        if key not in seen:
            seen.add(key)
            unique_spans.append(sp)

    return unique_spans, timing
