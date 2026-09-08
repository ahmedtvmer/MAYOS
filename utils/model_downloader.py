import os
from pathlib import Path
from huggingface_hub import hf_hub_download
from langchain_community.chat_models import ChatLlamaCpp


DEFAULT_MODEL_DIR = Path("models")
DEFAULT_MODEL_FILENAME = "qwen2.5-3b-instruct-q4_k_m.gguf"
REPO_ID = "Qwen/Qwen2.5-3B-Instruct-GGUF"
N_THREADS=os.getenv("OMP_NUM_THREADS")

def get_or_download_model_path() -> str:
    """Returns local model path, downloading from Hugging Face if absent."""
    env_path = os.getenv("MODEL_PATH")
    if env_path and Path(env_path).is_file():
        return env_path

    target_dir = Path(os.getenv("MODEL_DIR", DEFAULT_MODEL_DIR))
    target_dir.mkdir(parents=True, exist_ok=True)
    target_file = target_dir / DEFAULT_MODEL_FILENAME

    if not target_file.is_file():
        print(f"⚡ Model artifact not found. Downloading {DEFAULT_MODEL_FILENAME} from {REPO_ID}...")
        hf_hub_download(
            repo_id=REPO_ID,
            filename=DEFAULT_MODEL_FILENAME,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False
        )
        print("✅ Download complete.")

    return str(target_file)

import multiprocessing

# Use physical cores (avoid hyperthreading contention on CPU inference)
physical_cores = multiprocessing.cpu_count() // 2 or 4

llm = ChatLlamaCpp(
    model_path=get_or_download_model_path(),
    temperature=0.0,
    n_ctx=2048,             # Reduce context ceiling from 4096 to 2048 (drops memory footprint)
    n_batch=512,            # Process up to 512 prompt tokens in parallel SIMD batches
    n_threads=physical_cores,       # Threads dedicated to token generation
    n_threads_batch=physical_cores, # Threads dedicated to prompt evaluation (TTFT)
    max_tokens=250,
    streaming=True,
    verbose=False
)