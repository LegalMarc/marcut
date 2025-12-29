#!/usr/bin/env python3
"""
Run tests using the bundled Python framework that has lxml, docx, etc. installed.
This script launches the MarcutApp with a special test mode.
"""

import subprocess
import sys
import os
import json
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent  # scripts/../ = repo root
APP_PATH = REPO_ROOT / "build_swift" / "MarcutApp.app"
PYTHON_SITE = APP_PATH / "Contents" / "Resources" / "python_site"
TESTS_DIR = REPO_ROOT / "tests"

def run_bundled_test(test_file: str, report_path: str = None):
    """Run a test file using the app's embedded Python via CLI launcher."""
    
    # The app's Python is embedded and accessed via PythonKit
    # We need to run the test inside the app's Python environment
    # The easiest way is to use the CLI launcher with a custom script
    
    cli_launcher = APP_PATH / "Contents" / "Resources" / "marcut_cli_launcher.sh"
    
    if not cli_launcher.exists():
        print(f"❌ CLI launcher not found at {cli_launcher}")
        return False
    
    # Create a test wrapper that imports from python_site
    test_code = f'''
import sys
import os

# Set up paths for bundled environment
python_site = "{PYTHON_SITE}"
sys.path.insert(0, python_site)
sys.path.insert(0, "{REPO_ROOT}")

# Now run the test
os.chdir("{REPO_ROOT}")
exec(open("{test_file}").read())
'''
    
    # Write to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        temp_script = f.name
    
    try:
        # Run via CLI launcher
        result = subprocess.run(
            [str(cli_launcher), "run-script", temp_script],
            capture_output=True,
            text=True,
            timeout=120
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"Error: {e}")
        return False
    finally:
        os.unlink(temp_script)


def run_inline_test():
    """Run tests by directly invoking Python with the right environment."""
    
    # Set environment for bundled Python
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{PYTHON_SITE}:{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    
    # Find the system Python (we'll use it with the bundled site-packages)
    python = sys.executable
    
    test_script = TESTS_DIR / "test_metadata_scrubbing.py"
    report_path = "/tmp/bundled_test_report.json"
    
    print("🧪 Running metadata scrubbing tests with bundled environment...")
    print(f"   PYTHONPATH includes: {PYTHON_SITE}")
    
    result = subprocess.run(
        [python, str(test_script), "--report", report_path],
        env=env,
        cwd=str(REPO_ROOT)
    )
    
    # Check report
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)
        
        print("\n📊 Test Report:")
        print(f"   Tests run: {report['summary']['tests_run']}")
        print(f"   Passed: {report['summary']['tests_run'] - report['summary']['failures'] - report['summary']['errors'] - report['summary']['skipped']}")
        print(f"   Failed: {report['summary']['failures']}")
        print(f"   Errors: {report['summary']['errors']}")
        print(f"   Skipped: {report['summary']['skipped']}")
        print(f"   Success: {'✅' if report['summary']['success'] else '❌'}")
    
    return result.returncode == 0


if __name__ == "__main__":
    success = run_inline_test()
    sys.exit(0 if success else 1)
