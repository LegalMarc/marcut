"""
Tests for marcut.model_config - the loader for the shared `models.json`
catalog of supported Ollama models and their default parameters (ticket #22).

`models.json` is shipped as a bundled resource in three synced locations
(`assets/models.json`, `src/python/marcut/models.json`,
`src/swift/MarcutApp/Sources/MarcutApp/Resources/models.json`), the same way
`excluded-words.txt` is. These tests exercise the Python package copy that
ships with the `marcut` package; a parity check below also asserts the three
copies are byte-identical so they can't drift.
"""

import json
import os

import pytest

from marcut.model_config import (
    ModelCatalogError,
    ModelConfig,
    default_model,
    default_model_id,
    default_skip_confidence,
    default_temperature,
    get_model,
    is_gguf_model_path,
    list_models,
    uses_llama_cpp_backend,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EXPECTED_MODELS = {
    "qwen3.5:35b": {
        "display_name": "Qwen 3.5 35B A3B",
        "description": "Absolute highest accuracy. (Requires 24GB+ RAM).",
        "setup_description": "Absolute highest accuracy. (Requires 24GB+ RAM).",
        "processing_time": "~120s",
        "size_label": "22 GB",
        "badge": "Ultra",
        "accent_color": "purple",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
    "qwen2.5:14b": {
        "display_name": "Qwen 2.5 14B",
        "description": "Gold standard. Best accuracy for legal & complex documents.",
        "setup_description": "Gold standard. Best accuracy for legal & complex documents. Recommended.",
        "processing_time": "~50s",
        "size_label": "9.0 GB",
        "badge": "Best",
        "accent_color": "accent",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
    "qwen2.5:7b": {
        "display_name": "Qwen 2.5 7B",
        "description": "Balanced. Excellent extraction with lower memory usage.",
        "setup_description": "Balanced. Excellent extraction with lower memory usage.",
        "processing_time": "~30s",
        "size_label": "4.7 GB",
        "badge": "Balanced",
        "accent_color": "orange",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
    "phi4-mini:3.8b": {
        "display_name": "Phi-4 Mini 3.8B",
        "description": "Fast & lightweight. Good for simple documents.",
        "setup_description": "Fast & lightweight. Good for simple documents.",
        "processing_time": "~25s",
        "size_label": "2.5 GB",
        "badge": "Fast",
        "accent_color": "green",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
}


class TestListModels:
    def test_returns_all_expected_models(self):
        models = list_models()
        assert {m.id for m in models} == set(EXPECTED_MODELS)

    def test_each_model_matches_expected_fields(self):
        by_id = {m.id: m for m in list_models()}
        for model_id, expected in EXPECTED_MODELS.items():
            actual = by_id[model_id]
            assert actual == ModelConfig(id=model_id, **expected)

    def test_returns_a_copy_not_the_cached_list(self):
        first = list_models()
        first.append("mutated")
        assert "mutated" not in list_models()


class TestGetModel:
    def test_known_model_id_returns_config(self):
        model = get_model("qwen2.5:7b")
        assert model is not None
        assert model.display_name == "Qwen 2.5 7B"

    def test_unknown_model_id_returns_none(self):
        assert get_model("not-a-real-model:1b") is None


class TestDefaultModel:
    def test_default_model_id_is_qwen2_5_14b(self):
        # Matches the hardcoded default previously duplicated across cli.py,
        # gui.py, ollama_manager.py, and the Swift side.
        assert default_model_id() == "qwen2.5:14b"

    def test_default_model_returns_full_config(self):
        model = default_model()
        assert model.id == default_model_id()
        assert model == ModelConfig(id="qwen2.5:14b", **EXPECTED_MODELS["qwen2.5:14b"])

    def test_default_temperature_and_skip_confidence(self):
        assert default_temperature() == 0.1
        assert default_skip_confidence() == 0.95


class TestMalformedCatalog:
    def test_missing_file_raises_model_catalog_error(self, tmp_path):
        from marcut import model_config

        missing_path = tmp_path / "does-not-exist.json"
        with pytest.raises(ModelCatalogError):
            model_config._load_catalog(str(missing_path))

    def test_invalid_json_raises_model_catalog_error(self, tmp_path):
        from marcut import model_config

        bad_path = tmp_path / "models.json"
        bad_path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ModelCatalogError):
            model_config._load_catalog(str(bad_path))

    def test_missing_field_raises_model_catalog_error(self, tmp_path):
        from marcut import model_config

        bad_path = tmp_path / "models.json"
        bad_path.write_text(
            json.dumps({"defaultModel": "x", "models": [{"id": "x"}]}),
            encoding="utf-8",
        )
        with pytest.raises(ModelCatalogError):
            model_config._load_catalog(str(bad_path))

    def test_default_model_not_in_list_raises_model_catalog_error(self, tmp_path):
        from marcut import model_config

        bad_path = tmp_path / "models.json"
        bad_path.write_text(
            json.dumps(
                {
                    "defaultModel": "not-listed:1b",
                    "models": [
                        {
                            "id": "x:1b",
                            "displayName": "X",
                            "description": "d",
                            "setupDescription": "sd",
                            "processingTime": "~1s",
                            "sizeLabel": "1 GB",
                            "badge": "Fast",
                            "accentColor": "green",
                            "temperature": 0.1,
                            "skipConfidence": 0.95,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ModelCatalogError):
            model_config._load_catalog(str(bad_path))


class TestUsesLlamaCppBackend:
    """The single shared definition of "this run dispatches to llama.cpp
    rather than Ollama" (#87), unifying what used to be five separately
    drifted copies across model_enhanced.py, pipeline.py, and
    unified_redactor.py."""

    def test_explicit_llama_cpp_backend(self):
        # An explicit backend dispatches to llama.cpp regardless of the
        # model string's shape.
        assert uses_llama_cpp_backend("llama_cpp", "qwen2.5:14b") is True

    def test_gguf_suffix(self):
        assert uses_llama_cpp_backend("ollama", "model.gguf") is True
        assert uses_llama_cpp_backend("ollama", "models/mine/qwen2.5-14b.gguf") is True

    def test_absolute_path_without_gguf_suffix(self):
        assert uses_llama_cpp_backend("ollama", "/Users/alice/models/mine") is True

    def test_plain_ollama_tag(self):
        assert uses_llama_cpp_backend("ollama", "qwen2.5:14b") is False

    def test_namespaced_registry_id_is_not_a_local_path(self):
        # Contains "/" but is neither absolute nor a .gguf file -- an
        # Ollama registry namespace, not a local llama.cpp path (#85).
        assert uses_llama_cpp_backend("ollama", "hf.co/bartowski/Qwen2.5-14B-GGUF:Q4_K_M") is False

    def test_llama_gguf_set_with_backend_ollama(self):
        # --llama-gguf overrides the plain model id for dispatch even when
        # --backend is left at its "ollama" default (#68); callers pass
        # `llama_gguf or model_id` as `model_path`.
        model_id = "qwen2.5:14b"
        llama_gguf = "/Users/alice/models/mine.gguf"
        assert uses_llama_cpp_backend("ollama", llama_gguf or model_id) is True

    def test_relative_gguf_path_no_leading_slash(self):
        assert uses_llama_cpp_backend("ollama", "relative/model.gguf") is True


class TestIsGgufModelPath:
    """The narrower building block `uses_llama_cpp_backend` is built from,
    used directly at call sites that already know or have already fixed
    the backend (unified_redactor.py)."""

    def test_gguf_suffix(self):
        assert is_gguf_model_path("model.gguf") is True

    def test_absolute_path(self):
        assert is_gguf_model_path("/Users/alice/models/mine") is True

    def test_plain_ollama_tag_is_not_a_path(self):
        assert is_gguf_model_path("qwen2.5:14b") is False

    def test_namespaced_registry_id_is_not_a_path(self):
        assert is_gguf_model_path("hf.co/bartowski/Qwen2.5-14B-GGUF:Q4_K_M") is False


class TestBundledCopiesStaySynced:
    """The three shipped copies of models.json must be byte-identical, the
    same way excluded-words.txt is kept in sync across assets/,
    src/python/marcut/, and the Swift Resources bundle."""

    @pytest.mark.parametrize(
        "relative_path",
        [
            "assets/models.json",
            "src/swift/MarcutApp/Sources/MarcutApp/Resources/models.json",
        ],
    )
    def test_copy_matches_python_package_copy(self, relative_path):
        canonical_path = os.path.join(REPO_ROOT, "src/python/marcut/models.json")
        other_path = os.path.join(REPO_ROOT, relative_path)

        with open(canonical_path, "r", encoding="utf-8") as f:
            canonical = f.read()
        with open(other_path, "r", encoding="utf-8") as f:
            other = f.read()

        assert canonical == other, (
            f"{relative_path} has drifted from src/python/marcut/models.json; "
            "keep all shipped copies byte-identical."
        )
