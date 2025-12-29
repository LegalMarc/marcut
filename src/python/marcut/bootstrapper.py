#!/usr/bin/env python3
"""Bootstrapper for Marcut - Handles first run setup and app launching"""

import os
import sys
import json
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
import site

def is_first_run():
    """Check if this is the first time running the app"""
    app_dir = Path.home() / ".marcut"
    config_path = app_dir / "config.json"
    
    # If no config exists, it's first run
    if not config_path.exists():
        return True
    
    try:
        with open(config_path) as f:
            config = json.load(f)
            return not config.get("installed", False)
    except:
        return True

def setup_python_path():
    """Add our lib directory to Python path"""
    app_dir = Path.home() / ".marcut"
    lib_dir = app_dir / "lib"
    
    if lib_dir.exists():
        # Add to Python path
        site.addsitedir(str(lib_dir))
        # Also add to env var for subprocesses
        current = os.environ.get("PYTHONPATH", "")
        if current:
            os.environ["PYTHONPATH"] = f"{lib_dir}:{current}"
        else:
            os.environ["PYTHONPATH"] = str(lib_dir)
            
def is_arm64():
    """Check if we're running natively on Apple Silicon"""
    return sys.platform == "darwin" and "arm64" in os.uname().machine

def ensure_arm64():
    """Ensure we're running native on Apple Silicon"""
    if sys.platform == "darwin" and "arm64" not in os.uname().machine:
        # We're running under Rosetta - re-exec under arm64
        executable = sys.executable
        if "/Resources/" in executable:
            # We're in an app bundle, use absolute path
            cmd = ["arch", "-arm64", executable] + sys.argv
        else:
            # We're running from source, use python3
            cmd = ["arch", "-arm64", "python3"] + sys.argv
            
        os.execvp(cmd[0], cmd)
        
def handle_first_run():
    """Run first-time setup wizard"""
    print("First run detected - launching setup wizard...")
    from marcut.native_setup import run_wizard
    run_wizard()
    
def run_app():
    """Run the main Marcut application"""
    print("Launching Marcut...")
    from marcut.gui import main
    main()
    
def main():
    """Main entry point"""
    # Force ARM64 on Apple Silicon
    ensure_arm64()
    
    # Add our lib dir to Python path
    setup_python_path()
    
    try:
        # Check for first run
        if is_first_run():
            handle_first_run()
        
        # Run main app
        run_app()
        
    except Exception as e:
        # Create a minimal Tk root for error dialog
        root = tk.Tk()
        root.withdraw()
        
        error_msg = "An error occurred while starting Marcut:\n\n"
        if "No module named" in str(e):
            error_msg += (
                str(e) + "\n\n"
                "This usually means the first-run setup did not complete properly.\n"
                "Try deleting ~/.marcut and launching again."
            )
        else:
            error_msg += str(e)
            
        messagebox.showerror("Marcut Error", error_msg)
        sys.exit(1)
        
if __name__ == "__main__":
    main()
