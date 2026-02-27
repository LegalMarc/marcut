#!/usr/bin/env python3
"""
Run a constrained-override matrix over selected documents and summarize:
- processing time
- missed redactions (vs max-redaction baseline)
- not-necessary redactions (vs min-redaction baseline)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DOCS = [
    REPO_ROOT / ".marcut_artifacts/ignored-resources" / "sample-files" / "Sample 123 Earn-Out Note (bad redaction of org).docx",
    REPO_ROOT / ".marcut_artifacts/ignored-resources" / "sample-files" / "Compliance-Cert.docx",
    REPO_ROOT / ".marcut_artifacts/ignored-resources" / "sample-files" / "Sample 123 Preservation Letter track changes.docx",
]

MODEL_NAME = "llama3.1:8b"
MODE = "constrained_overrides"
BACKEND = "ollama"
SEED = 42


@dataclass(frozen=True)
class Combo:
    combo_id: str
    llm_confidence: int
    temperature: float
    chunk_tokens: int
    overlap: int
    label: str = ""

    @property
    def llm_skip_confidence(self) -> float:
        return self.llm_confidence / 100.0


COMBOS: List[Combo] = [
    Combo("C01", 99, 0.2, 800, 200, "max_redaction"),
    Combo("C02", 80, 0.0, 1200, 100, "min_redaction"),
    Combo("C03", 95, 0.1, 1000, 150, "default"),
    Combo("C04", 90, 0.1, 1000, 150, ""),
    Combo("C05", 85, 0.1, 1000, 150, ""),
    Combo("C06", 97, 0.1, 1000, 150, ""),
    Combo("C07", 95, 0.0, 1000, 150, ""),
    Combo("C08", 95, 0.2, 1000, 150, ""),
    Combo("C09", 95, 0.1, 800, 150, ""),
    Combo("C10", 95, 0.1, 1200, 150, ""),
    Combo("C11", 95, 0.1, 1000, 100, ""),
    Combo("C12", 95, 0.1, 1000, 200, ""),
    Combo("C13", 90, 0.0, 800, 100, ""),
    Combo("C14", 90, 0.2, 1200, 200, ""),
    Combo("C15", 85, 0.0, 1200, 150, ""),
    Combo("C16", 85, 0.2, 800, 100, ""),
    Combo("C17", 97, 0.0, 800, 200, ""),
    Combo("C18", 97, 0.2, 1200, 100, ""),
    Combo("C19", 99, 0.1, 800, 150, ""),
    Combo("C20", 80, 0.2, 1200, 200, ""),
]

REFERENCE_MAX_ID = "C01"
REFERENCE_MIN_ID = "C02"


def resolve_python_executable(project_root: Path) -> str:
    venv_python = project_root / ".marcut_artifacts/ignored-resources" / "temp-venvs" / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return slug or "doc"


def ollama_tags_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
    if "://" not in host:
        host = f"http://{host}"
    return host.rstrip("/") + "/api/tags"


def ollama_reachable() -> bool:
    try:
        result = subprocess.run(
            ["curl", "-s", ollama_tags_url()],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def attempt_start_ollama() -> bool:
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        return False
    try:
        subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def ensure_ollama() -> None:
    if ollama_reachable():
        return
    if attempt_start_ollama():
        deadline = time.time() + 20
        while time.time() < deadline:
            if ollama_reachable():
                return
            time.sleep(1)
    raise RuntimeError("Ollama is not reachable; start it before running the matrix.")


def check_model_available(model_name: str) -> None:
    result = subprocess.run(
        ["curl", "-s", ollama_tags_url()],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError("Failed to query Ollama tags; check Ollama status.")
    data = json.loads(result.stdout or "{}")
    names = {m.get("name") for m in data.get("models", [])}
    if model_name not in names:
        raise RuntimeError(f"Ollama model '{model_name}' not found; download it before running the matrix.")


def load_spans(report_path: Path) -> Set[Tuple[str, int, int]]:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    spans = payload.get("spans", [])
    out: Set[Tuple[str, int, int]] = set()
    for sp in spans:
        try:
            label = str(sp.get("label"))
            start = int(sp.get("start"))
            end = int(sp.get("end"))
        except (TypeError, ValueError):
            continue
        out.add((label, start, end))
    return out


def run_redaction(
    python_exec: str,
    doc_path: Path,
    output_dir: Path,
    combo: Combo,
    mode: str,
    env: Dict[str, str],
) -> Dict[str, object]:
    doc_slug = slugify(doc_path.stem)
    run_dir = output_dir / combo.combo_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out_doc = run_dir / f"{doc_slug}.docx"
    out_report = run_dir / f"{doc_slug}_report.json"

    cmd = [
        python_exec,
        "-m",
        "marcut.cli",
        "redact",
        "--in",
        str(doc_path),
        "--out",
        str(out_doc),
        "--report",
        str(out_report),
        "--mode",
        mode,
        "--backend",
        BACKEND,
        "--model",
        MODEL_NAME,
        "--chunk-tokens",
        str(combo.chunk_tokens),
        "--overlap",
        str(combo.overlap),
        "--temp",
        f"{combo.temperature:.2f}",
        "--seed",
        str(SEED),
        "--llm-skip-confidence",
        f"{combo.llm_skip_confidence:.2f}",
    ]

    start = time.perf_counter()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.perf_counter() - start

    payload: Dict[str, object] = {
        "combo_id": combo.combo_id,
        "doc": str(doc_path),
        "doc_slug": doc_slug,
        "elapsed_sec": elapsed,
        "return_code": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "report_path": str(out_report),
        "output_path": str(out_doc),
    }

    if result.returncode != 0:
        payload["status"] = "failed"
        return payload

    if not out_report.exists():
        payload["status"] = "failed"
        payload["error"] = "report_not_found"
        return payload

    payload["status"] = "ok"
    payload["spans"] = load_spans(out_report)
    return payload


def write_report(
    report_path: Path,
    combos: Iterable[Combo],
    docs: List[Path],
    results: Dict[str, Dict[str, Dict[str, object]]],
    baseline_max: Dict[str, Set[Tuple[str, int, int]]],
    baseline_min: Dict[str, Set[Tuple[str, int, int]]],
) -> None:
    rows = []
    for combo in combos:
        per_doc = results[combo.combo_id]
        total_time = 0.0
        missed_total = 0
        extra_total = 0
        failed = False
        for doc in docs:
            doc_key = str(doc)
            entry = per_doc.get(doc_key)
            if not entry or entry.get("status") != "ok":
                failed = True
                continue
            total_time += float(entry.get("elapsed_sec", 0.0))
            spans = entry.get("spans", set())
            if isinstance(spans, set):
                missed = len(baseline_max[doc_key] - spans)
                extra = len(spans - baseline_min[doc_key])
            else:
                missed = 0
                extra = 0
            missed_total += missed
            extra_total += extra
        avg_time = total_time / len(docs) if docs else 0.0
        rows.append(
            {
                "combo_id": combo.combo_id,
                "llm_confidence": combo.llm_confidence,
                "temperature": combo.temperature,
                "chunk_tokens": combo.chunk_tokens,
                "overlap": combo.overlap,
                "label": combo.label,
                "time_total": total_time,
                "time_avg": avg_time,
                "missed_total": missed_total,
                "extra_total": extra_total,
                "failed": failed,
            }
        )

    rows_sorted = sorted(
        [r for r in rows if not r["failed"]],
        key=lambda r: (r["missed_total"], r["extra_total"], r["time_total"]),
    )
    best = rows_sorted[0] if rows_sorted else None

    lines = []
    lines.append("# LLM Constrained Overrides Matrix Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Inputs")
    for doc in docs:
        lines.append(f"- {doc}")
    lines.append("")
    lines.append("## Baselines (heuristic)")
    lines.append(f"- Max-redaction baseline: {REFERENCE_MAX_ID}")
    lines.append(f"- Min-redaction baseline: {REFERENCE_MIN_ID}")
    lines.append("")
    lines.append("Missed redactions = spans in max-redaction baseline but absent in a run.")
    lines.append("Not-necessary redactions = spans in a run but absent in the min-redaction baseline.")
    lines.append("")
    lines.append("## Matrix")
    lines.append("")
    lines.append("| Combo | LLM% | Temp | Chunk | Overlap | Time Total (s) | Time Avg (s) | Missed | Not Necessary | Label |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            f"| {row['combo_id']} | {row['llm_confidence']} | {row['temperature']:.1f} | "
            f"{row['chunk_tokens']} | {row['overlap']} | {row['time_total']:.1f} | "
            f"{row['time_avg']:.1f} | {row['missed_total']} | {row['extra_total']} | {row['label']} |"
        )
    lines.append("")
    lines.append("## Conclusions")
    if best:
        lines.append(
            f"- Best overall (lowest missed, then extra, then time): {best['combo_id']} "
            f"(LLM% {best['llm_confidence']}, temp {best['temperature']:.1f}, "
            f"chunk {best['chunk_tokens']}, overlap {best['overlap']})."
        )
        lines.append(
            f"- Totals for {best['combo_id']}: missed {best['missed_total']}, "
            f"not necessary {best['extra_total']}, total time {best['time_total']:.1f}s."
        )
    else:
        lines.append("- No successful runs; check the raw results for errors.")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a constrained-override LLM matrix.")
    parser.add_argument("--output-dir", default=str(REPO_ROOT / ".marcut_artifacts/ignored-files" / "test-output"), help="Base output directory.")
    parser.add_argument("--docs", nargs="*", default=[str(p) for p in DEFAULT_DOCS])
    parser.add_argument("--mode", default=MODE, help="Processing mode (default: constrained_overrides).")
    args = parser.parse_args()

    docs = [Path(p) for p in args.docs]
    for doc in docs:
        if not doc.exists():
            print(f"Missing input: {doc}", file=sys.stderr)
            return 2

    ensure_ollama()
    check_model_available(MODEL_NAME)

    python_exec = resolve_python_executable(REPO_ROOT)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src' / 'python'}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path(args.output_dir) / f"llm-matrix-{timestamp}"
    base_dir.mkdir(parents=True, exist_ok=True)

    mode = args.mode
    results: Dict[str, Dict[str, Dict[str, object]]] = {}
    for combo in COMBOS:
        combo_results: Dict[str, Dict[str, object]] = {}
        print(f"== {combo.combo_id} (LLM {combo.llm_confidence}%, temp {combo.temperature}, "
              f"chunk {combo.chunk_tokens}, overlap {combo.overlap}) ==")
        for doc in docs:
            print(f"  - {doc.name}")
            payload = run_redaction(python_exec, doc, base_dir, combo, mode, env)
            combo_results[str(doc)] = payload
            if payload.get("status") != "ok":
                print(f"    FAILED: {payload.get('stderr')}")
        results[combo.combo_id] = combo_results

    max_combo = next((c for c in COMBOS if c.combo_id == REFERENCE_MAX_ID), None)
    min_combo = next((c for c in COMBOS if c.combo_id == REFERENCE_MIN_ID), None)
    if not max_combo or not min_combo:
        print("Reference combos missing from COMBOS list.", file=sys.stderr)
        return 2

    baseline_max: Dict[str, Set[Tuple[str, int, int]]] = {}
    baseline_min: Dict[str, Set[Tuple[str, int, int]]] = {}
    for doc in docs:
        doc_key = str(doc)
        max_entry = results[max_combo.combo_id].get(doc_key, {})
        min_entry = results[min_combo.combo_id].get(doc_key, {})
        if max_entry.get("status") != "ok" or min_entry.get("status") != "ok":
            print("Baseline runs failed; cannot compute matrix.", file=sys.stderr)
            return 2
        baseline_max[doc_key] = max_entry.get("spans", set())
        baseline_min[doc_key] = min_entry.get("spans", set())

    report_path = base_dir / "report.md"
    write_report(report_path, COMBOS, docs, results, baseline_max, baseline_min)

    raw_path = base_dir / "results.json"
    json_ready = {
        combo_id: {
            doc: {
                k: (list(v) if k == "spans" else v)
                for k, v in payload.items()
                if k != "spans" or isinstance(v, set)
            }
            for doc, payload in payloads.items()
        }
        for combo_id, payloads in results.items()
    }
    raw_path.write_text(json.dumps(json_ready, indent=2), encoding="utf-8")

    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
