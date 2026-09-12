# Third-Party Licenses and Attribution

Marcut itself is MIT-licensed (see [LICENSE](LICENSE)). It bundles or depends on the
following third-party components, which remain under their own licenses.

## Bundled runtime components (shipped inside the macOS app)

| Component | License | Notes |
|---|---|---|
| Python.framework (BeeWare Apple support build of CPython 3.11) | PSF-2.0 | Universal2 Python runtime; includes CPython's own bundled libraries (e.g. OpenSSL, Apache-2.0) |
| Ollama | MIT | Embedded binary for local LLM inference |
| PythonKit | Apache-2.0 | Swift–Python interoperability, via Swift Package Manager |

## Python dependencies (bundled in the app's `python_site/`)

| Package | License |
|---|---|
| python-docx | MIT |
| lxml | BSD-3-Clause |
| rapidfuzz | MIT |
| regex | Apache-2.0 |
| tqdm | MPL-2.0 AND MIT |
| pydantic | MIT |
| dateparser | BSD-3-Clause |
| requests | Apache-2.0 |
| numpy | BSD-3-Clause |

The authoritative, versioned inventory of Python packages shipped in release builds —
including transitive dependencies — is the SBOM at
[docs/release/python-sbom.json](docs/release/python-sbom.json), regenerated and verified in
CI via `scripts/generate_python_sbom.py --check`.

LLM models downloaded through the app or Ollama (e.g. the Qwen family) are subject to
their respective model licenses; consult the upstream model cards referenced in
[assets/models.json](assets/models.json).
