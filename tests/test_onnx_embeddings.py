import json
from pathlib import Path

import numpy as np

from core.embeddings import get_embedding_model

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "embedding_reference_vectors.json"


def test_onnx_embeddings_match_torch_reference_fixture():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    texts = [item["text"] for item in fixture["vectors"]]
    expected = np.asarray([item["vector"] for item in fixture["vectors"]], dtype=np.float32)

    actual = np.asarray(get_embedding_model().embed_documents(texts), dtype=np.float32)

    assert actual.shape == (len(texts), 384)
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1.0, atol=1e-6)
    cosine = np.sum(actual * expected, axis=1)
    assert np.all(cosine >= 0.9999), f"ONNX vectors differ from torch fixture: {cosine}"
