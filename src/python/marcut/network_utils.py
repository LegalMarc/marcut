from __future__ import annotations

import os
from urllib.parse import urlparse

_DEFAULT_OLLAMA_HOST = "127.0.0.1:11434"
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _format_host_for_url(host: str) -> str:
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def normalize_ollama_base_url(raw_host: str | None = None, *, loopback_only: bool = False) -> str:
    raw = (raw_host if raw_host is not None else os.getenv("OLLAMA_HOST") or _DEFAULT_OLLAMA_HOST).strip()
    if not raw:
        raw = _DEFAULT_OLLAMA_HOST
    if not raw.startswith(("http://", "https://")):
        raw = f"http://{raw}"

    parsed = urlparse(raw)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434

    if loopback_only and host not in _LOOPBACK_HOSTS:
        host = "127.0.0.1"

    return f"{scheme}://{_format_host_for_url(host)}:{port}"


def ollama_cli_host_arg(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 11434
    return f"{_format_host_for_url(host)}:{port}"
