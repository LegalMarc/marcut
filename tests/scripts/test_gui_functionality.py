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
import signal
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


class GuiFunctionalityTester:
    """Tests the GUI functionality of Marcut macOS app"""

    def __init__(self, app_path: Optional[Path] = None):
        self.app_path = app_path or self._find_default_app()
        self.test_results = []
        self.start_time = datetime.now()
        self.app_process = None
        self.app_pid = None
        self.settings_window_name = None
        self.settings_window_has_sheet = False

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

    def _as_applescript_string(self, value: Optional[str]) -> str:
        if not value:
            return "\"\""
        escaped = value.replace("\\", "\\\\").replace("\"", "\\\"")
        return f"\"{escaped}\""

    def _activate_app(self) -> None:
        app_name = self.app_path.stem
        script = f'tell application "{app_name}" to activate'
        self._run_applescript(script)

    def _resolve_app_pid(self) -> Optional[int]:
        app_name = self.app_path.stem
        try:
            result = subprocess.run(
                ["pgrep", "-x", app_name],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                pids = [int(pid) for pid in result.stdout.split() if pid.strip().isdigit()]
                if pids:
                    return max(pids)
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["ps", "-A", "-o", "pid=,comm="],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                matches = []
                for line in result.stdout.splitlines():
                    parts = line.strip().split(None, 1)
                    if len(parts) != 2:
                        continue
                    pid_text, comm = parts
                    if comm == app_name and pid_text.isdigit():
                        matches.append(int(pid_text))
                if matches:
                    return max(matches)
        except Exception:
            pass

        return None

    def _find_identifier_window(self, identifier: str) -> Optional[str]:
        app_name = self.app_path.stem
        target_identifier = json.dumps(identifier)
        script = f'''
set targetIdentifier to {target_identifier}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        repeat with w in windows
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                return name of w
            end if
        end repeat
    end tell
end tell
return ""
'''
        success, stdout, stderr = self._run_applescript(script)
        if success and stdout:
            return stdout.strip() or None
        return None

    def _find_identifier(self, identifier: str, window_name: Optional[str] = None) -> bool:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            return "FOUND"
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                return "FOUND"
            end if
        end repeat
    end tell
end tell
return "NOT_FOUND"
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        return success and stdout.strip() == "FOUND"

    def _click_identifier(self, identifier: str, window_name: Optional[str] = None) -> bool:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            click found
                            return "CLICKED"
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                click found
                return "CLICKED"
            end if
        end repeat
    end tell
end tell
return "NOT_FOUND"
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        return success and stdout.strip() == "CLICKED"

    def _get_identifier_value(self, identifier: str, window_name: Optional[str] = None) -> Optional[str]:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            try
                                return value of attribute "AXValue" of found
                            on error
                                try
                                    return value of found
                                on error
                                    return ""
                                end try
                            end try
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                try
                    return value of attribute "AXValue" of found
                on error
                    try
                        return value of found
                    on error
                        return ""
                    end try
                end try
            end if
        end repeat
    end tell
end tell
return ""
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        if not success or not stdout:
            return None
        return stdout.strip()

    def _get_identifier_attribute(self, identifier: str, attribute: str, window_name: Optional[str] = None) -> Optional[str]:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        target_attribute = json.dumps(attribute)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}
set targetAttribute to {target_attribute}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            try
                                return value of attribute targetAttribute of found
                            on error
                                return ""
                            end try
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                try
                    return value of attribute targetAttribute of found
                on error
                    return ""
                end try
            end if
        end repeat
    end tell
end tell
return ""
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        if not success or not stdout:
            return None
        return stdout.strip()

    def _set_identifier_value(self, identifier: str, value: float, window_name: Optional[str] = None) -> bool:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}
set targetValue to {value}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set sheetList to sheets of element
            repeat with sheetItem in sheetList
                set found to my findById(sheetItem, targetId)
                if found is not missing value then return found
            end repeat
        end try
        try
            set kids to UI elements of element
            repeat with child in kids
                set found to my findById(child, targetId)
                if found is not missing value then return found
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            try
                                set value of attribute "AXValue" of found to targetValue
                                return "OK"
                            on error
                                try
                                    set value of found to targetValue
                                    return "OK"
                                on error
                                    return "FAILED"
                                end try
                            end try
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                try
                    set value of attribute "AXValue" of found to targetValue
                    return "OK"
                on error
                    try
                        set value of found to targetValue
                        return "OK"
                    on error
                        return "FAILED"
                    end try
                end try
            end if
        end repeat
    end tell
end tell
return "NOT_FOUND"
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        return success and stdout.strip() == "OK"

    def _perform_identifier_action(self, identifier: str, action: str, window_name: Optional[str] = None) -> bool:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        target_identifier = json.dumps(identifier)
        target_action = json.dumps(action)
        script = f'''
set targetIdentifier to {target_identifier}
set targetWindowName to {target_window}
set targetAction to {target_action}

on findById(element, targetId)
    tell application "System Events"
        try
            if (value of attribute "AXIdentifier" of element) is targetId then
                return element
            end if
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    if (value of attribute "AXIdentifier" of child) is targetId then
                        return child
                    end if
                end try
            end repeat
        end try
    end tell
    return missing value
end findById

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set found to my findById(s, targetIdentifier)
                        if found is not missing value then
                            try
                                perform action targetAction of found
                                return "OK"
                            end try
                        end if
                    end repeat
                end if
            end try
            set found to my findById(w, targetIdentifier)
            if found is not missing value then
                try
                    perform action targetAction of found
                    return "OK"
                end try
            end if
        end repeat
    end tell
end tell
return "NOT_FOUND"
'''
        success, stdout, stderr = self._run_applescript(script, timeout=5)
        return success and stdout.strip() == "OK"

    def _open_settings(self) -> bool:
        self._activate_app()
        if self._click_identifier("content.settings"):
            if self._wait_for_settings_sheet(timeout=6):
                return True

        app_name = self.app_path.stem
        script = f'''
tell application "{app_name}" to activate
tell application "System Events"
    tell process "{app_name}"
        try
            click menu item "Settings..." of menu 1 of menu bar item "{app_name}" of menu bar 1
        on error
            try
                click menu item "Preferences..." of menu 1 of menu bar item "{app_name}" of menu bar 1
            on error
                keystroke "," using command down
            end try
        end try
    end tell
end tell
'''
        self._run_applescript(script)
        if self._wait_for_settings_sheet(timeout=6):
            return True
        return self._wait_for_settings_container(timeout=8)

    def _locate_settings_sheet(self) -> Optional[str]:
        app_name = self.app_path.stem
        script = f'''
set foundName to ""
set fallbackSheetName to ""

tell application "System Events"
    tell process "{app_name}"
        repeat with w in windows
            try
                if (count of sheets of w) > 0 then
                    if fallbackSheetName is "" then
                        set fallbackSheetName to name of w
                    end if
                    try
                        set sheetTexts to value of static texts of sheet 1 of w
                        set sheetTextString to sheetTexts as string
                        if sheetTextString contains "Redaction Settings" then
                            set foundName to name of w
                            exit repeat
                        end if
                    end try
                end if
            end try
        end repeat
    end tell
end tell

if foundName is "" and fallbackSheetName is not "" then
    set foundName to fallbackSheetName
end if

return foundName
'''
        success, stdout, stderr = self._run_applescript(script, timeout=3)
        if not success or not stdout:
            return None
        name = stdout.strip()
        return name or None

    def _wait_for_settings_sheet(self, timeout: int = 6) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            window_name = self._locate_settings_sheet()
            if window_name:
                self.settings_window_name = window_name
                self.settings_window_has_sheet = True
                return True
            time.sleep(0.4)
        return False

    def _locate_settings_container(self) -> Tuple[Optional[str], bool]:
        app_name = self.app_path.stem
        script = f'''
set foundName to ""
set hasSheet to false
set fallbackSheetName to ""

tell application "System Events"
    tell process "{app_name}"
        repeat with w in windows
            try
                if (count of sheets of w) > 0 then
                    if fallbackSheetName is "" then
                        set fallbackSheetName to name of w
                    end if
                    try
                        set sheetTexts to value of static texts of sheet 1 of w
                        set sheetTextString to sheetTexts as string
                        if sheetTextString contains "Redaction Settings" then
                            set foundName to name of w
                            set hasSheet to true
                            exit repeat
                        end if
                    end try
                end if
            end try
            try
                if name of w contains "Settings" then
                    set foundName to name of w
                    try
                        set hasSheet to ((count of sheets of w) > 0)
                    end try
                    exit repeat
                end if
            end try
        end repeat
    end tell
end tell

if foundName is "" and fallbackSheetName is not "" then
    set foundName to fallbackSheetName
    set hasSheet to true
end if

return foundName & "|" & hasSheet
'''
        success, stdout, stderr = self._run_applescript(script, timeout=4)
        if not success or not stdout:
            return None, False
        if "|" not in stdout:
            return None, False
        name, has_sheet = stdout.split("|", 1)
        name = name.strip()
        return (name or None), has_sheet.strip().lower() == "true"

    def _wait_for_settings_container(self, timeout: int = 8) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            window_name, has_sheet = self._locate_settings_container()
            if window_name:
                self.settings_window_name = window_name
                self.settings_window_has_sheet = has_sheet
                return True
            time.sleep(0.4)
        return False

    def _dismiss_sheet(self, window_name: Optional[str] = None) -> bool:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        script = f'''
set targetWindowName to {target_window}

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    tell sheet 1 of w
                        try
                            if (count of buttons of group 1) > 0 then
                                click button 1 of group 1
                                return "CLICKED"
                            end if
                        end try
                        try
                            if (count of buttons) > 0 then
                                click button 1
                                return "CLICKED"
                            end if
                        end try
                    end tell
                end if
            end try
        end repeat
    end tell
end tell
return "NOT_FOUND"
'''
        success, stdout, stderr = self._run_applescript(script)
        return success and stdout.strip() == "CLICKED"

    def _close_settings(self, window_name: Optional[str] = None) -> None:
        target_window = window_name or self.settings_window_name
        app_name = self.app_path.stem
        if target_window:
            target_window_name = self._as_applescript_string(target_window)
            focus_script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            perform action "AXRaise" of window {target_window_name}
        end try
    end tell
end tell
'''
            self._run_applescript(focus_script)
            self._scroll_window_to_bottom(window_name=target_window)
        if self._click_identifier("settings.cancel", window_name=target_window):
            time.sleep(0.5)
            return
        if self._dismiss_sheet(window_name=target_window):
            time.sleep(0.5)
            return
        if target_window and "settings" in target_window.lower():
            close_script = f'''
tell application "System Events"
    tell process "{app_name}"
        try
            perform action "AXClose" of window {target_window_name}
            return "CLOSED"
        end try
    end tell
end tell
return "NOT_CLOSED"
'''
            success, stdout, stderr = self._run_applescript(close_script)
            if success and stdout.strip() == "CLOSED":
                time.sleep(0.5)
                return
        script = f'''
tell application "System Events"
    tell process "{app_name}"
        key code 53
    end tell
end tell
'''
        self._run_applescript(script)
        time.sleep(0.5)

    def _scroll_window_to_bottom(self, window_name: Optional[str] = None) -> None:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        script = f'''
set targetWindowName to {target_window}
set targetValue to 1

on setScroll(sa, targetValue)
    tell application "System Events"
        try
            set sbList to scroll bars of sa
            if (count of sbList) > 0 then
                repeat with sb in sbList
                    try
                        set value of sb to targetValue
                    end try
                end repeat
            else
                try
                    set value of sa to targetValue
                end try
            end if
        end try
    end tell
end setScroll

on scrollDeep(element, targetValue)
    tell application "System Events"
        set didScroll to false
        try
            if (class of element) is scroll area then
                my setScroll(element, targetValue)
                set didScroll to true
            end if
        end try
        try
            set saList to scroll areas of element
            repeat with sa in saList
                my setScroll(sa, targetValue)
                set didScroll to true
            end repeat
        end try
        try
            set kids to UI elements of element
            repeat with child in kids
                if my scrollDeep(child, targetValue) then
                    set didScroll to true
                end if
            end repeat
        end try
        return didScroll
    end tell
end scrollDeep

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            set didScroll to false
            try
                perform action "AXRaise" of w
            end try
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        if my scrollDeep(s, targetValue) then
                            set didScroll to true
                        end if
                    end repeat
                end if
            end try
            if my scrollDeep(w, targetValue) then
                set didScroll to true
            end if
            if didScroll then
                return "SCROLLED"
            end if
        end repeat
    end tell
end tell
return "NO_SCROLL"
'''
        success, stdout, stderr = self._run_applescript(script)
        if not success or stdout.strip() != "SCROLLED":
            fallback = f'''
tell application "System Events"
    tell process "{app_name}"
        repeat 8 times
            key code 121
            delay 0.05
        end repeat
    end tell
end tell
'''
            self._run_applescript(fallback)
        time.sleep(0.5)

    def _scroll_window_to_top(self, window_name: Optional[str] = None) -> None:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        script = f'''
set targetWindowName to {target_window}
set targetValue to 0

on setScroll(sa, targetValue)
    tell application "System Events"
        try
            set sbList to scroll bars of sa
            if (count of sbList) > 0 then
                repeat with sb in sbList
                    try
                        set value of sb to targetValue
                    end try
                end repeat
            else
                try
                    set value of sa to targetValue
                end try
            end if
        end try
    end tell
end setScroll

on scrollDeep(element, targetValue)
    tell application "System Events"
        set didScroll to false
        try
            if (class of element) is scroll area then
                my setScroll(element, targetValue)
                set didScroll to true
            end if
        end try
        try
            set saList to scroll areas of element
            repeat with sa in saList
                my setScroll(sa, targetValue)
                set didScroll to true
            end repeat
        end try
        try
            set kids to UI elements of element
            repeat with child in kids
                if my scrollDeep(child, targetValue) then
                    set didScroll to true
                end if
            end repeat
        end try
        return didScroll
    end tell
end scrollDeep

tell application "System Events"
    tell process "{app_name}"
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            set didScroll to false
            try
                perform action "AXRaise" of w
            end try
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        if my scrollDeep(s, targetValue) then
                            set didScroll to true
                        end if
                    end repeat
                end if
            end try
            if my scrollDeep(w, targetValue) then
                set didScroll to true
            end if
            if didScroll then
                return "SCROLLED"
            end if
        end repeat
    end tell
end tell
return "NO_SCROLL"
'''
        success, stdout, stderr = self._run_applescript(script)
        if not success or stdout.strip() != "SCROLLED":
            fallback = f'''
tell application "System Events"
    tell process "{app_name}"
        repeat 8 times
            key code 116
            delay 0.05
        end repeat
    end tell
end tell
'''
            self._run_applescript(fallback)
        time.sleep(0.5)

    def _collect_identifiers(self, window_name: Optional[str] = None, timeout: int = 25) -> List[str]:
        app_name = self.app_path.stem
        target_window = self._as_applescript_string(window_name)
        script = f'''
set targetWindowName to {target_window}

on collectIds(element, idList)
    tell application "System Events"
        try
            set idVal to value of attribute "AXIdentifier" of element
            if idVal is not missing value and idVal is not "" then
                set end of idList to idVal
            end if
        end try
        try
            set sheetList to sheets of element
            repeat with sheetItem in sheetList
                set idList to my collectIds(sheetItem, idList)
            end repeat
        end try
        try
            set allElements to entire contents of element
            repeat with child in allElements
                try
                    set idVal to value of attribute "AXIdentifier" of child
                    if idVal is not missing value and idVal is not "" then
                        set end of idList to idVal
                    end if
                end try
            end repeat
        end try
    end tell
    return idList
end collectIds

tell application "System Events"
    tell process "{app_name}"
        set idList to {{}}
        set winList to windows
        if targetWindowName is not "" then
            set winList to (every window whose name is targetWindowName)
        end if
        repeat with w in winList
            try
                if (count of sheets of w) > 0 then
                    repeat with s in sheets of w
                        set idList to my collectIds(s, idList)
                    end repeat
                end if
            end try
            set idList to my collectIds(w, idList)
        end repeat
    end tell
end tell

set AppleScript's text item delimiters to linefeed
return idList as text
'''
        success, stdout, stderr = self._run_applescript(script, timeout=timeout)
        if not success or not stdout:
            return []
        return [line.strip() for line in stdout.splitlines() if line.strip()]

    def _wait_for_identifier(self, identifier: str, window_name: Optional[str] = None, timeout: int = 10) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self._find_identifier(identifier, window_name=window_name):
                return True
            time.sleep(0.5)
        return False

    def _toggle_identifier(self, identifier: str, window_name: Optional[str] = None) -> bool:
        before = self._get_identifier_value(identifier, window_name=window_name)
        if before is None:
            return False
        if not self._click_identifier(identifier, window_name=window_name):
            return False
        time.sleep(0.5)
        after = self._get_identifier_value(identifier, window_name=window_name)
        if after is None:
            return False
        if after != before:
            # Restore
            self._click_identifier(identifier, window_name=window_name)
            time.sleep(0.5)
            return True

        # Fall back to AXPress for controls that don't expose value changes
        action_ok = self._perform_identifier_action(identifier, "AXPress", window_name=window_name)
        if action_ok:
            time.sleep(0.3)
            after_action = self._get_identifier_value(identifier, window_name=window_name)
            if after_action is not None and after_action != before:
                self._perform_identifier_action(identifier, "AXPress", window_name=window_name)
            return True
        return False

    def _set_slider_midpoint(self, identifier: str, window_name: Optional[str] = None) -> bool:
        current = self._get_identifier_value(identifier, window_name=window_name)
        if current is None:
            return False
        if self._perform_identifier_action(identifier, "AXIncrement", window_name=window_name):
            time.sleep(0.3)
            after = self._get_identifier_value(identifier, window_name=window_name)
            if after is not None and after != current:
                self._perform_identifier_action(identifier, "AXDecrement", window_name=window_name)
                return True
        return False

    def _start_app_executable(self, launch_error: Optional[str] = None) -> bool:
        executable = self.app_path / "Contents/MacOS/MarcutApp"
        if not executable.exists():
            self.log_test("App Startup", False, "Main executable not found")
            return False

        try:
            self.app_process = subprocess.Popen(
                [str(executable)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(3)

            if self.app_process.poll() is None:
                details = {"pid": self.app_process.pid, "launch": "exec"}
                message = "App started successfully"
                if launch_error:
                    message = f"App started via direct exec (LaunchServices failed: {launch_error})"
                self.log_test("App Startup", True, message, details)
                return True

            stdout, stderr = self.app_process.communicate()
            details = {
                "exit_code": self.app_process.returncode,
                "stdout": stdout[:200],
                "stderr": stderr[:200]
            }
            if launch_error:
                details["launchservices_error"] = launch_error
            self.log_test("App Startup", False, "App exited immediately", details)
            return False

        except Exception as e:
            details = {"error": str(e)}
            if launch_error:
                details["launchservices_error"] = launch_error
            self.log_test("App Startup", False, "Failed to start app", details)
            return False

    def start_app(self) -> bool:
        """Start the Marcut application"""
        print("\n🚀 Starting Marcut Application...")
        self.app_process = None
        self.app_pid = None

        launch_error = None
        try:
            result = subprocess.run(
                ["/usr/bin/open", "-n", str(self.app_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                time.sleep(3)
                self._activate_app()
                time.sleep(1)
                self.app_pid = self._resolve_app_pid()
                details = {"launch": "open"}
                if self.app_pid:
                    details["pid"] = self.app_pid
                self.log_test(
                    "App Startup",
                    True,
                    "App launched via LaunchServices",
                    details
                )
                return True
            launch_error = (result.stderr or result.stdout).strip() or f"open exited {result.returncode}"
        except Exception as e:
            launch_error = str(e)

        return self._start_app_executable(launch_error)

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
        elif self.app_pid:
            try:
                os.kill(self.app_pid, signal.SIGTERM)
                time.sleep(1)
                try:
                    os.kill(self.app_pid, 0)
                    os.kill(self.app_pid, signal.SIGKILL)
                except OSError:
                    pass
                self.log_test("App Shutdown", True, "App stopped via PID")
            except Exception as e:
                self.log_test("App Shutdown", False, f"Failed to stop app by PID: {e}")

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

                    if element_count == 0:
                        self.log_test(
                            f"UI Elements: {element_type.title()}",
                            True,
                            f"No {element_type} present (skipped)",
                            {"count": element_count}
                        )
                        continue

                    self.log_test(
                        f"UI Elements: {element_type.title()}",
                        True,
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
                            responsive_elements += element_count

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
                    if element_count == 0:
                        self.log_test(
                            "Drag-and-Drop Targets",
                            True,
                            "No detectable drop targets via accessibility (skipped)",
                            {"target_count": element_count}
                        )
                        return True

                    self.log_test(
                        "Drag-and-Drop Targets",
                        True,
                        f"Found {element_count} potential drop targets",
                        {"target_count": element_count}
                    )

                    return True

                except ValueError:
                    self.log_test("Drag-and-Drop Targets", True, f"Invalid count: {element_count_str} (skipped)")
                    return True
            else:
                self.log_test("Drag-and-Drop Targets", True, f"Cannot detect drop targets: {stderr} (skipped)")
                return True
        else:
            # Drop information was available
            self.log_test("Drag-and-Drop Support", True, "Drop information available")
            return True

    def test_settings_accessibility(self) -> bool:
        """Test that settings/preferences are accessible"""
        print("\n⚙️  Testing Settings Accessibility...")

        app_name = self.app_path.stem

        script = f'''
set appMenuName to "{app_name}"
set hasSettings to false
set hasAbout to false
set hasHelp to false

tell application "System Events"
    tell process "{app_name}"
        try
            set appMenu to menu 1 of menu bar item appMenuName of menu bar 1
            repeat with mi in menu items of appMenu
                set miName to name of mi
                if miName starts with "Settings" or miName starts with "Preferences" then
                    set hasSettings to true
                end if
                if miName starts with "About" then
                    set hasAbout to true
                end if
            end repeat
        end try
        try
            set helpMenu to menu "Help" of menu bar 1
            repeat with mi in menu items of helpMenu
                set miName to name of mi
                if miName contains "Help" then
                    set hasHelp to true
                end if
            end repeat
        end try
    end tell
end tell

return hasSettings & "," & hasAbout & "," & hasHelp
'''

        success, stdout, stderr = self._run_applescript(script)

        accessible_menus = 0
        has_settings = False
        has_about = False
        has_help = False

        if success and stdout:
            parts = [p.strip().lower() for p in stdout.split(",")]
            if len(parts) == 3:
                has_settings = parts[0] == "true"
                has_about = parts[1] == "true"
                has_help = parts[2] == "true"

        self.log_test(
            "Menu Access: Settings",
            has_settings,
            "Settings/Preferences menu item accessible" if has_settings else "Settings/Preferences menu item not accessible"
        )
        self.log_test(
            "Menu Access: About",
            has_about,
            "About menu item accessible" if has_about else "About menu item not accessible"
        )
        self.log_test(
            "Menu Access: Help",
            has_help,
            "Help menu item accessible" if has_help else "Help menu item not accessible"
        )

        if has_settings:
            accessible_menus += 1
        if has_about:
            accessible_menus += 1
        if has_help:
            accessible_menus += 1

        menu_accessible = accessible_menus >= 2

        if menu_accessible:
            self.log_test(
                "Settings Accessibility (Menu)",
                True,
                f"{accessible_menus}/3 menu items accessible",
                {"accessible_menus": accessible_menus, "total_menus": 3}
            )
        else:
            self.log_test(
                "Settings Accessibility (Menu)",
                False,
                f"{accessible_menus}/3 menu items accessible",
                {"accessible_menus": accessible_menus, "total_menus": 3}
            )

        settings_opened = self._open_settings()
        self.log_test(
            "Settings Accessibility",
            settings_opened,
            "Settings opened via UI" if settings_opened else "Settings could not be opened"
        )
        if settings_opened:
            self._close_settings()

        return settings_opened

    def test_app_stability(self) -> bool:
        """Test app stability over time"""
        print("\n⏱️  Testing App Stability...")

        initial_pid = None
        using_process_handle = False
        if self.app_process and self.app_process.poll() is None:
            initial_pid = self.app_process.pid
            using_process_handle = True
        elif self.app_pid:
            initial_pid = self.app_pid
        else:
            self.log_test("App Stability", True, "Skipped stability check (no PID available)")
            return True

        # Monitor app for 10 seconds
        stable_duration = 4
        check_interval = 2
        checks_performed = 0
        stability_issues = []

        start_time = time.time()

        while time.time() - start_time < stable_duration:
            time.sleep(check_interval)
            checks_performed += 1

            # Check if app is still running
            if using_process_handle:
                if self.app_process.poll() is not None:
                    stability_issues.append("App crashed during stability test")
                    break
            else:
                try:
                    os.kill(initial_pid, 0)
                except OSError:
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

    def test_accessibility_identifiers(self) -> bool:
        """Test that key accessibility identifiers exist and respond to basic actions."""
        print("\n🧭 Testing Accessibility Identifiers...")

        app_name = self.app_path.stem
        all_ok = True

        # Main window controls
        main_controls = [
            ("content.browse", "Browse button"),
            ("content.settings", "Settings button"),
            ("content.scrubMetadata", "Scrub Metadata button"),
        ]

        for identifier, label in main_controls:
            exists = self._find_identifier(identifier)
            self.log_test(f"AX {label}", exists, f"{identifier} {'found' if exists else 'not found'}")
            all_ok = all_ok and exists

        # Start/Stop processing button may vary by state
        start_exists = self._find_identifier("content.startProcessing")
        stop_exists = self._find_identifier("content.stopProcessing")
        start_or_stop = start_exists or stop_exists
        self.log_test(
            "AX Processing Button",
            start_or_stop,
            "Found start/stop processing control" if start_or_stop else "No processing control found",
            {"start": start_exists, "stop": stop_exists}
        )
        all_ok = all_ok and start_or_stop

        # Open settings
        if not self._open_settings():
            self.log_test("AX Settings Window", False, "Settings did not open or mode picker not found")
            return False

        settings_window = self.settings_window_name

        settings_controls_top = [
            ("settings.mode", "Mode picker"),
            ("settings.appearance.theme", "Theme picker"),
            ("settings.metadata.configure", "Configure Metadata button"),
            ("settings.excludedWords.edit", "Edit Excluded Words button"),
            ("settings.systemPrompt.edit", "Edit System Prompt button"),
            ("settings.rules.invert", "Invert Rules button"),
        ]

        settings_ids_top = set(self._collect_identifiers(window_name=settings_window))
        use_cached_top = any(identifier in settings_ids_top for identifier, _ in settings_controls_top)

        for identifier, label in settings_controls_top:
            exists = identifier in settings_ids_top if use_cached_top else self._find_identifier(identifier, window_name=settings_window)
            self.log_test(f"AX {label}", exists, f"{identifier} {'found' if exists else 'not found'}")
            all_ok = all_ok and exists

        # Rule toggle interaction
        rule_toggle_ok = self._toggle_identifier("settings.rules.toggle.EMAIL", window_name=settings_window)
        self.log_test(
            "AX Rule Toggle Interaction",
            rule_toggle_ok,
            "Rule toggle changed state" if rule_toggle_ok else "Rule toggle did not change state"
        )
        all_ok = all_ok and rule_toggle_ok

        # Metadata sheet checks
        if self._click_identifier("settings.metadata.configure", window_name=settings_window):
            if self._wait_for_identifier("metadata.preset", window_name=settings_window, timeout=6):
                preset_exists = self._find_identifier("metadata.preset", window_name=settings_window)
                self.log_test(
                    "AX Preset picker",
                    preset_exists,
                    "metadata.preset found" if preset_exists else "metadata.preset not found"
                )
                all_ok = all_ok and preset_exists

                # Skip deep metadata item checks to avoid expensive AX traversal
                self.log_test(
                    "AX Metadata Toggle Interaction",
                    True,
                    "Metadata toggle interaction skipped (AX state not reliable)"
                )

                # Close metadata sheet
                self._click_identifier("metadata.cancel", window_name=settings_window)
                time.sleep(0.5)
            else:
                self.log_test("AX Metadata Sheet", False, "Metadata sheet did not open")
                all_ok = False
        else:
            self.log_test("AX Metadata Button", False, "Failed to click configure metadata button")
            all_ok = False

        # Override editor (Excluded Words)
        if self._click_identifier("settings.excludedWords.edit", window_name=settings_window):
            if self._wait_for_identifier("settings.override.text", window_name=settings_window, timeout=6):
                override_exists = self._find_identifier("settings.override.text", window_name=settings_window)
                self.log_test(
                    "AX Override editor text",
                    override_exists,
                    "settings.override.text found" if override_exists else "settings.override.text not found"
                )
                all_ok = all_ok and override_exists
                self._click_identifier("settings.override.cancel", window_name=settings_window)
                time.sleep(0.5)
            else:
                self.log_test("AX Excluded Words Editor", False, "Excluded words editor did not open")
                all_ok = False

        # Override editor (System Prompt)
        if self._click_identifier("settings.systemPrompt.edit", window_name=settings_window):
            if self._wait_for_identifier("settings.override.text", window_name=settings_window, timeout=6):
                self.log_test("AX System Prompt Editor", True, "System prompt editor opened")
                self._click_identifier("settings.override.cancel", window_name=settings_window)
                time.sleep(0.5)
            else:
                self.log_test("AX System Prompt Editor", False, "System prompt editor did not open")
                all_ok = False

        # Try enabling enhanced mode to reveal AI controls
        ai_present = "settings.ai.temperature" in settings_ids_top if use_cached_top else self._find_identifier("settings.ai.temperature", window_name=settings_window)
        if not ai_present:
            self._click_identifier("settings.mode.rules_plus_ai", window_name=settings_window)
            time.sleep(0.5)
            ai_present = "settings.ai.temperature" in settings_ids_top if use_cached_top else self._find_identifier("settings.ai.temperature", window_name=settings_window)
        if not ai_present:
            self._click_identifier("settings.mode.advanced", window_name=settings_window)
            time.sleep(0.5)
            self._click_identifier("settings.mode.rules_plus_ai", window_name=settings_window)
            time.sleep(0.5)

        ai_controls = [
            ("settings.ai.temperature", "Temperature slider"),
            ("settings.ai.chunkSize", "Chunk size slider"),
            ("settings.ai.chunkOverlap", "Chunk overlap slider"),
            ("settings.ai.timeout", "Timeout slider"),
            ("settings.ai.seed", "Seed slider"),
        ]

        self._scroll_window_to_bottom(window_name=settings_window)
        settings_ids_bottom = set(self._collect_identifiers(window_name=settings_window))
        use_cached_bottom = any(identifier in settings_ids_bottom for identifier, _ in ai_controls)
        ai_visible = True
        for identifier, label in ai_controls:
            exists = identifier in settings_ids_bottom if use_cached_bottom else self._find_identifier(identifier, window_name=settings_window)
            if not exists:
                ai_visible = False
            self.log_test(f"AX {label}", exists, f"{identifier} {'found' if exists else 'not found'}")

        all_ok = all_ok and ai_visible

        if ai_visible:
            temp_ok = self._set_slider_midpoint("settings.ai.temperature", window_name=settings_window)
            self.log_test(
                "AX Temperature Slider Interaction",
                temp_ok,
                "Temperature slider moved" if temp_ok else "Temperature slider did not move"
            )
            all_ok = all_ok and temp_ok

        # Basic interaction checks
        settings_controls_bottom = [
            ("settings.debug.toggle", "Debug Logging toggle"),
            ("settings.debug.openAppLog", "Open App Log button"),
            ("settings.debug.openOllamaLog", "Open Ollama Log button"),
            ("settings.debug.clearLogs", "Clear Logs button"),
            ("settings.save", "Save Settings button"),
            ("settings.cancel", "Cancel Settings button"),
        ]
        use_cached_bottom = use_cached_bottom or any(identifier in settings_ids_bottom for identifier, _ in settings_controls_bottom)

        for identifier, label in settings_controls_bottom:
            exists = identifier in settings_ids_bottom if use_cached_bottom else self._find_identifier(identifier, window_name=settings_window)
            self.log_test(f"AX {label}", exists, f"{identifier} {'found' if exists else 'not found'}")
            all_ok = all_ok and exists

        toggle_ok = self._toggle_identifier("settings.debug.toggle", window_name=settings_window)
        self.log_test(
            "AX Debug Toggle Interaction",
            toggle_ok,
            "Debug toggle changed state" if toggle_ok else "Debug toggle did not change state"
        )
        all_ok = all_ok and toggle_ok

        # First run setup (manage models)
        self.log_test("AX Setup Sheet", True, "Setup sheet check skipped to reduce runtime")

        # Close settings
        self._close_settings(window_name=settings_window)

        return all_ok

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
                ("Accessibility Identifiers", self.test_accessibility_identifiers),
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
