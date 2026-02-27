"""
Mock LLM module that simulates what Ollama would detect.
This is for demonstration purposes when Ollama is not available.
"""

from typing import List, Dict, Any
import re
import random

# Common patterns that an LLM would recognize
NAME_PATTERNS = [
    # Common first names that might appear in legal documents
    r'\b(John|Jane|James|Mary|Robert|Michael|William|David|Richard|Joseph|Thomas|Charles|Christopher|Daniel|Matthew|Mark|Paul|Steven|Peter|Jerry|Lisa|Sarah|Jennifer|Jessica|Amy|Michelle|Kimberly|Emily|Ashley|Melissa|Mikael|Erik|Eriksson|Peterson|Johnson|Smith|Brown|Davis|Wilson|Anderson|Thompson|Martinez|Robinson|Clark|Lewis|Lee|Walker|Hall|Allen|King|Wright|Scott|Green|Baker|Adams|Nelson|Carter|Mitchell|Roberts|Turner|Phillips|Campbell|Parker|Evans|Edwards|Collins)\b',
    # Title + Name patterns
    r'\b(Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.|Judge|Attorney|Director|Officer|President|CEO|CFO|CTO|Chairman|Secretary|Treasurer)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?',
    # Full name patterns
    r'\b[A-Z][a-z]+\s+(?:[A-Z]\.\s+)?[A-Z][a-z]+\b',
]

ORG_PATTERNS = [
    # Company suffixes
    r'\b[A-Z][a-zA-Z\s&]+(?:\s+(?:Inc\.?|LLC|Corp\.?|Corporation|Ltd\.?|Limited|LP|LLP|Co\.?|Company|Group|Holdings|Enterprises|Solutions|Services|Technologies|Systems|International|Global|Worldwide|Industries|Ventures|Capital|Partners|Associates|Consulting|Management|Bank|Trust|Financial|Insurance|Realty|Properties|Development|Manufacturing|Distribution|Logistics|Healthcare|Medical|Pharmaceutical|Biotech|Energy|Resources|Retail|Marketing|Media|Entertainment|Communications|Telecom|Software|Digital|Interactive|Networks|Securities|Investments|Advisors|Law Firm|LLP|PC|PA))\b',
    # Specific company names that might appear
    r'\b(Smartfrog|Acme|Apple|Google|Microsoft|Amazon|Facebook|Tesla|Oracle|IBM|Intel|Cisco|Adobe|Salesforce|Netflix|Twitter|Uber|Airbnb|Spotify|PayPal|Square|Stripe|Zoom|Slack|Dropbox|Box|DocuSign|Workday|ServiceNow|Snowflake|Databricks|Palantir|SpaceX|Boeing|Lockheed|Northrop|Raytheon|General\s+(?:Electric|Motors|Dynamics)|Bank\s+of\s+America|Wells\s+Fargo|JPMorgan|Goldman\s+Sachs|Morgan\s+Stanley|Citigroup|Barclays|Deutsche\s+Bank|Credit\s+Suisse|UBS|HSBC|BNP\s+Paribas|Societe\s+Generale|State\s+Street|BlackRock|Vanguard|Fidelity|Charles\s+Schwab)\b',
    # Generic organization indicators
    r'\b(?:the\s+)?(?:Company|Corporation|Firm|Entity|Organization|Institution|Agency|Department|Division|Bureau|Office|Committee|Commission|Board|Council|Authority|Administration)\b',
]

LOCATION_PATTERNS = [
    # US States
    r'\b(California|New\s+York|Texas|Florida|Illinois|Pennsylvania|Ohio|Georgia|North\s+Carolina|Michigan|New\s+Jersey|Virginia|Washington|Arizona|Massachusetts|Tennessee|Indiana|Missouri|Maryland|Wisconsin|Colorado|Minnesota|South\s+Carolina|Alabama|Louisiana|Kentucky|Oregon|Oklahoma|Connecticut|Utah|Iowa|Nevada|Arkansas|Mississippi|Kansas|New\s+Mexico|Nebraska|West\s+Virginia|Idaho|Hawaii|New\s+Hampshire|Maine|Montana|Rhode\s+Island|Delaware|South\s+Dakota|North\s+Dakota|Alaska|Vermont|Wyoming)\b',
    # Countries
    r'\b(United\s+States|USA|US|America|Canada|Mexico|United\s+Kingdom|UK|England|Scotland|Wales|Ireland|France|Germany|Spain|Italy|Netherlands|Belgium|Switzerland|Austria|Sweden|Norway|Denmark|Finland|Poland|Russia|China|Japan|Korea|India|Australia|Brazil|Argentina)\b',
    # Cities
    r'\b(New\s+York\s+City|Los\s+Angeles|Chicago|Houston|Phoenix|Philadelphia|San\s+Antonio|San\s+Diego|Dallas|San\s+Jose|Austin|Jacksonville|Fort\s+Worth|Columbus|San\s+Francisco|Charlotte|Indianapolis|Seattle|Denver|Washington\s+DC|Boston|El\s+Paso|Detroit|Nashville|Portland|Memphis|Oklahoma\s+City|Las\s+Vegas|Louisville|Baltimore|Milwaukee|Albuquerque|Tucson|Fresno|Mesa|Sacramento|Atlanta|Kansas\s+City|Colorado\s+Springs|Miami|Raleigh|Omaha|Long\s+Beach|Virginia\s+Beach|Oakland|Minneapolis|Tulsa|Arlington|Tampa|New\s+Orleans)\b',
]

def mock_llm_extract(text: str, temperature: float = 0.0, seed: int = 42) -> List[Dict[str, Any]]:
    """
    Simulate LLM extraction of entities from text.
    This mimics what phi4:mini-instruct would detect.
    """
    random.seed(seed)
    results = []
    
    # Extract names
    for pattern in NAME_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Skip common legal terms that aren't actually names
            if match.group().lower() in ['the', 'and', 'or', 'of', 'in', 'to', 'for', 'by', 'with', 'from', 'attorney', 'director', 'officer', 'president', 'secretary', 'treasurer']:
                continue
            
            results.append({
                "start": match.start(),
                "end": match.end(),
                "label": "NAME",
                "text": match.group(),
                "confidence": 0.85 + random.random() * 0.1
            })
    
    # Extract organizations
    for pattern in ORG_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            # Skip if it's just "the Company" or similar generic terms without context
            text_lower = match.group().lower()
            if text_lower in ['the company', 'the corporation', 'the firm', 'the entity']:
                # Check if it's capitalized in a way that suggests it's a defined term
                if match.group()[0].isupper() or 'Company' in match.group():
                    # This is likely a defined term referring to a specific entity
                    results.append({
                        "start": match.start(),
                        "end": match.end(),
                        "label": "ORG",
                        "text": match.group(),
                        "confidence": 0.75
                    })
            else:
                results.append({
                    "start": match.start(),
                    "end": match.end(),
                    "label": "ORG",
                    "text": match.group(),
                    "confidence": 0.80 + random.random() * 0.15
                })
    
    # Extract locations
    for pattern in LOCATION_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            results.append({
                "start": match.start(),
                "end": match.end(),
                "label": "LOC",
                "text": match.group(),
                "confidence": 0.90 + random.random() * 0.08
            })
    
    # Extract dates that rules might miss (written dates)
    date_patterns = [
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b',
        r'\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b',
    ]
    for pattern in date_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            results.append({
                "start": match.start(),
                "end": match.end(),
                "label": "DATE",
                "text": match.group(),
                "confidence": 0.92
            })
    
    # Remove duplicates and overlapping spans
    results = remove_overlaps(results)
    
    return results

def remove_overlaps(spans: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove overlapping spans, keeping the longer or higher confidence ones."""
    if not spans:
        return []
    
    # Sort by start position, then by span length (longer first)
    spans = sorted(spans, key=lambda x: (x["start"], -(x["end"] - x["start"])))
    
    kept = []
    for span in spans:
        # Check if this span overlaps with any kept span
        overlaps = False
        for kept_span in kept:
            if (span["start"] < kept_span["end"] and span["end"] > kept_span["start"]):
                # They overlap - keep the one with higher confidence or longer span
                if span["confidence"] > kept_span["confidence"] or \
                   (span["end"] - span["start"]) > (kept_span["end"] - kept_span["start"]):
                    # Replace the kept span with this one
                    kept.remove(kept_span)
                    kept.append(span)
                overlaps = True
                break
        
        if not overlaps:
            kept.append(span)
    
    return kept
