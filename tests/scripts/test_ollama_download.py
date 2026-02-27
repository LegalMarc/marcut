#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
from urllib import request, error


HOST_PATTERN = re.compile(r"(?:MARCUT_OLLAMA_HOST|OLLAMA_HOST)=([0-9a-zA-Z.\-]+:\d+)")


def log_candidates():
    home = os.path.expanduser("~")
    return [
        os.path.join(
            home,
            "Library/Containers/com.marclaw.marcutapp/Data/Library/Application Support/MarcutApp/logs/marcut.log",
        ),
        os.path.join(
            home,
            "Library/Containers/com.marclaw.marcutapp/Data/Library/Application Support/MarcutApp/logs/ollama.log",
        ),
        os.path.join(home, "Library/Application Support/MarcutApp/logs/marcut.log"),
        os.path.join(home, "Library/Application Support/MarcutApp/logs/ollama.log"),
    ]


def find_host_from_logs(paths):
    last_match = None
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    match = HOST_PATTERN.search(line)
                    if match:
                        last_match = match.group(1)
        except OSError:
            continue
    return last_match


def request_json(host, path, timeout):
    url = f"http://{host}{path}"
    req = request.Request(url)
    with request.urlopen(req, timeout=timeout) as response:
        data = response.read()
        return json.loads(data.decode("utf-8"))


def stream_pull(host, model, timeout, idle_timeout):
    url = f"http://{host}/api/pull"
    payload = json.dumps({"name": model, "stream": True}).encode("utf-8")
    req = request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    start = time.time()
    last_line_time = start
    final_status = None

    with request.urlopen(req, timeout=timeout) as response:
        while True:
            line = response.readline()
            now = time.time()
            if not line:
                break

            last_line_time = now
            stripped = line.strip()
            if not stripped:
                continue

            try:
                payload = json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                print(f"[warn] Non-JSON line: {stripped.decode('utf-8', errors='ignore')}")
                continue

            status = payload.get("status")
            total = payload.get("total")
            completed = payload.get("completed")
            if total and completed:
                percent = int((completed / total) * 100)
                print(f"[pull] {status} {percent}%")
            else:
                print(f"[pull] {status}")

            if status:
                final_status = status

            if (now - start) > timeout:
                raise TimeoutError("Overall pull timeout reached")

            if (now - last_line_time) > idle_timeout:
                raise TimeoutError("Pull stalled with no progress")

    return final_status


def main():
    parser = argparse.ArgumentParser(description="Test Ollama model download via /api/pull")
    parser.add_argument("--host", help="Ollama host:port (overrides log detection)")
    parser.add_argument("--model", default="llama3.1:8b", help="Model name to pull")
    parser.add_argument("--timeout", type=int, default=1800, help="Overall timeout in seconds")
    parser.add_argument("--idle-timeout", type=int, default=120, help="Idle timeout in seconds")
    parser.add_argument("--force", action="store_true", help="Pull even if model is already present")
    args = parser.parse_args()

    host = args.host or os.environ.get("MARCUT_OLLAMA_HOST") or os.environ.get("OLLAMA_HOST")
    if not host:
        host = find_host_from_logs(log_candidates())

    if not host:
        print("ERROR: Could not determine Ollama host. Launch the app and retry or pass --host.")
        return 2

    print(f"[info] Using host: {host}")

    try:
        version = request_json(host, "/api/version", timeout=5)
        print(f"[info] /api/version: {version}")
    except Exception as exc:
        print(f"ERROR: /api/version failed: {exc}")
        return 1

    try:
        tags = request_json(host, "/api/tags", timeout=10)
        models = [m.get("name") for m in tags.get("models", []) if isinstance(m, dict)]
        has_model = args.model in models
        print(f"[info] /api/tags models: {len(models)}")
        if has_model:
            print(f"[info] {args.model} already present")
        if has_model and not args.force:
            print("OK: Model already installed; use --force to pull anyway.")
            return 0
    except Exception as exc:
        print(f"ERROR: /api/tags failed: {exc}")
        return 1

    print(f"[info] Starting pull for {args.model}")
    try:
        final_status = stream_pull(host, args.model, args.timeout, args.idle_timeout)
    except TimeoutError as exc:
        print(f"ERROR: {exc}")
        return 1
    except error.HTTPError as exc:
        print(f"ERROR: HTTP error during pull: {exc}")
        return 1
    except Exception as exc:
        print(f"ERROR: Pull failed: {exc}")
        return 1

    print(f"[info] Final status: {final_status}")
    if final_status != "success":
        print("ERROR: Pull did not report success.")
        return 1

    try:
        tags = request_json(host, "/api/tags", timeout=10)
        models = [m.get("name") for m in tags.get("models", []) if isinstance(m, dict)]
        if args.model in models:
            print("OK: Model appears in /api/tags after pull.")
            return 0
    except Exception as exc:
        print(f"ERROR: /api/tags failed after pull: {exc}")
        return 1

    print("ERROR: Model not found in /api/tags after pull.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
