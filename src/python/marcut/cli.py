import argparse, sys
import os
import shlex
from .unified_redactor import run_unified_redaction
from .preflight import ensure_ollama_ready
from .progress import create_progress_callback, ProgressUpdate
from .docx_io import CLI_ARG_PAIRS


def _parse_mode(value: str) -> str:
    normalized = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized == "strict":
        normalized = "rules"
    if normalized not in {"rules", "enhanced", "rules_override", "constrained_overrides", "llm_overrides"}:
        raise argparse.ArgumentTypeError(
            f"Invalid mode '{value}'. Choose from rules, enhanced, rules_override, "
            "constrained_overrides, or llm_overrides."
        )
    return normalized


def build():
    p = argparse.ArgumentParser(prog="marcut", description="Marcut: local DOCX redaction")
    sp = p.add_subparsers(dest="cmd", required=True)
    r = sp.add_parser("redact", help="Redact a DOCX file")
    r.add_argument("--in", dest="inp", required=True)
    r.add_argument("--out", dest="out", required=True)
    r.add_argument("--report", dest="report", required=True)
    r.add_argument(
        "--mode",
        type=_parse_mode,
        choices=["rules", "enhanced", "rules_override", "constrained_overrides", "llm_overrides"],
        default="enhanced",
        help="rules (rules-only), enhanced/rules_override (rules + AI), constrained_overrides, llm_overrides.",
    )
    r.add_argument("--backend", choices=["ollama", "llama_cpp", "mock"], default="ollama")
    r.add_argument("--model", default="llama3.1:8b")
    r.add_argument("--llama-gguf", default=None)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--chunk-tokens", type=int, default=1000)
    r.add_argument("--overlap", type=int, default=150)
    r.add_argument("--temp", type=float, default=0.1)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--llm-skip-confidence", type=float, default=0.95)
    r.add_argument("--no-qa", action="store_true")
    r.add_argument("--debug", action="store_true")
    r.add_argument("--timing", action="store_true", help="Show detailed phase timing breakdown")
    r.add_argument("--llm-detail", action="store_true", help="Show detailed LLM sub-phase timing (implies --timing)")
    r.add_argument(
        "--metadata-preset",
        choices=["maximum", "balanced", "none", "custom"],
        default=None,
        help="Metadata cleaning preset for scrub behavior."
    )
    r.add_argument(
        "--metadata-settings-json",
        default=None,
        help="Full metadata settings JSON payload (field->bool) for exact checkbox parity."
    )
    r.add_argument(
        "--metadata-args",
        default=None,
        help="Raw metadata override flags string (e.g. '--no-clean-headers-footers --clean-created-date')."
    )
    r.add_argument(
        "--no-clean-review-comments",
        dest="metadata_overrides",
        action="append_const",
        const="--no-clean-review-comments",
        help=argparse.SUPPRESS
    )
    r.add_argument(
        "--clean-review-comments",
        dest="metadata_overrides",
        action="append_const",
        const="--clean-review-comments",
        help=argparse.SUPPRESS
    )
    for no_clean_flag, _ in CLI_ARG_PAIRS:
        clean_flag = no_clean_flag.replace("--no-clean-", "--clean-", 1)
        r.add_argument(
            no_clean_flag,
            dest="metadata_overrides",
            action="append_const",
            const=no_clean_flag,
            help=argparse.SUPPRESS
        )
        r.add_argument(
            clean_flag,
            dest="metadata_overrides",
            action="append_const",
            const=clean_flag,
            help=argparse.SUPPRESS
        )
    return p


def main():
    a = build().parse_args()

    metadata_overrides = list(getattr(a, "metadata_overrides", []) or [])
    raw_metadata_args = getattr(a, "metadata_args", None)
    if raw_metadata_args:
        metadata_overrides.extend(shlex.split(raw_metadata_args))
    metadata_args_value = " ".join(metadata_overrides).strip()
    if metadata_args_value:
        os.environ["MARCUT_METADATA_ARGS"] = metadata_args_value
    else:
        os.environ.pop("MARCUT_METADATA_ARGS", None)

    if getattr(a, "metadata_preset", None):
        os.environ["MARCUT_METADATA_PRESET"] = a.metadata_preset
    else:
        os.environ.pop("MARCUT_METADATA_PRESET", None)

    if getattr(a, "metadata_settings_json", None):
        os.environ["MARCUT_METADATA_SETTINGS_JSON"] = a.metadata_settings_json
    else:
        os.environ.pop("MARCUT_METADATA_SETTINGS_JSON", None)

    # Create CLI progress callback that outputs messages for SwiftUI parsing
    def cli_progress_callback(update: ProgressUpdate):
        try:
            # Output structured progress messages that SwiftUI can parse
            print(f"MARCUT_PROGRESS: {update.phase_name} | Stage: {update.phase_progress:.1%} | Overall: {update.overall_progress:.1%} | Remaining: {update.estimated_remaining:.0f}s")
            if update.message:
                print(f"MARCUT_STATUS: {update.message}")
            sys.stdout.flush()  # Ensure immediate output for real-time parsing
        except Exception as e:
            if a.debug:
                print(f"Progress callback error: {e}")
    
    progress_callback = create_progress_callback(cli_progress_callback)
    
    # Run preflight checks only when using real LLM backends
    if a.cmd == "redact":
        if a.mode != "rules" and a.backend == "ollama":
            print(f"Running Ollama preflight checks for {a.mode} mode...")
            ensure_ollama_ready(model_name=a.model)
            print("")
        else:
            print(f"Skipping Ollama preflight checks (mode: {a.mode}, backend: {a.backend})")

    try:
        # Use unified redactor for consistent behavior between GUI and CLI
        result = run_unified_redaction(
            input_path=a.inp,
            output_path=a.out,
            report_path=a.report,
            mode=a.mode,
            model=a.model,
            backend=a.backend,
            debug=a.debug,
            chunk_tokens=a.chunk_tokens,
            overlap=a.overlap,
            temperature=a.temp,
            seed=a.seed,
            llm_skip_confidence=a.llm_skip_confidence,
            log_path=f"/tmp/marcut_cli_{a.mode}_{a.model.replace(':', '_')}.log" if a.debug else None,
            timing=getattr(a, 'timing', False) or getattr(a, 'llm_detail', False),
            llm_detail=getattr(a, 'llm_detail', False),
            progress_callback=progress_callback,
        )

        if result['success']:
            print(f"✅ Redaction completed successfully")
            print(f"   Entities detected: {result['entity_count']}")
            print(f"   Processing time: {result['duration']:.2f}s")
            
            # Show timing breakdown if requested
            if (getattr(a, 'timing', False) or getattr(a, 'llm_detail', False)) and 'phase_timings' in result:
                total = result['duration']
                print(f"\n📊 Phase Timing Breakdown:")
                print(f"   {'Phase':<20} {'Time':>8} {'Pct':>6}")
                print(f"   {'-'*20} {'-'*8} {'-'*6}")
                for phase, duration in result['phase_timings'].items():
                    pct = (duration / total * 100) if total > 0 else 0
                    print(f"   {phase:<20} {duration:>7.2f}s {pct:>5.1f}%")
                # Identify bottleneck
                if result['phase_timings']:
                    bottleneck = max(result['phase_timings'].items(), key=lambda x: x[1])
                    print(f"\n   ⚡ Bottleneck: {bottleneck[0]} ({bottleneck[1]:.2f}s, {bottleneck[1]/total*100:.0f}%)")
            
            # Show LLM sub-phase detail if requested
            if getattr(a, 'llm_detail', False) and 'llm_timing' in result:
                llm = result['llm_timing']
                llm_total = llm.get('http_request', 0)
                print(f"\n🔬 LLM Sub-Phase Detail:")
                print(f"   {'Sub-Phase':<22} {'Time':>8} {'Pct':>6}")
                print(f"   {'-'*22} {'-'*8} {'-'*6}")
                sub_phases = [
                    ('Model Load', llm.get('ollama_model_load', 0)),
                    ('Prompt Processing', llm.get('ollama_prompt_eval', 0)),
                    ('Token Generation', llm.get('ollama_generation', 0)),
                    ('Network Overhead', llm.get('network_overhead', 0)),
                    ('Response Parsing', llm.get('response_parse', 0)),
                    ('Entity Location', llm.get('entity_locate', 0)),
                ]
                for name, dur in sub_phases:
                    pct = (dur / llm_total * 100) if llm_total > 0 else 0
                    print(f"   {name:<22} {dur:>7.3f}s {pct:>5.1f}%")
                print(f"\n   📈 Tokens: {llm.get('prompt_tokens', 0)} in → {llm.get('output_tokens', 0)} out")
                if llm.get('ollama_generation', 0) > 0:
                    tok_per_sec = llm.get('output_tokens', 0) / llm.get('ollama_generation', 1)
                    print(f"   ⚡ Speed: {tok_per_sec:.1f} tokens/sec")
            sys.exit(0)
        else:
            print(f"❌ Redaction failed: {result['error']}", file=sys.stderr)
            sys.exit(result['exit_code'])

    except KeyboardInterrupt:
        print("Operation cancelled by user", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
