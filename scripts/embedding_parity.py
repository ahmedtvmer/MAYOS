"""Compare cached PyTorch embeddings with the ONNX runtime and catalog search."""

import argparse
import ast
import os
import sqlite3
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import sqlite_vec

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from database.exercise_library.embeddings import exercise_id_for_vector_sql, semantic_text  # noqa: E402
from database.exercise_library.seeding import ExerciseSeedingMixin  # noqa: E402

PARITY_THRESHOLD = 0.9999
BENCHMARK_LIMIT = 5


def _test_guard_queries() -> list[str]:
    source_path = REPO_ROOT / "tests" / "test_clinical_semantic_guard.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    queries = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "parametrize" and len(node.args) >= 2:
            if isinstance(node.args[0], ast.Constant) and node.args[0].value == "query":
                values = node.args[1]
                if isinstance(values, (ast.List, ast.Tuple)):
                    queries.extend(
                        value_node.value
                        for value_node in values.elts
                        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str)
                    )
        if isinstance(node.func, ast.Name) and node.func.id == "evaluate_clinical_semantic_guard":
            queries.extend(
                argument.value
                for argument in node.args
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            )
    return list(dict.fromkeys(queries))


def _benchmark_queries() -> list[str]:
    source_path = REPO_ROOT / "tests" / "benchmark_vector_retrieval.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "QUERIES" for target in node.targets
        ):
            rows = ast.literal_eval(node.value)
            return [row[0] for row in rows]
    raise ValueError(f"QUERIES assignment not found in {source_path}")


def _catalog_texts(catalog_path: Path) -> tuple[list[tuple[str, str]], sqlite3.Connection]:
    connection = sqlite3.connect(f"file:{catalog_path.resolve()}?mode=ro", uri=True)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    rows = connection.execute(
        "SELECT id, name, target_muscle, equipment, instructions "
        "FROM exercises ORDER BY id"
    ).fetchall()
    texts = [
        (
            str(exercise_id),
            semantic_text(name, target_muscle, equipment, instructions),
        )
        for exercise_id, name, target_muscle, equipment, instructions in rows
    ]
    stored_sources = dict(connection.execute("SELECT exercise_id, semantic_text FROM exercise_embedding_sources"))
    differences = [exercise_id for exercise_id, text in texts if stored_sources.get(exercise_id) != text]
    if differences:
        connection.close()
        raise ValueError(f"Seeded semantic_text differs from stored vector sources for {len(differences)} rows.")
    return texts, connection


def _catalog_top_k(connection: sqlite3.Connection, query_vector: list[float]) -> list[str]:
    name_expression = "COALESCE(d.display_name, e.name)"
    id_expression = exercise_id_for_vector_sql("m.exercise_id")
    query = f"""
        WITH knn_matches AS (
            SELECT exercise_id, distance
            FROM vec_exercises
            WHERE embedding MATCH ? AND k = ?
        )
        SELECT e.id, {name_expression}, e.name
        FROM knn_matches m
        JOIN exercises e ON e.id = {id_expression}
        LEFT JOIN exercise_display_names d ON d.exercise_id = e.id
        WHERE NOT EXISTS (
            SELECT 1 FROM exercise_curated_fields cf
            WHERE cf.exercise_id = e.id AND cf.hidden = 1
        )
        ORDER BY m.distance ASC
    """
    rows = connection.execute(
        query,
        (sqlite_vec.serialize_float32(query_vector), BENCHMARK_LIMIT * 3),
    ).fetchall()
    candidates = []
    for exercise_id, display_name, source_name in rows:
        searchable_names = f"{display_name} {source_name}".lower()
        if any(pattern in searchable_names for pattern in ExerciseSeedingMixin.EXCLUDED_BIOMECHANICAL_PATTERNS):
            continue
        candidates.append(str(exercise_id))
        if len(candidates) == BENCHMARK_LIMIT:
            break
    return candidates


def _load_torch_embeddings(model_name: str):
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError as error:
        raise SystemExit(
            "Parity comparison requires the dev-only torch, sentence-transformers, and "
            "langchain-huggingface packages in the comparison environment."
        ) from error
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def _median_query_latency(model, query: str, repetitions: int = 12) -> float:
    model.embed_query(query)
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        model.embed_query(query)
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=REPO_ROOT / "db" / "catalog.db")
    args = parser.parse_args()
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog database not found: {args.catalog}")

    from agent.clinical_guard import CLINICAL_ANCHOR_DESCRIPTIONS

    exercise_texts, connection = _catalog_texts(args.catalog)
    guard_queries = _test_guard_queries()
    benchmark_queries = _benchmark_queries()
    text_groups = {
        "exercise_library": [text for _, text in exercise_texts],
        "clinical_anchors": list(CLINICAL_ANCHOR_DESCRIPTIONS),
        "clinical_guard_queries": guard_queries,
        "benchmark_queries": benchmark_queries,
    }
    texts = [text for category_texts in text_groups.values() for text in category_texts]

    from agent.clinical_guard import EMBED_MODEL

    model_name = EMBED_MODEL.model_name
    torch_model = _load_torch_embeddings(model_name)
    torch_vectors = np.asarray(torch_model.embed_documents(texts), dtype=np.float32)
    onnx_vectors = np.asarray(EMBED_MODEL.embed_documents(texts), dtype=np.float32)
    if torch_vectors.shape != onnx_vectors.shape:
        raise ValueError(f"Vector shape mismatch: torch={torch_vectors.shape}, onnx={onnx_vectors.shape}")

    cosines = np.sum(torch_vectors * onnx_vectors, axis=1)
    minimum_cosine = float(np.min(cosines))
    offsets = {}
    offset = 0
    for category, category_texts in text_groups.items():
        offsets[category] = (offset, offset + len(category_texts))
        offset += len(category_texts)

    print(f"catalog_rows={len(exercise_texts)}")
    print(f"semantic_text_match_count={len(exercise_texts)}")
    for category, (start, end) in offsets.items():
        print(f"{category}_count={end - start} min_cosine={float(np.min(cosines[start:end])):.9f}")
    print(f"total_text_count={len(texts)}")
    print(f"min_cosine={minimum_cosine:.9f}")

    mismatch_count = 0
    for index, query in enumerate(benchmark_queries):
        vector_index = offsets["benchmark_queries"][0] + index
        torch_top = _catalog_top_k(connection, torch_vectors[vector_index].tolist())
        onnx_top = _catalog_top_k(connection, onnx_vectors[vector_index].tolist())
        equal = torch_top == onnx_top
        mismatch_count += int(not equal)
        print(
            f"top_{BENCHMARK_LIMIT}_equal[{query!r}]={equal} "
            f"torch={torch_top} onnx={onnx_top}"
        )

    latency_query = benchmark_queries[0]
    torch_latency = _median_query_latency(torch_model, latency_query)
    onnx_latency = _median_query_latency(EMBED_MODEL, latency_query)
    print(f"median_query_latency_ms_torch={torch_latency:.3f}")
    print(f"median_query_latency_ms_onnx={onnx_latency:.3f}")
    print(f"latency_ratio_onnx_over_torch={onnx_latency / torch_latency:.3f}")
    connection.close()

    passed = minimum_cosine >= PARITY_THRESHOLD and mismatch_count == 0
    print(f"parity_threshold={PARITY_THRESHOLD:.4f}")
    print(f"parity_passed={passed}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
