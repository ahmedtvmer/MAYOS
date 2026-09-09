import time
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))
from database.database_manager import DatabaseManager
from agent.assistant_graph import EMBED_MODEL

QUERIES = [
    ("hamstrings barbell", "stiff-legged deadlift"),
    ("quads machine", "leg press"),
    ("chest cable", "cable crossover"),
    ("lats dumbbell", "dumbbell row"),
    ("triceps cable", "triceps pushdown")
]

def benchmark_vector_accuracy():
    db = DatabaseManager()
    latencies = []
    
    for query, expected in QUERIES:
        t0 = time.perf_counter()
        vec = EMBED_MODEL.embed_query(query)
        candidates = db.search_similar_exercises(vec, limit=5)
        elapsed = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed)
        
        names = [c["name"].lower() for c in candidates]
        matched = any(expected in name for name in names)
        print(f"Query: '{query}' -> Top Match: '{candidates[0]['name']}' ({elapsed:.2f} ms) | Relevant: {matched}")

    print(f"\nAverage Vector Search Latency: {sum(latencies)/len(latencies):.2f} ms")

if __name__ == "__main__":
    benchmark_vector_accuracy()