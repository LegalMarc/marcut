#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import zipfile
from dataclasses import fields
from pathlib import Path
from typing import Dict, List, Tuple
from xml.etree import ElementTree as ET

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from marcut.docx_io import MetadataCleaningSettings
from marcut import pipeline


def read_baseline_args(log_path: Path) -> List[str]:
    if not log_path.exists():
        return []
    lines = log_path.read_text(errors="ignore").splitlines()
    for line in reversed(lines):
        if "Metadata args:" in line:
            _, args = line.split("Metadata args:", 1)
            return args.strip().split()
    return []


def resolve_rels_target(rels_path: str, target: str) -> str:
    if rels_path == "_rels/.rels":
        base_dir = ""
    else:
        source_path = rels_path.replace("/_rels/", "/")
        if source_path.endswith(".rels"):
            source_path = source_path[:-5]
        base_dir = os.path.dirname(source_path)
    return os.path.normpath(os.path.join(base_dir, target)).replace("\\", "/")


def validate_docx(path: Path) -> List[str]:
    issues: List[str] = []
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())

            # Parse XML parts
            for name in names:
                if name.startswith("word/") and name.endswith(".xml"):
                    try:
                        ET.fromstring(z.read(name))
                    except ET.ParseError as exc:
                        issues.append(f"XML parse error: {name} ({exc})")

            # Validate relationships and targets
            for rels_name in names:
                if not rels_name.endswith(".rels"):
                    continue
                try:
                    root = ET.fromstring(z.read(rels_name))
                except ET.ParseError as exc:
                    issues.append(f"rels parse error: {rels_name} ({exc})")
                    continue
                for rel in root:
                    target = rel.attrib.get("Target", "")
                    target_mode = rel.attrib.get("TargetMode", "")
                    if target_mode == "External":
                        continue
                    resolved = resolve_rels_target(rels_name, target)
                    if resolved not in names:
                        issues.append(f"missing rel target: {rels_name} -> {target} ({resolved})")

            # Validate r:id references against rels
            for name in names:
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                rels_path = f"{os.path.dirname(name)}/_rels/{os.path.basename(name)}.rels"
                rel_ids = set()
                if rels_path in names:
                    rel_root = ET.fromstring(z.read(rels_path))
                    rel_ids = {rel.attrib.get("Id") for rel in rel_root}
                try:
                    root = ET.fromstring(z.read(name))
                except ET.ParseError:
                    continue
                for el in root.iter():
                    for attr, val in el.attrib.items():
                        if attr.endswith("}id") and "officeDocument/2006/relationships" in attr:
                            if val not in rel_ids:
                                issues.append(f"missing r:id {val} in {name}")

            # ProofState validation
            if "word/settings.xml" in names:
                root = ET.fromstring(z.read("word/settings.xml"))
                proof_states = [el for el in root.iter() if el.tag.endswith("}proofState")]
                if len(proof_states) > 1:
                    issues.append("multiple w:proofState elements in settings.xml")
                for el in proof_states:
                    if any(attr.endswith("}clean") for attr in el.attrib.keys()):
                        issues.append("invalid w:proofState @w:clean attribute")
                    if not any(attr.endswith("}spelling") for attr in el.attrib.keys()) and not any(
                        attr.endswith("}grammar") for attr in el.attrib.keys()
                    ):
                        issues.append("w:proofState missing spelling/grammar attributes")
    except zipfile.BadZipFile as exc:
        issues.append(f"bad zip: {exc}")
    return issues


def run_scrub(
    input_path: Path,
    output_path: Path,
    settings: MetadataCleaningSettings,
) -> Tuple[bool, str, Dict]:
    args = settings.to_cli_args()
    os.environ["MARCUT_METADATA_ARGS"] = " ".join(args)
    success, error, report = pipeline.scrub_metadata_only(
        input_path=str(input_path),
        output_path=str(output_path),
        debug=False,
    )
    if error is None:
        error = ""
    return success, error, report or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run per-toggle metadata scrub matrix.")
    parser.add_argument("--input", required=True, help="Path to input DOCX")
    parser.add_argument("--out", default="runs/metadata-matrix", help="Output directory")
    parser.add_argument("--baseline-args", default="", help="Baseline CLI args string")
    parser.add_argument("--log-path", default=os.path.expanduser("~/Library/Containers/com.marclaw.marcutapp/Data/Library/Application Support/MarcutApp/logs/marcut.log"))
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_args = args.baseline_args.split() if args.baseline_args else read_baseline_args(Path(args.log_path))
    baseline_settings = MetadataCleaningSettings.from_cli_args(baseline_args)

    results = []

    # Baseline run
    baseline_output = out_dir / "baseline.docx"
    success, error, report = run_scrub(input_path, baseline_output, baseline_settings)
    issues = validate_docx(baseline_output)
    results.append({
        "field": "baseline",
        "value": "baseline",
        "success": success,
        "error": error,
        "issues": issues,
    })

    # Per-toggle runs
    for field in fields(MetadataCleaningSettings):
        field_name = field.name
        base_value = getattr(baseline_settings, field_name)
        test_settings = MetadataCleaningSettings.from_cli_args(baseline_args)
        setattr(test_settings, field_name, not base_value)

        output_name = f"{field_name}-{'on' if not base_value else 'off'}.docx"
        output_path = out_dir / output_name
        success, error, report = run_scrub(input_path, output_path, test_settings)
        issues = validate_docx(output_path)

        results.append({
            "field": field_name,
            "value": "on" if not base_value else "off",
            "success": success,
            "error": error,
            "issues": issues,
        })

    # Write summary
    summary_json = out_dir / "summary.json"
    summary_csv = out_dir / "summary.csv"
    summary_json.write_text(json.dumps(results, indent=2))

    with summary_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "value", "success", "error", "issue_count", "issues"])
        for row in results:
            writer.writerow([
                row["field"],
                row["value"],
                row["success"],
                row["error"],
                len(row["issues"]),
                "; ".join(row["issues"]),
            ])

    print(f"Matrix complete. Summary: {summary_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
