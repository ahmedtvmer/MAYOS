import json
from pathlib import Path

import numpy as np
import pytest

import core.embeddings as embeddings
from core.embeddings import get_arabic_embedding_model, get_embedding_model

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "embedding_reference_vectors.json"
ARABIC_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "arabic_embedding_reference_vectors.json"
)


def test_onnx_embeddings_match_torch_reference_fixture():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    texts = [item["text"] for item in fixture["vectors"]]
    expected = np.asarray([item["vector"] for item in fixture["vectors"]], dtype=np.float32)

    actual = np.asarray(get_embedding_model().embed_documents(texts), dtype=np.float32)

    assert actual.shape == (len(texts), 384)
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1.0, atol=1e-6)
    cosine = np.sum(actual * expected, axis=1)
    assert np.all(cosine >= 0.9999), f"ONNX vectors differ from torch fixture: {cosine}"


def test_arabic_embedding_model_is_mean_pooled_384_dim_and_normalized():
    fixture = json.loads(ARABIC_FIXTURE_PATH.read_text(encoding="utf-8"))
    model = get_arabic_embedding_model()
    texts = [item["text"] for item in fixture["vectors"]]
    expected = np.asarray([item["vector"] for item in fixture["vectors"]], dtype=np.float32)

    actual = np.asarray([model.embed_query(text) for text in texts], dtype=np.float32)

    assert model._pooling == "mean"
    assert model._embedding_dimension == 384
    assert actual.shape == (len(texts), 384)
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1.0, atol=1e-6)
    cosine = np.sum(actual * expected, axis=1)
    assert np.all(cosine >= 0.9999), f"Arabic vectors drifted from fixture: {cosine}"


def test_arabic_query_prefix_changes_the_embedding():
    model = get_arabic_embedding_model()
    text = "ركبتي مش ثابتة"

    query_vector = np.asarray(model.embed_query(text), dtype=np.float32)
    document_vector = np.asarray(model.embed_documents([text])[0], dtype=np.float32)

    assert float(np.dot(query_vector, document_vector)) < 0.999


def test_arabic_and_english_models_produce_distinct_vectors():
    text = "ركبتي مش ثابتة"

    arabic = np.asarray(get_arabic_embedding_model().embed_query(text), dtype=np.float32)
    english = np.asarray(get_embedding_model().embed_query(text), dtype=np.float32)

    assert float(np.dot(arabic, english)) < 0.9


def test_arabic_runtime_resolves_the_same_configuration_as_the_downloader(monkeypatch, tmp_path):
    monkeypatch.setenv("ARABIC_EMBEDDING_MODEL", str(tmp_path))
    monkeypatch.setattr(embeddings, "_ARABIC_EMBEDDING_MODEL", None)

    model = embeddings.get_arabic_embedding_model()

    assert model.model_name == str(tmp_path)
    assert model._onnx_file == embeddings.DEFAULT_ARABIC_ONNX_FILE
    assert model._revision == embeddings.DEFAULT_ARABIC_REVISION


def test_arabic_download_honors_a_local_directory_override(monkeypatch, tmp_path):
    for name in embeddings._model_files(embeddings.DEFAULT_ARABIC_ONNX_FILE):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}")
    monkeypatch.setenv("ARABIC_EMBEDDING_MODEL", str(tmp_path))

    paths = embeddings.download_arabic_model_files()

    assert (
        paths[embeddings.DEFAULT_ARABIC_ONNX_FILE]
        == str(tmp_path / embeddings.DEFAULT_ARABIC_ONNX_FILE)
    )


def _pooling_paths(tmp_path, **flags):
    pooling_dir = tmp_path / "1_Pooling"
    pooling_dir.mkdir(parents=True, exist_ok=True)
    config = {"word_embedding_dimension": 384, **flags}
    (pooling_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "sentence_bert_config.json").write_text(
        json.dumps({"max_seq_length": 512}), encoding="utf-8"
    )
    return {
        "1_Pooling/config.json": str(pooling_dir / "config.json"),
        "sentence_bert_config.json": str(tmp_path / "sentence_bert_config.json"),
    }


@pytest.mark.parametrize("mode", ["max", "mean_sqrt_len"])
def test_unsupported_pooling_modes_fail_loudly(tmp_path, mode):
    paths = _pooling_paths(
        tmp_path,
        pooling_mode_cls_token=False,
        pooling_mode_mean_tokens=False,
        pooling_mode_max_tokens=mode == "max",
        pooling_mode_mean_sqrt_len_tokens=mode == "mean_sqrt_len",
    )

    with pytest.raises(ValueError):
        embeddings._pooling_config(paths)


def test_cls_and_mean_pooling_configs_are_accepted(tmp_path):
    cls_paths = _pooling_paths(tmp_path / "cls", pooling_mode_cls_token=True)
    mean_paths = _pooling_paths(tmp_path / "mean", pooling_mode_mean_tokens=True)

    assert embeddings._pooling_config(cls_paths)[2] == "cls"
    assert embeddings._pooling_config(mean_paths)[2] == "mean"
