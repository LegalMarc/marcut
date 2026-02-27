#!/usr/bin/env python3
"""
Check for dependency updates by comparing pinned versions against PyPI.
Shows which updates are safe (patch/minor) vs potentially breaking (major).
"""

import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

# ANSI colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
NC = "\033[0m"
BOLD = "\033[1m"


def parse_version(version_str: str) -> tuple[int, int, int]:
    """Parse version string into (major, minor, patch) tuple."""
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", version_str)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)


def get_pypi_version(package: str) -> str | None:
    """Query PyPI for the latest version of a package."""
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urlopen(url, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except (URLError, json.JSONDecodeError, KeyError):
        return None


def compare_versions(current: str, latest: str) -> str:
    """Compare versions and return update type: 'major', 'minor', 'patch', or 'current'."""
    curr = parse_version(current)
    lat = parse_version(latest)
    
    if lat <= curr:
        return "current"
    elif lat[0] > curr[0]:
        return "major"
    elif lat[1] > curr[1]:
        return "minor"
    else:
        return "patch"


def load_pinned_requirements(path: Path) -> dict[str, str]:
    """Load pinned requirements from file."""
    requirements = {}
    if not path.exists():
        return requirements
    
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            package, version = line.split("==", 1)
            requirements[package.strip()] = version.strip()
    
    return requirements


def main():
    print(f"\n{BOLD}{BLUE}Checking for Dependency Updates{NC}")
    print("=" * 50)
    
    # Find requirements file
    script_dir = Path(__file__).parent.parent
    req_file = script_dir / "requirements-pinned.txt"
    
    if not req_file.exists():
        print(f"{RED}Error: requirements-pinned.txt not found{NC}")
        sys.exit(1)
    
    requirements = load_pinned_requirements(req_file)
    
    if not requirements:
        print(f"{YELLOW}No pinned requirements found{NC}")
        sys.exit(0)
    
    updates = {"major": [], "minor": [], "patch": [], "current": [], "error": []}
    
    for package, current_version in requirements.items():
        print(f"Checking {package}...", end=" ", flush=True)
        latest = get_pypi_version(package)
        
        if latest is None:
            print(f"{RED}error{NC}")
            updates["error"].append((package, current_version, "N/A"))
        else:
            update_type = compare_versions(current_version, latest)
            updates[update_type].append((package, current_version, latest))
            
            if update_type == "current":
                print(f"{GREEN}up to date{NC}")
            elif update_type == "patch":
                print(f"{GREEN}{latest} (patch){NC}")
            elif update_type == "minor":
                print(f"{YELLOW}{latest} (minor){NC}")
            else:
                print(f"{RED}{latest} (MAJOR){NC}")
    
    # Summary
    print("\n" + "=" * 50)
    print(f"{BOLD}Summary{NC}\n")
    
    if updates["major"]:
        print(f"{RED}{BOLD}⚠️  MAJOR updates (review carefully):{NC}")
        for pkg, curr, lat in updates["major"]:
            print(f"   {pkg}: {curr} → {lat}")
        print()
    
    if updates["minor"]:
        print(f"{YELLOW}📦 Minor updates (generally safe):{NC}")
        for pkg, curr, lat in updates["minor"]:
            print(f"   {pkg}: {curr} → {lat}")
        print()
    
    if updates["patch"]:
        print(f"{GREEN}🔒 Patch updates (safe):{NC}")
        for pkg, curr, lat in updates["patch"]:
            print(f"   {pkg}: {curr} → {lat}")
        print()
    
    if updates["error"]:
        print(f"{RED}❌ Failed to check:{NC}")
        for pkg, curr, _ in updates["error"]:
            print(f"   {pkg}")
        print()
    
    total_updates = len(updates["major"]) + len(updates["minor"]) + len(updates["patch"])
    if total_updates == 0:
        print(f"{GREEN}✅ All dependencies are up to date!{NC}")
    else:
        print(f"Total updates available: {total_updates}")
        if updates["major"]:
            print(f"{YELLOW}Note: Major version updates may contain breaking changes.{NC}")
            print(f"Test thoroughly before updating.{NC}")


if __name__ == "__main__":
    main()
