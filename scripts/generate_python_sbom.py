#!/usr/bin/env python3
"""Generate a CycloneDX-style SBOM for shipped Marcut components.

The default scan targets the staged Swift app resources in this checkout. For
release validation, pass --bundle-root /path/to/MarcutApp.app so the SBOM is
derived from the actual bundle being distributed.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import subprocess
import uuid
from email.parser import Parser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STAGED_PYTHON_SITE = REPO_ROOT / "src/swift/MarcutApp/Sources/MarcutApp/python_site"
DEFAULT_PACKAGE_RESOLVED = REPO_ROOT / "src/swift/MarcutApp/Package.resolved"


def read_pins(path: Path) -> list[tuple[str, str]]:
    pins: list[tuple[str, str]] = []
    if not path.exists():
        return pins
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            raise SystemExit(f"Unsupported requirement in {path}: {line}")
        name, version = line.split("==", 1)
        pins.append((name.strip(), version.strip()))
    return pins


def _component_key(component: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(component.get("type", "")),
        str(component.get("name", "")).lower(),
        str(component.get("version", "")),
    )


def _dedupe(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for component in components:
        key = _component_key(component)
        if key in seen:
            continue
        seen.add(key)
        out.append(component)
    return sorted(out, key=lambda item: (str(item.get("type", "")), str(item.get("name", "")).lower()))


def _dist_info_components(python_site: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    if not python_site.exists():
        return components
    for metadata_path in sorted(python_site.glob("*.dist-info/METADATA")):
        metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8", errors="replace"))
        name = (metadata.get("Name") or metadata_path.parent.name.rsplit("-", 1)[0]).strip()
        version = (metadata.get("Version") or "").strip()
        if not name or not version:
            continue
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "properties": [
                {"name": "marcut:source", "value": str(metadata_path.relative_to(REPO_ROOT)) if metadata_path.is_relative_to(REPO_ROOT) else str(metadata_path)}
            ],
        })
    return components


def _swift_components(package_resolved: Path) -> list[dict[str, Any]]:
    if not package_resolved.exists():
        return []
    payload = json.loads(package_resolved.read_text(encoding="utf-8"))
    components = []
    for pin in payload.get("pins", []):
        state = pin.get("state", {}) or {}
        name = pin.get("identity") or Path(pin.get("location", "")).stem
        version = state.get("version") or state.get("revision") or "unversioned"
        component = {
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:github/{pin.get('location', '').rstrip('/').split('github.com/')[-1].removesuffix('.git')}@{version}" if "github.com/" in pin.get("location", "") else "",
            "externalReferences": [{"type": "vcs", "url": pin.get("location", "")}],
            "properties": [
                {"name": "marcut:ecosystem", "value": "swiftpm"},
                {"name": "marcut:revision", "value": state.get("revision", "")},
            ],
        }
        if not component["purl"]:
            component.pop("purl")
        components.append(component)
    return components


def _python_framework_component(bundle_root: Path | None) -> dict[str, Any]:
    candidates = []
    if bundle_root:
        candidates.append(bundle_root / "Contents/Frameworks/Python.framework/Resources/Info.plist")
    for path in candidates:
        if path.exists():
            try:
                info = plistlib.loads(path.read_bytes())
                version = str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "unknown")
            except Exception:
                version = "unknown"
            return {
                "type": "framework",
                "name": "Python.framework",
                "version": version,
                "properties": [
                    {"name": "marcut:ecosystem", "value": "beeware-python-support"},
                    {"name": "marcut:source", "value": str(path)},
                ],
            }
    return {
        "type": "framework",
        "name": "Python.framework",
        "version": "manual-review-required",
        "properties": [
            {"name": "marcut:manual_review", "value": "BeeWare Python framework version must be checked from the release bundle."}
        ],
    }


def _ollama_component(bundle_root: Path | None) -> dict[str, Any]:
    candidates = []
    if bundle_root:
        candidates.append(bundle_root / "Contents/Resources/ollama")
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        version = "unknown"
        try:
            completed = subprocess.run([str(path), "--version"], check=False, capture_output=True, text=True, timeout=5)
            output = (completed.stdout + completed.stderr).strip()
            if output:
                version = output.splitlines()[0].strip()
        except Exception:
            pass
        return {
            "type": "application",
            "name": "Ollama",
            "version": version,
            "properties": [
                {"name": "marcut:manual_review", "value": "Confirm embedded Ollama provenance and vulnerability status for each public release."},
                {"name": "marcut:source", "value": str(path)},
            ],
        }
    return {
        "type": "application",
        "name": "Ollama",
        "version": "manual-review-required",
        "properties": [
            {"name": "marcut:manual_review", "value": "Embedded Ollama binary was not present in the scanned root; verify from the release bundle."}
        ],
    }


def _python_site_for_bundle(bundle_root: Path | None) -> Path:
    if bundle_root:
        candidate = bundle_root / "Contents/Resources/python_site"
        if candidate.exists():
            return candidate
    return DEFAULT_STAGED_PYTHON_SITE


def build_sbom(requirements: Path, bundle_root: Path | None = None, package_resolved: Path = DEFAULT_PACKAGE_RESOLVED) -> dict:
    python_site = _python_site_for_bundle(bundle_root)
    components = _dist_info_components(python_site)
    if not components:
        components = [
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
                "properties": [{"name": "marcut:source", "value": str(requirements)}],
            }
            for name, version in read_pins(requirements)
        ]
    components.extend(_swift_components(package_resolved))
    components.append(_python_framework_component(bundle_root))
    components.append(_ollama_component(bundle_root))
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
            "properties": [
                {"name": "marcut:sbom_source", "value": str(bundle_root or python_site)},
                {"name": "marcut:unsupported_vulnerability_checks", "value": "SwiftPM Git revisions, BeeWare Python framework, and embedded Ollama require manual release review unless external scanner support is added."},
            ],
        },
        "components": _dedupe(components),
    }


def _component_pairs(components: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {
        (
            str(component.get("type", "")),
            str(component.get("name", "")).lower(),
            str(component.get("version", "")),
        )
        for component in components
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", default="requirements-pinned.txt")
    parser.add_argument("--bundle-root", help="Path to MarcutApp.app for release-derived SBOM generation")
    parser.add_argument("--package-resolved", default=str(DEFAULT_PACKAGE_RESOLVED))
    parser.add_argument("--output", default="docs/release/python-sbom.json")
    parser.add_argument("--check", action="store_true", help="Verify the SBOM exists and covers currently staged shipped components")
    args = parser.parse_args()

    bundle_root = Path(args.bundle_root).resolve() if args.bundle_root else None
    requirements = Path(args.requirements)
    package_resolved = Path(args.package_resolved)
    expected = build_sbom(requirements, bundle_root, package_resolved)
    output = Path(args.output)

    if args.check:
        if not output.exists():
            raise SystemExit(f"SBOM missing: {output}")
        existing = json.loads(output.read_text(encoding="utf-8"))
        existing_pairs = _component_pairs(existing.get("components", []))
        expected_pairs = _component_pairs(expected.get("components", []))
        missing = sorted(expected_pairs - existing_pairs)
        if missing:
            raise SystemExit(f"SBOM missing shipped components: {missing}")
        print(f"SBOM OK: {output} covers {len(expected_pairs)} shipped components")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
