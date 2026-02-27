#!/usr/bin/env python3
"""
Run Full Test Suite

Runs the complete end-to-end test suite on all sample files and generates a comprehensive report.

Usage:
    python3 scripts/run_full_test_suite.py
"""

import subprocess
import sys
import os
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_python_exec() -> str:
    candidates = [
        REPO_ROOT / ".marcut_artifacts/ignored-resources" / "temp-venvs" / "venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def resolve_sample_dir() -> Path:
    candidates = [
        REPO_ROOT / ".marcut_artifacts/ignored-resources" / "sample-files",
        REPO_ROOT / "sample-files",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def main():
    """Run the full test suite on all sample files"""
    print("🚀 Starting Full Marcut Test Suite")
    print("=" * 60)

    python_exec = resolve_python_exec()
    test_script = REPO_ROOT / "tests" / "scripts" / "test_end_to_end.py"
    sample_dir = resolve_sample_dir()
    cmd = [
        python_exec,
        str(test_script),
        "--debug",
        "--open-files",
        "--sample-files-dir",
        str(sample_dir),
    ]

    print("📋 Running comprehensive tests on all sample files...")
    print("⏱️  This may take 10-20 minutes depending on document size and AI processing time")
    print()

    try:
        # Run the command
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{REPO_ROOT / 'src' / 'python'}:{env.get('PYTHONPATH', '')}"

        result = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            capture_output=False,
            text=True,
        )

        if result.returncode == 0:
            print("\n" + "=" * 60)
            print("✅ FULL TEST SUITE COMPLETED SUCCESSFULLY!")
            print("=" * 60)
            print("\n📁 Generated files are available in: ~/Downloads/MarcutTestSuite/")
            print("📋 Test reports include:")
            print("   - Timestamped DOCX files for both pathways")
            print("   - JSON reports with entity details")
            print("   - Comprehensive test summary")
            print("   - Human review checklist")
            print("\n🔍 Next steps:")
            print("   1. Review the generated files in Microsoft Word")
            print("   2. Complete the human review checklist")
            print("   3. Compare redaction quality between pathways")
            print("   4. Document findings and recommendations")

        else:
            print("\n" + "=" * 60)
            print("❌ TEST SUITE FAILED!")
            print("=" * 60)
            print(f"Return code: {result.returncode}")
            print("Check the output above for error details.")

        return result.returncode

    except KeyboardInterrupt:
        print("\n⏹️  Test suite interrupted by user")
        return 130
    except Exception as e:
        print(f"\n💥 Test suite failed with exception: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
