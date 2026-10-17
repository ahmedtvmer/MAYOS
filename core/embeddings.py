"""Shared ONNX Runtime embeddings for clinical triage and the Exercise library.

Two models are deployed side by side (ADR 081): ``BAAI/bge-small-en-v1.5`` keeps
serving English clinical triage and Exercise library search, while
``intfloat/multilingual-e5-small`` backs the Arabic clinical guard. Both are
loaded through the same ONNX Runtime path with no PyTorch or Sentence
Transformers in the image (ADR 075).
"""

import json
import os
import threading
from pathlib import Path

import numpy as np

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
#: Arabic clinical guard model (ADR 081). 384-dimensional, MIT, XLM-R based.
DEFAULT_ARABIC_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
#: Pinned upstream revision the Arabic calibration was measured against. Pinning
#: keeps fresh builds from following mutable main and describing vectors the
#: deployed files do not produce (ADR 075 parity evidence).
DEFAULT_ARABIC_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
#: The e5 family is trained with a textual task prefix on every input.
DEFAULT_ARABIC_QUERY_PREFIX = "query: "
#: The Arabic model ships a raw and an ORT-optimized graph. The O4 graph is
#: numerically identical to the raw one for our inputs but is about half the
#: size and roughly 180 MB lighter in RSS, matching ADR 081's memory budget.
DEFAULT_ONNX_FILE = "onnx/model.onnx"
DEFAULT_ARABIC_ONNX_FILE = "onnx/model_O4.onnx"
_MODEL_CONFIG_FILES = (
    "tokenizer.json",
    "1_Pooling/config.json",
    "sentence_bert_config.json",
)
_BATCH_SIZE = 32

#: Sentence Transformers pooling flags in the ``1_Pooling/config.json``.
_POOLING_FLAGS = (
    ("pooling_mode_cls_token", "cls"),
    ("pooling_mode_max_tokens", "max"),
    ("pooling_mode_mean_tokens", "mean"),
    ("pooling_mode_mean_sqrt_len_tokens", "mean_sqrt_len"),
)
#: Only CLS and mean pooling are implemented in ``_pool``; any other configured
#: mode must fail loudly rather than silently falling back to CLS.
_SUPPORTED_POOLING_MODES = frozenset({"cls", "mean"})


def _model_name() -> str:
    return os.getenv("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL).strip("'\"")


def _arabic_model_name() -> str:
    return os.getenv("ARABIC_EMBEDDING_MODEL", DEFAULT_ARABIC_EMBEDDING_MODEL).strip("'\"")


def _model_files(onnx_file: str) -> tuple[str, ...]:
    return (onnx_file, *_MODEL_CONFIG_FILES)


def download_model_files(
    model_name: str | None = None,
    onnx_file: str = DEFAULT_ONNX_FILE,
    revision: str | None = None,
) -> dict[str, str]:
    """Download the model and Sentence Transformers configuration into HF_HOME.

    A local directory passed as ``model_name`` is honored as-is, matching the
    runtime resolution in ``_local_model_paths``.
    """
    repo_id = model_name or _model_name()
    local_model = Path(repo_id).expanduser()
    if local_model.is_dir():
        return {filename: str(local_model / filename) for filename in _model_files(onnx_file)}

    from huggingface_hub import hf_hub_download

    return {
        filename: hf_hub_download(repo_id=repo_id, filename=filename, revision=revision)
        for filename in _model_files(onnx_file)
    }


def download_arabic_model_files(model_name: str | None = None) -> dict[str, str]:
    """Download the Arabic clinical model and its configuration into HF_HOME.

    Uses the same resolved repo, graph and pinned revision as the runtime.
    """
    return download_model_files(
        model_name or _arabic_model_name(),
        onnx_file=DEFAULT_ARABIC_ONNX_FILE,
        revision=DEFAULT_ARABIC_REVISION,
    )


def _local_model_paths(
    model_name: str, onnx_file: str, revision: str | None = None
) -> dict[str, str]:
    local_model = Path(model_name).expanduser()
    if local_model.is_dir():
        return {filename: str(local_model / filename) for filename in _model_files(onnx_file)}

    from huggingface_hub import hf_hub_download

    return {
        filename: hf_hub_download(
            repo_id=model_name, filename=filename, revision=revision, local_files_only=True
        )
        for filename in _model_files(onnx_file)
    }


def _pooling_config(paths: dict[str, str]) -> tuple[int, int, str]:
    with open(paths["1_Pooling/config.json"], encoding="utf-8") as config_file:
        config = json.load(config_file)
    active_modes = [mode for key, mode in _POOLING_FLAGS if config.get(key, False)]
    if len(active_modes) != 1 or active_modes[0] not in _SUPPORTED_POOLING_MODES:
        raise ValueError(
            f"Unsupported Sentence Transformers pooling configuration: {active_modes!r}; "
            f"expected exactly one of {sorted(_SUPPORTED_POOLING_MODES)}."
        )

    with open(paths["sentence_bert_config.json"], encoding="utf-8") as config_file:
        max_seq_length = int(json.load(config_file)["max_seq_length"])
    return max_seq_length, int(config["word_embedding_dimension"]), active_modes[0]


def _configured_tokenizer(tokenizer_path: str, max_seq_length: int, pad_token: str):
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(tokenizer_path)
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
    """Sentence Transformers compatible query/document embedding interface.

    ``pooling`` selects CLS or mean pooling and, when given, is asserted against
    the model's ``1_Pooling/config.json`` so a swapped artifact fails loudly.
    ``query_prefix`` is prepended to every query text (the e5 ``"query: "`` rule);
    ``pad_token`` names the tokenizer's padding token; ``onnx_file`` selects the
    ONNX graph within the repo; ``revision`` pins the upstream repo revision.
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        pooling: str | None = None,
        query_prefix: str = "",
        pad_token: str = "[PAD]",
        onnx_file: str = DEFAULT_ONNX_FILE,
        revision: str | None = None,
    ):
        self.model_name = model_name or _model_name()
        self.query_prefix = query_prefix
        self._required_pooling = pooling
        self._pad_token = pad_token
        self._onnx_file = onnx_file
        self._revision = revision
        self._load_lock = threading.Lock()
        self._session = None
        self._tokenizer = None
        self._output_name = None
        self._embedding_dimension = None
        self._pooling = pooling

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return
        with self._load_lock:
            if self._session is not None:
                return

            paths = _local_model_paths(self.model_name, self._onnx_file, self._revision)
            max_seq_length, embedding_dimension, pooling = _pooling_config(paths)
            if self._required_pooling is not None and pooling != self._required_pooling:
                raise ValueError(
                    f"{self.model_name} uses {pooling!r} pooling, expected {self._required_pooling!r}."
                )
            tokenizer = _configured_tokenizer(
                paths["tokenizer.json"], max_seq_length, self._pad_token
            )
            session = _onnx_session(paths[self._onnx_file])
            self._validate_inputs(session)

            self._tokenizer = tokenizer
            self._output_name = session.get_outputs()[0].name
            self._embedding_dimension = embedding_dimension
            self._pooling = pooling
            # Publish the session last: the unlocked fast path treats it as "fully loaded".
            self._session = session

    @staticmethod
    def _validate_inputs(session) -> None:
        input_names = {item.name for item in session.get_inputs()}
        missing = {"input_ids", "attention_mask", "token_type_ids"} - input_names
        if missing:
            raise ValueError(f"ONNX embedding graph is missing required inputs: {sorted(missing)}")

    def embed_query(self, text: str) -> list[float]:
        """Embed one query text, applying the configured task prefix."""
        return self.embed_documents([self.query_prefix + text])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed raw text documents with the model's pooling and L2 normalization."""
        if not texts:
            return []
        self._ensure_loaded()

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            vectors.extend(self._embed_batch(texts[start : start + _BATCH_SIZE]))
        return vectors

    def _pool(self, hidden_states, attention_mask):
        if self._pooling == "mean":
            mask = attention_mask[..., None].astype(np.float32)
            return (hidden_states * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-12)
        return hidden_states[:, 0, :]

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        encodings = self._tokenizer.encode_batch(texts)
        inputs = {
            "input_ids": np.asarray([encoding.ids for encoding in encodings], dtype=np.int64),
            "attention_mask": np.asarray([encoding.attention_mask for encoding in encodings], dtype=np.int64),
            "token_type_ids": np.asarray([encoding.type_ids for encoding in encodings], dtype=np.int64),
        }
        hidden_states = self._session.run([self._output_name], inputs)[0]
        pooled = self._pool(hidden_states, inputs["attention_mask"])
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.maximum(norms, 1e-12)
        if normalized.shape[1] != self._embedding_dimension:
            raise ValueError(f"Expected {self._embedding_dimension} dimensions, got {normalized.shape[1]}.")
        return normalized.astype(np.float32).tolist()


_EMBEDDING_MODEL = OnnxEmbeddings()
#: Separate Arabic clinical model (ADR 081). Built lazily so the resolved
#: ``ARABIC_EMBEDDING_MODEL`` (and pinned revision) are honored at first use,
#: exactly as ``download_arabic_model_files`` resolves them, and so an
#: English-only process never pays for the second graph.
_ARABIC_EMBEDDING_MODEL: OnnxEmbeddings | None = None
_ARABIC_EMBEDDING_MODEL_LOCK = threading.Lock()


def get_embedding_model() -> OnnxEmbeddings:
    """Return the process-wide embedding model shared by every caller."""
    return _EMBEDDING_MODEL


def get_arabic_embedding_model() -> OnnxEmbeddings:
    """Return the separate Arabic clinical embedding model (ADR 081).

    Uses the same repo, ONNX graph and pinned revision as the downloader.
    """
    global _ARABIC_EMBEDDING_MODEL
    if _ARABIC_EMBEDDING_MODEL is None:
        with _ARABIC_EMBEDDING_MODEL_LOCK:
            if _ARABIC_EMBEDDING_MODEL is None:
                _ARABIC_EMBEDDING_MODEL = OnnxEmbeddings(
                    _arabic_model_name(),
                    pooling="mean",
                    query_prefix=DEFAULT_ARABIC_QUERY_PREFIX,
                    pad_token="<pad>",
                    onnx_file=DEFAULT_ARABIC_ONNX_FILE,
                    revision=DEFAULT_ARABIC_REVISION,
                )
    return _ARABIC_EMBEDDING_MODEL
