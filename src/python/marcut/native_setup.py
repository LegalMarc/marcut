#!/usr/bin/env python3
"""Native macOS setup wizard using WebKit"""

import os
import sys
import json
import subprocess
import threading
from pathlib import Path
import tempfile
import webbrowser
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs
import time

class SetupServer:
    def __init__(self):
        self.app_dir = Path.home() / ".marcut"
        self.app_dir.mkdir(exist_ok=True)
        self.server = None
        self.port = 0
        self.setup_complete = False
        
    def create_setup_html(self):
        """Create the setup HTML page"""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Marcut Setup</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 500px;
            width: 100%;
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 2.5em;
            font-weight: 300;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }
        .steps {
            text-align: left;
            background: #f8f9fa;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }
        .step {
            margin: 10px 0;
            font-size: 1.1em;
        }
        .install-btn {
            background: #007AFF;
            color: white;
            border: none;
            padding: 15px 30px;
            border-radius: 25px;
            font-size: 1.2em;
            cursor: pointer;
            transition: all 0.3s;
            margin-top: 20px;
        }
        .install-btn:hover {
            background: #0051D5;
            transform: translateY(-2px);
        }
        .install-btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .progress {
            display: none;
            margin: 20px 0;
        }
        .progress-bar {
            width: 100%;
            height: 8px;
            background: #e0e0e0;
            border-radius: 4px;
            overflow: hidden;
        }
        .progress-fill {
            height: 100%;
            background: #007AFF;
            border-radius: 4px;
            animation: pulse 1.5s ease-in-out infinite;
        }
        @keyframes pulse {
            0% { width: 10%; }
            50% { width: 80%; }
            100% { width: 10%; }
        }
        .status {
            margin-top: 15px;
            color: #666;
            font-style: italic;
        }
        .success {
            color: #28a745;
            font-weight: bold;
        }
        .error {
            color: #dc3545;
            font-weight: bold;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Marcut</h1>
        <p class="subtitle">One-time setup for Apple Silicon native performance</p>
        
        <div class="steps">
            <div class="step">✨ Install native Python packages (~50MB)</div>
            <div class="step">🚀 Configure app directories</div>
            <div class="step">🧠 Set up Ollama AI service</div>
        </div>
        
        <button class="install-btn" onclick="startInstall()" id="installBtn">
            Start Installation
        </button>
        
        <div class="progress" id="progress">
            <div class="progress-bar">
                <div class="progress-fill"></div>
            </div>
            <div class="status" id="status">Preparing installation...</div>
        </div>
    </div>

    <script>
        async function startInstall() {
            const btn = document.getElementById('installBtn');
            const progress = document.getElementById('progress');
            const status = document.getElementById('status');
            
            btn.disabled = true;
            btn.textContent = 'Installing...';
            progress.style.display = 'block';
            
            try {
                const response = await fetch('/install', { method: 'POST' });
                const result = await response.json();
                
                if (result.success) {
                    status.textContent = '✅ Installation complete!';
                    status.className = 'status success';
                    btn.textContent = 'Launch Marcut';
                    btn.disabled = false;
                    btn.onclick = () => {
                        fetch('/launch', { method: 'POST' });
                        window.close();
                    };
                } else {
                    status.textContent = '❌ Installation failed: ' + result.error;
                    status.className = 'status error';
                    btn.textContent = 'Retry';
                    btn.disabled = false;
                }
            } catch (error) {
                status.textContent = '❌ Installation failed: ' + error.message;
                status.className = 'status error';
                btn.textContent = 'Retry';
                btn.disabled = false;
            }
        }
        
        // Poll for status updates
        setInterval(async () => {
            try {
                const response = await fetch('/status');
                const result = await response.json();
                if (result.message) {
                    document.getElementById('status').textContent = result.message;
                }
            } catch (e) {
                // Ignore polling errors
            }
        }, 1000);
    </script>
</body>
</html>"""

    def start_server(self):
        """Start the setup web server"""
        class SetupHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, setup_instance, *args, **kwargs):
                self.setup = setup_instance
                super().__init__(*args, **kwargs)
                
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(self.setup.create_setup_html().encode())
                elif self.path == '/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    status = {"message": getattr(self.setup, 'current_status', '')}
                    self.wfile.write(json.dumps(status).encode())
                else:
                    self.send_error(404)
                    
            def do_POST(self):
                if self.path == '/install':
                    threading.Thread(target=self.setup.run_installation, daemon=True).start()
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "started"}).encode())
                elif self.path == '/launch':
                    self.setup.launch_main_app()
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "launching"}).encode())
                else:
                    self.send_error(404)
                    
            def log_message(self, format, *args):
                # Suppress server logs
                pass
        
        # Find available port
        with socketserver.TCPServer(("", 0), None) as s:
            self.port = s.server_address[1]
        
        # Create handler with setup instance
        handler = lambda *args, **kwargs: SetupHandler(self, *args, **kwargs)
        
        # Start server
        self.server = socketserver.TCPServer(("", self.port), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        
    def run_installation(self):
        """Run the actual installation"""
        try:
            self.current_status = "Creating app directories..."
            lib_dir = self.app_dir / "lib"
            lib_dir.mkdir(exist_ok=True)
            
            self.current_status = "Installing required packages..."
            requirements = [
                "python-docx>=1.1.0",
                "lxml>=5.0.0",
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
                raise Exception(f"Failed to install packages: {proc.stderr}")
            
            self.current_status = "Setting up Ollama AI service..."
            ollama_path = self.setup_ollama()
            
            # Create config
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
                
            self.current_status = "✅ Installation complete!"
            self.setup_complete = True
            
        except Exception as e:
            self.current_status = f"❌ Installation failed: {str(e)}"
            
    def setup_ollama(self):
        """Setup Ollama service"""
        # Check if we have embedded Ollama
        bundle_exe = os.environ.get('_MEIPASS')
        if bundle_exe:
            embedded_ollama = Path(bundle_exe).parent / "Resources" / "ollama" / "ollama"
            if embedded_ollama.exists():
                # Copy to user directory with secure permissions
                ollama_dir = self.app_dir / "bin"
                ollama_dir.mkdir(exist_ok=True, mode=0o700)
                
                # Ensure directory has restrictive permissions (user-only)
                # This prevents other local users from tampering with the binary
                current_mode = ollama_dir.stat().st_mode & 0o777
                if current_mode != 0o700:
                    os.chmod(ollama_dir, 0o700)
                
                user_ollama = ollama_dir / "ollama"
                
                import shutil
                shutil.copy2(embedded_ollama, user_ollama)
                os.chmod(user_ollama, 0o755)
                return str(user_ollama)
        
        # Fall back to system Ollama
        system_ollama = subprocess.run(["which", "ollama"], capture_output=True, text=True)
        if system_ollama.returncode == 0:
            return system_ollama.stdout.strip()
            
        return None
        
    def launch_main_app(self):
        """Launch the main Marcut app"""
        self.server.shutdown()
        # Import and run main app
        from marcut.gui import main
        main()
        
    def run(self):
        """Run the setup wizard"""
        self.start_server()
        
        # Open in default browser
        url = f"http://localhost:{self.port}"
        webbrowser.open(url)
        
        # Keep the process alive
        try:
            while not self.setup_complete:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            if self.server:
                self.server.shutdown()
                
def run_wizard():
    """Entry point for setup wizard"""
    setup = SetupServer()
    setup.run()
