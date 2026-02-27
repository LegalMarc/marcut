#!/usr/bin/env python3
"""
Score matrix outputs against an answer key (track-changes deletions).
Compares deleted-text tokens to compute missed and extra redactions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET


REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[\\.-][A-Za-z0-9]+)*")


@dataclass(frozen=True)
class ComboInfo:
    combo_id: str
    llm_confidence: int
    temperature: float
    chunk_tokens: int
    overlap: int
    label: str = ""


def load_combo_info() -> Dict[str, ComboInfo]:
    # Reuse the matrix settings from the generator script.
    sys.path.insert(0, str(REPO_ROOT / "tests" / "scripts"))
    from run_llm_matrix import COMBOS  # type: ignore

    return {
        combo.combo_id: ComboInfo(
            combo_id=combo.combo_id,
            llm_confidence=combo.llm_confidence,
            temperature=combo.temperature,
            chunk_tokens=combo.chunk_tokens,
            overlap=combo.overlap,
            label=combo.label,
        )
        for combo in COMBOS
    }


def iter_doc_parts(docx_path: Path) -> Iterable[Tuple[str, str]]:
    with zipfile.ZipFile(docx_path) as zf:
        for name in zf.namelist():
            if not name.startswith("word/"):
                continue
            if name == "word/document.xml" or name.startswith("word/header") or name.startswith("word/footer"):
                xml_bytes = zf.read(name)
                yield name, xml_bytes.decode("utf-8", errors="ignore")
            elif name in {"word/footnotes.xml", "word/endnotes.xml"}:
                xml_bytes = zf.read(name)
                yield name, xml_bytes.decode("utf-8", errors="ignore")


def extract_deleted_tokens(docx_path: Path) -> Counter:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    tokens: Counter = Counter()
    for _, xml_text in iter_doc_parts(docx_path):
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue
        for del_node in root.findall(".//w:del", ns):
            text_fragments: List[str] = []
            for node in del_node.iter():
                if node.tag in {f"{{{ns['w']}}}delText", f"{{{ns['w']}}}t"}:
                    if node.text:
                        text_fragments.append(node.text)
            for fragment in text_fragments:
                for token in TOKEN_RE.findall(fragment.lower()):
                    tokens[token] += 1
    return tokens


def compute_jaccard(text_a: str, text_b: str) -> float:
    set_a = set(TOKEN_RE.findall(text_a.lower()))
    set_b = set(TOKEN_RE.findall(text_b.lower()))
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def load_doc_text(doc_path: Path) -> str:
    sys.path.insert(0, str(REPO_ROOT / "src" / "python"))
    from marcut.docx_io import DocxMap  # type: ignore

    return DocxMap.load(str(doc_path)).text


def pick_doc(answer_key: Path, candidates: List[Path]) -> Optional[Path]:
    if not candidates:
        return None
    answer_text = load_doc_text(answer_key)
    best_doc = None
    best_score = -1.0
    for candidate in candidates:
        try:
            score = compute_jaccard(answer_text, load_doc_text(candidate))
        except Exception:
            continue
        if score > best_score:
            best_score = score
            best_doc = candidate
    return best_doc


def score_tokens(gold: Counter, pred: Counter) -> Tuple[int, int, float, float]:
    missed = 0
    extra = 0
    for token, count in gold.items():
        missed += max(0, count - pred.get(token, 0))
    for token, count in pred.items():
        extra += max(0, count - gold.get(token, 0))
    total_gold = sum(gold.values())
    total_pred = sum(pred.values())
    recall = 1.0 - (missed / total_gold) if total_gold else 1.0
    precision = 1.0 - (extra / total_pred) if total_pred else 1.0
    return missed, extra, recall, precision


def find_doc_key(results: Dict[str, Dict[str, Dict[str, object]]], doc_path: Path) -> Optional[str]:
    candidates = {str(doc_path), str(doc_path.resolve())}
    for combo_payloads in results.values():
        for key in combo_payloads.keys():
            if key in candidates:
                return key
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Score matrix outputs against an answer key.")
    parser.add_argument("--matrix-dir", required=True, help="Matrix directory containing results.json and outputs.")
    parser.add_argument("--answer-key", help="Answer key docx (defaults to matrix-dir/answer-key.docx).")
    parser.add_argument("--doc", help="Target doc path (optional; auto-detect if omitted).")
    parser.add_argument("--output", help="Output report path (defaults to matrix-dir/answer-key-scores.md).")
    args = parser.parse_args()

    matrix_dir = Path(args.matrix_dir)
    results_path = matrix_dir / "results.json"
    if not results_path.exists():
        print(f"Missing results.json: {results_path}", file=sys.stderr)
        return 2

    results = json.loads(results_path.read_text(encoding="utf-8"))

    answer_key = Path(args.answer_key) if args.answer_key else matrix_dir / "answer-key.docx"
    if not answer_key.exists():
        print(f"Missing answer key: {answer_key}", file=sys.stderr)
        return 2

    doc_candidates = []
    for doc_map in results.values():
        for doc_path in doc_map.keys():
            doc_candidates.append(Path(doc_path))
        break

    target_doc: Optional[Path] = None
    if args.doc:
        target_doc = Path(args.doc)
    elif len(doc_candidates) == 1:
        target_doc = doc_candidates[0]
    else:
        target_doc = pick_doc(answer_key, doc_candidates)

    if target_doc is None:
        print("Unable to determine target document.", file=sys.stderr)
        return 2

    doc_key = find_doc_key(results, target_doc)
    if not doc_key:
        print(f"Target document not found in results: {target_doc}", file=sys.stderr)
        return 2

    gold_tokens = extract_deleted_tokens(answer_key)
    combo_info = load_combo_info()

    rows = []
    for combo_id, doc_map in results.items():
        entry = doc_map.get(doc_key)
        if not entry or entry.get("status") != "ok":
            rows.append({"combo_id": combo_id, "failed": True})
            continue
        output_path = Path(entry.get("output_path", ""))
        if not output_path.exists():
            rows.append({"combo_id": combo_id, "failed": True})
            continue
        pred_tokens = extract_deleted_tokens(output_path)
        missed, extra, recall, precision = score_tokens(gold_tokens, pred_tokens)
        elapsed = entry.get("elapsed_sec")
        info = combo_info.get(combo_id)
        rows.append({
            "combo_id": combo_id,
            "llm_confidence": info.llm_confidence if info else None,
            "temperature": info.temperature if info else None,
            "chunk_tokens": info.chunk_tokens if info else None,
            "overlap": info.overlap if info else None,
            "label": info.label if info else "",
            "elapsed_sec": elapsed if isinstance(elapsed, (int, float)) else None,
            "missed": missed,
            "extra": extra,
            "recall": recall,
            "precision": precision,
            "failed": False,
        })

    scored = [r for r in rows if not r.get("failed")]
    ranked = sorted(scored, key=lambda r: (r["missed"], r["extra"], r["elapsed_sec"] or 0.0))

    output_path = Path(args.output) if args.output else matrix_dir / "answer-key-scores.md"

    lines: List[str] = []
    lines.append("# Answer Key Scoring Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Matrix: {matrix_dir}")
    lines.append(f"Answer key: {answer_key}")
    lines.append(f"Target doc: {target_doc}")
    lines.append("")
    lines.append("Scoring uses deleted-text tokens (w:del/w:delText).")
    lines.append("Missed = tokens in answer key but not redacted. Extra = tokens redacted but not in answer key.")
    lines.append("")
    lines.append("| Rank | Combo | LLM% | Temp | Chunk | Overlap | Time (s) | Missed | Extra | Recall | Precision | Label |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    rank_lookup = {row["combo_id"]: idx + 1 for idx, row in enumerate(ranked)}
    for row in rows:
        if row.get("failed"):
            lines.append(f"| - | {row['combo_id']} | - | - | - | - | - | - | - | - | - | - | failed |")
            continue
        elapsed = row.get("elapsed_sec")
        elapsed_str = f"{elapsed:.1f}" if isinstance(elapsed, (int, float)) else "-"
        lines.append(
            f"| {rank_lookup[row['combo_id']]} | {row['combo_id']} | {row['llm_confidence']} | "
            f"{row['temperature']:.1f} | {row['chunk_tokens']} | {row['overlap']} | "
            f"{elapsed_str} | {row['missed']} | {row['extra']} | {row['recall']:.3f} | "
            f"{row['precision']:.3f} | {row['label']} |"
        )
    lines.append("")
    lines.append("## Conclusions")
    if ranked:
        best = ranked[0]
        lines.append(
            f"- Best overall (lowest missed, then extra, then time): {best['combo_id']} "
            f"(missed {best['missed']}, extra {best['extra']}, time {best['elapsed_sec']:.1f}s)."
        )
    else:
        lines.append("- No successful runs found.")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
