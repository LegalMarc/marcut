#!/usr/bin/env python3
"""Generate a minimal CycloneDX-style SBOM from pinned Python dependencies."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def read_pins(path: Path) -> list[tuple[str, str]]:
    pins: list[tuple[str, str]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise SystemExit(f"Unsupported requirement in {path}: {line}")
        name, version = line.split("==", 1)
        pins.append((name.strip(), version.strip()))
    return pins


def build_sbom(pins: list[tuple[str, str]]) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "component": {
                "type": "application",
                "name": "Marcut",
            },
        },
        "components": [
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
            }
            for name, version in pins
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", default="requirements-pinned.txt")
    parser.add_argument("--output", default="docs/release/python-sbom.json")
    parser.add_argument("--check", action="store_true", help="Verify the SBOM exists and matches pinned components")
    args = parser.parse_args()

    pins = read_pins(Path(args.requirements))
    expected = build_sbom(pins)
    output = Path(args.output)

    if args.check:
        if not output.exists():
            raise SystemExit(f"SBOM missing: {output}")
        existing = json.loads(output.read_text(encoding="utf-8"))
        existing_components = {
            (component.get("name"), component.get("version"))
            for component in existing.get("components", [])
        }
        expected_components = set(pins)
        if existing_components != expected_components:
            raise SystemExit(f"SBOM components do not match {args.requirements}")
        print(f"SBOM OK: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
