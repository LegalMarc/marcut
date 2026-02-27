#!/usr/bin/env python3
"""
macOS App Bundle Testing for Marcut

Tests the actual .app bundle (not just CLI) to verify:
- App launches without critical errors
- Environment readiness
- Python framework availability
- Ollama binary presence
- App startup logs for errors

This complements the CLI test suite by validating the bundled macOS app.
"""

import argparse
import json
import os
import plistlib
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "build-scripts" / "config.json"


def resolve_build_dir() -> Path:
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text())
            build_dir = config.get("build_dir")
            if build_dir:
                return (CONFIG_PATH.parent / build_dir).resolve()
        except Exception:
            pass

    candidates = [
        REPO_ROOT / ".marcut_artifacts/ignored-resources" / "builds" / "build_swift",
        REPO_ROOT / "build_swift",
        REPO_ROOT / "build",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


class MacOSAppTester:
    """Test the macOS app bundle for Marcut"""

    def __init__(self, app_path: Optional[Path] = None):
        self.app_path = app_path or self._find_default_app()
        self.test_results = []
        self.start_time = datetime.now()

    def _find_default_app(self) -> Path:
        """Find the default Marcut.app bundle"""
        build_dir = resolve_build_dir()
        possible_paths = [
            build_dir / "MarcutApp.app",
            Path("/Applications/MarcutApp.app"),
            Path("~/Applications/MarcutApp.app").expanduser(),
            REPO_ROOT / "MarcutApp" / "build" / "MarcutApp.app",
            REPO_ROOT / "MarcutApp" / ".build" / "release" / "MarcutApp.app"
        ]

        for path in possible_paths:
            if path.exists() and path.is_dir() and path.suffix == ".app":
                return path

        raise FileNotFoundError("No MarcutApp.app bundle found. Please specify --app-path")

    def log_test(self, test_name: str, success: bool, message: str, details: Dict = None):
        """Log a test result"""
        result = {
            "test": test_name,
            "success": success,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "details": details or {}
        }
        self.test_results.append(result)

        status = "✅" if success else "❌"
        print(f"{status} {test_name}: {message}")

        if details:
            for key, value in details.items():
                print(f"    {key}: {value}")

    def test_app_bundle_structure(self) -> bool:
        """Test that the app bundle has correct structure"""
        print("\n🔍 Testing App Bundle Structure...")

        required_structure = {
            "Contents/MacOS/MarcutApp": "Main executable",
            "Contents/Info.plist": "App metadata",
            "Contents/Resources/": "Resources directory",
            "Contents/Frameworks/": "Frameworks directory"
        }

        all_passed = True

        for rel_path, description in required_structure.items():
            full_path = self.app_path / rel_path
            exists = full_path.exists()

            self.log_test(
                f"Bundle Structure: {rel_path}",
                exists,
                f"{description} {'found' if exists else 'missing'}",
                {"path": str(full_path)}
            )

            if not exists:
                all_passed = False

        return all_passed

    def test_info_plist(self) -> bool:
        """Test Info.plist configuration"""
        print("\n📋 Testing Info.plist...")

        info_plist = self.app_path / "Contents/Info.plist"
        if not info_plist.exists():
            self.log_test("Info.plist", False, "Info.plist file not found")
            return False

        try:
            with open(info_plist, 'rb') as f:
                plist_data = plistlib.load(f)

            required_keys = {
                "CFBundleIdentifier": "Bundle identifier",
                "CFBundleName": "Bundle name",
                "CFBundleExecutable": "Executable name",
                "CFBundleVersion": "Bundle version"
            }

            all_passed = True

            for key, description in required_keys.items():
                exists = key in plist_data
                value = plist_data.get(key, "MISSING")

                self.log_test(
                    f"Info.plist: {key}",
                    exists,
                    f"{description}: {value}",
                    {"value": str(value)}
                )

                if not exists:
                    all_passed = False

            return all_passed

        except Exception as e:
            self.log_test("Info.plist", False, f"Failed to read Info.plist: {e}")
            return False

    def test_python_framework(self) -> bool:
        """Test Python framework availability"""
        print("\n🐍 Testing Python Framework...")

        framework_paths = [
            "Contents/Frameworks/Python.framework",
            "Contents/Frameworks/Python.framework/Versions/3.11",
            "Contents/Frameworks/Python.framework/Versions/3.11/Python"
        ]

        all_passed = True

        for rel_path in framework_paths:
            full_path = self.app_path / rel_path
            exists = full_path.exists()

            self.log_test(
                f"Python Framework: {rel_path}",
                exists,
                f"Framework component {'found' if exists else 'missing'}",
                {"path": str(full_path)}
            )

            if not exists:
                all_passed = False

        # Test Python executable if framework exists
        python_exec = self.app_path / "Contents/Frameworks/Python.framework/Versions/3.11/Python"
        if python_exec.exists():
            try:
                result = subprocess.run(
                    [str(python_exec), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                success = result.returncode == 0
                version = result.stdout.strip() or result.stderr.strip()

                self.log_test(
                    "Python Framework Executable",
                    success,
                    f"Python version: {version}" if success else f"Python test failed: {result.stderr}",
                    {"executable": str(python_exec), "version": version}
                )

                if not success:
                    all_passed = False

            except subprocess.TimeoutExpired:
                self.log_test("Python Framework Executable", False, "Python executable timeout")
                all_passed = False
            except Exception as e:
                self.log_test("Python Framework Executable", False, f"Python test error: {e}")
                all_passed = False

        return all_passed

    def test_ollama_binary(self) -> bool:
        """Test Ollama binary availability"""
        print("\n🤖 Testing Ollama Binary...")

        ollama_paths = [
            "Contents/Resources/ollama",
            "Contents/MacOS/ollama"
        ]

        ollama_found = False

        for rel_path in ollama_paths:
            full_path = self.app_path / rel_path

            if full_path.exists():
                ollama_found = True

                # Test if executable
                is_executable = os.access(full_path, os.X_OK)
                self.log_test(
                    f"Ollama Binary: {rel_path}",
                    is_executable,
                    f"Ollama binary {'executable' if is_executable else 'not executable'}",
                    {"path": str(full_path)}
                )

                if is_executable:
                    # Test Ollama version
                    try:
                        result = subprocess.run(
                            [str(full_path), "--version"],
                            capture_output=True,
                            text=True,
                            timeout=10
                        )

                        success = result.returncode == 0
                        version = result.stdout.strip() or result.stderr.strip()

                        self.log_test(
                            "Ollama Binary Version",
                            success,
                            f"Ollama version: {version}" if success else f"Version check failed: {result.stderr}",
                            {"version": version}
                        )

                    except subprocess.TimeoutExpired:
                        self.log_test("Ollama Binary Version", False, "Ollama version check timeout")
                    except Exception as e:
                        self.log_test("Ollama Binary Version", False, f"Version check error: {e}")

        if not ollama_found:
            self.log_test("Ollama Binary", False, "No Ollama binary found in app bundle")

        return ollama_found

    def test_app_startup(self) -> bool:
        """Test app startup and monitor for errors"""
        print("\n🚀 Testing App Startup...")

        executable = self.app_path / "Contents/MacOS/MarcutApp"
        if not executable.exists():
            self.log_test("App Startup", False, "Main executable not found")
            return False

        try:
            # Start the app process
            process = subprocess.Popen(
                [str(executable), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            try:
                stdout, stderr = process.communicate(timeout=30)

                # Check for successful execution
                success = process.returncode == 0

                # Analyze output for error patterns
                error_patterns = [
                    "Environment Not Ready",
                    "PythonKit initialization failed",
                    "Failed to locate Python.framework",
                    "Ollama service not available",
                    "fatal error",
                    "assertion failure",
                    "Segmentation fault",
                    "Abort trap"
                ]

                output_text = stdout + stderr
                found_errors = []

                for pattern in error_patterns:
                    if pattern.lower() in output_text.lower():
                        found_errors.append(pattern)

                startup_success = success and len(found_errors) == 0

                self.log_test(
                    "App Startup Execution",
                    startup_success,
                    f"App exited with code {process.returncode}" +
                    (f", errors found: {', '.join(found_errors)}" if found_errors else ", no critical errors"),
                    {
                        "exit_code": process.returncode,
                        "stdout_length": len(stdout),
                        "stderr_length": len(stderr),
                        "errors_found": found_errors,
                        "stdout_preview": stdout[:200] + "..." if len(stdout) > 200 else stdout,
                        "stderr_preview": stderr[:200] + "..." if len(stderr) > 200 else stderr
                    }
                )

                return startup_success

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

                self.log_test("App Startup", False, "App startup timed out after 30 seconds")
                return False

        except Exception as e:
            self.log_test("App Startup", False, f"Failed to start app: {e}")
            return False

    def test_dependencies_in_bundle(self) -> bool:
        """Test that Python dependencies are bundled"""
        print("\n📦 Testing Python Dependencies...")

        python_site_paths = [
            "Contents/Resources/python_site",
            "Contents/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages"
        ]

        dependencies_found = False

        for rel_path in python_site_paths:
            full_path = self.app_path / rel_path

            if full_path.exists() and full_path.is_dir():
                dependencies_found = True

                # Check for key Marcut dependencies
                key_packages = ["docx", "requests", "lxml", "pydantic", "tqdm"]
                package_status = {}

                for package in key_packages:
                    # Look for package directory or .dist-info
                    package_found = any(
                        (full_path / item).exists()
                        for item in os.listdir(full_path)
                        if item.startswith(package)
                    )
                    package_status[package] = package_found

                all_packages_found = all(package_status.values())

                self.log_test(
                    f"Python Dependencies: {rel_path}",
                    all_packages_found,
                    f"Dependencies bundle: {len([p for p in package_status.values() if p])}/{len(key_packages)} packages found",
                    {
                        "path": str(full_path),
                        "packages": package_status
                    }
                )

                return all_packages_found

        if not dependencies_found:
            self.log_test("Python Dependencies", False, "No Python dependencies bundle found")

        return False

    def run_all_tests(self) -> Dict:
        """Run all app bundle tests"""
        print(f"🧪 Testing Marcut App Bundle: {self.app_path}")
        print(f"Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # Run all test categories
        tests = [
            ("App Bundle Structure", self.test_app_bundle_structure),
            ("Info.plist Configuration", self.test_info_plist),
            ("Python Framework", self.test_python_framework),
            ("Ollama Binary", self.test_ollama_binary),
            ("App Startup", self.test_app_startup),
            ("Python Dependencies", self.test_dependencies_in_bundle)
        ]

        results = {}
        overall_success = True

        for test_name, test_func in tests:
            try:
                result = test_func()
                results[test_name] = result
                if not result:
                    overall_success = False
            except Exception as e:
                self.log_test(test_name, False, f"Test execution error: {e}")
                results[test_name] = False
                overall_success = False

        # Generate summary
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        passed_tests = sum(1 for result in results.values() if result)
        total_tests = len(results)

        print("\n" + "=" * 60)
        print("📊 APP BUNDLE TEST SUMMARY")
        print("=" * 60)

        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status:12} {test_name}")

        print(f"\nOverall: {'✅ PASSED' if overall_success else '❌ FAILED'}")
        print(f"Tests: {passed_tests}/{total_tests} passed")
        print(f"Duration: {duration:.1f} seconds")

        # Return comprehensive results
        return {
            "app_path": str(self.app_path),
            "timestamp": self.start_time.isoformat(),
            "duration_seconds": duration,
            "overall_success": overall_success,
            "tests_passed": passed_tests,
            "total_tests": total_tests,
            "test_results": results,
            "detailed_results": self.test_results
        }


def main():
    parser = argparse.ArgumentParser(description="Test Marcut macOS App Bundle")
    parser.add_argument(
        "--app-path",
        type=Path,
        help="Path to MarcutApp.app bundle (auto-detected if not provided)"
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Save test results to JSON file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    try:
        # Create tester and run tests
        tester = MacOSAppTester(args.app_path)
        results = tester.run_all_tests()

        # Save results if requested
        if args.output_file:
            with open(args.output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n📄 Results saved to: {args.output_file}")

        # Exit with appropriate code
        sys.exit(0 if results["overall_success"] else 1)

    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
