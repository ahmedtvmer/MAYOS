"""Shared ONNX Runtime embeddings for clinical triage and the Exercise library."""

import json
import os
import threading
from pathlib import Path

import numpy as np

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
MODEL_FILES = (
    "onnx/model.onnx",
    "tokenizer.json",
    "1_Pooling/config.json",
    "sentence_bert_config.json",
)
_BATCH_SIZE = 32


def _model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip("'\"")


def download_model_files(model_name: str | None = None) -> dict[str, str]:
    """Download the model and Sentence Transformers configuration into HF_HOME."""
    from huggingface_hub import hf_hub_download

    repo_id = model_name or _model_name()
    return {
        filename: hf_hub_download(repo_id=repo_id, filename=filename)
        for filename in MODEL_FILES
    }


def _local_model_paths(model_name: str) -> dict[str, str]:
    local_model = Path(model_name).expanduser()
    if local_model.is_dir():
        return {filename: str(local_model / filename) for filename in MODEL_FILES}

    from huggingface_hub import hf_hub_download

    return {
        filename: hf_hub_download(repo_id=model_name, filename=filename, local_files_only=True)
        for filename in MODEL_FILES
    }


def _pooling_config(paths: dict[str, str]) -> tuple[int, int]:
    with open(paths["1_Pooling/config.json"], encoding="utf-8") as config_file:
        config = json.load(config_file)
    active_modes = [
        mode
        for key, mode in (
            ("pooling_mode_cls_token", "cls"),
            ("pooling_mode_max_tokens", "max"),
            ("pooling_mode_mean_tokens", "mean"),
            ("pooling_mode_mean_sqrt_len_tokens", "mean_sqrt_len"),
        )
        if config.get(key, False)
    ]
    if active_modes != ["cls"]:
        raise ValueError(f"Unsupported Sentence Transformers pooling configuration: {active_modes!r}; expected CLS.")

    with open(paths["sentence_bert_config.json"], encoding="utf-8") as config_file:
        max_seq_length = int(json.load(config_file)["max_seq_length"])
    return max_seq_length, int(config["word_embedding_dimension"])


def _configured_tokenizer(tokenizer_path: str, max_seq_length: int):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(tokenizer_path)
    pad_token = "[PAD]"
    pad_id = tokenizer.token_to_id(pad_token)
    if pad_id is None:
        raise ValueError(f"Tokenizer has no {pad_token} token.")
    tokenizer.enable_truncation(max_length=max_seq_length)
    tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)
    return tokenizer


def _onnx_session(model_path: str):
    import onnxruntime as ort

    session_options = ort.SessionOptions()
    # Two intra-op workers beat the PyTorch query latency on the one-vCPU Machine;
    # sequential inter-op execution avoids nesting another pool around them.
    session_options.intra_op_num_threads = 2
    session_options.inter_op_num_threads = 1
    session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session_options.enable_cpu_mem_arena = False
    # Avoid retaining both the original and prepacked BERT weights in process RSS.
    session_options.add_session_config_entry("session.disable_prepacking", "1")
    return ort.InferenceSession(
        model_path,
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )


class OnnxEmbeddings:
    """Sentence Transformers compatible query/document embedding interface."""

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or _model_name()
        self._load_lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._output_name = None
        self._embedding_dimension = None

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._load_lock:
            if self._session is not None:
                return

            paths = _local_model_paths(self.model_name)
            max_seq_length, embedding_dimension = _pooling_config(paths)
            tokenizer = _configured_tokenizer(paths["tokenizer.json"], max_seq_length)
            session = _onnx_session(paths["onnx/model.onnx"])
            self._validate_inputs(session)

            self._tokenizer = tokenizer
            self._output_name = session.get_outputs()[0].name
            self._embedding_dimension = embedding_dimension
            # Publish the session last: the unlocked fast path treats it as "fully loaded".
            self._session = session

    @staticmethod
    def _validate_inputs(session) -> None:
        input_names = {item.name for item in session.get_inputs()}
        missing = {"input_ids", "attention_mask", "token_type_ids"} - input_names
        if missing:
            raise ValueError(f"ONNX embedding graph is missing required inputs: {sorted(missing)}")

    def embed_query(self, text: str) -> list[float]:
        """Embed one text, matching ``HuggingFaceEmbeddings.embed_query``."""
        return self.embed_documents([text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed text documents with CLS pooling and L2 normalization."""
        if not texts:
            return []
        self._ensure_loaded()

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            vectors.extend(self._embed_batch(texts[start : start + _BATCH_SIZE]))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        encodings = self._tokenizer.encode_batch(texts)
        inputs = {
            "input_ids": np.asarray([encoding.ids for encoding in encodings], dtype=np.int64),
            "attention_mask": np.asarray([encoding.attention_mask for encoding in encodings], dtype=np.int64),
            "token_type_ids": np.asarray([encoding.type_ids for encoding in encodings], dtype=np.int64),
        }
        hidden_states = self._session.run([self._output_name], inputs)[0]
        pooled = hidden_states[:, 0, :]
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.maximum(norms, 1e-12)
        if normalized.shape[1] != self._embedding_dimension:
            raise ValueError(f"Expected {self._embedding_dimension} dimensions, got {normalized.shape[1]}.")
        return normalized.astype(np.float32).tolist()


_EMBEDDING_MODEL = OnnxEmbeddings()


def get_embedding_model() -> OnnxEmbeddings:
    """Return the process-wide embedding model shared by every caller."""
    return _EMBEDDING_MODEL
