#!/usr/bin/env python3
"""
Create Human Review Checklist

Generates a personalized human review checklist based on test results.

Usage:
    python3 scripts/create_review_checklist.py --results-file test_results_24-11-06_14-30-00.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_test_results(results_file: Path) -> dict:
    """Load test results from JSON file"""
    try:
        with open(results_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"❌ Results file not found: {results_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in results file: {e}")
        sys.exit(1)


def generate_review_checklist(results: dict) -> str:
    """Generate human review checklist based on test results"""

    template_content = f"""# Marcut Test Suite - Human Review Checklist

## Test Run Information
- **Test Run ID**: {results['test_run_id']}
- **Review Date**: {datetime.now().strftime('%Y-%m-%d')}
- **Total Documents**: {results['summary']['total_files']}
- **System Info**: Python {results['system_info'].get('python_version', 'unknown')}, Ollama: {results['system_info'].get('ollama_status', 'unknown')}

## Configuration
- **AI Model**: {results['configuration'].get('ai_model', 'N/A')}
- **Enhanced Mode**: {results['configuration'].get('enhanced_mode', False)}
- **Debug Mode**: {results['configuration'].get('debug_mode', False)}

## Document Review Results

"""

    # Generate checklist for each document
    for i, result in enumerate(results['results'], 1):
        source_file = result['source_file']
        file_size = result.get('file_size', 0)

        # Get pathway results
        rules_result = result.get('rules_only', {})
        ai_result = result.get('ai', {})

        rules_status = rules_result.get('status', 'unknown')
        ai_status = ai_result.get('status', 'unknown' if ai_result else 'not_run')

        rules_entities = rules_result.get('entities_detected', 0)
        ai_entities = ai_result.get('entities_detected', 0) if ai_result else 0

        rules_time = rules_result.get('processing_time', 0)
        ai_time = ai_result.get('processing_time', 0) if ai_result else 0

        template_content += f"""### Document {i}: {Path(source_file).name}
- **Source File**: {source_file} ({file_size // 1024:,} KB)
- **Rules Only Output**: {Path(rules_result.get('output_file', '')).name if rules_result.get('output_file') else 'FAILED'}
- **AI Enhanced Output**: {Path(ai_result.get('output_file', '')).name if ai_result and ai_result.get('output_file') else 'NOT RUN'}
- **Rules Only**: {rules_entities} entities in {rules_time:.1f}s [{rules_status}]
- **AI Enhanced**: {ai_entities} entities in {ai_time:.1f}s [{ai_status}]

#### Redaction Quality Assessment

| Category | Rules Only | AI Enhanced | Notes |
|----------|------------|-------------|-------|
| **Name Detection** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Organization Detection** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Contact Information** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Financial Information** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Date/Time Information** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Legal Terms** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |

#### Document Integrity

| Aspect | Rules Only | AI Enhanced | Notes |
|--------|------------|-------------|-------|
| **Formatting Preserved** | □ Yes □ Partially □ No | □ Yes □ Partially □ No | |
| **Track Changes Quality** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Text Corruption** | □ None □ Minor □ Major | □ None □ Minor □ Major | |
| **Readability** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |
| **Redaction Consistency** | □ Excellent □ Good □ Fair □ Poor | □ Excellent □ Good □ Fair □ Poor | |

#### Specific Findings

**Rules Only Pathway:**
- ✅ **Strengths**:
- ❌ **Issues**:
- ⚠️ **Observations**:

**AI Enhanced Pathway:**
- ✅ **Strengths**:
- ❌ **Issues**:
- ⚠️ **Observations**:

#### Pathway Comparison

**Entity Detection:**
- Rules Only detected: {rules_entities} entities
- AI Enhanced detected: {ai_entities} entities
- Difference: {'AI detected ' + str(ai_entities - rules_entities) + ' more entities' if ai_entities > rules_entities else 'Rules Only detected ' + str(rules_entities - ai_entities) + ' more entities' if rules_entities > ai_entities else 'Equal detection'}

**Quality Assessment:**
- **More Accurate**: □ Rules Only □ AI Enhanced □ Equal
- **Better Context**: □ Rules Only □ AI Enhanced □ Equal
- **Fewer False Positives**: □ Rules Only □ AI Enhanced □ Equal
- **Recommended**: □ Rules Only □ AI Enhanced □ Depends on use case

#### Specific Examples

**Example 1: [Type of Detection]**
- Original: [Quote the original text here]
- Rules Only: [Show redaction result]
- AI Enhanced: [Show redaction result]
- Assessment: [Which was better and why]

**Example 2: [Type of Detection]**
- Original: [Quote the original text here]
- Rules Only: [Show redaction result]
- AI Enhanced: [Show redaction result]
- Assessment: [Which was better and why]

#### Recommendations for This Document

1. **Primary Recommendation**: □ Rules Only □ AI Enhanced □ Depends on use case
2. **Use Case**: [When to use which pathway]
3. **Quality Improvements Needed**: [Specific improvements]
4. **Comments**: [Additional notes]

---

"""

    # Add overall assessment section
    template_content += """## Overall Assessment

### Summary Statistics

| Document | Rules Only Score | AI Enhanced Score | Preferred Pathway | Key Issues |
|----------|------------------|-------------------|-------------------|------------|
"""

    for i, result in enumerate(results['results'], 1):
        doc_name = Path(result['source_file']).name
        template_content += f"| {doc_name} | [Score/10] | [Score/10] | [Preferred] | [Issues] |\n"

    template_content += """
### Pathway Strengths and Weaknesses

#### Rules Only Pathway
**Strengths:**
-
-
-

**Weaknesses:**
-
-
-

**Best Use Cases:**
-
-
-

#### AI Enhanced Pathway
**Strengths:**
-
-
-

**Weaknesses:**
-
-
-

**Best Use Cases:**
-
-
-

### Quality Issues Identified

#### Common Issues Across Documents
1. **Issue**: [Description]
   - **Frequency**: [Number of documents affected]
   - **Severity**: [Low/Medium/High]
   - **Recommendation**: [How to fix]

2. **Issue**: [Description]
   - **Frequency**: [Number of documents affected]
   - **Severity**: [Low/Medium/High]
   - **Recommendation**: [How to fix]

#### Document-Specific Issues
- **Document Name**: [Specific issue and recommendation]

### Performance Analysis

#### Processing Time vs Quality Trade-offs
- **Rules Only Average**: {:.1f}s → [Quality Score]/10
- **AI Enhanced Average**: {:.1f}s → [Quality Score]/10
- **Efficiency Winner**: [Pathway]
- **Quality Winner**: [Pathway]

#### Recommendations for Different Use Cases

| Use Case | Recommended Pathway | Rationale |
|----------|---------------------|-----------|
| **Quick Review** | [Pathway] | [Reason] |
| **Legal Documents** | [Pathway] | [Reason] |
| **Financial Documents** | [Pathway] | [Reason] |
| **High Volume Processing** | [Pathway] | [Reason] |
| **Maximum Accuracy** | [Pathway] | [Reason] |

### Final Recommendations

#### For Development Team
1. **Priority Improvements**:
   - [Improvement 1]
   - [Improvement 2]
   - [Improvement 3]

2. **Bug Fixes Needed**:
   - [Bug 1]
   - [Bug 2]

3. **Feature Enhancements**:
   - [Enhancement 1]
   - [Enhancement 2]

#### For Users
1. **When to Use Rules Only**:
   - [Scenario 1]
   - [Scenario 2]

2. **When to Use AI Enhanced**:
   - [Scenario 1]
   - [Scenario 2]

3. **Quality Assurance Tips**:
   - [Tip 1]
   - [Tip 2]

## Reviewer Certification

I certify that I have thoroughly reviewed all test outputs and provided accurate assessments based on the following criteria:

- [ ] All documents were opened and examined
- [ ] Redaction quality was assessed for both pathways
- [ ] Document integrity was verified
- [ ] Specific examples were documented
- [ ] Recommendations are based on observed evidence

**Reviewer Signature**: [Your Name]

**Date**: [Date]

---

## Instructions for Use

1. **Open each output file** in Microsoft Word or compatible viewer
2. **Review track changes** to see what was redacted
3. **Compare pathways** for the same source document
4. **Fill in checkboxes** with X marks for your selections
5. **Add specific examples** with quoted text and redaction results
6. **Provide detailed feedback** for development improvement

### Scoring Guidelines

**Redaction Quality (1-10 scale):**
- 10: Perfect redaction, all PII caught, no false positives
- 8-9: Excellent, minor issues only
- 6-7: Good, some missed PII or false positives
- 4-5: Fair, significant issues
- 1-3: Poor, major problems

**Document Integrity (1-10 scale):**
- 10: Perfect formatting, no corruption
- 8-9: Excellent, minor formatting issues
- 6-7: Good, some formatting problems
- 4-5: Fair, significant readability issues
- 1-3: Poor, major corruption issues
""".format(
        results['summary']['average_processing_time_rules'],
        results['summary']['average_processing_time_ai']
    )

    return template_content


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Create human review checklist from test results"
    )

    parser.add_argument(
        "--results-file", "-r",
        required=True,
        help="Path to test results JSON file"
    )

    parser.add_argument(
        "--output", "-o",
        help="Output file for checklist (default: stdout)"
    )

    args = parser.parse_args()

    # Load test results
    results_file = Path(args.results_file)
    results = load_test_results(results_file)

    # Generate checklist
    checklist = generate_review_checklist(results)

    # Output checklist
    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            f.write(checklist)
        print(f"✅ Review checklist saved: {output_path}")
    else:
        print(checklist)


if __name__ == "__main__":
    main()