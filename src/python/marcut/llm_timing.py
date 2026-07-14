"""
LLM Timing Instrumentation Module
"""
import time
import json
import sys
import os
import threading
import requests
from typing import List, Dict, Any, Tuple, Optional, Callable
from .cancellation import check_processing_deadline, remaining_seconds, ProcessingDeadlineExceeded

from .model import (
    get_ollama_base_url,
    build_extraction_prompt,
    parse_llm_response,
    _map_label,
    _find_entity_spans,
    OllamaStreamIncompleteError,
)


def ollama_extract_with_timing(
    model: str,
    text: str,
    temperature: float = 0.0,
    seed: int = 42,
    context: Optional[str] = None,
    think_mode: bool = False,
    format_schema: Optional[Dict] = None,
    *,
    stream: bool = False,
    cancel_event: Optional[threading.Event] = None,
    on_token_progress: Optional[Callable[[int, Optional[int]], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    """Extract entities with detailed timing. Returns (spans, timing_dict).

    ``stream``/``cancel_event``/``on_token_progress`` mirror ``model.py``'s
    ``ollama_extract()`` (docs/design/streaming_progress.md, Option B) for
    parity between the two Ollama call sites; default ``stream=False``
    preserves the exact single-response behavior existing callers rely on.
    """
    base_url = get_ollama_base_url()
    try:
        request_timeout = max(1.0, float(os.getenv("MARCUT_OLLAMA_REQUEST_TIMEOUT", "300")))
    except (TypeError, ValueError):
        request_timeout = 300.0
    try:
        num_predict = max(128, int(os.getenv("MARCUT_OLLAMA_NUM_PREDICT", "2048")))
    except (TypeError, ValueError):
        num_predict = 2048
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
        check_processing_deadline()
        if cancel_event is not None and cancel_event.is_set():
            raise ProcessingDeadlineExceeded("Processing cancelled")
        body = {
            "model": model, "prompt": base_prompt, "stream": stream, "think": think_mode,
            "options": {"temperature": max(temperature, 0.1), "seed": seed, "num_ctx": 12288, "num_predict": num_predict, "top_p": 0.9}
        }
        if format_schema is not None:
             body["format"] = format_schema

        if not stream:
            resp = requests.post(
                f"{base_url}/api/generate",
                json=body,
                timeout=remaining_seconds(request_timeout)
            )
            resp.raise_for_status()
            payload = resp.json()
        else:
            resp = requests.post(
                f"{base_url}/api/generate",
                json=body,
                timeout=remaining_seconds(request_timeout),
                stream=True,
            )
            resp.raise_for_status()
            accumulated_parts: List[str] = []
            chars_so_far = 0
            saw_done = False
            final_event: Dict[str, Any] = {}
            try:
                for line in resp.iter_lines(decode_unicode=True):
                    if cancel_event is not None and cancel_event.is_set():
                        raise ProcessingDeadlineExceeded("Processing cancelled")
                    check_processing_deadline()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    piece = event.get("response") or event.get("thinking") or ""
                    if piece:
                        accumulated_parts.append(piece)
                        chars_so_far += len(piece)
                    if on_token_progress is not None and (piece or event.get("eval_count") is not None):
                        try:
                            on_token_progress(chars_so_far, event.get("eval_count"))
                        except Exception:
                            pass
                    if event.get("done"):
                        saw_done = True
                        final_event = event
                        break
            finally:
                resp.close()
            if not saw_done:
                raise OllamaStreamIncompleteError()
            # The final NDJSON line carries the same timing/token-count
            # fields the non-streaming payload has, plus the accumulated
            # response text (not present on the `done: true` line itself).
            payload = dict(final_event)
            payload["response"] = "".join(accumulated_parts)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama not reachable at {base_url}") from e

    http_elapsed = time.perf_counter() - t1

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
