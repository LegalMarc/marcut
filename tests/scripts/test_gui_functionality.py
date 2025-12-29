#!/usr/bin/env python3
"""
GUI Functionality Testing for Marcut

Tests the macOS app GUI functionality including:
- GUI state verification using AppleScript
- "Environment Not Ready" state detection
- Drag-and-drop functionality
- UI element responsiveness
- Settings and configuration

This script validates that the GUI components work correctly and can
detect the issues that command-line testing would miss.
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


class GuiFunctionalityTester:
    """Tests the GUI functionality of Marcut macOS app"""

    def __init__(self, app_path: Optional[Path] = None):
        self.app_path = app_path or self._find_default_app()
        self.test_results = []
        self.start_time = datetime.now()
        self.app_process = None

    def _find_default_app(self) -> Path:
        """Find the default Marcut.app bundle"""
        possible_paths = [
            Path("build_swift/MarcutApp.app"),
            Path("/Applications/MarcutApp.app"),
            Path("~/Applications/MarcutApp.app").expanduser(),
            Path("MarcutApp/build/MarcutApp.app"),
            Path("MarcutApp/.build/release/MarcutApp.app")
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

    def _run_applescript(self, script: str, timeout: int = 10) -> Tuple[bool, str, str]:
        """Run an AppleScript and return success, stdout, stderr"""
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "AppleScript execution timed out"
        except Exception as e:
            return False, "", f"AppleScript execution error: {e}"

    def start_app(self) -> bool:
        """Start the Marcut application"""
        print("\n🚀 Starting Marcut Application...")

        executable = self.app_path / "Contents/MacOS/MarcutApp"
        if not executable.exists():
            self.log_test("App Startup", False, "Main executable not found")
            return False

        try:
            # Start the app in background
            self.app_process = subprocess.Popen(
                [str(executable)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Wait a moment for the app to start
            time.sleep(3)

            # Check if process is still running
            if self.app_process.poll() is None:
                self.log_test(
                    "App Startup",
                    True,
                    "App started successfully",
                    {"pid": self.app_process.pid}
                )
                return True
            else:
                # App exited immediately
                stdout, stderr = self.app_process.communicate()
                self.log_test(
                    "App Startup",
                    False,
                    "App exited immediately",
                    {
                        "exit_code": self.app_process.returncode,
                        "stdout": stdout[:200],
                        "stderr": stderr[:200]
                    }
                )
                return False

        except Exception as e:
            self.log_test("App Startup", False, f"Failed to start app: {e}")
            return False

    def stop_app(self):
        """Stop the Marcut application"""
        if self.app_process and self.app_process.poll() is None:
            try:
                self.app_process.terminate()
                self.app_process.wait(timeout=10)
                self.log_test("App Shutdown", True, "App stopped successfully")
            except subprocess.TimeoutExpired:
                self.app_process.kill()
                self.app_process.wait()
                self.log_test("App Shutdown", True, "App force killed")
            except Exception as e:
                self.log_test("App Shutdown", False, f"Failed to stop app: {e}")

        # Also try using AppleScript to quit the app
        app_name = self.app_path.stem
        script = f'tell application "{app_name}" to quit'
        success, stdout, stderr = self._run_applescript(script, timeout=5)

    def test_app_window_presence(self) -> bool:
        """Test that the app window is present"""
        print("\n🪟 Testing App Window Presence...")

        app_name = self.app_path.stem

        # Check if app is running
        script = f'''
tell application "System Events"
    return (exists process "{app_name}")
end tell
'''

        success, stdout, stderr = self._run_applescript(script)

        if not success:
            self.log_test("App Process Detection", False, f"Cannot detect app process: {stderr}")
            return False

        app_running = stdout.lower() == "true"

        self.log_test(
            "App Process Detection",
            app_running,
            f"App process {'found' if app_running else 'not found'}",
            {"app_name": app_name}
        )

        if not app_running:
            return False

        # Check for window presence
        script = f'''
tell application "System Events"
    tell process "{app_name}"
        return (count of windows)
    end tell
end tell
'''

        success, stdout, stderr = self._run_applescript(script)

        if not success:
            self.log_test("Window Detection", False, f"Cannot detect windows: {stderr}")
            return False

        try:
            window_count = int(stdout)
            has_window = window_count > 0

            self.log_test(
                "Window Detection",
                has_window,
                f"Found {window_count} window(s)",
                {"window_count": window_count}
            )

            return has_window

        except ValueError:
            self.log_test("Window Detection", False, f"Invalid window count: {stdout}")
            return False

    def test_environment_ready_state(self) -> bool:
        """Test for 'Environment Not Ready' state"""
        print("\n⚠️  Testing Environment Ready State...")

        app_name = self.app_path.stem

        # Look for error dialogs or warning messages
        script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            -- Look for sheets (dialogs)
            set sheetCount to count of sheets of window 1
            return sheetCount
        on error
            return 0
        end try
    end tell
end tell
'''

        success, stdout, stderr = self._run_applescript(script)

        if success:
            try:
                sheet_count = int(stdout)
                has_sheets = sheet_count > 0

                self.log_test(
                    "Dialog Detection",
                    has_sheets,
                    f"Found {sheet_count} dialog(s)",
                    {"sheet_count": sheet_count}
                )

                if has_sheets:
                    # Try to get dialog text
                    script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set sheetText to value of static text of sheet 1 of window 1
            return sheetText
        on error
            return "Unable to read dialog text"
        end try
    end tell
end tell
'''

                    success, dialog_text, stderr = self._run_applescript(script)

                    if success and dialog_text:
                        # Check for environment-related errors
                        env_errors = [
                            "environment not ready",
                            "pythonkit initialization",
                            "ollama service",
                            "framework not found"
                        ]

                        found_env_errors = [
                            error for error in env_errors
                            if error.lower() in dialog_text.lower()
                        ]

                        env_issues_detected = len(found_env_errors) > 0

                        self.log_test(
                            "Environment Error Detection",
                            env_issues_detected,
                            f"Found {len(found_env_errors)} environment-related errors" if env_issues_detected else "No environment errors detected",
                            {
                                "dialog_text": dialog_text[:200],
                                "found_errors": found_env_errors
                            }
                        )

                        # Return False if environment issues are detected
                        return not env_issues_detected

            except ValueError:
                pass  # Continue with other checks

        # Check window title for status indicators
        script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set windowTitle to title of window 1
            return windowTitle
        on error
            return "No title"
        end try
    end tell
end tell
'''

        success, window_title, stderr = self._run_applescript(script)

        if success and window_title:
            # Check for error indicators in title
            title_issues = [
                "not ready",
                "error",
                "failed",
                "warning"
            ]

            title_issues_found = [
                issue for issue in title_issues
                if issue.lower() in window_title.lower()
            ]

            title_has_issues = len(title_issues_found) > 0

            self.log_test(
                "Window Title Check",
                not title_has_issues,
                f"Window title: {window_title[:50]}" if not title_has_issues else f"Issues in title: {title_issues_found}",
                {
                    "window_title": window_title,
                    "issues_found": title_issues_found
                }
            )

            if title_has_issues:
                return False

        # Assume environment is ready if no issues detected
        self.log_test("Environment Ready State", True, "No environment issues detected")
        return True

    def test_ui_element_responsiveness(self) -> bool:
        """Test that UI elements are responsive"""
        print("\n🖱️  Testing UI Element Responsiveness...")

        app_name = self.app_path.stem

        # Look for common UI elements
        ui_elements = [
            ("buttons", "buttons"),
            ("text fields", "text fields"),
            ("menus", "menus"),
            ("pop up buttons", "pop up buttons")
        ]

        responsive_elements = 0
        total_elements_found = 0

        for element_type, applescript_name in ui_elements:
            script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set elementCount to count of {applescript_name} of window 1
            return elementCount
        on error
            return 0
        end try
    end tell
end tell
'''

            success, stdout, stderr = self._run_applescript(script)

            if success:
                try:
                    element_count = int(stdout)
                    total_elements_found += element_count

                    self.log_test(
                        f"UI Elements: {element_type.title()}",
                        element_count > 0,
                        f"Found {element_count} {element_type}",
                        {"count": element_count}
                    )

                    # Test element responsiveness (can we interact with them?)
                    if element_count > 0:
                        # Try to get properties of first element to test responsiveness
                        script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set firstElement to {applescript_name} 1 of window 1
            set elementEnabled to enabled of firstElement
            set elementVisible to visible of firstElement
            return (elementEnabled and elementVisible)
        on error
            return false
        end try
    end tell
end tell
'''

                        success, is_responsive, stderr = self._run_applescript(script)

                        if success and is_responsive:
                            responsive_elements += 1

                except ValueError:
                    self.log_test(f"UI Elements: {element_type.title()}", False, f"Invalid count: {stdout}")

        # Calculate responsiveness ratio
        if total_elements_found > 0:
            responsiveness_ratio = responsive_elements / total_elements_found
            ui_responsive = responsiveness_ratio >= 0.5  # At least 50% of elements responsive

            self.log_test(
                "UI Responsiveness",
                ui_responsive,
                f"{responsive_elements}/{total_elements_found} elements responsive ({responsiveness_ratio:.1%})",
                {
                    "responsive_elements": responsive_elements,
                    "total_elements": total_elements_found,
                    "responsiveness_ratio": responsiveness_ratio
                }
            )

            return ui_responsive
        else:
            self.log_test("UI Responsiveness", False, "No UI elements found")
            return False

    def test_drag_drop_functionality(self) -> bool:
        """Test drag-and-drop capability (basic check)"""
        print("\n📁 Testing Drag-and-Drop Functionality...")

        app_name = self.app_path.stem

        # Check if the main window accepts drag and drop
        script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set mainWindow to window 1
            -- Try to get drop information (this tests if drop is supported)
            set dropInfo to drop information of mainWindow
            return true
        on error
            return false
        end try
    end tell
end tell
'''

        success, stdout, stderr = self._run_applescript(script)

        # Drop information test might not work, try alternative approach
        if not success:
            # Check for text areas that typically accept drag and drop
            script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set textAreas to count of text areas of window 1
            set textFields to count of text fields of window 1
            return (textAreas + textFields)
        on error
            return 0
        end try
    end tell
end tell
'''

            success, element_count_str, stderr = self._run_applescript(script)

            if success:
                try:
                    element_count = int(element_count_str)
                    has_drop_targets = element_count > 0

                    self.log_test(
                        "Drag-and-Drop Targets",
                        has_drop_targets,
                        f"Found {element_count} potential drop targets",
                        {"target_count": element_count}
                    )

                    return has_drop_targets

                except ValueError:
                    self.log_test("Drag-and-Drop Targets", False, f"Invalid count: {element_count_str}")
                    return False
            else:
                self.log_test("Drag-and-Drop Targets", False, f"Cannot detect drop targets: {stderr}")
                return False
        else:
            # Drop information was available
            self.log_test("Drag-and-Drop Support", True, "Drop information available")
            return True

    def test_settings_accessibility(self) -> bool:
        """Test that settings/preferences are accessible"""
        print("\n⚙️  Testing Settings Accessibility...")

        app_name = self.app_path.stem

        # Look for menu items related to settings
        menu_items = [
            ("Preferences", "Preferences"),
            ("Settings", "Settings"),
            ("Help", "Help"),
            ("About", "About")
        ]

        accessible_menus = 0

        for menu_name, display_name in menu_items:
            script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            set menuExists to exists menu item "{menu_name}" of menu "File" of menu bar 1
            if not menuExists then
                set menuExists to exists menu item "{menu_name}" of menu "Edit" of menu bar 1
            end if
            if not menuExists then
                set menuExists to exists menu item "{menu_name}" of menu "View" of menu bar 1
            end if
            if not menuExists then
                set menuExists to exists menu item "{menu_name}" of menu "Window" of menu bar 1
            end if
            if not menuExists then
                set menuExists to exists menu item "{menu_name}" of menu "Help" of menu bar 1
            end if
            return menuExists
        on error
            return false
        end try
    end tell
end tell
'''

            success, stdout, stderr = self._run_applescript(script)

            if success:
                menu_accessible = stdout.lower() == "true"

                if menu_accessible:
                    accessible_menus += 1

                self.log_test(
                    f"Menu Access: {display_name}",
                    menu_accessible,
                    f"Menu item {'accessible' if menu_accessible else 'not accessible'}",
                    {"menu_name": menu_name}
                )

            else:
                self.log_test(f"Menu Access: {display_name}", False, f"Menu check failed: {stderr}")

        settings_accessible = accessible_menus >= 2  # At least 2 menu items accessible

        self.log_test(
            "Settings Accessibility",
            settings_accessible,
            f"{accessible_menus}/{len(menu_items)} menu items accessible",
            {"accessible_menus": accessible_menus, "total_menus": len(menu_items)}
        )

        return settings_accessible

    def test_app_stability(self) -> bool:
        """Test app stability over time"""
        print("\n⏱️  Testing App Stability...")

        if not self.app_process or self.app_process.poll() is not None:
            self.log_test("App Stability", False, "App not running for stability test")
            return False

        initial_pid = self.app_process.pid

        # Monitor app for 10 seconds
        stable_duration = 10
        check_interval = 2
        checks_performed = 0
        stability_issues = []

        start_time = time.time()

        while time.time() - start_time < stable_duration:
            time.sleep(check_interval)
            checks_performed += 1

            # Check if app is still running
            if self.app_process.poll() is not None:
                stability_issues.append("App crashed during stability test")
                break

            # Check for excessive CPU usage (simplified)
            try:
                result = subprocess.run(
                    ["ps", "-p", str(initial_pid), "-o", "%cpu="],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    try:
                        cpu_usage = float(result.stdout.strip())
                        if cpu_usage > 80:  # More than 80% CPU
                            stability_issues.append(f"High CPU usage: {cpu_usage:.1f}%")
                    except ValueError:
                        pass  # Invalid CPU reading

            except Exception:
                pass  # CPU check failed, but continue stability test

        app_stable = len(stability_issues) == 0

        self.log_test(
            "App Stability",
            app_stable,
            f"App stable for {stable_duration} seconds" if app_stable else f"Stability issues: {stability_issues}",
            {
                "checks_performed": checks_performed,
                "stability_issues": stability_issues,
                "test_duration": stable_duration
            }
        )

        return app_stable

    def run_all_tests(self) -> Dict:
        """Run all GUI functionality tests"""
        print(f"🖥️  Testing Marcut GUI Functionality: {self.app_path}")
        print(f"Started at: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        # Start the app for GUI testing
        app_started = self.start_app()

        if not app_started:
            # Cannot proceed with GUI tests if app won't start
            end_time = datetime.now()
            duration = (end_time - self.start_time).total_seconds()

            return {
                "app_path": str(self.app_path),
                "timestamp": self.start_time.isoformat(),
                "duration_seconds": duration,
                "gui_functional": False,
                "tests_passed": 0,
                "total_tests": 0,
                "test_results": {"App Startup": False},
                "detailed_results": self.test_results,
                "error": "App failed to start - GUI tests aborted"
            }

        try:
            # Run all test categories
            tests = [
                ("App Window Presence", self.test_app_window_presence),
                ("Environment Ready State", self.test_environment_ready_state),
                ("UI Element Responsiveness", self.test_ui_element_responsiveness),
                ("Drag-and-Drop Functionality", self.test_drag_drop_functionality),
                ("Settings Accessibility", self.test_settings_accessibility),
                ("App Stability", self.test_app_stability)
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

        finally:
            # Always try to stop the app
            self.stop_app()

        # Generate summary
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()

        passed_tests = sum(1 for result in results.values() if result)
        total_tests = len(results)

        print("\n" + "=" * 60)
        print("📊 GUI FUNCTIONALITY TEST SUMMARY")
        print("=" * 60)

        for test_name, result in results.items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status:12} {test_name}")

        print(f"\nOverall: {'✅ FUNCTIONAL' if overall_success else '❌ NOT FUNCTIONAL'}")
        print(f"Tests: {passed_tests}/{total_tests} passed")
        print(f"Duration: {duration:.1f} seconds")

        # Return comprehensive results
        return {
            "app_path": str(self.app_path),
            "timestamp": self.start_time.isoformat(),
            "duration_seconds": duration,
            "gui_functional": overall_success,
            "tests_passed": passed_tests,
            "total_tests": total_tests,
            "test_results": results,
            "detailed_results": self.test_results
        }


def main():
    parser = argparse.ArgumentParser(description="Test Marcut GUI Functionality")
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
        tester = GuiFunctionalityTester(args.app_path)
        results = tester.run_all_tests()

        # Save results if requested
        if args.output_file:
            with open(args.output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n📄 Results saved to: {args.output_file}")

        # Exit with appropriate code
        sys.exit(0 if results["gui_functional"] else 1)

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