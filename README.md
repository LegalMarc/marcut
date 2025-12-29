# Marcut

**Professional, Local-First Document Redaction.**

Marcut is a native macOS application for legal and professional document redaction. It combines a deterministic rules engine with optional local AI (Ollama) to identify and redact sensitive information (PII) from Microsoft Word (.docx) documents, producing "Track Changes" redlines plus JSON audit and scrub reports.

![License](https://img.shields.io/github/license/marclaw/marcut)
![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)
![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)

![Architecture Overview](docs/Architecture%20Diagram.jpg)

## 🚀 Key Features

*   **Local-First & Private:** All processing happens on your device. No cloud uploads.
*   **Self-Contained Runtime:** Embedded Python (BeeWare) and local AI service; no system installs required.
*   **Dual-Engine Power:**
    *   **Rules Engine:** Instant, regex-based detection for structured data (SSN, Phone, Email, etc.).
    *   **AI Engine:** Context-aware entity recognition (Names, Organizations) using local Ollama models.
*   **Professional Output:** Generates standard DOCX files with redacting edits marked as "Track Changes".
*   **Audit Ready:** Produces JSON redaction reports and metadata scrub reports for compliance verification.
*   **App Store Ready:** Fully sandboxed and code-signed architecture.

## 📖 Documentation

*   **[User Guide](docs/USER_GUIDE.md)**: Installation, usage instructions, and troubleshooting.
*   **[Developer Guide](docs/DEVELOPER_GUIDE.md)**: Deep dive into the Swift+PythonKit architecture, build system, and contribution workflow.
*   **[Technical Architecture](docs/TECHNICAL_ARCHITECTURE.md)**: High-level system design and component interaction.
*   **[Security Policy](SECURITY.md)**: Vulnerability reporting and security model.

## 🛠️ Quick Start (Development)

To build Marcut from source (macOS required):

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/marclaw/marcut.git
    cd marcut
    ```

2.  **Configure:**
    Copy the example config and edit if needed (mostly for signing identities).
    ```bash
    cp build-scripts/config.example.json build-scripts/config.json
    ```

3.  **Build:**
    Use the unified build script to create a local dev build.
    ```bash
    ./build_swift_only.sh preset dev_fast
    ```

4.  **Run:**
    Launch the built app:
    ```bash
    open src/swift/MarcutApp/.build/arm64-apple-macosx/debug/MarcutApp
    ```

For detailed build instructions, see the [Developer Guide](docs/DEVELOPER_GUIDE.md).

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on code style, testing, and the pull request process.

## 📄 License

This project is licensed under the MIT License - see the LICENSE.txt file for details.

---
*Built with SwiftUI, PythonKit, BeeWare, and local Ollama.*
