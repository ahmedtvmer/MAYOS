import time
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from agent.assistant_graph import STATIC_SYSTEM_CORE, build_prompt_payload
from utils.model_downloader import llm

def benchmark_scaling():
    turns = [1, 4, 10, 20, 30]
    results = []
    
    for count in turns:
        # Generate artificial dialogue history
        messages = []
        for i in range(count):
            messages.append(HumanMessage(content=f"Question {i}: How do I perform exercise variation {i}?"))
            messages.append(AIMessage(content=f"Answer {i}: Maintain stable foot pressure and control the eccentric."))
        
        # Test A: Unclamped Full History
        t0 = time.perf_counter()
        _ = llm.invoke([SystemMessage(content=STATIC_SYSTEM_CORE)] + messages)
        unclamped_time = time.perf_counter() - t0
        
        # Test B: Myos Clamped Tail (4 messages)
        state = {
            "messages": messages,
            "coach_tone": "Direct",
            "custom_instructions": "",
            "telemetry_context": ""
        }
        clamped_payload = build_prompt_payload(state)
        t0 = time.perf_counter()
        _ = llm.invoke(clamped_payload)
        clamped_time = time.perf_counter() - t0
        
        results.append((count, unclamped_time, clamped_time))
        print(f"Turns: {count:<2} | Unclamped: {unclamped_time:.2f}s | Myos Clamped: {clamped_time:.2f}s")

if __name__ == "__main__":
    benchmark_scaling()