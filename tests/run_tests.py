#!/usr/bin/env python3
"""
Test runner script for Marcut
Runs both Swift and Python tests
"""

import sys
import subprocess
import os
from pathlib import Path
import json


def resolve_python_executable(project_root: Path) -> str:
    venv_python = project_root / "ignored-resources" / "temp-venvs" / "venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return "python3"

def run_swift_tests(project_root: Path):
    """Run Swift unit tests"""
    print("🧪 Running Swift Unit Tests...")

    swift_project = project_root / "src" / "swift" / "MarcutApp"
    if not swift_project.exists():
        print(f"❌ Swift project not found at {swift_project}")
        return False
        
    pwd = os.getcwd()
    os.chdir(swift_project)

    try:
        result = subprocess.run(
            ["swift", "test", "--parallel"],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            print("✅ Swift tests passed!")
            # print(result.stdout) # Less verbose
        else:
            print("❌ Swift tests failed!")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("⏰ Swift tests timed out!")
        return False
    except FileNotFoundError:
        print("⚠️ Swift not found - skipping Swift tests")
        return True
    finally:
        os.chdir(pwd)

    return True

def run_python_tests(project_root: Path):
    """Run Python unit tests"""
    print("\n🐍 Running Python Unit Tests...")

    # Set up Python path to include local package
    marcut_pkg = project_root / "src" / "python"
    
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{marcut_pkg}:{env.get('PYTHONPATH', '')}"
    python_exec = resolve_python_executable(project_root)

    tests_dir = project_root / "tests"

    try:
        # Try to run with pytest
        result = subprocess.run(
            [python_exec, "-m", "pytest", str(tests_dir), "-v"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            print("✅ Python tests passed!")
            # print(result.stdout)
            return True
        else:
            print("❌ Python tests failed!")
            print(result.stderr)
            return False

    except subprocess.TimeoutExpired:
        print("⏰ Python tests timed out!")
        return False
    except FileNotFoundError:
        print("⚠️ Python3 not found!")
        return False

def run_url_tests_only(project_root: Path):
    """Run only URL redaction tests"""
    print("\n🔗 Running URL Redaction Tests...")
    return run_python_tests(project_root) # Simplified to just run py tests for now

def run_metadata_tests(project_root: Path, report_path: str = None):
    """Run metadata scrubbing tests with optional JSON report."""
    print("\n🧹 Running Metadata Scrubbing Tests...")

    marcut_pkg = project_root / "src" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{marcut_pkg}:{env.get('PYTHONPATH', '')}"
    python_exec = resolve_python_executable(project_root)
    
    script_path = project_root / "tests" / "scripts" / "test_metadata_scrubbing.py"
    # Fallback if specific script not found, run generic pytest
    if not script_path.exists():
         print("⚠️ Metadata test script not found in tests/scripts/, running full suite")
         return run_python_tests(project_root)

    cmd = [python_exec, str(script_path)]
    if report_path:
        cmd.extend(["--report", report_path])

    try:
        result = subprocess.run(
            cmd,
            env=env,
            timeout=120
        )

        if result.returncode == 0:
            print("✅ Metadata scrubbing tests passed!")
            return True
        else:
            print("❌ Metadata scrubbing tests failed!")
            return False

    except Exception as e:
        print(f"⚠️ Could not run metadata tests: {e}")
        return False


def run_metadata_matrix_tests(project_root: Path):
    """Run per-toggle metadata matrix validation."""
    print("\n🧪 Running Metadata Matrix Validation...")

    marcut_pkg = project_root / "src" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{marcut_pkg}:{env.get('PYTHONPATH', '')}"
    python_exec = resolve_python_executable(project_root)

    input_doc = project_root / "ignored-resources" / "sample-files" / "Shareholder-Consent.docx"
    output_dir = project_root / "ignored-resources" / "runs" / "metadata-matrix"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    script_path = project_root / "tests" / "scripts" / "run_metadata_matrix.py"
    
    if not input_doc.exists():
        print("⚠️ Sample DOCX missing in ignored-resources/sample-files; skipping metadata matrix.")
        return True

    cmd = [
        python_exec,
        str(script_path),
        "--input",
        str(input_doc),
        "--out",
        str(output_dir),
        "--baseline-args",
        "",
    ]

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode != 0:
            print("❌ Metadata matrix script failed!")
            print(result.stdout)
            print(result.stderr)
            return False

        if not summary_json.exists():
            print("❌ Metadata matrix summary.json not found!")
            return False

        rows = json.loads(summary_json.read_text())
        issues = [row for row in rows if row.get("issues")]
        if issues:
            print(f"❌ Metadata matrix found {len(issues)} issue(s).")
            for row in issues[:5]:
                print(f" - {row.get('field')} {row.get('value')}: {row.get('issues')}")
            return False

        print("✅ Metadata matrix validation passed!")
        return True
    except Exception as e:
        print(f"⚠️ Could not run metadata matrix tests: {e}")
        return False

def main():
    """Main test runner"""
    import argparse

    parser = argparse.ArgumentParser(description="Marcut Test Runner")
    parser.add_argument("--swift-only", action="store_true", help="Run only Swift tests")
    parser.add_argument("--python-only", action="store_true", help="Run only Python tests")
    parser.add_argument("--url-only", action="store_true", help="Run only URL redaction tests")
    parser.add_argument("--metadata-only", action="store_true", help="Run only metadata scrubbing tests")
    parser.add_argument("--metadata-matrix", action="store_true", help="Run metadata matrix validation tests")
    parser.add_argument("--metadata-report", type=str, help="Path for metadata test JSON report")
    parser.add_argument("--quick", action="store_true", help="Run quick tests only")

    args = parser.parse_args()
    
    # Calculate project root (assuming this script is in tests/run_tests.py)
    # project_root/tests/run_tests.py
    project_root = Path(__file__).resolve().parent.parent

    print(f"🚀 Marcut Test Suite (Root: {project_root.name})")
    print("=" * 50)

    success = True

    if args.url_only:
        success = run_url_tests_only(project_root)
    elif args.metadata_only:
        success = run_metadata_tests(project_root, args.metadata_report)
    elif args.metadata_matrix:
        success = run_metadata_matrix_tests(project_root)
    elif args.swift_only:
        success = run_swift_tests(project_root)
    elif args.python_only:
        success = run_python_tests(project_root)
    else:
        # Run all tests
        if not args.quick:
            success &= run_swift_tests(project_root)
        success &= run_python_tests(project_root)
        if args.metadata_report or args.metadata_only:
             success &= run_metadata_tests(project_root, args.metadata_report)
        # Matrix tests are heavy/optional by default unless requested or full suite?
        # success &= run_metadata_matrix_tests(project_root) 

    print("\n" + "=" * 50)
    if success:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())
