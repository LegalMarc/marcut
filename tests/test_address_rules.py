import sys
import os
sys.path.append(os.getcwd())
from marcut.rules import run_rules

def test_address_detection():
    print("=== Testing Address Rule ===")
    
    # Test Cases
    positive_cases = [
        "123 Main St., New York, NY 10001",           # Standard
        "456 Maple Avenue Apt 4B, Springfield IL 62704", # With unit
        "P.O. Box 789, Austin, TX",                   # PO Box
        "123 Sample St, Sample City, ST 12345-6789", # Zip+4
        "Address: 10 Downing Street, London"          # Label
    ]
    
    negative_cases = [
        "Section 123 of the Main Street Act",   # False pos trap
        "See page 55, line 2",                  # Numbers + text
        "The meeting in NY on Dec 5",           # State code but no address
        "1999 bubbles",                         # Just number + text
        "200 apples"                            # Just number + text
    ]
    
    # Run Positive Tests
    print("\n[POSITIVE TESTS - Should be detected]")
    passed_pos = 0
    for text in positive_cases:
        results = run_rules(text)
        address_found = any(r['label'] == 'LOC' and r['source'] == 'rule' for r in results)
        if address_found:
            print(f"✅ DETECTED: {text}")
            passed_pos += 1
        else:
            print(f"❌ MISSED:   {text}")
            
    # Run Negative Tests
    print("\n[NEGATIVE TESTS - Should NOT be detected]")
    passed_neg = 0
    for text in negative_cases:
        results = run_rules(text)
        address_found = any(r['label'] == 'LOC' and r['source'] == 'rule' for r in results)
        if not address_found:
            print(f"✅ PASSED:   {text}")
            passed_neg += 1
        else:
            # Check what was found
            found = [r['text'] for r in results if r['label'] == 'LOC']
            print(f"❌ WEAK:     {text} -> Found: {found}")

    print(f"\nSummary: {passed_pos}/{len(positive_cases)} Positive, {passed_neg}/{len(negative_cases)} Negative passed")

def test_address_rejects_invalid_state_codes():
    """Issue #41: the (non-labeled) address patterns must not match an invalid/fake
    2-letter state code -- e.g. "ZZ" is not a real state abbreviation or US territory
    code, so "123 Main St ZZ 12345" must not be detected as an address."""
    invalid_state_cases = [
        "123 Main St ZZ 12345",
        "123 Main St, Anytown, ZZ 12345",
        "123 Main St XX 12345",
        "123 Main St QQ 12345",
    ]
    for text in invalid_state_cases:
        results = run_rules(text)
        address_found = any(r['label'] == 'LOC' and r['source'] == 'rule' for r in results)
        assert not address_found, f"Unexpected address match for invalid state code: {text!r}"


def test_address_accepts_valid_state_and_territory_codes():
    """Regression guard: valid state/DC/territory codes must still be detected."""
    valid_state_cases = [
        "123 Main St, Anytown, PR 00901",   # Puerto Rico (territory)
        "123 Main St, Anytown, DC 20001",   # District of Columbia
        "123 Main St, Anytown, VI 00801",   # US Virgin Islands (territory)
    ]
    for text in valid_state_cases:
        results = run_rules(text)
        address_found = any(r['label'] == 'LOC' and r['source'] == 'rule' for r in results)
        assert address_found, f"Expected address match for valid state/territory code: {text!r}"


if __name__ == "__main__":
    test_address_detection()
