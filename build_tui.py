#!/usr/bin/env python3
"""
Interactive TUI wrapper around scripts/sh/build_swift_only.sh using only the Python standard library.

The interface intentionally sticks to simple text prompts so it can run on the
system-provided /usr/bin/python3 without additional packages.
"""
from __future__ import annotations

# FORCE CACHE CLEAR AND SCRIPT VERIFICATION
import importlib
import sys

# Clear all build_tui related modules from cache
modules_to_remove = [mod for mod in list(sys.modules.keys()) if 'build_tui' in mod]
for mod in modules_to_remove:
    if mod in sys.modules:
        del sys.modules[mod]

# Verify we're running the correct script
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT_PATH = os.path.join(SCRIPT_DIR, "build_tui.py")

# Clear local __pycache__ directories (avoid recursive scans of large artifact trees)
import shutil
cache_dir = os.path.join(SCRIPT_DIR, "__pycache__")
if os.path.isdir(cache_dir):
    shutil.rmtree(cache_dir, ignore_errors=True)

# Clear local .pyc files only
for entry in os.listdir(SCRIPT_DIR):
    if entry.endswith(".pyc"):
        try:
            os.remove(os.path.join(SCRIPT_DIR, entry))
        except OSError:
            pass

if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
    print("MarcutApp Build Orchestrator (TUI)")
    print("Usage: ./build_tui.py")
    sys.exit(0)

print(f"✅ Running script from: {SCRIPT_PATH}")

import json
import plistlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# Basic ANSI colors for readability; fall back gracefully if disabled.
ENABLE_COLOR = os.environ.get("NO_COLOR") is None and os.isatty(1)


def colorize(text: str, code: str) -> str:
    if not ENABLE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def banner(text: str) -> None:
    line = "=" * len(text)
    print(colorize(line, "34"))
    print(colorize(text, "34"))
    print(colorize(line, "34"))

REPO_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = REPO_ROOT / "build-scripts" / "config.json"
if not CONFIG_PATH.exists():
    fallback = REPO_ROOT / "config.json"
    if fallback.exists():
        CONFIG_PATH = fallback
BUILD_SCRIPT = REPO_ROOT / "scripts" / "sh" / "build_swift_only.sh"
CONFIG: Dict[str, object] = {}

STEP_DEFINITIONS: List[Dict[str, object]] = [
    {
        "id": "cleanup",
        "label": "Step 1: Comprehensive Cleanup",
        "description": "Removes SwiftPM, Xcode, and Python caches plus previous build outputs.",
        "default": True,
    },
    {
        "id": "refresh_python",
        "label": "Step 2: Refresh Python Payload",
        "description": "Runs setup_beeware_framework.sh and copies python_site sources.",
        "default": True,
    },
    {
        "id": "build_swift",
        "label": "Step 3: Build Swift App",
        "description": "Compiles the Swift project (debug, arm64).",
        "default": True,
    },
    {
        "id": "verify_build",
        "label": "Step 4: Build Verification",
        "description": "Ensures diagnostic markers and binaries are present.",
        "default": True,
    },
    {
        "id": "assemble_bundle",
        "label": "Step 5: Create App Bundle & Embed Runtimes",
        "description": "Builds the .app structure, embeds Python, and copies resources.",
        "default": True,
    },
    {
        "id": "sign_components",
        "label": "Step 6: Sign App Components",
        "description": "Ad-hoc signs the helper binaries, frameworks, and bundle.",
        "default": True,
    },
    {
        "id": "testing_cleanup",
        "label": "Step 6.5: Reset App Data (Fresh-Install Simulation)",
        "description": "Clears app data, permissions, caches, and quarantine so the next launch behaves like a first-run.",
        "default": True,
    },
    {
        "id": "functional_verification",
        "label": "Step 7: Post-Build Functional Verification",
        "description": "Runs --help/--diagnose/CLI smoke tests.",
        "default": True,
    },
    {
        "id": "create_dmg",
        "label": "Step 8: Create Final DMG",
        "description": "Packages the signed .app into a distributable DMG file.",
        "default": False,
    },
]

PRESETS: Dict[str, Dict[str, object]] = {
    "dev_fast": {
        "label": "Dev Fast + Test Prep (reuse Python runtime)",
        "description": "Rebuild Swift + bundle with testing cleanup. Skips deep cleanup and BeeWare refresh for quick iteration.",
        "steps": [
            "build_swift",
            "assemble_bundle",
            "sign_components",
            "testing_cleanup",
        ],
    },
    "quick_debug": {
        "label": "Quick Debug Build",
        "description": "Fastest option for development. Skips deep cleaning and DMG creation.",
        "steps": [
            "refresh_python",
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "sign_components",
            "functional_verification",
        ],
    },
    "full_release": {
        "label": "Full Release Build (Clean & Archive)",
        "description": "Performs a deep clean, rebuilds everything, and creates the DMG.",
        "steps": [
            "cleanup",
            "refresh_python",
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "sign_components",
            "functional_verification",
            "create_dmg",
        ],
    },
    "diagnostics": {
        "label": "Run Diagnostics & Verification",
        "description": "Skips rebuild and only runs verification/tests on the existing bundle.",
        "steps": [
            "verify_build",
            "functional_verification",
        ],
    },
    "fast_incremental": {
        "label": "Incremental Build + Test Prep",
        "description": "Skip BeeWare refresh and rebuild only Swift + bundle with testing cleanup.",
        "steps": [
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "sign_components",
            "testing_cleanup",
        ],
    },
    "clean": {
        "label": "Clean All Build Artifacts",
        "description": "Runs the comprehensive cleanup only.",
        "steps": [
            "cleanup",
        ],
    },
}


class StepError(Exception):
    """Raised when a build step fails."""


def load_config() -> Dict[str, object]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Config file not found: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _parse_numeric_parts(value: object) -> Optional[List[int]]:
    text = str(value or "").strip()
    if not text:
        return None
    if not all(part.isdigit() for part in text.split(".")):
        return None
    return [int(part) for part in text.split(".")]


def predict_appstore_build_number(config: Dict[str, object]) -> Optional[str]:
    build_parts = _parse_numeric_parts(config.get("build_number"))
    if build_parts:
        if len(build_parts) > 3:
            build_parts = build_parts[:3]
        build_parts[-1] += 1
        return ".".join(str(part) for part in build_parts)

    version_parts = _parse_numeric_parts(config.get("version"))
    if version_parts:
        if len(version_parts) > 3:
            version_parts = version_parts[:3]
        return ".".join(str(part) for part in version_parts)

    return None


def script_from_config(key: str) -> Path:
    value = CONFIG.get(key)
    if not value:
        raise StepError(f"Config missing '{key}' entry.")
    path = (CONFIG_PATH.parent / value).resolve()
    if not path.exists():
        raise StepError(f"Script not found: {path}")
    return path


def resolve_config_path(value: object, default: Optional[Path] = None) -> Path:
    if value in (None, ""):
        if default is None:
            return Path()
        return default.resolve()
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (CONFIG_PATH.parent / path).resolve()


def submit_appstore_script() -> Path:
    candidates = [
        REPO_ROOT / "submit_appstore.sh",
        REPO_ROOT / "build-scripts" / "submit_appstore.sh",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise StepError("submit_appstore.sh not found in repo root or build-scripts/.")


def ensure_build_script() -> None:
    if not BUILD_SCRIPT.exists():
        raise SystemExit(f"Build script not found: {BUILD_SCRIPT}")
    if not BUILD_SCRIPT.stat().st_mode & 0o111:
        BUILD_SCRIPT.chmod(BUILD_SCRIPT.stat().st_mode | 0o111)


def step_meta(step_id: str) -> Dict[str, object]:
    for step in STEP_DEFINITIONS:
        if step["id"] == step_id:
            return step
    raise ValueError(f"Unknown step id: {step_id}")


def stream_pipe(pipe, prefix: str, buffer: List[str]) -> None:
    for line in iter(pipe.readline, ""):
        line = line.rstrip()
        buffer.append(line)
        if line:
            print(f"{prefix} {line}")
    pipe.close()


def run_with_live_output(label: str, cmd: Sequence[str], cwd: Path | None = None) -> None:
    """Run a command streaming its output live."""
    cwd = cwd or REPO_ROOT

    process = subprocess.Popen(
        list(cmd),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    stdout_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stdout, colorize("stdout:", "36"), stdout_lines),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=stream_pipe,
        args=(process.stderr, colorize("stderr:", "31"), stderr_lines),
        daemon=True,
    )

    print(colorize(f"→ {label}", "32"))
    stdout_thread.start()
    stderr_thread.start()
    process.wait()
    stdout_thread.join()
    stderr_thread.join()

    if process.returncode != 0:
        message = "\n".join(stderr_lines[-10:] or stdout_lines[-10:])
        raise StepError(
            f"{label} failed (exit code {process.returncode}). "
            f"Tail of output:\n{message}"
        )

    print(colorize(f"✓ {label} completed successfully.", "32"))


def execute_step(step_id: str) -> None:
    meta = step_meta(step_id)
    label = meta["label"]

    run_with_live_output(label, ["bash", str(BUILD_SCRIPT), "run_step", step_id])


def execute_steps(step_ids: Sequence[str], title: str) -> None:
    if not step_ids:
        print(colorize("No steps selected; nothing to run.", "33"))
        return

    banner(f"Starting {title}")

    for step in step_ids:
        execute_step(step)

    banner(f"{title} finished")


def show_intro(config: Dict[str, object]) -> None:
    banner("MarcutApp Build Orchestrator")
    print(f"App:        {config.get('app_name')} ({config.get('bundle_id')})")
    print(f"Version:    {config.get('version')} (build {config.get('build_number')})")
    next_build = predict_appstore_build_number(config)
    if next_build:
        print(f"App Store next build: {next_build}")
    print(f"Build script: {BUILD_SCRIPT}")
    print(f"Config:       {CONFIG_PATH}")
    print()


def prompt_menu(options: List[Tuple[str, str]]) -> str:
    for idx, (value, description) in enumerate(options, start=1):
        parts = description.split("\n", 1)
        title = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        print(f"{idx}. {colorize(title, '36')}")
        if desc.strip():
            print(f"   {desc.strip()}")
    while True:
        choice = input("Select an option (number): ").strip()
        if not choice.isdigit():
            print("Please enter a numeric choice.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(options):
            return options[idx - 1][0]
        print("Choice out of range.")


def prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def prompt_text(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    response = input(f"{question}{suffix}: ").strip()
    return response or default


def advanced_menu() -> None:
    print()
    print(
        colorize(
            "Advanced Build – enter the numbers of the steps you want to run. "
            "Press Enter with no input to use the default sequence.",
            "35",
        )
    )
    for idx, meta in enumerate(STEP_DEFINITIONS, start=1):
        default_hint = " (default)" if meta["default"] else ""
        print(f"{idx:>2}. [ ] {meta['label']}{default_hint}\n     {meta['description']}")
    raw = input("Enable steps (e.g. 1,4,8): ").strip()

    if not raw:
        selected = [meta["id"] for meta in STEP_DEFINITIONS if meta["default"]]
    else:
        enabled = {meta["id"]: False for meta in STEP_DEFINITIONS}
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        for part in parts:
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(STEP_DEFINITIONS):
                    step_id = STEP_DEFINITIONS[idx - 1]["id"]
                    enabled[step_id] = True
        selected = [meta["id"] for meta in STEP_DEFINITIONS if enabled[meta["id"]]]

    execute_steps(selected, "Advanced Build")


def run_preset(name: str) -> None:
    preset = PRESETS[name]
    execute_steps(preset["steps"], preset["label"])


def build_menu() -> None:
    options = [
        (
            "quick_debug",
            "Quick Debug Build\nFast development build (skips deep clean + DMG).",
        ),
        (
            "fast_incremental",
            "Incremental Build (Skip Python Refresh)\nRebuild Swift + bundle without re-staging BeeWare.",
        ),
        (
            "full_release",
            "Full Release Build (Clean & Archive)\nRuns every step including DMG creation.",
        ),
        (
            "diagnostics",
            "Run Diagnostics & Verification\nOnly verification/tests on existing bundle.",
        ),
        (
            "advanced",
            "Advanced Build (Customize Steps)\nToggle any phase manually.",
        ),
        (
            "clean",
            "Clean All Build Artifacts\nDeep clean without rebuilding.",
        ),
        ("return", "Return\nGo back to the main menu."),
    ]

    while True:
        print()
        selection = prompt_menu(options)
        print()
        if selection == "return":
            return
        try:
            if selection in PRESETS:
                run_preset(selection)
            elif selection == "fast_incremental":
                run_preset("fast_incremental")
            elif selection == "advanced":
                advanced_menu()
        except StepError as exc:
            print(colorize(str(exc), "31"))
            if not prompt_yes_no("Return to the build menu?", default=True):
                return
        else:
            if not prompt_yes_no("Run another build workflow?", default=True):
                return


def run_tests_command(label: str, extra_args: Sequence[str]) -> None:
    script = script_from_config("tests_script")
    run_with_live_output(label, ["python3", str(script), *extra_args])


def tests_menu() -> None:
    options = [
        ("tests_all", "Run Full Test Suite\nSwift + Python tests (default)."),
        ("tests_quick", "Run Quick Tests\nSkips Swift tests for faster turnaround."),
        ("tests_swift", "Swift Tests Only\nRuns `swift test --parallel`."),
        ("tests_python", "Python Tests Only\nRuns pytest/unittest fallback."),
        ("tests_url", "URL Redaction Tests Only\nRuns targeted regression tests."),
        ("return", "Return\nBack to the main menu."),
    ]

    while True:
        print()
        selection = prompt_menu(options)
        print()
        if selection == "return":
            return

        mapping = {
            "tests_all": ([], "Full Test Suite"),
            "tests_quick": (["--quick"], "Quick Test Suite"),
            "tests_swift": (["--swift-only"], "Swift Tests"),
            "tests_python": (["--python-only"], "Python Tests"),
            "tests_url": (["--url-only"], "URL Redaction Tests"),
        }
        args, label = mapping[selection]
        try:
            run_tests_command(label, args)
        except StepError as exc:
            print(colorize(str(exc), "31"))
        if not prompt_yes_no("Run another test suite?", default=False):
            return


def run_appstore_release() -> None:
    """
    Executes scripts/sh/build_appstore_release.sh for App Store archives (no notarization).
    """
    global CONFIG
    CONFIG = load_config()
    profile_path = resolve_config_path(
        CONFIG.get("appstore_default_profile"),
        REPO_ROOT / ".marcut_artifacts" / "ignored-resources" / "certificates" / "appstore.provisionprofile",
    )
    if not profile_path.exists():
        raise StepError(f"App Store provisioning profile not found: {profile_path}")

    # Always use the shell script defined in config, usually scripts/sh/build_appstore_release.sh
    script_path = script_from_config("appstore_release_script")

    # Ensure the script is executable
    if os.path.exists(script_path):
        os.chmod(script_path, 0o755)
    else:
        raise StepError(f"Release script not found: {script_path}")

    # Run the shell script
    print(colorize(f"🚀 Running App Store Build Script: {script_path.name}", "34"))
    next_build = predict_appstore_build_number(CONFIG)
    if next_build:
        print(colorize(f"Next App Store build number: {next_build}", "34"))
    run_with_live_output(
        "App Store Release Build",
        ["bash", str(script_path), "--skip-notarization"],
    )
    CONFIG = load_config()

    # Check result
    archive_root = resolve_config_path(
        CONFIG.get("appstore_archive_root"),
        REPO_ROOT / ".marcut_artifacts" / "ignored-resources" / "appstore" / "Archive",
    )
    archive_name = str(CONFIG.get("appstore_default_archive", "MarcutApp-AppStore"))
    archive_path = archive_root / f"{archive_name}.xcarchive"
    if archive_path.exists():
        print()
        print(colorize("✅ App Store Archive Created Successfully!", "32"))
        print(f"Location: {archive_path}")
        print()
        print(colorize("Instructions:", "34"))
        print("1. The folder 'Archive/MarcutApp.xcarchive' is ready.")
        print("2. Opening in Xcode Organizer now...")
        subprocess.run(["open", str(archive_path)])
    else:
        raise StepError("Archive creation failed (folder not found). Check logs.")


def run_developer_id_dmg() -> None:
    """
    Runs the Developer ID build script to produce a notarized DMG for direct distribution.
    """
    script_path = REPO_ROOT / "scripts" / "sh" / "build_devid_release.sh"

    if not script_path.exists():
        raise StepError(f"Developer ID release script not found: {script_path}")

    os.chmod(script_path, 0o755)
    print(colorize(f"🚀 Running Developer ID Notarized DMG: {script_path.name}", "34"))
    run_with_live_output("Developer ID Notarized DMG", ["bash", str(script_path)])


def run_appstore_archive() -> None:
    """Deprecated compatibility wrapper for the old Xcode archive path."""
    print(colorize("Using scripted App Store build for a path-clean, reproducible archive.", "34"))
    run_appstore_release()


def run_swiftpm_appstore_archive() -> None:
    """Deprecated compatibility wrapper."""
    print(colorize("run_swiftpm_appstore_archive is deprecated; using scripted App Store build instead.", "33"))
    run_appstore_release()


def notarize_existing_dmg() -> None:
    script = script_from_config("notarize_script")
    default_dmg = CONFIG.get("final_dmg")
    default_path = ""
    if default_dmg:
        candidate = resolve_config_path(default_dmg)
        if candidate.exists():
            default_path = str(candidate)

    dmg_path = prompt_text("Path to DMG for notarization", default_path)
    if not dmg_path:
        print("No DMG specified; aborting.")
        return

    dmg = Path(dmg_path).expanduser().resolve()
    if not dmg.exists():
        print(colorize(f"DMG not found: {dmg}", "31"))
        return

    run_with_live_output("Notarize DMG", ["bash", str(script), str(dmg)])


def distribution_menu() -> None:
    options = [
        (
            "appstore_build",
            "Build App Store Archive + DMG\nUses App Store signing; skips notarization.",
        ),
        (
            "developer_id_dmg",
            "Build Developer ID DMG\nDeveloper ID Application signing + notarization for direct downloads.",
        ),
        (
            "appstore_archive",
            "Create App Store Archive (Recommended)\n🎯 Scripted App Store build (no notarization).",
        ),
        (
            "appstore_export_pkg",
            "Export PKG for Transporter (No Upload)\nCreates signed PKG via submit_appstore.sh --export-only.",
        ),
        (
            "appstore_xcode",
            "Create App Store Archive (Compatibility Alias)\nUses the scripted App Store build path.",
        ),
        (
            "notarize_dmg",
            "Notarize Existing DMG\nSubmit + staple via scripts/notarize_macos.sh.",
        ),
        (
            "submit_app_store_cli",
            "Submit to App Store (CLI)\n🚀 Export signed PKG and upload to App Store Connect.",
        ),
        ("return", "Return\nBack to the main menu."),
    ]

    while True:
        print()
        selection = prompt_menu(options)
        print()
        if selection == "return":
            return

        try:
            if selection == "appstore_build":
                run_appstore_release()
            elif selection == "developer_id_dmg":
                run_developer_id_dmg()
            elif selection == "appstore_archive":
                print(colorize("🎯 RECOMMENDED: Using proven App Store build script", "32"))
                print(colorize("Swift Package archives aren't App Store-ready - use dedicated build", "34"))
                run_appstore_release()
            elif selection == "appstore_xcode":
                run_appstore_archive()
            elif selection == "notarize_dmg":
                notarize_existing_dmg()
            elif selection == "submit_app_store_cli":
                script = submit_appstore_script()
                print(f"\n🚀 Running Submission Script: {script}")
                try:
                    subprocess.run(["bash", str(script)], check=False, timeout=180)
                except subprocess.TimeoutExpired:
                    print(colorize("\n❌ Submission timed out after 3 minutes.", "31"))
                input("\nPress Enter to continue...")
            elif selection == "appstore_export_pkg":
                script = submit_appstore_script()
                print(f"\n📦 Exporting PKG for Transporter: {script}")
                try:
                    subprocess.run(["bash", str(script), "--export-only"], check=False, timeout=180)
                except subprocess.TimeoutExpired:
                    print(colorize("\n❌ Export timed out after 3 minutes.", "31"))
                archive_root = resolve_config_path(
                    CONFIG.get("appstore_archive_root"),
                    REPO_ROOT / ".marcut_artifacts" / "ignored-resources" / "appstore" / "Archive",
                )
                app_name = str(CONFIG.get("app_name", "MarcutApp"))
                pkg_path = archive_root / "Exported" / f"{app_name}.pkg"
                if pkg_path.exists() and prompt_yes_no("Open in Transporter now?", default=True):
                    subprocess.run(["open", "-a", "Transporter", str(pkg_path)])
                input("\nPress Enter to continue...")
        except StepError as exc:
            print(colorize(str(exc), "31"))
        if not prompt_yes_no("Perform another distribution task?", default=False):
            return


def main_menu() -> None:
    options = [
        (
            "build",
            "Build Workflows\nPresets, advanced customization, and cleaning tasks.",
        ),
        (
            "tests",
            "Run Tests\nExecute Swift/Python/URL suites via run_tests.py.",
        ),
        (
            "distribution",
            "Distribution & Notarization\nApp Store builds and notarization helpers.",
        ),
        ("exit", "Exit\nClose the build orchestrator."),
    ]

    while True:
        print()
        selection = prompt_menu(options)
        print()
        if selection == "exit":
            print("Goodbye!")
            return

        try:
            if selection == "build":
                build_menu()
            elif selection == "tests":
                tests_menu()
            elif selection == "distribution":
                distribution_menu()
        except StepError as exc:
            print(colorize(str(exc), "31"))
            if not prompt_yes_no("Return to main menu?", default=True):
                return


def main() -> None:
    global CONFIG
    CONFIG = load_config()
    ensure_build_script()
    show_intro(CONFIG)
    main_menu()


if __name__ == "__main__":
    main()
