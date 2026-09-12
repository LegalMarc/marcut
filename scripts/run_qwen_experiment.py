import sys
import os
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Set

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src', 'python'))
from marcut.unified_redactor import run_unified_redaction

MODELS = ["phi4-mini:3.8b", "qwen2.5:7b", "qwen2.5:14b", "qwen3.5:35b"]

def load_spans(report_path: Path) -> List[Dict]:
    if not report_path.exists():
        return []
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('spans', [])
    except Exception:
        return []

def extract_base_entities(spans: List[Dict]) -> Set[str]:
    # We use lowercase text and label as the strict identifier for F1 score
    return set(f"{span.get('text', '').strip().lower()}|{span.get('label', '')}" for span in spans)

def calculate_metrics(test_spans: List[Dict], gt_spans: List[Dict]):
    test_set = extract_base_entities(test_spans)
    gt_set = extract_base_entities(gt_spans)
    
    if not gt_set:
        return 1.0, 1.0, 1.0  # Avoid division by zero if empty doc
    
    true_positives = len(test_set.intersection(gt_set))
    false_positives = len(test_set - gt_set)
    false_negatives = len(gt_set - test_set)
    
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    return precision, recall, f1

def main():
    parser = argparse.ArgumentParser(description="Run Qwen3.5 PII Extraction Experiment")
    parser.add_argument('--input-dir', default='./.marcut_artifacts/ignored-resources/sample-files-marcut')
    parser.add_argument('--gt-dir', default='./.marcut_artifacts/ground_truth')
    parser.add_argument('--out-csv', default='docs/LLM_UPGRADE_EXPERIMENT_RESULTS.csv')
    args = parser.parse_args()

    input_dir = Path(os.path.abspath(args.input_dir))
    gt_dir = Path(os.path.abspath(args.gt_dir))
    
    if not gt_dir.exists():
        print(f"Error: Ground truth directory not found: {gt_dir}")
        print("Please run generate_ground_truth.py first, and review the outputs.")
        sys.exit(1)

    docs = list(input_dir.glob('*.docx'))
    print(f"Found {len(docs)} documents for testing.")
    
    schema = {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "classification": {"type": "string", "enum": ["FULL_REDACT", "SKIP", "PARTIAL_REDACT", "CONTEXT_DEPENDENT"]},
                        "confidence": {"type": "number"},
                        "explanation": {"type": "string"}
                    },
                    "required": ["id", "classification", "confidence"]
                }
            }
        },
        "required": ["results"]
    }

    configs = [
        {"desc": "Standard", "think": False, "format": None},
        {"desc": "Constraint", "think": False, "format": schema},
        {"desc": "Thinking", "think": True, "format": None},
    ]

    results = []

    for model in MODELS:
        print(f"\nEvaluating Model: {model}")
        for config in configs:
            print(f"  Configuration: {config['desc']}")
            
            f1_scores = []
            durations = []
            
            for doc in docs:
                gt_path = gt_dir / f"{doc.stem}_gt.json"
                gt_spans = load_spans(gt_path)
                
                temp_report = Path(f"/tmp/report_{doc.stem}.json")
                temp_doc = Path(f"/tmp/out_{doc.stem}.docx")
                
                try:
                    res = run_unified_redaction(
                        input_path=str(doc),
                        output_path=str(temp_doc),
                        report_path=str(temp_report),
                        mode="enhanced",
                        model=model,
                        backend="ollama",
                        debug=False,
                        llm_concurrency=4,
                        think_mode=config["think"],
                        format_schema=config["format"]
                    )
                    
                    test_spans = load_spans(temp_report)
                    p, r, f1 = calculate_metrics(test_spans, gt_spans)
                    f1_scores.append(f1)
                    durations.append(res.get('duration', 0))
                    
                except Exception as e:
                    print(f"    Error on {doc.name}: {e}")
            
            avg_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0
            avg_dur = sum(durations) / len(durations) if durations else 0
            print(f"    Average F1: {avg_f1:.2f} | Average Latency: {avg_dur:.2f}s")
            
            results.append({
                "model": model,
                "config": config["desc"],
                "avg_f1": avg_f1,
                "latency_s": avg_dur
            })

    # Save to CSV
    with open(args.out_csv, 'w') as f:
        f.write("Model,Config,Avg_F1,Latency_s\n")
        for r in results:
            f.write(f"{r['model']},{r['config']},{r['avg_f1']:.3f},{r['latency_s']:.2f}\n")
    print(f"\nExperiment complete. Results saved to {args.out_csv}")

if __name__ == "__main__":
    main()
