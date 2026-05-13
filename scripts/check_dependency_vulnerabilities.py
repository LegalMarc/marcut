#!/usr/bin/env python3
"""Fail if pinned Python dependencies have known OSV vulnerabilities."""

from __future__ import annotations

import json
import sys
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
    pins = read_pins(Path(sys.argv[1] if len(sys.argv) > 1 else "requirements-pinned.txt"))
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

    print(f"Dependency vulnerability gate passed for {len(pins)} pinned packages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
