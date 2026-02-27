#!/usr/bin/env python3
"""
Enhanced Ollama Integration for Marcut
Provides robust lifecycle management, model download progress, and ARM64 optimization
"""

import os
import sys
import json
import subprocess
import time
import requests
import threading
import signal
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Callable, TextIO
import logging
from dataclasses import dataclass

# Setup logging
logger = logging.getLogger(__name__)

@dataclass
class OllamaConfig:
    """Configuration for Ollama service"""
    home_dir: Path
    models_dir: Path
    host: str = "127.0.0.1"
    port: int = 11434
    binary_path: Optional[str] = None
    model_name: str = "llama3.1:8b"
    
    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"
    
    @property
    def api_url(self) -> str:
        return f"{self.url}/api"

class OllamaManager:
    """Enhanced Ollama service manager with robust error handling"""
    
    def __init__(self, config: OllamaConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self._stdout_log_handle: Optional[TextIO] = None
        self._stderr_log_handle: Optional[TextIO] = None
        self.is_running = False
        self.is_embedded = False
        self._setup_directories()
        self._find_binary()
        
    def _setup_directories(self):
        """Create required directories"""
        for directory in [self.config.home_dir, self.config.models_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {directory}")
    
    def _find_binary(self):
        """Find Ollama binary (embedded or system)"""
        # Check for embedded binary first
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller bundle
            embedded_path = Path(sys._MEIPASS).parent / "Resources" / "ollama" / "ollama"
        else:
            # Development or app bundle
            exe_dir = Path(sys.executable).parent
            potential_paths = [
                exe_dir.parent / "Resources" / "ollama" / "ollama",
                exe_dir.parent.parent / "Resources" / "ollama" / "ollama",
            ]
            embedded_path = None
            for path in potential_paths:
                if path.exists() and path.is_file():
                    embedded_path = path
                    break
        
        if embedded_path and embedded_path.exists():
            self.config.binary_path = str(embedded_path)
            self.is_embedded = True
            logger.info(f"Found embedded Ollama: {embedded_path}")
            
            # Verify it's ARM64
            try:
                result = subprocess.run(['file', str(embedded_path)], 
                                     capture_output=True, text=True)
                if 'arm64' in result.stdout:
                    logger.info("Embedded Ollama is ARM64 native")
                else:
                    logger.warning("Embedded Ollama may not be ARM64 native")
            except Exception as e:
                logger.warning(f"Could not verify Ollama architecture: {e}")
        else:
            # Fall back to system Ollama
            system_ollama = subprocess.run(['which', 'ollama'], 
                                         capture_output=True, text=True)
            if system_ollama.returncode == 0:
                self.config.binary_path = system_ollama.stdout.strip()
                logger.info(f"Using system Ollama: {self.config.binary_path}")
            else:
                logger.error("No Ollama binary found (embedded or system)")
                raise RuntimeError("Ollama binary not found")
    
    def is_service_running(self) -> bool:
        """Check if Ollama service is responding"""
        try:
            response = requests.get(f"{self.config.api_url}/tags", timeout=5)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    def _close_log_handles(self):
        for handle_name in ("_stdout_log_handle", "_stderr_log_handle"):
            handle = getattr(self, handle_name, None)
            if handle:
                try:
                    handle.close()
                except OSError:
                    pass
                setattr(self, handle_name, None)
    
    def start_service(self, timeout: int = 60) -> bool:
        """Start Ollama service with timeout"""
        if self.is_service_running():
            logger.info("Ollama service already running")
            self.is_running = True
            return True
        
        if not self.config.binary_path:
            logger.error("No Ollama binary path configured")
            return False
        
        try:
            # Set up environment
            env = os.environ.copy()
            env.update({
                'OLLAMA_MODELS': str(self.config.models_dir),
                'OLLAMA_HOME': str(self.config.home_dir),
                'OLLAMA_HOST': f"{self.config.host}:{self.config.port}"
            })
            
            # Start process
            logger.info(f"Starting Ollama service: {self.config.binary_path}")
            
            # Create logs directory
            logs_dir = self.config.home_dir / "logs"
            logs_dir.mkdir(exist_ok=True)

            # Open log files
            self._close_log_handles()
            self._stdout_log_handle = open(logs_dir / "ollama.log", "a")
            self._stderr_log_handle = open(logs_dir / "ollama_error.log", "a")
            
            self.process = subprocess.Popen(
                [self.config.binary_path, 'serve'],
                env=env,
                stdout=self._stdout_log_handle,
                stderr=self._stderr_log_handle,
                preexec_fn=os.setsid  # Create new process group
            )
            
            # Wait for service to start
            for i in range(timeout):
                if self.is_service_running():
                    self.is_running = True
                    logger.info(f"Ollama service started (PID: {self.process.pid})")
                    
                    # Save PID for cleanup
                    pid_file = self.config.home_dir / "ollama.pid"
                    pid_file.write_text(str(self.process.pid))
                    
                    return True
                time.sleep(1)
            
            logger.error(f"Ollama service failed to start within {timeout} seconds")
            self.stop_service()
            return False
            
        except Exception as e:
            logger.error(f"Failed to start Ollama service: {e}")
            self._close_log_handles()
            return False
    
    def stop_service(self):
        """Stop Ollama service gracefully"""
        if self.process:
            try:
                # Try graceful shutdown first
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                    logger.info("Ollama service stopped gracefully")
                except subprocess.TimeoutExpired:
                    # Force kill if graceful shutdown fails
                    self.process.kill()
                    self.process.wait()
                    logger.warning("Ollama service force killed")
            except Exception as e:
                logger.warning(f"Error stopping Ollama service: {e}")
            
            self.process = None
        
        # Clean up PID file
        pid_file = self.config.home_dir / "ollama.pid"
        if pid_file.exists():
            try:
                pid_file.unlink()
            except OSError as e:
                logger.warning(f"Failed to remove pid file {pid_file}: {e}")
        
        self._close_log_handles()
        self.is_running = False
    
    def list_models(self) -> Dict[str, Any]:
        """List available models"""
        if not self.is_service_running():
            return {"error": "Service not running"}
        
        try:
            response = requests.get(f"{self.config.api_url}/tags", timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def is_model_available(self, model_name: str) -> bool:
        """Check if a specific model is available"""
        models_data = self.list_models()
        if "models" in models_data:
            return any(model["name"].startswith(model_name) for model in models_data["models"])
        return False
    
    def download_model(self, model_name: str, 
                      progress_callback: Optional[Callable[[float, str], None]] = None) -> bool:
        """Download a model with progress tracking and resume capability"""
        logger.info(f"Starting download of model: {model_name}")
        
        if not self.is_service_running():
            logger.error("Cannot download model: Ollama service not running")
            return False
        
        try:
            # Check if model already exists
            if self.is_model_available(model_name):
                logger.info(f"Model {model_name} already available")
                if progress_callback:
                    progress_callback(100.0, "Already available")
                return True
            
            # Start download with progress tracking
            if progress_callback:
                progress_callback(0.0, "Starting download...")
            
            # Use Ollama pull command with progress tracking
            cmd = [self.config.binary_path, 'pull', model_name]
            env = os.environ.copy()
            env.update({
                'OLLAMA_MODELS': str(self.config.models_dir),
                'OLLAMA_HOME': str(self.config.home_dir),
            })
            
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Monitor progress
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                logger.debug(f"Ollama output: {line}")
                
                # Parse progress from Ollama output
                if progress_callback:
                    progress_percent, speed = self._parse_download_progress(line)
                    if progress_percent is not None:
                        progress_callback(progress_percent, speed or "")
            
            process.wait()
            
            if process.returncode == 0:
                logger.info(f"Successfully downloaded model: {model_name}")
                if progress_callback:
                    progress_callback(100.0, "Download complete")
                return True
            else:
                logger.error(f"Model download failed with exit code: {process.returncode}")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading model {model_name}: {e}")
            return False
    
    def _parse_download_progress(self, line: str) -> tuple[Optional[float], Optional[str]]:
        """Parse download progress from Ollama output"""
        # Ollama outputs progress lines like:
        # "pulling manifest"
        # "pulling <layer>... 50% ███████████████              1.2 GB/2.4 GB"
        # "verifying sha256 digest"
        # "writing manifest"
        # "removing any unused layers"
        # "success"
        
        if "%" in line and "GB" in line:
            try:
                # Extract percentage
                percent_start = line.find(" ") + 1
                percent_end = line.find("%")
                if percent_end > percent_start:
                    percent_str = line[percent_start:percent_end].strip()
                    try:
                        percent = float(percent_str)
                        
                        # Extract speed info
                        if "/" in line and "GB" in line:
                            gb_parts = line.split("/")
                            if len(gb_parts) >= 2:
                                speed = gb_parts[-1].strip()
                                return percent, speed
                        
                        return percent, None
                    except ValueError:
                        pass
            except:
                pass
        
        # Handle other status messages
        status_messages = {
            "pulling manifest": (5.0, "Preparing download"),
            "verifying sha256": (90.0, "Verifying integrity"),
            "writing manifest": (95.0, "Finalizing"),
            "success": (100.0, "Complete")
        }
        
        for msg, (percent, status) in status_messages.items():
            if msg in line.lower():
                return percent, status
        
        return None, None
    
    def verify_model_integrity(self, model_name: str) -> bool:
        """Verify model integrity (placeholder for checksum verification)"""
        # This is a placeholder - Ollama handles integrity internally
        # but we could add additional verification here if needed
        return self.is_model_available(model_name)
    
    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """Get detailed information about a model"""
        if not self.is_service_running():
            return {"error": "Service not running"}
        
        try:
            response = requests.post(
                f"{self.config.api_url}/show",
                json={"name": model_name},
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def cleanup_old_models(self, keep_models: list = None) -> bool:
        """Clean up old or unused models to save space"""
        if keep_models is None:
            keep_models = [self.config.model_name]
        
        try:
            models_data = self.list_models()
            if "models" not in models_data:
                return True
            
            for model in models_data["models"]:
                model_name = model["name"]
                should_keep = any(keep in model_name for keep in keep_models)
                
                if not should_keep:
                    logger.info(f"Removing old model: {model_name}")
                    result = subprocess.run(
                        [self.config.binary_path, 'rm', model_name],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        logger.info(f"Removed model: {model_name}")
                    else:
                        logger.warning(f"Failed to remove model {model_name}: {result.stderr}")
            
            return True
        except Exception as e:
            logger.error(f"Error cleaning up models: {e}")
            return False
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get comprehensive service status"""
        status = {
            "running": self.is_service_running(),
            "embedded": self.is_embedded,
            "binary_path": self.config.binary_path,
            "models_dir": str(self.config.models_dir),
            "home_dir": str(self.config.home_dir),
            "url": self.config.url,
            "process_pid": self.process.pid if self.process else None,
        }
        
        if status["running"]:
            # Get model list
            models_data = self.list_models()
            status["models"] = models_data.get("models", [])
            status["model_count"] = len(status["models"])
            
            # Check if our required model is available
            status["required_model_available"] = self.is_model_available(self.config.model_name)
        
        return status
    
    def health_check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        health = {
            "timestamp": time.time(),
            "service_running": False,
            "models_available": False,
            "disk_space_ok": False,
            "network_ok": False,
            "errors": []
        }
        
        try:
            # Check service
            health["service_running"] = self.is_service_running()
            if not health["service_running"]:
                health["errors"].append("Ollama service not running")
            
            # Check models
            if health["service_running"]:
                health["models_available"] = self.is_model_available(self.config.model_name)
                if not health["models_available"]:
                    health["errors"].append(f"Required model {self.config.model_name} not available")
            
            # Check disk space (need ~8GB for model + overhead)
            try:
                disk_usage = os.statvfs(str(self.config.models_dir))
                free_bytes = disk_usage.f_bavail * disk_usage.f_frsize
                free_gb = free_bytes / (1024**3)
                health["free_space_gb"] = round(free_gb, 2)
                health["disk_space_ok"] = free_gb > 8.0
                if not health["disk_space_ok"]:
                    health["errors"].append(f"Insufficient disk space: {free_gb:.1f}GB free, need 8GB+")
            except Exception as e:
                health["errors"].append(f"Could not check disk space: {e}")
            
            # Check network (for model downloads)
            # Note: Network check is optional - Ollama can work with cached models
            try:
                # Try Ollama's own registry first (more reliable for our use case)
                response = requests.head("https://registry.ollama.ai", timeout=5)
                health["network_ok"] = response.status_code in [200, 301, 302, 403]
            except:
                # Network might be down, but that's OK if we have cached models
                health["network_ok"] = False
                # Only report as error if we don't have the required model
                if not health["models_available"]:
                    health["errors"].append("Network connectivity issue - cannot download models")
        
        except Exception as e:
            health["errors"].append(f"Health check error: {e}")
        
        health["overall_healthy"] = (
            health["service_running"] and 
            health["models_available"] and 
            health["disk_space_ok"]
        )
        
        return health
    
    def restart_service(self) -> bool:
        """Restart the Ollama service"""
        logger.info("Restarting Ollama service")
        self.stop_service()
        time.sleep(2)  # Brief pause
        return self.start_service()
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop_service()

class ModelDownloader:
    """Specialized class for handling model downloads with resume capability"""
    
    def __init__(self, ollama_manager: OllamaManager):
        self.ollama = ollama_manager
        self.download_active = False
        
    def download_with_progress(self, model_name: str, 
                              progress_callback: Optional[Callable[[float, str], None]] = None,
                              completion_callback: Optional[Callable[[bool, str], None]] = None) -> bool:
        """
        Download model with detailed progress tracking and resume capability
        """
        if self.download_active:
            logger.warning("Download already in progress")
            return False
        
        self.download_active = True
        
        try:
            logger.info(f"Starting download of {model_name}")
            
            # Check if already available
            if self.ollama.is_model_available(model_name):
                logger.info(f"Model {model_name} already available")
                if progress_callback:
                    progress_callback(100.0, "Already available")
                if completion_callback:
                    completion_callback(True, "Model already available")
                return True
            
            # Ensure service is running
            if not self.ollama.is_service_running():
                logger.info("Starting Ollama service for download")
                if not self.ollama.start_service():
                    error_msg = "Failed to start Ollama service"
                    logger.error(error_msg)
                    if completion_callback:
                        completion_callback(False, error_msg)
                    return False
            
            # Start download process
            success = self._run_download_process(model_name, progress_callback)
            
            if completion_callback:
                if success:
                    completion_callback(True, "Download completed successfully")
                else:
                    completion_callback(False, "Download failed")
            
            return success
            
        except Exception as e:
            error_msg = f"Download error: {e}"
            logger.error(error_msg)
            if completion_callback:
                completion_callback(False, error_msg)
            return False
        finally:
            self.download_active = False
    
    def _run_download_process(self, model_name: str, 
                             progress_callback: Optional[Callable[[float, str], None]]) -> bool:
        """Run the actual download process with progress monitoring"""
        try:
            cmd = [self.ollama.config.binary_path, 'pull', model_name]
            env = os.environ.copy()
            env.update({
                'OLLAMA_MODELS': str(self.ollama.config.models_dir),
                'OLLAMA_HOME': str(self.ollama.config.home_dir),
            })
            
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            last_progress = 0.0
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    logger.debug(f"Download output: {line}")
                    
                    # Parse and report progress
                    if progress_callback:
                        progress, speed = self.ollama._parse_download_progress(line)
                        if progress is not None and progress != last_progress:
                            progress_callback(progress, speed or "")
                            last_progress = progress
            
            process.wait()
            
            # Final verification
            if process.returncode == 0:
                # Double-check that model is now available
                time.sleep(1)  # Brief pause for filesystem sync
                if self.ollama.is_model_available(model_name):
                    logger.info(f"Model {model_name} download verified")
                    return True
                else:
                    logger.error(f"Model {model_name} download completed but model not found")
                    return False
            else:
                logger.error(f"Model download failed with exit code: {process.returncode}")
                return False
                
        except Exception as e:
            logger.error(f"Download process error: {e}")
            return False

def create_ollama_manager() -> OllamaManager:
    """Factory function to create configured OllamaManager"""
    marcut_home = Path.home() / ".marcut"
    
    config = OllamaConfig(
        home_dir=marcut_home,
        models_dir=marcut_home / "models",
        model_name="llama3.1:8b"
    )
    
    return OllamaManager(config)

def setup_logging():
    """Setup logging for Ollama manager"""
    marcut_home = Path.home() / ".marcut"
    logs_dir = marcut_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(logs_dir / "ollama_manager.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )

# Example usage and testing
if __name__ == "__main__":
    setup_logging()
    
    # Test the Ollama manager
    manager = create_ollama_manager()
    
    try:
        print("Starting Ollama service...")
        if manager.start_service():
            print("✓ Service started successfully")
            
            # Check status
            status = manager.get_service_status()
            print(f"Status: {json.dumps(status, indent=2)}")
            
            # Health check
            health = manager.health_check()
            print(f"Health: {json.dumps(health, indent=2)}")
            
            # Download model if needed
            if not manager.is_model_available("llama3.1:8b"):
                print("Downloading model...")
                downloader = ModelDownloader(manager)
                
                def progress_cb(percent, speed):
                    print(f"Progress: {percent:.1f}% {speed}")
                
                def completion_cb(success, message):
                    print(f"Download {'completed' if success else 'failed'}: {message}")
                
                downloader.download_with_progress(
                    "llama3.1:8b", 
                    progress_callback=progress_cb,
                    completion_callback=completion_cb
                )
            else:
                print("✓ Model already available")
        else:
            print("✗ Failed to start service")
    
    finally:
        manager.stop_service()
        print("Service stopped")
