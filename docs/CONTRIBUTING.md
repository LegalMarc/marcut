# Contributing to Marcut

Thank you for your interest in contributing to Marcut! We welcome contributions from the community to help make professional-grade document redaction accessible to everyone.

## Getting Started

1.  **Read the Docs**: Familiarize yourself with the project structure.
    *   [User Guide](docs/USER_GUIDE.md)
    *   [Developer Guide](docs/DEVELOPER_GUIDE.md)
    *   [Architecture](docs/TECHNICAL_ARCHITECTURE.md)
2.  **Environment Setup**: Follow the [Developer Guide](docs/DEVELOPER_GUIDE.md) to set up your macOS development environment (Xcode, Python 3.9+).
3.  **Fork & Clone**: Fork the repository and clone it locally.

## Development Workflow

1.  **Branching**: Create a feature branch (`git checkout -b feature/my-cool-feature`).
2.  **Coding**:
    *   Swift code lives in `src/swift/MarcutApp`.
    *   Python core logic lives in `src/python/marcut`.
    *   Follow the "PythonKit + BeeWare" architecture strictly. **Do not introduce subprocess calls.**
3.  **Testing**:
    *   Run Python tests: `python3 -m pytest`
    *   Run Build tests: `./build_tui.py` → “Run Tests”
4.  **Committing**: Write clear, descriptive commit messages.

## Pull Request Process

1.  Ensure all tests pass locally.
2.  Update documentation if your change affects user workflows or architecture.
3.  Open a Pull Request against the `main` branch.
4.  Describe your changes, why they are needed, and how to verify them.

## Code Style

*   **Swift**: Follow standard Swift API Design Guidelines.
*   **Python**: Follow PEP 8.
*   **Safety**: Prioritize App Store compliance and sandbox security.

## Questions?

If you have questions, please open a GitHub Issue with the "question" label.
