#!/usr/bin/env python3
"""Fail if shipped Python dependencies have known OSV vulnerabilities."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path


OSV_QUERY_BATCH_URL = "https://api.osv.dev/v1/querybatch"


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


def read_pypi_components_from_sbom(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pins: list[tuple[str, str]] = []
    manual: list[str] = []
    for component in payload.get("components", []):
        purl = str(component.get("purl", ""))
        name = str(component.get("name", "")).strip()
        version = str(component.get("version", "")).strip()
        if purl.startswith("pkg:pypi/") and name and version:
            pins.append((name, version))
            continue
        properties = component.get("properties") or []
        if any(prop.get("name") == "marcut:manual_review" for prop in properties if isinstance(prop, dict)):
            manual.append(f"{name or 'unknown'} {version or ''}".strip())
    return sorted(set(pins)), manual


def query_osv(pins: list[tuple[str, str]]) -> dict:
    payload = {
        "queries": [
            {
                "package": {"name": name, "ecosystem": "PyPI"},
                "version": version,
            }
            for name, version in pins
        ]
    }
    request = urllib.request.Request(
        OSV_QUERY_BATCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", nargs="?", default="requirements-pinned.txt")
    parser.add_argument("--sbom", default="docs/release/python-sbom.json")
    args = parser.parse_args()

    sbom_path = Path(args.sbom)
    manual: list[str] = []
    if sbom_path.exists():
        pins, manual = read_pypi_components_from_sbom(sbom_path)
    else:
        pins = read_pins(Path(args.requirements))
    if not pins:
        raise SystemExit("No PyPI components found for vulnerability scan")

    result = query_osv(pins)
    vulnerable: list[str] = []
    for (name, version), package_result in zip(pins, result.get("results", [])):
        vulns = package_result.get("vulns") or []
        if not vulns:
            continue
        ids = ", ".join(vuln.get("id", "unknown") for vuln in vulns)
        vulnerable.append(f"{name}=={version}: {ids}")

    if vulnerable:
        print("Dependency vulnerability gate failed:", file=sys.stderr)
        for line in vulnerable:
            print(f"- {line}", file=sys.stderr)
        return 1

    print(f"Dependency vulnerability gate passed for {len(pins)} shipped PyPI packages.")
    if manual:
        print("Manual vulnerability review required for unsupported shipped components:")
        for item in manual:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
