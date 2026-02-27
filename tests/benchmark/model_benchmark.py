"""
Model Benchmark Test Rig

Compares LLM model speed vs accuracy for document redaction.
Supports both Ollama models and GGUF files directly.

Usage:
    # Test Ollama models
    python -m tests.benchmark.model_benchmark \
        --doc "sample-files/Sample 123 Preservation Letter track changes.docx" \
        --models llama3.1:8b,llama3.2:3b
    
    # Test all GGUF files in a directory
    python -m tests.benchmark.model_benchmark \
        --doc "sample-files/Sample 123 Preservation Letter track changes.docx" \
        --models-dir "/path/to/models"
"""

import argparse
import glob
import json
import os
import sys
import time
from typing import List, Dict, Any, Tuple, Optional

# Ensure marcut is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Default app models directory
DEFAULT_MODELS_DIR = os.path.expanduser(
    "~/Library/Application Support/MarcutApp/models"
)


def load_document_text(doc_path: str) -> str:
    """Load document and extract text."""
    from docx import Document
    doc = Document(doc_path)
    return '\n'.join([p.text for p in doc.paragraphs])


def load_ground_truth(truth_path: str) -> List[Dict[str, Any]]:
    """Load expected entities from ground truth JSON."""
    with open(truth_path, 'r') as f:
        data = json.load(f)
    return data.get('expected_entities', [])


def discover_gguf_models(models_dir: str) -> List[str]:
    """Find all GGUF files in a directory."""
    if not os.path.exists(models_dir):
        return []
    pattern = os.path.join(models_dir, "*.gguf")
    return sorted(glob.glob(pattern))


def run_ollama_extraction(
    model_id: str, 
    text: str, 
    custom_prompt: Optional[str] = None
) -> Tuple[List[Dict], Dict[str, float]]:
    """Run extraction via Ollama API with timing."""
    if custom_prompt:
        os.environ['MARCUT_SYSTEM_PROMPT_PATH'] = custom_prompt
    elif 'MARCUT_SYSTEM_PROMPT_PATH' in os.environ:
        del os.environ['MARCUT_SYSTEM_PROMPT_PATH']
    
    from marcut.llm_timing import ollama_extract_with_timing
    from marcut.model import _SYSTEM_PROMPT_CACHE
    
    _SYSTEM_PROMPT_CACHE['path'] = None
    _SYSTEM_PROMPT_CACHE['mtime'] = None
    
    return ollama_extract_with_timing(model_id, text, temperature=0.1, seed=42)


def run_gguf_extraction(
    model_path: str,
    text: str,
    custom_prompt: Optional[str] = None
) -> Tuple[List[Dict], Dict[str, float]]:
    """Run extraction via llama.cpp with timing."""
    if custom_prompt:
        os.environ['MARCUT_SYSTEM_PROMPT_PATH'] = custom_prompt
    elif 'MARCUT_SYSTEM_PROMPT_PATH' in os.environ:
        del os.environ['MARCUT_SYSTEM_PROMPT_PATH']
    
    from marcut.model import llama_cpp_extract, get_system_prompt, _map_label, _find_entity_spans
    
    timing = {
        "prompt_build": 0.0, "http_request": 0.0, "ollama_model_load": 0.0,
        "ollama_prompt_eval": 0.0, "ollama_generation": 0.0, "network_overhead": 0.0,
        "response_parse": 0.0, "entity_locate": 0.0, "prompt_tokens": 0, "output_tokens": 0,
    }
    
    t_start = time.perf_counter()
    spans = llama_cpp_extract(model_path, text, temperature=0.1, seed=42, threads=4)
    timing['http_request'] = time.perf_counter() - t_start  # Total time (misnamed but consistent)
    
    # Add text field to spans if missing
    for sp in spans:
        if 'text' not in sp:
            sp['text'] = text[sp['start']:sp['end']]
    
    return spans, timing


def run_extraction(
    model_id: str, 
    text: str, 
    custom_prompt: Optional[str] = None,
    is_gguf: bool = False
) -> Tuple[List[Dict], Dict[str, float]]:
    """Run extraction with timing. Returns (spans, timing_dict)."""
    if is_gguf:
        return run_gguf_extraction(model_id, text, custom_prompt)
    else:
        return run_ollama_extraction(model_id, text, custom_prompt)


def calculate_metrics(
    predicted: List[Dict], 
    expected: List[Dict],
    fuzzy: bool = True
) -> Dict[str, float]:
    """Calculate precision, recall, F1."""
    if fuzzy:
        pred_set = {(e['text'], e['label']) for e in predicted}
        exp_set = {(e['text'], e['label']) for e in expected}
    else:
        pred_set = {(e['text'], e['label'], e['start'], e['end']) for e in predicted}
        exp_set = {(e['text'], e['label'], e['start'], e['end']) for e in expected}
    
    true_positives = len(pred_set & exp_set)
    false_positives = len(pred_set - exp_set)
    false_negatives = len(exp_set - pred_set)
    
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) > 0 else 0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
    
    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'true_positives': true_positives,
        'false_positives': false_positives,
        'false_negatives': false_negatives,
    }


def check_ollama() -> bool:
    """Check if Ollama is running."""
    import requests
    try:
        resp = requests.get('http://127.0.0.1:11434/api/tags', timeout=5)
        return resp.status_code == 200
    except:
        return False


def get_available_ollama_models() -> List[str]:
    """Get list of models installed in Ollama."""
    import requests
    try:
        resp = requests.get('http://127.0.0.1:11434/api/tags', timeout=5)
        data = resp.json()
        return [m['name'] for m in data.get('models', [])]
    except:
        return []


def format_results_table(results: List[Dict], ground_truth_count: int):
    """Print formatted results table."""
    print()
    print("=" * 85)
    print(f"{'Model':<25} {'Avg Time':>10} {'F1':>8} {'Prec':>8} {'Recall':>8} {'Speedup':>10}")
    print("=" * 85)
    
    baseline_time = results[0]['avg_time'] if results else 1.0
    
    for r in results:
        speedup = baseline_time / r['avg_time'] if r['avg_time'] > 0 else 0
        model_name = r['model'][:24]  # Truncate for display
        print(f"{model_name:<25} {r['avg_time']:>9.2f}s {r['f1']:>7.2f} {r['precision']:>7.2f} {r['recall']:>7.2f} {speedup:>9.1f}x")
    
    print("=" * 85)
    print(f"Ground truth: {ground_truth_count} entities")
    
    if len(results) > 1:
        best_speedup = max(results[1:], key=lambda x: (baseline_time / x['avg_time']) if x['avg_time'] > 0 else 0)
        if best_speedup['f1'] >= 0.8:
            speedup = baseline_time / best_speedup['avg_time']
            print(f"\n💡 Recommended: {best_speedup['model']} ({speedup:.1f}x faster, F1={best_speedup['f1']:.2f})")


def main():
    parser = argparse.ArgumentParser(description='Model Benchmark Test Rig')
    parser.add_argument('--doc', required=True, help='Path to test document')
    parser.add_argument('--truth', help='Path to ground truth JSON')
    parser.add_argument('--models', help='Comma-separated list of Ollama models to test')
    parser.add_argument('--models-dir', help=f'Directory containing GGUF files (default: {DEFAULT_MODELS_DIR})')
    parser.add_argument('--runs', type=int, default=1, help='Number of runs per model')
    parser.add_argument('--prompt', help='Path to custom system prompt file')
    parser.add_argument('--json', help='Output results to JSON file')
    args = parser.parse_args()
    
    # Determine which models to test
    models_to_test = []  # List of (name, path_or_id, is_gguf)
    
    if args.models_dir or (not args.models):
        # Auto-discover GGUF files
        models_dir = args.models_dir or DEFAULT_MODELS_DIR
        gguf_files = discover_gguf_models(models_dir)
        if gguf_files:
            print(f"📂 Found {len(gguf_files)} GGUF files in: {models_dir}")
            for gguf in gguf_files:
                name = os.path.basename(gguf)
                models_to_test.append((name, gguf, True))
        else:
            print(f"⚠️  No GGUF files found in: {models_dir}")
    
    if args.models:
        # Also test specified Ollama models
        if not check_ollama():
            print("⚠️  Ollama is not running - skipping Ollama models")
        else:
            available = get_available_ollama_models()
            for model in [m.strip() for m in args.models.split(',')]:
                if model in available:
                    models_to_test.append((model, model, False))
                else:
                    print(f"⚠️  Ollama model '{model}' not installed")
    
    if not models_to_test:
        print("❌ No models to test. Use --models or --models-dir", file=sys.stderr)
        sys.exit(1)
    
    # Load document
    if not os.path.exists(args.doc):
        print(f"❌ Document not found: {args.doc}", file=sys.stderr)
        sys.exit(1)
    
    print(f"\n📄 Loading document: {args.doc}")
    text = load_document_text(args.doc)
    print(f"   {len(text)} chars, {len(text.split())} words")
    
    # Load ground truth
    truth_path = args.truth
    if not truth_path:
        default_truth = os.path.join(os.path.dirname(__file__), 'ground_truth', 'preservation_letter.json')
        if os.path.exists(default_truth):
            truth_path = default_truth
    
    if truth_path and os.path.exists(truth_path):
        print(f"📋 Loading ground truth: {truth_path}")
        ground_truth = load_ground_truth(truth_path)
        print(f"   {len(ground_truth)} expected entities")
    else:
        print("⚠️  No ground truth - timing only")
        ground_truth = []
    
    if args.prompt:
        if not os.path.exists(args.prompt):
            print(f"❌ Prompt file not found: {args.prompt}", file=sys.stderr)
            sys.exit(1)
        print(f"📝 Using custom prompt: {args.prompt}")
    
    # Run benchmarks
    print(f"\n🚀 Running benchmark ({args.runs} run(s) per model)...\n")
    results = []
    
    for name, path_or_id, is_gguf in models_to_test:
        print(f"Testing {name}...", end=' ', flush=True)
        
        times = []
        all_spans = None
        timing_detail = None
        error = None
        
        for run in range(args.runs):
            try:
                spans, timing = run_extraction(path_or_id, text, args.prompt, is_gguf=is_gguf)
                times.append(timing['http_request'])
                if all_spans is None:
                    all_spans = spans
                    timing_detail = timing
            except Exception as e:
                error = str(e)
                break
        
        if error:
            print(f"ERROR: {error[:50]}...")
            continue
        
        avg_time = sum(times) / len(times) if times else 0
        
        if ground_truth:
            metrics = calculate_metrics(all_spans or [], ground_truth)
        else:
            metrics = {'precision': 0, 'recall': 0, 'f1': 0}
        
        result = {
            'model': name,
            'path': path_or_id,
            'is_gguf': is_gguf,
            'avg_time': avg_time,
            'min_time': min(times) if times else 0,
            'max_time': max(times) if times else 0,
            'entities_found': len(all_spans or []),
            'precision': metrics['precision'],
            'recall': metrics['recall'],
            'f1': metrics['f1'],
            'prompt_tokens': timing_detail.get('prompt_tokens', 0) if timing_detail else 0,
            'output_tokens': timing_detail.get('output_tokens', 0) if timing_detail else 0,
        }
        results.append(result)
        
        print(f"{avg_time:.2f}s, F1={metrics['f1']:.2f}, found {len(all_spans or [])} entities")
    
    # Output table
    if results:
        format_results_table(results, len(ground_truth))
    
    # JSON output
    if args.json:
        output_data = {
            'document': args.doc,
            'prompt': args.prompt,
            'ground_truth_count': len(ground_truth),
            'results': results
        }
        with open(args.json, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\n📁 Results saved to: {args.json}")


if __name__ == '__main__':
    main()
