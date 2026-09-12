"""
Span scorer for the PII detection precision/recall harness (A1).

Matches expected (gold) entities against predicted spans from the redaction
audit report by (label, text) using bidirectional substring containment,
rather than exact character offsets or exact string equality:

- Exact offsets would require hardcoding the synthetic document's linearized
  character positions by hand (fragile, and it duplicates knowledge that
  belongs to docx_io.py's part-linearization logic).
- Exact text equality is too strict: rule regexes occasionally trim a boundary
  character (e.g. a leading parenthesis on a phone number, or a leading
  currency symbol on a money span) without that being a real detection miss.

Containment still requires genuine overlap of the identifying content, so an
actually-missed or mislabeled entity still counts as a miss.
"""

from __future__ import annotations

from typing import Any, Dict, List


def _texts_overlap(expected: str, predicted: str) -> bool:
    e = (expected or "").strip()
    p = (predicted or "").strip()
    if not e or not p:
        return False
    return e in p or p in e


def score_entities(
    expected: List[Dict[str, Any]],
    predicted: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Greedily match expected entities against predicted spans of the same label.

    Each predicted span is consumed by at most one expected entity, so N
    identical expected entities require N distinct predicted spans (duplicates
    are not free matches).

    Returns a dict keyed by label plus an "OVERALL" aggregate row, each mapping
    to {tp, fp, fn, precision, recall, f1}.
    """
    remaining: Dict[str, List[Dict[str, Any]]] = {}
    for sp in predicted:
        remaining.setdefault(sp.get("label", ""), []).append(sp)

    counts: Dict[str, Dict[str, int]] = {}

    def bump(label: str, key: str) -> None:
        counts.setdefault(label, {"tp": 0, "fp": 0, "fn": 0})
        counts[label][key] += 1

    for exp in expected:
        label = exp["label"]
        candidates = remaining.get(label, [])
        match_idx = None
        for idx, cand in enumerate(candidates):
            if _texts_overlap(exp["text"], cand.get("text", "")):
                match_idx = idx
                break
        if match_idx is not None:
            bump(label, "tp")
            candidates.pop(match_idx)
        else:
            bump(label, "fn")

    for label, candidates in remaining.items():
        for _ in candidates:
            bump(label, "fp")

    results: Dict[str, Dict[str, float]] = {}
    total_tp = total_fp = total_fn = 0
    for label, c in sorted(counts.items()):
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        results[label] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision, "recall": recall, "f1": f1,
        }

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 1.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 1.0
    overall_f1 = (
        2 * overall_precision * overall_recall / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) else 0.0
    )
    results["OVERALL"] = {
        "tp": total_tp, "fp": total_fp, "fn": total_fn,
        "precision": overall_precision, "recall": overall_recall, "f1": overall_f1,
    }
    return results


def format_score_table(results: Dict[str, Dict[str, float]]) -> str:
    """Render a per-label precision/recall/F1 table for console output."""
    lines = [
        f"{'Label':<10} {'TP':>4} {'FP':>4} {'FN':>4} {'Precision':>10} {'Recall':>8} {'F1':>6}",
        "-" * 52,
    ]
    for label, r in results.items():
        if label == "OVERALL":
            continue
        lines.append(
            f"{label:<10} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} "
            f"{r['precision']:>10.2f} {r['recall']:>8.2f} {r['f1']:>6.2f}"
        )
    lines.append("-" * 52)
    o = results["OVERALL"]
    lines.append(
        f"{'OVERALL':<10} {o['tp']:>4} {o['fp']:>4} {o['fn']:>4} "
        f"{o['precision']:>10.2f} {o['recall']:>8.2f} {o['f1']:>6.2f}"
    )
    return "\n".join(lines)
