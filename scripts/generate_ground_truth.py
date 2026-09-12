import sys
import os
import json
import time
import argparse
from pathlib import Path

# Add src/python to path so we can import marcut
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src', 'python'))

from marcut.unified_redactor import run_unified_redaction

def main():
    parser = argparse.ArgumentParser(description="Generate model-assisted ground truth JSONs for review")
    parser.add_argument('--input-dir', default='./.marcut_artifacts/ignored-resources/sample-files-marcut')
    parser.add_argument('--output-dir', default='./.marcut_artifacts/ground_truth')
    parser.add_argument('--model', default='qwen2.5:14b')
    args = parser.parse_args()

    input_dir = Path(os.path.abspath(args.input_dir))
    output_dir = Path(os.path.abspath(args.output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating Ground Truth using {args.model}...")
    
    docs = list(input_dir.glob('**/*.docx'))
    if not docs:
        print(f"No documents found in {input_dir}")
        return

    for doc in docs:
        out_json = output_dir / f"{doc.stem}_gt.json"
        
        if out_json.exists():
            print(f"Skipping {doc.name}, ground truth already exists.")
            continue
            
        print(f"Processing: {doc.name}")
        try:
            res = run_unified_redaction(
                input_path=str(doc),
                output_path=str(output_dir / f"{doc.stem}_temp.docx"),
                report_path=str(out_json),
                mode="enhanced",
                model=args.model,
                backend="ollama",
                debug=False,
                llm_concurrency=4
            )
            print(f"  -> Extracted {res.get('entity_count')} entities in {res.get('duration', 0):.2f}s.")
        except Exception as e:
            print(f"  -> Error processing {doc.name}: {e}")

if __name__ == "__main__":
    main()
