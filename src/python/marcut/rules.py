import os
import regex as re
from typing import List, Dict, Any, Optional, Set

# Lazy import to avoid circular dependency
_exclusion_patterns_cache = None

def _get_exclusion_patterns():
    """Lazily import exclusion patterns from model module."""
    global _exclusion_patterns_cache
    if _exclusion_patterns_cache is None:
        try:
            from .model import get_exclusion_patterns
            _exclusion_patterns_cache = get_exclusion_patterns
        except ImportError:
            # Fallback: no exclusion patterns
            _exclusion_patterns_cache = lambda: set()
    return _exclusion_patterns_cache()

def _is_excluded(text: str) -> bool:
    """Check if text matches any excluded pattern."""
    # Standardize input: strip common prefixes to match user intent
    # e.g. "The Company" -> "Company", "A Trust" -> "Trust"
    text_clean = re.sub(r'^(?:the|a|an|this|that|such|each|any)\s+', '', text.strip(), flags=re.IGNORECASE).strip()
    
    for pattern in _get_exclusion_patterns():
        if pattern.match(text_clean):
            return True
    return False

# Email pattern - comprehensive
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")

# Phone patterns - US and international
PHONE = re.compile(r"(?x)(?<!\d)(?:\+?\s?\d{1,3}[\s.\-\u2013\u2014\u2212]?)?(?:\(\d{3}\)|\d{3})[\s.\-\u2013\u2014\u2212]?\d{3}[\s.\-\u2013\u2014\u2212]?\d{4}(?!\d)")

# SSN pattern - only with proper formatting
SSN = re.compile(r"\b\d{3}[-\u2013\u2014\u2212]\d{2}[-\u2013\u2014\u2212]\d{4}\b")

# Improved currency/money pattern - supports bracketed forms and ISO codes
CURRENCY = re.compile(
    r"(?ix)"  # verbose + case-insensitive
    # ISO codes or currency symbols followed by amount (with optional brackets)
    r"(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|\$|£|€|¥)\s*\[?\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{1,2})?\]?|"
    # Common symbol-specific forms
    r"\$\s*\[?\d[\d,]*(?:\.\d{1,2})?\]?|"
    r"€\s*\[?\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?\]?|"
    r"£\s*\[?\d[\d,]*(?:\.\d{1,2})?\]?|"
    # Spelled-out amounts with currency words (supports multi-word like "Six Hundred Thousand Dollars")
    r"\b(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|and)"
    r"(?:\s+|-)){1,10}"
    r"(?:dollars?|euros?|pounds?|yen|yuan)\b"
)

# Percentage patterns - numeric and spelled-out
PERCENT = re.compile(
    r"(?ix)"
    # Numeric percentages: 0.06%, 5%, 12.5%, (0.06%), etc.
    r"\(?\d+(?:\.\d+)?\s*%\)?|"
    # Bracketed numeric percentages: [5]%
    r"\[\d+(?:\.\d+)?\]\s*%|"
    # Spelled-out percentages: "six-hundredths of one percent", "fifty percent", etc.
    r"\b(?:(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"hundredth|hundredths|thousandth|thousandths|tenth|tenths|"
    r"half|quarter|third|thirds|fourth|fourths|fifth|fifths|and|of|one)"
    r"(?:\s+|-)){1,10}"
    r"percent(?:age)?\b"
)

# Account numbers
ACCOUNT = re.compile(r"(?<!\d)(?:\d[ \-\u2013\u2014\u2212]?){8,20}(?!\d)")

# Credit card patterns (will validate with Luhn)
CARD = re.compile(r"(?<!\d)(?:\d[ \-\u2013\u2014\u2212]?){13,19}(?!\d)")

# URL pattern (handles schemes, www, and bare domains with paths), trailing punctuation trimmed later
URL = re.compile(
    r"""
    (
        (?:https?|ftp|sftp)://[^\s<>()]+ |
        mailto:[^\s<>()]+ |
        www\.[^\s<>()]+\.[a-z]{2,}(?:[^\s<>()]*)? |
        (?<!@)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s<>()]+)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# IP address pattern (IPv4)
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b")

# Comprehensive date patterns
def _compile_date_patterns() -> re.Pattern:
    """Compile comprehensive date detection patterns."""
    month_names = (
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    )
    
    patterns = [
        # Numeric date formats
        r"\b\d{1,2}[/\-\u2013\u2014\u2212]\d{1,2}[/\-\u2013\u2014\u2212]\d{2,4}\b",
        r"\b\d{4}[/\-\u2013\u2014\u2212]\d{1,2}[/\-\u2013\u2014\u2212]\d{1,2}\b",
        r"\b\d{1,2}[.]\d{1,2}[.]\d{2,4}\b",
        r"\b\d{1,2}\s*[./\-\u2013\u2014\u2212]\s*\d{1,2}\s*[./\-\u2013\u2014\u2212]\s*\d{2,4}\b",
        
        # ISO formats
        r"\b\d{4}[-\u2013\u2014\u2212]\d{2}[-\u2013\u2014\u2212]\d{2}\b",
        r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?\b",
        
        # Month name patterns
        rf"(?i)\b(?:{month_names})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,\s*|\s+)\d{{2,4}}\b",
        rf"(?i)\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{month_names})(?:,\s*|\s+)\d{{2,4}}\b",
        rf"(?i)\b(?:{month_names})\s+\d{{4}}\b",
        
        # Placeholder dates (common in legal docs)
        rf"(?i)\b(?:{month_names})\s+___+,?\s*\d{{4}}\b",
        r"\b__+[/\-\u2013\u2014\u2212]__+[/\-\u2013\u2014\u2212]\d{2,4}\b",
        r"\b\d{1,2}[/\-\u2013\u2014\u2212]__+[/\-\u2013\u2014\u2212]\d{2,4}\b",
        
        # "Day of" pattern
        rf"(?i)\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)?\s+day\s+of\s+(?:{month_names}),?\s*\d{{4}}\b",
    ]
    
    return re.compile("|".join(patterns), re.IGNORECASE)

DATE = _compile_date_patterns()

# NUMBER pattern - bracketed numeric quantities (not preceded by a currency symbol)
NUMBER_BRACKET = re.compile(r"(?<![$€£¥])\[(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\]")

# Company suffix pattern for basic org detection
# Company suffix pattern for basic org detection
# Simpler, backtracking-safe company pattern
# Structure: [CapWord]+ [suffix]
# Where CapWord can be a capitalized word or a connector followed by a capitalized word
# Using a flatter structure to avoid catastrophic backtracking
COMPANY_SUFFIX = re.compile(
    # Simple, backtracking-safe company pattern
    r"\b"
    r"(?=[A-Z])"  # Optimization: Fail immediately if not Capitalized start
    r"(?:"
        r"(?:"
            r"[A-Z][\w'&.-]+"       # Capitalized Word
            r"|"
            r"(?:and|of|the|for|a|an|&|de|la)"  # Connector (lowercase)
        r")"
        r",?\s+"                    # Required space (with optional comma) after each token
    r"){1,10}"                      # Scan 1 to 10 tokens forward
    r"(?:"
    r"(?i:Incorporated|Corporation|Company|Limited)|"
    r"(?i:Inc)\.?|(?i:Corp)\.?|(?i:Co)\.?|(?i:Ltd)\.?|"
    r"(?i:Limited\s+Liability\s+Company)|L\.L\.C\.|LLC|L\.C\.|LC|"
    r"(?i:Limited\s+Liability\s+Partnership)|L\.L\.P\.|LLP|"
    r"(?i:Limited\s+Partnership)|L\.P\.|LP|"
    r"(?i:General\s+Partnership)|G\.P\.|GP|"
    r"(?i:Professional\s+Corporation)|P\.C\.|PC|"
    r"(?i:Professional\s+Association)|P\.A\.|PA|"
    r"(?i:Federal\s+Savings\s+Bank)|FSB|"
    r"(?i:National\s+Association)|N\.A\.|"
    r"(?i:National\s+Bank|Bank)|"
    r"(?i:Trust\s+Company)|"
    r"Capital|Holdings|Group|Fund|"
    r"(?i:Statutory\s+Trust|Business\s+Trust)|REIT|Trust|"
    r"(?i:Foundation|Association|Society|Institute)|"
    r"GmbH|AG|S\.A\.|B\.V\.|N\.V\.|(?i:PLC|p\.l\.c\.)"
    r")"
    r"(?!\w)"
)

# Address patterns - Strict Anchor strategy to avoid over-redaction
def _compile_address_patterns() -> re.Pattern:
    # 1. Standard US Block: Number + Street Name + Suffix + State Code + Zip
    # e.g. "123 Main St., New York, NY 10001" or "712 Main Street, Floor 5, Houston, Texas 77002"
    
    # State abbreviations (ISO 3166-2:US)
    state_abbrevs = (
        r"A[LKSZRAEP]|C[AOT]|D[EC]|F[LM]|G[AU]|HI|I[ADLN]|K[SY]|LA|M[ADEHINOPST]|"
        r"N[CDEHJMVY]|O[HKR]|P[ARW]|RI|S[CD]|T[NX]|UT|V[AIT]|W[AIVY]"
    )
    
    # Full state names (common ones - catches Texas, California, New York, etc.)
    state_names = (
        r"Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
        r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
        r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
        r"Nebraska|Nevada|New\s+Hampshire|New\s+Jersey|New\s+Mexico|New\s+York|"
        r"North\s+Carolina|North\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode\s+Island|"
        r"South\s+Carolina|South\s+Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
        r"West\s+Virginia|Wisconsin|Wyoming|District\s+of\s+Columbia"
    )
    
    # Combined state pattern (abbreviation OR full name)
    states = rf"(?:{state_abbrevs}|{state_names})"
    
    # Common street suffixes
    suffixes = (
        r"Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Court|Ct|"
        r"Circle|Cir|Terrace|Ter|Place|Pl|Apartment|Apt|Suite|Ste|Unit|Building|Bldg|Floor|Fl"
    )
    
    # Secondary unit prefixes (Apt, Suite, Floor, etc.)
    secondary_units = r"Apt|Apartment|Suite|Ste|Unit|Floor|Fl|Bldg|Building|#"

    p_standard = (
        r"\b\d+\s+"                         # House number
        r"[A-Z0-9][a-zA-Z0-9\s.]+\b"        # Street name - fixed to allow multi-word capitalized streets
        rf"(?:{suffixes})\.?,?\s+"          # Suffix + optional dot/comma
        rf"(?:(?:{secondary_units})\.?\s*\S+\s*,?\s*)?"  # Optional secondary unit + optional comma
        r"(?:[A-Za-z\s]+,?\s+)?"            # City (optional loose match)
        rf"(?:{states})\s+"                 # State (abbreviation OR full name)
        r"\d{5}(?:-\d{4})?"                 # Zip code
    )

    # 2. PO Box Pattern
    # e.g. "P.O. Box 123"
    p_pobox = r"(?i)\bP\.?O\.?\s+Box\s+\d+(?:,\s*[A-Za-z\s]+)?\b"

    # 3. Explicit Label Pattern (supports international)
    # e.g. "Address: 10 Downing St, London" - Relaxed to require just 1+ comma segments
    p_label = r"(?i)(?:Address|Residing at|Location):\s+([^\n,]+(?:,[^\n,]+){1,})"

    return re.compile("|".join([p_standard, p_pobox, p_label]))

ADDRESS = _compile_address_patterns()

# Signature block name detection - captures names following "Name:" patterns
SIGNATURE_NAME = re.compile(
    r"(?i)(?:^|\n)\s*Name:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)(?:\s{2,}([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+))?\s*(?:\n|$)",
    re.MULTILINE
)

# Alternative pattern to find individual names in signature lines
SIGNATURE_LINE = re.compile(
    r"(?i)(?:^|\n)\s*Name:\s*([^\n]+?)\s*(?:\n|$)",
    re.MULTILINE
)

# Pattern to validate if text looks like an individual person name
INDIVIDUAL_NAME = re.compile(
    r"^[A-Z][a-z]+(?:\s+(?:[A-Z][a-z]+|[A-Z]\.?))?\s+[A-Z][a-z]+$"
)

_RULE_FILTER_ENV = "MARCUT_RULE_FILTER"
SIGNATURE_RULE_LABEL = "SIGNATURE"
_RULE_FILTER_CACHE: Dict[str, Optional[Set[str]]] = {"raw": None, "labels": None}

def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", s)]
    if len(digits) < 13 or len(digits) > 19: return False
    checksum, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9: d -= 9
        checksum += d
    return checksum % 10 == 0

RULES = [
    ("EMAIL", EMAIL, 0.98, None),
    ("PHONE", PHONE, 0.96, None),
    ("SSN", SSN, 0.99, None),
    ("MONEY", CURRENCY, 0.90, None),
    ("PERCENT", PERCENT, 0.90, None),
    ("NUMBER", NUMBER_BRACKET, 0.70, None),
    ("DATE", DATE, 0.88, None),
    ("ACCOUNT", ACCOUNT, 0.80, None),
    ("CARD", CARD, 0.92, luhn_ok),
    ("URL", URL, 0.90, None),
    ("IP", IPV4, 0.90, None),
    # Basic org patterns only (names too error-prone for rules)
    ("ORG", COMPANY_SUFFIX, 0.75, None),
    # Strict address detection (Label maps to LOC downstream or directly here)
    ("LOC", ADDRESS, 0.85, None),
]

def _selected_rule_labels() -> Optional[Set[str]]:
    raw = os.environ.get(_RULE_FILTER_ENV)
    if raw == _RULE_FILTER_CACHE["raw"]:
        return _RULE_FILTER_CACHE["labels"]
    if raw is None:
        labels = None
    else:
        labels = {token.strip().upper() for token in raw.split(",") if token.strip()}
    _RULE_FILTER_CACHE["raw"] = raw
    _RULE_FILTER_CACHE["labels"] = labels
    return labels

def _rule_enabled(label: str, selected: Optional[Set[str]]) -> bool:
    if selected is None:
        return True
    return label.upper() in selected

def _is_generic_org(text: str) -> bool:
    """
    Check if an ORG match is generic and should NOT be redacted.
    
    Generic means:
    1. Just article + suffix: "The Company", "A Trust"
    2. Name portion consists entirely of connectors + excluded words:
       e.g. "Target Company", "Acquired LLC", "the Borrower Trust"
    
    This prevents over-redaction of legal defined terms.
    """
    parts = text.split()
    if len(parts) < 2:
        return False  # Single word like "Company" is handled by exclusion list
    
    # Define generic articles/connectors
    generic_connectors = {"the", "a", "an", "this", "that", "and", "of", "for", "de", "la"}
    
    # Get excluded words for checking (lazy-loaded from model module)
    excluded_patterns = _get_exclusion_patterns()
    
    def is_excluded_word(word: str) -> bool:
        """Check if a word matches any exclusion pattern."""
        word_clean = word.strip()
        for pattern in excluded_patterns:
            if pattern.match(word_clean):
                return True
        return False
    
    # Check all words except the last (which is the suffix)
    # If ALL of them are either connectors or excluded words, it's generic
    name_portion = parts[:-1]  # Everything except the suffix
    
    for word in name_portion:
        word_lower = word.lower().rstrip(",")
        if word_lower in generic_connectors:
            continue  # Connectors are always generic
        if is_excluded_word(word):
            continue  # Excluded words are treated as generic
        # Found a non-generic word - this is a real company name
        return False
    
    # All words in the name portion were generic
    return True

def run_rules(text: str) -> List[Dict[str,Any]]:
    out: List[Dict[str,Any]] = []
    selected = _selected_rule_labels()

    for label, rx, conf, extra in RULES:
        if not _rule_enabled(label, selected):
            continue
        for m in rx.finditer(text):
            s, e = m.span()
            sub = text[s:e]
            # Post-process URLs to strip trailing punctuation/brackets
            if label == "URL":
                trimmed = sub.rstrip(r".,;:!?)]}>\"'")
                # If we trimmed, adjust end index and substring
                if len(trimmed) != len(sub):
                    e = s + len(trimmed)
                    sub = trimmed
            if extra and not extra(sub):
                continue
            
            # Special logic for ORG matches to avoid over-redaction of defined terms
            if label == "ORG" and _is_generic_org(sub):
                continue

            # Filter out excluded terms (consistent with LLM pipeline)
            if label in ("ORG", "NAME", "LOC") and _is_excluded(sub):
                continue
            out.append({
                "start": s, "end": e, "label": label,
                "confidence": conf, "source": "rule", "text": sub
            })
    
    if _rule_enabled(SIGNATURE_RULE_LABEL, selected):
        # Special handling for signature block name extraction
        # Find all "Name:" lines and extract individual names from each line
        for line_match in SIGNATURE_LINE.finditer(text):
            line_text = line_match.group(1)  # The content after "Name:"
            line_start = line_match.start(1)  # Start of the content after "Name:"
            
            # Split on multiple spaces to separate names formatted with spacing
            potential_names = re.split(r'\s{2,}', line_text.strip())
            
            # Pre-compile regex for performance inside loop
            # INDIVIDUAL_NAME is already compiled at module level
            
            current_pos = 0
            for potential_name in potential_names:
                potential_name = potential_name.strip()
                
                # Check if this looks like a person's name (2-3 capitalized words)
                if potential_name and INDIVIDUAL_NAME.match(potential_name):
                    # Find the position of this name in the line
                    name_pos = line_text.find(potential_name, current_pos)
                    if name_pos != -1:
                        # Calculate absolute position in document
                        absolute_start = line_start + name_pos
                        absolute_end = absolute_start + len(potential_name)
                        
                        out.append({
                            "start": absolute_start,
                            "end": absolute_end,
                            "label": "NAME",
                            "confidence": 0.95,  # High confidence for signature blocks
                            "source": "rule_signature",
                            "text": potential_name
                        })
                        
                        current_pos = name_pos + len(potential_name)
    
    return out
