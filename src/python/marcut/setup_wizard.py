#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import sys
import os
import threading
import requests
from pathlib import Path
import json

class SetupWizard:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Marcut First-Run Setup")
        self.root.geometry("600x400")
        self.root.minsize(500, 400)
        
        # App paths
        self.app_dir = Path.home() / ".marcut"
        self.app_dir.mkdir(exist_ok=True)
        
        self.progress = None
        self.status_label = None
        self.setup_ui()
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Welcome text
        welcome = ttk.Label(
            main_frame,
            text="Welcome to Marcut!",
            font=("Helvetica", 24, "bold")
        )
        welcome.grid(row=0, column=0, pady=(0, 10))
        
        # Subtitle
        subtitle = ttk.Label(
            main_frame,
            text="One-time setup for Apple Silicon native performance",
            font=("Helvetica", 12),
            foreground="gray"
        )
        subtitle.grid(row=1, column=0, pady=(0, 20))
        
        # Installation steps
        steps_frame = ttk.LabelFrame(main_frame, text="Installation Steps", padding=10)
        steps_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        
        steps = [
            "✨ Install native Python packages (~50MB)",
            "🚀 Configure app directories",
            "🧠 Set up Ollama AI service"
        ]
        
        for i, step in enumerate(steps):
            ttk.Label(steps_frame, text=step).grid(
                row=i, column=0, sticky=tk.W, pady=2
            )
        
        # Status
        self.status_label = ttk.Label(
            main_frame,
            text="Ready to install...",
            font=("Helvetica", 10)
        )
        self.status_label.grid(row=3, column=0, pady=10)
        
        # Progress bar
        self.progress = ttk.Progressbar(
            main_frame,
            mode="indeterminate",
            length=300
        )
        self.progress.grid(row=4, column=0, pady=10)
        
        # Install button
        self.install_btn = ttk.Button(
            main_frame,
            text="Start Installation",
            command=self.start_installation
        )
        self.install_btn.grid(row=5, column=0, pady=10)
        
        # Configure grid
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
    def start_installation(self):
        self.install_btn.config(state="disabled")
        self.progress.start()
        threading.Thread(target=self.run_installation, daemon=True).start()
        
    def update_status(self, msg):
        self.status_label.config(text=msg)
        
    def run_installation(self):
        try:
            # 1. Create app directories
            self.update_status("Creating app directories...")
            lib_dir = self.app_dir / "lib"
            lib_dir.mkdir(exist_ok=True)
            
            # 2. Install Python packages to user directory
            self.update_status("Installing required packages...")
            requirements = [
                "python-docx>=1.1.0",
                "requests>=2.31.0",
                "numpy>=1.25.0",
                "rapidfuzz>=3.6.1",
                "regex>=2024.4.16",
                "tqdm>=4.66.0",
                "pydantic>=2.6.4",
                "dateparser>=1.2.0"
            ]
            
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(lib_dir)] + requirements,
                capture_output=True,
                text=True
            )
            
            if proc.returncode != 0:
                raise Exception(f"Failed to install packages:\n{proc.stderr}")
            
            # 3. Setup Ollama
            self.update_status("Setting up Ollama AI service...")
            ollama_path = self.setup_ollama()
            
            # 4. Create config file
            config = {
                "installed": True,
                "version": "0.2.2",
                "arch": "arm64",
                "python_path": sys.executable,
                "lib_dir": str(lib_dir),
                "ollama_path": ollama_path
            }
            
            with open(self.app_dir / "config.json", "w") as f:
                json.dump(config, f, indent=2)
            
            # Success!
            self.progress.stop()
            self.update_status("✅ Installation complete!")
            
            messagebox.showinfo(
                "Setup Complete",
                "Marcut is now ready to use!\n\n"
                "The AI model will be downloaded automatically when needed."
            )
            
            self.root.quit()
            
        except Exception as e:
            self.progress.stop()
            self.update_status("❌ Installation failed")
            messagebox.showerror(
                "Setup Failed",
                f"An error occurred during installation:\n{str(e)}"
            )
            self.install_btn.config(state="normal")
    
    def setup_ollama(self):
        """Setup Ollama service"""
        # Check if we have embedded Ollama
        bundle_exe = os.environ.get('_MEIPASS')
        if bundle_exe:
            embedded_ollama = Path(bundle_exe).parent / "Resources" / "ollama" / "ollama"
            if embedded_ollama.exists():
                # Copy to user directory for persistent use
                ollama_dir = self.app_dir / "bin"
                ollama_dir.mkdir(exist_ok=True)
                user_ollama = ollama_dir / "ollama"
                
                import shutil
                shutil.copy2(embedded_ollama, user_ollama)
                os.chmod(user_ollama, 0o755)
                return str(user_ollama)
        
        # Fall back to system Ollama or download
        system_ollama = subprocess.run(["which", "ollama"], capture_output=True, text=True)
        if system_ollama.returncode == 0:
            return system_ollama.stdout.strip()
            
        # If no Ollama found, we'll download it on demand later
        return None
            
    def run(self):
        self.root.mainloop()
        
        
def run_wizard():
    wizard = SetupWizard()
    wizard.run()
