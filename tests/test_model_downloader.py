"""Unit tests for the hardened model-downloader helpers (no GGUF loads)."""


def test_resolve_model_path_env_override(tmp_path, monkeypatch):
    from utils import model_downloader as md

    ghost = tmp_path / "custom.gguf"
    ghost.write_bytes(b"fake")
    monkeypatch.setenv("MODEL_PATH", str(ghost))
    assert md.resolve_model_path("production") == str(ghost)
    monkeypatch.delenv("MODEL_PATH")
    # The repo .env (auto-loaded via the agent import chain) may point at real
    # files; neutralize both knobs so resolution is fully hermetic.
    monkeypatch.setenv("JUDGE_MODEL_PATH", str(tmp_path / "missing-judge.gguf"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    assert md.resolve_model_path("judge") == str(tmp_path / "Qwen3.5-9B-Q4_K_M.gguf")


def test_unknown_model_type_rejected():
    import pytest

    from utils import model_downloader as md

    with pytest.raises(ValueError):
        md.resolve_model_path("nope")
    with pytest.raises(ValueError):
        md.get_or_download_model_path("nope")


def test_testing_mode_returns_mocks_without_files(tmp_path, monkeypatch):
    from utils import model_downloader as md

    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "missing.gguf"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "models"))
    md._llm_instance = None
    md._judge_llm_instance = None
    try:
        assert isinstance(md.get_llm(), md.MockSafeChatLlamaCpp)
        assert isinstance(md.get_judge_llm(), md.MockSafeChatLlamaCpp)
    finally:
        md._llm_instance = None
        md._judge_llm_instance = None


def test_lazy_proxies_never_load_on_repr_or_dunder():
    from utils import model_downloader as md

    assert md._llm_instance is None and md._judge_llm_instance is None
    assert "loaded=False" in repr(md.llm)
    assert "loaded=False" in repr(md.judge_llm)
    assert md._llm_instance is None and md._judge_llm_instance is None
    import pytest

    with pytest.raises(AttributeError):
        _ = md.llm.__wrapped__
    assert md._llm_instance is None


def test_mock_public_stream_matches_production_contract():
    """The graph consumes ``llm.stream`` via ``chunk.content``; a repr must never leak."""
    import asyncio

    from langchain_core.messages import AIMessageChunk

    from utils import model_downloader as md

    mock = md.MockSafeChatLlamaCpp()
    chunks = list(mock.stream("hi"))
    assert len(chunks) > 3, "streaming must be incremental, not one blob"
    assert all(isinstance(chunk, AIMessageChunk) for chunk in chunks)
    # Exactly the idiom used by stream_assistant_turn.
    consumed = "".join(chunk.content if hasattr(chunk, "content") else str(chunk) for chunk in chunks)
    assert "Romanian deadlifts" in consumed
    assert "ChatGenerationChunk" not in consumed and "AIMessageChunk(" not in consumed
    assert "Romanian deadlifts" in asyncio.run(mock.ainvoke("hi")).content


def test_skip_llm_load_is_not_a_mock_switch(monkeypatch):
    import sys as _sys

    from utils import model_downloader as md

    # Remove the pytest fallback from the equation entirely.
    monkeypatch.delitem(_sys.modules, "pytest", raising=False)
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("SKIP_LLM_LOAD", "true")
    assert md._should_use_mock("production") is False


def test_testing_env_forces_mock_unconditionally(monkeypatch):
    from utils import model_downloader as md

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TESTING", "1")
    assert md._should_use_mock("production") is True


def test_ci_mocks_only_when_model_file_is_absent(monkeypatch, tmp_path):
    from utils import model_downloader as md

    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("MODEL_PATH", str(tmp_path / "missing.gguf"))
    monkeypatch.setenv("MODEL_DIR", str(tmp_path / "missing_dir"))
    assert md._should_use_mock("production") is True
    ghost = tmp_path / "present.gguf"
    ghost.write_bytes(b"x")
    monkeypatch.setenv("MODEL_PATH", str(ghost))
    assert md._should_use_mock("production") is False


def test_file_lock_blocks_second_acquirer_then_releases(tmp_path):
    import pytest

    from utils import model_downloader as md

    lock = tmp_path / "model.lock"
    with md._file_lock(lock, timeout_s=1.0, poll_s=0.05):
        # A second open file description cannot take the lock while held.
        with pytest.raises(TimeoutError):
            with md._file_lock(lock, timeout_s=0.2, poll_s=0.05):
                pass
    # Released on context exit: immediately re-acquirable.
    with md._file_lock(lock, timeout_s=1.0, poll_s=0.05):
        pass


def test_stale_lock_file_does_not_block_flock(tmp_path):
    from utils import model_downloader as md

    if md.fcntl is None:  # pragma: no cover - Windows fallback blocks by design
        return
    lock = tmp_path / "model.lock"
    lock.write_text("")  # leftover file from a crashed download
    # flock cares about holders, not file existence: acquisition succeeds.
    with md._file_lock(lock, timeout_s=0.5, poll_s=0.05):
        pass


def test_lockfile_fallback_acquires_and_cleans_up(tmp_path, monkeypatch):
    from utils import model_downloader as md

    monkeypatch.setattr(md, "fcntl", None)
    lock = tmp_path / "fallback.lock"
    with md._file_lock(lock, timeout_s=0.5, poll_s=0.05):
        assert lock.exists()
    assert not lock.exists()


def test_lockfile_fallback_times_out_when_held(tmp_path, monkeypatch):
    import pytest

    from utils import model_downloader as md

    monkeypatch.setattr(md, "fcntl", None)
    lock = tmp_path / "fallback.lock"
    with md._file_lock(lock, timeout_s=1.0, poll_s=0.05):
        with pytest.raises(TimeoutError):
            with md._file_lock(lock, timeout_s=0.2, poll_s=0.05):
                pass
