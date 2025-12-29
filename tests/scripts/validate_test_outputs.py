#!/usr/bin/env python3
"""
Validate Test Outputs

Validates the integrity and quality of test outputs from the Marcut test suite.

Usage:
    python3 scripts/validate_test_outputs.py --test-dir ~/Downloads/MarcutTestSuite
"""

import argparse
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import zipfile
import xml.etree.ElementTree as ET


class TestOutputValidator:
    """Validates test outputs for quality and integrity"""

    def __init__(self, test_dir: Path):
        self.test_dir = test_dir.expanduser()
        self.issues = []
        self.validations = []

    def validate_docx_file(self, docx_path: Path) -> Dict:
        """Validate a DOCX file for integrity and track changes"""
        validation = {
            "file": docx_path.name,
            "valid": True,
            "issues": [],
            "track_changes_found": False,
            "redactions_found": False
        }

        try:
            # Check if file exists and is not empty
            if not docx_path.exists():
                validation["valid"] = False
                validation["issues"].append("File does not exist")
                return validation

            if docx_path.stat().st_size == 0:
                validation["valid"] = False
                validation["issues"].append("File is empty")
                return validation

            # Check DOCX structure by examining the ZIP file
            try:
                with zipfile.ZipFile(docx_path, 'r') as docx_zip:
                    # Check for required files
                    required_files = ['[Content_Types].xml', 'word/document.xml']
                    for req_file in required_files:
                        if req_file not in docx_zip.namelist():
                            validation["issues"].append(f"Missing required file: {req_file}")

                    # Check document.xml for track changes
                    try:
                        with docx_zip.open('word/document.xml') as doc_xml:
                            content = doc_xml.read().decode('utf-8')

                            # Look for track changes markers
                            track_changes_indicators = [
                                '<w:ins',  # Insertions
                                '<w:del',  # Deletions
                                '<w:moveFrom',  # Move from
                                '<w:moveTo',    # Move to
                                'w:ins',  # Alternative namespace
                                'w:del',  # Alternative namespace
                            ]

                            for indicator in track_changes_indicators:
                                if indicator in content:
                                    validation["track_changes_found"] = True
                                    break

                            # Look for redaction placeholders
                            redaction_patterns = [
                                '[NAME_',
                                '[ORG_',
                                '[EMAIL_',
                                '[PHONE_',
                                '[DATE_',
                                '[MONEY_',
                                '[CREDIT_CARD_',
                                '[URL_'
                            ]

                            for pattern in redaction_patterns:
                                if pattern in content:
                                    validation["redactions_found"] = True
                                    break

                    except Exception as e:
                        validation["issues"].append(f"Error reading document.xml: {e}")

            except zipfile.BadZipFile:
                validation["valid"] = False
                validation["issues"].append("Invalid DOCX file (corrupted or not a ZIP file)")

        except Exception as e:
            validation["valid"] = False
            validation["issues"].append(f"Unexpected error: {e}")

        return validation

    def validate_json_report(self, json_path: Path) -> Dict:
        """Validate a JSON report for structure and content"""
        validation = {
            "file": json_path.name,
            "valid": True,
            "issues": [],
            "spans_count": 0,
            "has_metadata": False,
            "has_entities": False
        }

        try:
            # Check if file exists and is not empty
            if not json_path.exists():
                validation["valid"] = False
                validation["issues"].append("File does not exist")
                return validation

            if json_path.stat().st_size == 0:
                validation["valid"] = False
                validation["issues"].append("File is empty")
                return validation

            # Parse JSON
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Check required fields
                required_fields = ['spans', 'created_at']
                for field in required_fields:
                    if field not in data:
                        validation["issues"].append(f"Missing required field: {field}")

                # Check spans
                if 'spans' in data:
                    validation["spans_count"] = len(data['spans'])
                    if validation["spans_count"] > 0:
                        validation["has_entities"] = True

                    # Validate span structure
                    for i, span in enumerate(data['spans'][:5]):  # Check first 5 spans
                        required_span_fields = ['start', 'end', 'label', 'entity_id']
                        for field in required_span_fields:
                            if field not in span:
                                validation["issues"].append(f"Span {i}: Missing field '{field}'")

                        # Check for reasonable values
                        if 'start' in span and 'end' in span:
                            if not isinstance(span['start'], int) or not isinstance(span['end'], int):
                                validation["issues"].append(f"Span {i}: start/end must be integers")
                            elif span['start'] >= span['end']:
                                validation["issues"].append(f"Span {i}: start must be less than end")

                # Check metadata
                metadata_fields = ['created_at', 'input_sha256', 'model']
                for field in metadata_fields:
                    if field in data and data[field]:
                        validation["has_metadata"] = True
                        break

            except json.JSONDecodeError as e:
                validation["valid"] = False
                validation["issues"].append(f"Invalid JSON: {e}")

        except Exception as e:
            validation["valid"] = False
            validation["issues"].append(f"Unexpected error: {e}")

        return validation

    def validate_app_bundle(self, app_path: Optional[Path] = None) -> Dict:
        """Validate macOS app bundle structure and components"""
        validation = {
            "app_found": False,
            "valid": True,
            "issues": [],
            "components": {
                "executable": False,
                "info_plist": False,
                "python_framework": False,
                "ollama_binary": False,
                "python_dependencies": False
            }
        }

        # Find app bundle if not specified
        if not app_path:
            possible_paths = [
                Path("build_swift/MarcutApp.app"),
                Path("/Applications/MarcutApp.app"),
                Path("~/Applications/MarcutApp.app").expanduser(),
                Path("MarcutApp/build/MarcutApp.app"),
                Path("MarcutApp/.build/release/MarcutApp.app")
            ]

            for path in possible_paths:
                if path.exists() and path.is_dir() and path.suffix == ".app":
                    app_path = path
                    break

        if not app_path or not app_path.exists():
            validation["valid"] = False
            validation["issues"].append("MarcutApp.app bundle not found")
            return validation

        validation["app_found"] = True
        app_path_str = str(app_path)

        # Check executable
        executable = app_path / "Contents/MacOS/MarcutApp"
        if executable.exists() and os.access(executable, os.X_OK):
            validation["components"]["executable"] = True
        else:
            validation["issues"].append("Main executable not found or not executable")

        # Check Info.plist
        info_plist = app_path / "Contents/Info.plist"
        if info_plist.exists():
            try:
                with open(info_plist, 'rb') as f:
                    plist_data = plistlib.load(f)
                    required_keys = ["CFBundleIdentifier", "CFBundleName", "CFBundleExecutable"]
                    missing_keys = [key for key in required_keys if key not in plist_data]

                    if not missing_keys:
                        validation["components"]["info_plist"] = True
                    else:
                        validation["issues"].append(f"Info.plist missing keys: {missing_keys}")
            except Exception as e:
                validation["issues"].append(f"Cannot read Info.plist: {e}")
        else:
            validation["issues"].append("Info.plist not found")

        # Check Python framework
        framework_paths = [
            "Contents/Frameworks/Python.framework",
            "Contents/Frameworks/Python.framework/Versions/3.11",
            "Contents/Frameworks/Python.framework/Versions/3.11/Python"
        ]

        framework_found = True
        for rel_path in framework_paths:
            if not (app_path / rel_path).exists():
                framework_found = False
                break

        if framework_found:
            validation["components"]["python_framework"] = True

            # Test Python executable
            python_exec = app_path / "Contents/Frameworks/Python.framework/Versions/3.11/Python"
            if python_exec.exists():
                try:
                    result = subprocess.run(
                        [str(python_exec), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        validation["components"]["python_dependencies"] = True
                    else:
                        validation["issues"].append(f"Python executable test failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    validation["issues"].append("Python executable timeout")
                except Exception as e:
                    validation["issues"].append(f"Python executable error: {e}")
            else:
                validation["issues"].append("Python executable not found in framework")
        else:
            validation["issues"].append("Python.framework not found or incomplete")

        # Check Ollama binary
        ollama_paths = ["Contents/Resources/ollama", "Contents/MacOS/ollama"]
        ollama_found = False

        for rel_path in ollama_paths:
            ollama_binary = app_path / rel_path
            if ollama_binary.exists() and os.access(ollama_binary, os.X_OK):
                ollama_found = True
                validation["components"]["ollama_binary"] = True

                # Test Ollama version
                try:
                    result = subprocess.run(
                        [str(ollama_binary), "--version"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode != 0:
                        validation["issues"].append(f"Ollama version check failed: {result.stderr}")
                except subprocess.TimeoutExpired:
                    validation["issues"].append("Ollama version check timeout")
                except Exception as e:
                    validation["issues"].append(f"Ollama version check error: {e}")
                break

        if not ollama_found:
            validation["issues"].append("Ollama binary not found")

        # Check for Python dependencies bundle
        python_site_paths = [
            "Contents/Resources/python_site",
            "Contents/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages"
        ]

        deps_found = False
        for rel_path in python_site_paths:
            deps_path = app_path / rel_path
            if deps_path.exists() and deps_path.is_dir():
                # Check for key packages
                key_packages = ["docx", "requests", "lxml"]
                packages_found = sum(1 for pkg in key_packages
                                  if any(item.startswith(pkg) for item in os.listdir(deps_path)))

                if packages_found >= 2:  # At least 2 key packages found
                    deps_found = True
                    validation["components"]["python_dependencies"] = True
                    break

        if not deps_found:
            validation["issues"].append("Python dependencies bundle not found or incomplete")

        # Overall validity
        critical_components = ["executable", "info_plist"]
        missing_critical = [comp for comp in critical_components if not validation["components"][comp]]

        if missing_critical:
            validation["valid"] = False
            validation["issues"].append(f"Missing critical components: {missing_critical}")

        return validation

    def validate_app_startup(self, app_path: Optional[Path] = None) -> Dict:
        """Test app startup and check for critical errors"""
        validation = {
            "startup_tested": False,
            "startup_success": False,
            "exit_code": None,
            "errors_found": [],
            "output_captured": False
        }

        # Find app if not specified
        if not app_path:
            possible_paths = [
                Path("build_swift/MarcutApp.app"),
                Path("/Applications/MarcutApp.app"),
                Path("~/Applications/MarcutApp.app").expanduser(),
                Path("MarcutApp/build/MarcutApp.app"),
                Path("MarcutApp/.build/release/MarcutApp.app")
            ]

            for path in possible_paths:
                if path.exists() and path.is_dir() and path.suffix == ".app":
                    app_path = path
                    break

        if not app_path or not app_path.exists():
            validation["errors_found"].append("App bundle not found for startup test")
            return validation

        executable = app_path / "Contents/MacOS/MarcutApp"
        if not executable.exists():
            validation["errors_found"].append("Executable not found for startup test")
            return validation

        try:
            # Start app with --help flag to test startup
            process = subprocess.Popen(
                [str(executable), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            try:
                stdout, stderr = process.communicate(timeout=30)
                validation["exit_code"] = process.returncode
                validation["startup_tested"] = True
                validation["output_captured"] = True

                # Check for critical error patterns
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

                output_text = (stdout or "") + (stderr or "")

                for pattern in error_patterns:
                    if pattern.lower() in output_text.lower():
                        validation["errors_found"].append(f"Critical error detected: {pattern}")

                # Determine success
                validation["startup_success"] = (
                    process.returncode == 0 and len(validation["errors_found"]) == 0
                )

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                validation["errors_found"].append("App startup timed out after 30 seconds")

        except Exception as e:
            validation["errors_found"].append(f"Failed to start app: {e}")

        return validation

    def find_test_files(self) -> List[Tuple[Path, Path]]:
        """Find pairs of DOCX and JSON files generated by tests"""
        docx_files = list(self.test_dir.glob("*.docx"))
        json_files = list(self.test_dir.glob("*.json"))

        # Filter out test results files
        docx_files = [f for f in docx_files if not f.name.startswith("test_results_")]
        json_files = [f for f in json_files if not f.name.startswith("test_results_") and not f.name.startswith("human_review_")]

        # Pair files by timestamp and pathway
        file_pairs = []
        for docx_file in docx_files:
            # Extract base name (pathway and timestamp)
            base_name = docx_file.stem
            json_file = self.test_dir / f"{base_name}.json"

            if json_file in json_files:
                file_pairs.append((docx_file, json_file))
            else:
                self.issues.append(f"No matching JSON file for {docx_file.name}")

        return file_pairs

    def validate_test_results(self, include_app_bundle: bool = True) -> Dict:
        """Validate all test outputs and generate a comprehensive report"""
        print(f"🔍 Validating test outputs in: {self.test_dir}")
        print("=" * 60)

        # Validate file outputs
        file_pairs = self.find_test_files()
        print(f"📁 Found {len(file_pairs)} test output pairs")

        # Validate each pair
        results = []
        for docx_path, json_path in file_pairs:
            print(f"\n📋 Validating: {docx_path.name}")

            # Validate DOCX
            docx_validation = self.validate_docx_file(docx_path)

            # Validate JSON
            json_validation = self.validate_json_report(json_path)

            # Combine results
            pair_result = {
                "base_name": docx_path.stem,
                "docx": docx_validation,
                "json": json_validation,
                "overall_valid": docx_validation["valid"] and json_validation["valid"]
            }

            results.append(pair_result)

            # Print summary
            status = "✅" if pair_result["overall_valid"] else "❌"
            entities = json_validation["spans_count"]
            track_changes = "📝" if docx_validation["track_changes_found"] else "⚠️ "
            print(f"   {status} {entities} entities, {track_changes} track changes")

            if not pair_result["overall_valid"]:
                all_issues = docx_validation["issues"] + json_validation["issues"]
                for issue in all_issues:
                    print(f"      • {issue}")

        # Validate app bundle if requested
        app_bundle_validation = None
        app_startup_validation = None

        if include_app_bundle:
            print(f"\n🍎 Validating macOS App Bundle...")
            app_bundle_validation = self.validate_app_bundle()

            if app_bundle_validation["app_found"]:
                # Print app bundle validation results
                bundle_status = "✅" if app_bundle_validation["valid"] else "❌"
                print(f"   {bundle_status} App bundle found")

                for component, status in app_bundle_validation["components"].items():
                    comp_status = "✅" if status else "❌"
                    comp_name = component.replace("_", " ").title()
                    print(f"      {comp_status} {comp_name}")

                if app_bundle_validation["issues"]:
                    for issue in app_bundle_validation["issues"]:
                        print(f"      • {issue}")

                # Test app startup if bundle is valid
                if app_bundle_validation["valid"]:
                    print(f"\n🚀 Testing App Startup...")
                    app_startup_validation = self.validate_app_startup()

                    startup_status = "✅" if app_startup_validation["startup_success"] else "❌"
                    startup_label = "Startup Test" if app_startup_validation["startup_tested"] else "Startup Test (Not Tested)"
                    print(f"   {startup_status} {startup_label}")

                    if app_startup_validation["errors_found"]:
                        for error in app_startup_validation["errors_found"]:
                            print(f"      • {error}")
            else:
                print(f"   ⚠️  App bundle not found - skipping app validation")

        # Generate summary
        total_pairs = len(results)
        valid_pairs = sum(1 for r in results if r["overall_valid"])
        invalid_pairs = total_pairs - valid_pairs

        summary = {
            "total_files": total_pairs,
            "valid_files": valid_pairs,
            "invalid_files": invalid_pairs,
            "overall_success_rate": (valid_pairs / total_pairs * 100) if total_pairs > 0 else 0,
            "results": results,
            "additional_issues": self.issues,
            "app_bundle_validation": app_bundle_validation,
            "app_startup_validation": app_startup_validation
        }

        # Calculate overall success including app validation
        file_success = invalid_pairs == 0
        app_success = (
            not include_app_bundle or
            (app_bundle_validation and app_bundle_validation["valid"] and
             (not app_startup_validation or app_startup_validation["startup_success"]))
        )

        summary["overall_success"] = file_success and app_success

        print(f"\n" + "=" * 60)
        print(f"📊 COMPREHENSIVE VALIDATION SUMMARY")
        print(f"=" * 60)
        print(f"📁 Test file pairs: {valid_pairs}/{total_pairs} valid")
        if include_app_bundle:
            if app_bundle_validation:
                bundle_status = "✅" if app_bundle_validation["valid"] else "❌"
                startup_status = "✅" if (not app_startup_validation or app_startup_validation["startup_success"]) else "❌"
                print(f"🍎 App bundle: {bundle_status} valid")
                print(f"🚀 App startup: {startup_status} successful")
            else:
                print(f"🍎 App bundle: ⚠️  not found")

        overall_status = "✅ PASSED" if summary["overall_success"] else "❌ FAILED"
        print(f"🎯 Overall: {overall_status}")

        if self.issues:
            print(f"\n⚠️  Additional issues:")
            for issue in self.issues:
                print(f"   • {issue}")

        return summary

    def save_validation_report(self, summary: Dict) -> Path:
        """Save validation report to file"""
        report_data = {
            "validation_timestamp": datetime.now().isoformat(),
            "test_directory": str(self.test_dir),
            "summary": {
                "total_files": summary["total_files"],
                "valid_files": summary["valid_files"],
                "invalid_files": summary["invalid_files"],
                "success_rate": summary["overall_success_rate"]
            },
            "results": summary["results"],
            "additional_issues": summary["additional_issues"]
        }

        report_filename = f"validation_report_{datetime.now().strftime('%y-%m-%d_%H-%M-%S')}.json"
        report_path = self.test_dir / report_filename

        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2)

        print(f"\n📋 Validation report saved: {report_path}")
        return report_path


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Validate Marcut test outputs"
    )

    parser.add_argument(
        "--test-dir", "-t",
        default="~/Downloads/MarcutTestSuite",
        help="Directory containing test outputs (default: ~/Downloads/MarcutTestSuite)"
    )

    parser.add_argument(
        "--no-app-bundle",
        action="store_true",
        help="Skip app bundle validation (only validate CLI outputs)"
    )

    parser.add_argument(
        "--app-path",
        type=Path,
        help="Specific path to MarcutApp.app bundle (auto-detected if not provided)"
    )

    args = parser.parse_args()

    # Create validator and run validation
    validator = TestOutputValidator(Path(args.test_dir))
    include_app_bundle = not args.no_app_bundle

    # Override app path if specified
    if args.app_path:
        validator.app_path = args.app_path

    summary = validator.validate_test_results(include_app_bundle=include_app_bundle)

    # Save report
    validator.save_validation_report(summary)

    # Determine success criteria
    file_issues = summary["invalid_files"] > 0
    app_issues = False

    if include_app_bundle and summary.get("app_bundle_validation"):
        app_bundle_valid = summary["app_bundle_validation"]["valid"]
        app_startup_success = (
            not summary.get("app_startup_validation") or
            summary["app_startup_validation"]["startup_success"]
        )
        app_issues = not (app_bundle_valid and app_startup_success)

    # Return appropriate exit code
    if file_issues or app_issues:
        error_messages = []
        if file_issues:
            error_messages.append(f"{summary['invalid_files']} files had validation issues")
        if app_issues:
            error_messages.append("App bundle validation failed")

        print(f"\n⚠️  Validation issues found:")
        for msg in error_messages:
            print(f"   • {msg}")
        return 1

    print(f"\n✅ All validations passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())