#!/usr/bin/env python3
"""
Marcut End-to-End Test Suite

Tests both Rules Only and Rules + AI pathways on sample files,
generating timestamped outputs for human review.

Usage:
    python3 scripts/test_end_to_end.py [options]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add project root + src/python to path for imports
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))
sys.path.insert(0, str(REPO_ROOT))

# Optional psutil import for system info
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    from marcut.cli import main as marcut_main
    from marcut.pipeline import RedactionError
except ImportError as e:
    print(f"❌ Failed to import marcut: {e}")
    print("Please install marcut with: pip install -e .")
    sys.exit(1)


class MarcutTestRunner:
    """Main test runner for Marcut end-to-end testing"""

    EXPECTED_CORRUPT_FILES = {
        "Sample 123 Consent Corrupt.docx",
    }

    def __init__(self, args):
        self.args = args
        self.output_dir = Path(args.output_dir).expanduser()
        self.sample_files_dir = Path(args.sample_files_dir)
        self.results = []
        self.test_run_id = datetime.now().strftime("%y-%m-%d %H:%M:%S")

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Verify marcut installation
        self._verify_marcut_installation()

        # Check Ollama status for AI pathway
        self.ollama_available = self._check_ollama_status()

    def _verify_marcut_installation(self):
        """Verify marcut is properly installed"""
        try:
            result = subprocess.run([
                sys.executable, "-m", "marcut.cli", "--help"
            ], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception("marcut CLI not working")
        except Exception as e:
            print(f"❌ Marcut installation verification failed: {e}")
            sys.exit(1)

    def _ollama_tags_url(self) -> str:
        host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
        if "://" not in host:
            host = f"http://{host}"
        return host.rstrip("/") + "/api/tags"

    def _ollama_reachable(self) -> bool:
        try:
            result = subprocess.run(
                ["curl", "-s", self._ollama_tags_url()],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _attempt_start_ollama(self) -> bool:
        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            print("⚠️  Ollama binary not found in PATH; AI pathway disabled")
            return False
        try:
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
        except Exception as e:
            print(f"⚠️  Failed to start Ollama: {e}")
            return False

    def _wait_for_ollama(self, timeout: int = 15) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ollama_reachable():
                return True
            time.sleep(1)
        return False

    def _check_ollama_status(self) -> bool:
        """Check if Ollama is available and running; attempt to start if needed."""
        if self._ollama_reachable():
            print("✅ Ollama service is running")
            return True

        print("⚠️  Ollama not reachable; attempting to start...")
        if self._attempt_start_ollama():
            if self._wait_for_ollama():
                print("✅ Ollama service started")
                return True

        print("⚠️  Ollama service not available - AI pathway disabled")
        return False

    def get_sample_files(self) -> List[Path]:
        """Get list of sample files to test"""
        if self.args.file:
            file_path = Path(self.args.file)
            if not file_path.exists():
                raise FileNotFoundError(f"Sample file not found: {file_path}")
            return [file_path]

        # Get all .docx files in sample directory
        sample_files = list(self.sample_files_dir.glob("*.docx"))
        if not sample_files:
            raise FileNotFoundError(f"No .docx files found in {self.sample_files_dir}")

        return sorted(sample_files)

    def _is_expected_corrupt(self, source_file: Path) -> bool:
        return source_file.name in self.EXPECTED_CORRUPT_FILES

    def generate_output_filename(self, source_file: Path, pathway: str) -> Tuple[str, str]:
        """Generate timestamped output filenames for DOCX and JSON"""
        timestamp = datetime.now().strftime("%y-%m-%d %H:%M:%S")
        base_name = source_file.stem

        docx_name = f"{timestamp} {pathway} - {base_name}.docx"
        json_name = f"{timestamp} {pathway} - {base_name}.json"

        return docx_name, json_name

    def run_marcut_command(self, cmd: List[str]) -> Tuple[bool, str, Dict]:
        """Run a marcut command and return success, output, and timing info"""
        start_time = time.time()

        try:
            if self.args.debug:
                print(f"🔧 Running command: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.args.timeout
            )

            processing_time = time.time() - start_time

            success = result.returncode == 0
            output = result.stdout + result.stderr

            # Try to parse the report for entity count
            entity_count = 0
            try:
                # Extract report path from command
                report_path = None
                for i, arg in enumerate(cmd):
                    if arg == "--report" and i + 1 < len(cmd):
                        report_path = cmd[i + 1]
                        break

                if report_path and Path(report_path).exists():
                    with open(report_path, 'r') as f:
                        report_data = json.load(f)
                        entity_count = len(report_data.get('spans', []))
            except Exception:
                pass  # Entity count parsing failed, continue

            timing_info = {
                "processing_time": processing_time,
                "entity_count": entity_count,
                "return_code": result.returncode
            }

            return success, output, timing_info

        except subprocess.TimeoutExpired:
            processing_time = self.args.timeout
            error_msg = f"Command timed out after {self.args.timeout} seconds"

            timing_info = {
                "processing_time": processing_time,
                "entity_count": 0,
                "return_code": -1,
                "error": "timeout"
            }

            return False, error_msg, timing_info

    def test_rules_only_pathway(self, source_file: Path) -> Dict:
        """Test the Rules Only pathway"""
        print(f"📋 Testing Rules Only pathway: {source_file.name}")

        docx_name, json_name = self.generate_output_filename(source_file, "Rules Only")
        docx_path = self.output_dir / docx_name
        json_path = self.output_dir / json_name

        cmd = [
            sys.executable, "-m", "marcut.cli",
            "redact",
            "--in", str(source_file),
            "--out", str(docx_path),
            "--report", str(json_path),
            "--mode", "rules",  # Rules only
            "--backend", "mock",  # Mock backend
            "--debug" if self.args.debug else ""
        ]

        # Remove empty strings
        cmd = [arg for arg in cmd if arg]

        success, output, timing = self.run_marcut_command(cmd)

        result = {
            "pathway": "rules_only",
            "status": "success" if success else "failed",
            "processing_time": timing["processing_time"],
            "entities_detected": timing["entity_count"],
            "output_file": str(docx_path),
            "report_file": str(json_path),
            "command": ' '.join(cmd)
        }

        if not success:
            result["error"] = output
            print(f"   ❌ Rules Only failed: {output[:200]}...")
        else:
            print(f"   ✅ Rules Only completed in {timing['processing_time']:.1f}s, {timing['entity_count']} entities")

        return result

    def test_ai_pathway(self, source_file: Path) -> Optional[Dict]:
        """Test the Rules + AI pathway"""
        if not self.ollama_available:
            print(f"   ⏭️  Skipping AI pathway - Ollama not available: {source_file.name}")
            return None

        print(f"🤖 Testing AI pathway: {source_file.name}")

        docx_name, json_name = self.generate_output_filename(source_file, "AI")
        docx_path = self.output_dir / docx_name
        json_path = self.output_dir / json_name

        cmd = [
            sys.executable, "-m", "marcut.cli",
            "redact",
            "--in", str(source_file),
            "--out", str(docx_path),
            "--report", str(json_path),
            "--mode", "enhanced",  # Enhanced AI pathway
            "--backend", "ollama",
            "--model", self.args.model,
            "--debug" if self.args.debug else ""
        ]

        # Remove empty strings
        cmd = [arg for arg in cmd if arg]

        success, output, timing = self.run_marcut_command(cmd)

        result = {
            "pathway": "ai",
            "status": "success" if success else "failed",
            "processing_time": timing["processing_time"],
            "entities_detected": timing["entity_count"],
            "output_file": str(docx_path),
            "report_file": str(json_path),
            "command": ' '.join(cmd)
        }

        if not success:
            result["error"] = output
            print(f"   ❌ AI failed: {output[:200]}...")
        else:
            print(f"   ✅ AI completed in {timing['processing_time']:.1f}s, {timing['entity_count']} entities")

        return result

    def validate_output_files(self, source_file: Path, rules_result: Dict, ai_result: Optional[Dict]) -> Dict:
        """Validate that output files were generated correctly"""
        validation = {
            "automated_checks": "pass",
            "issues": []
        }
        expected_corrupt = self._is_expected_corrupt(source_file)

        # Check Rules Only outputs
        for result in [rules_result, ai_result]:
            if not result:
                continue

            if result["status"] != "success":
                validation["issues"].append(f"{result['pathway']}: Processing failed")
                continue

            # Check DOCX file
            docx_path = Path(result["output_file"])
            if not docx_path.exists():
                validation["issues"].append(f"{result['pathway']}: DOCX file not created")
            elif docx_path.stat().st_size == 0:
                validation["issues"].append(f"{result['pathway']}: DOCX file is empty")

            # Check JSON report
            json_path = Path(result["report_file"])
            if not json_path.exists():
                validation["issues"].append(f"{result['pathway']}: JSON report not created")
            else:
                try:
                    with open(json_path, 'r') as f:
                        report_data = json.load(f)
                    if not report_data.get('spans'):
                        validation["issues"].append(f"{result['pathway']}: No redactions in report")
                except json.JSONDecodeError:
                    validation["issues"].append(f"{result['pathway']}: Invalid JSON report")

        if validation["issues"]:
            validation["automated_checks"] = "failed"

        if expected_corrupt and validation["issues"]:
            validation = {
                "automated_checks": "pass",
                "issues": [],
                "expected_corrupt": True,
                "ignored_issues": validation["issues"],
            }
        elif expected_corrupt:
            validation["expected_corrupt"] = True

        return validation

    def compare_pathways(self, source_file: Path, rules_result: Dict, ai_result: Optional[Dict]) -> str:
        """Compare results between Rules Only and AI pathways"""
        if not ai_result or ai_result["status"] != "success":
            return "ai_unavailable"

        if rules_result["status"] != "success":
            return "rules_failed"

        rules_entities = rules_result["entities_detected"]
        ai_entities = ai_result["entities_detected"]

        if ai_entities > rules_entities:
            difference = ai_entities - rules_entities
            return f"ai_detected_{difference}_additional_entities"
        elif ai_entities == rules_entities:
            return "equal_detection"
        else:
            difference = rules_entities - ai_entities
            return f"rules_detected_{difference}_more_entities"

    def open_files_for_review(self, source_file: Path, rules_result: Dict, ai_result: Optional[Dict]):
        """Open generated files for human review"""
        if not self.args.open_files:
            return

        files_to_open = []

        if rules_result["status"] == "success":
            files_to_open.append(rules_result["output_file"])

        if ai_result and ai_result["status"] == "success":
            files_to_open.append(ai_result["output_file"])

        for file_path in files_to_open:
            try:
                subprocess.run(["open", str(file_path)], check=True)
                print(f"   🔍 Opened for review: {Path(file_path).name}")
            except subprocess.CalledProcessError:
                print(f"   ⚠️  Could not open: {Path(file_path).name}")

    def run_single_file_test(self, source_file: Path) -> Dict:
        """Run tests for a single sample file"""
        print(f"\n📄 Testing: {source_file.name}")
        print("=" * 60)

        expected_corrupt = self._is_expected_corrupt(source_file)
        file_result = {
            "source_file": str(source_file),
            "file_size": source_file.stat().st_size,
            "timestamp": datetime.now().isoformat(),
            "expected_corrupt": expected_corrupt
        }

        # Test Rules Only pathway
        rules_result = self.test_rules_only_pathway(source_file)
        file_result["rules_only"] = rules_result

        # Test AI pathway
        ai_result = None
        if not self.args.rules_only:
            ai_result = self.test_ai_pathway(source_file)
            file_result["ai"] = ai_result

        # Validate outputs
        validation = self.validate_output_files(source_file, rules_result, ai_result)
        file_result["validation"] = validation

        # Compare pathways
        comparison = self.compare_pathways(source_file, rules_result, ai_result)
        if expected_corrupt:
            comparison = "expected_corrupt"
        file_result["comparison"] = comparison

        # Open files for review
        self.open_files_for_review(source_file, rules_result, ai_result)

        # Print summary
        print(f"   📊 Comparison: {comparison}")
        if validation.get("expected_corrupt"):
            print(f"   ⚠️  Expected corrupt sample; validation failures ignored")
        elif validation["automated_checks"] == "pass":
            print(f"   ✅ Automated validation passed")
        else:
            print(f"   ❌ Automated validation failed: {', '.join(validation['issues'])}")

        return file_result

    def get_system_info(self) -> Dict:
        """Get system information for the test report"""
        info = {
            "python_version": sys.version,
            "platform": sys.platform,
        }

        if PSUTIL_AVAILABLE:
            info["cpu_count"] = psutil.cpu_count()
            info["memory_gb"] = psutil.virtual_memory().total / (1024**3)
        else:
            info["cpu_count"] = "unknown"
            info["memory_gb"] = "unknown"

        # Get marcut version
        try:
            import marcut
            info["marcut_version"] = getattr(marcut, '__version__', 'unknown')
        except ImportError:
            info["marcut_version"] = "unknown"

        # Get Ollama status
        info["ollama_status"] = "available" if self.ollama_available else "unavailable"

        if self.ollama_available:
            try:
                result = subprocess.run([
                    "curl", "-s", "http://localhost:11434/api/tags"
                ], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    data = json.loads(result.stdout)
                    info["models_available"] = [model["name"] for model in data.get("models", [])]
            except Exception:
                info["models_available"] = []

        return info

    def generate_test_report(self) -> Dict:
        """Generate comprehensive test report"""
        eligible_results = [r for r in self.results if not r.get("expected_corrupt")]
        expected_corrupt_count = len(self.results) - len(eligible_results)
        successful_rules = sum(1 for r in eligible_results if r.get("rules_only", {}).get("status") == "success")
        successful_ai = sum(1 for r in eligible_results if (r.get("ai") or {}).get("status") == "success")

        # Calculate averages
        rules_times = [r["rules_only"]["processing_time"] for r in eligible_results
                      if r.get("rules_only", {}).get("status") == "success"]
        ai_times = [r["ai"]["processing_time"] for r in eligible_results
                   if (r.get("ai") or {}).get("status") == "success"]

        avg_rules_time = sum(rules_times) / len(rules_times) if rules_times else 0
        avg_ai_time = sum(ai_times) / len(ai_times) if ai_times else 0

        report = {
            "test_run_id": self.test_run_id,
            "timestamp": datetime.now().isoformat(),
            "system_info": self.get_system_info(),
            "configuration": {
                "ai_model": self.args.model,
                "enhanced_mode": True,
                "debug_mode": self.args.debug,
                "timeout": self.args.timeout,
                "open_files": self.args.open_files
            },
            "results": self.results,
            "summary": {
                "total_files": len(eligible_results),
                "expected_corrupt_files": expected_corrupt_count,
                "total_files_tested": len(self.results),
                "rules_only_success": successful_rules,
                "ai_success": successful_ai,
                "average_processing_time_rules": round(avg_rules_time, 2),
                "average_processing_time_ai": round(avg_ai_time, 2),
                "total_processing_time": round(sum(r.get("total_time", 0) for r in self.results), 2)
            }
        }

        return report

    def save_test_report(self, report: Dict):
        """Save test report to file"""
        report_filename = f"test_results_{datetime.now().strftime('%y-%m-%d_%H-%M-%S')}.json"
        report_path = self.output_dir / report_filename

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\n📋 Test report saved: {report_path}")
        return report_path

    def test_app_bundle(self) -> Dict:
        """Test macOS app bundle functionality"""
        if not self.args.test_app_bundle:
            return {"app_bundle_tested": False, "reason": "Not requested"}

        print(f"\n🍎 Testing macOS App Bundle...")

        # Import the app bundle tester
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from test_macos_app import MacOSAppTester
        except ImportError as e:
            print(f"❌ Cannot import app bundle tester: {e}")
            return {"app_bundle_tested": False, "reason": f"Import error: {e}"}

        try:
            tester = MacOSAppTester(self.args.app_path)
            results = tester.run_all_tests()

            # Convert to simpler format for integration
            app_bundle_result = {
                "app_bundle_tested": True,
                "app_path": str(results["app_path"]),
                "overall_success": results["overall_success"],
                "tests_passed": results["tests_passed"],
                "total_tests": results["total_tests"],
                "duration": results["duration_seconds"],
                "test_results": results["test_results"]
            }

            # Log summary
            status = "✅ PASSED" if results["overall_success"] else "❌ FAILED"
            print(f"\n📊 App Bundle Test: {status}")
            print(f"   Tests: {results['tests_passed']}/{results['total_tests']} passed")
            print(f"   Duration: {results['duration_seconds']:.1f}s")

            return app_bundle_result

        except Exception as e:
            error_msg = f"App bundle testing failed: {e}"
            print(f"❌ {error_msg}")
            if self.args.debug:
                import traceback
                traceback.print_exc()
            return {"app_bundle_tested": False, "reason": error_msg}

    def run(self):
        """Run the complete test suite"""
        print(f"🚀 Starting Marcut End-to-End Test Suite")
        print(f"📅 Test Run ID: {self.test_run_id}")
        print(f"📁 Output Directory: {self.output_dir}")
        print(f"🤖 AI Available: {self.ollama_available}")

        try:
            # Test app bundle first if requested
            app_bundle_result = self.test_app_bundle()

            sample_files = self.get_sample_files()
            print(f"📄 Found {len(sample_files)} sample files to test")

            for source_file in sample_files:
                start_time = time.time()

                file_result = self.run_single_file_test(source_file)
                file_result["total_time"] = time.time() - start_time

                self.results.append(file_result)

            # Generate and save report
            report = self.generate_test_report()

            # Add app bundle results to report
            if app_bundle_result.get("app_bundle_tested"):
                report["app_bundle_test"] = app_bundle_result

            report_path = self.save_test_report(report)

            # Print final summary
            self.print_final_summary(report)

            # Check app bundle test success
            if app_bundle_result.get("app_bundle_tested") and not app_bundle_result.get("overall_success", True):
                print(f"\n❌ App bundle tests failed")
                return 1

            # Return appropriate exit code
            failed_validations = sum(1 for r in self.results
                                   if r.get("validation", {}).get("automated_checks") == "failed")

            if failed_validations > 0:
                print(f"\n⚠️  {failed_validations} files had validation failures")
                return 1

            print(f"\n✅ All tests completed successfully!")
            return 0

        except KeyboardInterrupt:
            print(f"\n⏹️  Test suite interrupted by user")
            return 130
        except Exception as e:
            print(f"\n💥 Test suite failed: {e}")
            if self.args.debug:
                import traceback
                traceback.print_exc()
            return 1

    def print_final_summary(self, report: Dict):
        """Print final test summary"""
        summary = report["summary"]

        print(f"\n" + "=" * 60)
        print(f"📊 FINAL TEST SUMMARY")
        print(f"=" * 60)
        print(f"📄 Total Files Tested: {summary['total_files_tested']}")
        if summary.get("expected_corrupt_files"):
            print(f"🧪 Expected Corrupt Samples: {summary['expected_corrupt_files']}")
        print(f"✅ Rules Only Success: {summary['rules_only_success']}/{summary['total_files']}")
        print(f"✅ AI Pathway Success: {summary['ai_success']}/{summary['total_files']}")
        print(f"⏱️  Avg Rules Time: {summary['average_processing_time_rules']:.1f}s")
        print(f"⏱️  Avg AI Time: {summary['average_processing_time_ai']:.1f}s")
        print(f"⏱️  Total Time: {summary['total_processing_time']:.1f}s")

        # Print pathway comparisons
        print(f"\n📈 Pathway Comparisons:")
        comparisons = {}
        for result in self.results:
            comparison = result.get("comparison", "unknown")
            comparisons[comparison] = comparisons.get(comparison, 0) + 1

        for comparison, count in sorted(comparisons.items()):
            print(f"   {count:2d} files: {comparison.replace('_', ' ').title()}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Marcut End-to-End Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run full test suite
    python3 scripts/test_end_to_end.py

    # Test specific file
    python3 scripts/test_end_to_end.py --file sample-files/Sample 123 Consent.docx

    # Rules Only only
    python3 scripts/test_end_to_end.py --rules-only

    # Debug mode
    python3 scripts/test_end_to_end.py --debug
        """
    )

    parser.add_argument(
        "--file", "-f",
        help="Specific sample file to test (default: all files)"
    )

    parser.add_argument(
        "--output-dir", "-o",
        default="~/Downloads/MarcutTestSuite",
        help="Output directory for test results (default: ~/Downloads/MarcutTestSuite)"
    )

    parser.add_argument(
        "--sample-files-dir", "-s",
        default="sample-files",
        help="Directory containing sample files (default: sample-files)"
    )

    parser.add_argument(
        "--model", "-m",
        default="llama3.1:8b",
        help="AI model to use for enhanced pathway (default: llama3.1:8b)"
    )

    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=1200,
        help="Timeout per document in seconds (default: 1200)"
    )

    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="Test only Rules Only pathway"
    )

    parser.add_argument(
        "--ai-only",
        action="store_true",
        help="Test only AI pathway (requires Ollama)"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )

    parser.add_argument(
        "--open-files",
        action="store_true",
        help="Open generated files for review"
    )

    parser.add_argument(
        "--test-app-bundle",
        action="store_true",
        help="Test macOS app bundle functionality (comprehensive testing)"
    )

    parser.add_argument(
        "--app-path",
        type=Path,
        help="Path to MarcutApp.app bundle for app bundle testing"
    )

    args = parser.parse_args()

    # Validate arguments
    if args.rules_only and args.ai_only:
        print("❌ Cannot specify both --rules-only and --ai-only")
        return 1

    # Enforce a sane minimum timeout for large documents/AI runs
    min_timeout = 1200
    if args.timeout < min_timeout:
        print(f"⚠️  Timeout too low ({args.timeout}s); raising to {min_timeout}s.")
        args.timeout = min_timeout

    # Create and run test suite
    runner = MarcutTestRunner(args)
    return runner.run()


if __name__ == "__main__":
    sys.exit(main())
