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
        "77 Massachusetts Ave, Cambridge, MA 02139-4307", # Zip+4
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

if __name__ == "__main__":
    test_address_detection()
