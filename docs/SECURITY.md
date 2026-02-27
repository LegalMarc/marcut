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
*   **Sandbox Escapes**: Arbitrary file access outside the sandboxed Application Support container.
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

**File**: `preflight.py`

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

**Mitigation**: Core redaction reads and writes DOCX content in memory via `ZipFile.read()`/`ZipFile.writestr()`. The macOS app also runs a validation pass that:
- Copies the DOCX to a temp directory for sandbox-safe inspection.
- Runs `/usr/bin/unzip -t` and extracts a minimal set of XML parts for integrity checks.
- Securely removes the temp directory after validation.

### App Sandbox Compliance

**File**: `MarcutApp.entitlements`

The macOS App Sandbox restricts what the application can access.

**Entitlements granted**:
| Entitlement | Purpose |
|-------------|---------|
| `com.apple.security.app-sandbox` | Enables sandbox |
| `com.apple.security.files.user-selected.read-write` | Access files user explicitly opens |
| `com.apple.security.network.client` | Model downloads + connect to local Ollama |
| `com.apple.security.network.server` | Ollama binds to localhost |

No broader filesystem access; outbound network use is limited to model downloads, and inference stays on localhost.

### Secure HTTP Requests

**Files**: `model.py`, `model_enhanced.py`, `preflight.py`

All HTTP requests are made to the local Ollama service (`http://127.0.0.1:<port>/api/...`).

**Security properties**:
- Localhost-only: No external network calls.
- No `verify=False`: TLS verification is not disabled (not needed for localhost HTTP).
- Timeouts: Health checks use short timeouts (2–5s). LLM requests allow long-running responses (up to ~120 minutes). The macOS app also enforces per-phase and per-document timeouts (default 120 minutes for the processing phase).

---
