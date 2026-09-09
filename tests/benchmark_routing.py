# tests/benchmark_routing.py
import os
import sys
import time
from pathlib import Path
from typing import Dict, List
import statistics

from langchain_core.messages import HumanMessage, SystemMessage

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.assistant_graph import (
    router_node,
    IntentClassification,
    ROUTER_PROMPT
)
from utils.model_downloader import llm

BENCHMARK_PROMPTS = [
    ("Clinical Intercept", "I felt a sharp pop in my shoulder during bench press"),
    ("Explicit Swap (2-Way)", "swap barbell squat for pendulum squat"),
    ("Candidate Lookup (1-Way)", "alternatives for assisted pull-up"),
    ("Split Mutation", "switch routine to 4 days a week"),
    ("Catalog Search", "search incline dumbbell press"),
    ("Coaching QA Pass-Through", "how do I optimize mechanical tension on RDLs?"),
]

WARMUP_RUNS = 2
ITERATIONS = 5

structured_llm = llm.with_structured_output(IntentClassification)

def time_fast_path(query: str) -> float:
    """Executes pure deterministic router logic."""
    start = time.perf_counter()
    state = {"messages": [HumanMessage(content=query)]}
    _ = router_node(state)
    end = time.perf_counter()
    return (end - start) * 1000.0  # ms

def time_llm_routing(query: str) -> float:
    """Forces standard structured LLM intent extraction."""
    start = time.perf_counter()
    _ = structured_llm.invoke([
        SystemMessage(content=ROUTER_PROMPT),
        HumanMessage(content=query)
    ])
    end = time.perf_counter()
    return (end - start) * 1000.0  # ms

def run_benchmark():
    print("=" * 80)
    print("⚡ ZERO-LLM ROUTING VS TRADITIONAL LLM CLASSIFICATION BENCHMARK")
    print(f"Model: {os.getenv('MODEL_PATH', 'Qwen 2.5 3B GGUF')} | Runs: {ITERATIONS} (after {WARMUP_RUNS} warmups)")
    print("=" * 80)

    print("\nWarming up inference pipeline...")
    for _ in range(WARMUP_RUNS):
        _ = structured_llm.invoke([
            SystemMessage(content=ROUTER_PROMPT),
            HumanMessage(content="how do I optimize mechanical tension on RDLs?")
        ])
    print("Warmup complete.\n")

    results: List[Dict] = []

    for category, prompt in BENCHMARK_PROMPTS:
        fast_latencies = []
        for _ in range(ITERATIONS):
            fast_latencies.append(time_fast_path(prompt))

        llm_latencies = []
        for _ in range(ITERATIONS):
            llm_latencies.append(time_llm_routing(prompt))

        fast_mean = statistics.mean(fast_latencies)
        llm_mean = statistics.mean(llm_latencies)
        speedup = llm_mean / fast_mean if fast_mean > 0 else 0.0

        results.append({
            "category": category,
            "prompt": prompt,
            "fast_mean_ms": fast_mean,
            "llm_mean_ms": llm_mean,
            "speedup": speedup
        })

    print(f"{'Category':<26} | {'Regex Router':<14} | {'LLM Router':<14} | {'Speedup':<10}")
    print("-" * 72)
    for r in results:
        print(
            f"{r['category']:<26} | "
            f"{r['fast_mean_ms']:>8.3f} ms    | "
            f"{r['llm_mean_ms']:>8.1f} ms    | "
            f"{r['speedup']:>7.0f}x"
        )
    print("-" * 72)

    avg_fast = statistics.mean([r["fast_mean_ms"] for r in results])
    avg_llm = statistics.mean([r["llm_mean_ms"] for r in results])
    print(f"{'OVERALL AVERAGE':<26} | {avg_fast:>8.3f} ms    | {avg_llm:>8.1f} ms    | {avg_llm/avg_fast:>7.0f}x\n")

if __name__ == "__main__":
    run_benchmark()