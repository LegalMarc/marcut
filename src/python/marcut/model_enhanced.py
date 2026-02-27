"""
Enhanced LLM model for intelligent entity extraction with validation.
Implements a two-pass system: extraction with classification, then selective validation.
"""

import sys
import io

# Reconfigure stdout/stderr for UTF-8 with error handling
# This prevents encoding errors when printing strings with non-ASCII characters
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

import inspect
import json
import math
import os
import re
import time
from typing import List, Dict, Any, Optional, Tuple, Set
import requests
from dataclasses import dataclass, asdict
import hashlib
from .model import (
    parse_llm_response,
    _valid_candidate,
    get_ollama_base_url,
    get_exclusion_data,
    _normalize_for_exclusion,
    _strip_leading_determiner,
    _matches_exclusion_literal,
    _is_generic_term,
    build_extraction_prompt,
    _map_label,
)

_DOC_TITLE_RE = re.compile(
    r"(?i)\b(?:agreement|amendment|consent|resolution|statement|minutes|bylaws|charter|policy|plan)\b"
)
_ORG_SUFFIX_HINT_RE = re.compile(
    r"(?i)\b(?:inc\.?|corp\.?|co\.?|ltd\.?|llc|l\.l\.c\.|llp|l\.l\.p\.|lp|l\.p\.|plc|gmbh|ag|s\.a\.|s\.r\.l\.)\b"
)


def _looks_like_document_title(text: str) -> bool:
    if not text:
        return False
    if not _DOC_TITLE_RE.search(text):
        return False
    if _ORG_SUFFIX_HINT_RE.search(text):
        return False
    words = [w for w in text.split() if w.strip(",.;:()[]{}")]
    return len(words) >= 2


@dataclass
class Entity:
    """Entity with enhanced metadata for intelligent processing."""
    text: str
    label: str
    start: int
    end: int
    confidence: float
    needs_redaction: bool
    rationale: Optional[str] = None
    source: str = "model"
    validated: bool = False
    validation_result: Optional[str] = None


class ValidationCache:
    """Cache validation decisions to avoid redundant LLM calls."""
    
    def __init__(self):
        self.cache = {}
    
    def get_key(self, text: str, label: str) -> str:
        """Generate cache key for entity."""
        return f"{text.lower().strip()}:{label}"
    
    def get(self, text: str, label: str) -> Optional[Dict]:
        """Get cached validation if exists."""
        key = self.get_key(text, label)
        return self.cache.get(key)
    
    def set(self, text: str, label: str, result: Dict):
        """Cache validation result."""
        key = self.get_key(text, label)
        self.cache[key] = result


class DocumentContext:
    """Maintains document-level context for better extraction."""
    
    def __init__(self):
        self.primary_entities = {}
        self.entity_aliases = {}
        self.document_type = None
        self.redaction_level = "standard"
        self.all_entities = []
    
    def analyze_document(self, text: str):
        """Analyze document to identify main parties and document type."""
        # Identify document type from header/title
        doc_lower = text[:1000].lower()
        if "shareholder" in doc_lower and "consent" in doc_lower:
            self.document_type = "shareholder_consent"
        elif "purchase agreement" in doc_lower:
            self.document_type = "purchase_agreement"
        elif "employment agreement" in doc_lower:
            self.document_type = "employment_agreement"
        else:
            self.document_type = "legal_document"
        
        # Look for primary entity patterns (company names that appear in title/header)
        header_text = text[:500]
        company_pattern = r'\b[A-Z][A-Z\s&,\.]+(?:INC\.|LLC|LTD|CORP|CORPORATION|COMPANY|L\.P\.|LP|AB|GMBH|AG)\b'
        potential_companies = re.findall(company_pattern, header_text, re.IGNORECASE)

        primary_parties = []
        seen = set()
        for candidate in potential_companies:
            cleaned = " ".join(candidate.strip().split()).strip(" ,.;:")
            if not cleaned:
                continue
            upper_cleaned = cleaned.upper()
            if " BY AND BETWEEN " in upper_cleaned:
                cleaned = cleaned.split(" BY AND BETWEEN ", 1)[1].strip(" ,.;:")
            elif " BETWEEN " in upper_cleaned:
                cleaned = cleaned.split(" BETWEEN ", 1)[1].strip(" ,.;:")
            if not cleaned:
                continue
            if _looks_like_document_title(cleaned):
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            primary_parties.append(cleaned)
            if len(primary_parties) >= 2:
                break

        if len(primary_parties) < 2:
            between_match = re.search(
                r"(?is)\bby\s+and\s+between\s+(.{0,200}?)\s+and\s+(.{0,200}?)(?:\n|\r|\(|$)",
                text[:1500]
            )
            if between_match:
                for candidate in (between_match.group(1), between_match.group(2)):
                    cleaned = " ".join(candidate.strip().split()).strip(" ,.;:")
                    if not cleaned:
                        continue
                    key = cleaned.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    primary_parties.append(cleaned)
                    if len(primary_parties) >= 2:
                        break
        
        if primary_parties:
            # The first major company name is likely the primary entity
            self.primary_entities['company'] = primary_parties[0]
            self.primary_entities['parties'] = primary_parties
            # Common aliases
            self.entity_aliases[primary_parties[0].lower()] = [
                "the company",
                "the corporation",
                "company",
                "borrower",
                "issuer"
            ]
    
    def get_confidence_threshold(self, label: str) -> float:
        """Get dynamic confidence threshold based on entity distribution."""
        same_label_entities = [e for e in self.all_entities if e.label == label]
        if len(same_label_entities) < 5:
            # Not enough data, use defaults
            return 0.7

        confidences = [e.confidence for e in same_label_entities]
        # Use bottom quartile as threshold
        sorted_confidences = sorted(confidences)
        position = (len(sorted_confidences) - 1) * 0.25
        lower_index = math.floor(position)
        upper_index = math.ceil(position)
        if lower_index == upper_index:
            return sorted_confidences[int(position)]

        lower_weight = upper_index - position
        upper_weight = position - lower_index
        return (sorted_confidences[lower_index] * lower_weight) + (
            sorted_confidences[upper_index] * upper_weight
        )


def build_prompt_context(doc_context: DocumentContext) -> Optional[str]:
    parts = []
    if doc_context.document_type:
        parts.append(f"Document type (best guess): {doc_context.document_type.replace('_', ' ')}.")

    parties = doc_context.primary_entities.get("parties") or []
    if parties:
        if len(parties) >= 2:
            parts.append(f"Primary parties (best guess): {parties[0]}; {parties[1]}.")
        else:
            parts.append(f"Primary party (best guess): {parties[0]}.")
    elif doc_context.primary_entities.get("company"):
        parts.append(f"Primary party (best guess): {doc_context.primary_entities['company']}.")

    if not parts:
        return None

    parts.append("Use this context only to interpret ambiguous references; do not infer entities not in the text.")
    return "Context:\n- " + "\n- ".join(parts)


def get_validation_prompt(entity: Entity, context: str, doc_context: DocumentContext) -> str:
    """Build validation prompt for uncertain entities."""
    
    # Adaptive context window based on entity type
    context_sizes = {
        'ORG': 150,
        'NAME': 80,
        'LOC': 200,
        'DATE': 60,
        'MONEY': 60
    }
    
    context_size = context_sizes.get(entity.label, 100)
    
    # Extract surrounding context
    start_ctx = max(0, entity.start - context_size)
    end_ctx = min(len(context), entity.end + context_size)
    surrounding = context[start_ctx:end_ctx]
    
    # Highlight the entity in context
    entity_start_in_ctx = entity.start - start_ctx
    entity_end_in_ctx = entity_start_in_ctx + len(entity.text)
    
    highlighted = (
        surrounding[:entity_start_in_ctx] + 
        f"**{surrounding[entity_start_in_ctx:entity_end_in_ctx]}**" +
        surrounding[entity_end_in_ctx:]
    )
    
    doc_info = ""
    if doc_context.primary_entities.get('company'):
        doc_info = f"\nNote: The primary company in this document is '{doc_context.primary_entities['company']}', often referred to as 'the Company'."
    
    prompt = f"""You are validating whether an extracted entity needs redaction in a legal document.
{doc_info}

Entity found: "{entity.text}"
Entity type: {entity.label}
Initial assessment: {entity.rationale or 'No rationale provided'}
Context: ...{highlighted}...

Carefully analyze whether this is:
1. A SPECIFIC entity with confidential information that must be redacted (real company name, person's name, etc.)
2. A GENERIC reference or legal boilerplate that should NOT be redacted
3. PARTIAL - contains both specific and generic parts

Consider:
- Is this the actual name of a real person or organization?
- Or is it a generic reference like "the Company" or a role like "Board of Directors"?
- Would revealing this information identify specific parties or remain generic?

Respond with this JSON structure:
{{
  "classification": "FULL_REDACT|SKIP|PARTIAL_REDACT|CONTEXT_DEPENDENT",
  "needs_redaction": true/false,
  "confidence": 0.0-1.0,
  "explanation": "brief explanation of your decision"
}}

Classification guide:
- FULL_REDACT: Entire text is confidential and should be redacted
- SKIP: Generic reference/boilerplate, no redaction needed
- PARTIAL_REDACT: Contains both generic and specific parts
- CONTEXT_DEPENDENT: Depends on document recipient/use case

Return ONLY valid JSON."""
    
    return prompt


def needs_validation(entity: Entity, doc_context: DocumentContext) -> bool:
    """Determine if an entity needs validation based on multiple factors.
    Option A: If the text matches any excluded-words pattern, we FORCE validation
    but we do not auto-drop it. This keeps the decision with the LLM.
    """
    
    # 1. Safety Net: Bypass validation for high-precision, rule-like patterns.
    # If it looks like an SSN/Email/Phone, do NOT ask the LLM to second-guess it.
    # We redact these by default.
    if entity.label in ("EMAIL", "PHONE", "SSN", "MONEY", "NUMBER"):
        return False

    # Check rationale for uncertainty markers
    if entity.rationale:
        uncertain_phrases = [
            'might be', 'possibly', 'unclear', 'could be', 
            'not sure', 'maybe', 'perhaps', 'seems like'
        ]
        if any(p in entity.rationale.lower() for p in uncertain_phrases):
            return True
    
    # Use excluded-words list as a validation trigger (not a filter)
    # Use optimized O(1) lookup with consistent normalization (same as Rules path)
    txt = entity.text.strip()
    text_clean = _strip_leading_determiner(txt)
    normalized_txt = _normalize_for_exclusion(txt)
    literals, patterns = get_exclusion_data()
    
    # Fast path: O(1) set lookup for literals with optional singularization
    if _matches_exclusion_literal(normalized_txt, literals):
        return True
    
    # Slow path: check regex patterns (rare)
    for pat in patterns:
        try:
            if pat.match(text_clean):
                return True
        except Exception:
            # In case any user-provided pattern is malformed, ignore
            continue
    
    # Get dynamic threshold for this entity type
    threshold = doc_context.get_confidence_threshold(entity.label)
    if entity.confidence < threshold:
        return True
    
    # Check for known problematic patterns
    text_lower = entity.text.lower()
    
    # ORG-specific checks
    if entity.label == 'ORG':
        problematic_org_patterns = [
            'the company', 'board of', 'officers of', 'stockholders of',
            'bylaws of', 'directors of', 'shares of', 'agreement',
            'resolved', 'whereas', 'transaction', 'exhibit'
        ]
        if any(pattern in text_lower for pattern in problematic_org_patterns):
            return True
    
    # NAME-specific checks
    if entity.label == 'NAME':
        problematic_name_patterns = [
            'whereas', 'resolved', 'agreement', 'amendment',
            'authoriz', 'approval', 'consent', 'action by'
        ]
        if any(pattern in text_lower for pattern in problematic_name_patterns):
            return True
    
    # Check for unusually long spans that might be phrases
    if len(entity.text) > 60:
        return True
    
    # If confidence is very high and no red flags, skip validation
    if entity.confidence > 0.9 and entity.needs_redaction:
        return False
    
    # When in doubt about whether to redact, validate
    if entity.confidence > 0.7 and not entity.needs_redaction:
        return False
    
    return True


def get_batch_validation_prompt(entities: List[Entity], full_text: str, doc_context: DocumentContext) -> str:
    """Build validation prompt for a batch of entities."""
    
    doc_info = ""
    if doc_context.primary_entities.get('company'):
        doc_info = f"\nNote: The primary company in this document is '{doc_context.primary_entities['company']}', often referred to as 'the Company'."

    items_str = ""
    for idx, entity in enumerate(entities):
        # Context extraction (similar to single validation)
        context_sizes = {'ORG': 150, 'NAME': 80, 'LOC': 200, 'DATE': 60, 'MONEY': 60}
        ctx_size = context_sizes.get(entity.label, 100)
        start_ctx = max(0, entity.start - ctx_size)
        end_ctx = min(len(full_text), entity.end + ctx_size)
        surrounding = full_text[start_ctx:end_ctx]

        # Escape newlines in context for prompt clarity
        surrounding = surrounding.replace("\n", " ")
        
        # approximate highlight
        # Since we just took a substring, we can't easily bold perfectly without offset math, 
        # but for batching we just provide the snippet.
        
        items_str += f"""
Item {idx + 1}:
- Text: "{entity.text}"
- Type: {entity.label}
- Context: "...{surrounding}..."
"""

    prompt = f"""You are validating potential redactions in a legal document.
{doc_info}

Review the following list of extracted items. For each, determine if it is a SPECIFIC confidential entity (REDACT) or a GENERIC reference/boilerplate (SKIP).

Items to validate:{items_str}

Respond with a JSON object containing a "results" array.
Each result must have:
- "id": The item number (1, 2, etc.)
- "classification": "FULL_REDACT" (specific entity) or "SKIP" (generic)
- "confidence": 0.0 to 1.0 (how sure are you?)

Crucial Rules:
1. "The Company", "The Board", "The Parties" -> SKIP (Generic)
2. Specific Names ("John Smith", "Sample 123 Corp") -> FULL_REDACT
3. If unsure, classify as FULL_REDACT.

Example Response:
{{
  "results": [
    {{ "id": 1, "classification": "FULL_REDACT", "confidence": 0.98 }},
    {{ "id": 2, "classification": "SKIP", "confidence": 0.99 }}
  ]
}}

Return ONLY valid JSON.
"""
    return prompt


def ollama_validate_batch(
    model_id: str,
    entities: List[Entity],
    full_text: str,
    doc_context: DocumentContext,
    temperature: float = 0.1,
    skip_confidence: float = 0.95,
    warnings: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict]:
    """Validate a batch of entities. Returns a list of results corresponding to input entities."""
    
    if not entities:
        return []

    prompt = get_batch_validation_prompt(entities, full_text, doc_context)

    # Build request
    url = f"{get_ollama_base_url()}/api/generate"
    body = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "num_predict": 2048 # Increased for batch response
        }
    }
    
    retry_plan = [
        {"timeout": 30, "wait": 2},
        {"timeout": 60, "wait": 2},
    ]
    
    response_json = {}
    
    # Execute Request
    for attempt in retry_plan:
        try:
            resp = requests.post(url, json=body, timeout=attempt["timeout"])
            if resp.status_code == 200:
                try:
                    res = resp.json()
                    parsed = parse_llm_response(res.get("response", ""))
                    response_json = parsed
                    break
                except Exception as e:
                    if warnings is not None:
                        warnings.append({
                            "code": "LLM_BATCH_PARSE_FAILED",
                            "message": "Failed to parse batch validation response.",
                            "details": str(e),
                        })
                    print(f"[MARCUT] Batch validation parse failed: {e}")
        except Exception as e:
            print(f"Batch validation attempt failed: {e}")
            time.sleep(attempt["wait"])
            
    # Process results with "Bias Towards Retention"
    results_map = {}
    if "results" in response_json and isinstance(response_json["results"], list):
        for res in response_json["results"]:
            try:
                item_id = int(res.get("id", -1))
                results_map[item_id] = res
            except (TypeError, ValueError):
                continue

    final_results = []
    for idx, entity in enumerate(entities):
        item_id = idx + 1
        res = results_map.get(item_id, {})
        
        classification = res.get("classification", "UNKNOWN")
        try:
            confidence = float(res.get("confidence", 0.0))
        except (ValueError, TypeError):
            confidence = 0.0  # Treat as uncertain -> keep redaction
        
        # SAFEGUARD: Strict retention bias
        # Only SKIP if model meets the configured confidence threshold.
        effective_skip = skip_confidence
        if entity.label == "NAME":
            # PREVIOUSLY: effective_skip = min(skip_confidence, 0.80)
            # CAUTION: We intentionally removed the 0.80 cap to enforce strict safety.
            # "Bias Towards Retention" means we only SKIP if we are extremely confident (>= 0.95 or similar).
            # Capping this value downwards would make it EASIER to skip names (less safe).
            effective_skip = skip_confidence

        if classification == "SKIP" and confidence >= effective_skip:
            needs_redaction = False
            final_classification = "SKIP"
        else:
            # Default to REDACT for anything ambiguous, low confidence, or explicitly REDACT
            needs_redaction = True
            final_classification = "FULL_REDACT" if classification != "SKIP" else "keep (low conf)"

        final_results.append({
            "classification": final_classification,
            "needs_redaction": needs_redaction,
            "confidence": confidence,
            "rationale": f"Batch Validation: {final_classification} ({confidence})"
        })
        
    return final_results


def apply_llm_overrides_to_rule_spans(
    text: str,
    rule_spans: List[Dict[str, Any]],
    model_id: str,
    backend: str,
    temperature: float = 0.1,
    seed: Optional[int] = None,
    skip_confidence: float = 0.95,
    allowed_labels: Optional[Set[str]] = None,
    suppressed: Optional[List[Dict[str, Any]]] = None,
    debug: bool = False,
) -> List[Dict[str, Any]]:
    """Use LLM validation to drop rule spans marked as SKIP with high confidence."""
    if not rule_spans:
        return rule_spans

    if not model_id or model_id == "mock" or backend == "mock":
        return rule_spans

    if allowed_labels is not None and not allowed_labels:
        return rule_spans

    candidates: List[Tuple[int, Entity]] = []
    company_suffix_re = None
    for idx, sp in enumerate(rule_spans):
        label = sp.get("label")
        if allowed_labels and label not in allowed_labels:
            continue

        span_text = sp.get("text")
        if span_text is None and "start" in sp and "end" in sp:
            try:
                span_text = text[sp["start"]:sp["end"]]
            except Exception:
                span_text = ""

        if not span_text:
            continue
        if label == "ORG":
            if company_suffix_re is None:
                try:
                    from .rules import COMPANY_SUFFIX
                    company_suffix_re = COMPANY_SUFFIX
                except Exception:
                    company_suffix_re = False
            if company_suffix_re and company_suffix_re.search(span_text):
                continue

        candidates.append(
            (
                idx,
                Entity(
                    text=span_text,
                    label=label or "UNK",
                    start=sp.get("start", 0),
                    end=sp.get("end", 0),
                    confidence=float(sp.get("confidence", 0.7) or 0.7),
                    needs_redaction=True,
                    rationale="Rule span override check",
                    source="rule_override",
                ),
            )
        )

    if not candidates:
        return rule_spans

    doc_context = DocumentContext()
    doc_context.analyze_document(text)

    results: List[Dict[str, Any]] = []
    try:
        if backend == "llama_cpp" or (model_id.endswith(".gguf") or model_id.startswith("/")):
            pipeline = LlamaCppRedactionPipeline(model_id, temperature, seed)
            for _, entity in candidates:
                results.append(pipeline.validate_entity(entity, text, doc_context))
        else:
            results = ollama_validate_batch(
                model_id,
                [entity for _, entity in candidates],
                text,
                doc_context,
                temperature,
                skip_confidence=skip_confidence,
            )
    except Exception as exc:
        if debug:
            print(f"[MARCUT] LLM override validation failed: {exc}")
        return rule_spans

    drop_indices: Set[int] = set()
    if backend == "llama_cpp" or (model_id.endswith(".gguf") or model_id.startswith("/")):
        for (idx, _), res in zip(candidates, results):
            classification = res.get("classification", "")
            try:
                confidence = float(res.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            if classification == "SKIP" and confidence >= skip_confidence:
                drop_indices.add(idx)
    else:
        for (idx, _), res in zip(candidates, results):
            if res.get("needs_redaction") is False:
                drop_indices.add(idx)

    if not drop_indices:
        return rule_spans

    if suppressed is not None:
        for idx in sorted(drop_indices):
            sp = rule_spans[idx]
            span_text = sp.get("text")
            if span_text is None and "start" in sp and "end" in sp:
                try:
                    span_text = text[sp["start"]:sp["end"]]
                except Exception:
                    span_text = ""
            suppressed.append({
                "reason": "llm_override_skip",
                "label": sp.get("label", "UNK"),
                "text": span_text or "",
                "start": sp.get("start"),
                "end": sp.get("end"),
                "source": sp.get("source", "rule"),
            })

    return [sp for i, sp in enumerate(rule_spans) if i not in drop_indices]


def ollama_validate(
    model_id: str,
    entity: Entity,
    full_text: str,
    doc_context: DocumentContext,
    temperature: float = 0.1
) -> Dict:
    """Validate a single entity using Ollama."""

    prompt = get_validation_prompt(entity, full_text, doc_context)

    # Build request
    url = f"{get_ollama_base_url()}/api/generate"
    body = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "num_predict": 500
        }
    }
    
    retry_plan = [
        {"timeout": 5, "wait": 2},
        {"timeout": 20, "wait": 5},
        {"timeout": 45, "wait": 0},
    ]
    last_error: Optional[Exception] = None

    for attempt_idx, attempt in enumerate(retry_plan, 1):
        try:
            resp = requests.post(url, json=body, timeout=attempt["timeout"])
            status = resp.status_code
            if 500 <= status <= 599:
                raise requests.exceptions.HTTPError(f"{status} Server Error", response=resp)
            if 400 <= status <= 499:
                detail = (resp.text or "").strip()
                if detail:
                    detail = detail[:200]
                raise RuntimeError(f"Ollama validation request failed: {status} Client Error {detail}".strip())

            result = json.loads(resp.text or "{}")
            response_text = result.get("response", "")

            # Parse validation result
            validation = parse_llm_response(response_text)
            return validation
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, json.JSONDecodeError) as e:
            last_error = e
            print(f"Validation attempt {attempt_idx} failed: {type(e).__name__}: {e}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status is not None and 500 <= status <= 599:
                last_error = e
                print(f"Validation attempt {attempt_idx} failed: HTTP {status}")
            else:
                raise RuntimeError(f"Ollama validation request failed: {e}")

        if attempt_idx < len(retry_plan):
            time.sleep(attempt["wait"])

    print(f"Validation failed after {len(retry_plan)} attempts: {last_error}")
    raise RuntimeError(f"Ollama validation failed after {len(retry_plan)} attempts: {last_error}")


class IntelligentRedactionPipeline:
    """Main pipeline for intelligent entity extraction and validation."""
    
    def __init__(self, model_id: str = "llama3.1:8b", temperature: float = 0.1, skip_confidence: float = 0.95):
        self.model_id = model_id
        self.temperature = temperature
        self.skip_confidence = skip_confidence
        self.validation_cache = ValidationCache()
        self.doc_context = DocumentContext()
    
    def process_document(
        self,
        text: str,
        chunks: List[Dict],
        progress_callback=None,
        warnings: Optional[List[Dict[str, Any]]] = None,
        suppressed: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict]:
        """Process entire document with intelligent extraction and validation."""
        
        # Analyze document for context
        self.doc_context.analyze_document(text)
        prompt_context = build_prompt_context(self.doc_context)

        def emit_mass_event(payload, progress=None, status_message=None):
            try:
                message = json.dumps(payload)
                display = status_message or message
                if tracker:
                    tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, progress or 0.0, display)
                elif progress_callback:
                    try:
                        progress_callback(0, 0, display)
                    except TypeError:
                        try:
                            progress_callback(0, 0)
                        except TypeError:
                            pass
                # Print with encoding error handling to prevent thread crashes
                try:
                    print(message, flush=True)
                except UnicodeEncodeError:
                    print(message.encode('ascii', errors='replace').decode('ascii'), flush=True)
            except Exception as e:
                pass
        
        all_entities = []

        tracker = None
        accepts_progress_update = False
        total_chunks = len(chunks)
        if progress_callback:
            try:
                sig = inspect.signature(progress_callback)
                params = [
                    p for p in sig.parameters.values()
                    if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                ]
                accepts_progress_update = (
                    len(params) == 1 and params[0].kind in (params[0].POSITIONAL_ONLY, params[0].POSITIONAL_OR_KEYWORD)
                )
            except (TypeError, ValueError):
                accepts_progress_update = False

            if accepts_progress_update:
                from .progress import ProgressTracker, ProcessingPhase
                word_count = len(text.split())
                tracker = ProgressTracker(progress_callback, text, word_count)
                tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 0.0, "Starting AI extraction")

        total_mass = sum(len(c.get("text", "")) for c in chunks)
        emit_mass_event({"type": "mass_total", "value": total_mass}, 0.0)

        # Buffer for batch validation
        to_validate_buffer = []

        if warnings is None:
            warnings = []
        if suppressed is None:
            suppressed = []

        # Helper to flush validation buffer
        def flush_validation(force=False):
            if not to_validate_buffer:
                return
            
            # Flush if enough items or forced
            if len(to_validate_buffer) < 20 and not force:
                return

            batch_entities = to_validate_buffer[:]
            to_validate_buffer.clear()
            
            print(f"[MARCUT][LLM] Batch validating {len(batch_entities)} items...", flush=True)
            
            try:
                 results = ollama_validate_batch(
                    self.model_id,
                    batch_entities,
                    text,
                    self.doc_context,
                    self.temperature,
                    skip_confidence=self.skip_confidence,
                    warnings=warnings,
                )
                 
                 # Apply results
                 for entity, result in zip(batch_entities, results):
                     entity.validated = True
                     entity.validation_result = result.get("classification")
                     entity.needs_redaction = result.get("needs_redaction", True) # Default True
                     
                     # Cache result for future
                     self.validation_cache.set(entity.text, entity.label, result)
                     
            except Exception as e:
                print(f"[MARCUT] Batch validation failed: {e}")
                # Fallback: explicitly mark all as needs_redaction=True for safety
                for entity in batch_entities:
                    entity.validated = False
                    entity.needs_redaction = True

        # === Main Processing Loop ===
        
        from .model import ollama_extract
        import time
        import threading
        
        # Global keep-alive mechanism for this process
        stop_progress = threading.Event()
        progress_thread = None
        chunk_lock = threading.Lock()
        current_chunk = 0

        if progress_callback:
            keepalive_warning_emitted = False
            def send_keepalive():
                nonlocal keepalive_warning_emitted
                while not stop_progress.is_set():
                    with chunk_lock:
                        chunk_index = current_chunk
                        chunk_total = total_chunks
                    try:
                        payload = {
                            "type": "keepalive",
                            "message": "AI processing..."
                        }
                        if chunk_total:
                            payload["chunk"] = chunk_index
                            payload["total"] = chunk_total
                        elapsed = time.time() - tracker.start_time if tracker else None
                        if elapsed is not None and chunk_total:
                            status = f"Processing chunk {chunk_index}/{chunk_total} (still running, {elapsed:.0f}s elapsed)"
                        elif elapsed is not None:
                            status = f"Processing AI extraction (still running, {elapsed:.0f}s elapsed)"
                        else:
                            status = "Processing AI extraction (still running)..."
                        emit_mass_event(payload, status_message=status)
                    except Exception as e:
                        if not keepalive_warning_emitted:
                            warnings.append({
                                "code": "LLM_KEEPALIVE_FAILED",
                                "message": "Progress keepalive updates failed during AI extraction.",
                                "details": str(e),
                            })
                            keepalive_warning_emitted = True
                        print(f"[MARCUT] Keepalive update failed: {e}")
                    stop_progress.wait(3.0)
            progress_thread = threading.Thread(target=send_keepalive, daemon=True)
            progress_thread.start()

        try:
            for chunk_idx, chunk in enumerate(chunks):
                with chunk_lock:
                    current_chunk = chunk_idx + 1
                chunk_progress = (chunk_idx / total_chunks) if total_chunks else 0.0
                if tracker:
                    tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, chunk_progress, f"Processing chunk {chunk_idx + 1}/{total_chunks}")
                
                chunk_text = chunk.get("text", "")
                chunk_start = chunk.get("start", 0)

                # Emit chunk start
                emit_mass_event({
                    "type": "chunk_start",
                    "size": len(chunk_text),
                    "estimated_time": 30.0
                }, chunk_progress)
                
                # 1. Extraction (per chunk) with retry
                simple_spans = []
                extract_error = None
                for attempt_idx, wait_s in enumerate((0, 2), start=1):
                    try:
                        simple_spans = ollama_extract(
                            self.model_id,
                            chunk_text,
                            self.temperature,
                            seed=42,
                            context=prompt_context
                        )
                        extract_error = None
                        break
                    except Exception as e:
                        extract_error = e
                        print(f"Extraction attempt {attempt_idx} failed for chunk {chunk_idx}: {e}")
                        if wait_s:
                            time.sleep(wait_s)
                if extract_error is not None:
                    warnings.append({
                        "code": "LLM_CHUNK_FAILED",
                        "message": f"AI extraction failed for chunk {chunk_idx + 1} after retries.",
                        "details": str(extract_error)
                    })

                # Convert to Entities
                entities = []
                for span in simple_spans:
                    entity_text = chunk_text[span["start"]:span["end"]]
                    
                    # PRE-FILTER: Skip clearly generic entities immediately
                    # This catches "the Company", "the Board", etc. before wasting LLM calls
                    if _looks_like_document_title(entity_text):
                        suppressed.append({
                            "reason": "doc_title",
                            "label": span.get("label", "UNK"),
                            "text": entity_text,
                            "start": span.get("start", 0) + chunk_start,
                            "end": span.get("end", 0) + chunk_start,
                            "source": "llm_extract",
                        })
                        continue
                    if _is_generic_term(entity_text):
                        suppressed.append({
                            "reason": "generic_term",
                            "label": span.get("label", "UNK"),
                            "text": entity_text,
                            "start": span.get("start", 0) + chunk_start,
                            "end": span.get("end", 0) + chunk_start,
                            "source": "llm_extract",
                        })
                        continue
                        
                    entities.append(Entity(
                        text=entity_text,
                        label=span["label"],
                        start=span["start"] + chunk_start, # Adjust to doc coordinates immediately
                        end=span["end"] + chunk_start,
                        confidence=0.7,
                        needs_redaction=True,
                        rationale="Extracted by model"
                    ))
                
                self.doc_context.all_entities.extend(entities)
                all_entities.extend(entities)

                # 2. Identify candidates for validation (check cache first)
                for entity in entities:
                    cached = self.validation_cache.get(entity.text, entity.label)
                    if cached:
                        entity.validated = True
                        entity.needs_redaction = cached.get("needs_redaction", True)
                        entity.validation_result = cached.get("classification")
                    elif needs_validation(entity, self.doc_context):
                        to_validate_buffer.append(entity)

                # 3. Opportunistic Flush (Batch Validation)
                flush_validation(force=False)

                emit_mass_event({
                    "type": "chunk_end",
                    "size": len(chunk_text)
                }, (chunk_idx + 1) / total_chunks)

            # Final flush of validaton buffer
            flush_validation(force=True)

        finally:
            if stop_progress:
                stop_progress.set()
            if progress_thread:
                progress_thread.join(timeout=1.0)

        if tracker:
            tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 1.0, "AI extraction complete")
        
        # Convert to output format
        output_spans = []
        for entity in all_entities:
            # Filter based on final needs_redaction status
            if not entity.needs_redaction:
                continue
            
            span = {
                "start": entity.start,
                "end": entity.end,
                "text": entity.text,
                "label": entity.label,
                "confidence": entity.confidence,
                "source": entity.source,
                "validated": entity.validated
            }
            if entity.validation_result:
                span["validation_result"] = entity.validation_result
            
            output_spans.append(span)
        
        return output_spans


def run_enhanced_model(
    backend: str,
    text: str,
    chunks: List[Dict],
    temperature: float = 0.1,
    seed: Optional[int] = None,
    progress_callback=None,
    model_id: str = None,  # For backward compatibility
    model_path: str = None,  # For llama_cpp backend
    skip_confidence: float = 0.95,
    warnings: Optional[List[Dict[str, Any]]] = None,
    suppressed: Optional[List[Dict[str, Any]]] = None,
    **kwargs
) -> List[Dict]:
    """Main entry point for enhanced model extraction."""

    if backend == "ollama":
        if not model_id:
            raise ValueError("model_id required for Ollama backend")
        pipeline = IntelligentRedactionPipeline(model_id, temperature, skip_confidence=skip_confidence)
        return pipeline.process_document(
            text,
            chunks,
            progress_callback=progress_callback,
            warnings=warnings,
            suppressed=suppressed,
        )
    elif backend == "llama_cpp":
        if not model_path:
            raise ValueError("model_path required for llama_cpp backend")
        pipeline = LlamaCppRedactionPipeline(model_path, temperature, seed)
        return pipeline.process_document(text, chunks, progress_callback=progress_callback)
    else:
        raise ValueError(f"Unsupported backend: {backend}. Use 'ollama' or 'llama_cpp'")


# Global variable to cache the llama.cpp model
_llama_model = None
_llama_model_path = None


class LlamaCppRedactionPipeline:
    """LLama.cpp-based redaction pipeline using direct GGUF model loading."""

    def __init__(self, model_path: str, temperature: float = 0.1, seed: Optional[int] = None):
        self.model_path = model_path
        self.temperature = temperature
        self.seed = seed or 42
        self._llama_model = None

    def _get_model(self):
        """Load and cache the llama.cpp model."""
        global _llama_model, _llama_model_path

        try:
            from llama_cpp import Llama
        except ImportError:
            raise RuntimeError("llama-cpp-python not installed. Run: pip install llama-cpp-python")

        # Load model if not cached or if path changed
        if _llama_model is None or _llama_model_path != self.model_path:
            if not os.path.exists(self.model_path):
                raise RuntimeError(f"Model file not found: {self.model_path}")

            print(f"Loading model: {self.model_path}...", file=sys.stderr)
            try:
                _llama_model = Llama(
                    model_path=self.model_path,
                    n_ctx=8192,  # Context window
                    n_gpu_layers=-1,  # Offload all layers to GPU if available
                    seed=self.seed,
                    verbose=False
                )
                _llama_model_path = self.model_path
            except Exception as e:
                raise RuntimeError(f"Error loading model: {e}")

        return _llama_model

    def _generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        """Generate response using llama.cpp model."""
        model = self._get_model()

        try:
            response = model(
                prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                stop=["<|end|>", "<|user|>", "\n\n"],
                echo=False
            )
            return response['choices'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Error during inference: {e}")

    def extract_entities(self, text: str, doc_context: DocumentContext) -> List[Entity]:
        """Extract entities using local Llama.cpp model."""
        try:
            prompt_context = build_prompt_context(doc_context)
            prompt = build_extraction_prompt(text, prompt_context)

            # Generate response locally
            # Note: We trust the prompt builder to provide the correct JSON structure instruction
            response_text = self._generate_response(prompt)
            
            # Parse JSON response
            parsed = parse_llm_response(response_text)
            
            # Convert parsed dict items to Entity objects
            entities = []
            for item in parsed.get("entities", []):
                entity_text = item.get("text", "")
                if not entity_text:
                    continue
                    
                raw_label = item.get("label") or item.get("type") or ""
                label = _map_label(raw_label)
                if not label and raw_label:
                    label = raw_label.strip().upper()
                if label not in ["NAME", "ORG", "LOC", "DATE", "MONEY", "NUMBER", "EMAIL", "PHONE", "SSN"]:
                    continue

                # Validate candidate (prevent span explosion on garbage)
                if not _valid_candidate(entity_text, label):
                    continue

                # Find all occurrences of the entity text
                start_search = 0
                while True:
                    start = text.find(entity_text, start_search)
                    if start == -1:
                        break

                    entity = Entity(
                        text=entity_text,
                        label=label,
                        start=start,
                        end=start + len(entity_text),
                        confidence=item.get("confidence", 0.85),
                        needs_redaction=item.get("needs_redaction", True),
                        rationale=item.get("rationale"),
                        source=self.model_id
                    )
                    entities.append(entity)
                    start_search = start + 1

            return entities

        except Exception as e:
            print(f"Error in Llama.cpp entity extraction: {e}")
            return []

    def validate_entity(self, entity: Entity, full_text: str, doc_context: DocumentContext) -> Dict:
        """Validate a single entity using local Llama.cpp model."""
        try:
            # Build validation prompt
            prompt = get_validation_prompt(entity, full_text, doc_context)
            
            # Generate response locally
            response_text = self._generate_response(prompt, max_tokens=512)
            
            # Parse JSON
            validation_result = parse_llm_response(response_text)

            # Return normalized result
            return {
                "classification": validation_result.get("classification", "UNKNOWN"),
                "needs_redaction": validation_result.get("needs_redaction", True),
                "confidence": validation_result.get("confidence"),
                "rationale": validation_result.get("explanation") or validation_result.get("rationale")
            }

        except Exception as e:
            print(f"Error in Llama.cpp entity validation: {e}")
            # Default to keeping the entity if validation fails
            return {
                "classification": "UNKNOWN",
                "needs_redaction": True,
                "confidence": 0.0,
                "rationale": f"Validation failed: {str(e)}"
            }

    def process_document(self, text: str, chunks: List[Dict], progress_callback=None) -> List[Dict]:
        """Process document using the enhanced pipeline with Ollama."""
        # Create document context
        doc_context = DocumentContext()
        doc_context.analyze_document(text)

        all_entities = []
        total_chunks = len(chunks)

        # Extract entities from each chunk
        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback(i + 1, total_chunks, f"Processing chunk {i + 1}/{total_chunks}")

            chunk_text = chunk["text"]
            chunk_start = chunk["start"]

            # Extract entities from this chunk
            entities = self.extract_entities(chunk_text, doc_context)

            # Adjust entity positions to document coordinates
            for entity in entities:
                entity.start += chunk_start
                entity.end += chunk_start
                # Update text to match document text
                entity.text = text[entity.start:entity.end]

            all_entities.extend(entities)

        # Convert entities to span format
        spans = []
        for entity in all_entities:
            span = {
                "start": entity.start,
                "end": entity.end,
                "label": entity.label,
                "text": entity.text,
                "confidence": entity.confidence,
                "source": entity.source,
                "needs_redaction": entity.needs_redaction,
                "rationale": entity.rationale
            }
            spans.append(span)

        return spans
