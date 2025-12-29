
import argparse, sys
from .unified_redactor import run_unified_redaction
from .preflight import ensure_ollama_ready
from .progress import create_progress_callback, ProgressUpdate


def _parse_mode(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "strict":
        normalized = "rules"
    if normalized not in {"rules", "enhanced", "balanced"}:
        raise argparse.ArgumentTypeError(f"Invalid mode '{value}'. Choose from rules, enhanced, or balanced.")
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
        choices=["rules", "enhanced", "balanced"],
        default="enhanced",
        help="rules (rules-only), enhanced (two-pass LLM), balanced (legacy hybrid).",
    )
    r.add_argument("--backend", choices=["ollama", "llama_cpp", "mock"], default="ollama")
    r.add_argument("--model", default="llama3.1:8b")
    r.add_argument("--llama-gguf", default=None)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--chunk-tokens", type=int, default=1000)
    r.add_argument("--overlap", type=int, default=150)
    r.add_argument("--temp", type=float, default=0.1)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--no-qa", action="store_true")
    r.add_argument("--debug", action="store_true")
    r.add_argument("--timing", action="store_true", help="Show detailed phase timing breakdown")
    r.add_argument("--llm-detail", action="store_true", help="Show detailed LLM sub-phase timing (implies --timing)")
    return p


def main():
    a = build().parse_args()

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
        if a.mode in {"enhanced", "balanced"} and a.backend == "ollama":
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
            log_path=f"/tmp/marcut_cli_{a.mode}_{a.model.replace(':', '_')}.log" if a.debug else None,
            timing=getattr(a, 'timing', False) or getattr(a, 'llm_detail', False),
            llm_detail=getattr(a, 'llm_detail', False)
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
