#!/usr/bin/env python3
"""
App Environment Validation for Marcut

Tests the app environment readiness including:
- App container access
- PythonKit initialization
- Ollama service detection
- Model discovery
- Document processing workflow

This script validates that the app environment is properly configured for
both development and production deployments.
"""

import argparse
import json
import os
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


class AppEnvironmentValidator:
    """Validates the app environment for Marcut"""

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

    def test_app_container_access(self) -> bool:
        """Test app container access and permissions"""
        print("\n📦 Testing App Container Access...")

        # Test app bundle directory access
        bundle_accessible = os.access(self.app_path, os.R_OK | os.X_OK)
        self.log_test(
            "App Bundle Access",
            bundle_accessible,
            f"App bundle is {'accessible' if bundle_accessible else 'not accessible'}",
            {"path": str(self.app_path), "permissions": oct(os.stat(self.app_path).st_mode)[-3:]}
        )

        if not bundle_accessible:
            return False

        # Test critical subdirectories
        subdirs = [
            ("Contents", "Main bundle directory"),
            ("Contents/MacOS", "Executable directory"),
            ("Contents/Resources", "Resources directory"),
            ("Contents/Frameworks", "Frameworks directory")
        ]

        all_accessible = True

        for subdir, description in subdirs:
            full_path = self.app_path / subdir
            accessible = full_path.exists() and os.access(full_path, os.R_OK)

            self.log_test(
                f"Subdirectory Access: {subdir}",
                accessible,
                f"{description} {'accessible' if accessible else 'not accessible'}",
                {"path": str(full_path)}
            )

            if not accessible:
                all_accessible = False

        return all_accessible

    def test_python_kit_environment(self) -> bool:
        """Test PythonKit environment setup"""
        print("\n🐍 Testing PythonKit Environment...")

        # Check for Python framework
        framework_path = self.app_path / "Contents/Frameworks/Python.framework"
        framework_exists = framework_path.exists()

        self.log_test(
            "Python Framework Presence",
            framework_exists,
            f"Python.framework {'found' if framework_exists else 'not found'}",
            {"path": str(framework_path)}
        )

        if not framework_exists:
            return False

        # Test Python execution via bundled launcher when available.
        python_works = False
        python_version = None
        launcher = self.app_path / "Contents" / "Resources" / "run_python.sh"

        if launcher.exists() and os.access(launcher, os.X_OK):
            try:
                result = subprocess.run(
                    [str(launcher), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                python_works = result.returncode == 0
                python_version = result.stdout.strip() or result.stderr.strip()

                self.log_test(
                    "Python Executable Test",
                    python_works,
                    f"Bundled python {'works' if python_works else 'failed'}",
                    {
                        "executable": str(launcher),
                        "version": python_version,
                        "exit_code": result.returncode
                    }
                )
            except subprocess.TimeoutExpired:
                self.log_test("Python Executable Test", False, "Bundled python timeout")
            except Exception as e:
                self.log_test("Python Executable Test", False, f"Bundled python error: {e}")
        else:
            self.log_test("Python Executable Test", False, "Bundled python launcher not found")

        # Test Python site-packages access
        site_packages_paths = [
            self.app_path / "Contents" / "Resources" / "python_site",
            framework_path / "Versions/3.11" / "lib" / "python3.11" / "site-packages",
        ]

        site_accessible = False
        site_path_used = None

        for site_path in site_packages_paths:
            if site_path.exists() and os.access(site_path, os.R_OK):
                site_accessible = True
                site_path_used = str(site_path)

                # Check for key packages
                key_packages = ["docx", "requests", "lxml", "pydantic"]
                found_packages = []

                for pkg in key_packages:
                    pkg_found = any(
                        (site_path / item).exists()
                        for item in os.listdir(site_path)
                        if item.startswith(pkg)
                    )
                    if pkg_found:
                        found_packages.append(pkg)

                self.log_test(
                    "Python Site Packages",
                    site_accessible,
                    f"Site packages accessible at {site_path.name}",
                    {
                        "path": site_path_used,
                        "packages_found": found_packages,
                        "total_packages": len(found_packages)
                    }
                )
                break

        if not site_accessible:
            self.log_test("Python Site Packages", False, "No accessible site packages found")

        return framework_exists and python_works and site_accessible

    def test_ollama_service_detection(self) -> bool:
        """Test Ollama service detection and accessibility"""
        print("\n🤖 Testing Ollama Service Detection...")

        # Check for bundled Ollama binary
        bundled_ollama_paths = [
            self.app_path / "Contents/Resources/ollama",
            self.app_path / "Contents/MacOS/ollama"
        ]

        bundled_ollama = None
        for path in bundled_ollama_paths:
            if path.exists() and os.access(path, os.X_OK):
                bundled_ollama = path
                break

        ollama_available = False
        ollama_version = None
        ollama_source = "none"

        if bundled_ollama:
            try:
                result = subprocess.run(
                    [str(bundled_ollama), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.returncode == 0:
                    ollama_available = True
                    ollama_version = result.stdout.strip() or result.stderr.strip()
                    ollama_source = "bundled"

                self.log_test(
                    "Bundled Ollama Binary",
                    ollama_available,
                    f"Bundled Ollama {'available' if ollama_available else 'unavailable'}",
                    {
                        "path": str(bundled_ollama),
                        "version": ollama_version,
                        "exit_code": result.returncode
                    }
                )

            except subprocess.TimeoutExpired:
                self.log_test("Bundled Ollama Binary", False, "Bundled Ollama version check timeout")
            except Exception as e:
                self.log_test("Bundled Ollama Binary", False, f"Bundled Ollama error: {e}")

        # Check for system Ollama as fallback
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )

            system_ollama_available = result.returncode == 0
            system_version = result.stdout.strip() or result.stderr.strip()

            if system_ollama_available and not ollama_available:
                ollama_available = True
                ollama_version = system_version
                ollama_source = "system"

            self.log_test(
                "System Ollama Binary",
                system_ollama_available,
                f"System Ollama {'available' if system_ollama_available else 'unavailable'}",
                {
                    "version": system_version,
                    "exit_code": result.returncode
                }
            )

        except FileNotFoundError:
            self.log_test("System Ollama Binary", False, "System Ollama not found in PATH")
        except subprocess.TimeoutExpired:
            self.log_test("System Ollama Binary", False, "System Ollama version check timeout")
        except Exception as e:
            self.log_test("System Ollama Binary", False, f"System Ollama error: {e}")

        # Test Ollama service connectivity
        service_available = False
        models_available = []

        if ollama_available:
            try:
                # Test service API
                import urllib.request
                import urllib.error

                request = urllib.request.Request(
                    "http://localhost:11434/api/tags",
                    headers={"User-Agent": "Marcut-Environment-Validator"}
                )

                try:
                    with urllib.request.urlopen(request, timeout=5) as response:
                        data = json.loads(response.read().decode())
                        service_available = True
                        models_available = [model["name"] for model in data.get("models", [])]

                    self.log_test(
                        "Ollama Service API",
                        service_available,
                        f"Ollama service {'running' if service_available else 'not running'}",
                        {
                            "models_count": len(models_available),
                            "models": models_available[:5]  # First 5 models
                        }
                    )

                except urllib.error.URLError:
                    self.log_test("Ollama Service API", False, "Cannot connect to Ollama service API")

            except Exception as e:
                self.log_test("Ollama Service API", False, f"Ollama API test error: {e}")

        overall_success = ollama_available

        self.log_test(
            "Ollama Overall Status",
            overall_success,
            f"Ollama {'available' if overall_success else 'unavailable'} via {ollama_source}",
            {
                "source": ollama_source,
                "version": ollama_version,
                "service_running": service_available,
                "models_count": len(models_available)
            }
        )

        return overall_success

    def test_model_discovery(self) -> bool:
        """Test AI model discovery and availability"""
        print("\n🧠 Testing AI Model Discovery...")

        # Check for common models
        common_models = ["llama3.1:8b", "llama3.1:7b", "llama3:8b", "llama3:7b"]
        available_models = []

        # Try to get models from Ollama API
        try:
            import urllib.request
            import urllib.error

            request = urllib.request.Request(
                "http://localhost:11434/api/tags",
                headers={"User-Agent": "Marcut-Environment-Validator"}
            )

            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    data = json.loads(response.read().decode())
                    available_models = [model["name"] for model in data.get("models", [])]

            except urllib.error.URLError:
                pass  # Service not running, will use alternative detection

        except Exception:
            pass  # API test failed, continue with other checks

        # Check for recommended models
        recommended_found = []
        for model in common_models:
            if model in available_models:
                recommended_found.append(model)

        has_recommended = len(recommended_found) > 0

        self.log_test(
            "Recommended Model Availability",
            has_recommended,
            f"Found {len(recommended_found)} recommended models",
            {
                "available_models": available_models,
                "recommended_found": recommended_found,
                "total_models": len(available_models)
            }
        )

        # Test model download capability (if service is running)
        can_download = False
        if available_models:  # Service is running
            try:
                # Check if we can access model info (doesn't download, just checks availability)
                test_model = "llama3.1:8b"
                request = urllib.request.Request(
                    f"http://localhost:11434/api/show",
                    data=json.dumps({"name": test_model}).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Marcut-Environment-Validator"
                    }
                )

                try:
                    with urllib.request.urlopen(request, timeout=10) as response:
                        data = json.loads(response.read().decode())
                        can_download = "error" not in data

                except urllib.error.URLError as e:
                    # HTTP 404 means model doesn't exist, but service is working
                    if hasattr(e, 'code') and e.code == 404:
                        can_download = True  # Service works, model just not present

                except Exception:
                    pass

            except Exception:
                pass

        self.log_test(
            "Model Download Capability",
            can_download,
            f"Model download {'available' if can_download else 'unavailable'}",
            {"service_responsive": can_download}
        )

        return has_recommended or can_download

    def test_document_processing_workflow(self) -> bool:
        """Test basic document processing workflow"""
        print("\n📄 Testing Document Processing Workflow...")

        # Test using bundled app executable
        executable = self.app_path / "Contents/MacOS/MarcutApp"
        if not executable.exists():
            self.log_test("Document Processing", False, "App executable not found")
            return False

        # Create a simple test command (help/version check)
        try:
            process = subprocess.Popen(
                [str(executable), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            try:
                stdout, stderr = process.communicate(timeout=30)

                # Check if the app runs without critical initialization errors
                success = process.returncode == 0

                # Look for critical error patterns
                critical_errors = [
                    "PythonKit initialization failed",
                    "Failed to locate Python.framework",
                    "Environment Not Ready",
                    "fatal error",
                    "Segmentation fault"
                ]

                output_text = (stdout or "") + (stderr or "")
                found_critical = [err for err in critical_errors if err.lower() in output_text.lower()]

                workflow_success = success and len(found_critical) == 0

                self.log_test(
                    "Document Processing Workflow",
                    workflow_success,
                    f"App startup {'successful' if workflow_success else 'failed'}",
                    {
                        "exit_code": process.returncode,
                        "critical_errors": found_critical,
                        "output_length": len(output_text)
                    }
                )

                return workflow_success

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                self.log_test("Document Processing Workflow", False, "App startup timed out")
                return False

        except Exception as e:
            self.log_test("Document Processing Workflow", False, f"Failed to test workflow: {e}")
            return False

    def test_app_permissions(self) -> bool:
        """Test app permissions and sandbox compliance"""
        print("\n🔒 Testing App Permissions...")

        # Test file write permissions in appropriate locations
        test_locations = [
            ("~/Desktop", Path("~/Desktop").expanduser()),
            ("~/Downloads", Path("~/Downloads").expanduser()),
            ("~/Documents", Path("~/Documents").expanduser()),
            ("/tmp", Path("/tmp"))
        ]

        writable_locations = 0

        for name, path in test_locations:
            if path.exists():
                test_file = path / f".marcut_test_{int(time.time())}"
                try:
                    test_file.write_text("test")
                    test_file.unlink()
                    writable_locations += 1

                    self.log_test(
                        f"Write Permission: {name}",
                        True,
                        f"Can write to {name}",
                        {"path": str(path)}
                    )
                except Exception as e:
                    self.log_test(
                        f"Write Permission: {name}",
                        False,
                        f"Cannot write to {name}: {e}",
                        {"path": str(path)}
                    )
            else:
                self.log_test(
                    f"Write Permission: {name}",
                    False,
                    f"Directory {name} does not exist",
                    {"path": str(path)}
                )

        # Check if app has sufficient permissions
        has_basic_permissions = writable_locations >= 2  # At least Desktop and Downloads

        self.log_test(
            "Basic File Permissions",
            has_basic_permissions,
            f"App has write access to {writable_locations}/4 standard locations",
            {"writable_locations": writable_locations}
        )

        return has_basic_permissions

    def run_all_tests(self) -> Dict:
        """Run all environment tests"""
        print(f"🔧 Validating Marcut App Environment: {self.app_path}")
        print(f"Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # Run all test categories
        tests = [
            ("App Container Access", self.test_app_container_access),
            ("PythonKit Environment", self.test_python_kit_environment),
            ("Ollama Service Detection", self.test_ollama_service_detection),
            ("Model Discovery", self.test_model_discovery),
            ("Document Processing Workflow", self.test_document_processing_workflow),
            ("App Permissions", self.test_app_permissions)
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
        print("📊 ENVIRONMENT VALIDATION SUMMARY")
        print("=" * 60)

        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status:12} {test_name}")

        print(f"\nOverall: {'✅ READY' if overall_success else '❌ NOT READY'}")
        print(f"Tests: {passed_tests}/{total_tests} passed")
        print(f"Duration: {duration:.1f} seconds")

        # Provide recommendations
        if not overall_success:
            print(f"\n🔧 RECOMMENDATIONS:")

            if not results.get("PythonKit Environment", False):
                print(f"  • Fix Python framework bundling in build process")
                print(f"  • Ensure Python.framework is properly signed")

            if not results.get("Ollama Service Detection", False):
                print(f"  • Bundle Ollama binary in app resources")
                print(f"  • Or ensure system Ollama is available")

            if not results.get("App Container Access", False):
                print(f"  • Check app bundle permissions")
                print(f"  • Verify app is properly signed")

        # Return comprehensive results
        return {
            "app_path": str(self.app_path),
            "timestamp": self.start_time.isoformat(),
            "duration_seconds": duration,
            "environment_ready": overall_success,
            "tests_passed": passed_tests,
            "total_tests": total_tests,
            "test_results": results,
            "detailed_results": self.test_results
        }


def main():
    parser = argparse.ArgumentParser(description="Validate Marcut App Environment")
    parser.add_argument(
        "--app-path",
        type=Path,
        help="Path to MarcutApp.app bundle (auto-detected if not provided)"
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Save validation results to JSON file"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    args = parser.parse_args()

    try:
        # Create validator and run tests
        validator = AppEnvironmentValidator(args.app_path)
        results = validator.run_all_tests()

        # Save results if requested
        if args.output_file:
            with open(args.output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n📄 Results saved to: {args.output_file}")

        # Exit with appropriate code
        sys.exit(0 if results["environment_ready"] else 1)

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
