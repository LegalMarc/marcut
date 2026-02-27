"""
Preflight checks to ensure all required components are available.
"""

import sys
import os
import time
import subprocess
import requests
from typing import Tuple, Optional
from .network_utils import normalize_ollama_base_url, ollama_cli_host_arg


def _ollama_base_url() -> str:
    return normalize_ollama_base_url(loopback_only=True)


def _cli_host_arg() -> str:
    return ollama_cli_host_arg(_ollama_base_url())


def _normalize_model_name(name: str) -> tuple[str, str, Optional[str]]:
    cleaned = (name or "").strip()
    # Strip registry host prefix if present (e.g., registry.ollama.ai/library/...)
    if "/" in cleaned:
        prefix = cleaned.split("/", 1)[0]
        if "." in prefix:
            cleaned = cleaned.split("/", 1)[1]
    if cleaned.startswith("library/"):
        cleaned = cleaned[len("library/"):]
    if ":" in cleaned:
        base, tag = cleaned.split(":", 1)
    else:
        base, tag = cleaned, None
    return cleaned, base, tag


def _matches_model(requested: str, candidate: str) -> bool:
    _, req_base, req_tag = _normalize_model_name(requested)
    _, cand_base, cand_tag = _normalize_model_name(candidate)
    if req_tag:
        return req_base == cand_base and req_tag == cand_tag
    return req_base == cand_base


def _is_executable(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    except OSError:
        return False


def find_ollama_binary() -> Optional[str]:
    """Locate the bundled Ollama binary only.
    Order:
    1) Bundled next to the executable (e.g., in app Resources)
    2) Bundled in ../Resources relative to the executable
    Returns absolute path or None if not found.
    """
    # 1) Same directory as the current executable (e.g., Contents/Resources)
    exe_dir = os.path.abspath(os.path.dirname(sys.executable))
    try:
        cand = os.path.join(exe_dir, "ollama")
        if _is_executable(cand):
            return cand
    except OSError:
        pass

    # 2) ../Resources directory (handles cases where sys.executable is within MacOS/)
    try:
        resources_dir = os.path.abspath(os.path.join(exe_dir, "..", "Resources"))
        cand2 = os.path.join(resources_dir, "ollama")
        if _is_executable(cand2):
            return cand2
    except OSError:
        pass

    return None

def check_ollama_installed() -> bool:
    """Check if embedded Ollama is present."""
    return find_ollama_binary() is not None

def check_ollama_running() -> bool:
    """Check if Ollama service is running."""
    base_url = _ollama_base_url()
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def wait_for_service(timeout_s: int = 45) -> bool:
    """Wait for Ollama HTTP service to become available."""
    base_url = _ollama_base_url()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    return False

def check_model_available(model_name: str = "phi4:mini-instruct") -> bool:
    """Check if the required model is available."""
    # Prefer API check (works regardless of how service started)
    # Then fall back to CLI if service is down but CLI is present
    base_url = _ollama_base_url()
    cli_host = _cli_host_arg()
    
    try:
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        if response.status_code == 200:
            models_data = response.json()
            available_models = [model['name'] for model in models_data.get('models', [])]
            return any(_matches_model(model_name, model) for model in available_models)
    except requests.exceptions.RequestException:
        # Try CLI list if API is not reachable
        try:
            ollama_bin = find_ollama_binary()
            if ollama_bin:
                result = subprocess.run([ollama_bin, 'list', '--host', cli_host], capture_output=True, text=True)
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        parts = line.strip().split()
                        if not parts:
                            continue
                        if _matches_model(model_name, parts[0]):
                            return True
        except (OSError, subprocess.SubprocessError):
            pass
    
    return False

def start_ollama_service() -> bool:
    """Attempt to start Ollama service."""
    try:
        ollama_bin = find_ollama_binary()
        if not ollama_bin:
            return False
        # Try to start Ollama in background
        env = os.environ.copy()
        subprocess.Popen([ollama_bin, 'serve'],
                         env=env,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        
        # Wait up to 45s for it to start
        return wait_for_service(timeout_s=45)
    except (OSError, subprocess.SubprocessError):
        return False

def download_model(model_name: str = "phi4:mini-instruct") -> bool:
    """Download the required model."""
    cli_host = _cli_host_arg()
    try:
        print(f"Downloading {model_name} model...")
        print("This is required for detecting names and organizations.")
        ollama_bin = find_ollama_binary()
        if not ollama_bin:
            return False
        result = subprocess.run([ollama_bin, 'pull', model_name, '--host', cli_host])
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False

def run_preflight_checks(auto_fix: bool = True, model_name: str = "phi4:mini-instruct") -> Tuple[bool, Optional[str]]:
    """
    Run all preflight checks and attempt to fix issues if auto_fix is True.
    
    Returns:
        Tuple of (success, error_message)
    """
    # Check 1: Is Ollama service running? (Priority check - API is what matters)
    if not check_ollama_running():
        # Check if Ollama CLI is available to try starting it
        if check_ollama_installed():
            print("✓ Ollama is installed")
            print(f"⚠ Ollama service is not running at {_ollama_base_url()}")
            if auto_fix:
                print("Attempting to start Ollama service...")
                if start_ollama_service():
                    print(f"✓ Ollama service started at {_ollama_base_url()}")
                else:
                    error_msg = """
⚠ Embedded Ollama service is not running and could not be started automatically.

Please restart MarcutApp. If the issue persists, reinstall MarcutApp to restore the embedded service.
"""
                    return False, error_msg
            else:
                return False, "Ollama service is not running"
        else:
            error_msg = """
❌ CRITICAL: Embedded Ollama is missing from the app bundle.

Ollama is MANDATORY for proper legal document redaction.
Without it, Marcut cannot detect names and organizations.

Please reinstall MarcutApp to restore the embedded Ollama service.
"""
            return False, error_msg
    else:
        print(f"✓ Ollama service is running at {_ollama_base_url()}")
    
    # Check 2: Is the required model available?
    if not check_model_available(model_name):
        print(f"⚠ {model_name} model not found")
        
        # Show available models for guidance
        try:
            response = requests.get(f"{_ollama_base_url()}/api/tags", timeout=5)
            if response.status_code == 200:
                models_data = response.json()
                available_models = [model['name'] for model in models_data.get('models', [])]
                print(f"Available models: {', '.join(available_models)}")
        except requests.exceptions.RequestException:
            pass
        
        if auto_fix:
            print(f"Downloading {model_name} model...")
            if download_model(model_name):
                # After download, wait briefly and re-check
                if wait_for_service(10) and check_model_available(model_name):
                    print(f"✓ {model_name} model downloaded")
                else:
                    error_msg = f"""
❌ Failed to download {model_name} model.

Please download it manually:
  ollama pull {model_name}

This model is required for detecting names and organizations in legal documents.
"""
                    return False, error_msg
        else:
            return False, f"{model_name} model not available"
    else:
        print(f"✓ {model_name} model is available")
    
    print("\n✅ All preflight checks passed!")
    print("Marcut is ready for comprehensive legal document redaction.")
    return True, None

def ensure_ollama_ready(model_name: str = "phi4:mini-instruct"):
    """
    Ensure Ollama is ready before processing. Hard-fails if requirements are not met.
    This should be called before any document processing.
    """
    success, error = run_preflight_checks(auto_fix=True, model_name=model_name)
    if not success:
        print(error, file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # Run preflight checks when module is executed directly
    ensure_ollama_ready()
