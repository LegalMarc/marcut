#!/usr/bin/env python3
"""
Run Full Test Suite

Runs the complete end-to-end test suite on all sample files and generates a comprehensive report.

Usage:
    python3 scripts/run_full_test_suite.py
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime


def main():
    """Run the full test suite on all sample files"""
    print("🚀 Starting Full Marcut Test Suite")
    print("=" * 60)

    # Activate virtual environment and run test suite
    cmd = [
        "source", ".venv/bin/activate", "&&",
        "python", "scripts/test_end_to_end.py",
        "--debug",  # Enable debug output
        "--open-files"  # Open files for human review
    ]

    print("📋 Running comprehensive tests on all sample files...")
    print("⏱️  This may take 10-20 minutes depending on document size and AI processing time")
    print()

    try:
        # Run the command
        result = subprocess.run(
            " ".join(cmd),
            shell=True,
            cwd=Path.cwd(),
            capture_output=False,  # Show output in real-time
            text=True
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