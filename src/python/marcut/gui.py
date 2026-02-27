#!/usr/bin/env python3
"""
Minimal GUI for Marcut - Document Redaction Tool
This provides a simple drag-and-drop interface for redacting DOCX files.
"""

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import threading
import subprocess
from pathlib import Path
import json
import tempfile
from datetime import datetime
import time
import requests
from marcut.network_utils import normalize_ollama_base_url, ollama_cli_host_arg

# Add parent directory to path for imports when running standalone
if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ollama_base_url() -> str:
    return normalize_ollama_base_url(loopback_only=True)


def _ollama_host_arg() -> str:
    return ollama_cli_host_arg(_ollama_base_url())

try:
    from marcut.pipeline import run_redaction_enhanced
    from marcut.preflight import check_ollama_installed, check_ollama_running, check_model_available
    from marcut.progress import create_progress_callback, ProgressUpdate
    from marcut.progress_widgets import EnhancedProgressFrame
    IMPORTS_SUCCESS = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_SUCCESS = False
    # Fallback implementations for testing
    def run_redaction_enhanced(*args, **kwargs):
        return 1
    def check_ollama_installed():
        return False
    def check_ollama_running():
        return False
    def check_model_available(model_name):
        return False
    def create_progress_callback(func):
        return func
    class ProgressUpdate:
        def __init__(self):
            pass
    class EnhancedProgressFrame(tk.Frame):
        def __init__(self, parent, **kwargs):
            super().__init__(parent, **kwargs)
        def update_progress(self, *args, **kwargs):
            pass
        def reset(self):
            pass


class MarcutGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Marcut - Document Redaction")
        self.root.geometry("600x500")
        
        # Set macOS-specific options
        if sys.platform == "darwin":
            self.root.createcommand('tk::mac::ShowPreferences', self.show_preferences)
            
        # Variables
        self.file_path = None
        self.ollama_process = None
        self.model_name = "llama3.1:8b"
        
        self.setup_ui()
        # Defer setup so the window can render first
        self.root.after(0, self.start_bootstrap)

    def start_bootstrap(self):
        """Kick off startup checks on a background thread."""
        threading.Thread(target=self.bootstrap_startup, daemon=True).start()

    def _ui_call(self, func, *args, **kwargs):
        """Run UI updates on the main thread."""
        if threading.current_thread() is threading.main_thread():
            func(*args, **kwargs)
        else:
            self.root.after(0, lambda: func(*args, **kwargs))

    def _set_label(self, label, text):
        self._ui_call(label.config, text=text)

    def _set_button_state(self, button, state):
        self._ui_call(button.config, state=state)

    def _show_info(self, title, message):
        self._ui_call(messagebox.showinfo, title, message)

    def _show_error(self, title, message):
        self._ui_call(messagebox.showerror, title, message)

    def _ask_yes_no(self, title, message, **kwargs):
        result = {"value": False}
        event = threading.Event()

        def ask():
            result["value"] = messagebox.askyesno(title, message, **kwargs)
            event.set()

        self.root.after(0, ask)
        event.wait()
        return result["value"]
        
    def setup_ui(self):
        """Create the user interface"""
        # Configure root window
        self.root.minsize(500, 400)
        
        # Main container (use tk widgets with explicit colors to avoid blank UI)
        bg = "#FFFFFF"
        fg = "#111111"
        subfg = "#555555"
        self.root.configure(bg=bg)
        
        main_frame = tk.Frame(self.root, bg=bg)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=20, pady=20)
        
        # Title
        title_label = tk.Label(main_frame, text="Marcut Document Redaction", 
                               font=('Helvetica', 18, 'bold'), bg=bg, fg=fg)
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 8), sticky=tk.W)
        
        # Subtitle
        subtitle_label = tk.Label(main_frame, 
                                  text="Legal Document Redaction with AI",
                                  font=('Helvetica', 10), bg=bg, fg=subfg)
        subtitle_label.grid(row=1, column=0, columnspan=2, pady=(0, 16), sticky=tk.W)
        
        # Drop zone frame
        self.drop_frame = tk.LabelFrame(main_frame, text="Select Document", bg=bg, fg=fg, bd=1, padx=20, pady=20)
        self.drop_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        
        # Drop zone content with better styling
        drop_content = tk.Frame(self.drop_frame, bg=bg)
        drop_content.pack(expand=True, fill='both')
        
        self.drop_label = tk.Label(drop_content, 
                                   text="📄 Click here to select a DOCX file\n\nSupported: Legal contracts, agreements,\ncompliance documents",
                                   font=('Helvetica', 12),
                                   justify='center', bg=bg, fg=fg)
        self.drop_label.pack(expand=True, pady=30)
        
        # File info label
        self.file_info = tk.Label(main_frame, text="No file selected", 
                                  bg=bg, fg=subfg)
        self.file_info.grid(row=3, column=0, columnspan=2, pady=5)
        
        # Status frame
        status_frame = tk.LabelFrame(main_frame, text="System Status", bg=bg, fg=fg, bd=1, padx=10, pady=10)
        status_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Status labels
        self.ollama_status = tk.Label(status_frame, text="⏳ Checking AI service...", bg=bg, fg=subfg)
        self.ollama_status.grid(row=0, column=0, sticky=tk.W, pady=2)
        
        self.model_status = tk.Label(status_frame, text="⏳ Checking AI model...", bg=bg, fg=subfg)
        self.model_status.grid(row=1, column=0, sticky=tk.W, pady=2)
        
        # Enhanced Progress Frame
        self.enhanced_progress = EnhancedProgressFrame(main_frame, bg=bg)
        self.enhanced_progress.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        
        # Keep old progress components for backwards compatibility
        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress_text = tk.Label(main_frame, text="Ready to redact documents", bg=bg, fg="#0A7D00")
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=7, column=0, columnspan=2, pady=20)
        
        self.select_button = ttk.Button(button_frame, text="Select Document", 
                                       command=self.select_file)
        self.select_button.pack(side=tk.LEFT, padx=5)
        
        self.redact_button = ttk.Button(button_frame, text="Redact Document", 
                                       command=self.start_redaction, state='disabled')
        self.redact_button.pack(side=tk.LEFT, padx=5)
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)
        
        # Bind click event to drop zone
        self.drop_frame.bind("<Button-1>", lambda e: self.select_file())
        self.drop_label.bind("<Button-1>", lambda e: self.select_file())
        
    def bootstrap_startup(self):
        """Synchronously ensure Ollama service is running and the model is available.
        This runs during startup so the user gets deterministic behavior.
        """
        # Resolve embedded Ollama binary path
        self.ollama_bin = self.get_ollama_binary_path()
        # Always prefer embedded binary; do not rely on PATH
        if not os.path.isfile(self.ollama_bin) or not os.access(self.ollama_bin, os.X_OK):
            # Fallback to system, but update status clearly
            self._set_label(self.ollama_status, "⚠️ Embedded AI not found; checking system Ollama…")
            self.ollama_bin = 'ollama'
        
        # Ensure service is running
        self._set_label(self.ollama_status, "⏳ Starting AI service…")
        self.ensure_service_running_sync()
        
        # After service is running, verify model
        self._set_label(self.model_status, f"⏳ Checking model {self.model_name}…")
        if self.check_model_api():
            self._set_label(self.model_status, f"✅ Model {self.model_name} ready")
            self._set_label(self.ollama_status, "✅ AI service running")
            self._set_label(self.progress_text, "Ready to redact documents")
            self._set_button_state(self.redact_button, 'normal')
            return
        
        # Prompt and download if missing
        self.prompt_download_model_sync()
        # Re-check and update state
        if self.check_model_api():
            self._set_label(self.model_status, f"✅ Model {self.model_name} ready")
            self._set_label(self.progress_text, "Ready to redact documents")
            self._set_button_state(self.redact_button, 'normal')
        else:
            self._set_label(self.model_status, f"❌ Model {self.model_name} not available")
            self._set_button_state(self.redact_button, 'disabled')
        
    def service_running_api(self) -> bool:
        try:
            r = requests.get(f"{_ollama_base_url()}/api/tags", timeout=2)
            return r.status_code == 200
        except Exception:
            return False
        
    def ensure_service_running_sync(self):
        """Start Ollama serve with embedded binary if not already running."""
        if self.service_running_api():
            self._set_label(self.ollama_status, "✅ AI service running")
            return
        
        # Use ~/.marcut/models for model cache
        models_dir = os.path.join(os.path.expanduser('~'), '.marcut', 'models')
        os.makedirs(models_dir, exist_ok=True)
        env = os.environ.copy()
        env['OLLAMA_MODELS'] = models_dir
        
        try:
            # Start service
            self.ollama_process = subprocess.Popen([self.ollama_bin, 'serve'],
                                                  stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL,
                                                  env=env)
        except Exception as e:
            self._set_label(self.ollama_status, "❌ Failed to start AI service")
            self._show_error("Error", f"Could not start AI service:\n{e}")
            return
        
        # Wait up to 30s for readiness, keeping UI responsive
        for _ in range(60):
            if self.service_running_api():
                self._set_label(self.ollama_status, "✅ AI service running")
                return
            time.sleep(0.5)
        self._set_label(self.ollama_status, "❌ AI service did not start")
        
    def check_model_api(self) -> bool:
        """Check via API if the required model is present."""
        try:
            r = requests.get(f"{_ollama_base_url()}/api/tags", timeout=5)
            if r.status_code != 200:
                return False
            data = r.json() or {}
            names = [m.get('name','') for m in data.get('models', [])]
            base = self.model_name.split(':')[0]
            return any(self.model_name in n or n.startswith(base) for n in names)
        except Exception:
            return False
        
    def prompt_download_model_sync(self):
        """Prompt user and, if accepted, download model synchronously using embedded ollama."""
        ok = self._ask_yes_no(
            "Download AI Model",
            f"Marcut requires the {self.model_name} model (~4.7 GB).\n\n"
            "This is a one-time download stored locally at ~/.marcut/models.\n\n"
            "Proceed to download now?",
            icon='question'
        )
        if not ok:
            self._set_label(self.model_status, "❌ Model download cancelled")
            return
        
        # Show progress spinner during pull
        self._ui_call(self.progress.start)
        self._set_label(self.progress_text, f"Downloading {self.model_name}…")
        self._set_label(self.model_status, "📥 Downloading model…")
        
        env = os.environ.copy()
        env['OLLAMA_MODELS'] = os.path.join(os.path.expanduser('~'), '.marcut', 'models')
        env['OLLAMA_HOST'] = _ollama_host_arg()
        try:
            result = subprocess.run([self.ollama_bin, 'pull', self.model_name],
                                    capture_output=True, text=True, env=env)
            if result.returncode == 0:
                self._set_label(self.model_status, f"✅ Model {self.model_name} ready")
                self._show_info("Download Complete", f"Successfully downloaded {self.model_name}.")
            else:
                self._set_label(self.model_status, "❌ Download failed")
                self._show_error("Download Failed", result.stderr or "Unknown error")
        except Exception as e:
            self._set_label(self.model_status, "❌ Download error")
            self._show_error("Download Error", str(e))
        finally:
            self._ui_call(self.progress.stop)
            self._set_label(self.progress_text, "")
        
    def get_ollama_binary_path(self):
        """Find the Ollama binary (embedded or system)"""
        # Try PyInstaller macOS app layout first
        try:
            exe = sys.executable  # In a bundled app, this is .../Contents/MacOS/Marcut
            resources_dir = os.path.abspath(os.path.join(os.path.dirname(exe), '..', 'Resources'))
            cand = os.path.join(resources_dir, 'ollama', 'ollama')
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                print(f"Found embedded Ollama (Resources): {cand}")
                return cand
        except Exception as e:
            print(f"Embedded search (Resources) failed: {e}")
        
        # Check for embedded Ollama near this file (when running from source)
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            potential_paths = [
                os.path.join(current_dir, '..', '..', 'Resources', 'ollama', 'ollama'),
                os.path.join(current_dir, '..', 'Resources', 'ollama', 'ollama')
            ]
            for path in potential_paths:
                abs_path = os.path.abspath(path)
                if os.path.isfile(abs_path) and os.access(abs_path, os.X_OK):
                    print(f"Found embedded Ollama near source: {abs_path}")
                    return abs_path
        except Exception as e:
            print(f"Error looking for embedded Ollama: {e}")
        
        # Fallback to system ollama
        return 'ollama'
        
    def start_ollama_service(self):
        """Start Ollama service in background"""
        try:
            ollama_binary = self.get_ollama_binary_path()
            
            # Set up environment for embedded models directory
            env = os.environ.copy()
            if 'embedded' in ollama_binary.lower() or 'resources' in ollama_binary.lower():
                # We're using embedded Ollama, set models directory
                app_resources = os.path.dirname(os.path.dirname(ollama_binary))
                models_dir = os.path.join(app_resources, 'models')
                os.makedirs(models_dir, exist_ok=True)
                env['OLLAMA_MODELS'] = models_dir
                print(f"Using embedded models directory: {models_dir}")
            
            # Start Ollama service
            self.ollama_process = subprocess.Popen([ollama_binary, 'serve'],
                                                  stdout=subprocess.DEVNULL,
                                                  stderr=subprocess.DEVNULL,
                                                  env=env)
            # Wait a moment for service to start
            import time
            time.sleep(3)
            
            if check_ollama_running():
                self.ollama_status.config(text="✅ Ollama running")
                # Now check model
                if check_model_available(self.model_name):
                    self.model_status.config(text=f"✅ Model {self.model_name} ready")
                else:
                    self.model_status.config(text=f"📥 Model {self.model_name} not found")
                    # Automatically offer to download on first run
                    self.root.after(1000, self.download_model)  # Small delay for UI to settle
            else:
                self.ollama_status.config(text="❌ Failed to start Ollama")
        except Exception as e:
            self.ollama_status.config(text="❌ Error starting Ollama")
            print(f"Error starting Ollama: {e}")
            
    def download_model(self):
        """Download the required model with user confirmation"""
        # Ask user for permission to download
        response = messagebox.askyesno(
            "Download AI Model",
            f"Marcut requires the {self.model_name} AI model (~4.7 GB) for document redaction.\n\n"
            "This is a one-time download that will be cached locally.\n\n"
            "Would you like to download it now?\n\n"
            "Note: This may take 5-15 minutes depending on your internet connection.",
            icon='question'
        )
        
        if not response:
            self.model_status.config(text="❌ Model download cancelled")
            messagebox.showinfo(
                "Model Required",
                "The AI model is required for document redaction.\n"
                "You can download it later by restarting the application."
            )
            return
            
        def download():
            try:
                self.progress.start()
                self.progress_text.config(text=f"Downloading {self.model_name} (~4.7 GB, please wait...)")
                
                # Run ollama pull command
                result = subprocess.run(['ollama', 'pull', self.model_name],
                                      capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.model_status.config(text=f"✅ Model {self.model_name} ready")
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Download Complete",
                        f"Successfully downloaded {self.model_name}!\n\n"
                        "Marcut is now ready for document redaction."
                    ))
                else:
                    self.model_status.config(text=f"❌ Failed to download {self.model_name}")
                    self.root.after(0, lambda: messagebox.showerror(
                        "Download Failed",
                        f"Failed to download {self.model_name}.\n\n"
                        "Please check your internet connection and try again."
                    ))
                    
            except Exception as e:
                self.model_status.config(text=f"❌ Error downloading model")
                self.root.after(0, lambda: messagebox.showerror(
                    "Download Error",
                    f"An error occurred while downloading the model:\n{str(e)}"
                ))
                print(f"Error downloading model: {e}")
            finally:
                self.progress.stop()
                self.progress_text.config(text="")
                
        threading.Thread(target=download, daemon=True).start()
        
    def select_file(self):
        """Open file dialog to select a DOCX file"""
        file_path = filedialog.askopenfilename(
            title="Select DOCX Document",
            filetypes=[("Word Documents", "*.docx"), ("All Files", "*.*")]
        )
        
        if file_path:
            self.file_path = file_path
            filename = os.path.basename(file_path)
            self.file_info.config(text=f"Selected: {filename}")
            self.drop_label.config(text=f"📄 {filename}")
            self.redact_button.config(state='normal')
            
    def start_redaction(self):
        """Start the redaction process in a background thread"""
        if not self.file_path:
            messagebox.showwarning("No File", "Please select a document first")
            return
            
        # Disable buttons during processing
        self.redact_button.config(state='disabled')
        self.select_button.config(state='disabled')
        
        # Reset and show enhanced progress
        self.enhanced_progress.reset()
        
        # Start progress bar (for backwards compatibility)
        self.progress.start()
        self.progress_text.config(text="Redacting document...")
        
        # Run redaction in background thread
        threading.Thread(target=self.run_redaction, daemon=True).start()
        
    def run_redaction(self):
        """Perform the actual redaction"""
        try:
            # Prepare output paths
            input_path = Path(self.file_path)
            output_dir = input_path.parent
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = input_path.stem
            
            output_path = output_dir / f"{base_name}_redacted_{timestamp}.docx"
            report_path = output_dir / f"{base_name}_redacted_{timestamp}.json"
            
            # Update progress
            self.progress_text.config(text="Processing document with AI model...")
            
            # Create progress callback for enhanced UI
            def update_progress_ui(update: ProgressUpdate):
                """Update the enhanced progress UI safely from background thread."""
                try:
                    self.root.after(0, lambda: self.enhanced_progress.update_progress(
                        update.phase_progress,
                        update.overall_progress,
                        update.phase_name,
                        update.estimated_remaining,
                        update.message
                    ))
                except Exception as e:
                    print(f"Progress UI update error: {e}")
            
            progress_callback = create_progress_callback(update_progress_ui)
            
            # Run enhanced redaction pipeline
            result = run_redaction_enhanced(
                input_path=str(input_path),
                output_path=str(output_path),
                report_path=str(report_path),
                model_id=self.model_name,
                chunk_tokens=1000,
                overlap=150,
                temperature=0.1,
                seed=42,
                debug=False,
                progress_callback=progress_callback
            )
            
            if result == 0:
                # Success
                self.progress.stop()
                self.progress_text.config(text="✅ Redaction complete!")
                
                # Show success message
                messagebox.showinfo(
                    "Success",
                    f"Document redacted successfully!\n\n"
                    f"Output saved to:\n{output_path.name}\n\n"
                    f"Report saved to:\n{report_path.name}"
                )
                
                # Open the folder containing the output
                if sys.platform == "darwin":
                    subprocess.run(["open", "-R", str(output_path)])
                    
            else:
                # Error
                self.progress.stop()
                self.progress_text.config(text="❌ Redaction failed")
                messagebox.showerror("Error", "Redaction failed. Please check the logs.")
                
        except Exception as e:
            self.progress.stop()
            self.progress_text.config(text="❌ Error during redaction")
            messagebox.showerror("Error", f"An error occurred:\n{str(e)}")
            
        finally:
            # Re-enable buttons
            self.redact_button.config(state='normal')
            self.select_button.config(state='normal')
            self.progress_text.config(text="")
            
    def setup_embedded_ollama(self):
        """Set up embedded Ollama when standard detection fails"""
        print(f"[DEBUG] Setting up embedded Ollama...")
        
        # Try to find and start embedded Ollama directly
        ollama_binary = self.get_ollama_binary_path()
        
        if ollama_binary != 'ollama':  # We found an embedded binary
            try:
                print(f"[DEBUG] Found embedded Ollama at: {ollama_binary}")
                self.ollama_status.config(text="✅ Embedded Ollama found")
                
                # Check if already running by trying to connect
                import requests
                try:
                    response = requests.get(f"{_ollama_base_url()}/api/tags", timeout=2)
                    if response.status_code == 200:
                        print(f"[DEBUG] Ollama already running")
                        self.ollama_status.config(text="✅ Ollama running")
                        self.check_embedded_model()
                        return
                except requests.exceptions.RequestException:
                    pass
                
                # Start embedded Ollama
                print(f"[DEBUG] Starting embedded Ollama service...")
                self.ollama_status.config(text="⚠️ Starting AI service...")
                
                # Set up environment
                env = os.environ.copy()
                models_dir = os.path.join(os.path.expanduser('~'), '.marcut', 'models')
                os.makedirs(models_dir, exist_ok=True)
                env['OLLAMA_MODELS'] = models_dir
                env['OLLAMA_HOST'] = _ollama_host_arg()
                
                print(f"[DEBUG] Using models directory: {models_dir}")
                
                # Start the service
                self.ollama_process = subprocess.Popen(
                    [ollama_binary, 'serve'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env
                )
                
                # Wait for service to start
                print(f"[DEBUG] Waiting for Ollama service to start...")
                for i in range(15):
                    time.sleep(1)
                    try:
                        response = requests.get(f"{_ollama_base_url()}/api/tags", timeout=1)
                        if response.status_code == 200:
                            print(f"[DEBUG] Ollama service started successfully")
                            self.ollama_status.config(text="✅ Ollama running")
                            self.check_embedded_model()
                            return
                    except requests.exceptions.RequestException:
                        pass
                
                print(f"[DEBUG] Ollama service failed to start")
                self.ollama_status.config(text="❌ Failed to start Ollama")
                
            except Exception as e:
                print(f"[DEBUG] Error setting up embedded Ollama: {e}")
                self.ollama_status.config(text="❌ Error starting Ollama")
        else:
            print(f"[DEBUG] No embedded Ollama found")
            self.show_setup_wizard()
    
    def check_embedded_model(self):
        """Check if the model is available when using embedded Ollama"""
        try:
            import requests
            response = requests.get(f"{_ollama_base_url()}/api/tags", timeout=5)
            if response.status_code == 200:
                models_data = response.json()
                available_models = [model['name'] for model in models_data.get('models', [])]
                print(f"[DEBUG] Available models: {available_models}")
                
                # Check for exact match or prefix match
                model_found = any(
                    self.model_name in model or model.startswith(self.model_name.split(':')[0]) 
                    for model in available_models
                )
                
                if model_found:
                    self.model_status.config(text=f"✅ Model {self.model_name} ready")
                else:
                    self.model_status.config(text=f"📥 Model {self.model_name} not found")
                    # Show setup wizard for model download
                    self.root.after(1000, self.show_setup_wizard)
        except Exception as e:
            print(f"[DEBUG] Error checking models: {e}")
            self.model_status.config(text="❌ Error checking model")
    
    def show_setup_wizard(self):
        """Show the first-run setup wizard for model download"""
        print(f"[DEBUG] Showing setup wizard")
        
        # Create a professional welcome dialog
        response = messagebox.askyesno(
            "Welcome to Marcut!",
            f"🎉 Welcome to Marcut Document Redaction!\n\n"
            f"To get started, Marcut needs to download the AI model ({self.model_name}) "
            f"for secure document redaction.\n\n"
            f"📦 Download size: ~4.7 GB\n"
            f"⏱️ Estimated time: 5-15 minutes\n"
            f"💾 Storage location: ~/.marcut/models/\n\n"
            f"This is a one-time setup. Would you like to download now?",
            icon='question'
        )
        
        if response:
            self.download_model_with_progress()
        else:
            self.model_status.config(text="❌ Setup cancelled")
            messagebox.showinfo(
                "Setup Required",
                "The AI model is required for document redaction.\n\n"
                "You can complete setup later by restarting Marcut."
            )
    
    def download_model_with_progress(self):
        """Download model with enhanced progress tracking"""
        def download():
            try:
                self.progress.start()
                self.progress_text.config(text=f"Downloading {self.model_name} model...")
                self.model_status.config(text="📥 Downloading model...")
                
                # Use embedded ollama binary if available
                ollama_cmd = self.get_ollama_binary_path()
                if ollama_cmd == 'ollama':
                    ollama_cmd = 'ollama'  # Use system ollama
                
                print(f"[DEBUG] Downloading model with: {ollama_cmd}")
                
                # Start download
                result = subprocess.run(
                    [ollama_cmd, 'pull', self.model_name],
                    capture_output=True,
                    text=True,
                    env=os.environ.copy()
                )
                
                if result.returncode == 0:
                    print(f"[DEBUG] Model download successful")
                    self.model_status.config(text=f"✅ Model {self.model_name} ready")
                    self.root.after(0, lambda: self.show_setup_complete())
                else:
                    print(f"[DEBUG] Model download failed: {result.stderr}")
                    self.model_status.config(text=f"❌ Download failed")
                    self.root.after(0, lambda: messagebox.showerror(
                        "Download Failed",
                        f"Failed to download {self.model_name}.\n\n"
                        f"Error: {result.stderr}\n\n"
                        "Please check your internet connection and try again."
                    ))
                    
            except Exception as e:
                print(f"[DEBUG] Exception during model download: {e}")
                self.model_status.config(text=f"❌ Download error")
                self.root.after(0, lambda: messagebox.showerror(
                    "Download Error",
                    f"An error occurred while downloading the model:\n\n{str(e)}"
                ))
            finally:
                self.progress.stop()
                self.progress_text.config(text="")
                
        threading.Thread(target=download, daemon=True).start()
    
    def show_setup_complete(self):
        """Show setup completion dialog"""
        messagebox.showinfo(
            "Setup Complete!",
            f"🎉 Marcut is now ready!\n\n"
            f"✅ AI service running\n"
            f"✅ Model {self.model_name} downloaded\n"
            f"✅ Ready for document redaction\n\n"
            f"You can now select and redact DOCX documents."
        )

    def show_preferences(self):
        """Show preferences window (placeholder for future settings)"""
        messagebox.showinfo("Preferences", 
                          f"Model: {self.model_name}\n"
                          "Enhanced redaction: Enabled\n"
                          "Chunk size: 1000 tokens")
        
    def cleanup(self):
        """Clean up resources on exit"""
        if self.ollama_process:
            self.ollama_process.terminate()
            

def main():
    """Main entry point for GUI application"""
    root = tk.Tk()
    app = MarcutGUI(root)
    
    # Handle cleanup on window close
    def on_closing():
        app.cleanup()
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    # Start the GUI
    root.mainloop()


if __name__ == "__main__":
    main()
