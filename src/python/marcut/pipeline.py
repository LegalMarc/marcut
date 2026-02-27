import sys
import io
import datetime
from dataclasses import fields
import logging

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
# (Use try-except to avoid breaking environments where .buffer or reconfigure are unavailable)
try:
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    elif hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass
except Exception:
    pass

import json
import hashlib
import traceback
import warnings
import time
import os
from typing import List, Dict, Any, Tuple, Optional, Callable, TypedDict
from .docx_io import DocxMap, MetadataCleaningSettings
from .docx_revisions import accept_revisions_in_docx_bytes
from .chunker import make_chunks
from .rules import run_rules, _is_excluded_combo, _is_excluded, ADDRESS
from .model_enhanced import (
    LlamaCppRedactionPipeline,
    run_enhanced_model,
    apply_llm_overrides_to_rule_spans,
    DocumentContext,
    build_prompt_context,
)
from .cluster import ClusterTable
from .confidence import combine, low_conf
from .report import write_report
import regex as re  # For consistency pass boundaries

logger = logging.getLogger(__name__)

class Span(TypedDict, total=False):
    start: int
    end: int
    label: str
    text: str
    confidence: float
    source: str
    entity_id: str
    validated: bool
    validation_result: str
    needs_redaction: bool

def _rank(lbl: str) -> int:
    """Priority ranking for span overlap resolution. Higher rank = higher priority."""
    order = {
        "EMAIL": 3, "PHONE": 3, "SSN": 3, "CARD": 3, "ACCOUNT": 3, "SWIFT": 3, "URL": 3, "IP": 3, "DOCID": 3,
        "NAME": 2, "ORG": 2, "BRAND": 2, "LOC": 2,
        "MONEY": 1, "NUMBER": 1, "DATE": 1, "PERCENT": 1,
    }
    return order.get(lbl, 0)

def _merge_overlaps(spans: List[Dict[str,Any]], text: str) -> List[Dict[str,Any]]:
    """Merge overlapping spans, keeping the higher-priority or longer span."""
    if not spans:
        return []

    # Validate span data structures
    valid_spans = []
    for i, span in enumerate(spans):
        if not isinstance(span, dict):
            continue
        if not all(key in span for key in ["start", "end", "label"]):
            continue
        if not isinstance(span["start"], int) or not isinstance(span["end"], int):
            continue
        if span["start"] >= span["end"]:
            continue
        if not span["label"]:
            continue
        valid_spans.append(span)

    if not valid_spans:
        return []

    # Sort by start position primary, then priority descending, then length descending
    # This ensures that if multiple spans start at same spot, the "best" one is seen first
    valid_spans.sort(key=lambda s: (
        s["start"], 
        -_rank(s["label"]), 
        -(s["end"] - s["start"]),
        -s.get("confidence", 0)
    ))
    
    out: List[Dict[str,Any]] = []
    
    for sp in valid_spans:
        if not out:
            out.append(sp)
            continue
            
        last = out[-1]
        
        # Check for overlap
        if sp["start"] < last["end"]:
            # Intersection detected.
            # Determine which span is "better" to define the merged entity properties
            rank_last = _rank(last["label"])
            rank_curr = _rank(sp["label"])
            conf_last = last.get("confidence", 0.0)
            conf_curr = sp.get("confidence", 0.0)
            
            is_better = False
            if rank_curr > rank_last:
                is_better = True
            elif rank_curr == rank_last:
                if conf_curr > conf_last:
                    is_better = True
                elif conf_curr == conf_last:
                    # Tie-break: length
                    if (sp["end"] - sp["start"]) > (last["end"] - last["start"]):
                        is_better = True
            
            # UNION Logic: Extend the end coverage
            new_end = max(last["end"], sp["end"])
            last["end"] = new_end
            
            # If current span is "better", adopt its identity (label, id, confidence)
            if is_better:
                last["label"] = sp["label"]
                last["confidence"] = sp.get("confidence", 0.7)
                if "entity_id" in sp:
                    last["entity_id"] = sp["entity_id"]
                # Also adopt its source if present?
                if "source" in sp:
                    last["source"] = sp["source"]
            
            # Update text to cover thefull merged range
            if text:
                last["text"] = text[last["start"]:last["end"]]
                
        else:
            out.append(sp)
    
    return out

def _snap_to_boundaries(text: str, spans: List[Dict[str, Any]], debug: bool = False) -> List[Dict[str, Any]]:
    """Expand spans to encompass full tokens (snapping to whitespace/punctuation)."""
    out = []
    numeric_labels = {"PHONE", "ACCOUNT", "CARD", "SSN", "NUMBER", "IP"}
    
    def is_word_char(c: str) -> bool:
        return c.isalnum() or c in ("-", "'", "’", "_")
    
    def is_numeric_char(c: str) -> bool:
        return c.isdigit() or c in ("+", "-", "(", ")", ".", "/", ",")

    for sp in spans:
        s, e = sp["start"], sp["end"]
        label = sp.get("label")
        # original_text = sp.get("text", text[s:e])
        
        # Expand left
        # We greedily expand left if the previous char is a word char, 
        # BUT we must be careful not to cross separating punctuation like ", " or ". "
        # Basic strategy: Expand if alnum. If punctuation, check if it's connected to alnum?
        # Simpler: Expand while prev char is alnum. 
        # If prev char is hyphen/apostrophe, check if char BEFORE that is alnum?
        # Actually, existing logic only checked isalnum().
        # Fixed logic: Expand while prev char matches a broader word-token set.
        while s > 0 and (
            is_numeric_char(text[s-1]) if label in numeric_labels else is_word_char(text[s-1])
        ):
             # Boundary check: ensure we don't eat a trailing hyphen of previous word "Pre- determined"?
             # If text[s-1] is '-', check text[s-2]?
             # For now, just expand loosely to capture Co-Op.
             s -= 1
             
        # Expand right
        while e < len(text) and (
            is_numeric_char(text[e]) if label in numeric_labels else is_word_char(text[e])
        ):
             e += 1
             
        # Trim leading/trailing delimiters if we expanded too far (e.g. captured leading "-")
        # " -Word" -> "-Word". Valid? No.
        # Clean up edges
        while s < e and not text[s].isalnum():
            s += 1
        while e > s and not text[e-1].isalnum():
             # Exception: 's is valid suffix? "John's". ' is not alnum.
             # If we have "John's", e is after 's'. text[e-1] is 's'. alnum.
             # If we have "John-", text[e-1] is '-'.
             e -= 1
        
        if s != sp["start"] or e != sp["end"]:
            sp["start"] = s
            sp["end"] = e
            sp["text"] = text[s:e]
            
        out.append(sp)
    return out

MAX_SUFFIX_PADDING = 30

def _filter_overlong_org_spans(text: str, spans: List[Dict[str, Any]], max_len: int = 60) -> List[Dict[str, Any]]:
    """Drop ORG spans that are likely over-broad (very long or multi-line)."""
    if not spans:
        return spans

    # Permit short, suffix-anchored ORGs with a single line break (common in tables).
    # Use re.IGNORECASE flag rather than (?i) inside for cleaner multiline
    suffix_re = re.compile(
        r"(?:Incorporated|Corporation|Company|Limited|Inc\.?|Corp\.?|Co\.?|Ltd\.?|"
        r"Limited\s+Liability\s+Company|L\.L\.C\.|LLC|L\.C\.|LC|"
        r"Limited\s+Liability\s+Partnership|L\.L\.P\.|LLP|"
        r"Limited\s+Partnership|L\.P\.|LP|"
        r"General\s+Partnership|G\.P\.|GP|"
        r"Professional\s+Corporation|P\.C\.|PC|"
        r"Professional\s+Association|P\.A\.|PA|"
        r"Federal\s+Savings\s+Bank|FSB|"
        r"National\s+Association|N\.A\.|"
        r"National\s+Bank|Bank|"
        r"Trust\s+Company|"
        r"Capital|Holdings|Group|Fund|"
        r"Statutory\s+Trust|Business\s+Trust|REIT|Trust|"
        r"Foundation|Association|Society|Institute|"
        r"GmbH|AG|S\.A\.S\.|S\.A\.|S\.R\.L\.|Sp\.\s+z\s+o\.o\.|B\.V\.|N\.V\.|PLC|p\.l\.c\.)\s*$",
        re.IGNORECASE
    )
    suffix_max_len = max_len + MAX_SUFFIX_PADDING

    filtered: List[Dict[str, Any]] = []
    for sp in spans:
        if not isinstance(sp, dict):
            continue
        if sp.get("label") != "ORG":
            filtered.append(sp)
            continue

        span_text = sp.get("text")
        if span_text is None:
            try:
                span_text = text[sp["start"]:sp["end"]]
            except Exception:
                span_text = ""

        normalized = span_text.replace("\r", "\n")
        line_breaks = normalized.count("\n")
        has_suffix = suffix_re.search(normalized.strip()) is not None

        if len(span_text) > max_len:
            if has_suffix and line_breaks <= 1 and len(normalized) <= suffix_max_len:
                filtered.append(sp)
            continue
        if line_breaks > 0:
            if line_breaks <= 1 and has_suffix:
                filtered.append(sp)
                continue
            continue
        filtered.append(sp)

    return filtered


_ORG_SUFFIX_TRAIL_RE = re.compile(
    r"^[\s,]+"
    r"(?P<suffix>"
    r"(?:inc\.?|corp\.?|co\.?|ltd\.?|llc|l\.l\.c\.|llp|l\.l\.p\.|lp|l\.p\.|"
    r"pllc|plc|p\.l\.c\.|gmbh|ag|s\.a\.?|b\.v\.?|n\.v\.?)"
    r")"
    r"[\s\.]*" # Allow trailing whitespace or period
    r"(?=$|[\s,;:\)\]\}])", # Lookahead for end or separator
    re.IGNORECASE,
)


_DEFINED_TERM_PATTERN = re.compile(
    r"^\s*(?:,)?\s*\(\s*(?:(?:the|a|an)\s+)?(?P<alias>[^)]+?)\s*\)",
    re.IGNORECASE,
)
# Fixed: allow internal hyphens/apostrophes in tokens
_DEFINED_TERM_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019\-][A-Za-z0-9]+)*")
_DEFINED_TERM_QUOTES = "\"'“”‘’"
_DEFINED_TERM_STOP_WORDS = {"and", "of", "the", "for", "a", "an", "&"}
_DEFINED_TERM_ORG_SUFFIXES = {
    "inc", "inc.", "llc", "l.l.c.", "corp", "corp.", "co", "co.", "ltd", "ltd.",
    "lp", "l.p.", "llp", "l.l.p.", "pllc", "gmbh", "sa", "s.a", "s.a.", "bv",
    "b.v", "b.v.", "nv", "n.v", "plc", "p.l.c", "p.l.c.",
}


def _trim_defined_term_alias_span(text: str, start: int, end: int) -> Optional[Tuple[int, int]]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1

    while start < end and text[start] in _DEFINED_TERM_QUOTES:
        start += 1
    while end > start and text[end - 1] in _DEFINED_TERM_QUOTES:
        end -= 1

    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1

    alias = text[start:end]
    alias_lower = alias.lower()
    for prefix in ("the ", "a ", "an "):
        if alias_lower.startswith(prefix):
            start += len(prefix)
            break

    while start < end and text[start].isspace():
        start += 1
    if start >= end:
        return None
    return (start, end)


def _tokenize_defined_term(text: str) -> List[str]:
    return _DEFINED_TERM_TOKEN_RE.findall(text or "")


def _build_org_acronym(tokens: List[str]) -> str:
    letters: List[str] = []
    for token in tokens:
        norm = token.lower().rstrip(".")
        if not norm:
             continue
        if norm in _DEFINED_TERM_STOP_WORDS:
            # Exception: "A" as in "A Corp" (Capitalized) should be kept
            if norm == "a" and token[0].isupper():
                pass
            else:
                continue
        if norm in _DEFINED_TERM_ORG_SUFFIXES:
            continue
        letters.append(norm[0].upper())
    return "".join(letters)


def _defined_term_matches_entity(alias_text: str, entity_text: str, label: str) -> bool:
    if not alias_text or not entity_text:
        return False
    alias_text = alias_text.replace("’", "'").replace("‘", "'")
    entity_text = entity_text.replace("’", "'").replace("‘", "'")
    alias_text = re.sub(r"'s\b", "", alias_text)
    entity_text = re.sub(r"'s\b", "", entity_text)
    alias_tokens = _tokenize_defined_term(alias_text)
    entity_tokens = _tokenize_defined_term(entity_text)
    if not alias_tokens or not entity_tokens:
        return False

    alias_norm = [t.lower().rstrip(".") for t in alias_tokens]
    entity_norm = [t.lower().rstrip(".") for t in entity_tokens]
    has_long_token = any(len(t) >= 2 for t in alias_norm)

    if label == "NAME":
        if not has_long_token:
            return False
        for token in alias_norm:
            if len(token) == 1:
                if not any(ent.startswith(token) for ent in entity_norm):
                    return False
            elif token not in entity_norm:
                return False
        return True

    if label == "ORG":
        alias_acronym = re.sub(r"[^A-Z]", "", alias_text.upper())
        if 2 <= len(alias_acronym) <= 6:
            entity_acronym = _build_org_acronym(entity_tokens)
            if alias_acronym and alias_acronym == entity_acronym:
                return True

        if not has_long_token:
            return False
        for token in alias_norm:
            if token not in entity_norm:
                return False
        return True

    return False


def _attach_defined_term_aliases(
    text: str,
    spans: List[Dict[str, Any]],
    lookahead: int = 120,
) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    out = list(spans)
    existing = {(sp.get("start"), sp.get("end"), sp.get("label")) for sp in spans}

    for sp in spans:
        label = sp.get("label")
        if label not in {"NAME", "ORG"}:
            continue
        start = sp.get("start")
        end = sp.get("end")
        if start is None or end is None or end >= len(text):
            continue

        window = text[end:min(len(text), end + lookahead)]
        match = _DEFINED_TERM_PATTERN.match(window)
        if not match:
            continue

        alias_start = end + match.start("alias")
        alias_end = end + match.end("alias")
        trimmed = _trim_defined_term_alias_span(text, alias_start, alias_end)
        if not trimmed:
            continue
        alias_start, alias_end = trimmed

        alias_text = text[alias_start:alias_end]
        if not alias_text or "\n" in alias_text or "\r" in alias_text:
            continue
        if len(alias_text) > 60:
            continue
        if _is_excluded(alias_text):
            continue
        alias_text = alias_text.replace("’", "'").replace("‘", "'")
        if not _defined_term_matches_entity(alias_text, sp.get("text", ""), label):
            continue

        key = (alias_start, alias_end, label)
        if key in existing:
            continue
        if any(alias_start < other.get("end", 0) and alias_end > other.get("start", 0) for other in spans):
            continue

        out.append({
            "start": alias_start,
            "end": alias_end,
            "label": label,
            "confidence": sp.get("confidence", 0.7),
            "source": "defined_term",
            "text": alias_text,
        })
        existing.add(key)

    return out

def _apply_consistency_pass(
    text: str,
    spans: List[Dict[str, Any]],
    debug: bool = False,
    exclude_if: Optional[Callable[[str, str], bool]] = None,
) -> List[Dict[str, Any]]:
    """
    Consistency Pass: Rescan document for exact matches of found entities.
    Optimized to use batched regex scanning instead of O(N) linear scans.
    """
    if not spans:
        return spans

    def _normalize_org_text(value: str) -> str:
        cleaned = re.sub(r"[’']s\b", "", value)
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.lower()

    def _org_tokens(value: str) -> List[str]:
        return [tok for tok in re.findall(r"[A-Za-z0-9]+", value) if len(tok) >= 2]

    # 1. Collect Candidates
    SAFE_LABELS = {"ORG", "PERSON", "NAME", "EMAIL", "SSN", "PHONE", "ACCOUNT", "CARD", "BRAND"}
    STOP_WORDS = {
        "the", "and", "for", "with", "from", "that", "this", "inc", "llc", "corp", 
        "ltd", "company", "mr", "mrs", "ms", "dr", "esq", "dept"
    } 
    
    # Store candidates: Map text -> Label
    # If same text maps to multiple labels, priority should handle it, or we just pick one?
    # Better: Map text -> List[Label] and emit spans for each? Or just emit highest priority?
    case_sensitive_map: Dict[str, str] = {}
    case_insensitive_map: Dict[str, str] = {}
    
    # Also keep full candidate objects for strict checks or fuzzy scan
    all_candidates: List[Dict[str, Any]] = []
    seen_candidate_keys = set()

    for sp in spans:
        lbl = sp["label"]
        txt = sp["text"].strip()
        
        if lbl not in SAFE_LABELS:
            continue
        
        if len(txt) < 4:
            continue 
        if txt.lower() in STOP_WORDS:
            continue
        if not any(c.isalnum() for c in txt):
            continue
        
        if exclude_if and exclude_if(txt, lbl):
            continue

        key = (lbl, txt)
        if key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        
        cand = {
            "text": txt,
            "label": lbl,
            "norm": _normalize_org_text(txt) if lbl == "ORG" else None,
            "tokens": _org_tokens(txt) if lbl == "ORG" else None,
        }
        all_candidates.append(cand)
        
        if lbl == "ORG":
            # For ORG, we scan case-insensitive
            # We strip singular 's for matching base form 
            base = re.sub(r"[’']s$", "", txt)
            if base not in case_insensitive_map:
                case_insensitive_map[base.lower()] = lbl
                # Also candidate text itself
                case_insensitive_map[txt.lower()] = lbl
        else:
            if txt not in case_sensitive_map:
                case_sensitive_map[txt] = lbl

    if not all_candidates:
        return spans

    new_spans = []
    existing_keys = {(sp.get("start"), sp.get("end"), sp.get("label")) for sp in spans}
    existing_spans = [
        (sp.get("start"), sp.get("end"), sp.get("label"), sp.get("text", "") or "")
        for sp in spans
        if sp.get("start") is not None and sp.get("end") is not None and sp.get("label")
    ]
    new_keys: set[tuple[int, int, str]] = set()

    def _overlaps_existing(s: int, e: int, label: str, matched_text: str) -> bool:
        if not matched_text:
            return False
        if label == "ORG":
            target_norm = _normalize_org_text(matched_text)
        else:
            target_norm = matched_text.strip().lower()
        for es, ee, el, etext in existing_spans:
            if el != label:
                continue
            if not (s < ee and e > es):
                continue
            if label == "ORG":
                existing_norm = _normalize_org_text(etext)
            else:
                existing_norm = etext.strip().lower()
            if target_norm and existing_norm and target_norm == existing_norm:
                return True
        return False

    # 2. Batched Rescan (Exact Matches)
    
    # Build regex for case-sensitive
    if case_sensitive_map:
        # Sort by length descending to match longest first
        patterns = sorted(case_sensitive_map.keys(), key=len, reverse=True)
        # Escape and join
        pattern_str = r"\b(?:" + "|".join(re.escape(p) for p in patterns) + r")\b"
        try:
            for match in re.finditer(pattern_str, text):
                matched_text = match.group(0)
                label = case_sensitive_map.get(matched_text)
                if not label: continue
                
                s, e = match.span()
                if _overlaps_existing(s, e, label, matched_text):
                    continue
                key = (s, e, label)
                if key in existing_keys or key in new_keys: continue
                
                new_spans.append({
                    "start": s, "end": e, "label": label, "text": matched_text,
                    "confidence": 0.95, "source": "consistency_pass"
                })
                new_keys.add(key)
        except Exception as e:
            if debug: print(f"Consistency Pass Error (CS): {e}")

    # Build regex for case-insensitive (ORGs)
    if case_insensitive_map:
        patterns = sorted(case_insensitive_map.keys(), key=len, reverse=True)
        pattern_str = r"\b(?:" + "|".join(re.escape(p) for p in patterns) + r")\b"
        try:
            for match in re.finditer(pattern_str, text, flags=re.IGNORECASE):
                matched_text = match.group(0)
                # Lookup by lowercase
                label = case_insensitive_map.get(matched_text.lower())
                if not label: continue
                
                s, e = match.span()
                if _overlaps_existing(s, e, label, matched_text):
                    continue
                key = (s, e, label)
                if key in existing_keys or key in new_keys: continue
                
                new_spans.append({
                    "start": s, "end": e, "label": label, "text": matched_text,
                    "confidence": 0.95, "source": "consistency_pass_ci"
                })
                new_keys.add(key)
        except Exception as e:
             if debug: print(f"Consistency Pass Error (CI): {e}")

    # 3. Fuzzy Scan for ORGs (Per-candidate, expensive but necessary for complex forms)
    # Only iterate ORG candidates
    for cand in all_candidates:
        if cand["label"] != "ORG":
            continue
        
        norm_tokens = cand.get("tokens") or []
        if len(norm_tokens) < 2:
            continue
            
        cand_text = cand["text"]
        label = "ORG"
        
        gap = r"[ \t\r\n\u00A0,.;:'\"/\-]{0,10}"
        fuzzy_pattern = r"\b" + gap.join(re.escape(tok) for tok in norm_tokens) + r"\b"
        
        try:
            for match in re.finditer(fuzzy_pattern, text, flags=re.IGNORECASE):
                s, e = match.span()
                if exclude_if and exclude_if(cand_text, label): continue
                if s > 0 and text[s - 1].isalnum(): continue
                if e < len(text) and text[e:e+1].isalnum(): continue
                if _overlaps_existing(s, e, label, text[s:e]): continue
                
                key = (s, e, label)
                if key in existing_keys or key in new_keys: continue
                
                # Length check
                if (e - s) < max(4, len("".join(norm_tokens)) - 1): continue
                
                new_spans.append({
                    "start": s, "end": e, "label": label, "text": text[s:e],
                    "confidence": 0.93, "source": "consistency_pass_fuzzy"
                })
                new_keys.add(key)
        except Exception:
            continue

    if debug:
        print(f"Consistency Pass: Generated {len(new_spans)} new spans.")

    return spans + new_spans


def _filter_excluded_combo_spans(
    text: str,
    spans: List[Dict[str, Any]],
    suppressed: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    filtered: List[Dict[str, Any]] = []
    for sp in spans:
        label = sp.get("label")
        if label in ("ORG", "NAME", "LOC"):
            span_text = sp.get("text")
            if span_text is None and "start" in sp and "end" in sp:
                try:
                    span_text = text[sp["start"]:sp["end"]]
                except Exception:
                    span_text = ""
            if span_text and _is_excluded_combo(span_text):
                if suppressed is not None:
                    suppressed.append({
                        "reason": "excluded_combo",
                        "label": label,
                        "text": span_text,
                        "start": sp.get("start"),
                        "end": sp.get("end"),
                        "source": sp.get("source", "unknown"),
                    })
                continue
        filtered.append(sp)
    return filtered


def _exclude_combo_for_pass(text: str, label: str) -> bool:
    del label
    return _is_excluded_combo(text)

def _find_last_top_level_separator(text: str) -> Optional[int]:
    """Find the last separator in text that isn't nested in parentheses."""
    depth = 0
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == ")":
            depth += 1
            continue
        if ch == "(":
            if depth > 0:
                depth -= 1
            continue
        if depth != 0:
            continue
        # Separators: comma, semicolon, colon
        # Added: Forward slash (e.g. "Name/Title")
        # Added: Period? No, period is risky if it's "Inc."
        if ch in {",", ";", ":", "/"}:
            return i
        if ch in {"\u2013", "\u2014"}: # dashes
            return i
        if ch == "-" and i > 0 and i + 1 < len(text):
            # Only treat hyphen as separator if surrounded by spaces " - "
            if text[i - 1].isspace() and text[i + 1].isspace():
                return i
    return None

def _trim_trailing_parenthetical(segment: str) -> str:
    """Trim ONE trailing parenthetical block if it contains excluded words."""
    stripped = segment.rstrip()
    if not stripped.endswith(")"):
        return segment
    
    # improved scan for matching '('
    depth = 0
    open_idx = -1
    for i in range(len(stripped) - 1, -1, -1):
        if stripped[i] == ")":
            depth += 1
        elif stripped[i] == "(":
            depth -= 1
            if depth == 0:
                open_idx = i
                break
                
    if open_idx == -1:
        return segment
        
    inner = stripped[open_idx + 1 : -1].strip()
    if not inner:
        # Empty parens? Treat as excluded/junk
        return stripped[:open_idx].rstrip()
        
    if _is_excluded_combo(inner):
        return stripped[:open_idx].rstrip()
    
    return segment

def _trim_trailing_delimited_segment(segment: str) -> str:
    """Trim trailing segment separated by delimiters if excluded."""
    stripped = segment.rstrip()
    if not stripped:
        return segment
    sep_idx = _find_last_top_level_separator(stripped)
    if sep_idx is None:
        return segment
    trailing = stripped[sep_idx + 1 :].strip()
    # Check if trailing part is excluded
    if trailing and _is_excluded_combo(trailing):
        # Also check if it looks like a suffix?
        # If "Company, Inc.", "Inc." is excluded combo? Maybe.
        # But _is_excluded_combo checks for things like "Borrower", "Lender".
        return stripped[:sep_idx].rstrip()
    return segment

def _trim_org_trailing_excluded_segments(
    text: str,
    spans: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    trimmed: List[Dict[str, Any]] = []
    for sp in spans:
        if sp.get("label") != "ORG":
            trimmed.append(sp)
            continue

        start = sp.get("start")
        end = sp.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            trimmed.append(sp)
            continue
        if start < 0 or end <= start or end > len(text):
            trimmed.append(sp)
            continue

        span_text = text[start:end]
        candidate = span_text.rstrip()
        if not candidate:
            trimmed.append(sp)
            continue

        while True:
            before = candidate
            candidate = _trim_trailing_parenthetical(candidate)
            candidate = _trim_trailing_delimited_segment(candidate)
            if candidate == before:
                break

        if not candidate or candidate == span_text:
            trimmed.append(sp)
            continue

        new_end = start + len(candidate)
        if new_end <= start:
            trimmed.append(sp)
            continue

        updated = dict(sp)
        updated["end"] = new_end
        updated["text"] = candidate
        trimmed.append(updated)

    return trimmed


def _trim_org_jurisdiction_suffixes(
    text: str,
    spans: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    try:
        from .rules import _trim_org_jurisdiction_suffix
    except Exception:
        return spans

    trimmed: List[Dict[str, Any]] = []
    for sp in spans:
        if sp.get("label") != "ORG":
            trimmed.append(sp)
            continue

        start = sp.get("start")
        end = sp.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            trimmed.append(sp)
            continue
        if start < 0 or end <= start or end > len(text):
            trimmed.append(sp)
            continue

        span_text = text[start:end]
        candidate = _trim_org_jurisdiction_suffix(span_text)
        if candidate == span_text:
            trimmed.append(sp)
            continue
        if not candidate:
            continue

        new_end = start + len(candidate)
        if new_end <= start:
            continue

        updated = dict(sp)
        updated["end"] = new_end
        updated["text"] = candidate
        trimmed.append(updated)

    return trimmed


def _extend_org_suffixes(text: str, spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    extended: List[Dict[str, Any]] = []
    for sp in spans:
        if sp.get("label") != "ORG":
            extended.append(sp)
            continue

        start = sp.get("start")
        end = sp.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            extended.append(sp)
            continue
        if start < 0 or end <= start or end > len(text):
            extended.append(sp)
            continue

        tail = text[end:]
        match = _ORG_SUFFIX_TRAIL_RE.match(tail)
        if not match:
            extended.append(sp)
            continue

        new_end = end + match.end()
        if new_end <= end:
            extended.append(sp)
            continue

        updated = dict(sp)
        updated["end"] = new_end
        updated["text"] = text[start:new_end]
        extended.append(updated)

    return extended


def _extend_loc_to_line(text: str, spans: List[Dict[str, Any]], max_line_len: int = 240) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    org_spans: List[tuple[int, int]] = []
    for sp in spans:
        if sp.get("label") != "ORG":
            continue
        start = sp.get("start")
        end = sp.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
            org_spans.append((start, end))

    extended: List[Dict[str, Any]] = []
    for sp in spans:
        if sp.get("label") != "LOC":
            extended.append(sp)
            continue

        start = sp.get("start")
        end = sp.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            extended.append(sp)
            continue
        if start < 0 or end <= start or end > len(text):
            extended.append(sp)
            continue

        line_start = text.rfind("\n", 0, start)
        if line_start == -1:
            line_start = 0
        else:
            line_start += 1
        line_end = text.find("\n", end)
        if line_end == -1:
            line_end = len(text)
        if line_end <= line_start:
            extended.append(sp)
            continue

        line = text[line_start:line_end]
        if not line.strip():
            extended.append(sp)
            continue

        rel_start = start - line_start
        rel_end = end - line_start
        matches = [m for m in ADDRESS.finditer(line) if m.start() <= rel_end and m.end() >= rel_start]
        if not matches:
            extended.append(sp)
            continue

        if org_spans:
            org_on_line_outside_loc = any(
                org_end > line_start
                and org_start < line_end
                and (org_start < start or org_end > end)
                for org_start, org_end in org_spans
            )
            if org_on_line_outside_loc:
                extended.append(sp)
                continue

        line_len = len(line)
        best_match = max(matches, key=lambda m: (m.end() - m.start()))
        coverage = (best_match.end() - best_match.start()) / max(line_len, 1)
        
        # Determine dominance, but cap at max_line_len to prevent huge redactions
        dominant = coverage >= 0.6
        if line_len > max_line_len:
            dominant = False

        updated = dict(sp)
        if dominant:
            # Only promote to full line when the address dominates the line
            updated["start"] = line_start
            updated["end"] = line_end
            updated["text"] = line
        else:
            # Otherwise constrain to the detected address segment to avoid over-redaction
            updated["start"] = line_start + best_match.start()
            updated["end"] = line_start + best_match.end()
            updated["text"] = text[updated["start"]:updated["end"]]
            # Mark source as extended
            updated["source"] = "rule_extended_address"
            
        extended.append(updated)

    return extended

def _filter_county_spans(text: str, spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not spans:
        return spans

    generic_determiners = {
        "the", "this", "that", "such", "any", "each", "aforementioned",
        "foregoing", "said", "a", "an",
    }
    county_keywords = {"county", "parish", "borough"}
    banned_trailing = {"court", "clerk", "jail", "probation", "board", "commission", "department", "office"}

    filtered: List[Dict[str, Any]] = []
    for sp in spans:
        label = sp.get("label")
        if label not in {"ORG", "LOC"}:
            filtered.append(sp)
            continue

        span_text = sp.get("text")
        if span_text is None:
            try:
                span_text = text[sp["start"]:sp["end"]]
            except Exception:
                span_text = ""

        cleaned = span_text.strip()
        if not cleaned:
            filtered.append(sp)
            continue

        if len(cleaned) > 80:
            filtered.append(sp)
            continue

        lower_clean = cleaned.lower()
        if not any(k in lower_clean for k in ("county", "parish", "borough")):
            filtered.append(sp)
            continue

        if any(ch.isdigit() for ch in cleaned):
            filtered.append(sp)
            continue

        tokens = re.findall(r"[A-Za-z'\u2019-]+", cleaned)
        if not tokens:
            filtered.append(sp)
            continue

        # Drop generic defined-term style mentions with no proper name
        proper_tokens = [
            t for t in tokens
            if t.lower() not in county_keywords
            and t.lower() not in generic_determiners
            and t.lower() != "of"
        ]
        if not proper_tokens:
            continue

        # Safety net: if trailing token is an office/facility term and the span starts with a county keyword, treat as generic
        if tokens[-1].lower() in banned_trailing and tokens[0].lower() in county_keywords:
            continue

        filtered.append(sp)

    return filtered

def _build_report_settings(
    *,
    mode: str,
    mode_requested: str,
    backend: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    llm_skip_confidence: float,
) -> Dict[str, Any]:
    settings = {
        "mode": mode,
        "mode_requested": mode_requested,
        "backend": backend,
        "model": model_id,
        "chunk_tokens": chunk_tokens,
        "overlap": overlap,
        "temperature": temperature,
        "seed": seed,
        "llm_skip_confidence": llm_skip_confidence,
        "llm_skip_confidence_percent": int(round(llm_skip_confidence * 100)),
    }

    advanced_enabled = os.environ.get("MARCUT_ADVANCED_MODE_ENABLED")
    if advanced_enabled is not None:
        settings["advanced_mode_enabled"] = advanced_enabled.strip().lower() in {"1", "true", "yes", "on"}
    advanced_mode = os.environ.get("MARCUT_ADVANCED_AI_MODE")
    if advanced_mode:
        settings["advanced_ai_mode"] = advanced_mode
    advanced_confidence = os.environ.get("MARCUT_ADVANCED_CONFIDENCE")
    if advanced_confidence:
        try:
            settings["advanced_confidence_percent"] = int(advanced_confidence)
        except ValueError:
            settings["advanced_confidence_percent"] = advanced_confidence

    try:
        from .rules import RULES, SIGNATURE_RULE_LABEL, _selected_rule_labels, _rule_enabled
    except Exception:
        return settings

    selected = _selected_rule_labels()
    settings["rule_filter"] = "all" if selected is None else sorted(selected)

    rules_snapshot = []
    for label, _, conf, _ in RULES:
        rules_snapshot.append({
            "label": label,
            "confidence": conf,
            "enabled": _rule_enabled(label, selected),
        })
    rules_snapshot.append({
        "label": SIGNATURE_RULE_LABEL,
        "confidence": 0.95,
        "enabled": _rule_enabled(SIGNATURE_RULE_LABEL, selected),
    })
    settings["rules"] = rules_snapshot
    return settings


def _finalize_and_write(
    dm: DocxMap,
    text: str,
    spans: List[Dict[str,Any]],
    output_path: str,
    report_path: str,
    input_path: str,
    model_info: str,
    report_settings: Optional[Dict[str, Any]] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    suppressed: Optional[List[Dict[str, Any]]] = None,
    debug: bool = False,
) -> int:
    """Apply redactions with track changes and generate audit report."""
    if warnings is None:
        warnings = []
    if suppressed is None:
        suppressed = []
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
            "low_confidence": low_conf(sp.get("confidence", 0.7)),
            "label": sp.get("label")
        })
    
    # Apply track changes and save
    dm.apply_replacements(replacements, track_changes=True)
    warnings.extend(getattr(dm, "warnings", []) or [])
    
    # Parse metadata cleaning settings from environment (set by Swift UI)
    metadata_args_str = os.environ.get("MARCUT_METADATA_ARGS", "")
    metadata_args = metadata_args_str.split() if metadata_args_str else []
    metadata_settings = MetadataCleaningSettings.from_environment(metadata_args)
    scrub_report_path = os.environ.get("MARCUT_SCRUB_REPORT_PATH", "").strip() or None
    is_none_preset = "--preset-none" in metadata_args or "--preset-none" in metadata_args_str
    if is_none_preset:
        scrub_report_path = None
    elif not scrub_report_path:
        scrub_report_path = _default_scrub_report_path(report_path, output_path)
    scrub_before_values = None
    scrub_input_file_info = None
    if scrub_report_path:
        scrub_input_file_info = _safe_report_file_info(input_path)
        try:
            dm_before = DocxMap.load(input_path)
            scrub_before_values = _read_metadata_values(dm_before)
        except Exception:
            scrub_before_values = _read_metadata_values(dm)
    
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

    redaction_changes_created = bool(replacements)
    if metadata_settings.clean_track_changes and not redaction_changes_created:
        try:
            cleaned_bytes, changed = accept_revisions_in_docx_bytes(output_path, debug=debug)
            if changed and cleaned_bytes:
                with open(output_path, "wb") as fh:
                    fh.write(cleaned_bytes)
                warnings.append({
                    "code": "TRACK_CHANGES_REMOVED",
                    "message": "Track changes were accepted and removed per settings."
                })
        except Exception as e:
            warnings.append({
                "code": "TRACK_CHANGES_REMOVE_FAILED",
                "message": "Unable to remove track changes after redaction.",
                "details": str(e)
            })
    if scrub_report_path and scrub_before_values is not None:
        try:
            try:
                dm_after = DocxMap.load(output_path)
                scrub_after_values = _read_metadata_values(dm_after)
            except Exception:
                scrub_after_values = _read_metadata_values(dm)

            report = _build_scrub_report(
                scrub_before_values,
                scrub_after_values,
                metadata_settings,
                file_path=output_path,
                input_path=input_path,
                input_file_info=scrub_input_file_info,
                report_dir=os.path.dirname(scrub_report_path),
                warnings=warnings,
            )
            report_dir = os.path.dirname(scrub_report_path)
            if report_dir:
                os.makedirs(report_dir, exist_ok=True)
            with open(scrub_report_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
            
            # Generate HTML report alongside JSON
            try:
                from .report_html import generate_report_from_json_file
                html_report_path = generate_report_from_json_file(scrub_report_path)
                if not html_report_path or not os.path.exists(html_report_path):
                    raise RuntimeError("HTML report generation did not produce a file")
            except Exception as html_err:
                report.setdefault("warnings", []).append({
                    "code": "SCRUB_REPORT_HTML_FAILED",
                    "message": "Scrub report HTML generation failed.",
                    "details": str(html_err)
                })
                warnings.append({
                    "code": "SCRUB_REPORT_HTML_FAILED",
                    "message": "Scrub report HTML generation failed.",
                    "details": str(html_err)
                })
                try:
                    with open(scrub_report_path, "w", encoding="utf-8") as fh:
                        json.dump(report, fh, indent=2)
                except Exception:
                    pass
        except Exception as e:
            warnings.append({
                "code": "SCRUB_REPORT_WRITE_FAILED",
                "message": "Scrub report could not be written.",
                "details": str(e)
            })
            if debug:
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
    
    try:
        write_report(
            report_path,
            input_path,
            model_info,
            audit,
            settings=report_settings,
            warnings=warnings,
            suppressed=suppressed,
        )
    except Exception as e:
        raise RedactionError(
            message="Failed to write audit report",
            error_code="REPORT_SAVE_FAILED",
            technical_details=f"Report path: {report_path}, Error: {str(e)}",
            original_error=e
        )
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


def _collect_enhanced_spans(
    text: str,
    model_id: str,
    chunk_tokens: int,
    overlap: int,
    temperature: float,
    seed: int,
    llm_skip_confidence: float,
    debug: bool,
    progress_callback=None,
    warnings: Optional[List[Dict[str, Any]]] = None,
    suppressed: Optional[List[Dict[str, Any]]] = None,
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
            skip_confidence=llm_skip_confidence,
            progress_callback=progress_callback,
            warnings=warnings,
            suppressed=suppressed,
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
    details = str(error.technical_details or "")
    for sensitive_path in (input_path, report_path):
        if sensitive_path:
            details = details.replace(sensitive_path, "<redacted-path>")
    details = re.sub(r"/Users/[^/\s]+", "/Users/<redacted>", details)
    details = re.sub(r"[A-Za-z]:\\\\[^\s]+", "<redacted-path>", details)
    details = re.sub(r"\\\\\\\\[^\s]+", "<redacted-path>", details)

    payload = {
        "status": "error",
        "input_file": os.path.basename(input_path) if input_path else "",
        "error_code": error.error_code,
        "message": str(error),
        "technical_details": details,
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
    llm_skip_confidence: float = 0.95,
) -> Tuple[int, Dict[str, float]]:
    """
    Unified pipeline entry point. Dispatches between rule-only and Rules + AI
    modes based on the supplied mode value.
    """
    rules_only_modes = {"rules", "strict", "rules_only"}
    llm_modes = {"rules_override", "constrained_overrides", "llm_overrides"}
    try:
        del do_qa  # parameter kept for API compatibility
        
        # Initialize timing collection
        phase_timings: Dict[str, float] = {}
        warnings: List[Dict[str, Any]] = []
        suppressed: List[Dict[str, Any]] = []
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

        mode_requested = mode or ""
        normalized_mode = mode_requested.strip().lower()
        if not normalized_mode:
            normalized_mode = "rules_override"
        normalized_mode = normalized_mode.replace("-", "_").replace(" ", "_")
        mode_aliases = {
            "enhanced": "rules_override",
            "enhanced_ai": "rules_override",
            "llm": "rules_override",
        }
        normalized_mode = mode_aliases.get(normalized_mode, normalized_mode)

        def _normalize_confidence(value: float, fallback: float = 0.95) -> float:
            try:
                val = float(value)
            except (TypeError, ValueError):
                return fallback
            if val > 1.0:
                val = val / 100.0
            return max(0.0, min(1.0, val))

        llm_skip_confidence = _normalize_confidence(llm_skip_confidence)
        allowed_modes = rules_only_modes | llm_modes
        if normalized_mode not in allowed_modes:
            raise RedactionError(
                message=f"Unsupported mode '{mode_requested or normalized_mode}'",
                error_code="INVALID_MODE",
                technical_details=f"Mode must be one of: {sorted(allowed_modes)}",
            )
        guardrailed_modes = rules_only_modes | {"rules_override", "constrained_overrides"}
        guardrailed_mode = normalized_mode in guardrailed_modes
        report_settings = _build_report_settings(
            mode=normalized_mode,
            mode_requested=mode_requested.strip(),
            backend=backend,
            model_id=model_id or "rules",
            chunk_tokens=chunk_tokens,
            overlap=overlap,
            temperature=temperature,
            seed=seed,
            llm_skip_confidence=llm_skip_confidence,
        )

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

        if guardrailed_mode:
            rule_spans = _filter_excluded_combo_spans(text, rule_spans, suppressed)

        if normalized_mode in rules_only_modes:
            with timed("POST_PROCESS"):
                rule_spans = _snap_to_boundaries(text, rule_spans, debug=debug)
                rule_spans = _trim_org_trailing_excluded_segments(text, rule_spans)
                rule_spans = _extend_org_suffixes(text, rule_spans)
                rule_spans = _attach_defined_term_aliases(text, rule_spans)
                # Apply Consistency Pass (Rules Only)
                rule_spans = _apply_consistency_pass(
                    text,
                    rule_spans,
                    debug=debug,
                    exclude_if=_exclude_combo_for_pass if guardrailed_mode else None,
                )
                rule_spans = _trim_org_jurisdiction_suffixes(text, rule_spans)
                rule_spans = _extend_loc_to_line(text, rule_spans)
                rule_spans = _filter_overlong_org_spans(text, rule_spans)
                rule_spans = _filter_county_spans(text, rule_spans)
                merged = _merge_overlaps(rule_spans, text)
                # Re-filter after merge to catch overlong spans created by union merging
                merged = _filter_overlong_org_spans(text, merged)
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
                        report_settings=report_settings,
                        warnings=warnings,
                        suppressed=suppressed,
                        debug=debug
                    )
                return (result, phase_timings)
            except RedactionError:
                raise
            except Exception as e:
                raise RedactionError(
                    message="Failed to save redacted document in rules-only mode",
                    error_code="OUTPUT_SAVE_FAILED",
                    technical_details=f"Output path: {output_path}, Error: {str(e)}",
                    original_error=e
                )

        if normalized_mode in llm_modes:
            # Enhanced error handling for AI processing
            try:
                with timed("LLM"):
                    if llm_detail and not (model_id.endswith(".gguf") or model_id.startswith("/")):
                        # Use timing-instrumented extraction for detailed profiling
                        from .llm_timing import ollama_extract_with_timing
                        prompt_context = None
                        try:
                            doc_context = DocumentContext()
                            doc_context.analyze_document(text)
                            prompt_context = build_prompt_context(doc_context)
                        except Exception:
                            prompt_context = None
                        model_spans = []
                        llm_error = None
                        for attempt_idx, wait_s in enumerate((0, 2), start=1):
                            try:
                                model_spans, llm_timing_detail = ollama_extract_with_timing(
                                    model_id, text, temperature, seed, context=prompt_context
                                )
                                llm_error = None
                                # Store in phase_timings for return
                                phase_timings['llm_timing'] = llm_timing_detail
                                break
                            except Exception as e:
                                llm_error = e
                                if wait_s:
                                    time.sleep(wait_s)
                        if llm_error is not None:
                            warnings.append({
                                "code": "LLM_EXTRACTION_FAILED",
                                "message": "AI extraction failed during detailed timing run after retries. Continuing with rules-only spans.",
                                "details": str(llm_error)
                            })
                    else:
                        model_spans = _collect_enhanced_spans(
                            text,
                            model_id,
                            chunk_tokens,
                            overlap,
                            temperature,
                            seed,
                            llm_skip_confidence,
                            debug,
                            progress_callback=progress_callback,
                            warnings=warnings,
                            suppressed=suppressed,
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

            if guardrailed_mode:
                model_spans = _filter_excluded_combo_spans(text, model_spans, suppressed)

            if normalized_mode in {"constrained_overrides", "llm_overrides"}:
                allowed_labels = {"ORG", "NAME", "LOC"} if normalized_mode == "constrained_overrides" else None
                before_count = len(rule_spans)
                rule_spans = apply_llm_overrides_to_rule_spans(
                    text=text,
                    rule_spans=rule_spans,
                    model_id=model_id,
                    backend=backend,
                    temperature=temperature,
                    seed=seed,
                    skip_confidence=llm_skip_confidence,
                    allowed_labels=allowed_labels,
                    suppressed=suppressed,
                    debug=debug,
                )
                if debug:
                    removed = before_count - len(rule_spans)
                    print(f"LLM override pass removed {removed} rule spans")

            with timed("POST_PROCESS"):
                all_spans = rule_spans + model_spans
                all_spans = _snap_to_boundaries(text, all_spans, debug=debug)
                all_spans = _trim_org_trailing_excluded_segments(text, all_spans)
                all_spans = _extend_org_suffixes(text, all_spans)
                all_spans = _attach_defined_term_aliases(text, all_spans)
                # Apply Consistency Pass (Enhanced)
                all_spans = _apply_consistency_pass(
                    text,
                    all_spans,
                    debug=debug,
                    exclude_if=_exclude_combo_for_pass if guardrailed_mode else None,
                )
                all_spans = _trim_org_jurisdiction_suffixes(text, all_spans)
                all_spans = _extend_loc_to_line(text, all_spans)
                all_spans = _filter_overlong_org_spans(text, all_spans)
                all_spans = _filter_county_spans(text, all_spans)
                merged = _merge_overlaps(all_spans, text)
                # Re-filter after merge to catch overlong spans created by union merging
                merged = _filter_overlong_org_spans(text, merged)
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
                        report_settings=report_settings,
                        warnings=warnings,
                        suppressed=suppressed,
                        debug=debug
                    )
                return (result, phase_timings)
            except RedactionError:
                raise
            except Exception as e:
                raise RedactionError(
                    message="Failed to save redacted document",
                    error_code="OUTPUT_SAVE_FAILED",
                    technical_details=f"Output path: {output_path}, Error: {str(e)}",
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


def _sha256_file(path: str) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_report_file_info(path: Optional[str]) -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    if not path:
        return info

    file_name = os.path.basename(path)
    if file_name:
        info["file_name"] = file_name

    extension = os.path.splitext(path)[1].lower().lstrip(".")
    if extension:
        info["file_extension"] = extension

    try:
        from .report_common import get_mime_type
        mime_type = get_mime_type(path)
        if mime_type:
            info["mime_type"] = mime_type
    except Exception:
        pass

    try:
        info["size_bytes"] = os.path.getsize(path)
    except Exception:
        pass

    try:
        info["sha256"] = _sha256_file(path)
    except Exception:
        pass

    return info


def _read_metadata_values(dm) -> dict:
    """
    Read current metadata values from document for forensic before/after comparison.
    
    Captures FULL values (no truncation) for all metadata fields including:
    - Core properties (author, title, dc:rights, etc.)
    - Extended properties (company, template, statistics)
    - Comments with anchor text and author info
    - Full hyperlink URLs
    - All RSID values
    - Non-standard/unknown fields discovered dynamically
    - Binary parts for extraction
    """
    values = {}
    binary_parts: List[Dict[str, Any]] = []
    text_parts: Dict[str, List[str]] = {}

    def _extract_text_from_part(part_blob) -> str:
        try:
            from lxml import etree
            root = etree.fromstring(part_blob)
            texts = []
            for el in root.iter():
                if isinstance(el.tag, str) and el.tag.endswith("}t") and el.text:
                    texts.append(el.text)
            return " ".join(texts).strip()
        except Exception:
            return ""
    
    # ========== CORE PROPERTIES (docProps/core.xml) ==========
    try:
        cp = dm.doc.core_properties
        
        values['author'] = str(cp.author or '')
        values['last_modified_by'] = str(cp.last_modified_by or '')
        values['title'] = str(cp.title or '')
        values['subject'] = str(cp.subject or '')
        values['keywords'] = str(cp.keywords or '')
        values['comments'] = str(cp.comments or '')  # Document-level comments property
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
    
    # Extended core properties from XML (dc:rights, dc:publisher, etc.)
    try:
        from lxml import etree
        for rel in dm.doc.part.package.rels.values():
            if "core-properties" in rel.reltype:
                core_part = rel.target_part
                if hasattr(core_part, '_blob') and core_part._blob:
                    core_xml = etree.fromstring(core_part._blob)
                    ns = {
                        'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
                        'dc': 'http://purl.org/dc/elements/1.1/',
                        'dcterms': 'http://purl.org/dc/terms/',
                    }
                    for elem in core_xml.findall('.//cp:contentType', namespaces=ns):
                        values['core_content_type'] = str(elem.text or '')
                    # Additional Dublin Core fields not in python-docx
                    for dc_field in ['rights', 'publisher', 'type', 'format', 'source', 'relation', 'coverage']:
                        for elem in core_xml.findall(f'.//dc:{dc_field}', namespaces=ns):
                            values[f'dc_{dc_field}'] = str(elem.text or '')
                    for dcterms_field in ['issued', 'available', 'valid']:
                        for elem in core_xml.findall(f'.//dcterms:{dcterms_field}', namespaces=ns):
                            values[f'dcterms_{dcterms_field}'] = str(elem.text or '')
                break
    except Exception:
        pass
    
    # ========== EXTENDED PROPERTIES (docProps/app.xml) ==========
    try:
        from lxml import etree
        for rel in dm.doc.part.package.rels.values():
            if "extended-properties" in rel.reltype or "app" in rel.reltype:
                app_part = rel.target_part
                if hasattr(app_part, '_blob') and app_part._blob:
                    app_xml = etree.fromstring(app_part._blob)
                    ns = {'ep': 'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties',
                          'vt': 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'}
                    
                    # All extended property fields
                    extended_tags = [
                        'Company', 'Manager', 'Application', 'AppVersion', 'Template',
                        'HyperlinkBase', 'TotalTime', 'Words', 'Characters', 'CharactersWithSpaces',
                        'Pages', 'Paragraphs', 'Lines', 'DocSecurity', 'ScaleCrop', 
                        'SharedDoc', 'LinksUpToDate', 'HyperlinksChanged',
                        'Slides', 'Notes', 'HiddenSlides', 'MMClips', 'PresentationFormat',
                    ]
                    for tag in extended_tags:
                        for elem in app_xml.findall(f'.//ep:{tag}', namespaces=ns):
                            key = "hyperlink_base" if tag == "HyperlinkBase" else tag.lower()
                            values[key] = str(elem.text or '')
                    
                    # HeadingPairs and TitlesOfParts (can reveal document structure)
                    heading_pairs = []
                    for hp in app_xml.findall('.//ep:HeadingPairs', namespaces=ns):
                        for variant in hp.findall('.//vt:lpstr', namespaces=ns):
                            if variant.text:
                                heading_pairs.append(variant.text)
                    if heading_pairs:
                        values['heading_pairs'] = heading_pairs
                    
                    titles_of_parts = []
                    for tp in app_xml.findall('.//ep:TitlesOfParts', namespaces=ns):
                        for variant in tp.findall('.//vt:lpstr', namespaces=ns):
                            if variant.text:
                                titles_of_parts.append(variant.text)
                    if titles_of_parts:
                        values['titles_of_parts'] = titles_of_parts
                    
                    # DigSig element presence
                    digsig = app_xml.find('.//ep:DigSig', namespaces=ns)
                    if digsig is not None:
                        values['digsig_info'] = 'present'

                    # Hyperlink list (HLinks)
                    hlinks = []
                    for hl in app_xml.findall('.//ep:HLinks', namespaces=ns):
                        for entry in hl.findall('.//vt:lpstr', namespaces=ns):
                            if entry.text:
                                hlinks.append(entry.text)
                    if hlinks:
                        values['hlinks'] = hlinks

                    # Consolidated document statistics (pages/words/characters/etc.)
                    stats_map = {
                        "Pages": values.get("pages"),
                        "Words": values.get("words"),
                        "Characters": values.get("characters"),
                        "Characters with spaces": values.get("characterswithspaces"),
                        "Paragraphs": values.get("paragraphs"),
                        "Lines": values.get("lines"),
                    }
                    stats = {label: val for label, val in stats_map.items() if val not in (None, "", [], {})}
                    if stats:
                        values["document_statistics"] = stats
                    break
    except Exception:
        pass
    
    # ========== DOCUMENT SETTINGS (settings.xml) ==========
    try:
        from docx.oxml.ns import qn
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            
            # Spell/Grammar State
            proof_state = settings_xml.find(qn('w:proofState'))
            if proof_state is not None:
                spelling = proof_state.get(qn('w:spelling')) or 'clean'
                grammar = proof_state.get(qn('w:grammar')) or 'clean'
                values['proof_state'] = f"spelling={spelling}, grammar={grammar}"
            else:
                values['proof_state'] = "default (clean)"

            # Attached template path (settings.xml)
            attached_template = settings_xml.find(qn('w:attachedTemplate'))
            if attached_template is not None:
                template_val = attached_template.get(qn('w:val')) or ''
                template_rid = attached_template.get(qn('r:id')) or ''
                values['attached_template'] = {
                    "path": template_val,
                    "rid": template_rid,
                }
            else:
                values['attached_template'] = {}

            # Document protection settings
            protection = settings_xml.find(qn('w:documentProtection'))
            if protection is not None:
                attrs = {}
                for key, val in protection.attrib.items():
                    cleaned_key = key.split('}', 1)[-1] if '}' in key else key
                    attrs[cleaned_key] = val
                values['document_protection'] = attrs
            else:
                values['document_protection'] = {}
            
            # Document Variables - FULL capture
            doc_vars = settings_xml.find(qn('w:docVars'))
            if doc_vars is not None:
                doc_var_list = []
                for var in doc_vars.findall(qn('w:docVar')):
                    name = var.get(qn('w:name')) or ''
                    val = var.get(qn('w:val')) or ''
                    if name:
                        doc_var_list.append({'name': name, 'value': val})
                values['doc_vars'] = doc_var_list
            else:
                values['doc_vars'] = []
            
            # Mail merge - full sources
            mail_merge = settings_xml.find(qn('w:mailMerge'))
            if mail_merge is not None:
                mm_info = {'present': True}
                ds = mail_merge.find(qn('w:dataSource'))
                if ds is not None:
                    ds_rel_id = ds.get(qn('r:id'))
                    mm_info['data_source_rid'] = ds_rel_id
                hs = mail_merge.find(qn('w:headerSource'))
                if hs is not None:
                    hs_rel_id = hs.get(qn('r:id'))
                    mm_info['header_source_rid'] = hs_rel_id
                values['mail_merge'] = mm_info
            else:
                values['mail_merge'] = {'present': False}
    except Exception:
        pass

    # ========== STRUCTURAL METADATA ==========
    try:
        from docx.oxml.ns import qn
        from lxml import etree
        import posixpath
        import zipfile

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

        def _is_unc_path(target: str) -> bool:
            return target.startswith("\\\\") or (target.startswith("//") and not target.startswith("http"))

        def _is_user_path(target: str) -> bool:
            for sep in ("\\", "/"):
                if f"{sep}Users{sep}" in target or f"{sep}home{sep}" in target:
                    return True
            return "%USERPROFILE%" in target

        def _is_file_path(target: str) -> bool:
            if target.startswith("file:"):
                return True
            if re.match(r"^[A-Za-z]:[\\/]", target):
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

        # ========== REVIEW COMMENTS - FULL FORENSIC CAPTURE ==========
        comments_list = []
        comment_id_to_text = {}  # Map comment IDs to their text
        try:
            # Parse comments.xml directly
            for part in dm.doc.part.package.parts:
                if str(part.partname) == "/word/comments.xml":
                    blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
                    if blob:
                        comments_xml = etree.fromstring(blob)
                        for comment in comments_xml.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}comment'):
                            comment_id = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id') or comment.get('id', '')
                            author = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}author') or comment.get('author', '')
                            date = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}date') or comment.get('date', '')
                            initials = comment.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}initials') or comment.get('initials', '')
                            # Extract full comment text
                            comment_text_parts = []
                            for t in comment.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
                                if t.text:
                                    comment_text_parts.append(t.text)
                            comment_text = ''.join(comment_text_parts)
                            comment_id_to_text[comment_id] = {
                                'author': author,
                                'date': date,
                                'initials': initials,
                                'comment_text': comment_text,
                            }
                    break

            def _has_ancestor(elem, tag) -> bool:
                return any(a.tag == tag for a in elem.iterancestors())

            def _is_hidden_run(elem) -> bool:
                for run in elem.iterancestors(qn('w:r')):
                    rpr = run.find(qn('w:rPr'))
                    if rpr is None:
                        continue
                    if rpr.find(qn('w:vanish')) is not None:
                        return True
                    if rpr.find(qn('w:webHidden')) is not None:
                        return True
                    if rpr.find(qn('w:specVanish')) is not None:
                        return True
                return False

            comment_anchors = {}

            # Single pass through parts to capture anchor ranges and context.
            for root in _iter_part_elements():
                active = {}
                for elem in root.iter():
                    tag = elem.tag
                    if tag == qn('w:commentRangeStart'):
                        cid = elem.get(qn('w:id')) or ''
                        if not cid:
                            continue
                        info = comment_anchors.setdefault(cid, {"text_parts": [], "contexts": set(), "has_start": False, "has_end": False})
                        info["has_start"] = True
                        if _has_ancestor(elem, qn('w:del')) or _has_ancestor(elem, qn('w:moveFrom')):
                            info["contexts"].add("deleted")
                        active[cid] = True
                        continue
                    if tag == qn('w:commentRangeEnd'):
                        cid = elem.get(qn('w:id')) or ''
                        info = comment_anchors.get(cid)
                        if info:
                            info["has_end"] = True
                        if cid in active:
                            del active[cid]
                        continue
                    if not active:
                        continue
                    if tag in (qn('w:t'), qn('w:delText'), qn('w:instrText')) and elem.text:
                        is_hidden = _is_hidden_run(elem)
                        is_deleted = _has_ancestor(elem, qn('w:del')) or _has_ancestor(elem, qn('w:moveFrom'))
                        for cid in active:
                            info = comment_anchors[cid]
                            info["text_parts"].append(elem.text)
                            if is_hidden:
                                info["contexts"].add("hidden")
                            if is_deleted:
                                info["contexts"].add("deleted")

            # Build final list with explicit visibility status.
            for cid, base in comment_id_to_text.items():
                anchor_info = comment_anchors.get(cid) or {}
                anchor_text = ''.join(anchor_info.get("text_parts", [])).strip()
                contexts = anchor_info.get("contexts", set())
                if not anchor_info or not anchor_info.get("has_start"):
                    status = "deleted"
                elif "deleted" in contexts:
                    status = "deleted"
                elif "hidden" in contexts:
                    status = "hidden"
                else:
                    status = "visible"
                comment_info = base.copy()
                comment_info['comment_id'] = cid
                comment_info['anchor_text'] = anchor_text
                comment_info['status'] = status
                comments_list.append(comment_info)
        except Exception:
            pass
        values['review_comments'] = comments_list
        values['review_comments_visible'] = [
            c for c in comments_list if (c.get('status') or '') == 'visible'
        ]
        values['review_comments_hidden'] = [
            c for c in comments_list if (c.get('status') or '') in ('hidden', 'deleted')
        ]

        # ========== TRACK CHANGES - FULL CAPTURE ==========
        track_changes_list = []
        track_tags = [qn('w:ins'), qn('w:del'), qn('w:moveFrom'), qn('w:moveTo')]
        for root in _iter_part_elements():
            for tag in track_tags:
                tag_local = tag.split('}', 1)[-1]
                for elem in root.iter(tag):
                    author = elem.get(qn('w:author')) or ''
                    date = elem.get(qn('w:date')) or ''
                    # Extract text content
                    text_parts = []
                    for t in elem.iter(qn('w:t')):
                        if t.text:
                            text_parts.append(t.text)
                    change_text = ''.join(text_parts)
                    if change_text or author:  # Only capture if there's meaningful content
                        track_changes_list.append({
                            'type': tag_local,
                            'author': author,
                            'date': date,
                            'text': change_text,
                        })
        values['track_changes'] = track_changes_list

        # ========== RSIDS - FULL LIST ==========
        rsid_values = set()
        for root in _iter_part_elements():
            # Check all attributes on all elements
            for el in root.iter():
                for key, val in el.attrib.items():
                    if "rsid" in key.lower() and val:
                        rsid_values.add(val)
            
            # Check for w:rsids in settings.xml
            if root.tag == qn('w:settings'):
                for rsid_el in root.findall(".//{*}rsid"):
                    val = rsid_el.get(qn('w:val'))
                    if val:
                        rsid_values.add(val)
        
        values['rsids'] = sorted(list(rsid_values))

        # ========== DOCUMENT GUIDs ==========
        guids = []
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            # w14:docId
            for ns_prefix in ['w14', 'w15', 'w16']:
                guid_elements = settings_xml.findall(f'{{{ns_prefix}}}docId')
                for el in guid_elements:
                    val = el.get(f'{{{ns_prefix}}}val') or el.get('val')
                    if val:
                        guids.append({'namespace': ns_prefix, 'value': val})
        values['document_guid'] = guids

        # ========== DATA BINDINGS - FULL ==========
        data_bindings = []
        for root in _iter_part_elements():
            for el in root.iter(qn('w:dataBinding')):
                store_item_id = el.get(qn('w:storeItemID')) or el.get('storeItemID') or ''
                xpath = el.get(qn('w:xpath')) or el.get('xpath') or ''
                prefix_mappings = el.get(qn('w:prefixMappings')) or el.get('prefixMappings') or ''
                data_bindings.append({
                    'storeItemID': store_item_id,
                    'xpath': xpath,
                    'prefixMappings': prefix_mappings,
                })
        values['data_bindings'] = data_bindings

        # ========== HIDDEN TEXT - FULL CAPTURE ==========
        hidden_text_runs = []
        for root in _iter_part_elements():
            for run in root.iter(qn('w:r')):
                rpr = run.find(qn('w:rPr'))
                if rpr is None:
                    continue
                is_hidden = (rpr.find(qn('w:vanish')) is not None
                            or rpr.find(qn('w:specVanish')) is not None
                            or rpr.find(qn('w:webHidden')) is not None)
                if is_hidden:
                    text_parts = []
                    for t in run.iter(qn('w:t')):
                        if t.text:
                            text_parts.append(t.text)
                    if text_parts:
                        hidden_text_runs.append(''.join(text_parts))
        values['hidden_text'] = hidden_text_runs

        # ========== INVISIBLE OBJECTS ==========
        invisible_objects = []
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
                    tag_name = el.tag.split('}', 1)[-1] if '}' in el.tag else el.tag
                    invisible_objects.append({'tag': tag_name, 'style': style or visibility or display})
        values['invisible_objects'] = invisible_objects

        # ========== HEADERS & FOOTERS ==========
        headers_footers = []
        for rel in dm.doc.part.rels.values():
            if "header" in rel.reltype or "footer" in rel.reltype:
                hf_type = "header" if "header" in rel.reltype else "footer"
                part_name = str(rel.target_part.partname) if hasattr(rel.target_part, 'partname') else ''
                # Extract text content
                text_content = ''
                if hasattr(rel.target_part, 'element'):
                    text_parts = []
                    for t in rel.target_part.element.iter(qn('w:t')):
                        if t.text:
                            text_parts.append(t.text)
                    text_content = ''.join(text_parts)
                headers_footers.append({
                    'type': hf_type,
                    'part': part_name,
                    'text': text_content,
                })
        values['headers_footers'] = headers_footers

        # ========== WATERMARKS ==========
        watermarks = []
        for rel in dm.doc.part.rels.values():
            if "header" not in rel.reltype:
                continue
            if not hasattr(rel.target_part, "element"):
                continue
            root = rel.target_part.element
            for el in root.iter():
                attrs = " ".join(str(v) for v in el.attrib.values()).lower()
                if "powerpluswatermarkobject" in attrs or "watermark" in attrs:
                    tag_name = el.tag.split('}', 1)[-1] if '}' in el.tag else el.tag
                    watermarks.append({'tag': tag_name, 'attributes': dict(el.attrib)})
                elif "mso-position-horizontal:center" in attrs and "mso-position-vertical:center" in attrs:
                    tag_name = el.tag.split('}', 1)[-1] if '}' in el.tag else el.tag
                    watermarks.append({'tag': tag_name, 'attributes': dict(el.attrib)})
        values['watermarks'] = watermarks

        # ========== INK ANNOTATIONS ==========
        ink_parts = []
        for part in dm.doc.part.package.parts:
            if str(part.partname).startswith("/word/ink"):
                ink_parts.append(str(part.partname))
        values['ink_annotations'] = ink_parts

        # ========== DOCUMENT VERSIONS ==========
        version_parts = []
        for part in dm.doc.part.package.parts:
            if str(part.partname).startswith("/word/versions"):
                version_parts.append(str(part.partname))
        values['document_versions'] = version_parts

        # ========== CUSTOM PROPERTIES - FULL ==========
        custom_property_list = []
        custom_xml_parts = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if name.endswith("/docProps/custom.xml") and blob:
                try:
                    root = etree.fromstring(blob)
                    for prop in root.findall(".//{*}property"):
                        prop_name = prop.get("name") or prop.get("fmtid") or ""
                        prop_pid = prop.get("pid") or ""
                        # Get value from child element
                        prop_value = ""
                        for child in prop:
                            if child.text:
                                prop_value = child.text
                                break
                        custom_property_list.append({
                            'name': prop_name,
                            'pid': prop_pid,
                            'value': prop_value,
                        })
                except Exception:
                    pass
            if name.startswith("/customXml/") and name.endswith(".xml") and blob:
                try:
                    root = etree.fromstring(blob)
                    root_tag = root.tag.split("}", 1)[-1] if "}" in root.tag else root.tag
                    root_ns = root.tag.split("}", 1)[0][1:] if root.tag.startswith("{") else ""
                    xml_content = etree.tostring(root, encoding='unicode')
                    custom_xml_parts.append({
                        'part': name,
                        'root_tag': root_tag,
                        'namespace': root_ns,
                        'xml': xml_content,
                    })
                except Exception:
                    custom_xml_parts.append({'part': name})
        custom_xml_rel_count = 0
        try:
            rel_sets = []
            if hasattr(dm.doc.part, "rels"):
                rel_sets.append(dm.doc.part.rels.values())
            if hasattr(dm.doc.part.package, "rels"):
                rel_sets.append(dm.doc.part.package.rels.values())
            for rels in rel_sets:
                for rel in rels:
                    reltype = getattr(rel, "reltype", "") or ""
                    if "customXml" in reltype or "custom-properties" in reltype:
                        custom_xml_rel_count += 1
        except Exception:
            pass
        values['custom_properties'] = custom_property_list
        values['custom_xml_parts'] = custom_xml_parts
        values['custom_xml_rel_count'] = custom_xml_rel_count

        # ========== RELATIONSHIP INVENTORY ==========
        unknown_relationships = []
        referenced_parts = set()
        try:
            standard_rel_prefixes = (
                "http://schemas.openxmlformats.org/",
                "http://schemas.microsoft.com/office/",
            )
            for part in dm.doc.part.package.parts:
                part_name = str(part.partname)
                if not part_name.endswith(".rels"):
                    continue
                blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
                if not blob:
                    continue
                try:
                    rel_root = etree.fromstring(blob)
                except Exception:
                    continue
                for rel in rel_root:
                    reltype = rel.get("Type") or ""
                    target = rel.get("Target") or ""
                    target_mode = rel.get("TargetMode") or ""
                    if target_mode != "External" and target:
                        # Resolve relative to the rels part path
                        rels_path = part_name
                        base_dir = ""
                        if rels_path != "_rels/.rels" and "/_rels/" in rels_path:
                            source_path = rels_path.replace("/_rels/", "/")
                            if source_path.endswith(".rels"):
                                source_path = source_path[:-5]
                            base_dir = posixpath.dirname(source_path)
                        resolved = posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")
                        referenced_parts.add(resolved)
                    if not reltype.startswith(standard_rel_prefixes):
                        unknown_relationships.append({
                            "source_rels": part_name,
                            "reltype": reltype,
                            "target": target,
                            "target_mode": target_mode or "Internal",
                        })
        except Exception:
            pass
        try:
            def _add_ref(partname):
                if partname:
                    referenced_parts.add(str(partname).lstrip("/"))
            for rel in getattr(dm.doc.part, "rels", {}).values():
                if getattr(rel, "is_external", False):
                    continue
                target_part = getattr(rel, "target_part", None)
                if target_part is not None:
                    _add_ref(getattr(target_part, "partname", None))
            for rel in getattr(dm.doc.part.package, "rels", {}).values():
                if getattr(rel, "is_external", False):
                    continue
                target_part = getattr(rel, "target_part", None)
                if target_part is not None:
                    _add_ref(getattr(target_part, "partname", None))
            for part in dm.doc.part.package.parts:
                rels = getattr(part, "rels", None)
                if not rels:
                    continue
                for rel in rels.values():
                    if getattr(rel, "is_external", False):
                        continue
                    target_part = getattr(rel, "target_part", None)
                    if target_part is not None:
                        _add_ref(getattr(target_part, "partname", None))
        except Exception:
            pass
        values['unknown_relationships'] = unknown_relationships

        # ========== ORPHANED PARTS ==========
        orphaned_parts = []
        try:
            for part in dm.doc.part.package.parts:
                part_name = str(part.partname).lstrip("/")
                if part_name == "[Content_Types].xml" or part_name.endswith(".rels"):
                    continue
                if part_name not in referenced_parts:
                    blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
                    orphaned_parts.append({
                        "part": part_name,
                        "size": len(blob) if blob else 0,
                        "content_type": getattr(part, "content_type", "") or "",
                    })
        except Exception:
            pass
        values['orphaned_parts'] = orphaned_parts

        # ========== HYPERLINKS - FULL URLs ==========
        hyperlinks_list = []
        # Build relationship ID to target mapping
        rid_to_target = {}
        for rel in dm.doc.part.rels.values():
            if hasattr(rel, 'target_ref'):
                rid_to_target[rel.rId] = str(rel.target_ref)
        # Find all hyperlinks
        for root in _iter_part_elements():
            for hyperlink in root.iter(qn('w:hyperlink')):
                rid = hyperlink.get(qn('r:id')) or ''
                anchor = hyperlink.get(qn('w:anchor')) or ''
                # Get display text
                text_parts = []
                for t in hyperlink.iter(qn('w:t')):
                    if t.text:
                        text_parts.append(t.text)
                display_text = ''.join(text_parts)
                target_url = rid_to_target.get(rid, '')
                hyperlinks_list.append({
                    'rid': rid,
                    'url': target_url,
                    'anchor': anchor,
                    'display_text': display_text,
                })
        values['hyperlinks'] = hyperlinks_list

        # ========== ALT TEXT - FULL ==========
        alt_text_list = []
        for root in _iter_part_elements():
            for el in root.iter():
                if el.tag == '{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}docPr':
                    descr = el.attrib.get("descr") or ''
                    title = el.attrib.get("title") or ''
                    name = el.attrib.get("name") or ''
                    if descr or title:
                        alt_text_list.append({
                            'name': name,
                            'title': title,
                            'description': descr,
                        })
        values['alt_text'] = alt_text_list

        # ========== OLE OBJECTS ==========
        ole_objects = []
        for root in _iter_part_elements():
            for obj in root.iter(qn('w:object')):
                obj_info = {'type': 'object'}
                ole_obj = obj.find('.//{urn:schemas-microsoft-com:office:office}OLEObject')
                if ole_obj is not None:
                    obj_info['prog_id'] = ole_obj.get('ProgID') or ''
                    obj_info['shape_id'] = ole_obj.get('ShapeID') or ''
                    obj_info['rid'] = ole_obj.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id') or ''
                ole_objects.append(obj_info)
            for ctrl in root.iter(qn('w:control')):
                ctrl_info = {'type': 'control'}
                ctrl_info['name'] = ctrl.get(qn('w:name')) or ''
                ctrl_info['rid'] = ctrl.get(qn('r:id')) or ''
                ole_objects.append(ctrl_info)
        values['ole_objects'] = ole_objects

        # ========== EMBEDDED CONTENT PRESENCE ==========
        rel_types = [rel.reltype for rel in dm.doc.part.rels.values()]
        values['vba_macros'] = "present" if any("vbaProject" in t for t in rel_types) else "none"
        values['digital_signatures'] = "present" if any("signature" in t for t in rel_types) else "none"
        values['printer_settings'] = "present" if any("printerSettings" in t for t in rel_types) else "none"
        values['glossary'] = "present" if any("glossary" in t for t in rel_types) else "none"
        values['thumbnail'] = "present" if any(str(part.partname).startswith("/docProps/thumbnail")
                                              for part in dm.doc.part.package.parts) else "none"

        # Digital signature details (package signatures)
        digital_signature_details = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if not name.startswith("/_xmlsignatures/"):
                continue
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            sig_info = {"part": name}
            if blob:
                try:
                    sig_root = etree.fromstring(blob)
                    ds_ns = "http://www.w3.org/2000/09/xmldsig#"
                    subject = sig_root.find(f".//{{{ds_ns}}}X509SubjectName")
                    issuer = sig_root.find(f".//{{{ds_ns}}}X509IssuerName")
                    serial = sig_root.find(f".//{{{ds_ns}}}X509SerialNumber")
                    if subject is not None and subject.text:
                        sig_info["subject"] = subject.text
                    if issuer is not None and issuer.text:
                        sig_info["issuer"] = issuer.text
                    if serial is not None and serial.text:
                        sig_info["serial"] = serial.text
                    signing_time = None
                    for el in sig_root.iter():
                        tag = el.tag.split('}', 1)[-1] if isinstance(el.tag, str) else ''
                        if tag.lower() in ("signingtime", "signaturetime"):
                            if el.text:
                                signing_time = el.text
                                break
                    if signing_time:
                        sig_info["signing_time"] = signing_time
                except Exception:
                    pass
            digital_signature_details.append(sig_info)
        values['digital_signature_details'] = digital_signature_details

        # Printer settings details
        printer_settings_parts = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if name.startswith("/word/printerSettings/"):
                blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
                printer_settings_parts.append({
                    "part": name,
                    "size": len(blob) if blob else 0,
                })
        values['printer_settings_parts'] = printer_settings_parts

        # ========== EMBEDDED FONTS - FULL LIST ==========
        embedded_fonts = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if name.startswith("/word/fonts/"):
                embedded_fonts.append(name)
        values['embedded_fonts'] = embedded_fonts

        # ========== EMBEDDED FILES & MEDIA ==========
        embedded_files = []
        embedded_media = []
        media_exts = {".mp3", ".wav", ".m4a", ".wma", ".mp4", ".mov", ".avi", ".mkv", ".webm"}
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if name.startswith("/word/embeddings/"):
                embedded_files.append({
                    "part": name,
                    "content_type": getattr(part, "content_type", "") or "",
                    "size": len(blob) if blob else 0,
                })
            if name.startswith("/word/media/"):
                ext = os.path.splitext(name)[1].lower()
                if ext in media_exts or getattr(part, "content_type", "").startswith(("audio/", "video/")):
                    embedded_media.append({
                        "part": name,
                        "content_type": getattr(part, "content_type", "") or "",
                        "size": len(blob) if blob else 0,
                    })
        values['embedded_files'] = embedded_files
        values['embedded_media'] = embedded_media

        # ========== BINARY PARTS FOR EXTRACTION ==========
        # ALL binary parts (export everything with a blob)
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            data = getattr(part, "blob", None) or getattr(part, "_blob", None)
            if data is None:
                continue
            
            part_type = None
            if name.startswith("/word/media/"):
                part_type = "image"
            elif name.startswith("/docProps/thumbnail"):
                part_type = "thumbnail"
            elif name.startswith("/word/fonts/"):
                part_type = "font"
            elif name.endswith("vbaProject.bin"):
                part_type = "macro"
            elif name.startswith("/word/printerSettings/"):
                part_type = "printer_settings"
            elif name.startswith("/word/embeddings/"):
                part_type = "ole_embedding"
            elif name.startswith("/word/activeX/"):
                part_type = "activex"
            else:
                part_type = "other"
            
            binary_parts.append({
                "name": name.strip("/"),
                "type": part_type,
                "size": len(data),
                "content_type": getattr(part, "content_type", "") or "",
                "extension": os.path.splitext(name)[1].lower(),
                "data": data,
            })

        # ========== EXTERNAL RELATIONSHIPS ==========
        external_targets = []
        for rel in dm.doc.part.rels.values():
            target = getattr(rel, "target_ref", "")
            is_external = getattr(rel, "is_external", False)
            if is_external:
                external_targets.append({
                    'reltype': rel.reltype or '',
                    'target': str(target),
                    'is_unc': _is_unc_path(str(target)),
                    'is_user_path': _is_user_path(str(target)),
                    'is_file_path': _is_file_path(str(target)),
                    'is_internal_url': _is_internal_url(str(target)),
                })
        values['external_links'] = external_targets

        # ========== IMAGE EXIF DETECTION ==========
        exif_images = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if not name.startswith("/word/media/"):
                continue
            data = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if data is None:
                continue
            has_exif = False
            if name.lower().endswith((".jpg", ".jpeg")) and b"Exif" in data[:4096]:
                has_exif = True
            if name.lower().endswith(".png") and b"eXIf" in data:
                has_exif = True
            if has_exif:
                exif_images.append(name)
        values['image_exif'] = exif_images

        # ========== STYLE NAMES ==========
        custom_styles = []
        for part in dm.doc.part.package.parts:
            if str(part.partname) != "/word/styles.xml":
                continue
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if blob:
                root = etree.fromstring(blob)
                for style in root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}style"):
                    is_custom = style.get(qn("w:customStyle")) == "1"
                    style_id = style.get(qn("w:styleId")) or ''
                    style_type = style.get(qn("w:type")) or ''
                    name_elem = style.find(qn("w:name"))
                    style_name = name_elem.get(qn("w:val")) if name_elem is not None else ''
                    if is_custom:
                        custom_styles.append({
                            'styleId': style_id,
                            'type': style_type,
                            'name': style_name,
                        })
        values['style_names'] = custom_styles

        # ========== CHART LABELS ==========
        chart_labels = []
        for part in dm.doc.part.package.parts:
            if not str(part.partname).startswith("/word/charts/"):
                continue
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if blob:
                try:
                    root = etree.fromstring(blob)
                    for el in root.iter():
                        if el.tag.endswith("}v") or el.tag.endswith("}t"):
                            if el.text:
                                chart_labels.append(el.text)
                except Exception:
                    pass
        values['chart_labels'] = chart_labels

        # ========== FORM DEFAULTS ==========
        form_defaults = []
        for root in _iter_part_elements():
            for default in root.iter(qn('w:default')):
                val = default.get(qn('w:val')) or ''
                form_defaults.append({'type': 'default', 'value': val})
            for result in root.iter(qn('w:result')):
                val = result.text or ''
                form_defaults.append({'type': 'result', 'value': val})
        values['form_defaults'] = form_defaults

        # ========== LANGUAGE SETTINGS ==========
        lang_list = []
        for root in _iter_part_elements():
            for el in root.iter():
                lang_val = el.attrib.get(qn('w:val'))
                bidi = el.attrib.get(qn('w:bidi'))
                east_asia = el.attrib.get(qn('w:eastAsia'))
                if el.tag == qn('w:lang'):
                    lang_list.append({
                        'val': lang_val or '',
                        'bidi': bidi or '',
                        'eastAsia': east_asia or '',
                    })
        values['language_settings'] = lang_list

        # ========== ACTIVEX CONTROLS ==========
        activex_parts = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if name.startswith("/word/activeX/") or name.startswith("/word/controls/"):
                activex_parts.append(name)
        values['activex'] = activex_parts

        # ========== FAST SAVE DATA ==========
        if hasattr(dm.doc, 'settings') and dm.doc.settings:
            settings_xml = dm.doc.settings.element
            fast_save_entries = []
            for tag in (qn('w:savePreviewPicture'), qn('w:saveThroughXslt')):
                el = settings_xml.find(tag)
                if el is None:
                    continue
                tag_name = tag.split('}', 1)[-1] if '}' in tag else tag
                fast_save_entries.append({
                    "tag": tag_name,
                    "attributes": dict(el.attrib) if el.attrib else {},
                    "xml": etree.tostring(el, encoding='unicode'),
                })
            values['fast_save'] = fast_save_entries

        # ========== NON-STANDARD FIELD DISCOVERY ==========
        # Scan all XML parts for elements we haven't explicitly captured
        non_standard_fields = []
        microsoft_extension_fields = []
        known_namespaces = {
            'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
            'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
            'http://schemas.openxmlformats.org/drawingml/2006/main',
            'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
            'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
            'http://schemas.openxmlformats.org/officeDocument/2006/extended-properties',
            'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes',
            'http://purl.org/dc/elements/1.1/',
            'http://purl.org/dc/terms/',
            'http://schemas.openxmlformats.org/markup-compatibility/2006',
        }
        known_namespace_prefixes = (
            "http://schemas.microsoft.com/office/word/",
            "http://schemas.microsoft.com/office/",
        )
        alternate_content = []
        for part in dm.doc.part.package.parts:
            name = str(part.partname)
            if not name.endswith('.xml'):
                continue
            blob = getattr(part, 'blob', None) or getattr(part, '_blob', None)
            if not blob:
                continue
            try:
                root = etree.fromstring(blob)
                for el in root.iter():
                    if '}' in el.tag:
                        ns = el.tag.split('}')[0][1:]
                        local_name = el.tag.split('}')[1]
                        entry = {
                            'part': name,
                            'namespace': ns,
                            'element': local_name,
                            'text': (el.text or '').strip(),
                            'attributes': dict(el.attrib) if el.attrib else {},
                            'xml': etree.tostring(el, encoding='unicode'),
                        }
                        if ns in known_namespaces:
                            continue
                        if any(ns.startswith(prefix) for prefix in known_namespace_prefixes):
                            if entry['text'] or entry['attributes']:
                                microsoft_extension_fields.append(entry)
                            continue
                        if entry['text'] or entry['attributes']:
                            non_standard_fields.append(entry)
                    else:
                        continue
                # Alternate content blocks
                for ac in root.findall(".//mc:AlternateContent", namespaces={"mc": "http://schemas.openxmlformats.org/markup-compatibility/2006"}):
                    alternate_content.append({
                        "part": name,
                        "xml": etree.tostring(ac, encoding='unicode'),
                    })
            except Exception:
                continue
        values['non_standard_fields'] = non_standard_fields
        values['microsoft_extension_fields'] = microsoft_extension_fields
        values['alternate_content'] = alternate_content

    except Exception:
        pass

    if binary_parts:
        values["_binary_parts"] = binary_parts
    return values



def _build_scrub_report(
    before: dict,
    after: dict,
    settings,
    *,
    file_path: Optional[str] = None,
    input_path: Optional[str] = None,
    input_file_info: Optional[Dict[str, Any]] = None,
    report_dir: Optional[str] = None,
    warnings: Optional[List[Dict[str, Any]]] = None,
) -> dict:
    """
    Build comprehensive forensic report with before/after values grouped like UI.
    
    Handles list and dict values from enhanced _read_metadata_values,
    exports binary parts to structured binaries/ subdirectory.
    """
    
    def _perform_forensic_analysis(before_values: dict, after_values: dict) -> List[Dict[str, Any]]:
        """Run heuristic checks to flag suspicious metadata inconsistencies."""
        findings: List[Dict[str, Any]] = []
        now_local = datetime.datetime.now().astimezone()
        local_tz = now_local.tzinfo
        local_tz_label = local_tz.tzname(now_local) if local_tz else "local"

        def _add(severity: str, title: str, detail: str, evidence: Optional[List[str]] = None):
            findings.append({
                "severity": severity,
                "title": title,
                "detail": detail,
                "evidence": evidence or [],
            })

        def _safe_int(val) -> Optional[int]:
            try:
                return int(str(val).strip())
            except Exception:
                return None

        def _parse_dt(val) -> tuple[Optional[datetime.datetime], bool]:
            if not val:
                return None, False
            if isinstance(val, datetime.datetime):
                dt = val
                assumed_local = dt.tzinfo is None
                if assumed_local:
                    return dt.replace(tzinfo=local_tz), True
                return dt.astimezone(local_tz), False
            s = str(val).strip()
            if not s:
                return None, False
            try:
                # Normalize Z suffix
                if s.endswith("Z"):
                    dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                else:
                    dt = datetime.datetime.fromisoformat(s)
                assumed_local = dt.tzinfo is None
                if assumed_local:
                    return dt.replace(tzinfo=local_tz), True
                return dt.astimezone(local_tz), False
            except Exception:
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.datetime.strptime(s, fmt)
                        return dt.replace(tzinfo=local_tz), True
                    except Exception:
                        continue
            return None, False

        # Laundered template: high revision count with tiny edit time
        revision = _safe_int(before_values.get("revision"))
        edit_minutes = _safe_int(before_values.get("totaltime"))
        if revision is not None and edit_minutes is not None and revision >= 20:
            minutes_per_rev = edit_minutes / max(revision, 1)
            if edit_minutes <= 1 or minutes_per_rev < 0.1 or (revision >= 50 and edit_minutes < 5):
                _add(
                    "high",
                    "Possible revision/edit time mismatch",
                    f"Revision count {revision} with total edit time {edit_minutes} minute(s) (~{minutes_per_rev:.2f} min/rev).",
                    ["Possible save-as laundering or manual XML manipulation. Can also occur with autosave or template reuse."],
                )

        # Ghost author: creator vs first tracked/comment author
        core_author = (before_values.get("author") or "").strip()
        last_modified_by = (before_values.get("last_modified_by") or "").strip()
        track_changes = before_values.get("track_changes") or []
        comments = before_values.get("review_comments") or []

        def _first_author(entries):
            best_author = ""
            best_dt = None
            order_unknown = False
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                author = entry.get("author")
                if not author:
                    continue
                author = str(author).strip()
                date_val = entry.get("date") or entry.get("created") or entry.get("modified")
                if date_val:
                    parsed_dt, _ = _parse_dt(date_val)
                else:
                    parsed_dt = None
                if parsed_dt is not None:
                    if best_dt is None or parsed_dt < best_dt:
                        best_dt = parsed_dt
                        best_author = author
                elif not best_author:
                    best_author = author
                    order_unknown = True
            return best_author, order_unknown

        tc_author, tc_order_unknown = _first_author(track_changes)
        comment_author, comment_order_unknown = _first_author(comments)
        content_author = tc_author or comment_author
        content_order_unknown = tc_order_unknown if tc_author else comment_order_unknown

        if core_author and content_author and core_author.lower() != content_author.lower():
            evidence = [f"Last Modified By: {last_modified_by or '(none)'}"] if last_modified_by else []
            if content_order_unknown:
                evidence.append("No timestamps available; author order reflects XML order.")
            _add(
                "medium",
                "Author mismatch",
                f"Document creator '{core_author}' differs from first content author '{content_author}'.",
                evidence if evidence else None,
            )
        elif last_modified_by and content_author and last_modified_by.lower() != content_author.lower():
            evidence = [f"Creator: {core_author or '(none)'}"]
            if content_order_unknown:
                evidence.append("No timestamps available; author order reflects XML order.")
            _add(
                "medium",
                "Last Modified By mismatch",
                f"Last modified by '{last_modified_by}' differs from first content author '{content_author}'.",
                evidence,
            )

        # Timestamp rationality checks
        created_dt, created_local = _parse_dt(before_values.get("created"))
        modified_dt, modified_local = _parse_dt(before_values.get("modified"))
        printed_dt, printed_local = _parse_dt(before_values.get("last_printed"))
        tz_note = f"Timezone not specified; assumed local time ({local_tz_label})."

        if created_dt and modified_dt and modified_dt < created_dt:
            evidence = [tz_note] if created_local or modified_local else None
            _add(
                "medium",
                "Timestamp anomaly",
                f"Modified date {modified_dt.isoformat()} is before created date {created_dt.isoformat()}.",
                evidence,
            )
        if modified_dt and printed_dt and printed_dt < modified_dt - datetime.timedelta(minutes=5):
            evidence = [tz_note] if printed_local or modified_local else None
            _add(
                "info",
                "Print before modification",
                f"Last printed {printed_dt.isoformat()} is before last modified {modified_dt.isoformat()}.",
                evidence,
            )
        for label, dt_val, dt_local in (
            ("Created", created_dt, created_local),
            ("Modified", modified_dt, modified_local),
            ("Last Printed", printed_dt, printed_local),
        ):
            if dt_val and dt_val > now_local + datetime.timedelta(days=1):
                evidence = [tz_note] if dt_local else None
                _add(
                    "high",
                    "Future timestamp detected",
                    f"{label} timestamp {dt_val.isoformat()} is in the future relative to system clock.",
                    evidence,
                )

        # Software fingerprinting
        application = (before_values.get("application") or "").lower()
        app_version = (before_values.get("appversion") or "").strip()
        if application:
            if any(sig in application for sig in ("apache poi", "aspose", "libreoffice", "openxmlsdk")):
                _add(
                    "info",
                    "Automated authoring software (informational)",
                    f"Application string '{before_values.get('application')}' suggests automated generation.",
                    [f"App Version: {app_version or '(unspecified)'}"] if app_version else None,
                )
            elif "microsoft" in application and app_version and app_version.startswith("1."):
                _add(
                    "low",
                    "Suspicious application version",
                    f"Application '{before_values.get('application')}' reports unusually low version '{app_version}'.",
                )

        if findings:
            severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
            indexed = list(enumerate(findings))
            indexed.sort(key=lambda item: (severity_rank.get(item[1].get("severity", "medium"), 99), item[0]))
            findings = [finding for _, finding in indexed]

        return findings

    def _detect_encryption(path: Optional[str]) -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {"status": "unknown"}
        import zipfile
        try:
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
            parts = []
            for candidate in ("EncryptionInfo", "EncryptedPackage"):
                if candidate in names:
                    parts.append(candidate)
            if parts:
                return {"status": "present", "parts": parts}
            return {"status": "none"}
        except zipfile.BadZipFile:
            return {"status": "present (non-zip container)"}
        except Exception:
            return {"status": "unknown"}
    
    def _serialize_value(val):
        """Serialize complex values for JSON report while preserving structure."""
        if val is None:
            return None
        if isinstance(val, (str, int, float, bool)):
            return val
        if isinstance(val, (list, tuple)):
            return [_serialize_value(v) for v in val]
        if isinstance(val, dict):
            # Remove binary data, keep metadata
            return {k: _serialize_value(v) for k, v in val.items() if k != 'data' and not k.startswith('_')}
        return str(val)

    def _summarize_parts(parts, label):
        if isinstance(parts, list):
            return f"{len(parts)} {label}"
        if parts is None:
            return f"0 {label}"
        return str(parts)

    def _custom_properties_payload(values):
        custom_props = values.get("custom_properties") or []
        names = []
        for prop in custom_props:
            if isinstance(prop, dict):
                name = prop.get("name") or prop.get("fmtid") or ""
                if name:
                    names.append(name)
            else:
                names.append(str(prop))
        return {
            "custom_property_names": names,
            "custom_xml_parts": values.get("custom_xml_parts") or [],
            "custom_xml_rel_count": int(values.get("custom_xml_rel_count") or 0),
        }
    
    groups = {
        "App Properties": [
            {"field": "Company", "setting": "clean_company", "before_key": "company"},
            {"field": "Manager", "setting": "clean_manager", "before_key": "manager"},
            {"field": "Total Editing Time", "setting": "clean_total_editing_time", "before_key": "totaltime"},
            {"field": "Application", "setting": "clean_application", "before_key": "application"},
            {"field": "App Version", "setting": "clean_app_version", "before_key": "appversion"},
            {"field": "Template", "setting": "clean_template", "before_key": "template"},
            {"field": "Hyperlink Base", "setting": "clean_hyperlink_base", "before_key": "hyperlink_base"},
            {"field": "Hyperlink List (HLinks)", "setting": "clean_hyperlink_urls", "before_key": "hlinks"},
            {"field": "Document Statistics", "setting": "clean_statistics", "before_key": "document_statistics"},
            {"field": "Document Security", "setting": "clean_doc_security", "before_key": "docsecurity"},
            {"field": "Thumbnail Settings", "setting": "clean_scale_crop", "before_key": "scalecrop"},
            {"field": "Shared Document Flag", "setting": "clean_shared_doc", "before_key": "shareddoc"},
            {"field": "Links Up-to-Date Flag", "setting": "clean_links_up_to_date", "before_key": "linksuptodate"},
            {"field": "Hyperlinks Changed Flag", "setting": "clean_hyperlinks_changed", "before_key": "hyperlinkschanged"},
            {"field": "Heading Pairs", "setting": "clean_statistics", "before_key": "heading_pairs"},
            {"field": "Titles of Parts", "setting": "clean_statistics", "before_key": "titles_of_parts"},
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
            {"field": "Content Type", "setting": "clean_title", "before_key": "core_content_type"},
            {"field": "Created Date", "setting": "clean_created_date", "before_key": "created"},
            {"field": "Modified Date", "setting": "clean_modified_date", "before_key": "modified"},
            {"field": "Last Printed", "setting": "clean_last_printed", "before_key": "last_printed"},
            {"field": "Revision Number", "setting": "clean_revision_number", "before_key": "revision"},
            {"field": "Identifier", "setting": "clean_identifier", "before_key": "identifier"},
            {"field": "Language", "setting": "clean_language", "before_key": "language"},
            {"field": "Version", "setting": "clean_version", "before_key": "version"},
            {"field": "Rights (Copyright)", "setting": "clean_title", "before_key": "dc_rights"},
            {"field": "Publisher", "setting": "clean_title", "before_key": "dc_publisher"},
            {"field": "Type (DC)", "setting": "clean_title", "before_key": "dc_type"},
            {"field": "Format (DC)", "setting": "clean_title", "before_key": "dc_format"},
            {"field": "Source (DC)", "setting": "clean_title", "before_key": "dc_source"},
            {"field": "Relation (DC)", "setting": "clean_title", "before_key": "dc_relation"},
            {"field": "Coverage (DC)", "setting": "clean_title", "before_key": "dc_coverage"},
            {"field": "Issued Date", "setting": "clean_modified_date", "before_key": "dcterms_issued"},
            {"field": "Available Date", "setting": "clean_modified_date", "before_key": "dcterms_available"},
            {"field": "Valid Date", "setting": "clean_modified_date", "before_key": "dcterms_valid"},
        ],
        "Custom Properties": [
            {"field": "Custom Properties & Custom XML", "setting": "clean_custom_properties", "before_key": "custom_properties_xml"},
        ],
        "Document Structure": [
            {"field": "Visible Review Comments", "setting": "clean_review_comments_visible", "before_key": "review_comments_visible"},
            {"field": "Hidden/Resolved Review Comments", "setting": "clean_review_comments_hidden", "before_key": "review_comments_hidden"},
            {"field": "Track Changes", "setting": "clean_track_changes", "before_key": "track_changes"},
            {"field": "RSIDs", "setting": "clean_rsids", "before_key": "rsids"},
            {"field": "Document GUID", "setting": "clean_document_guid", "before_key": "document_guid"},
            {"field": "Spell/Grammar State", "setting": "clean_spell_grammar_state", "before_key": "proof_state"},
            {"field": "Document Variables", "setting": "clean_document_variables", "before_key": "doc_vars"},
            {"field": "Attached Template Path", "setting": "clean_template", "before_key": "attached_template"},
            {"field": "Document Protection", "setting": "clean_doc_security", "before_key": "document_protection"},
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
            {"field": "Embedded Files", "setting": "clean_ole_objects", "before_key": "embedded_files"},
            {"field": "Audio/Video Media", "setting": "clean_ole_objects", "before_key": "embedded_media"},
            {"field": "VBA Macros", "setting": "clean_vba_macros", "before_key": "vba_macros"},
            {"field": "Digital Signatures", "setting": "clean_digital_signatures", "before_key": "digital_signatures"},
            {"field": "Digital Signature Details", "setting": "clean_digital_signatures", "before_key": "digital_signature_details"},
            {"field": "Printer Settings", "setting": "clean_printer_settings", "before_key": "printer_settings"},
            {"field": "Printer Settings Details", "setting": "clean_printer_settings", "before_key": "printer_settings_parts"},
            {"field": "Embedded Fonts", "setting": "clean_embedded_fonts", "before_key": "embedded_fonts"},
            {"field": "Glossary/AutoText", "setting": "clean_glossary", "before_key": "glossary"},
            {"field": "Fast Save Data", "setting": "clean_fast_save_data", "before_key": "fast_save"},
            {"field": "Package Encryption", "setting": "clean_doc_security", "before_key": "encryption"},
        ],
        "Advanced Hardening": [
            {"field": "External Link Paths", "setting": "clean_external_links", "before_key": "external_links"},
            {"field": "Image EXIF Data", "setting": "clean_image_exif", "before_key": "image_exif"},
            {"field": "Custom Style Names", "setting": "clean_style_names", "before_key": "style_names"},
            {"field": "Chart Labels", "setting": "clean_chart_labels", "before_key": "chart_labels"},
            {"field": "Form Field Defaults", "setting": "clean_form_defaults", "before_key": "form_defaults"},
            {"field": "Language Settings", "setting": "clean_language_settings", "before_key": "language_settings"},
            {"field": "ActiveX Controls", "setting": "clean_activex", "before_key": "activex"},
            {"field": "Nuclear Option: Custom XML Parts", "setting": "clean_custom_xml_parts", "before_key": "custom_xml_parts"},
            {"field": "Nuclear Option: Non-Standard XML Namespaces", "setting": "clean_nonstandard_xml", "before_key": "non_standard_fields"},
            {"field": "Nuclear Option: Microsoft Extension Namespaces", "setting": "clean_microsoft_extension_xml", "before_key": "microsoft_extension_fields"},
            {"field": "Nuclear Option: Unknown Relationships", "setting": "clean_unknown_relationships", "before_key": "unknown_relationships"},
            {"field": "Nuclear Option: Orphaned Package Parts", "setting": "clean_orphaned_parts", "before_key": "orphaned_parts"},
            {"field": "Nuclear Option: Alternate Content Blocks", "setting": "clean_alternate_content", "before_key": "alternate_content"},
        ],
    }
    
    report = {
        "summary": {"total_cleaned": 0, "total_preserved": 0, "total_unchanged": 0},
        "groups": {},
    }
    if warnings:
        report["warnings"] = warnings
    
    # ========== STRUCTURED BINARY EXPORT ==========
    binary_exports = []
    large_exports = []
    binary_parts = before.get("_binary_parts") or []
    if report_dir and binary_parts:
        # Create structured binaries directory
        binaries_dir = os.path.join(report_dir, "binaries")
        type_dirs = {
            "image": "media",
            "thumbnail": "",
            "font": "fonts",
            "macro": "",
            "printer_settings": "",
            "ole_embedding": "ole",
            "activex": "activex",
        }
        
        large_threshold = 64 * 1024
        for part in binary_parts:
            part_name = part.get("name") or ""
            part_type = part.get("type") or "other"
            data = part.get("data")
            size = part.get("size") or (len(data) if data else 0)
            extension = part.get("extension") or os.path.splitext(part_name)[1].lower()
            if not data:
                continue

            is_binary_type = part_type in type_dirs or extension in (".bin", ".dat")
            is_large_embedded = (not is_binary_type) and size >= large_threshold
            if not is_binary_type and not is_large_embedded:
                continue

            # Determine subdirectory
            subdir = type_dirs.get(part_type, "other") if is_binary_type else "embedded"
            if subdir:
                out_dir = os.path.join(binaries_dir, subdir)
            else:
                out_dir = binaries_dir
            
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError:
                # Skip binary export if we can't create the directory (sandbox, permission issues)
                continue
            
            # Create safe filename
            safe_name = part_name.replace("/", "_").replace("\\", "_").lstrip("_")
            out_path = os.path.join(out_dir, safe_name)
            
            try:
                with open(out_path, "wb") as fh:
                    fh.write(data)
                rel_path = os.path.relpath(out_path, report_dir)
                export_entry = {
                    "name": part_name,
                    "type": part_type,
                    "path": rel_path,
                    "size": size,
                }
                if is_binary_type:
                    binary_exports.append(export_entry)
                else:
                    large_exports.append(export_entry)
            except Exception:
                continue
    
    # ========== FILE SUMMARY ==========
    input_file_info = dict(input_file_info or _safe_report_file_info(input_path))
    output_file_info = _safe_report_file_info(file_path or input_path)
    report["file_info"] = {
        "input": input_file_info,
        "output": output_file_info,
    }

    report["summary"].update({
        "scrub_datetime": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "file_name": input_file_info.get("file_name", ""),
        "file_extension": input_file_info.get("file_extension", ""),
        "mime_type": input_file_info.get("mime_type", ""),
        "size_bytes": input_file_info.get("size_bytes", ""),
        "input_sha256": input_file_info.get("sha256", ""),
        "metadata_preset": (lambda preset: preset if preset in {"maximum", "balanced", "none", "custom"} else (
            "none" if all(not getattr(settings, f.name) for f in fields(settings)) else
            "maximum" if all(getattr(settings, f.name) for f in fields(settings)) else
            "custom"
        ))(os.environ.get("MARCUT_METADATA_PRESET", "").strip().lower()),
    })
    report["summary"]["report_type"] = report["summary"].get("report_type", "scrub")

    if binary_exports:
        report["binary_exports"] = binary_exports
    if large_exports:
        report["large_exports"] = large_exports

    # ========== FORENSIC DEEP EXPLORER ==========
    def _build_deep_explorer(package_path: Optional[str], label: str) -> Optional[Dict[str, Any]]:
        if not report_dir or not package_path:
            return None
        try:
            import zipfile
            from lxml import etree
        except Exception:
            return None

        explorer_root = os.path.join(report_dir, "forensic_explorer", label)
        try:
            os.makedirs(explorer_root, exist_ok=True)
        except OSError:
            return None

        def _safe_output_path(root: str, entry_name: str) -> Optional[str]:
            normalized = entry_name.replace("\\", "/").lstrip("/")
            if not normalized:
                return None
            if normalized.startswith(".."):
                return None
            normalized = os.path.normpath(normalized)
            if normalized.startswith("..") or os.path.isabs(normalized):
                return None
            candidate = os.path.abspath(os.path.join(root, normalized))
            root_abs = os.path.abspath(root) + os.sep
            if not candidate.startswith(root_abs):
                return None
            return candidate

        def _read_content_types(zip_file: zipfile.ZipFile) -> Tuple[Dict[str, str], Dict[str, str]]:
            overrides: Dict[str, str] = {}
            defaults: Dict[str, str] = {}
            try:
                data = zip_file.read("[Content_Types].xml")
                root = etree.fromstring(data)
                for default in root.findall("Default"):
                    ext = (default.get("Extension") or "").lower()
                    ctype = default.get("ContentType") or ""
                    if ext:
                        defaults[f".{ext}"] = ctype
                for override in root.findall("Override"):
                    part_name = (override.get("PartName") or "").lstrip("/")
                    ctype = override.get("ContentType") or ""
                    if part_name:
                        overrides[part_name] = ctype
            except Exception:
                pass
            return overrides, defaults

        text_exts = {".xml", ".rels", ".txt", ".csv", ".tsv", ".json", ".md", ".html", ".htm", ".rtf"}
        parts: List[Dict[str, Any]] = []
        raw_text_rel_path = os.path.join("forensic_explorer", label, "_raw_text_index.txt")
        raw_text_path = os.path.join(report_dir, raw_text_rel_path)

        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                overrides, defaults = _read_content_types(zf)
                with open(raw_text_path, "w", encoding="utf-8") as raw_out:
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        name = info.filename
                        try:
                            data = zf.read(name)
                        except Exception:
                            continue
                        size = len(data)
                        ext = os.path.splitext(name)[1].lower()
                        content_type = overrides.get(name) or defaults.get(ext, "")
                        is_text = ext in text_exts or content_type.endswith(("xml", "+xml")) or content_type.startswith("text/")
                        text_content = ""
                        if is_text:
                            try:
                                text_content = data.decode("utf-8", errors="replace")
                            except Exception:
                                text_content = ""
                            raw_out.write(f"----- {name} -----\n")
                            raw_out.write(text_content)
                            raw_out.write("\n\n")

                        out_path = _safe_output_path(explorer_root, name)
                        if not out_path:
                            continue
                        try:
                            os.makedirs(os.path.dirname(out_path), exist_ok=True)
                            with open(out_path, "wb") as fh:
                                fh.write(data)
                        except Exception:
                            continue

                        parts.append({
                            "name": name,
                            "path": os.path.relpath(out_path, report_dir),
                            "size": size,
                            "content_type": content_type,
                            "extension": ext,
                            "is_text": is_text,
                            "text": text_content if is_text else "",
                        })
        except Exception:
            return None

        return {
            "label": label,
            "raw_text_path": raw_text_rel_path,
            "parts": parts,
        }

    deep_explorer = {}
    pre_explorer = _build_deep_explorer(input_path, "pre_scrub")
    if pre_explorer:
        deep_explorer["pre"] = pre_explorer
    if report["summary"].get("report_type") != "metadata_only":
        post_explorer = _build_deep_explorer(file_path or input_path, "post_scrub")
        if post_explorer:
            deep_explorer["post"] = post_explorer
    if deep_explorer:
        report["deep_explorer"] = deep_explorer

    # ========== FORENSIC ANALYSIS ==========
    try:
        forensic_findings = _perform_forensic_analysis(before, after)
        forensic_error = None
    except Exception as e:
        forensic_findings = []
        forensic_error = str(e)
    report["forensic_findings"] = {
        "count": len(forensic_findings),
        "findings": forensic_findings,
    }
    if forensic_error:
        report["forensic_findings"]["error"] = forensic_error

    if "encryption" not in before:
        before["encryption"] = _detect_encryption(input_path)
    if "encryption" not in after:
        after["encryption"] = _detect_encryption(file_path or input_path)
    
    # ========== PROCESS GROUPS ==========
    for group_name, group_fields in groups.items():
        group_data = []
        for field_info in group_fields:
            field_name = field_info["field"]
            setting_attr = field_info["setting"]
            before_key = field_info.get("before_key")
            
            was_enabled = getattr(settings, setting_attr, False)
            before_val = before.get(before_key, "") if before_key else "(complex data)"
            after_val = after.get(before_key, "") if before_key else ("" if was_enabled else "(preserved)")

            if before_key == "custom_properties_xml":
                before_val = _custom_properties_payload(before)
                after_val = _custom_properties_payload(after)
            elif before_key == "document_versions":
                before_val = _summarize_parts(before_val, "parts")
                after_val = _summarize_parts(after_val, "parts")
            elif before_key == "ink_annotations":
                before_val = _summarize_parts(before_val, "ink parts")
                after_val = _summarize_parts(after_val, "ink parts")
            
            # Serialize for JSON output
            before_serialized = _serialize_value(before_val)
            after_serialized = _serialize_value(after_val)

            # Determine actual status based on whether values changed
            if was_enabled:
                if before_serialized != after_serialized:
                    report["summary"]["total_cleaned"] += 1
                    status = "cleaned"
                else:
                    report["summary"]["total_unchanged"] += 1
                    status = "unchanged"
            else:
                report["summary"]["total_preserved"] += 1
                status = "preserved" if before_serialized == after_serialized else "observed"
            
            group_data.append({
                "field": field_name,
                "before": before_serialized,
                "after": after_serialized,
                "status": status
            })
        
        report["groups"][group_name] = group_data
    
    return report



def scrub_metadata_only(
    input_path: str,
    output_path: str,
    debug: bool = False,
) -> Tuple[bool, str, Optional[dict]]:
    """
    Scrub metadata only - no rules or LLM redaction.
    """
    try:
        # 1. Parse Args
        metadata_args_str = os.environ.get("MARCUT_METADATA_ARGS", "")
        metadata_args = metadata_args_str.split() if metadata_args_str else []
        metadata_settings = MetadataCleaningSettings.from_environment(metadata_args)
        
        # Check for explicit 'None' preset flag for ultra-robust handling
        is_none_preset = "--preset-none" in metadata_args or "--preset-none" in metadata_args_str
        
        if debug:
            print(f"[MARCUT_PIPELINE] Input: {input_path}")
            print(f"[MARCUT_PIPELINE] Args: {metadata_args_str[:100]}...")
            print(f"[MARCUT_PIPELINE] is_none_preset: {is_none_preset}")

        # 2. Get Before Values (Read-Only)
        # Load just for reading - if this fails, document is likely already corrupt
        try:
            dm_original = DocxMap.load(input_path)
            before_values = _read_metadata_values(dm_original)
        except Exception as e:
            return (False, f"Failed to read input document (it may be corrupt): {e}", {})
        input_file_info = _safe_report_file_info(input_path)

        # 3. Decision Path
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if is_none_preset:
            # COPY PATH: Safe handling for None preset
            import shutil
            if debug:
                print(f"[MARCUT_PIPELINE] None preset: Copying file without processed save.")
            shutil.copy2(input_path, output_path)
            return (True, "", None)

        # 4. Scrubbing Path
        # Use a revision-accepted view only when cleaning track changes
        if metadata_settings.clean_track_changes:
            dm = DocxMap.load_accepting_revisions(input_path, debug=debug)
        else:
            dm = dm_original
        
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
        report = _build_scrub_report(
            before_values,
            after_values,
            metadata_settings,
            file_path=output_path,
            input_path=input_path,
            input_file_info=input_file_info,
            report_dir=output_dir,
            warnings=getattr(dm, "warnings", []) or None,
        )
        report["summary"]["report_type"] = "scrub"
        return (True, "", report)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return (False, f"Metadata scrub failed: {str(e)}", {})


def metadata_report_only(
    input_path: str,
    report_path: str,
    debug: bool = False,
) -> Tuple[bool, str, dict, str, str]:
    """
    Generate a read-only metadata report without modifying the document.

    Returns (success, error, report_dict, json_path, html_path).
    """
    del debug
    try:
        metadata_args_str = os.environ.get("MARCUT_METADATA_ARGS", "")
        metadata_args = metadata_args_str.split() if metadata_args_str else []
        metadata_settings = MetadataCleaningSettings.from_environment(metadata_args)

        # Load original document for read-only metadata extraction
        dm = DocxMap.load(input_path)
        before_values = _read_metadata_values(dm)
        input_file_info = _safe_report_file_info(input_path)

        # Build report using before values only
        report_dir = os.path.dirname(report_path)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        report = _build_scrub_report(
            before_values,
            before_values,
            metadata_settings,
            file_path=input_path,
            input_path=input_path,
            input_file_info=input_file_info,
            report_dir=report_dir,
        )
        total_observed = sum(len(grp or []) for grp in report.get("groups", {}).values())
        report["summary"]["total_cleaned"] = 0
        report["summary"]["total_preserved"] = 0
        report["summary"]["total_unchanged"] = 0
        report["summary"]["total_observed"] = total_observed
        report["summary"]["report_type"] = "metadata_only"

        for grp in report.get("groups", {}).values():
            for field in grp:
                field["after"] = ""
                field["status"] = "observed"

        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)

        try:
            from .report_html import generate_report_from_json_file
            html_path = generate_report_from_json_file(report_path)
            if not html_path or not os.path.exists(html_path):
                raise RuntimeError("HTML report generation did not produce a file")
        except Exception as html_err:
            print(f"[MARCUT_PIPELINE] Metadata HTML report generation failed: {html_err}")
            return False, f"Metadata HTML report generation failed: {html_err}", {}, "", ""

        return True, "", report, report_path, html_path
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, f"Metadata report failed: {str(e)}", {}, "", ""
