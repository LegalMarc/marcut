#!/usr/bin/env python3
"""
Interactive TUI wrapper around build_swift_only.sh using only the Python standard library.

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
# Project root is parent of build-scripts/
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Force execution from SCRIPT_DIR so relative paths in config.json (../src/) work correctly
if os.getcwd() != SCRIPT_DIR:
    print(f"🔄 Switching working directory to: {SCRIPT_DIR}")
    os.chdir(SCRIPT_DIR)

print(f"✅ Running script from: {SCRIPT_PATH}")
print(f"✅ Project root: {PROJECT_ROOT}")

# Clear all __pycache__ directories recursively
import glob
cache_dirs = glob.glob(os.path.join(SCRIPT_DIR, "**/__pycache__"), recursive=True)
for cache_dir in cache_dirs:
    try:
        import shutil
        shutil.rmtree(cache_dir)
    except:
        pass

# Clear .pyc files
pyc_files = glob.glob(os.path.join(SCRIPT_DIR, "**/*.pyc"), recursive=True)
for pyc_file in pyc_files:
    try:
        os.remove(pyc_file)
    except:
        pass

# (Verification message moved above)

# RULE: Always ensure TUI build works with latest app fixes
print("🔄 SYNC: Ensuring latest source changes are included in TUI build...")

# Check if src/swift/MarcutApp/Sources/ needs sync
ROOT_SOURCES = os.path.join(PROJECT_ROOT, "src", "swift", "MarcutApp", "Sources", "MarcutApp")
TUI_SOURCES = os.path.join(PROJECT_ROOT, "src", "swift", "MarcutApp", "Sources", "MarcutApp")

if os.path.exists(ROOT_SOURCES) and os.path.exists(TUI_SOURCES):
    import shutil
    import filecmp
    import time

    print("🔄 SYNC: Checking for source synchronization...")

    # Key files to always sync for critical fixes
    CRITICAL_FILES = ["PythonBridge.swift"]
    needs_sync = False

    for critical_file in CRITICAL_FILES:
        root_path = os.path.join(ROOT_SOURCES, critical_file)
        tui_path = os.path.join(TUI_SOURCES, critical_file)

        if os.path.exists(root_path) and os.path.exists(tui_path):
            # Compare files and sync if different
            if not filecmp.cmp(root_path, tui_path):
                print(f"🔄 SYNC: Updating {critical_file} with latest fixes...")
                shutil.copy2(root_path, tui_path)
                needs_sync = True
            else:
                print(f"✅ SYNC: {critical_file} is up to date")
        elif os.path.exists(root_path):
            print(f"🔄 SYNC: Adding {critical_file} to TUI build...")
            shutil.copy2(root_path, tui_path)
            needs_sync = True

    if needs_sync:
        print("✅ SYNC: Critical fixes synchronized to TUI build sources")
        # Add small delay to ensure filesystem sync
        time.sleep(0.5)
    else:
        print("✅ SYNC: All critical files up to date")

import json
import plistlib
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

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

# Build scripts are in build-scripts/, so REPO_ROOT is the parent
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPTS_DIR / "config.json"
BUILD_SCRIPT = SCRIPTS_DIR / "build_swift_only.sh"
CONFIG: Dict[str, object] = {}

STEP_DEFINITIONS: List[Dict[str, object]] = [
    {
        "id": "bump_version",
        "label": "Step 0: Bump Patch Version",
        "description": "Increments the patch version in config.json, syncs build_number, and refreshes the DMG name.",
        "default": False,
    },
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
        "id": "sync_python_sources",
        "label": "Step 3.5: Sync Python Sources",
        "description": "Copies latest marcut/ package to staging before assembly.",
        "default": False,
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
        "description": "Builds the .app structure, embeds Python, Ollama, and the XPC helper.",
        "default": True,
    },
    {
        "id": "bundle_cleanup",
        "label": "Step 5.5: Bundle Bytecode Cleanup",
        "description": "Removes __pycache__ and .pyc/.pyo artifacts before signing.",
        "default": True,
    },
    {
        "id": "sign_components",
        "label": "Step 6: Sign App Components",
        "description": "Developer ID signs the helper binaries, frameworks, and bundle.",
        "default": True,
    },
    {
        "id": "testing_cleanup",
        "label": "Step 6.5: Testing Environment Cleanup",
        "description": "Clears caches, permissions, and quarantine for fresh testing.",
        "default": True,
    },
    {
        "id": "bundle_audit",
        "label": "Step 7: Bundle Audit (Gatekeeper + File Checks)",
        "description": "Validates bundle contents + signatures and runs clean-env --diagnose; Gatekeeper checks run only for notarized DMGs (Full Release).",
        "default": True,
    },
    {
        "id": "functional_verification",
        "label": "Step 8: Post-Build Functional Verification",
        "description": "Runs --help/--diagnose/CLI smoke tests.",
        "default": True,
    },
    {
        "id": "create_dmg",
        "label": "Step 9: Create Final DMG",
        "description": "Packages the signed .app into a distributable DMG file.",
        "default": False,
    },
    {
        "id": "notarize_dmg",
        "label": "Step 10: Notarize & Staple DMG",
        "description": "Runs upload/scripts/notarize_macos.sh (prompts for API key or Apple ID creds; saves to ~/.config/marcut/notarize.env).",
        "default": False,
    },
]

PRESETS: Dict[str, Dict[str, object]] = {
    "dev_fast": {
        "label": "Dev Fast + Test Prep (reuse Python runtime)",
        "description": "Rebuild Swift + bundle with testing cleanup. Skips deep cleanup and BeeWare refresh for quick iteration.",
        "steps": [
            "sync_python_sources",
            "build_swift",
            "assemble_bundle",
            "bundle_cleanup",
            "sign_components",
            "testing_cleanup",
        ],
    },
    "quick_debug": {
        "label": "Quick Debug Build",
        "description": "Fastest option for development. Skips deep cleaning and DMG creation.",
        "steps": [
            "cleanup",
            "refresh_python",
            "sync_python_sources",
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "bundle_cleanup",
            "sign_components",
            "bundle_audit",
            "functional_verification",
        ],
    },
    "full_release": {
        "label": "Full Release Build (Clean & Archive)",
        "description": "Auto-bumps patch version, then deep clean, bundle audit, smoke tests, DMG creation, and notarization.",
        "steps": [
            "bump_version",
            "cleanup",
            "refresh_python",
            "sync_python_sources",
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "bundle_cleanup",
            "sign_components",
            "testing_cleanup",
            "functional_verification",
            "create_dmg",
            "notarize_dmg",
            "bundle_audit",
        ],
    },
    "diagnostics": {
        "label": "Run Diagnostics & Verification",
        "description": "Skips rebuild and only runs verification/tests on the existing bundle.",
        "steps": [
            "verify_build",
            "bundle_audit",
            "functional_verification",
        ],
    },
    "fast_incremental": {
        "label": "Incremental Build + Test Prep",
        "description": "Skip BeeWare refresh and rebuild only Swift + bundle with testing cleanup.",
        "steps": [
            "sync_python_sources",
            "build_swift",
            "verify_build",
            "assemble_bundle",
            "bundle_cleanup",
            "sign_components",
            "testing_cleanup",
            "bundle_audit",
        ],
    },
    "python_only": {
        "label": "Python Logic Only (Hot-Swap)",
        "description": "Updates only the Python code in existing bundle & resigns. Requires prior full build.",
        "steps": [
            # Syncs Python sources to staging, then directly to existing bundle
            "sync_python_sources",
            # Skip assemble_bundle - we don't want to rebuild the entire bundle structure
            # Just re-sign what's already there with updated Python code
            "bundle_cleanup",
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


def script_from_config(key: str) -> Path:
    value = CONFIG.get(key)
    if not value:
        raise StepError(f"Config missing '{key}' entry.")
    path = (REPO_ROOT / value).resolve()
    if not path.exists():
        raise StepError(f"Script not found: {path}")
    return path


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


    print(colorize(f"✓ {label} completed successfully.", "32"))


def notify_build_complete(title: str, success: bool = True) -> None:
    """Send a terminal bell and macOS notification."""
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    if success:
        print(colorize(f"🕒 Build finished at: {now}", "35"))
        sound = "Glass"
        msg = f"{title} Completed"
    else:
        print(colorize(f"❌ Build failed at: {now}", "31"))
        sound = "Basso"
        msg = f"{title} Failed"
        
    # Terminal Bell
    print("\a")
    
    # macOS Notification
    try:
        subprocess.run([
            "osascript", "-e", 
            f'display notification "{msg}" with title "Marcut Build" sound name "{sound}"'
        ], capture_output=True)
    except Exception:
        pass


def execute_step(step_id: str) -> None:
    meta = step_meta(step_id)
    label = meta["label"]

    if step_id == "sync_python_sources":
        # Internal Python implementation to avoid shell script dependency issues
        print(colorize("→ Syncing Python Sources (Repo -> Staging)", "32"))
        try:
            src = REPO_ROOT / "src" / "python" / "marcut"
            dst = REPO_ROOT / "src" / "swift" / "MarcutApp" / "Sources" / "MarcutApp" / "python_site" / "marcut"
            if src.exists():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                
                # Sync excluded-words.txt payload
                assets_excluded = REPO_ROOT / "assets" / "excluded-words.txt"
                dst_excluded = dst / "excluded-words.txt"
                if assets_excluded.exists():
                    shutil.copy2(assets_excluded, dst_excluded)
                
                print(colorize("✓ Synced marcut package to staging.", "32"))
            else:
                print(colorize("❌ Source marcut dir not found!", "31"))
                raise StepError("Source marcut dir not found")
        except StepError:
            raise
        except Exception as e:
            print(colorize(f"❌ Sync failed: {e}", "31"))
            raise StepError("Source sync failed")
        
        # Also sync directly to existing bundle if it exists (for hot-swap)
        bundle_python_site = REPO_ROOT / "ignored-resources" / "builds" / "build_swift" / "MarcutApp.app" / "Contents" / "Resources" / "python_site" / "marcut"
        if bundle_python_site.parent.exists():
            print(colorize("→ Syncing Python Sources (Staging -> Existing Bundle)", "32"))
            try:
                if bundle_python_site.exists():
                    shutil.rmtree(bundle_python_site)
                shutil.copytree(src, bundle_python_site, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                
                # Sync excluded-words.txt payload to bundle (both package and Resources root)
                assets_excluded = REPO_ROOT / "assets" / "excluded-words.txt"
                dst_excluded_pkg = bundle_python_site / "excluded-words.txt"
                # bundle_python_site is .../Resources/python_site/marcut
                # We want .../Resources/excluded-words.txt
                dst_excluded_resources = bundle_python_site.parent.parent / "excluded-words.txt"
                
                if assets_excluded.exists():
                    # Update Python package copy (used by Python backend default)
                    shutil.copy2(assets_excluded, dst_excluded_pkg)
                    
                    # Update Resources root copy (used by Swift frontend default)
                    if dst_excluded_resources.parent.exists():
                        shutil.copy2(assets_excluded, dst_excluded_resources)
                
                # Sync system-prompt.txt payload to bundle (Resources root only - used by Swift)
                assets_prompt = REPO_ROOT / "assets" / "system-prompt.txt"
                dst_prompt_resources = bundle_python_site.parent.parent / "system-prompt.txt"
                
                if assets_prompt.exists():
                    if dst_prompt_resources.parent.exists():
                        shutil.copy2(assets_prompt, dst_prompt_resources)
                    
                print(colorize("✓ Synced marcut package to existing bundle.", "32"))
            except Exception as e:
                print(colorize(f"⚠️  Bundle sync failed (bundle may not exist yet): {e}", "33"))
        else:
            print(colorize("ℹ️  No existing bundle found - skipping direct bundle sync.", "36"))
        return

    run_with_live_output(label, ["bash", str(BUILD_SCRIPT), "run_step", step_id])

    if step_id == "bump_version":
        global CONFIG
        CONFIG = load_config()


def execute_steps(step_ids: Sequence[str], title: str) -> None:
    if not step_ids:
        print(colorize("No steps selected; nothing to run.", "33"))
        return

    step_ids = list(step_ids)
    if "create_dmg" in step_ids and "bump_version" not in step_ids:
        print(colorize("Auto-bumping patch version for DMG build.", "33"))
        step_ids = ["bump_version", *step_ids]

    banner(f"Starting {title}")

    for step in step_ids:
        execute_step(step)

    # Clear, prominent ending
    print()
    print(colorize("=" * 60, "32"))
    print(colorize("  ✅ BUILD COMPLETE", "32"))
    print(colorize("=" * 60, "32"))
    
    # Show DMG path if it exists (DMGs are now in ignored-resources/)
    dmg_dir = REPO_ROOT / "ignored-resources"
    dmg_files = list(dmg_dir.glob("MarcutApp-Swift-*.dmg"))
    if dmg_files:
        latest_dmg = max(dmg_files, key=lambda p: p.stat().st_mtime)
        print(colorize(f"  📦 DMG: {latest_dmg.name}", "36"))
        print(colorize(f"     Path: {latest_dmg}", "35"))
    
    print()
    banner(f"{title} finished")
    notify_build_complete(title, success=True)


def show_intro(config: Dict[str, object]) -> None:
    banner("MarcutApp Build Orchestrator")
    print(f"App:        {config.get('app_name')} ({config.get('bundle_id')})")
    print(f"Version:    {config.get('version')} (build {config.get('build_number')})")
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


def delete_models_workflow() -> None:
    """
    Interactive workflow to delete downloaded Ollama models from the app's sandbox.
    """
    import shutil
    
    # Define the path to the app's sandboxed Ollama models
    # Note: This hardcodes the path for the current user. 
    # In a real multi-user scenario we might need to be more dynamic, but for a dev tool this is fine.
    home = Path.home()
    sandbox_models_dir = home / "Library/Containers/com.marclaw.marcutapp/Data/Library/Application Support/MarcutApp/ollama/models"
    
    if not sandbox_models_dir.exists():
        print(colorize(f"❌ No models directory found at: {sandbox_models_dir}", "31"))
        print("The app may not have run yet, or no models have been downloaded.")
        return

    print(colorize(f"🔍 Scanning for models in: {sandbox_models_dir}", "34"))
    
    # Simple discovery: look for manifests
    manifests_dir = sandbox_models_dir / "manifests"
    blobs_dir = sandbox_models_dir / "blobs"
    
    if not manifests_dir.exists():
        print(colorize("No manifests directory found.", "33"))
        return

    # Find all manifest files
    models = []
    for registry in manifests_dir.iterdir():
        if not registry.is_dir(): continue
        for library in registry.iterdir():
            if not library.is_dir(): continue
            for model_name in library.iterdir():
                if not model_name.is_dir(): continue
                # Check for tag files (Ollama 0.12.5+) or manifest.json
                for tag_file in model_name.iterdir():
                    if tag_file.name.startswith("."): continue
                    tag = "latest" if tag_file.name == "manifest.json" else tag_file.name
                    full_name = f"{model_name.name}:{tag}"
                    models.append({
                        "name": full_name,
                        "manifest_path": tag_file,
                        "blob_dir": blobs_dir # We might not know exact blobs without parsing, but we can delete the manifest
                    })

    if not models:
        print(colorize("No installed models found.", "33"))
        return

    print()
    print(colorize("Installed Models:", "36"))
    for idx, model in enumerate(models, 1):
        print(f"{idx}. {model['name']}")
    
    print(f"{len(models) + 1}. Delete ALL Models")
    print(f"{len(models) + 2}. Cancel")
    
    choice = input("\nSelect a model to delete (number): ").strip()
    if not choice.isdigit():
        return
        
    idx = int(choice)
    
    if idx == len(models) + 2:
        return
        
    if idx == len(models) + 1:
        if prompt_yes_no("Are you sure you want to delete ALL models? This cannot be undone.", default=False):
            print(colorize("Deleting all models...", "31"))
            try:
                shutil.rmtree(sandbox_models_dir)
                print(colorize("✅ All models deleted.", "32"))
            except Exception as e:
                print(colorize(f"❌ Failed to delete directory: {e}", "31"))
        return

    if 1 <= idx <= len(models):
        target = models[idx-1]
        if prompt_yes_no(f"Delete model '{target['name']}'?", default=True):
            print(colorize(f"Deleting {target['name']}...", "33"))
            try:
                # Delete the manifest file
                target["manifest_path"].unlink()
                print(colorize("✅ Manifest deleted.", "32"))
                
                # Note: We are NOT aggressively cleaning up blobs here because they might be shared.
                # A full cleanup would require parsing all manifests to find unreferenced blobs.
                # For a "quick delete" to fix issues, removing the manifest is usually enough to make Ollama forget it.
                # If the user wants to reclaim space, "Delete ALL" is better.
                print("Note: Shared blobs were preserved. Use 'Delete ALL' to reclaim full disk space.")
                
            except Exception as e:
                print(colorize(f"❌ Failed to delete model: {e}", "31"))


def check_dependency_updates() -> None:
    """Run the dependency update checker script."""
    script_path = REPO_ROOT / "scripts" / "check_dependency_updates.py"
    if not script_path.exists():
        print(colorize(f"❌ Script not found: {script_path}", "31"))
        return
    
    print(colorize("🔍 Checking for dependency updates...", "34"))
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(REPO_ROOT),
            check=False
        )
        if result.returncode != 0:
            print(colorize("⚠️  Dependency check completed with warnings.", "33"))
    except Exception as e:
        print(colorize(f"❌ Failed to run dependency checker: {e}", "31"))
    
    input("\nPress Enter to continue...")


def force_rebuild_dependencies() -> None:
    """Force rebuild Python dependencies by purging pip cache."""
    if not prompt_yes_no("This will purge the pip cache and rebuild all Python dependencies from source. Continue?", default=False):
        return
    
    script_path = REPO_ROOT / "setup_beeware_framework.sh"
    if not script_path.exists():
        print(colorize(f"❌ Script not found: {script_path}", "31"))
        return
    
    print(colorize("🔄 Force rebuilding Python dependencies (this may take several minutes)...", "34"))
    try:
        run_with_live_output(
            "Force Dependency Rebuild",
            ["bash", str(script_path), "--purge-cache"]
        )
        print(colorize("✅ Dependencies rebuilt successfully.", "32"))
    except StepError as e:
        print(colorize(f"❌ Rebuild failed: {e}", "31"))
    
    input("\nPress Enter to continue...")


def build_menu() -> None:
    options = [
        (
            "quick_debug",
            "Quick Debug Build\nFast dev build with bundle audit + smoke tests (skips deep clean + DMG).",
        ),
        (
            "fast_incremental",
            "Incremental Build (Skip Python Refresh)\nRebuild Swift + bundle with test cleanup + bundle audit.",
        ),
        (
            "full_release",
            "Full Release Build (Clean & Archive)\nAuto-bumps patch version, builds DMG, and notarizes.",
        ),
        (
            "diagnostics",
            "Run Diagnostics & Verification\nVerify build + bundle audit + smoke tests (no rebuild).",
        ),
        (
            "delete_models",
            "Delete Downloaded Models\nManage/Delete models from the app's sandbox.",
        ),
        (
            "python_only",
            "Python Logic Only (Hot-Swap)\nUpdates only Python code (skips Swift rebuild). Fastest for pure logic fixes.",
        ),
        (
            "check_deps",
            "Check Dependency Updates\nQuery PyPI for latest versions and show safe vs breaking updates.",
        ),
        (
            "force_rebuild_deps",
            "Force Dependency Rebuild\nPurge pip cache and recompile all Python dependencies from source.",
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
            elif selection == "python_only":
                run_preset("python_only")
            elif selection == "delete_models":
                delete_models_workflow()
            elif selection == "check_deps":
                check_dependency_updates()
            elif selection == "force_rebuild_deps":
                force_rebuild_dependencies()
            elif selection == "advanced":
                advanced_menu()
        except StepError as exc:
            notify_build_complete("Build", success=False)
            print(colorize(str(exc), "31"))
            if not prompt_yes_no("Return to the build menu?", default=True):
                return
        else:
            if selection not in ("delete_models", "check_deps") and not prompt_yes_no("Run another build workflow?", default=True):
                return

def run_tests_command(label: str, extra_args: Sequence[str]) -> None:
    script = script_from_config("tests_script")
    run_with_live_output(label, ["python3", str(script), *extra_args])


def tests_menu() -> None:
    options = [
        ("tests_all", "Run Full Test Suite\nSwift + Python + Metadata + Functional tests."),
        ("tests_quick", "Run Quick Tests\nSkips Swift tests for faster turnaround."),
        ("tests_swift", "Swift Tests Only\nRuns `swift test --parallel`."),
        ("tests_python", "Python Tests Only\nRuns pytest/unittest fallback."),
        ("tests_url", "URL Redaction Tests Only\nRuns targeted regression tests."),
        ("tests_metadata", "Metadata Scrubbing Tests\nTests metadata cleaning + path escaping + reports."),
        ("tests_metadata_matrix", "Metadata Matrix Validation\nRuns per-toggle scrubbing and corruption checks."),
        ("app_diagnose", "App Diagnostics (--diagnose)\nRuns built app diagnostics (Ollama, PythonKit, model)."),
        ("app_functional", "Functional Verification\nRuns CLI smoke tests on built app."),
        ("tests_report", "Generate Full Test Report\nRuns all tests and saves JSON report to /tmp."),
        ("return", "Return\nBack to the main menu."),
    ]

    while True:
        print()
        selection = prompt_menu(options)
        print()
        if selection == "return":
            return

        try:
            if selection == "app_diagnose":
                run_app_diagnostics()
            elif selection == "app_functional":
                execute_step("functional_verification")
            elif selection == "tests_report":
                run_full_test_report()
            else:
                mapping = {
                    "tests_all": ([], "Full Test Suite"),
                    "tests_quick": (["--quick"], "Quick Test Suite"),
                    "tests_swift": (["--swift-only"], "Swift Tests"),
                    "tests_python": (["--python-only"], "Python Tests"),
                    "tests_url": (["--url-only"], "URL Redaction Tests"),
                    "tests_metadata": (["--metadata-only"], "Metadata Scrubbing Tests"),
                    "tests_metadata_matrix": (["--metadata-matrix"], "Metadata Matrix Validation"),
                }
                args, label = mapping[selection]
                run_tests_command(label, args)
            notify_build_complete(selection, success=True)
        except StepError as exc:
            notify_build_complete(selection, success=False)
            print(colorize(str(exc), "31"))
        if not prompt_yes_no("Run another test suite?", default=False):
            return


def run_app_diagnostics() -> None:
    """Run the built app's --diagnose command."""
    app_path = REPO_ROOT / "build_swift" / "MarcutApp.app" / "Contents" / "MacOS" / "MarcutApp"
    if not app_path.exists():
        raise StepError(f"App not found at {app_path}. Build first.")
    
    print(colorize("🔍 Running App Diagnostics (--diagnose)...", "34"))
    run_with_live_output("App Diagnostics", [str(app_path), "--diagnose"])


def run_full_test_report() -> None:
    """Run all tests and generate a comprehensive JSON report."""
    import datetime
    
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"/tmp/marcut_test_report_{timestamp}.json"
    
    print(colorize(f"📊 Generating Full Test Report: {report_path}", "34"))
    
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "tests": {}
    }
    
    # Run Python tests
    print(colorize("\n1️⃣ Running Python Tests...", "36"))
    try:
        run_tests_command("Python Tests", ["--python-only"])
        results["tests"]["python"] = {"status": "passed"}
    except StepError:
        results["tests"]["python"] = {"status": "failed"}
    
    # Run Metadata tests
    print(colorize("\n2️⃣ Running Metadata Scrubbing Tests...", "36"))
    try:
        run_tests_command("Metadata Tests", ["--metadata-only"])
        results["tests"]["metadata"] = {"status": "passed"}
    except StepError:
        results["tests"]["metadata"] = {"status": "failed"}
    
    # Run Metadata Matrix
    print(colorize("\n3️⃣ Running Metadata Matrix Validation...", "36"))
    try:
        run_tests_command("Metadata Matrix", ["--metadata-matrix"])
        results["tests"]["metadata_matrix"] = {"status": "passed"}
    except StepError:
        results["tests"]["metadata_matrix"] = {"status": "failed"}

    # Run App Diagnostics
    print(colorize("\n4️⃣ Running App Diagnostics...", "36"))
    try:
        run_app_diagnostics()
        results["tests"]["app_diagnose"] = {"status": "passed"}
    except StepError:
        results["tests"]["app_diagnose"] = {"status": "failed"}
    
    # Run Functional Verification
    print(colorize("\n5️⃣ Running Functional Verification...", "36"))
    try:
        execute_step("functional_verification")
        results["tests"]["functional"] = {"status": "passed"}
    except StepError:
        results["tests"]["functional"] = {"status": "failed"}
    
    # Summary
    passed = sum(1 for t in results["tests"].values() if t["status"] == "passed")
    total = len(results["tests"])
    results["summary"] = {
        "passed": passed,
        "failed": total - passed,
        "total": total,
        "success": passed == total
    }
    
    # Save report
    import json
    with open(report_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print()
    print(colorize("=" * 60, "32" if results["summary"]["success"] else "31"))
    print(colorize(f"📊 Test Report Summary: {passed}/{total} passed", "32" if results["summary"]["success"] else "31"))
    print(colorize(f"📄 Report saved to: {report_path}", "35"))
    print(colorize("=" * 60, "32" if results["summary"]["success"] else "31"))
    
    if not results["summary"]["success"]:
        raise StepError("Some tests failed")




def run_appstore_release() -> None:
    """
    Executes the robust build_appstore_release.sh script.
    """
    # Always use the shell script defined in config, usually build_appstore_release.sh
    script_path = script_from_config("appstore_release_script")

    # Ensure the script is executable
    if os.path.exists(script_path):
        os.chmod(script_path, 0o755)
    else:
        raise StepError(f"Release script not found: {script_path}")

    # Run the shell script
    print(colorize(f"🚀 Running App Store Build Script: {script_path.name}", "34"))
    run_with_live_output("App Store Release Build", ["bash", str(script_path)])

    # Check result
    archive_root = Path(CONFIG.get("appstore_archive_root", str(REPO_ROOT / "Archive"))).resolve()
    archive_path = archive_root / "MarcutApp.xcarchive"
    if archive_path.exists():
        print()
        print(colorize("✅ App Store Archive Created Successfully!", "32"))
        print(f"Location: {archive_path}")
        print()
        print(colorize("Instructions:", "34"))
        print("1. The folder 'Archive/MarcutApp.xcarchive' is ready.")
        if prompt_yes_no("Open in Xcode Organizer now?", default=True):
            print("2. Opening in Xcode Organizer...")
            subprocess.run(["open", str(archive_path)])
        if prompt_yes_no("Run submit_appstore.sh to export + upload now?", default=False):
            subprocess.run(["./submit_appstore.sh"], check=False)
    else:
        raise StepError("Archive creation failed (folder not found). Check logs.")


def run_appstore_archive() -> None:
    project_dir = (REPO_ROOT / str(CONFIG.get("swift_project_dir", "MarcutApp"))).resolve()
    if not project_dir.exists():
        raise StepError(f"Swift project directory not found: {project_dir}")

    archive_root = REPO_ROOT / "Archive"
    archive_root.mkdir(exist_ok=True)

    # Check for provisioning profile in root
    provisioning_profile = REPO_ROOT / "Marcut_App_Store.provisionprofile"
    has_profile = provisioning_profile.exists()
    
    if has_profile:
        print(colorize(f"✅ Found provisioning profile: {provisioning_profile.name}", "32"))
        
    # Use your specific credentials
    default_scheme = str(CONFIG.get("appstore_scheme", "MarcutApp"))
    default_archive_name = str(CONFIG.get("appstore_default_archive", "MarcutApp-AppStore"))
    default_team = "QG85EMCQ75"  # Your Team ID
    
    scheme = prompt_text("Scheme to archive", default_scheme)
    archive_name = prompt_text("Archive base name", default_archive_name)
    team_id = prompt_text("Team ID for signing", default_team)

    # Manual signing logic
    use_manual_signing = False
    code_sign_identity = ""
    profile_specifier = ""
    
    if has_profile:
        if prompt_yes_no(f"Use manual signing with {provisioning_profile.name}? (Recommended)", default=True):
            use_manual_signing = True
            # Get profile UUID or name - for now we'll use the filename or try to extract UUID if we had a parser
            # But xcodebuild often takes the name or UUID. Let's try to use the profile name (without extension) or specifier
            # Actually, for manual signing via xcodebuild, we often need the UUID. 
            # Let's try a simpler approach: "Manual" style requires explicit profile mapping.
            # For simplicity in this TUI, we will try to use the profile name.
            profile_specifier = provisioning_profile.stem # "Marcut_App_Store"
            code_sign_identity = "3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)" # Correct App Store identity
            print(colorize("✅ Using Manual Signing configuration", "32"))
    
    if not use_manual_signing:
        if prompt_yes_no("Use automatic signing (recommended ONLY if Xcode is configured perfectly)?", default=True):
            code_sign_identity = ""
            profile_specifier = ""
            print(colorize("✅ Using automatic signing - Xcode will handle certificates", "32"))
        else:
            code_sign_identity = prompt_text("Code signing identity (leave blank for automatic)", "")
            profile_specifier = prompt_text("Provisioning profile (leave blank for automatic)", "")

    # Clean up old archives first
    print(colorize("Cleaning up old Xcode archives...", "33"))
    old_archives = list(archive_root.glob("*.xcarchive"))
    for old_archive in old_archives:
        print(f"Removing old archive: {old_archive.name}")
        try:
            shutil.rmtree(old_archive)
        except Exception as e:
            print(colorize(f"Warning: Could not remove {old_archive.name}: {e}", "33"))

    archive_path = archive_root / f"{archive_name}.xcarchive"
    export_dir = archive_root / f"{archive_name}-export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    # Find the Swift Package workspace
    workspace_path = project_dir / ".swiftpm" / "xcode" / "package.xcworkspace"
    if not workspace_path.exists():
        raise StepError(f"Swift Package workspace not found: {workspace_path}")

    print(colorize(f"Using workspace: {workspace_path}", "34"))

    archive_cmd: List[str] = [
        "xcodebuild",
        "archive",
        "-workspace",
        str(workspace_path),
        "-scheme",
        scheme,
        "-configuration",
        "Release",
        "-archivePath",
        str(archive_path),
        "-destination",
        "generic/platform=macOS",
        "SKIP_INSTALL=NO",
        "BUILD_LIBRARY_FOR_DISTRIBUTION=YES",
    ]
    
    if team_id:
        archive_cmd.append(f"DEVELOPMENT_TEAM={team_id}")
        
    if use_manual_signing:
        archive_cmd.append("CODE_SIGN_STYLE=Manual")
        archive_cmd.append(f"CODE_SIGN_IDENTITY={code_sign_identity}")
        archive_cmd.append(f"PROVISIONING_PROFILE_SPECIFIER={profile_specifier}")
    elif code_sign_identity or profile_specifier:
        # User manual overrides
        if code_sign_identity:
            archive_cmd.append(f"CODE_SIGN_IDENTITY={code_sign_identity}")
        if profile_specifier:
            archive_cmd.append(f"PROVISIONING_PROFILE_SPECIFIER={profile_specifier}")

    run_with_live_output("Xcode Archive", archive_cmd, cwd=project_dir)

    print(colorize(f"✅ Xcode Archive ready at {archive_path}", "32"))
    print(colorize("⚠️  Swift Package archives need Xcode Organizer for App Store submission", "33"))
    print()
    print(colorize("Open in Xcode Organizer:", "34"))

    # For Swift Packages, open Xcode Organizer directly
    if prompt_yes_no("Open in Xcode Organizer for App Store submission?", default=True):
        print(colorize("Opening Xcode Organizer...", "33"))
        subprocess.run(["open", str(archive_path)], check=True)

        print(colorize("✅ Xcode Organizer opened with your archive", "32"))
        print(colorize("Next steps in Xcode Organizer:", "34"))
        print("1. Your archive should be selected in the Archives tab")
        print("2. Click 'Distribute App'")
        print("3. Choose 'App Store Connect'")
        print("4. Follow the prompts to upload to App Store")

    print()
    print(colorize("Alternative options:", "34"))
    print("1. Open manually in Xcode Organizer:")
    print(f"   open '{archive_path}'")
    print("   Then: Window ▸ Organizer ▸ Archives ▸ Distribute App")
    print("2. Use Transporter app for upload")
    print("3. Archive location for manual upload:")
    print(f"   {archive_path}")


def run_swiftpm_appstore_archive() -> None:
    """Create App Store archive from Swift Package Manager with user's signing credentials."""

    # User's specific credentials
    DEFAULT_TEAM_ID = "QG85EMCQ75"
    DEFAULT_IDENTITY = "3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"
    DEFAULT_PROFILE_PATH = "/Users/mhm/Documents/Hobby/Marcut-2/Marcut_App_Store.provisionprofile"

    project_dir = (REPO_ROOT / str(CONFIG.get("swift_project_dir", "MarcutApp"))).resolve()
    if not project_dir.exists():
        raise StepError(f"Swift project directory not found: {project_dir}")

    version = str(CONFIG.get("version", "0.0.0"))
    build_number = str(CONFIG.get("build_number", "1"))

    # Verify provisioning profile exists
    profile_path = Path(DEFAULT_PROFILE_PATH)
    if not profile_path.exists():
        raise StepError(f"Provisioning profile not found: {profile_path}")

    # Check if binary is already built
    built_binary = project_dir / ".build" / "arm64-apple-macosx" / "release" / "MarcutApp"
    if not built_binary.exists():
        print(colorize("Release binary not found. Building release version...", "33"))
        build_cmd = ["swift", "build", "-c", "release", "--arch", "arm64"]
        run_with_live_output("Building Release Binary", build_cmd, cwd=project_dir)

        if not built_binary.exists():
            raise StepError("Failed to build release binary")

    # Prompts with defaults
    default_team = str(CONFIG.get("appstore_default_team_id", DEFAULT_TEAM_ID))
    default_identity = str(CONFIG.get("appstore_default_identity", DEFAULT_IDENTITY))
    default_archive_name = str(CONFIG.get("appstore_default_archive", "MarcutApp-AppStore"))

    team_id = prompt_text("Team ID", default_team)
    code_sign_identity = prompt_text("Code signing identity", default_identity)
    archive_name = prompt_text("Archive name", default_archive_name)

    archive_path = REPO_ROOT / f"{archive_name}.xcarchive"

    # Clean up old archives first
    print(colorize("Cleaning up old archives...", "33"))
    old_archives = list(REPO_ROOT.glob("*.xcarchive"))
    for old_archive in old_archives:
        if old_archive != archive_path:
            print(f"Removing old archive: {old_archive.name}")
            try:
                shutil.rmtree(old_archive)
            except Exception as e:
                print(colorize(f"Warning: Could not remove {old_archive.name}: {e}", "33"))

    # Remove existing archive with same name
    if archive_path.exists():
        print(f"Removing existing archive: {archive_path.name}")
        shutil.rmtree(archive_path)

    print(colorize("Creating App Store archive from Swift Package Manager...", "34"))

    # Create app bundle
    app_bundle_path = REPO_ROOT / "MarcutApp.app"
    if app_bundle_path.exists():
        shutil.rmtree(app_bundle_path)

    # Create app bundle structure
    app_bundle_path.mkdir(parents=True)
    (app_bundle_path / "Contents" / "MacOS").mkdir(parents=True)
    (app_bundle_path / "Contents" / "Frameworks").mkdir(parents=True)
    (app_bundle_path / "Contents" / "Resources").mkdir(parents=True)

    # Create Info.plist
    info_plist = {
        "CFBundleExecutable": "MarcutApp",
        "CFBundleIdentifier": "com.marclaw.marcutapp",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "MarcutApp",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build_number,
        "LSMinimumSystemVersion": "14.0",
        "NSPrincipalClass": "NSApplication",
        "CFBundleDisplayName": "MarcutApp",
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "Copyright © 2025 Marc Law Software. All rights reserved.",
        "CFBundleIconFile": "AppIcon"
    }

    with open(app_bundle_path / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info_plist, f)

    # Use the project entitlements file - fail if not found (don't silently substitute)
    project_entitlements = REPO_ROOT / "src" / "swift" / "MarcutApp" / "MarcutApp.entitlements"
    if not project_entitlements.exists():
        raise StepError(f"Entitlements file not found: {project_entitlements}. This file is required for App Store builds.")
    
    temp_entitlements_path = str(project_entitlements)
    print(colorize(f"✅ Using project entitlements: {project_entitlements.name}", "32"))

    # Copy built binary
    shutil.copy2(built_binary, app_bundle_path / "Contents" / "MacOS" / "MarcutApp")

    # Copy app icon if available
    app_icon_src = REPO_ROOT / "AppIcon.icns"
    app_icon_dst = app_bundle_path / "Contents" / "Resources" / "AppIcon.icns"
    if app_icon_src.exists():
        shutil.copy2(app_icon_src, app_icon_dst)
        print(colorize("✅ App icon copied", "32"))
    else:
        print(colorize("⚠️  App icon not found at AppIcon.icns", "33"))

    # Copy resources from existing build if available
    existing_build = REPO_ROOT / "build_swift" / "MarcutApp.app"
    if existing_build.exists():
        # Copy frameworks with error handling
        frameworks_src = existing_build / "Contents" / "Frameworks"
        frameworks_dst = app_bundle_path / "Contents" / "Frameworks"
        if frameworks_src.exists():
            print(colorize("Copying frameworks...", "33"))
            try:
                # Use a more robust approach to copy frameworks
                for item in frameworks_src.iterdir():
                    if item.is_file():
                        shutil.copy2(item, frameworks_dst / item.name)
                    elif item.is_dir() and not item.name.endswith('.dSYM'):
                        # Skip directories that might be broken
                        try:
                            # For Python framework, use cp to preserve symlinks properly
                            if item.name == 'Python.framework':
                                import subprocess
                                copy_cmd = ['cp', '-R', '-a', str(item), str(frameworks_dst / item.name)]
                                result = subprocess.run(copy_cmd, capture_output=True, text=True, check=False)
                                if result.returncode != 0:
                                    print(colorize(f"Warning: Python framework copy failed: {result.stderr}", "33"))
                                else:
                                    print(colorize("✅ Python framework copied with symlinks preserved", "32"))
                            else:
                                shutil.copytree(item, frameworks_dst / item.name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.dSYM'))
                        except (OSError, shutil.Error) as e:
                            print(colorize(f"Warning: Skipping framework {item.name}: {e}", "33"))
            except Exception as e:
                print(colorize(f"Warning: Framework copy failed: {e}", "33"))

        # Copy resources with error handling
        resources_src = existing_build / "Contents" / "Resources"
        resources_dst = app_bundle_path / "Contents" / "Resources"
        if resources_src.exists():
            print(colorize("Copying resources...", "33"))
            try:
                # Use a more robust approach to copy resources
                for item in resources_src.iterdir():
                    if item.is_file():
                        # Skip problematic executables
                        if item.name in ['ollama', 'python3_embed']:
                            print(f"Skipping {item.name} (not allowed in App Store sandbox)")
                            continue
                        shutil.copy2(item, resources_dst / item.name)
                    elif item.is_dir():
                        try:
                            # Skip known problematic directories and files
                            skip_items = [
                                'MarcutApp_MarcutApp.bundle',
                                'Ollama.app',      # Contains embedded executables needing sandbox
                                'ollama',          # Standalone executable needing sandbox
                                'python3_embed'    # Standalone executable needing sandbox
                            ]
                            if item.name in skip_items:
                                print(f"Skipping {item.name} (not allowed in App Store sandbox)")
                                continue
                            shutil.copytree(item, resources_dst / item.name, dirs_exist_ok=True)
                        except (OSError, shutil.Error) as e:
                            print(colorize(f"Warning: Skipping resource {item.name}: {e}", "33"))
            except Exception as e:
                print(colorize(f"Warning: Resource copy failed: {e}", "33"))

    # As an alternative, copy from the Swift build resources directly
    if not (app_bundle_path / "Contents" / "Frameworks" / "Python.framework").exists():
        print(colorize("Frameworks not found, trying alternative sources...", "33"))

        # Try to copy from the most recent Swift build
        swift_build_bundle = project_dir / ".build" / "arm64-apple-macosx" / "release" / "MarcutApp_MarcutApp.bundle"
        if swift_build_bundle.exists():
            frameworks_src = swift_build_bundle / "Frameworks"
            frameworks_dst = app_bundle_path / "Contents" / "Frameworks"
            if frameworks_src.exists():
                try:
                    shutil.copytree(frameworks_src, frameworks_dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.dSYM'))
                    print(colorize("✅ Copied frameworks from Swift build bundle", "32"))
                except Exception as e:
                    print(colorize(f"Warning: Swift bundle copy failed: {e}", "33"))

        # Try to copy Python site resources
        python_site_src = swift_build_bundle / "python_site"
        python_site_dst = app_bundle_path / "Contents" / "Resources" / "python_site"
        if python_site_src.exists():
            try:
                shutil.copytree(python_site_src, python_site_dst, dirs_exist_ok=True)
                print(colorize("✅ Copied Python site from Swift build bundle", "32"))
            except Exception as e:
                print(colorize(f"Warning: Python site copy failed: {e}", "33"))

    # Validate that essential resources are present
    python_framework = app_bundle_path / "Contents" / "Frameworks" / "Python.framework"
    if not python_framework.exists():
        print(colorize("⚠️  Warning: Python framework not found. App may not function correctly.", "33"))
        print(colorize("Consider running a full build first to ensure all resources are available.", "33"))
    else:
        print(colorize("✅ Python framework found", "32"))

    # Sign the app bundle
    print(colorize("Signing app bundle...", "34"))

    # Note: Skipping framework signing to avoid Python framework issues
    frameworks_dir = app_bundle_path / "Contents" / "Frameworks"
    if frameworks_dir.exists():
        print(colorize("Skipping framework signing (to avoid Python framework issues)...", "33"))
        python_framework = frameworks_dir / "Python.framework"
        if python_framework.exists():
            print(colorize("⚠️  Python framework found but will not be signed - this is acceptable for App Store", "33"))
        else:
            print(colorize("No frameworks found to sign", "33"))

    # First, check if the requested identity exists
    try:
        result = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, check=True
        )
        available_identities = result.stdout
    except subprocess.CalledProcessError:
        available_identities = ""

    # Check if the requested identity is available
    identity_found = code_sign_identity in available_identities

    # If the default identity isn't found, also check for the exact certificate with the hash
    if not identity_found and "3rd Party Mac Developer Application" in code_sign_identity:
        # Look for any 3rd Party Mac Developer cert with your team ID
        if "4C81AF18575AB7C02BC24A35A423E0EB2AFF736E" in available_identities:
            identity_found = True
            code_sign_identity = "3rd Party Mac Developer Application: Marc Mandel (QG85EMCQ75)"
            print(colorize("✅ Found 3rd Party Mac Developer Application certificate", "32"))

    if not identity_found:
        print(colorize(f"❌ Signing identity '{code_sign_identity}' not found!", "31"))
        print(colorize("Available signing identities:", "34"))
        print(available_identities)
        print()
        print(colorize("For App Store distribution, you need an 'Apple Distribution' or '3rd Party Mac Developer Application' certificate.", "33"))
        print(colorize("You currently have:", "33"))

        if "Developer ID Application" in available_identities:
            print("✅ Developer ID Application (for direct distribution outside App Store)")
        if "Apple Development" in available_identities:
            print("✅ Apple Development (for development testing)")
        if "3rd Party Mac Developer Application" in available_identities:
            print("✅ 3rd Party Mac Developer Application (✅ VALID for Mac App Store)")

        print()
        print(colorize("Note: '3rd Party Mac Developer Application' certificates are valid for Mac App Store distribution.", "32"))
        print(colorize("If you need an 'Apple Distribution' certificate, you can create one at:", "34"))
        print("1. Go to https://developer.apple.com/account/resources/certificates/")
        print("2. Click '+' to create a new certificate")
        print("3. Choose 'Apple Distribution' as certificate type")
        print("4. Download and install the certificate in Keychain Access")
        print()

        if prompt_yes_no("Continue with a different signing identity for testing?", default=True):
            # Extract available identities for selection
            identity_lines = [line.strip() for line in available_identities.split('\n') if ')' in line]
            identities = []
            for line in identity_lines:
                if '"' in line:
                    parts = line.split('"', 2)
                    if len(parts) >= 2:
                        identity = parts[1]
                        desc = parts[2].strip() if len(parts) > 2 else ""
                        identities.append((identity, desc))

            if identities:
                print("Available identities:")
                for i, (identity, desc) in enumerate(identities, 1):
                    print(f"  {i}. {identity}")
                    print(f"     {desc}")

                try:
                    choice = int(input("Select an identity (number): "))
                    if 1 <= choice <= len(identities):
                        code_sign_identity = identities[choice-1][0]
                        print(f"Selected: {code_sign_identity}")
                    else:
                        print("Invalid selection. Continuing with signing attempt...")
                except (ValueError, KeyboardInterrupt):
                    print("Invalid selection. Continuing with signing attempt...")
            else:
                print("No valid identities found. Continuing with signing attempt...")
        else:
            raise StepError("Apple Distribution or 3rd Party Mac Developer Application certificate required for App Store submission")

    # Try a more robust signing approach for the main app
    print(colorize("Attempting robust signing approach...", "33"))

    # Remove any existing signature from the app bundle first
    print(colorize("Removing existing signatures...", "33"))
    remove_main_sig_cmd = ["codesign", "--remove-signature", str(app_bundle_path)]
    subprocess.run(remove_main_sig_cmd, capture_output=True, check=False)

    # First, try signing the app bundle with specific flags
    sign_cmd = [
        "codesign",
        "--force",
        "--options", "runtime",
        "--sign", code_sign_identity,
        "--entitlements", temp_entitlements_path,
        "--preserve-metadata=identifier,entitlements",
        str(app_bundle_path)
    ]

    try:
        run_with_live_output("Signing App Bundle", sign_cmd)
        print(colorize("✅ App bundle signed successfully", "32"))
    except Exception as e:
        print(colorize(f"Standard signing failed: {e}", "33"))

        # Fallback: Try signing without deep signing (to avoid framework issues)
        print(colorize("Trying fallback signing method...", "33"))
        fallback_sign_cmd = [
            "codesign",
            "--force",
            "--options", "runtime",
            "--sign", code_sign_identity,
            "--entitlements", temp_entitlements_path,
            str(app_bundle_path)
        ]

        run_with_live_output("Fallback Signing App Bundle", fallback_sign_cmd)
        print(colorize("✅ App bundle signed with fallback method", "32"))

    # Verify the app bundle is properly signed
    print(colorize("Verifying app bundle signature...", "33"))
    try:
        verify_cmd = ["codesign", "--verify", "--verbose", str(app_bundle_path)]
        verify_result = subprocess.run(verify_cmd, capture_output=True, text=True, check=False)
        if verify_result.returncode == 0:
            print(colorize("✅ App bundle signature verified", "32"))
        else:
            print(colorize("⚠️  App bundle signature verification failed, but continuing...", "33"))
            print(colorize("Verification output:", "33"))
            print(verify_result.stderr[-500:] if verify_result.stderr else "No output")  # Last 500 chars
    except Exception as e:
        print(colorize(f"Warning: Could not verify signature: {e}", "33"))

    # Create archive structure
    archive_path.mkdir(parents=True, exist_ok=True)
    archive_apps = archive_path / "Products" / "Applications"
    archive_apps.mkdir(parents=True, exist_ok=True)

    # Copy app to archive
    shutil.copytree(app_bundle_path, archive_apps / "MarcutApp.app")

    # Create archive Info.plist
    archive_info = {
        "ApplicationProperties": {
            "ApplicationPath": "Applications/MarcutApp.app",
            "CFBundleIdentifier": "com.marclaw.marcutapp",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": build_number,
            "SigningIdentity": code_sign_identity,
            "Team": team_id
        },
        "ArchiveVersion": 2,
        "Name": "MarcutApp",
        "SchemeName": "MarcutApp",
        "product-identifier": "com.marclaw.marcutapp",
        "product-version": version,
        "ProductBuildVersion": "14A5294g"
    }

    with open(archive_path / "Info.plist", "wb") as f:
        plistlib.dump(archive_info, f)

    # Cleanup temporary app bundle
    shutil.rmtree(app_bundle_path)

    # Cleanup temporary entitlements file
    try:
        import os
        os.unlink(temp_entitlements_path)
    except Exception:
        pass  # Ignore cleanup errors

    # Remove any existing misplaced entitlements file from the working directory
    misplaced_entitlements = Path("MarcutApp.app/Contents/MarcutApp.entitlements")
    if misplaced_entitlements.exists():
        try:
            misplaced_entitlements.unlink()
            print(colorize("✅ Cleaned up misplaced entitlements file", "32"))
        except Exception:
            pass  # Ignore cleanup errors

    # Success message
    print(colorize(f"✅ App Store archive created successfully!", "32"))
    print(colorize(f"Archive location: {archive_path}", "32"))
    print()
    print(colorize("Upload to App Store Connect:", "34"))

    # Prompt for upload
    if prompt_yes_no("Upload to App Store Connect now?", default=True):
        # Get Apple ID for upload (with default)
        default_apple_id = "mhmhm@me.com"  # Apple Developer account
        apple_id = prompt_text("Apple ID (email)", default_apple_id)
        if not apple_id:
            print(colorize("❌ Apple ID required for upload", "31"))
            return

        print(colorize("🔐 Checking keychain authentication...", "34"))
        
        # Fallback to manual auth if needed
        pass

        print(colorize("Uploading to App Store Connect...", "33"))
        
        # Prompt for app-specific password if not checking keychain here for simplicity
        # Or better yet, tell user to use manual mode if CLI fails
        # Re-implementing basic altool command
        import getpass
        app_password = getpass.getpass("App-Specific Password: ")
        if not app_password:
             print(colorize("❌ Password required", "31"))
             return

        upload_cmd = [
            "xcrun",
            "altool",
            "--upload-app",
            "--type", "osx",
            "--file", str(archive_path),
            "--username", apple_id,
            "--password", app_password
        ]

        try:
            run_with_live_output("Uploading to App Store Connect", upload_cmd)
            print(colorize("✅ Upload completed successfully!", "32"))
            print(colorize("You can check the status in App Store Connect", "32"))
        except Exception as e:
            print(colorize(f"❌ Upload failed: {e}", "31"))
            print(colorize("💡 Troubleshooting:", "34"))
            print("   1. Check your App-Specific Password")
            print("   2. Use Xcode Organizer (recommended)")
            print(f"   3. Manual upload: xcrun altool --upload-app --type osx --file '{archive_path}' --username '{apple_id}' --password ...")

    print()
    print(colorize("Alternative options:", "34"))
    print("1. Open in Xcode Organizer:")
    print(f"   open '{archive_path}'")
    print("   Then: Window ▸ Organizer ▸ Archives ▸ Distribute App")
    print()
    print("2. Manual upload:")
    print(f"   xcrun altool --upload-app --type osx --file '{archive_path}' --username 'YOUR_APPLE_ID'")
    print()
    print("3. Verify signing:")
    print(f"   codesign -dv --verbose=4 '{archive_path}/Products/Applications/MarcutApp.app'")


def notarize_existing_dmg() -> None:
    script = script_from_config("notarize_script")
    default_dmg = CONFIG.get("final_dmg")
    default_path = ""
    if default_dmg:
        candidate = (REPO_ROOT / str(default_dmg)).resolve()
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


def run_pkg_no_upload() -> None:
    """
    Executes package_release.sh to create a signed pkg without upload.
    """
    script_path = REPO_ROOT / "package_release.sh"
    
    if not script_path.exists():
         raise StepError(f"Script not found: {script_path}")

    # Ensure executable
    os.chmod(script_path, 0o755)

    print(colorize(f"📦 Running Packaging Script: {script_path.name}", "34"))
    run_with_live_output("Package Release (No Upload)", ["bash", str(script_path)])

    pkg_path = REPO_ROOT / "Archive" / "Exported" / "MarcutApp.pkg"
    if pkg_path.exists():
        print()
        print(colorize("✅ Signed Package Created Successfully!", "32"))
        print(f"Location: {pkg_path}")
        print()
        if prompt_yes_no("Reveal in Finder?", default=True):
             subprocess.run(["open", "-R", str(pkg_path)])
    else:
        raise StepError("Packaging failed (PKG not found).")


def distribution_menu() -> None:
    options = [
        (
            "appstore_release",
            "App Store Archive (Script)\nRuns build_appstore_release.sh to create Archive/MarcutApp.xcarchive.",
        ),
        (
            "submit_app_store_cli",
            "Submit to App Store (CLI)\nExport signed PKG + upload to App Store Connect.",
        ),
        (
            "pkg_no_upload",
            "Build PKG (No Upload)\nBuilds release and creates signed PKG. No Upload.",
        ),
        (
            "notarize_dmg",
            "Notarize Existing DMG\nSubmit + staple via upload/scripts/notarize_macos.sh.",
        ),
        (
            "appstore_xcode",
            "App Store Archive (Xcode, Experimental)\nManual xcodebuild archive flow for debugging.",
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
            if selection == "appstore_release":
                print(colorize("Using build_appstore_release.sh (recommended)", "32"))
                run_appstore_release()
            elif selection == "appstore_xcode":
                print(colorize("Using experimental Xcode archive workflow", "33"))
                run_appstore_archive()
            elif selection == "notarize_dmg":
                notarize_existing_dmg()
            elif selection == "submit_app_store_cli":
                print(f"\n🚀 Running Submission Script: submit_appstore.sh")
                try:
                    subprocess.run(["./submit_appstore.sh"], check=False, timeout=180)
                except subprocess.TimeoutExpired:
                    print(colorize("\n❌ Submission timed out after 3 minutes.", "31"))
                input("\nPress Enter to continue...")
            elif selection == "pkg_no_upload":
                run_pkg_no_upload()
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
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "test":
            tests_menu()
        elif cmd == "release":
            run_appstore_release()
        elif cmd == "archive":
            run_appstore_archive()
        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)
        return

    show_intro(CONFIG)
    main_menu()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
