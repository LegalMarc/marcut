# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| v0.5.x  | :white_check_mark: |
| < v0.5  | :x:                |

## Reporting a Vulnerability

Marcut deals with sensitive legal and personal documents. We take security seriously.

**Do NOT report security vulnerabilities via public GitHub issues.**

If you discover a security vulnerability, please email [security@marclaw.com](mailto:security@marclaw.com) (or the repository owner directly). We will acknowledge receipt of your vulnerability report within 48 hours and strive to send you regular updates about our progress.

### Areas of Interest

We are particularly interested in reports concerning:
*   **Data Leakage**: Unintended retention of PII or document content (e.g., in logs or temp files).
*   **Sandbox Escapes**: Arbitrary file access outside the App Group container.
*   **Redaction Failures**: Scenarios where "redacted" text is recoverable from the DOCX structure.
*   **Dependency Vulnerabilities**: Issues in embedded libraries (Ollama, Python packages).

## Security Best Practices

*   Marcut processes all documents **locally**.
*   Network access is restricted to `localhost` (Ollama) and explicit model downloads.
*   No telemetry or usage data is collected.

---

## Security Hardening Measures

This section documents the security controls implemented in Marcut.

### XML External Entity (XXE) Protection

**Files**: `docx_io.py`, `docx_revisions.py`

DOCX files are ZIP archives containing XML. Malicious XML can include external entity declarations that read local files or cause denial of service.

**Mitigation**: All XML parsing uses a safe parser with entity resolution disabled:
```python
parser = etree.XMLParser(resolve_entities=False)
root = etree.fromstring(xml_bytes, parser)
```

### Command Injection Prevention

**Files**: `ollama_manager.py`, `preflight.py`, `native_setup.py`

The application spawns subprocesses to manage the Ollama service.

**Mitigation**: 
- All `subprocess.run()` and `subprocess.Popen()` calls use **list arguments**, never shell strings.
- `shell=True` is never used.
- Model names are validated via `validate_model_name()` to reject shell metacharacters (`;`, `|`, `&`, `$`, `` ` ``, `>`, `<`).

### Input Validation

**File**: `unified_redactor.py`

User-provided model names could potentially be passed to subprocesses.

**Mitigation**: The `validate_model_name()` function enforces:
- Ollama model names: alphanumerics, underscores, hyphens, colons, periods only.
- GGUF file paths: no shell metacharacters.

### Zip Slip Prevention

**Files**: `docx_io.py`, `docx_revisions.py`

Malicious ZIP archives can contain paths like `../../../etc/passwd` to overwrite files outside the extraction directory.

**Mitigation**: Marcut never extracts DOCX files to disk. All processing occurs in memory:
- Files are read via `ZipFile.read(name)`.
- Modified content is written to a new ZIP via `ZipFile.writestr()`.
- No path traversal is possible because no filesystem extraction occurs.

### Secure Binary Installation

**File**: `native_setup.py`

When copying the embedded Ollama binary to the user's home directory, improper permissions could allow local tampering.

**Mitigation**:
- The `~/.marcut/bin` directory is created with `0o700` permissions (owner-only access).
- Permissions are verified and corrected before copying.
- The binary itself is set to `0o755` (executable by owner, readable by others).

### App Sandbox Compliance

**File**: `MarcutApp.entitlements`

The macOS App Sandbox restricts what the application can access.

**Entitlements granted**:
| Entitlement | Purpose |
|-------------|---------|
| `com.apple.security.app-sandbox` | Enables sandbox |
| `com.apple.security.files.user-selected.read-write` | Access files user explicitly opens |
| `com.apple.security.network.client` | Connect to Ollama on localhost |
| `com.apple.security.network.server` | Ollama binds to localhost |
| `com.apple.security.application-groups` | Shared container for app data |

No broader filesystem access, no outbound internet access beyond localhost.

### Secure HTTP Requests

**Files**: `model.py`, `model_enhanced.py`, `ollama_manager.py`, `preflight.py`

All HTTP requests are made to the local Ollama service (`http://127.0.0.1:<port>/api/...`).

**Security properties**:
- Localhost-only: No external network calls.
- No `verify=False`: TLS verification is not disabled (not needed for localhost HTTP).
- Timeouts: All requests have explicit timeouts (5-300 seconds).

---

## Known Limitations

### Python Standalone Setup Wizard (Not Fixed)

**File**: `native_setup.py`

**Issue**: The Python standalone distribution (not the Swift app) includes a web-based setup wizard that runs an unauthenticated HTTP server on a random port.

**Risk**: Another process on the same machine could send POST requests to `/install` or `/launch` endpoints.

**Why not fixed**:
1. This code path is only used by the Python CLI distribution, not the main Swift desktop app.
2. The attack requires same-user local access (the server binds to `127.0.0.1`).
3. Adding authentication would increase complexity with no existing test coverage.

**Recommendation**: If you use the Python CLI distribution on a shared system, be aware of this limitation. The Swift app (primary distribution) is not affected.
