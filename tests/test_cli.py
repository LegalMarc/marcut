"""
Tests for cli.py module.

Tests cover:
- _parse_mode: Mode validation and normalization
- build(): Argument parser construction
"""

import pytest
import argparse
import sys
import marcut.cli as cli
from marcut.cli import _parse_mode, build


class TestParseMode:
    """Test _parse_mode function."""

    def test_valid_modes(self):
        """Test that valid modes pass through."""
        assert _parse_mode("rules") == "rules"
        assert _parse_mode("enhanced") == "enhanced"
        assert _parse_mode("rules_override") == "rules_override"
        assert _parse_mode("constrained_overrides") == "constrained_overrides"
        assert _parse_mode("llm_overrides") == "llm_overrides"

    def test_mode_normalization(self):
        """Test that modes are normalized to lowercase."""
        assert _parse_mode("RULES") == "rules"
        assert _parse_mode("Rules") == "rules"
        assert _parse_mode("ENHANCED") == "enhanced"
        assert _parse_mode("rules-override") == "rules_override"

    def test_whitespace_stripped(self):
        """Test that whitespace is stripped."""
        assert _parse_mode("  rules  ") == "rules"
        assert _parse_mode("\trules\n") == "rules"

    def test_strict_alias(self):
        """Test that 'strict' maps to 'rules'."""
        assert _parse_mode("strict") == "rules"
        assert _parse_mode("STRICT") == "rules"

    def test_invalid_mode_raises(self):
        """Test that invalid modes raise ArgumentTypeError."""
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode("invalid")
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode("foo")
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode("hybrid")
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode("balanced")

    def test_empty_raises(self):
        """Test that empty/None raises error."""
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode("")
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_mode(None)


class TestBuildParser:
    """Test build() argument parser construction."""

    def test_parser_created(self):
        """Test that parser is created successfully."""
        parser = build()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_has_redact_subcommand(self):
        """Test that redact subcommand exists."""
        parser = build()
        # Parse with redact subcommand should work
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json"
        ])
        assert args.cmd == "redact"

    def test_required_arguments(self):
        """Test required arguments."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json"
        ])
        assert args.inp == "/input.docx"
        assert args.out == "/output.docx"
        assert args.report == "/report.json"

    def test_default_values(self):
        """Test default argument values."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json"
        ])
        # Check defaults
        assert args.mode == "enhanced"  # default mode
        assert args.backend == "ollama"  # default backend
        assert args.model == "llama3.1:8b"  # default model
        assert args.threads == 4
        assert args.chunk_tokens == 1000
        assert args.overlap == 150
        assert args.temp == 0.1
        assert args.seed == 42
        assert args.llm_skip_confidence == 0.95
        assert args.debug is False
        assert args.no_qa is False
        assert args.metadata_preset is None
        assert args.metadata_settings_json is None
        assert args.metadata_args is None
        assert args.metadata_overrides is None

    def test_mode_argument(self):
        """Test mode argument."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--mode", "rules"
        ])
        assert args.mode == "rules"

    def test_backend_argument(self):
        """Test backend argument choices."""
        parser = build()
        for backend in ["ollama", "llama_cpp", "mock"]:
            args = parser.parse_args([
                "redact",
                "--in", "/input.docx",
                "--out", "/output.docx",
                "--report", "/report.json",
                "--backend", backend
            ])
            assert args.backend == backend

    def test_timing_flags(self):
        """Test timing and llm-detail flags."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--timing",
            "--llm-detail"
        ])
        assert args.timing is True
        assert args.llm_detail is True

    def test_debug_flag(self):
        """Test debug flag."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--debug"
        ])
        assert args.debug is True

    def test_custom_numeric_values(self):
        """Test custom numeric argument values."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--threads", "8",
            "--chunk-tokens", "2000",
            "--overlap", "300",
            "--temp", "0.5",
            "--seed", "123"
        ])
        assert args.threads == 8
        assert args.chunk_tokens == 2000
        assert args.overlap == 300
        assert args.temp == 0.5
        assert args.seed == 123

    def test_metadata_options(self):
        """Test metadata preset/json/override arguments."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--metadata-preset", "balanced",
            "--metadata-settings-json", "{\"cleanHeadersFooters\":false}",
            "--no-clean-headers-footers",
            "--clean-watermarks",
            "--metadata-args=--no-clean-track-changes"
        ])
        assert args.metadata_preset == "balanced"
        assert args.metadata_settings_json == "{\"cleanHeadersFooters\":false}"
        assert args.metadata_args == "--no-clean-track-changes"
        assert args.metadata_overrides == [
            "--no-clean-headers-footers",
            "--clean-watermarks",
        ]


class TestEdgeCases:
    """Test edge cases in CLI parsing."""

    def test_missing_required_arg_raises(self):
        """Test that missing required args raise error."""
        parser = build()
        with pytest.raises(SystemExit):
            # Missing --out and --report
            parser.parse_args(["redact", "--in", "/input.docx"])

    def test_gguf_model_path(self):
        """Test GGUF model path."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--llama-gguf", "/path/to/model.gguf"
        ])
        assert args.llama_gguf == "/path/to/model.gguf"

    def test_main_forwards_gguf_backend_settings(self, monkeypatch):
        """CLI llama.cpp settings should reach unified execution."""
        captured = {}

        def fake_run_unified_redaction(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "exit_code": 0,
                "duration": 0.1,
                "entity_count": 0,
                "phase_timings": {},
                "llm_timing": {},
            }

        monkeypatch.setattr(cli, "run_unified_redaction", fake_run_unified_redaction)
        monkeypatch.setattr(sys, "argv", [
            "marcut",
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--mode", "enhanced",
            "--backend", "llama_cpp",
            "--llama-gguf", "/models/local.gguf",
            "--threads", "8",
            "--temp", "0.4",
            "--seed", "123",
        ])

        with pytest.raises(SystemExit) as exc:
            cli.main()

        assert exc.value.code == 0
        assert captured["backend"] == "llama_cpp"
        assert captured["llama_gguf"] == "/models/local.gguf"
        assert captured["threads"] == 8
        assert captured["temperature"] == 0.4
        assert captured["seed"] == 123

    def test_no_qa_flag(self):
        """Test --no-qa flag."""
        parser = build()
        args = parser.parse_args([
            "redact",
            "--in", "/input.docx",
            "--out", "/output.docx",
            "--report", "/report.json",
            "--no-qa"
        ])
        assert args.no_qa is True
