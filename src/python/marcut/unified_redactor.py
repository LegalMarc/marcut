#!/usr/bin/env python3
"""
Unified Redactor Module for MarcutApp

Single entry point for both GUI and CLI redaction operations.
Provides consistent behavior, logging, and error handling across all interfaces.
"""

import sys
import json
import os
import traceback
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root and bundled deps to path for imports, enforcing order to avoid stray package roots
project_root = Path(__file__).parent.parent
python_site_candidates = [
    project_root / "MarcutApp" / "Sources" / "MarcutApp" / "python_site",
]
python_stdlib = project_root / "MarcutApp" / "Sources" / "MarcutApp" / "Resources" / "python_stdlib"

# Start from existing sys.path to retain stdlib, then prepend our preferred roots
clean_path = []
for p in sys.path:
    name = Path(p).name.lower()
    # Drop direct marcut package roots and older embedded python_site copies under Contents
    if name == "marcut":
        continue
    if "Contents/Resources/python_site" in p:
        continue
    clean_path.append(p)

# Ensure bundled python_site takes precedence
primary_site = str(project_root / "MarcutApp" / "Sources" / "MarcutApp" / "python_site")
clean_path = [entry for entry in clean_path if "Contents/Resources/python_site" not in entry]
if primary_site in clean_path:
    clean_path.remove(primary_site)
clean_path.insert(0, primary_site)

prepends = [str(project_root)]
for candidate in python_site_candidates:
    if candidate.exists():
        prepends.append(str(candidate))
if python_stdlib.exists():
    prepends.append(str(python_stdlib))
# Prepend while preserving order and avoiding duplicates
for entry in reversed(prepends):
    if entry not in clean_path:
        clean_path.insert(0, entry)
sys.path = clean_path
if os.environ.get("MARCUT_DEBUG_PATH") == "1":
    print("DEBUG sys.path:", sys.path, file=sys.stderr)

import re

# Import the pipeline with strict package import (no fallbacks)
import marcut.pipeline as pipeline


def validate_model_name(model: str) -> bool:
    """
    Validate model name to prevent command injection.
    Allows alphanumerics, underscores, hyphens, colons, and periods.
    """
    if not model or model == "mock":
        return True
    # Allow simple file paths for GGUF models (e.g., /path/to/model.gguf)
    # but still restrict characters to safe set
    if model.endswith(".gguf") or "/" in model:
        # Relaxed check for paths, but still no shell metachars like ; | & $ > < `
        return not any(char in model for char in ";|&><$`")
    
    # Strict check for Ollama model names (e.g., llama3.1:8b)
    return bool(re.match(r"^[a-zA-Z0-9_\-\.:]+$", model))



def setup_logging(debug: bool = False, log_path: Optional[str] = None) -> None:
    """Setup unified logging configuration."""
    import logging

    level = logging.DEBUG if debug else logging.INFO
    format_str = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Configure root logger
    logging.basicConfig(
        level=level,
        format=format_str,
        handlers=[
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_path) if log_path else logging.NullHandler()
        ]
    )

    logger = logging.getLogger(__name__)
    logger.debug("Unified redactor logging initialized")


def validate_parameters(
    input_path: str,
    output_path: str,
    report_path: str,
    mode: str = "rules",
    model: str = "mock",
    backend: str = "auto"
) -> None:
    """Validate input parameters before processing."""
    logger = logging.getLogger(__name__)

    # Validate input file exists
    if not os.path.exists(input_path):
        raise ValueError(f"Input file not found: {input_path}")

    # Validate input file extension
    if not input_path.lower().endswith('.docx'):
        raise ValueError(f"Input file must be a DOCX file: {input_path}")

    # Validate mode
    valid_modes = ["rules", "enhanced", "balanced"]
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode '{mode}'. Valid modes: {valid_modes}")

    # Validate model/backend combination
    if model != "mock" and backend == "mock":
        raise ValueError("Cannot use non-mock model with mock backend")

    # Validate model name security
    if not validate_model_name(model):
        raise ValueError(f"Invalid model name '{model}'. Contains unsafe characters.")


    # Create output directories
    if os.path.dirname(output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.dirname(report_path):
        os.makedirs(os.path.dirname(report_path), exist_ok=True)

    logger.debug(f"Parameters validated: input={input_path}, output={output_path}, mode={mode}, model={model}")


def run_unified_redaction(
    input_path: str,
    output_path: str,
    report_path: str,
    mode: str = "rules",
    model: str = "mock",
    backend: str = "auto",
    debug: bool = False,
    chunk_tokens: int = 500,
    overlap: int = 100,
    temperature: float = 0.1,
    seed: int = 42,
    log_path: Optional[str] = None,
    timing: bool = False,
    llm_detail: bool = False
) -> Dict[str, Any]:
    """
    Unified redaction entry point.

    Args:
        input_path: Path to input DOCX file
        output_path: Path for output redacted DOCX file
        report_path: Path for JSON report file
        mode: Processing mode ('rules' or 'enhanced')
        model: Model identifier (e.g., 'mock', 'llama3.1:8b')
        backend: Processing backend ('auto', 'ollama', 'mock')
        debug: Enable debug logging
        chunk_tokens: Token chunk size for processing
        overlap: Token overlap between chunks
        temperature: LLM temperature parameter
        seed: Random seed for reproducible results
        log_path: Optional log file path

    Returns:
        Dictionary with processing results and metadata

    Raises:
        Exception: If processing fails
    """
    logger = logging.getLogger(__name__)
    normalized_mode = (mode or "rules").strip().lower()
    rules_only = normalized_mode in {"rules", "strict", "rules-only", "rules_only"}
    if rules_only:
        # Rules-only should never depend on Ollama; force a mock backend/model
        mode = "rules"
        model = "mock"
        backend = "mock"

    # Initialize logging
    setup_logging(debug, log_path)

    # Log operation start
    operation_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info(f"Starting unified redaction operation {operation_id}")
    logger.info(f"Input: {input_path}")
    logger.info(f"Output: {output_path}")
    logger.info(f"Report: {report_path}")
    logger.info(f"Mode: {mode}, Model: {model}, Backend: {backend}")
    if rules_only:
        logger.info("Rules-only mode detected; skipping Ollama and using deterministic rules backend.")

    actual_backend = model if model != "mock" else "mock"
    resolved_backend = "mock" if rules_only else ("ollama" if backend == "auto" else backend)

    try:
        # Validate parameters
        validate_parameters(input_path, output_path, report_path, mode, model, backend)

        # Determine actual backend to use
        actual_backend = model if model != "mock" else "mock"
        resolved_backend = "mock" if rules_only else ("ollama" if backend == "auto" else backend)
        logger.info(f"Using backend: {resolved_backend} with model: {actual_backend}")

        # Run the redaction pipeline
        logger.info("Starting redaction pipeline...")
        start_time = datetime.now()

        exit_code, phase_timings = pipeline.run_redaction(
            input_path,
            output_path,
            report_path,
            mode=mode,
            model_id=actual_backend,
            chunk_tokens=chunk_tokens,
            overlap=overlap,
            temperature=temperature,
            seed=seed,
            debug=debug,
            backend=resolved_backend,
            timing=timing,
            llm_detail=llm_detail
        )
        
        # Extract LLM timing if available
        llm_timing = {}
        if isinstance(phase_timings, dict) and 'llm_timing' in phase_timings:
            llm_timing = phase_timings.pop('llm_timing', {})

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Check results
        if exit_code == 0:
            logger.info(f"Redaction completed successfully in {duration:.2f} seconds")

            # Load and validate report
            if os.path.exists(report_path):
                with open(report_path, 'r') as f:
                    report_data = json.load(f)

                entity_count = len(report_data.get('spans', []))
                logger.info(f"Detected {entity_count} entities for redaction")

                return {
                    'success': True,
                    'exit_code': 0,
                    'duration': duration,
                    'entity_count': entity_count,
                    'input_file': input_path,
                    'output_file': output_path,
                    'report_file': report_path,
                    'mode': mode,
                    'model': actual_backend,
                    'backend': resolved_backend,
                    'operation_id': operation_id,
                    'phase_timings': phase_timings if timing else {},
                    'llm_timing': llm_timing if llm_detail else {}
                }
            else:
                raise FileNotFoundError(f"Report file not created: {report_path}")
        else:
            raise RuntimeError(f"Redaction pipeline failed with exit code {exit_code}")

    except Exception as e:
        logger.error(f"Redaction failed: {str(e)}")
        logger.debug(f"Full traceback: {traceback.format_exc()}")

        return {
            'success': False,
            'exit_code': getattr(e, 'exit_code', 1),
            'error': str(e),
            'input_file': input_path,
            'mode': mode,
            'model': actual_backend,
            'backend': resolved_backend,
            'operation_id': operation_id,
            'duration': (datetime.now() - start_time).total_seconds() if 'start_time' in locals() else 0
        }


def main():
    """Command line interface for unified redactor."""
    parser = argparse.ArgumentParser(
        description="Unified Marcut Redactor - Single entry point for document redaction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Rules-only redaction
  python unified_redactor.py --in document.docx --out redacted.docx --report report.json --mode rules

  # LLM-enhanced redaction
  python unified_redactor.py --in document.docx --out redacted.docx --report report.json --mode enhanced --model llama3.2:3b

  # Debug mode with custom logging
  python unified_redactor.py --in document.docx --out redacted.docx --report report.json --debug --log debug.log
        """
    )

    parser.add_argument('--in', required=True, help='Input DOCX file')
    parser.add_argument('--out', required=True, help='Output redacted DOCX file')
    parser.add_argument('--report', required=True, help='JSON report file')
    parser.add_argument('--mode', default='rules', choices=['rules', 'enhanced'],
                       help='Processing mode (default: rules)')
    parser.add_argument('--model', default='mock',
                       help='Model to use (default: mock, e.g., llama3.2:3b for LLM)')
    parser.add_argument('--backend', default='auto', choices=['auto', 'ollama', 'mock'],
                       help='Processing backend (default: auto)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--log', help='Log file path (optional)')
    parser.add_argument('--chunk-tokens', type=int, default=500, help='Token chunk size (default: 500)')
    parser.add_argument('--overlap', type=int, default=100, help='Token overlap (default: 100)')
    parser.add_argument('--temperature', type=float, default=0.1, help='LLM temperature (default: 0.1)')
    parser.add_argument('--seed', type=int, default=42, help='Random seed (default: 42)')

    args = parser.parse_args()

    # Run unified redaction
    result = run_unified_redaction(
        input_path=getattr(args, 'in'),
        output_path=args.out,
        report_path=args.report,
        mode=args.mode,
        model=args.model,
        backend=args.backend,
        debug=args.debug,
        chunk_tokens=args.chunk_tokens,
        overlap=args.overlap,
        temperature=args.temperature,
        seed=args.seed,
        log_path=args.log
    )

    # Exit with appropriate code
    if result['success']:
        print(f"✅ Redaction completed successfully")
        print(f"   Input: {result['input_file']}")
        print(f"   Output: {result['output_file']}")
        print(f"   Report: {result['report_file']}")
        print(f"   Entities: {result['entity_count']}")
        print(f"   Duration: {result['duration']:.2f}s")
        sys.exit(0)
    else:
        print(f"❌ Redaction failed: {result['error']}", file=sys.stderr)
        sys.exit(result['exit_code'])


if __name__ == "__main__":
    main()
