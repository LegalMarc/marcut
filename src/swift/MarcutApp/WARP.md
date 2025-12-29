# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

MarcutApp is a macOS application (minimum version 14.0) built with Swift using SwiftUI. The project utilizes LLMs for redacting critical names and parties alongside regular expression based rules.

## Build System

The project uses Swift Package Manager (SPM) for build management. Key commands:

```bash path=null start=null
# Build the application
swift build

# Run tests
swift test

# Run specific test target
swift test --target MarcutAppTests

# Build for release
swift build -c release

# Clean build artifacts
swift package clean
```

## Architecture

### Core Components

1. Redaction System
   - Uses a combination of LLM and regex-based rules for redacting sensitive information
   - LLM integration is mandatory for all installations
   - Excluded words are managed in `excluded-words.txt` (case-insensitive, supports singular/plural forms)

### Build Artifacts

- All OXT build files must be placed in the main project directory
- Build file naming convention: `{description} (note) {datetime}`
  Example: `build_v1.0.0 (initial release) 2025-09-01-1151`

### Design Principles

1. Robust Single System
   - System should either work fully or fail completely
   - No intent-aware or specific type fallbacks
   - Avoid fallbacks on specific types of edits or rules

## Developer Notes

- API compatibility notes and key insights should be documented in `docs/api_compatibility_notes.md`
- The redaction system requires both LLM and regex rules to be operational
- Excluded words list is applied using regex patterns and supports case-insensitive matching

## Important Rules

1. LLM Integration:
   - Required for all installations
   - Essential for redaction alongside regex rules

2. Build File Management:
   - Location: Main project directory
   - Naming: Must include update notes and timestamp

3. System Design:
   - Single robust system approach
   - No partial functionality or fallbacks
