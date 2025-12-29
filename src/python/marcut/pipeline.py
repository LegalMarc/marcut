import sys
import io

# Unicode to ASCII mapping for common document characters
# These are frequently found in Word documents and cause encoding issues
UNICODE_TO_ASCII = {
    '\xa0': ' ',      # Non-breaking space -> regular space
    '\u2018': "'",    # Left single quotation mark
    '\u2019': "'",    # Right single quotation mark (common apostrophe)
    '\u201a': ',',    # Single low-9 quotation mark
    '\u201c': '"',    # Left double quotation mark
    '\u201d': '"',    # Right double quotation mark
    '\u201e': '"',    # Double low-9 quotation mark
    '\u2013': '-',    # En dash
    '\u2014': '--',   # Em dash
    '\u2026': '...',  # Ellipsis
    '\u00b7': '*',    # Middle dot (bullet)
    '\u2022': '*',    # Bullet
    '\u00a9': '(c)',  # Copyright
    '\u00ae': '(R)',  # Registered trademark
    '\u2122': '(TM)', # Trademark
    '\u00b0': ' deg', # Degree symbol
    '\u00bc': '1/4',  # Fraction 1/4
    '\u00bd': '1/2',  # Fraction 1/2
    '\u00be': '3/4',  # Fraction 3/4
    '\u00d7': 'x',    # Multiplication sign
    '\u00f7': '/',    # Division sign
    '\u2032': "'",    # Prime (feet/minutes)
    '\u2033': '"',    # Double prime (inches/seconds)
    '\u00ab': '<<',   # Left-pointing double angle quotation
    '\u00bb': '>>',   # Right-pointing double angle quotation
}

def normalize_unicode(text: str) -> str:
    """Replace common Unicode characters with ASCII equivalents."""
    for unicode_char, ascii_equiv in UNICODE_TO_ASCII.items():
        text = text.replace(unicode_char, ascii_equiv)
    return text

def safe_print(*args, **kwargs):
    """Print function that handles Unicode characters gracefully."""
    try:
        # First try to normalize any string arguments
        normalized_args = []
        for arg in args:
            if isinstance(arg, str):
                normalized_args.append(normalize_unicode(arg))
            else:
                normalized_args.append(arg)
        print(*normalized_args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: encode with errors='replace'
        try:
            message = ' '.join(str(a) for a in args)
            print(message.encode('ascii', errors='replace').decode('ascii'), **kwargs)
        except Exception:
            print("[Unicode encoding error in message]", **kwargs)

# Reconfigure stdout/stderr for UTF-8 with error handling
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
elif not isinstance(sys.stdout, io.TextIOWrapper):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

import json
import traceback
import warnings
import time
import os
from typing import List, Dict, Any, Tuple
from .docx_io import DocxMap, MetadataCleaningSettings
from .chunker import make_chunks
from .rules import run_rules
from .model_enhanced import LlamaCppRedactionPipeline, run_enhanced_model
from .model import run_model
from .cluster import ClusterTable
from .confidence import combine, low_conf
from .report import write_report
import regex as re  # For consistency pass boundaries

def _rank(lbl: str) -> int:
    """Priority ranking for span overlap resolution. Higher rank = higher priority."""
    order = {
        "EMAIL": 3, "PHONE": 3, "SSN": 3, "CARD": 3, "ACCOUNT": 3, "URL": 3, "IP": 3,
        "NAME": 2, "ORG": 2, "BRAND": 2,
        "MONEY": 1, "NUMBER": 1, "DATE": 1
    }
    return order.get(lbl, 0)

def _merge_overlaps(spans: List[Dict[str,Any]], text: str) -> List[Dict[str,Any]]:
    """Merge overlapping spans, keeping the higher-priority or longer span."""
    if not spans:
        return []

    # Validate span data structures to prevent crashes
    valid_spans = []
    for i, span in enumerate(spans):
        if not isinstance(span, dict):
            print(f"Warning: Span {i} is not a dictionary, skipping")
            continue
        if not all(key in span for key in ["start", "end", "label"]):
            print(f"Warning: Span {i} missing required keys, has: {list(span.keys())}, skipping")
            continue
        if not isinstance(span["start"], int) or not isinstance(span["end"], int):
            print(f"Warning: Span {i} has non-integer start/end positions, skipping")
            continue
        if span["start"] >= span["end"]:
            print(f"Warning: Span {i} has start >= end position ({span['start']} >= {span['end']}), skipping")
            continue
        if not span["label"]:  # Empty label
            print(f"Warning: Span {i} has empty label, skipping")
            continue
        valid_spans.append(span)

    if not valid_spans:
        return []

    # Sort by start position
    spans = sorted(valid_spans, key=lambda s: s["start"])
    out: List[Dict[str,Any]] = []
    
    for sp in spans:
        if not out:
            out.append(sp)
            continue
            
        last = out[-1]
        # Check for overlap (start < end means they intersect)
        if sp["start"] < last["end"]:
            # UNION Logic: Extend the end to cover both
            new_end = max(last["end"], sp["end"])
            last["end"] = new_end
            # UPDATE TEXT for the new extended range
            if text:
                last["text"] = text[last["start"]:last["end"]]
            
            # Label Handling: Upgrade label if current span has higher priority
            if _rank(sp["label"]) > _rank(last["label"]):
                last["label"] = sp["label"]
                # Inherit higher confidence if switching label, or average?
                # Keeping it simple: If we switch label, we essentially "become" the higher priority entity 
                # covering the whole range.
                if "entity_id" in sp:
                    last["entity_id"] = sp["entity_id"]
        else:
            out.append(sp)
    
    return out

def _snap_to_boundaries(text: str, spans: List[Dict[str, Any]], debug: bool = False) -> List[Dict[str, Any]]:
    """Expand spans to encompass full tokens (snapping to whitespace/punctuation)."""
    # This prevents mid-word redactions like 20[DATE]25 by expanding the span to 2025.
    out = []
    for sp in spans:
        s, e = sp["start"], sp["end"]
        original_text = sp.get("text", text[s:e])
        
        # DEBUG: Trace expansion for suspicious spans
        trace = False
        if "20" in original_text or "Mont" in original_text:
            trace = True
            if debug: print(f"DEBUG: Snapping '{original_text}' [{s}:{e}]")

        # Expand left: while previous char is alphanumeric, move start back
        while s > 0 and text[s-1].isalnum():
            # if trace and debug: print(f"  Expand Left: text[{s-1}]='{repr(text[s-1])}' is alnum")
            s -= 1
            
        # Expand right: while current char is alphanumeric, move end forward
        while e < len(text) and text[e].isalnum():
            # if trace and debug: print(f"  Expand Right: text[{e}]='{repr(text[e])}' is alnum")
            e += 1
        
        if trace and debug:
             if e < len(text): print(f"  Stopped Right at text[{e}]='{repr(text[e])}'")
             else: print("  Stopped Right at EOF")

        if s != sp["start"] or e != sp["end"]:
            sp["start"] = s
            sp["end"] = e
            sp["text"] = text[s:e]
            if trace and debug: print(f"  Expanded to: '{sp['text']}' [{s}:{e}]")
        out.append(sp)
    return out

def _apply_consistency_pass(text: str, spans: List[Dict[str, Any]], debug: bool = False) -> List[Dict[str, Any]]:
    """
    Consistency Pass: Rescan document for exact, case-sensitive matches of found entities.
    Mitigates inconsistency (e.g., finding 'RDS Delivery' in one place but missing it in another).
    """
    if not spans:
        return spans

    # 1. Collect Candidates
    # Filter for safe entities to auto-propagate (Avoid ambiguous types like DATE/NUMBER)
    SAFE_LABELS = {"ORG", "PERSON", "EMAIL", "SSN", "PHONE", "ACCOUNT", "CARD", "BRAND"}
    STOP_WORDS = {
        "the", "and", "for", "with", "from", "that", "this", "inc", "llc", "corp", 
        "ltd", "company", "mr", "mrs", "ms", "dr", "esq", "dept"
    } 
    
    candidates = {} # normalized_text -> label
    
    for sp in spans:
        lbl = sp["label"]
        txt = sp["text"].strip()
        
        if lbl not in SAFE_LABELS: continue
        
        # Safety Filters
        if len(txt) < 4: continue # Too short (risk of "The", "Act")
        if txt.lower() in STOP_WORDS: continue # Stop words
        if not any(c.isalnum() for c in txt): continue # Just punctuation?
        
        # Store (Case Sensitive Key)
        # If multiple labels for same text, prioritize existing rank? 
        # For simplicity, first entry wins (or last).
        candidates[txt] = lbl

    if not candidates:
        if debug: print("Consistency Pass: No suitable candidates found.")
        return spans

    if debug:
        print(f"Consistency Pass: Scanning for {len(candidates)} entities...")

    new_spans = []
    
    # 2. Rescan
    # We use regex with \b word boundaries to avoid partial matches (e.g. "Will" inside "William")
    for cand_text, label in candidates.items():
        pattern_str = r"\b" + re.escape(cand_text) + r"\b"
        try:
            # Case Sensitive search
            for match in re.finditer(pattern_str, text):
                s, e = match.span()
                new_spans.append({
                    "start": s,
                    "end": e,
                    "label": label,
                    "text": cand_text,
                    "confidence": 0.95, 
                    "source": "consistency_pass"
                })
        except Exception as e:
            if debug: print(f"Consistency Pass Error scanning '{cand_text}': {e}")
            continue

    if debug:
        print(f"Consistency Pass: Generated {len(new_spans)} new spans.")

    # 3. Merge with original
    return spans + new_spans

def _finalize_and_write(dm: DocxMap, text: str, spans: List[Dict[str,Any]], output_path: str, report_path: str, input_path: str, model_info: str, debug: bool = False) -> int:
    """Apply redactions with track changes and generate audit report."""
    ct = ClusterTable()
    url_counter = {}
    
    # Assign entity IDs for clustering and consistent numbering
    # Use generic counters for exact-match types
    entity_counters = {} # label -> {text: id}
    
    for sp in spans:
        label = sp["label"]
        text = sp["text"].strip() # Normalize text for matching
        
        if label in ("NAME", "ORG", "BRAND"):
            eid, score, is_new = ct.link(label, text)
            sp["entity_id"] = eid
            sp["confidence"] = combine(sp.get("confidence", 0.7), agreements=0 if is_new else 1)
        else:
            # Generalize numbering for ALL other types (PHONE, DATE, EMAIL, ACCOUNT, URL, etc.)
            if label not in entity_counters:
                entity_counters[label] = {}
            
            if text not in entity_counters[label]:
                entity_counters[label][text] = len(entity_counters[label]) + 1
            
            seq_id = entity_counters[label][text]
            sp["entity_id"] = f"{label}_{seq_id}"
    
    # Create replacements
    replacements = []
    for sp in spans:
        if not sp.get("needs_redaction", True):
            continue
            
        # Use entity_id if available, otherwise use label
        if sp.get("entity_id"):
            tag = f"[{sp['entity_id']}]"
        else:
            tag = f"[{sp['label']}]"
        
        s, e = sp["start"], sp["end"]
        
        # Handle possessive forms (e.g., "John's" -> "[NAME_1]'s")
        if e + 2 <= len(text) and text[e:e+2] == "'s":
            e += 2
            tag += "'s"
        
        # Check for existing brackets to avoid [[TAG]]
        # Safety check: indices must be within valid range
        has_left_bracket = (s > 0 and s <= len(text) and text[s-1] == '[')
        has_right_bracket = (e < len(text) and text[e] == ']')
        
        if has_left_bracket and has_right_bracket:
            tag = tag[1:-1]  # Remove our brackets
        
        if debug:
             print(f"DEBUG: Replacement span: {s}-{e} = '{tag}' (Label: {sp.get('label')})")

        replacements.append({
            "start": s, 
            "end": e, 
            "replacement": tag, 
            "low_confidence": low_conf(sp.get("confidence", 0.7))
        })
    
    # Apply track changes and save
    dm.apply_replacements(replacements, track_changes=True)
    
    # Parse metadata cleaning settings from environment (set by Swift UI)
    metadata_args_str = os.environ.get("MARCUT_METADATA_ARGS", "")
    metadata_args = metadata_args_str.split() if metadata_args_str else []
    metadata_settings = MetadataCleaningSettings.from_cli_args(metadata_args)
    scrub_report_path = os.environ.get("MARCUT_SCRUB_REPORT_PATH", "").strip() or None
    if not scrub_report_path:
        scrub_report_path = _default_scrub_report_path(report_path, output_path)
    scrub_before_values = _read_metadata_values(dm) if scrub_report_path else None
    
    # Apply security hardening only if relevant settings are enabled
    # (RSIDs, hyperlinks, OLE objects are hardening targets)
    hardening_enabled = any([
        metadata_settings.clean_rsids,
        metadata_settings.clean_hyperlink_urls,
        metadata_settings.clean_ole_objects,
        metadata_settings.clean_activex,
    ])
    
    if hardening_enabled:
        try:
            from .rules import _selected_rule_labels, _rule_enabled
            selected_rules = _selected_rule_labels()
            scrub_images = _rule_enabled("IMAGES", selected_rules)
        except ImportError:
            scrub_images = False
        dm.harden_document(scrub_all_images=scrub_images, settings=metadata_settings)
    
    # Scrub metadata using user-configured settings
    dm.scrub_metadata(metadata_settings)
    
    dm.save(output_path)

    if scrub_report_path and scrub_before_values is not None:
        try:
            try:
                dm_after = DocxMap.load(output_path)
                scrub_after_values = _read_metadata_values(dm_after)
            except Exception:
                scrub_after_values = _read_metadata_values(dm)

            report = _build_scrub_report(scrub_before_values, scrub_after_values, metadata_settings)
            report_dir = os.path.dirname(scrub_report_path)
            if report_dir:
                os.makedirs(report_dir, exist_ok=True)
            with open(scrub_report_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
        except Exception as e:
            print(f"[MARCUT_PIPELINE] Failed to write scrub report: {e}")
    
    # Generate audit report
    audit = [{
        "start": sp["start"], 
        "end": sp["end"], 
        "label": sp["label"],
        "entity_id": sp.get("entity_id"),
        "confidence": sp.get("confidence", 0.0),
        "source": sp.get("source", ""),
        "text": sp.get("text", "")[:120],
        "validated": sp.get("validated"),
        "validation_result": sp.get("validation_result")
    } for sp in spans]
    
    write_report(report_path, input_path, model_info, audit)
    return 0

def _collect_rule_spans(text: str, debug: bool) -> List[Dict[str, Any]]:
    """Run deterministic rule engine and normalize span metadata."""
    rule_spans = run_rules(text)
    for sp in rule_spans:
        sp["source"] = sp.get("source", "rule")
        sp["confidence"] = max(sp.get("confidence", 0.0), 0.90)
        if "text" not in sp:
            sp["text"] = text[sp["start"]:sp["end"]]
    if debug:
        print(f"Rule-based detection found {len(rule_spans)} spans.")
    return rule_spans


def _collect_classic_model_spans(
    text: str,
    backend: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    llama_gguf: str,
    threads: int,
    debug: bool,
) -> List[Dict[str, Any]]:
    """Run the legacy lightweight LLM detector."""
    model_spans: List[Dict[str, Any]] = []
    chunks = make_chunks(text, max_len=chunk_tokens * 4, overlap=overlap * 4)

    for ch in chunks:
        base = ch["start"]
        preds = run_model(
            backend,
            model_id,
            ch["text"],
            temperature,
            seed,
            llama_gguf,
            threads,
        )
        for sp in preds:
            start = base + sp["start"]
            end = base + sp["end"]
            sp["start"] = start
            sp["end"] = end
            sp["source"] = "model"
            sp["confidence"] = sp.get("confidence", 0.70)
            sp["text"] = text[start:end]
            model_spans.append(sp)

    if debug:
        print(f"Legacy LLM detection found {len(model_spans)} spans.")
    return model_spans


def _collect_enhanced_spans(
    text: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    debug: bool,
    progress_callback=None,
) -> List[Dict[str, Any]]:
    """Run the enhanced extraction pipeline (Ollama or llama.cpp)."""
    from .progress import ProgressTracker, ProcessingPhase

    # Initialize rich progress tracking if callback provided
    tracker = None
    if progress_callback:
        word_count = len(text.split())
        tracker = ProgressTracker(progress_callback, text, word_count)
        tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 0.0, "Starting AI entity extraction...")

    chunks = make_chunks(text, max_len=chunk_tokens * 4, overlap=overlap * 4)

    if model_id.endswith(".gguf") or ("/" in model_id and model_id.startswith("/")):
        if debug:
            print(f"Using LlamaCpp backend with model: {model_id}")
        pipeline = LlamaCppRedactionPipeline(
            model_path=model_id,
            temperature=temperature,
            seed=seed,
        )
        model_spans = pipeline.process_document(
            text, chunks, progress_callback=progress_callback
        )
    else:
        if debug:
            print(f"Using Ollama backend with model: {model_id}")
        model_spans = run_enhanced_model(
            backend="ollama",
            model_id=model_id,
            text=text,
            chunks=chunks,
            temperature=temperature,
            seed=seed,
            progress_callback=progress_callback,
        )

    if debug:
        print(f"Enhanced LLM detection found {len(model_spans)} spans.")

    # Complete progress tracking
    if tracker:
        tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 1.0, f"AI extraction complete - found {len(model_spans)} entities")
        tracker.complete()

    return model_spans


class RedactionError(Exception):
    """Enhanced error class for specific redaction failure reasons."""
    def __init__(self, message: str, error_code: str, technical_details: str = "", original_error: Exception = None):
        super().__init__(message)
        self.error_code = error_code
        self.technical_details = technical_details
        self.original_error = original_error


def _log_redaction_error(error: RedactionError, debug: bool = False) -> None:
    """Emit structured logging for redaction failures."""
    print(f"[MARCUT_PIPELINE][{error.error_code}] {error}")
    if error.technical_details:
        print(f"[MARCUT_PIPELINE] Details: {error.technical_details}")
    if error.original_error and debug:
        traceback.print_exception(error.original_error)


def _write_failure_report(report_path: str, input_path: str, error: RedactionError) -> None:
    """Persist a minimal error report so the GUI/CLI can surface context."""
    payload = {
        "status": "error",
        "input": input_path,
        "error_code": error.error_code,
        "message": str(error),
        "technical_details": error.technical_details,
    }
    try:
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except Exception as report_exc:
        print(f"[MARCUT_PIPELINE] Failed to write error report: {report_exc}")
        traceback.print_exc()

def run_redaction(
    input_path: str,
    output_path: str,
    report_path: str,
    mode: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    debug: bool,
    *,
    backend: str = "ollama",
    llama_gguf: str = "",
    threads: int = 4,
    redaction_author: str = "Marcut",
    do_qa: bool = True,  # retained for backwards compatibility
    progress_callback=None,
    timing: bool = False,
    llm_detail: bool = False,
) -> Tuple[int, Dict[str, float]]:
    """
    Unified pipeline entry point. Dispatches between rule-only, enhanced, and
    legacy hybrid modes based on the supplied mode value.
    """
    try:
        del do_qa  # parameter kept for API compatibility
        
        # Initialize timing collection
        phase_timings: Dict[str, float] = {}
        def timed(phase_name: str):
            """Context manager for timing a phase."""
            class Timer:
                def __enter__(self):
                    self.start = time.perf_counter()
                    return self
                def __exit__(self, *args):
                    phase_timings[phase_name] = time.perf_counter() - self.start
            return Timer()
        
        # Storage for LLM sub-timing
        llm_timing_detail = {}

        normalized_mode = (mode or "").strip().lower()
        if not normalized_mode:
            normalized_mode = "enhanced"

        # Enhanced error handling for document loading
        try:
            with timed("DOCX_LOAD"):
                dm = DocxMap.load_accepting_revisions(input_path, debug=debug)
                dm.author_name = redaction_author
                text = dm.text
            if debug:
                print(f"Successfully loaded document: {len(text)} characters")
        except Exception as e:
            raise RedactionError(
                message="Failed to load document file",
                error_code="DOC_LOAD_FAILED",
                technical_details=f"Input path: {input_path}, Error: {str(e)}",
                original_error=e
            )

        # Enhanced error handling for rules processing
        try:
            with timed("RULES"):
                rule_spans = _collect_rule_spans(text, debug)
            if debug:
                print(f"Rule-based processing found {len(rule_spans)} spans")
        except Exception as e:
            raise RedactionError(
                message="Rules engine failed during processing",
                error_code="RULES_ENGINE_FAILED",
                technical_details=f"Error in rules processing: {str(e)}",
                original_error=e
            )

        if normalized_mode in {"rules", "strict", "rules-only"}:
            with timed("POST_PROCESS"):
                rule_spans = _snap_to_boundaries(text, rule_spans, debug=debug)
                # Apply Consistency Pass (Rules Only)
                rule_spans = _apply_consistency_pass(text, rule_spans, debug=debug)
                merged = _merge_overlaps(rule_spans, text)
            if debug:
                print(f"Total spans after merging: {len(merged)}")

            # Enhanced error handling for rules-only output
            try:
                with timed("DOCX_SAVE"):
                    result = _finalize_and_write(
                        dm,
                        text,
                        merged,
                        output_path,
                        report_path,
                        input_path,
                        model_id or "rules",
                        debug=debug
                    )
                return (result, phase_timings)
            except Exception as e:
                raise RedactionError(
                    message="Failed to save redacted document in rules-only mode",
                    error_code="OUTPUT_SAVE_FAILED",
                    technical_details=f"Output path: {output_path}, Report path: {report_path}, Error: {str(e)}",
                    original_error=e
                )

        if normalized_mode in {"enhanced", "enhanced_ai", "llm"}:
            # Enhanced error handling for AI processing
            try:
                with timed("LLM"):
                    if llm_detail and not (model_id.endswith(".gguf") or model_id.startswith("/")):
                        # Use timing-instrumented extraction for detailed profiling
                        from .llm_timing import ollama_extract_with_timing
                        model_spans, llm_timing_detail = ollama_extract_with_timing(
                            model_id, text, temperature, seed
                        )
                        # Store in phase_timings for return
                        phase_timings['llm_timing'] = llm_timing_detail
                    else:
                        model_spans = _collect_enhanced_spans(
                            text,
                            model_id,
                            chunk_tokens,
                            overlap,
                            temperature,
                            seed,
                            debug,
                            progress_callback=progress_callback,
                        )
                if debug:
                    print(f"Enhanced AI processing found {len(model_spans)} spans")
            except Exception as e:
                # Check for specific error patterns
                error_str = str(e).lower()
                if "ollama" in error_str and ("not reachable" in error_str or "connection" in error_str):
                    raise RedactionError(
                        message="AI service is not available or cannot be reached",
                        error_code="AI_SERVICE_UNAVAILABLE",
                        technical_details=f"Ollama service error: {str(e)}. Ensure Ollama is running and accessible.",
                        original_error=e
                    )
                elif "timeout" in error_str:
                    raise RedactionError(
                        message="AI processing timed out",
                        error_code="AI_PROCESSING_TIMEOUT",
                        technical_details=f"Model: {model_id}, Error: {str(e)}. Try with a smaller document or different model.",
                        original_error=e
                    )
                elif "model" in error_str and ("not found" in error_str or "pull" in error_str):
                    raise RedactionError(
                        message="AI model is not available",
                        error_code="AI_MODEL_UNAVAILABLE",
                        technical_details=f"Model: {model_id}, Error: {str(e)}. Ensure the model is downloaded and available.",
                        original_error=e
                    )
                else:
                    raise RedactionError(
                        message="AI processing failed with an unexpected error",
                        error_code="AI_PROCESSING_FAILED",
                        technical_details=f"Model: {model_id}, Error: {str(e)}",
                        original_error=e
                    )

            with timed("POST_PROCESS"):
                all_spans = rule_spans + model_spans
                all_spans = _snap_to_boundaries(text, all_spans, debug=debug)
                # Apply Consistency Pass (Enhanced)
                all_spans = _apply_consistency_pass(text, all_spans, debug=debug)
                merged = _merge_overlaps(all_spans, text)
            if debug:
                print(f"Total spans after merging: {len(merged)}")

            # Enhanced error handling for final output
            try:
                with timed("DOCX_SAVE"):
                    result = _finalize_and_write(
                        dm,
                        text,
                        merged,
                        output_path,
                        report_path,
                        input_path,
                        model_id,
                        debug=debug
                    )
                return (result, phase_timings)
            except Exception as e:
                raise RedactionError(
                    message="Failed to save redacted document",
                    error_code="OUTPUT_SAVE_FAILED",
                    technical_details=f"Output path: {output_path}, Report path: {report_path}, Error: {str(e)}",
                    original_error=e
                )

        # Fallback to classic hybrid pipeline for legacy modes (e.g., "balanced")
        try:
            with timed("LLM"):
                model_spans = _collect_classic_model_spans(
                    text,
                    backend,
                    model_id,
                    chunk_tokens,
                    overlap,
                    temperature,
                    seed,
                    llama_gguf or "",
                    threads,
                    debug,
                )
            with timed("POST_PROCESS"):
                all_spans = rule_spans + model_spans
                all_spans = _snap_to_boundaries(text, all_spans, debug=debug)
                # Apply Consistency Pass (Legacy)
                all_spans = _apply_consistency_pass(text, all_spans, debug=debug)
                merged = _merge_overlaps(all_spans, text)
            if debug:
                print(f"Total spans after merging: {len(merged)}")

            with timed("DOCX_SAVE"):
                result = _finalize_and_write(
                    dm,
                    text,
                    merged,
                    output_path,
                    report_path,
                    input_path,
                    model_id,
                    debug=debug
                )
            return (result, phase_timings)
        except Exception as e:
            raise RedactionError(
                message="Legacy hybrid processing failed",
                error_code="LEGACY_PROCESSING_FAILED",
                technical_details=f"Backend: {backend}, Model: {model_id}, Error: {str(e)}",
                original_error=e
            )
    except RedactionError as err:
        if debug:
            _log_redaction_error(err, debug=True)
        else:
            print(f"[MARCUT_PIPELINE] {err}")
        _write_failure_report(report_path, input_path, err)
        return (2, phase_timings if 'phase_timings' in dir() else {})
    except Exception as err:
        wrapped = RedactionError(
            message="Unexpected error during redaction",
            error_code="UNEXPECTED_FAILURE",
            technical_details=str(err),
            original_error=err,
        )
        _log_redaction_error(wrapped, debug=debug)
        _write_failure_report(report_path, input_path, wrapped)
        return (3, phase_timings if 'phase_timings' in dir() else {})


def run_redaction_enhanced(
    input_path: str,
    output_path: str,
    report_path: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    debug: bool,
    progress_callback=None,
) -> int:
    """
    Backwards-compatible wrapper that delegates to run_redaction in enhanced mode.
    """
    warnings.warn(
        "run_redaction_enhanced is deprecated; use run_redaction(..., mode='enhanced')",
        DeprecationWarning,
        stacklevel=2,
    )
    return run_redaction(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        mode="enhanced",
        model_id=model_id,
        chunk_tokens=chunk_tokens,
        overlap=overlap,
        temperature=temperature,
        seed=seed,
        debug=debug,
        progress_callback=progress_callback,
    )

# Alias for backwards compatibility
redact_docx = run_redaction


def _default_scrub_report_path(report_path: str, output_path: str):
    if report_path:
        base_dir = os.path.dirname(report_path)
        base_name = os.path.basename(report_path)
        if base_name.endswith("_report.json"):
            scrub_name = base_name[:-len("_report.json")] + "_scrub_report.json"
        else:
            stem, _ = os.path.splitext(base_name)
            scrub_name = f"{stem}_scrub_report.json"
        return os.path.join(base_dir, scrub_name) if base_dir else scrub_name

    if output_path:
        base_dir = os.path.dirname(output_path)
        stem, _ = os.path.splitext(os.path.basename(output_path))
        scrub_name = f"{stem}_scrub_report.json"
        return os.path.join(base_dir, scrub_name) if base_dir else scrub_name

    return None


def _read_metadata_values(dm) -> dict:
    """Read current metadata values from document for before/after comparison."""
    values = {}
    
    try:
        cp = dm.doc.core_properties
        
        # Core properties
        values['author'] = str(cp.author or '')
        values['last_modified_by'] = str(cp.last_modified_by or '')
        values['title'] = str(cp.title or '')
        values['subject'] = str(cp.subject or '')
        values['keywords'] = str(cp.keywords or '')
        values['comments'] = str(cp.comments or '')
        values['category'] = str(getattr(cp, 'category', '') or '')
        values['content_status'] = str(getattr(cp, 'content_status', '') or '')
        values['revision'] = str(cp.revision or '')
        values['created'] = str(cp.created or '')
        values['modified'] = str(cp.modified or '')
        values['last_printed'] = str(getattr(cp, 'last_printed', '') or '')
        values['identifier'] = str(getattr(cp, 'identifier', '') or '')
        values['language'] = str(getattr(cp, 'language', '') or '')
        values['version'] = str(getattr(cp, 'version', '') or '')
    except Exception:
        pass
    
    # App properties (from app.xml) - read via package relationships
    try:
        from lxml import etree
        for rel in dm.doc.part.package.rels.values():
            if "extended-properties" in rel.reltype or "app" in rel.reltype:
                app_part = rel.target_part
                if hasattr(app_part, '_blob') and app_part._blob:
                    app_xml = etree.fromstring(app_part._blob)
                    ns = {'ep': 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties'}
                    
                    for tag in ['Company', 'Manager', 'Application', 'AppVersion', 'Template',
                               'HyperlinkBase', 'TotalTime', 'Words', 'Characters', 'Pages',
                               'DocSecurity', 'ScaleCrop', 'SharedDoc', 'LinksUpToDate',
                               'HyperlinksChanged']:
                        for elem in app_xml.findall(f'.//ep:{tag}', namespaces=ns):
                            key = "hyperlink_base" if tag == "HyperlinkBase" else tag.lower()
                            values[key] = str(elem.text or '')
                    break
    except Exception:
        pass

    # Document Settings (settings.xml)
    try:
        from docx.oxml.ns import qn
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            
            # Spell/Grammar State (w:proofState)
            proof_state = settings_xml.find(qn('w:proofState'))
            if proof_state is not None:
                spelling = proof_state.get(qn('w:spelling')) or 'clean'
                grammar = proof_state.get(qn('w:grammar')) or 'clean'
                values['proof_state'] = f"spelling={spelling}, grammar={grammar}"
            else:
                values['proof_state'] = "default (clean)"
                
            # Document Variables (w:docVars)
            doc_vars = settings_xml.find(qn('w:docVars'))
            if doc_vars is not None:
                count = len(doc_vars.findall(qn('w:docVar')))
                values['doc_vars'] = f"{count} variables found"
            else:
                values['doc_vars'] = "0 variables"

            mail_merge = settings_xml.find(qn('w:mailMerge'))
            if mail_merge is not None:
                parts = []
                if mail_merge.find(qn('w:dataSource')) is not None:
                    parts.append("dataSource")
                if mail_merge.find(qn('w:headerSource')) is not None:
                    parts.append("headerSource")
                values['mail_merge'] = ", ".join(parts) if parts else "present"
            else:
                values['mail_merge'] = "none"
    except Exception:
        pass

    # Additional structural metadata for reporting
    try:
        from docx.oxml.ns import qn
        from lxml import etree
        import posixpath
        import re

        def _iter_part_elements():
            if dm.doc.element is not None:
                yield dm.doc.element
            for rel in dm.doc.part.rels.values():
                if any(key in rel.reltype for key in ("header", "footer", "footnotes", "endnotes")):
                    if hasattr(rel.target_part, "element"):
                        yield rel.target_part.element

        def _count_tag(tag):
            total = 0
            for root in _iter_part_elements():
                total += sum(1 for _ in root.iter(tag))
            return total

        def _count_attr(attr_name):
            total = 0
            for root in _iter_part_elements():
                for el in root.iter():
                    for key in el.attrib.keys():
                        if key == attr_name:
                            total += 1
            return total

        def _is_unc_path(target: str) -> bool:
            return target.startswith("\\\\") or (target.startswith("//") and not target.startswith("http"))

        def _is_user_path(target: str) -> bool:
            return ("/Users/" in target or "/home/" in target or "C:\\\\Users\\" in target
                    or "C:/Users/" in target or "%USERPROFILE%" in target)

        def _is_file_path(target: str) -> bool:
            if target.startswith("file:"):
                return True
            if re.match(r"^[A-Za-z]:[\\\\/]", target):
                return True
            return target.startswith("/") or target.startswith("./") or target.startswith("../")

        def _is_internal_url(target: str) -> bool:
            if not target.startswith(("http://", "https://")):
                return False
            try:
                host = target.split("//", 1)[1].split("/", 1)[0]
            except Exception:
                return False
            if host.startswith(("127.", "10.", "192.168.", "169.254.")):
                return True
            if host.endswith(".local") or host.endswith(".lan"):
                return True
            return "." not in host

        # Custom properties and custom XML parts
        custom_property_names = []
        custom_xml_parts = []
        custom_xml_rels = [rel for rel in dm.doc.part.rels.values() if "customXml" in rel.reltype]

        def _part_blob(part):
            if hasattr(part, "blob"):
                return part.blob
            return getattr(part, "_blob", None)

        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            blob = _part_blob(part)
            if name.endswith("/docProps/custom.xml"):
                if blob:
                    try:
                        root = etree.fromstring(blob)
                        for prop in root.findall(".//{*}property"):
                            prop_name = prop.get("name")
                            if prop_name:
                                custom_property_names.append(prop_name)
                    except Exception:
                        pass
            if name.startswith("/customXml/") and name.endswith(".xml"):
                if blob:
                    try:
                        root = etree.fromstring(blob)
                        root_tag = root.tag.split("}", 1)[-1]
                        root_ns = root.tag.split("}", 1)[0][1:] if root.tag.startswith("{") else ""
                        custom_xml_parts.append({
                            "part": name,
                            "root_tag": root_tag,
                            "namespace": root_ns,
                        })
                    except Exception:
                        custom_xml_parts.append({"part": name})

        values["custom_properties"] = {
            "custom_property_names": custom_property_names,
            "custom_xml_parts": custom_xml_parts,
            "custom_xml_rel_count": len(custom_xml_rels),
        }

        # Review comments and track changes
        values["review_comments"] = f"{_count_tag(qn('w:commentRangeStart'))} comment ranges"
        track_tags = [qn('w:ins'), qn('w:del'), qn('w:moveFrom'), qn('w:moveTo'),
                      qn('w:rPrChange'), qn('w:pPrChange')]
        track_count = 0
        for tag in track_tags:
            track_count += _count_tag(tag)
        values["track_changes"] = f"{track_count} revisions"

        # RSIDs and GUID
        rsid_count = 0
        for root in _iter_part_elements():
            for el in root.iter():
                for key in el.attrib.keys():
                    if qn('w:rsidR') in key or qn('w:rsidRPr') in key or qn('w:rsidP') in key:
                        rsid_count += 1
        values["rsids"] = f"{rsid_count} rsid attrs"
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            guid_count = len(settings_xml.findall(qn('w14:docId')))
        values["document_guid"] = f"{guid_count} docIds"

        # Mail merge bindings and data bindings
        values["data_bindings"] = f"{_count_tag(qn('w:dataBinding'))} bindings"

        # Hidden text runs
        hidden_run_count = 0
        for root in _iter_part_elements():
            for run in root.iter(qn('w:r')):
                rpr = run.find(qn('w:rPr'))
                if rpr is None:
                    continue
                if (rpr.find(qn('w:vanish')) is not None
                        or rpr.find(qn('w:specVanish')) is not None
                        or rpr.find(qn('w:webHidden')) is not None):
                    hidden_run_count += 1
        values["hidden_text"] = f"{hidden_run_count} runs"

        # Invisible objects (VML/DrawingML with hidden visibility)
        invisible_count = 0
        for root in _iter_part_elements():
            for el in root.iter():
                style = (el.get("style") or "").lower()
                visibility = (el.get("visibility") or "").lower()
                display = (el.get("display") or "").lower()
                if ("visibility:hidden" in style
                        or "visibility: hidden" in style
                        or "display:none" in style
                        or "mso-hide:all" in style
                        or visibility == "hidden"
                        or display == "none"):
                    invisible_count += 1
        values["invisible_objects"] = f"{invisible_count} objects"

        # Headers and footers
        header_count = sum(1 for rel in dm.doc.part.rels.values() if "header" in rel.reltype)
        footer_count = sum(1 for rel in dm.doc.part.rels.values() if "footer" in rel.reltype)
        values["headers_footers"] = f"{header_count} headers, {footer_count} footers"

        # Watermarks (heuristic)
        watermark_count = 0
        def _is_watermark_candidate(el) -> bool:
            attrs = " ".join(str(v) for v in el.attrib.values()).lower()
            if "powerpluswatermarkobject" in attrs or "watermark" in attrs:
                return True
            if "mso-position-horizontal:center" in attrs and "mso-position-vertical:center" in attrs and "z-index" in attrs:
                return True
            return False

        for rel in dm.doc.part.rels.values():
            if "header" not in rel.reltype:
                continue
            if not hasattr(rel.target_part, "element"):
                continue
            root = rel.target_part.element
            for el in root.iter():
                if _is_watermark_candidate(el):
                    watermark_count += 1
        values["watermarks"] = f"{watermark_count} shapes"

        # Ink annotations
        ink_parts = 0
        for part in dm.doc.part.package.parts:
            if str(part.partname).startswith("/word/ink"):
                ink_parts += 1
        ink_elements = 0
        for root in _iter_part_elements():
            for el in root.iter():
                tag = el.tag
                if not isinstance(tag, str):
                    continue
                local = tag.split("}", 1)[-1].lower()
                if local.startswith("ink"):
                    ink_elements += 1
        values["ink_annotations"] = f"{ink_parts} ink parts, {ink_elements} ink elements"

        # Document versions (legacy)
        version_parts = 0
        for part in dm.doc.part.package.parts:
            if str(part.partname).startswith("/word/versions"):
                version_parts += 1
        values["document_versions"] = f"{version_parts} parts"

        # Embedded content counts
        values["thumbnail"] = "present" if any(str(part.partname).startswith("/docProps/thumbnail")
                                              for part in dm.doc.part.package.parts) else "none"
        values["hyperlinks"] = f"{_count_tag(qn('w:hyperlink'))} hyperlinks"
        alt_text_count = 0
        for root in _iter_part_elements():
            for el in root.iter():
                if el.tag == '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr':
                    if el.attrib.get("descr") or el.attrib.get("title"):
                        alt_text_count += 1
        values["alt_text"] = f"{alt_text_count} alt text entries"
        values["ole_objects"] = f"{_count_tag(qn('w:object')) + _count_tag(qn('w:control'))} objects"

        rel_types = [rel.reltype for rel in dm.doc.part.rels.values()]
        values["vba_macros"] = "present" if any("vbaProject" in t for t in rel_types) else "none"
        values["digital_signatures"] = "present" if any("signature" in t for t in rel_types) else "none"
        values["printer_settings"] = "present" if any("printerSettings" in t for t in rel_types) else "none"
        values["glossary"] = "present" if any("glossary" in t for t in rel_types) else "none"

        # Embedded fonts detection
        values["embedded_fonts"] = "present" if any(str(part.partname).startswith("/word/fonts/")
                                                   for part in dm.doc.part.package.parts) else "none"

        # Fast save data (heuristic)
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            fast_save = settings_xml.find(qn('w:savePreviewPicture'))
            fast_save_xslt = settings_xml.find(qn('w:saveThroughXslt'))
            values["fast_save"] = "present" if (fast_save is not None or fast_save_xslt is not None) else "none"

        # Advanced hardening counts (relationships)
        external_targets = []
        for rel in dm.doc.part.rels.values():
            target = getattr(rel, "target_ref", "")
            is_external = getattr(rel, "is_external", False)
            if is_external:
                external_targets.append((rel.reltype or "", str(target)))

        values["external_links"] = str(sum(1 for _, target in external_targets if _is_file_path(target)))
        values["unc_paths"] = str(sum(1 for _, target in external_targets if _is_unc_path(target)))
        values["user_paths"] = str(sum(1 for _, target in external_targets if _is_user_path(target)))
        values["internal_urls"] = str(sum(1 for _, target in external_targets if _is_internal_url(target)))
        values["ole_sources"] = str(sum(1 for r_type, target in external_targets if "oleObject" in r_type and _is_file_path(target)))

        # Image EXIF detection (heuristic)
        exif_hits = 0
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if not name.startswith("/word/media/"):
                continue
            data = part.blob
            if name.lower().endswith((".jpg", ".jpeg")) and b"Exif" in data[:4096]:
                exif_hits += 1
            if name.lower().endswith(".png") and b"eXIf" in data:
                exif_hits += 1
        values["image_exif"] = f"{exif_hits} images"

        # Style names
        style_custom = 0
        for part in dm.doc.part.package.parts:
            if str(part.partname) != "/word/styles.xml":
                continue
            root = etree.fromstring(part.blob)
            for style in root.findall(".//w:style", namespaces=root.nsmap):
                if style.get(qn("w:customStyle")) == "1":
                    style_custom += 1
        values["style_names"] = f"{style_custom} custom styles"

        # Chart labels
        chart_labels = 0
        for part in dm.doc.part.package.parts:
            if not str(part.partname).startswith("/word/charts/"):
                continue
            root = etree.fromstring(part.blob)
            for el in root.iter():
                if el.tag.endswith("}v") or el.tag.endswith("}t"):
                    if el.text:
                        chart_labels += 1
        values["chart_labels"] = f"{chart_labels} labels"

        # Form defaults and language settings
        values["form_defaults"] = f"{_count_tag(qn('w:default')) + _count_tag(qn('w:result'))} defaults"
        values["language_settings"] = f"{_count_tag(qn('w:lang'))} lang tags"

        # ActiveX
        active_x_parts = 0
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if name.startswith("/word/activeX/") or name.startswith("/word/controls/"):
                active_x_parts += 1
        values["activex"] = f"{active_x_parts} parts"

    except Exception:
        pass

    return values


def _build_scrub_report(before: dict, after: dict, settings) -> dict:
    """Build comprehensive report with before/after values grouped like UI."""
    
    groups = {
        "App Properties": [
            {"field": "Company", "setting": "clean_company", "before_key": "company"},
            {"field": "Manager", "setting": "clean_manager", "before_key": "manager"},
            {"field": "Total Editing Time", "setting": "clean_total_editing_time", "before_key": "totaltime"},
            {"field": "Application", "setting": "clean_application", "before_key": "application"},
            {"field": "App Version", "setting": "clean_app_version", "before_key": "appversion"},
            {"field": "Template", "setting": "clean_template", "before_key": "template"},
            {"field": "Hyperlink Base", "setting": "clean_hyperlink_base", "before_key": "hyperlink_base"},
            {"field": "Document Statistics", "setting": "clean_statistics", "before_key": "words"},
            {"field": "Document Security", "setting": "clean_doc_security", "before_key": "docsecurity"},
            {"field": "Thumbnail Settings", "setting": "clean_scale_crop", "before_key": "scalecrop"},
            {"field": "Shared Document Flag", "setting": "clean_shared_doc", "before_key": "shareddoc"},
            {"field": "Links Up-to-Date Flag", "setting": "clean_links_up_to_date", "before_key": "linksuptodate"},
            {"field": "Hyperlinks Changed Flag", "setting": "clean_hyperlinks_changed", "before_key": "hyperlinkschanged"},
        ],
        "Core Properties": [
            {"field": "Author", "setting": "clean_author", "before_key": "author"},
            {"field": "Last Modified By", "setting": "clean_last_modified_by", "before_key": "last_modified_by"},
            {"field": "Title", "setting": "clean_title", "before_key": "title"},
            {"field": "Subject", "setting": "clean_subject", "before_key": "subject"},
            {"field": "Keywords", "setting": "clean_keywords", "before_key": "keywords"},
            {"field": "Comments", "setting": "clean_comments", "before_key": "comments"},
            {"field": "Category", "setting": "clean_category", "before_key": "category"},
            {"field": "Content Status", "setting": "clean_content_status", "before_key": "content_status"},
            {"field": "Created Date", "setting": "clean_created_date", "before_key": "created"},
            {"field": "Modified Date", "setting": "clean_modified_date", "before_key": "modified"},
            {"field": "Last Printed", "setting": "clean_last_printed", "before_key": "last_printed"},
            {"field": "Revision Number", "setting": "clean_revision_number", "before_key": "revision"},
            {"field": "Identifier", "setting": "clean_identifier", "before_key": "identifier"},
            {"field": "Language", "setting": "clean_language", "before_key": "language"},
            {"field": "Version", "setting": "clean_version", "before_key": "version"},
        ],
        "Custom Properties": [
            {"field": "Custom Properties & Custom XML", "setting": "clean_custom_properties", "before_key": "custom_properties"},
        ],
        "Document Structure": [
            {"field": "Review Comments", "setting": "clean_review_comments", "before_key": "review_comments"},
            {"field": "Track Changes", "setting": "clean_track_changes", "before_key": "track_changes"},
            {"field": "RSIDs", "setting": "clean_rsids", "before_key": "rsids"},
            {"field": "Document GUID", "setting": "clean_document_guid", "before_key": "document_guid"},
            {"field": "Spell/Grammar State", "setting": "clean_spell_grammar_state", "before_key": "proof_state"},
            {"field": "Document Variables", "setting": "clean_document_variables", "before_key": "doc_vars"},
            {"field": "Mail Merge Data", "setting": "clean_mail_merge", "before_key": "mail_merge"},
            {"field": "Data Bindings", "setting": "clean_data_bindings", "before_key": "data_bindings"},
            {"field": "Document Versions", "setting": "clean_document_versions", "before_key": "document_versions"},
            {"field": "Ink Annotations", "setting": "clean_ink_annotations", "before_key": "ink_annotations"},
            {"field": "Hidden Text", "setting": "clean_hidden_text", "before_key": "hidden_text"},
            {"field": "Invisible Objects", "setting": "clean_invisible_objects", "before_key": "invisible_objects"},
            {"field": "Headers & Footers", "setting": "clean_headers_footers", "before_key": "headers_footers"},
            {"field": "Watermarks", "setting": "clean_watermarks", "before_key": "watermarks"},
        ],
        "Embedded Content": [
            {"field": "Thumbnail Image", "setting": "clean_thumbnail", "before_key": "thumbnail"},
            {"field": "Hyperlink URLs", "setting": "clean_hyperlink_urls", "before_key": "hyperlinks"},
            {"field": "Alt Text on Images", "setting": "clean_alt_text", "before_key": "alt_text"},
            {"field": "OLE Objects", "setting": "clean_ole_objects", "before_key": "ole_objects"},
            {"field": "VBA Macros", "setting": "clean_vba_macros", "before_key": "vba_macros"},
            {"field": "Digital Signatures", "setting": "clean_digital_signatures", "before_key": "digital_signatures"},
            {"field": "Printer Settings", "setting": "clean_printer_settings", "before_key": "printer_settings"},
            {"field": "Embedded Fonts", "setting": "clean_embedded_fonts", "before_key": "embedded_fonts"},
            {"field": "Glossary/AutoText", "setting": "clean_glossary", "before_key": "glossary"},
            {"field": "Fast Save Data", "setting": "clean_fast_save_data", "before_key": "fast_save"},
        ],
        "Advanced Hardening": [
            {"field": "External Link Paths", "setting": "clean_external_links", "before_key": "external_links"},
            {"field": "Network (UNC) Paths", "setting": "clean_unc_paths", "before_key": "unc_paths"},
            {"field": "User Profile Paths", "setting": "clean_user_paths", "before_key": "user_paths"},
            {"field": "Internal URLs", "setting": "clean_internal_urls", "before_key": "internal_urls"},
            {"field": "OLE Source Paths", "setting": "clean_ole_sources", "before_key": "ole_sources"},
            {"field": "Image EXIF Data", "setting": "clean_image_exif", "before_key": "image_exif"},
            {"field": "Custom Style Names", "setting": "clean_style_names", "before_key": "style_names"},
            {"field": "Chart Labels", "setting": "clean_chart_labels", "before_key": "chart_labels"},
            {"field": "Form Field Defaults", "setting": "clean_form_defaults", "before_key": "form_defaults"},
            {"field": "Language Settings", "setting": "clean_language_settings", "before_key": "language_settings"},
            {"field": "ActiveX Controls", "setting": "clean_activex", "before_key": "activex"},
        ],
    }
    
    report = {
        "summary": {"total_cleaned": 0, "total_preserved": 0},
        "groups": {},
    }
    
    for group_name, fields in groups.items():
        group_data = []
        for field_info in fields:
            field_name = field_info["field"]
            setting_attr = field_info["setting"]
            before_key = field_info.get("before_key")
            
            was_enabled = getattr(settings, setting_attr, False)
            before_val = before.get(before_key, "") if before_key else "(complex data)"
            after_val = after.get(before_key, "") if before_key else ("" if was_enabled else "(preserved)")
            
            # Determine actual status based on whether values changed
            if was_enabled:
                if before_val != after_val:
                    # Setting was enabled AND values actually changed
                    report["summary"]["total_cleaned"] += 1
                    status = "cleaned"
                else:
                    # Setting was enabled but values didn't change (nothing to clean)
                    report["summary"]["total_preserved"] += 1
                    status = "unchanged"
            else:
                # Setting was disabled - preserve original
                report["summary"]["total_preserved"] += 1
                status = "preserved"
            
            group_data.append({
                "field": field_name,
                "before": before_val,
                "after": after_val if was_enabled else before_val,
                "status": status
            })
        
        report["groups"][group_name] = group_data
    
    return report


def scrub_metadata_only(
    input_path: str,
    output_path: str,
    debug: bool = False,
) -> Tuple[bool, str, dict]:
    """
    Scrub metadata only - no rules or LLM redaction.
    """
    try:
        # 1. Parse Args
        metadata_args_str = os.environ.get("MARCUT_METADATA_ARGS", "")
        metadata_args = metadata_args_str.split() if metadata_args_str else []
        metadata_settings = MetadataCleaningSettings.from_cli_args(metadata_args)
        
        # Check for explicit 'None' preset flag for ultra-robust handling
        is_none_preset = "--preset-none" in metadata_args or "--preset-none" in metadata_args_str
        
        if debug:
            print(f"[MARCUT_PIPELINE] Input: {input_path}")
            print(f"[MARCUT_PIPELINE] Args: {metadata_args_str[:100]}...")
            print(f"[MARCUT_PIPELINE] is_none_preset: {is_none_preset}")

        # 2. Get Before Values (Read-Only)
        # Load just for reading - if this fails, document is likely already corrupt
        try:
            if metadata_settings.clean_track_changes:
                dm_read = DocxMap.load_accepting_revisions(input_path, debug=debug)
            else:
                dm_read = DocxMap.load(input_path)
            before_values = _read_metadata_values(dm_read)
        except Exception as e:
            return (False, f"Failed to read input document (it may be corrupt): {e}", {})

        # 3. Decision Path
        if is_none_preset:
            # COPY PATH: Safe handling for None preset
            import shutil
            print(f"[MARCUT_PIPELINE] None preset: Copying file without processed save.")
            shutil.copy2(input_path, output_path)
            
            # Use 'before' values as 'after' values (everything preserved)
            # We don't need to re-read because we haven't touched it.
            report = _build_scrub_report(before_values, before_values, metadata_settings)
            return (True, "", report)

        # 4. Scrubbing Path
        # We can reuse dm_read as our working model since DocxMap loads into memory
        dm = dm_read
        
        # Apply hardening if settings imply it
        # (Logic from before: hardening enabled if rsids/hyperlinks/ole enabled)
        hardening_enabled = any([
            metadata_settings.clean_rsids,
            metadata_settings.clean_hyperlink_urls,
            metadata_settings.clean_ole_objects,
            metadata_settings.clean_activex,
        ])
        if hardening_enabled:
            # Check for Scrub Images rule (optional)
            try:
                from .rules import _selected_rule_labels, _rule_enabled
                selected_rules = _selected_rule_labels()
                scrub_images = _rule_enabled("IMAGES", selected_rules)
            except ImportError:
                scrub_images = False
            dm.harden_document(scrub_all_images=scrub_images, settings=metadata_settings)

        # Scrub metadata
        dm.scrub_metadata(metadata_settings)
        
        # Save processed document
        dm.save(output_path)

        # Read After Values from saved document (captures zip-level cleanups)
        try:
            dm_after = DocxMap.load(output_path)
            after_values = _read_metadata_values(dm_after)
        except Exception:
            after_values = _read_metadata_values(dm)
        
        # Build Report
        report = _build_scrub_report(before_values, after_values, metadata_settings)
        return (True, "", report)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return (False, f"Metadata scrub failed: {str(e)}", {})
