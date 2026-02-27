import os
import regex as re
from typing import List, Dict, Any, Optional, Set

# Lazy import to avoid circular dependency
_exclusion_data_cache = None

_RULE_SCAN_TRANSLATION_TABLE = str.maketrans({
    "\u2018": "'",  # left single quotation mark
    "\u2019": "'",  # right single quotation mark
    "\u201B": "'",  # single high-reversed-9 quotation mark
    "\u02BC": "'",  # modifier letter apostrophe
    "\uFF07": "'",  # fullwidth apostrophe
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2212": "-",  # minus sign
})
_RULE_SCAN_NORMALIZE_RE = re.compile(r"[\u2018\u2019\u201B\u02BC\uFF07\u2010-\u2014\u2212]")
_ACCOUNT_CONTEXT_RE = re.compile(
    r"(?i)\b(?:account\s+(?:number|no\.?|#)|acct\s+(?:number|no\.?|#)|iban|routing|aba|swift|bic|sort\s+code)\b"
)
# Phone label hints to reduce false positives for digit-only matches
_PHONE_CONTEXT_RE = re.compile(
    r"(?i)\b(?:phone|tel|telephone|mobile|cell|fax|call|ph\.?)\b"
)
# Fixed: removed anchor ^ to allow matching in window
_CURRENCY_TRAIL_RE = re.compile(r"\s*\(?[A-Z]{3}(?:\b|/)")


def _normalize_rule_scan_text(text: str) -> str:
    if not text:
        return text
    if _RULE_SCAN_NORMALIZE_RE.search(text):
        return text.translate(_RULE_SCAN_TRANSLATION_TABLE)
    return text


def _looks_like_account_context(text: str, start: int, end: int) -> bool:
    if not text:
        return False
    # Expanded window to 120 chars
    window_before = text[max(0, start - 120):start]
    if _ACCOUNT_CONTEXT_RE.search(window_before):
        return True
    window_after = text[end:min(len(text), end + 20)]
    if _CURRENCY_TRAIL_RE.match(window_after):
        return True
    return False

def _looks_like_phone_context(text: str, start: int, end: int) -> bool:
    if not text:
        return False
    window_before = text[max(0, start - 60):start]
    if _PHONE_CONTEXT_RE.search(window_before):
        return True
    window_after = text[end:min(len(text), end + 30)]
    if _PHONE_CONTEXT_RE.search(window_after):
        return True
    return False

def _get_exclusion_data():
    """Lazily import exclusion data from model module."""
    global _exclusion_data_cache
    if _exclusion_data_cache is None:
        try:
            from .model import (
                get_exclusion_data,
                _normalize_for_exclusion,
                _strip_leading_determiner,
                _matches_exclusion_literal,
                _DETERMINER_PREFIXES,
            )
            _exclusion_data_cache = (
                get_exclusion_data,
                _normalize_for_exclusion,
                _strip_leading_determiner,
                _matches_exclusion_literal,
                _DETERMINER_PREFIXES,
            )
        except ImportError:
            # Fallback: no exclusion data
            _exclusion_data_cache = (
                lambda: (set(), []),           # get_data
                lambda x: x.strip().lower(),   # normalize
                lambda x: x.strip(),           # strip_determiner
                lambda x, y: False,            # matches_literal (dummy)
                tuple(),                       # determiners
            )
    return _exclusion_data_cache


def _is_excluded(text: str) -> bool:
    """
    Check if text matches any excluded pattern.
    Optimized: O(1) set lookup for literals, then O(n) for regex patterns.
    Preserves article-stripping behavior (e.g., "The Company" -> "Company").
    """
    get_data, normalize, strip_determiner, matches_literal, _ = _get_exclusion_data()
    text_clean = strip_determiner(text)

    # Normalize for lookup
    normalized = normalize(text)
    literals, patterns = get_data()
    
    # Fast path: O(1) set lookup for the vast majority of exclusions
    if matches_literal and matches_literal(normalized, literals):
        return True
    
    if text_clean != text:
         normalized_clean = normalize(text_clean)
         if matches_literal and matches_literal(normalized_clean, literals):
             return True
         elif not matches_literal and normalized_clean in literals:
             return True

    if not matches_literal and normalized in literals:
        return True
    
    if normalize(text_clean) in literals:
        return True
    
    # Slow path: check regex patterns (should be rare)
    for pattern in patterns:
        if pattern.match(text_clean):
            return True
    
    return False


def _is_excluded_combo(text: str) -> bool:
    """
    Return True if the phrase can be segmented into excluded words/phrases and
    generic connectors/determiners.
    """
    if not text or not text.strip():
        return False

    # Negative lookbehind prevents splitting on "U.S.", "Mr.", "Mrs.", "Dr.", "St.", "Inc.", "Ltd."
    # Matches a period, followed by space(s), followed by an uppercase letter.
    if re.search(r"(?<!\b(?:[A-Z]|Mr|Mrs|Ms|Dr|St|Jr|Sr|Inc|Ltd))\.\s+[A-Z]", text):
        return True

    get_data, normalize, _, matches_literal, determiners = _get_exclusion_data()
    literals, patterns = get_data()

    if determiners:
        generic_connectors = set(determiners) | {"and", "or", "of", "for", "de", "la", "if"}
    else:
        generic_connectors = {
            "the", "a", "an", "this", "that", "such", "each", "any", "certain",
            "both", "all", "these", "those", "every", "either", "neither",
            "and", "or", "of", "for", "de", "la", "if",
            "&"
        }
    generic_connectors.add("&")

    tokens = re.findall(r"[A-Za-z0-9']+|&", text)
    if not tokens:
        return False

    tokens_norm = [t.lower() for t in tokens]
    if all(t in generic_connectors for t in tokens_norm):
        return True

    def phrase_matches(start: int, end: int) -> bool:
        phrase = " ".join(tokens_norm[start:end + 1]).strip()
        if not phrase:
            return False
        # Utilize _is_excluded logic indirectly or replicate cleanly
        # Replicating cleanly to avoid recursion loop or redundant parsing
        if matches_literal:
             if matches_literal(normalize(phrase), literals):
                 return True
        elif normalize(phrase) in literals:
            return True
            
        for pattern in patterns:
            # Need strict match for tokens?
            if pattern.match(phrase):
                return True
        return False

    n = len(tokens_norm)
    dp = [False] * (n + 1)
    dp[n] = True
    for i in range(n - 1, -1, -1):
        if tokens_norm[i] in generic_connectors and dp[i + 1]:
            dp[i] = True
            continue
        for j in range(i, n):
            if phrase_matches(i, j) and dp[j + 1]:
                dp[i] = True
                break

    return dp[0]


# Maximum length for ORG spans (mirrors pipeline.py _filter_overlong_org_spans)
_ORG_MAX_LENGTH = 60

# Jurisdiction tail that should not be part of an ORG span (e.g., ", a Delaware limited liability company")
_US_JURISDICTIONS = (
    r"Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
    r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
    r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
    r"Nebraska|Nevada|New\\s+Hampshire|New\\s+Jersey|New\\s+Mexico|New\\s+York|"
    r"North\\s+Carolina|North\\s+Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
    r"Rhode\\s+Island|South\\s+Carolina|South\\s+Dakota|Tennessee|Texas|Utah|"
    r"Vermont|Virginia|Washington|West\\s+Virginia|Wisconsin|Wyoming|"
    r"District\\s+of\\s+Columbia|D\\.C\\."
)
_JURISDICTION_TAIL_RE = re.compile(
    rf"(?ix)"
    rf"(?:,\\s*)?"
    rf"(?:a|an)\\s+"
    rf"(?:{_US_JURISDICTIONS})\\s+"
    rf"(?:"
        rf"limited\\s+liability\\s+company|"
        rf"limited\\s+liability\\s+partnership|"
        rf"limited\\s+partnership|"
        rf"general\\s+partnership|"
        rf"corporation|inc\\.?|company|"
        rf"llc|l\\.l\\.c\\.|l\\.c\\.|lc|"
        rf"llp|l\\.l\\.p\\.|"
        rf"lp|l\\.p\\.|"
        rf"plc|p\\.l\\.c\\.|"
        rf"statutory\\s+trust|business\\s+trust"
    rf")"
    rf"\\s*$"
)

# Entity suffixes containing periods that should NOT trigger sentence boundary detection
_ENTITY_SUFFIX_PERIODS = re.compile(
    r"(?:L\.L\.C\.|L\.L\.P\.|L\.P\.|G\.P\.|P\.C\.|P\.A\.|N\.A\.|S\.A\.S\.|S\.A\.|B\.V\.|N\.V\.|p\.l\.c\.)"
)


def _is_overlong_org_span(text: str) -> bool:
    """Return True if the ORG span exceeds the maximum allowed length."""
    return len(text) > _ORG_MAX_LENGTH


def _trim_org_jurisdiction_suffix(text: str) -> str:
    """
    Remove trailing jurisdiction clauses from ORG spans, e.g.:
    \"EXOS, LLC, a Delaware limited liability company\" -> \"EXOS, LLC\".
    Returns empty string if the span is only a jurisdiction clause.
    """
    if not text:
        return text
    match = _JURISDICTION_TAIL_RE.search(text)
    if not match:
        return text
    if match.start() == 0:
        return ""
    trimmed = text[:match.start()].rstrip(" ,;")
    return trimmed if trimmed else ""


def _contains_sentence_boundary(text: str) -> bool:
    """
    Return True if the text contains a sentence boundary (period followed by capital letter),
    excluding legal entity suffixes like L.L.C., P.A., etc.
    """
    # Remove known entity suffixes before checking
    cleaned = _ENTITY_SUFFIX_PERIODS.sub("", text)
    # Check for pattern: period + optional space + capital letter
    # This catches "Inc. We are" but not "Inc." at end of string
    return bool(re.search(r"(?<!\b(?:[A-Z]|Mr|Mrs|Ms|Dr|St|Jr|Sr|Inc|Ltd))\.\s+[A-Z]", cleaned))


# Email pattern - comprehensive
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")

# Phone patterns - US and international
PHONE_NANP = (
    r"(?<!\d)(?:\+?\s?\d{1,3}[\s.\-\u2013\u2014\u2212]?)?"
    r"(?:\(\d{3}\)|\d{3})[\s.\-\u2013\u2014\u2212]?\d{3}[\s.\-\u2013\u2014\u2212]?\d{4}(?!\d)"
)
PHONE_INTL = (
    r"(?<!\d)\+\s?\d{1,3}(?:[\s().\-\u2013\u2014\u2212]?\d){7,12}(?!\d)"
)
PHONE = re.compile(rf"(?x)(?:{PHONE_NANP}|{PHONE_INTL})")

# SSN pattern - only with proper formatting
SSN = re.compile(r"\b\d{3}[-\u2013\u2014\u2212]\d{2}[-\u2013\u2014\u2212]\d{4}\b")

# Improved currency/money pattern - supports bracketed forms and ISO codes
CURRENCY = re.compile(
    r"(?ix)"  # verbose + case-insensitive
    # Symbol/ISO with magnitude words (e.g., "$3 million", "USD 2.5 billion")
    r"(?:USD|EUR|GBP|CAD|AUD|JPY|CHF|\$|£|€|¥)\s*\[?\d[\d,]*(?:\.\d{1,2})?\]?\s*(?:thousand|million|billion|trillion)\b(?:\s*(?:dollars?|euros?|pounds?|yen|yuan))?|"
    # Numeric + magnitude + currency word (e.g., "3 million dollars")
    r"\b\d{1,3}(?:[\s.,]\d{3})*(?:[.,]\d{1,2})?\s*(?:thousand|million|billion|trillion)\s*(?:dollars?|euros?|pounds?|yen|yuan)\b|"
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

# SWIFT/BIC codes (8 or 11 chars, require at least one digit to reduce false positives)
SWIFT_BIC = re.compile(
    r"\b(?=[A-Z0-9]{8}(?:[A-Z0-9]{3})?\b)(?=[A-Z0-9]*\d)"
    r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"
)

# Credit card patterns (will validate with Luhn)
CARD = re.compile(r"(?<!\d)(?:\d[ \-\u2013\u2014\u2212]?){13,19}(?!\d)")

# URL pattern (handles schemes, www, and bare domains with paths)
URL = re.compile(
    r"""
    (
        (?:https?|ftp|sftp)://[^\s<>()]+ | # basic protocol
        mailto:[^\s<>()]+ |
        www\.[^\s<>()]+\.[a-z]{2,}[^\s<>()]* |
        (?<!@)(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}[^\s<>()]*
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# IP address pattern (IPv4)
IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b")
# IP address pattern (IPv6, including compressed and IPv4-mapped)
IPV6 = re.compile(
    r"""
    \b(
        (?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4} |
        (?:[A-Fa-f0-9]{1,4}:){1,7}: |
        :(?:[A-Fa-f0-9]{1,4}:){1,7} |
        (?:[A-Fa-f0-9]{1,4}:){1,6}:[A-Fa-f0-9]{1,4} |
        (?:[A-Fa-f0-9]{1,4}:){1,5}(?::[A-Fa-f0-9]{1,4}){1,2} |
        (?:[A-Fa-f0-9]{1,4}:){1,4}(?::[A-Fa-f0-9]{1,4}){1,3} |
        (?:[A-Fa-f0-9]{1,4}:){1,3}(?::[A-Fa-f0-9]{1,4}){1,4} |
        (?:[A-Fa-f0-9]{1,4}:){1,2}(?::[A-Fa-f0-9]{1,4}){1,5} |
        [A-Fa-f0-9]{1,4}:(?::[A-Fa-f0-9]{1,4}){1,6} |
        :(?::[A-Fa-f0-9]{1,4}){1,7} |
        (?:[A-Fa-f0-9]{1,4}:){1,4}:(?:\d{1,3}\.){3}\d{1,3}
    )\b
    """,
    re.VERBOSE,
)

# Document ID patterns for e-sign platforms and document management systems
# Covers: DocuSign, Adobe Sign, HelloSign, iManage, NetDocuments, Worldox, SharePoint, etc.
_DOCID_DOCUSIGN = r"(?:DocuSign|Docusign)\s+Envelope\s+ID:\s*[A-Fa-f0-9]{8}\s*-\s*[A-Fa-f0-9]{4}\s*-\s*[A-Fa-f0-9]{4}\s*-\s*[A-Fa-f0-9]{4}\s*-\s*[A-Fa-f0-9]{12}"
_DOCID_LABELED = r"(?:Document|Doc|File|Envelope|Agreement|Contract|Transaction|Reference|Ref|Case|Matter|Deal|Project)\s*(?:ID|Id|No\.?|Number|#|Ref|Reference)?:\s*[A-Za-z0-9][-A-Za-z0-9_.]{4,40}"
_DOCID_UUID = r"(?<![A-Za-z0-9])[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-[A-Fa-f0-9]{12}(?![A-Za-z0-9])"
_DOCID_VERSION = r"(?<![A-Za-z0-9])\d{7,12}(?:\s*[vV]\.?\s*\d{1,3}|\.\d{1,3})(?![A-Za-z0-9])"
_DOCID_PREFIX = r"\b(?:DOC|ENV|AGR|REF|CASE|MATTER|DEAL|FILE|PROJ|TXN|DMS|ND)[-:_#]?[A-Za-z0-9]{4,20}\b"

DOCID = re.compile(
    rf"(?:{_DOCID_DOCUSIGN})|(?:{_DOCID_LABELED})|(?:{_DOCID_UUID})|(?:{_DOCID_VERSION})|(?:{_DOCID_PREFIX})",
    re.IGNORECASE,
)

# Defined-term person pattern: Full Name (“Last”)
_DEFINED_TERM_NAME = re.compile(
    r"""
    (?P<full>[A-Z][A-Za-z'\-\.]+(?:\s+[A-Z][A-Za-z'\-\.]+){1,2})   # Full name (2-3 words)
    \s*\(\s*["“”](?P<short>[A-Z][A-Za-z'\-\.]+)["”]\s*\)          # Short defined term in quotes
    """,
    re.VERBOSE,
)

# Comprehensive date patterns
def _compile_date_patterns() -> re.Pattern:
    """Compile comprehensive date detection patterns."""
    month_names = (
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    )
    placeholder_token = r"(?:_{1,}|[\u2022\u25CF\u25CB\u25A0\u25A1]+|[ \t]{2,})"
    placeholder_bracket = r"\[\s*[_\u2022\u25CF\u25CB\u25A0\u25A1]*\s*\]"
    placeholder_any = rf"(?:{placeholder_token}|{placeholder_bracket})"
    placeholder_day = placeholder_any
    placeholder_year = rf"(?:_{2,4}|[\u2022\u25CF\u25CB\u25A0\u25A1]{{2,4}}|{placeholder_bracket}|[ \t]{{2,}})"
    date_sep = r"[./\-\u2013\u2014\u2212]"
    
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
        rf"(?i)\b(?:{month_names})(?:\s+|\s*,\s*)\d{{4}}\b",
        
        # Placeholder dates (common in legal docs)
        rf"(?i)\b(?:{month_names})\s+{placeholder_day}(?:\s*,\s*|\s+)\d{{4}}\b",
        r"\b__+[/\-\u2013\u2014\u2212]__+[/\-\u2013\u2014\u2212]\d{2,4}\b",
        r"\b\d{1,2}[/\-\u2013\u2014\u2212]__+[/\-\u2013\u2014\u2212]\d{2,4}\b",
        rf"(?<!\w){placeholder_any}\s*{date_sep}\s*(?:\d{{1,2}}|{placeholder_any})\s*{date_sep}\s*(?:\d{{2,4}}|{placeholder_year})(?!\w)",
        rf"(?<!\w)\d{{1,2}}\s*{date_sep}\s*{placeholder_any}\s*{date_sep}\s*(?:\d{{2,4}}|{placeholder_year})(?!\w)",
        rf"(?<!\w)\d{{1,2}}\s*{date_sep}\s*\d{{1,2}}\s*{date_sep}\s*{placeholder_year}(?!\w)",
        rf"(?<!\w)\d{{2,4}}\s*{date_sep}\s*{placeholder_any}\s*{date_sep}\s*(?:\d{{1,2}}|{placeholder_any})(?!\w)",
        rf"(?<!\w)\d{{2,4}}\s*{date_sep}\s*\d{{1,2}}\s*{date_sep}\s*{placeholder_any}(?!\w)",
        rf"(?<!\w){placeholder_year}\s*{date_sep}\s*(?:\d{{1,2}}|{placeholder_any})\s*{date_sep}\s*(?:\d{{1,2}}|{placeholder_any})(?!\w)",
        
        # "Day of" pattern
        rf"(?i)\b(?:the\s+)?\d{{1,2}}(?:st|nd|rd|th)?\s+day\s+of\s+(?:{month_names}),?\s*\d{{4}}\b",
    ]
    
    return re.compile("|".join(patterns), re.IGNORECASE)

DATE = _compile_date_patterns()

# NUMBER pattern - bracketed numeric quantities (not preceded by a currency symbol)
NUMBER_BRACKET = re.compile(r"(?<![$€£¥])\[(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?\]")

# Company suffix pattern for basic org detection
# Structure: [CapWord]+ [suffix]
# Where CapWord can be a capitalized word or a connector followed by a capitalized word
COMPANY_SUFFIX = re.compile(
    # Simple, backtracking-safe company pattern
    r"\b"
    r"(?=[A-Z])"  # Optimization: Fail immediately if not Capitalized start
        r"(?:"
            r"(?:"
            r"[A-Z][\w'&.-]+"       # Capitalized Word
            r"|"
            r"\d+[A-Za-z0-9'&.-]*"  # Numeric token (e.g., 123, 123A)
            r"|"
            r"(?i:and|of|the|for|a|an|&|de|la)"  # Connector (case-insensitive)
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
    # Extended International Suffixes
    r"GmbH|AG|S\.A\.S\.|S\.A\.|S\.R\.L\.|Sp\.\s+z\s+o\.o\.|B\.V\.|N\.V\.|(?i:PLC|p\.l\.c\.)"
    r")"
    r"(?!\w)"
)

# Address patterns - Strict Anchor strategy to avoid over-redaction
def _compile_address_patterns() -> re.Pattern:
    # 1. Standard US Block: Number + Street Name + Suffix + State Code + Zip
    
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
        r"Street|St|Road|Rd|Avenue|Ave|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|"
        r"Place|Pl|Terrace|Ter|Way|Parkway|Pkwy|Circle|Cir|Loop|Crescent|Cres|"
        r"Square|Sq|Alley|Aly|Plaza|Plz|Highway|Hwy|Freeway|Fwy|Expressway|Expy|"
        r"Turnpike|Tpke|Causeway|Cswy|Trail|Trl|Path|Walk|Row|Mews|Close|Cl|"
        r"Gardens|Gdns|Esplanade|Esp|Promenade|Prom|Quay|Wharf|Embankment|Emb|"
        r"Mall|Via|Route|Rte|Byway|Bywy|Spur|Cutoff|Crossing|Xing|Trace|Trce|"
        r"Apartment|Apt|Suite|Ste|Unit|Building|Bldg|Floor|Fl"
    )

    # Secondary unit prefixes (Apt, Suite, Floor, etc.)
    secondary_units = r"Apt|Apartment|Suite|Ste|Unit|Floor|Fl|Bldg|Building|#"
    secondary_block = rf"(?:(?:{secondary_units})\.?\s*\S+|\S+\s*(?:{secondary_units})\.?)"

    no_suffix_literals = [
        "Broadway", "The Strand", "The Mall", "The Bowery", "The High Line", "Wall", "Canal",
        "Fleet", "Piccadilly", "Lombard", "Hollywood", "Sunset", "Market", "Mission",
        "Valencia", "Causeway", "Esplanade", "Promenade", "Boardwalk", "Embankment",
        "Walk", "Way", "Via Appia", "Via del Corso", "Beacon", "Liberty", "Union",
        "Central", "Victory", "Heritage",
    ]
    no_suffix_patterns = [
        r"King(?:'|\u2019)s Way",
        r"Queen(?:'|\u2019)s Walk",
        r"Champs[-\s](?:Elysees|\u00c9lys\u00e9es)",
    ]
    no_suffix = "|".join([re.escape(name) for name in no_suffix_literals] + no_suffix_patterns)

    # Use atomic groups (?>...) for performance if feasible in 'regex' module
    p_standard = (
        r"(?>"
        r"\b\d+\s+"                         # House number
        r"[A-Z0-9][a-zA-Z0-9\s.]+\b"        # Street name - fixed to allow multi-word capitalized streets
        rf"(?:{suffixes})\.?,?\s+"          # Suffix + optional dot/comma
        rf"(?:(?:{secondary_block})\s*,?\s*)?"  # Optional secondary unit + optional comma
        r"(?:[A-Za-z\s]+,?\s+)?"            # City (optional loose match)
        rf"(?:{states})\s+"                 # State (abbreviation OR full name)
        r"\d{5}(?:-\d{4})?"                 # Zip code
        r")"
    )

    p_no_suffix = (
        r"(?>"
        r"\b\d+\s+"                         # House number
        rf"(?:{no_suffix})\b,?\s+"          # No-suffix street name + optional comma
        rf"(?:(?:{secondary_block})\s*,?\s*)?"  # Optional secondary unit + optional comma
        r"(?:[A-Za-z\s]+,?\s+)?"            # City (optional loose match)
        rf"(?:{states})\s+"                 # State (abbreviation OR full name)
        r"\d{5}(?:-\d{4})?"                 # Zip code
        r")"
    )

    # 2. PO Box Pattern
    # e.g. "P.O. Box 123"
    p_pobox = r"(?i)\bP\.?O\.?\s+Box\s+\d+(?:,\s*[A-Za-z\s]+)?\b"

    # 3. Explicit Label Pattern (supports international)
    # e.g. "Address: 10 Downing St, London" - Relaxed to require just 1+ comma segments
    p_label = r"(?i)(?:Address|Residing at|Location):\s+([^\n,]+(?:,[^\n,]+){1,})"

    return re.compile("|".join([p_standard, p_no_suffix, p_pobox, p_label]))

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
    ("SWIFT", SWIFT_BIC, 0.92, None),
    ("CARD", CARD, 0.92, luhn_ok),
    ("URL", URL, 0.90, None),
    ("IP", IPV4, 0.90, None),
    ("IP", IPV6, 0.90, None),
    # Document IDs from e-sign platforms (DocuSign, Adobe Sign) and DMS (iManage, NetDocuments, Worldox)
    ("DOCID", DOCID, 0.95, None),
    # Basic org patterns only (names too error-prone for rules)
    ("ORG", COMPANY_SUFFIX, 0.75, None),
    # Strict address detection (Label maps to LOC downstream or directly here)
    ("LOC", ADDRESS, 0.85, None),
    # County/Parish/Borough names as standalone locations
    (
        "LOC",
        re.compile(
            r"(?ix)"
            r"(?:"
                r"(?:[A-Z][A-Za-z'’-]{1,30}\s+){0,2}[A-Z][A-Za-z'’-]{1,30}\s+(?:County|Parish|Borough)"
                r"|"
                r"(?:County|Parish|Borough)\s+of\s+(?:[A-Z][A-Za-z'’-]{1,30}\s+){0,2}[A-Z][A-Za-z'’-]{1,30}"
            r")"
        ),
        0.82,
        None,
    ),
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

def _is_generic_org_span(text: str) -> bool:
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
    
    get_data, normalize, _, matches_literal, determiners = _get_exclusion_data()
    if determiners:
        generic_connectors = set(determiners) | {"and", "of", "for", "de", "la", "if"}
    else:
        generic_connectors = {
            "the", "a", "an", "this", "that", "such", "each", "any", "certain",
            "both", "all", "these", "those", "every", "either", "neither",
            "and", "of", "for", "de", "la", "if",
        }
    
    # Get exclusion data (optimized: set for literals, list for regex)
    literals, patterns = get_data()
    
    def is_excluded_word(word: str) -> bool:
        """Check if a word matches any exclusion pattern. O(1) for literals."""
        word_clean = word.strip()
        normalized = normalize(word_clean)
        
        # Fast path: O(1) set lookup
        if matches_literal and matches_literal(normalized, literals):
            return True
        elif not matches_literal and normalized in literals:
            return True
        
        # Slow path: check regex patterns (rare)
        for pattern in patterns:
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
    scan_text = _normalize_rule_scan_text(text)

    for label, rx, conf, extra in RULES:
        if not _rule_enabled(label, selected):
            continue
        for m in rx.finditer(scan_text):
            s, e = m.span()
            sub = text[s:e]
            label_out = label
            conf_out = conf
            
            # Post-process URLs to strip trailing punctuation/brackets
            # NOTE: URL regex is now tighter, but we verify anyway for safety
            if label == "URL":
                trimmed = sub.rstrip(r".,;:!?)]}>\"'")
                if len(trimmed) != len(sub):
                    e = s + len(trimmed)
                    sub = trimmed
                
            if extra and not extra(sub):
                continue

            if label == "PHONE":
                if sub.isdigit() and _rule_enabled("ACCOUNT", selected):
                    if _looks_like_account_context(scan_text, s, e):
                        continue
                if sub.isdigit() and not _looks_like_phone_context(scan_text, s, e):
                    if _rule_enabled("NUMBER", selected):
                        label_out = "NUMBER"
                        conf_out = 0.70
                    else:
                        continue
            
            # Special logic for ORG matches to avoid over-redaction of defined terms
            if label == "ORG":
                trimmed = _trim_org_jurisdiction_suffix(sub)
                if trimmed != sub:
                    if not trimmed:
                        continue
                    e = s + len(trimmed)
                    sub = trimmed
                # Reject spans that are too long (likely captured sentence fragments)
                if _is_overlong_org_span(sub):
                    continue
                # Reject spans containing sentence boundaries (period + capital)
                if _contains_sentence_boundary(sub):
                    continue
                # Reject generic defined terms like "the Company"
                if _is_generic_org_span(sub):
                    continue

            # Filter out excluded terms (consistent with LLM pipeline)
            if label in ("ORG", "NAME", "LOC") and _is_excluded(sub):
                continue
            
            # For ORG matches, trim any excluded phrase prefix (e.g., "FOR VALUE RECEIVED,")
            if label == "ORG":
                # Split on comma and check if leading segments are excluded phrases
                segments = re.split(r',\s*', sub)
                if len(segments) > 1:
                    # Check each prefix segment to see if it's an excluded phrase
                    trim_count = 0
                    for seg in segments[:-1]:  # Don't check the last segment (the actual company)
                        seg_clean = seg.strip()
                        if seg_clean and _is_excluded(seg_clean):
                            trim_count += 1
                        else:
                            break  # Stop at first non-excluded segment
                    
                    if trim_count > 0:
                        # Calculate actual prefix length in original text
                        # Find position of the segment we want to keep
                        trimmed_text = ", ".join(segments[trim_count:])
                        # Find where this trimmed portion starts in the original sub
                        trim_start = sub.find(segments[trim_count])
                        if trim_start > 0:
                            s = s + trim_start
                            e = s + len(trimmed_text)
                            sub = trimmed_text
                        
                        # Re-check if the trimmed result is now generic
                        if _is_generic_org_span(sub) or _is_excluded(sub):
                            continue
                        
            out.append({
                "start": s, "end": e, "label": label_out,
                    "confidence": conf_out, "source": "rule", "text": sub
                })
    
    # Defined-term person fallback: Full Name (“Last”) -> emit both full and short NAME spans
    for m in _DEFINED_TERM_NAME.finditer(scan_text):
        full = m.group("full")
        short = m.group("short")
        if not full or not short:
            continue
        full_tokens = full.split()
        if not full_tokens:
            continue
        full_last = full_tokens[-1].strip(".'-")
        short_clean = short.strip(".'-")
        if full_last.lower() != short_clean.lower():
            continue

        fs, fe = m.span("full")
        ss, se = m.span("short")
        try:
            full_text = text[fs:fe]
            short_text = text[ss:se]
        except Exception:
            continue

        out.append({
            "start": fs,
            "end": fe,
            "label": "NAME",
            "confidence": 0.90,
            "source": "rule_defined_term",
            "text": full_text,
        })
        out.append({
            "start": ss,
            "end": se,
            "label": "NAME",
            "confidence": 0.88,
            "source": "rule_defined_term",
            "text": short_text,
        })

    if _rule_enabled(SIGNATURE_RULE_LABEL, selected):
        # Special handling for signature block name extraction
        # Find all "Name:" lines and extract individual names from each line
        for line_match in SIGNATURE_LINE.finditer(scan_text):
            line_start = line_match.start(1)  # Start of the content after "Name:"
            line_end = line_match.end(1)
            line_text = scan_text[line_start:line_end]  # The content after "Name:"
            
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
                        original_name = text[absolute_start:absolute_end]
                        
                        out.append({
                            "start": absolute_start,
                            "end": absolute_end,
                            "label": "NAME",
                            "confidence": 0.95,  # High confidence for signature blocks
                            "source": "rule_signature",
                            "text": original_name
                        })
                        
                        current_pos = name_pos + len(potential_name)
    
    return out
