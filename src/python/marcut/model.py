
from typing import List, Dict, Any, Optional, Set
import json, requests
import os
import sys
import re
import time
from .network_utils import normalize_ollama_base_url

DEFAULT_EXTRACT_SYSTEM = """Extract entities for legal document redaction. Output JSON only.

Types:
- NAME: People (e.g., "John Smith", "Dr. Jane Doe"). NOT roles like "Company", "Board".
- ORG: Companies with designators (Inc, LLC, Corp, Ltd). NOT "Purchaser", "Seller", "Party".
  Examples:
    ✓ Correct: "Sample 123 Holdings, Inc."
    ✗ Wrong: "Sample 123 Holdings, Inc., a Delaware corporation"
    ✗ Wrong: "the Company"
- LOC: Places (e.g., "Delaware", "123 Main St, NY"). NOT "the State", "Section".

Rules:
- Extract the minimal span that identifies the entity. Do not include surrounding context, parenthetical descriptions, or jurisdictional phrases like "a Delaware corporation".
- No boilerplate: Agreement, Section, Exhibit, Article, Bylaws, Charter, DGCL, Board, Stockholder(s)
- Prefer full names over fragments

Format: {"entities": [{"text": "...", "type": "NAME|ORG|LOC"}]}
"""

_SYSTEM_PROMPT_CACHE = {
    "text": DEFAULT_EXTRACT_SYSTEM,
    "mtime": None,
    "path": None,
}

_DEFAULT_EXCLUDED_FILE = os.path.join(os.path.dirname(__file__), 'excluded-words.txt')

# Determiner prefixes to strip for exclusion checks
_DETERMINER_PREFIXES = (
    "the", "a", "an", "this", "that", "such", "each", "any", "certain",
    "both", "all", "these", "those", "every", "either", "neither",
)
_DETERMINER_PREFIX_RE = re.compile(
    rf"^(?:{'|'.join(_DETERMINER_PREFIXES)})\s+",
    re.IGNORECASE,
)
_TRAILING_PAREN_S_RE = re.compile(r"\(s\)\s*$", re.IGNORECASE)

# Optimized cache: split literals (O(1) set lookup) from regex patterns
_EXCLUDED_CACHE = {
    "literals": None,   # Set[str] - normalized lowercase literals for O(1) lookup
    "patterns": None,   # List[re.Pattern] - actual regex patterns (rare)
    "mtime": None,
    "path": None,
    "last_check": 0,
}

# Cache for backward-compatible get_exclusion_patterns() - avoids recompiling on every call
_LEGACY_PATTERNS_CACHE = {
    "patterns": None,
    "cache_key": None,  # Hash of (literals, len(patterns)) to detect changes
}

# Global variable to cache the llama.cpp model
_llama_model = None
_llama_model_path = None

def _log_app_event(message: str) -> None:
    log_path = os.getenv("MARCUT_LOG_PATH")
    if not log_path:
        return
    try:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] PythonModel: {message}\n")
    except Exception:
        pass

def get_ollama_base_url() -> str:
    return normalize_ollama_base_url(loopback_only=False)


def parse_llm_response(response_text: str) -> Dict[str, Any]:
    """
    Sanitize and parse an LLM response, raising json.JSONDecodeError when invalid.
    """
    cleaned = (response_text or "").strip()

    code_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', cleaned, re.IGNORECASE)
    if code_block_match:
        json_str = code_block_match.group(1).strip()
    else:
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        if start == -1 or end <= start:
            raise json.JSONDecodeError("No JSON object found in response", cleaned, 0)
        json_str = cleaned[start:end]

    json_str = re.sub(r'(?m)//.*$', '', json_str)
    json_str = re.sub(r',\s*(\]|\})', r'\1', json_str)

    return json.loads(json_str)

def llama_cpp_extract(
    model_path: str,
    text: str,
    temperature: float = 0.0,
    seed: int = 42,
    threads: int = 4,
    context: Optional[str] = None
) -> List[Dict[str,Any]]:
    """Extract PII spans using llama.cpp with a GGUF model."""
    global _llama_model, _llama_model_path
    
    try:
        from llama_cpp import Llama
    except ImportError:
        print("Error: llama-cpp-python not installed. Run: pip install llama-cpp-python", file=sys.stderr)
        return []
    
    # Load model if not cached or if path changed
    if _llama_model is None or _llama_model_path != model_path:
        if not os.path.exists(model_path):
            print(f"Error: Model file not found: {model_path}", file=sys.stderr)
            return []
        
        print(f"Loading model: {model_path}...", file=sys.stderr)
        try:
            _llama_model = Llama(
                model_path=model_path,
                n_ctx=8192,  # Context window
                n_threads=threads,  # CPU threads
                seed=seed,
                verbose=False
            )
            _llama_model_path = model_path
        except Exception as e:
            print(f"Error loading model: {e}", file=sys.stderr)
            return []
    
    # Format prompt for Phi-3 or similar instruction models
    prompt = build_extraction_prompt(text, context)
    
    try:
        # Generate response
        response = _llama_model(
            prompt,
            max_tokens=1024,
            temperature=temperature,
            stop=["<|end|>", "<|user|>", "\n\n"],
            echo=False
        )
        
        # Extract the generated text
        generated_text = response['choices'][0]['text'].strip()
        
        # Try to parse as JSON
        # Handle cases where the model might add extra text
        json_start = generated_text.find('{')
        json_end = generated_text.rfind('}') + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = generated_text[json_start:json_end]
            data = json.loads(json_str)
            
            # Case A: Standard "entities" format (as requested by prompt)
            if "entities" in data:
                entities = data["entities"]
                all_spans = []
                for ent in entities:
                    if not isinstance(ent, dict): continue
                    etext = ent.get("text", "")
                    etype = ent.get("type", "")
                    label = _map_label(etype)
                    if etext and label:
                        # Use smart split to clean boilerplate (e.g. "Title: Name" -> "Name")
                        cleaned_text = _smart_split_clean(etext)
                        if cleaned_text:
                            # Use shared helper to find all instances
                            found = _find_entity_spans(text, cleaned_text, label)
                            all_spans.extend(found)
                
                # Deduplicate spans
                unique = []
                seen = set()
                for s in sorted(all_spans, key=lambda x: (x["start"], x["end"])):
                    k = (s["start"], s["end"], s["label"])
                    if k not in seen:
                        seen.add(k)
                        unique.append(s)
                return unique

            # Case B: Legacy "spans" format (fallback)
            elif "spans" in data:
                return data["spans"]
            
            return []
        else:
            return []
            
    except json.JSONDecodeError:
        # If JSON parsing fails, try to extract any valid spans
        return []
    except Exception as e:
        print(f"Error during inference: {e}", file=sys.stderr)
        return []

def _map_label(lbl: str) -> Optional[str]:
    t = (lbl or '').strip().upper()
    if t in ("NAME", "PERSON", "HUMAN", "INDIVIDUAL"): return "NAME"
    if t in ("ORG", "ORGANIZATION", "COMPANY", "INSTITUTION", "BUSINESS"): return "ORG"
    if t in ("BRAND", "PRODUCT", "SERVICE"): return "BRAND"
    if t in ("LOC", "LOCATION", "GPE", "PLACE", "ADDRESS"): return "LOC"
    if t in ("MONEY", "CURRENCY"): return "MONEY"
    if t in ("NUMBER", "QUANTITY", "COUNT", "AMOUNT"): return "NUMBER"
    if t in ("DATE",): return "DATE"
    # IMPORTANT: no fallback. Unknown labels are dropped.
    return None

def _normalize_for_exclusion(text: str) -> str:
    """
    Normalize text for exclusion checking.
    - Strip common determiners (e.g., "the", "a", "certain")
    - Collapse internal whitespace to single spaces
    - Lowercase for case-insensitive matching
    """
    text = _strip_leading_determiner(text)
    text = text.strip().lower()
    # Strip common trailing punctuation to allow matching at sentence ends
    # e.g. "Delaware corporation." -> "delaware corporation"
    text = text.rstrip(".,;:!?\"'")
    text = re.sub(r'\s+', ' ', text)
    return text


def _strip_leading_determiner(text: str) -> str:
    """Remove leading determiners from a phrase for exclusion matching."""
    return _DETERMINER_PREFIX_RE.sub("", text.strip())


def _matches_exclusion_literal(normalized: str, literals: Set[str]) -> bool:
    """
    Check literal exclusions with optional singularization.
    Only strip trailing "(s)" or "s" if the singular form exists in literals.
    """
    if normalized in literals:
        return True
    singular: Optional[str] = None
    if _TRAILING_PAREN_S_RE.search(normalized):
        singular = _TRAILING_PAREN_S_RE.sub("", normalized).strip()
    elif normalized.endswith("ies") and len(normalized) > 3:
        singular = normalized[:-3] + "y"
    elif normalized.endswith("s") and len(normalized) > 1:
        singular = normalized[:-1].rstrip()
    if singular and singular in literals:
        return True
    return False


def _is_regex_pattern(line: str) -> bool:
    """
    Check if a line contains regex special characters.
    Reuses the exact heuristic from the original implementation.
    """
    return bool(re.search(r'[\\^$.*+?{}()\[\]|]', line))


def _get_base_excluded_literals() -> Set[str]:
    """
    Get base excluded terms as normalized literals (for O(1) set lookup).
    Includes auto-generated plurals for terms not ending in 's'.
    """
    base_terms = [
        "agreement", "section", "article", "recital", "exhibit", "schedule", "appendix", "annex",
        "notice", "resolution", "minutes", "consent", "meeting", "vote", "bylaws", "charter",
        "company", "corporation", "board", "board of directors", "stockholder", "stockholders",
        "member", "members", "party", "parties", "purchaser", "seller", "target", "counterparty",
        "dgcl", "act", "law", "statute", "code", "regulation", "ccpa",
    ]
    literals: Set[str] = set()
    for term in base_terms:
        normalized = _normalize_for_exclusion(term)
        literals.add(normalized)
        # Auto-generate plurals for terms not ending in 's'
        if not normalized.endswith('s'):
            literals.add(normalized + 's')
    return literals


_BASE_EXCLUDED_LITERALS = _get_base_excluded_literals()


def get_exclusion_data() -> tuple:
    """
    Get optimized exclusion data: (literals_set, regex_patterns_list).
    
    Returns:
        tuple: (Set[str], List[re.Pattern])
            - literals_set: Normalized lowercase strings for O(1) lookup
            - regex_patterns_list: Compiled regex patterns for complex matching
    """
    global _EXCLUDED_CACHE
    current_time = time.time()
    
    # Check if cache is valid (simple 5s TTL + mtime check)
    if _EXCLUDED_CACHE["literals"] is not None:
        last_check = _EXCLUDED_CACHE.get("last_check", 0)
        if current_time - last_check < 5.0:
            return (_EXCLUDED_CACHE["literals"], _EXCLUDED_CACHE["patterns"])
    
    # Start with base literals
    literals: Set[str] = set(_BASE_EXCLUDED_LITERALS)
    patterns: List[re.Pattern] = []
    
    # Load excluded words (env var override or default)
    user_path = os.getenv("MARCUT_EXCLUDED_WORDS_PATH")
    target_path = user_path if (user_path and os.path.exists(user_path)) else _DEFAULT_EXCLUDED_FILE
    
    if os.path.exists(target_path):
        try:
            mtime = os.path.getmtime(target_path)
            # Reload if file changed OR path changed
            if mtime != _EXCLUDED_CACHE["mtime"] or target_path != _EXCLUDED_CACHE["path"]:
                # Build fresh collections
                file_literals: Set[str] = set()
                file_patterns: List[re.Pattern] = []
                
                with open(target_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        try:
                            if _is_regex_pattern(line):
                                # User provided a regex pattern - compile as-is
                                file_patterns.append(re.compile(line, re.IGNORECASE))
                            else:
                                # Plain text - normalize and add to literals set
                                file_literals.add(_normalize_for_exclusion(line))
                        except re.error:
                            print(f"Warning: Invalid regex in excluded words: {line}", file=sys.stderr)
                
                # Merge with base literals
                literals = set(_BASE_EXCLUDED_LITERALS) | file_literals
                patterns = file_patterns
                
                _EXCLUDED_CACHE["mtime"] = mtime
                _EXCLUDED_CACHE["path"] = target_path
            else:
                # File unchanged, use cached data
                literals = _EXCLUDED_CACHE["literals"]
                patterns = _EXCLUDED_CACHE["patterns"]
        except Exception as e:
            print(f"Error loading excluded words: {e}", file=sys.stderr)
    
    # Update cache atomically
    _EXCLUDED_CACHE["literals"] = literals
    _EXCLUDED_CACHE["patterns"] = patterns
    _EXCLUDED_CACHE["last_check"] = current_time
    return (literals, patterns)


def get_exclusion_patterns() -> Set[re.Pattern]:
    """
    DEPRECATED: Get combined set of exclusion regex patterns.
    Kept for backward compatibility. Use get_exclusion_data() for better performance.
    
    This function now caches compiled patterns to avoid recompilation on every call.
    """
    global _LEGACY_PATTERNS_CACHE
    
    literals, regex_patterns = get_exclusion_data()
    
    # Create cache key from current state
    # Use frozenset of literals and tuple of pattern strings for stable hashing
    cache_key = (frozenset(literals), len(regex_patterns))
    
    # Return cached patterns if still valid
    if _LEGACY_PATTERNS_CACHE["patterns"] is not None and _LEGACY_PATTERNS_CACHE["cache_key"] == cache_key:
        return _LEGACY_PATTERNS_CACHE["patterns"]
    
    # Rebuild patterns
    all_patterns: Set[re.Pattern] = set()
    for lit in literals:
        all_patterns.add(re.compile(rf"^{re.escape(lit)}$", re.IGNORECASE))
    for pat in regex_patterns:
        all_patterns.add(pat)
    
    # Update cache
    _LEGACY_PATTERNS_CACHE["patterns"] = all_patterns
    _LEGACY_PATTERNS_CACHE["cache_key"] = cache_key
    
    return all_patterns


# Initialize on module load (backward compatibility)
EXCLUDED_PATTERNS = get_exclusion_patterns()

def get_system_prompt(context: Optional[str] = None) -> str:
    override_path = os.environ.get("MARCUT_SYSTEM_PROMPT_PATH")
    cache = _SYSTEM_PROMPT_CACHE
    if override_path and os.path.exists(override_path):
        try:
            mtime = os.path.getmtime(override_path)
        except OSError:
            mtime = None
        if cache["path"] != override_path or cache["mtime"] != mtime:
            try:
                with open(override_path, 'r', encoding='utf-8') as f:
                    cache["text"] = f.read()
                    cache["path"] = override_path
                    cache["mtime"] = mtime
            except Exception as e:
                print(f"Warning: Error loading custom system prompt: {e}", file=sys.stderr)
                cache["text"] = DEFAULT_EXTRACT_SYSTEM
                cache["path"] = None
                cache["mtime"] = None
        base_text = cache["text"]
    else:
        cache["text"] = DEFAULT_EXTRACT_SYSTEM
        cache["path"] = None
        cache["mtime"] = None
        base_text = DEFAULT_EXTRACT_SYSTEM

    if context:
        context_clean = context.strip()
        if context_clean:
            return f"{base_text.rstrip()}\n\n{context_clean}"

    return base_text


def build_extraction_prompt(text: str, context: Optional[str] = None) -> str:
    system_prompt = get_system_prompt(context)
    return f"""<|system|>
{system_prompt}<|end|>
<|user|>
Text:
{text}<|end|>
<|assistant|>
"""

def _is_generic_term(text: str) -> bool:
    """
    Check if text matches any excluded pattern.
    Optimized: O(1) set lookup for literals, then O(n) for regex patterns.
    """
    text_clean = _strip_leading_determiner(text)
    normalized = _normalize_for_exclusion(text)
    literals, patterns = get_exclusion_data()
    
    # Fast path: O(1) set lookup for the vast majority of exclusions
    if _matches_exclusion_literal(normalized, literals):
        return True
    
    # Slow path: check regex patterns (should be rare)
    for pattern in patterns:
        if pattern.match(text_clean):
            return True
    
    return False

def _smart_split_clean(text: str) -> Optional[str]:
    """
    Clean entity text by splitting on separators and removing excluded segments.
    Retains valid segments and their internal separators.
    Example: "FOR VALUE RECEIVED, Sample 123 Holdings, Inc." -> "Sample 123 Holdings, Inc."
    """
    # Split on comma, colon, semicolon, newline, capturing delimiters
    # We allow whitespace around delimiters
    tokens = re.split(r'(,\s*|:\s*|;\s*|\n)', text)
    
    sb = []
    last_valid_idx = -1
    
    for i in range(0, len(tokens), 2):
        seg_val = tokens[i]
        seg_clean = seg_val.strip()
        
        # Skip empty segments
        if not seg_clean: 
            continue
            
        # Check exclusion
        if not _is_generic_term(seg_clean):
            # If adjacent to previous valid token, keep the separator
            if last_valid_idx != -1 and i == last_valid_idx + 2:
                sb.append(tokens[i-1])
            elif last_valid_idx != -1:
                # Non-adjacent (we dropped something in between). 
                # For safety in legal contexts, we don't try to guess a joiner.
                # We interpret this as a disjoint entity or broken extraction.
                # However, usually we simply want the longest valid chain?
                # "Title: Name" -> "Name".
                # "Prefix, Valid, Suffix" -> "Valid".
                # "Valid1, Valid2" -> "Valid1, Valid2".
                pass
            
            sb.append(seg_val)
            last_valid_idx = i
            
    final_text = "".join(sb).strip()
    return final_text if final_text else None

def _valid_candidate(entity_text: str, label: str) -> bool:
    """Apply simple, robust shape rules to reduce noise before matching."""
    s = entity_text.strip()
    if not s:
        return False
    # Never allow obvious boilerplate
    if _is_generic_term(s) or (s.lower().startswith("the ") and _is_generic_term(s[4:].strip())):
        return False

    # Very short tokens are unsafe for NAME/ORG
    if label in ("NAME", "ORG"):
        toks = [t for t in re.split(r"\s+", s) if t]
        if len(toks) < 2:
            return False
        if label == "NAME":
            # Require most tokens to look like capitalized names
            cap_like = sum(1 for t in toks if re.match(r"^[A-Z][a-z'’.-]*$", t))
            if cap_like < max(2, len(toks) - 1):
                return False
        if label == "ORG":
            # Accept if contains a common designator or has at least two capitalized tokens
            if not re.search(r"\b(Inc\.?|LLC|L\.L\.C\.|Corp\.?|Corporation|Ltd\.?|Limited|LP|L\.P\.|LLP|L\.L\.P\.|Co\.?|Company|GmbH|AG|S\.A\.|B\.V\.|N\.V\.|PLC|Pty|KK|Holdings|Partners|Capital|Group|Management|Ventures|Bank|Trust|University)\b", s):
                cap_like = sum(1 for t in toks if re.match(r"^[A-Z][A-Za-z&'’.-]*$", t))
                if cap_like < 2:
                    return False
    return True


def _find_entity_spans(text: str, entity_text: str, label: str) -> List[Dict[str,Any]]:
    """Find all occurrences of entity_text in text and return as spans."""
    spans = []
    entity_text = entity_text.strip()

    # Basic validation
    if not _valid_candidate(entity_text, label):
        return spans

    # Use word-boundary matching when safe
    safe_for_word_boundary = re.match(r"^[A-Za-z0-9][A-Za-z0-9 '&.,-]*[A-Za-z0-9]$", entity_text) is not None
    if safe_for_word_boundary:
        pattern = re.compile(rf"\b{re.escape(entity_text)}\b")
        for m in pattern.finditer(text):
            spans.append({"start": m.start(), "end": m.end(), "label": label})
        if spans:
            return spans

        # Low-risk case-insensitive fallback for common LLM casing issues
        if label in ("NAME", "ORG", "BRAND"):
            tokens = re.findall(r"[A-Za-z0-9]+", entity_text)
            stopwords = {
                "may", "june", "july", "march", "april", "august", "september",
                "october", "november", "december", "monday", "tuesday",
                "wednesday", "thursday", "friday", "saturday", "sunday",
                "will", "shall", "must",
            }
            allow_ci = False
            if len(tokens) >= 2:
                allow_ci = True
            elif len(tokens) == 1:
                token = tokens[0]
                if len(token) >= 5 and token.lower() not in stopwords and entity_text.isupper():
                    allow_ci = True
            if allow_ci:
                pattern = re.compile(rf"\b{re.escape(entity_text)}\b", flags=re.IGNORECASE)
                for m in pattern.finditer(text):
                    spans.append({"start": m.start(), "end": m.end(), "label": label})
                return spans

    # Fallback to exact substring search
    start = 0
    while True:
        pos = text.find(entity_text, start)
        if pos == -1:
            break
        spans.append({"start": pos, "end": pos + len(entity_text), "label": label})
        start = pos + 1

    return spans

def ollama_extract(
    model: str,
    text: str,
    temperature: float = 0.0,
    seed: int = 42,
    context: Optional[str] = None
) -> List[Dict[str,Any]]:
    """
    Extract entities using Ollama with a single self-correction retry on malformed JSON.
    """
    base_url = get_ollama_base_url()

    def _request(prompt: str, format_value) -> str:
        resp = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": format_value,
                "stream": False,  # CRITICAL: Disable streaming to get single JSON response
                "options": {
                    "temperature": max(temperature, 0.1),
                    "seed": seed,
                    "num_ctx": 12288,
                    "num_predict": 4096,
                    "top_p": 0.9
                },
                },
            # Increase timeout to 7200s (120min) to handle large docs and initial Metal shader compilation
            timeout=7200
        )
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("response", "")

    def _schema_fallback_allowed(err: requests.exceptions.HTTPError) -> bool:
        resp = err.response
        if resp is None:
            return False
        if resp.status_code not in (400, 404, 415, 422):
            return False
        body = (resp.text or "").lower()
        return "format" in body or "schema" in body or "json schema" in body or "unsupported" in body

    base_prompt = build_extraction_prompt(text, context)

    schema_format = {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "type": {"type": "string"}
                    },
                    "required": ["text", "type"],
                    "additionalProperties": True
                }
            }
        },
        "required": ["entities"],
        "additionalProperties": True
    }

    try:
        response_text = _request(base_prompt, schema_format)
    except requests.exceptions.HTTPError as e:
        if _schema_fallback_allowed(e):
            status = f" status={e.response.status_code}" if e.response is not None else ""
            response_hint = ""
            if e.response is not None and e.response.text:
                response_hint = f" body={e.response.text[:200].strip()}"
            print("Warning: Ollama schema format unsupported. Falling back to JSON mode.", file=sys.stderr)
            _log_app_event(f"Ollama schema format unsupported{status}.{response_hint} Falling back to JSON mode.")
            response_text = _request(base_prompt, "json")
        else:
            raise RuntimeError(
                f"Ollama rejected the request at {base_url}. Ensure the Ollama service is running and the model is pulled."
            ) from e
    except (requests.exceptions.RequestException, requests.exceptions.ConnectionError) as e:
        raise RuntimeError(
            f"Ollama is not reachable at {base_url} or rejected the request. Ensure the Ollama service is running and the model is pulled."
        ) from e

    try:
        parsed = parse_llm_response(response_text)
    except json.JSONDecodeError as first_error:
        # Log the raw response for debugging - use _log_app_event so it appears in marcut.log
        _log_app_event(f"JSON parsing failed. Response ({len(response_text)} chars): {response_text[:500]}{'...[truncated]' if len(response_text) > 500 else ''}")
        _log_app_event("Attempting self-correction...")
        correction_prompt = f"""You are a JSON correction assistant. The previous response you provided was not valid JSON.
Original Task:
{get_system_prompt(context)}

Text to Analyze:
{text}

Your invalid response was:
---
{response_text}
---

Please correct your response. Return ONLY the valid JSON object that adheres to the schema. Do not include any other text or explanations.
"""
        corrected_text = _request(correction_prompt, "json")
        try:
            parsed = parse_llm_response(corrected_text)
        except json.JSONDecodeError as final_error:
            debug_msg = f"LLM response was not valid JSON after self-correction. Raw response: {corrected_text[:500]}"
            raise RuntimeError(debug_msg) from final_error
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
            
        # Use smart split to clean boilerplate
        cleaned_text = _smart_split_clean(entity_text)
        if not cleaned_text:
            continue
            
        spans = _find_entity_spans(text, cleaned_text, label)
        all_spans.extend(spans)

    seen = set()
    unique_spans = []
    for sp in sorted(all_spans, key=lambda x: (x["start"], x["end"])):
        key = (sp["start"], sp["end"], sp["label"])
        if key not in seen:
            seen.add(key)
            unique_spans.append(sp)

    return unique_spans
