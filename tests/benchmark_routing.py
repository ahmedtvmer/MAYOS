"""Measure the pre-model safety gate; task success belongs to tests/eval/run_evaluation.py."""

import statistics
import time

from langchain_core.messages import HumanMessage

from agent.assistant_graph import router_node


BENCHMARK_PROMPTS = [
    ("Clinical", "I felt a sharp pop in my shoulder during bench press"),
    ("Banned movement", "Add upright rows to my program"),
    ("Program options", "What other 5-day programs are there?"),
    ("Model handoff", "How do I optimize mechanical tension on RDLs?"),
]


def run_benchmark():
    for label, query in BENCHMARK_PROMPTS:
        latencies = []
        for _ in range(5):
            started = time.perf_counter()
            result = router_node({"messages": [HumanMessage(content=query)]})
            latencies.append((time.perf_counter() - started) * 1000)
        print(f"{label}: {statistics.median(latencies):.3f} ms; {result['intent']}")


if __name__ == "__main__":
    run_benchmark()
