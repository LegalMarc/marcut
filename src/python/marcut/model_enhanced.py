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
from typing import List, Dict, Any, Optional, Tuple
import requests
from dataclasses import dataclass, asdict
import hashlib
from .model import run_model, parse_llm_response, _valid_candidate, get_ollama_base_url, get_exclusion_patterns


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
        
        if potential_companies:
            # The first major company name is likely the primary entity
            self.primary_entities['company'] = potential_companies[0]
            # Common aliases
            self.entity_aliases[potential_companies[0].lower()] = [
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


def get_enhanced_extraction_prompt(text: str, doc_context: DocumentContext) -> str:
    """Build enhanced extraction prompt with document context."""
    
    context_info = ""
    if doc_context.document_type:
        context_info = f"This is a {doc_context.document_type.replace('_', ' ')}. "
    if doc_context.primary_entities.get('company'):
        context_info += f"The primary company is '{doc_context.primary_entities['company']}' which may be referred to as 'the Company' throughout. "
    
    prompt = f"""You are a legal document redaction specialist reviewing a {doc_context.document_type or 'legal document'}.
{context_info}

Your task is to identify entities that contain CONFIDENTIAL information requiring redaction.

EXTRACT AND MARK FOR REDACTION (needs_redaction=true):
- Actual names of real people (e.g., "John Smith", "Mary Johnson") 
- Actual names of specific companies/organizations (e.g., "Apple Inc.", "Goldman Sachs", "Smartfrog & Canary Holdings, Inc.")
- Specific addresses with street names/numbers
- Phone numbers, email addresses, SSNs
- Specific monetary amounts (e.g., "$1,000,000")
- Specific dates when they identify particular events

CRITICAL FOR SIGNATURE BLOCKS:
- In signature blocks (areas with "By:", "Name:", "Title:" patterns), ALWAYS extract individual person names even if they appear on the same line
- Look for multiple names separated by spaces or formatting in signature areas
- Each individual person name should be extracted as a separate NAME entity
- Example: "Name: John Smith          Jane Doe" should extract both "John Smith" and "Jane Doe" as separate NAME entities

IMPORTANT: Real company names like "SMARTFROG & CANARY HOLDINGS, INC." should have needs_redaction=true because they identify specific parties.

DO NOT EXTRACT (skip these entirely):
- Generic references: "the Company", "the Board", "the Stockholders", "the Purchaser"
- Legal boilerplate: "RESOLVED", "WHEREAS", "NOW THEREFORE", "AGREEMENT"
- Role descriptions: "officers of the Company", "Board of Directors", "Chief Executive Officer"
- Document references: "Exhibit A", "Schedule 1", "Section 3.2", "the Bylaws"
- Legal provisions: "Section 141(f)", "DGCL", "Delaware General Corporation Law"

For the following text, extract entities and provide this JSON structure:
{{
  "entities": [
    {{
      "text": "exact text from document",
      "label": "NAME|ORG|LOC|DATE|MONEY|NUMBER|EMAIL|PHONE|SSN",
      "needs_redaction": true/false,
      "confidence": 0.0-1.0,
      "rationale": "brief explanation of why this needs/doesn't need redaction"
    }}
  ]
}}

ONLY use these labels: NAME, ORG, LOC, DATE, MONEY, NUMBER, EMAIL, PHONE, SSN
Do not use other labels like ROLE, LEGISLATION, DOCUMENT, ACRONYM, etc.

Important guidelines:
- Monetary amounts: ALWAYS mark monetary amounts that include a currency sign or ISO code (e.g., $, £, €, ¥, USD, EUR, GBP, CAD) as MONEY, whether or not the number is bracketed (e.g., "$[20,034,641.91]").
- Numbers: Numeric amounts WITHOUT an explicit currency sign or ISO code should be labeled NUMBER (e.g., "[2,057,103]").
- Set needs_redaction=true ONLY for specific, identifiable entities or sensitive values (MONEY, SSN, etc.).
- Set needs_redaction=false for generic references and legal language.
- Provide confidence based on how certain you are this is a real entity vs generic reference.
- Include a brief rationale explaining your decision.

Text to analyze:
{text}

Return ONLY valid JSON with the structure shown above."""
    
    return prompt


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
    
    # Check rationale for uncertainty markers
    if entity.rationale:
        uncertain_phrases = [
            'might be', 'possibly', 'unclear', 'could be', 
            'not sure', 'maybe', 'perhaps', 'seems like'
        ]
        if any(p in entity.rationale.lower() for p in uncertain_phrases):
            return True
    
    # Use excluded-words list as a validation trigger (not a filter)
    txt = entity.text.strip()
    for pat in get_exclusion_patterns():
        try:
            if pat.match(txt):
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


def ollama_extract_enhanced(
    model_id: str,
    text: str,
    doc_context: DocumentContext,
    temperature: float = 0.1,
    seed: Optional[int] = None
) -> List[Entity]:
    """Extract entities using enhanced prompt with Ollama."""

    prompt = get_enhanced_extraction_prompt(text, doc_context)

    # Build request
    url = f"{get_ollama_base_url()}/api/generate"
    body = {
        "model": model_id,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "num_predict": 2000
        }
    }
    
    if seed is not None:
        body["options"]["seed"] = seed
    
    # Make request
    try:
        # Increase timeout to 300s (5min) to handle initial Metal shader compilation
        resp = requests.post(url, json=body, timeout=300)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama request failed: {e}")
    
    # Parse response
    result = resp.json()
    response_text = result.get("response", "")
    
    # Parse entities from response
    parsed = parse_llm_response(response_text)
    
    entities = []
    for item in parsed.get("entities", []):
        entity_text = item.get("text", "")
        if not entity_text: continue
        
        # Filter out unexpected labels
        label = item.get("label", "UNK")
        if label not in ["NAME", "ORG", "LOC", "DATE", "MONEY", "NUMBER", "EMAIL", "PHONE", "SSN"]:
            continue
            
        # Validate candidate (prevent span explosion on garbage)
        if not _valid_candidate(entity_text, label):
             continue

        # Use shared helper to find ALL occurrences (fixes bug where only first was found)
        # We need to import _find_entity_spans inside the method or at top level if not present
        # Assuming it's available via from .model import _find_entity_spans
        # But since I can't see imports easily, I'll rely on the fact that I can add the import.
        # Wait, I should add the import first.
        # Actually, I'll implement a local loop if I can't verify imports easily, 
        # BUT I should prefer reuse.
        
        # Let's assume I will add the import in a separate block or verify it exists.
        # Using a reliable local loop here to avoid import errors if circular.
        
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
                confidence=0.85, 
                source=model_id
            )
            entities.append(entity)
            start_search = start + 1
            
    return entities


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
    
    # Make request
    try:
        resp = requests.post(url, json=body, timeout=300)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Ollama validation request failed: {e}")
    
    # Parse response
    result = resp.json()
    response_text = result.get("response", "")
    
    # Parse validation result
    validation = parse_llm_response(response_text)
    
    return validation


class IntelligentRedactionPipeline:
    """Main pipeline for intelligent entity extraction and validation."""
    
    def __init__(self, model_id: str = "llama3.1:8b", temperature: float = 0.1):
        self.model_id = model_id
        self.temperature = temperature
        self.validation_cache = ValidationCache()
        self.doc_context = DocumentContext()
    
    def process_document(self, text: str, chunks: List[Dict], progress_callback=None) -> List[Dict]:
        """Process entire document with intelligent extraction and validation."""
        
        # Analyze document for context
        self.doc_context.analyze_document(text)

        def emit_mass_event(payload, progress=None):
            try:
                message = json.dumps(payload)
                if tracker:
                    tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, progress or 0.0, message)
                elif progress_callback:
                    try:
                        progress_callback(0, 0, message)
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
                # Catch-all: never let this function crash the calling thread
                try:
                    print(f"[MARCUT] emit_mass_event error: {e}", flush=True)
                except Exception:
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

        for chunk_idx, chunk in enumerate(chunks):
            if tracker:
                progress = (chunk_idx) / total_chunks if total_chunks else 0.0
                message = f"Processing chunk {chunk_idx + 1}/{total_chunks}" if total_chunks else None
                tracker.update_phase(
                    ProcessingPhase.LLM_EXTRACTION,
                    progress,
                    message,
                )
            elif progress_callback:
                try:
                    progress_callback(chunk_idx + 1, total_chunks)
                except TypeError:
                    progress_callback(chunk_idx + 1, total_chunks, f"Processing chunk {chunk_idx + 1}/{total_chunks}")
            chunk_text = chunk.get("text", "")
            chunk_start = chunk.get("start", 0)

            # Emit chunk start event for smooth progress
            # 30.0s is a heuristic for "worst case" chunk time on typical hardware
            chunk_progress = (chunk_idx / total_chunks) if total_chunks else 0.0
            emit_mass_event({
                "type": "chunk_start",
                "size": len(chunk_text),
                "estimated_time": 30.0
            }, chunk_progress)
            
            # Extract entities with simple prompt (enhanced prompt times out with large chunks)
            # Use the simpler, proven ollama_extract from model.py
            from .model import ollama_extract
            import time
            import threading

            # Start keep-alive heartbeat during AI processing
            # This prevents stall detection during long blocking LLM calls
            progress_thread = None
            stop_progress = None
            if progress_callback:  # Always run keep-alive if we have a callback
                stop_progress = threading.Event()

                def send_keepalive():
                    """Send periodic keep-alive signals during blocking AI call.
                    
                    This prevents the Swift heartbeat monitor from detecting a stall
                    during long LLM inference calls. We send a simple JSON payload
                    that the UI can recognize as a keep-alive signal.
                    """
                    keepalive_interval = 3.0  # Send keep-alive every 3 seconds
                    
                    while not stop_progress.is_set():
                        try:
                            # Send keep-alive event through the mass event system
                            emit_mass_event({
                                "type": "keepalive",
                                "chunk": chunk_idx + 1,
                                "total": total_chunks,
                                "message": f"AI processing chunk {chunk_idx + 1}/{total_chunks}..."
                            })
                        except Exception as e:
                            # Log but don't crash - keep trying
                            try:
                                print(f"[MARCUT] Keep-alive error: {e}", flush=True)
                            except Exception:
                                pass
                        
                        # Wait for next interval or until stopped
                        stop_progress.wait(timeout=keepalive_interval)

                progress_thread = threading.Thread(target=send_keepalive, daemon=True)
                progress_thread.start()

            try:
                print(f"[MARCUT][LLM] Requesting entities via Ollama model '{self.model_id}' for chunk {chunk_idx + 1}/{total_chunks}")
                simple_spans = ollama_extract(
                    self.model_id,
                    chunk_text,
                    self.temperature,
                    seed=42  # Fixed seed for consistency
                )
            except Exception as e:
                if tracker:
                    tracker.update_phase(
                        ProcessingPhase.LLM_EXTRACTION,
                        (chunk_idx) / total_chunks if total_chunks else 0.0,
                        f"AI extraction failed: {e}"
                    )
                raise RuntimeError(f"Ollama extraction failed for chunk {chunk_idx + 1}/{total_chunks}: {e}") from e
            finally:
                # Stop progress simulation
                if progress_thread and stop_progress:
                    stop_progress.set()
                    progress_thread.join(timeout=1.0)

            # Convert simple spans to Entity objects
            entities = []
            for span in simple_spans:
                try:
                    entity = Entity(
                        text=chunk_text[span["start"]:span["end"]],
                        label=span["label"],
                        start=span["start"],
                        end=span["end"],
                        confidence=0.7,  # Default confidence
                        needs_redaction=True,  # Default to redact
                        rationale="Extracted by model"
                    )
                    entities.append(entity)
                except Exception as e:
                    print(f"Error creating entity from span {span}: {e}")
                    continue
            if tracker:
                completed = (chunk_idx + 1) / total_chunks if total_chunks else 1.0
                tracker.update_phase(
                    ProcessingPhase.LLM_EXTRACTION,
                    completed,
                    f"Processing chunk {chunk_idx + 1}/{total_chunks}" if total_chunks else None,
                )

            # Adjust positions to document level
            for entity in entities:
                entity.start += chunk_start
                entity.end += chunk_start
            
            # Update document context with new entities
            self.doc_context.all_entities.extend(entities)
            
            # Identify entities needing validation
            to_validate = []
            for entity in entities:
                # Check cache first
                cached = self.validation_cache.get(entity.text, entity.label)
                if cached:
                    entity.validated = True
                    entity.validation_result = cached.get("classification")
                    entity.needs_redaction = cached.get("needs_redaction", entity.needs_redaction)
                    entity.confidence = cached.get("confidence", entity.confidence)
                elif needs_validation(entity, self.doc_context):
                    to_validate.append(entity)
            
            # Validate uncertain entities
            for entity in to_validate:
                try:
                    validation = ollama_validate(
                        self.model_id,
                        entity,
                        text,  # Full document text for context
                        self.doc_context,
                        self.temperature
                    )
                    
                    # Update entity with validation results
                    entity.validated = True
                    entity.validation_result = validation.get("classification", "UNKNOWN")
                    entity.needs_redaction = validation.get("needs_redaction", entity.needs_redaction)
                    
                    # Update confidence based on validation
                    if validation.get("confidence"):
                        # Average original and validation confidence
                        entity.confidence = (entity.confidence + validation["confidence"]) / 2
                    
                    # Cache result
                    self.validation_cache.set(entity.text, entity.label, validation)
                    
                except Exception as e:
                    print(f"Validation failed for entity '{entity.text}': {e}")
                    # Keep original assessment if validation fails
                    entity.validated = False
            
            all_entities.extend(entities)

            # Emit chunk end event
            chunk_progress = ((chunk_idx + 1) / total_chunks) if total_chunks else 1.0
            emit_mass_event({
                "type": "chunk_end",
                "size": len(chunk_text)
            }, chunk_progress)

        if tracker:
            tracker.update_phase(ProcessingPhase.LLM_EXTRACTION, 1.0, "AI extraction complete")
        
        # Convert to output format
        output_spans = []
        for entity in all_entities:
            # Skip entities that don't need redaction after validation
            if not entity.needs_redaction:
                continue
            
            # Skip PARTIAL_REDACT for now (would need special handling)
            if entity.validation_result == "PARTIAL_REDACT":
                print(f"Skipping partial redaction for: {entity.text}")
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
    **kwargs
) -> List[Dict]:
    """Main entry point for enhanced model extraction."""

    if backend == "ollama":
        if not model_id:
            raise ValueError("model_id required for Ollama backend")
        pipeline = IntelligentRedactionPipeline(model_id, temperature)
        return pipeline.process_document(text, chunks, progress_callback=progress_callback)
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
            # Build prompt using the shared enhanced prompt builder
            prompt = get_enhanced_extraction_prompt(text, doc_context)

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
                    
                # Find position in text (simple find, could be improved)
                label = item.get("label", "UNK")
                # Filter allowed labels
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


def llama_cpp_validate(
    model_path: str,
    entity: Entity,
    full_text: str,
    doc_context: DocumentContext,
    temperature: float = 0.1
) -> Dict:
    """Validate a single entity using llama.cpp model."""
    pipeline = LlamaCppRedactionPipeline(model_path, temperature)
    return pipeline.validate_entity(entity, full_text, doc_context)
