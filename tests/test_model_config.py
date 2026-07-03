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
    list_models,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EXPECTED_MODELS = {
    "llama3.1:8b": {
        "display_name": "Llama 3.1 8B",
        "description": "Gold standard. The most accurate model tested.",
        "setup_description": "Gold standard. The most accurate model tested. Recommended.",
        "processing_time": "~45s",
        "size_label": "4.7 GB",
        "badge": "Best",
        "accent_color": "accent",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
    "mistral:7b": {
        "display_name": "Mistral 7B",
        "description": "Solid alternative, but less consistent than Llama 3.1.",
        "setup_description": "Solid alternative, but less consistent than Llama 3.1.",
        "processing_time": "~35s",
        "size_label": "4.1 GB",
        "badge": "Balanced",
        "accent_color": "orange",
        "temperature": 0.1,
        "skip_confidence": 0.95,
    },
    "llama3.2:3b": {
        "display_name": "Llama 3.2 3B",
        "description": "Very fast, but frequently misses entities. Use with caution.",
        "setup_description": "Very fast, but frequently misses entities. Use with caution.",
        "processing_time": "~20s",
        "size_label": "2.0 GB",
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
        model = get_model("mistral:7b")
        assert model is not None
        assert model.display_name == "Mistral 7B"

    def test_unknown_model_id_returns_none(self):
        assert get_model("not-a-real-model:1b") is None


class TestDefaultModel:
    def test_default_model_id_is_llama_3_1_8b(self):
        # Preserves the pre-refactor hardcoded default across cli.py,
        # gui.py, ollama_manager.py, and the Swift side.
        assert default_model_id() == "llama3.1:8b"

    def test_default_model_returns_full_config(self):
        model = default_model()
        assert model.id == default_model_id()
        assert model == ModelConfig(id="llama3.1:8b", **EXPECTED_MODELS["llama3.1:8b"])

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
