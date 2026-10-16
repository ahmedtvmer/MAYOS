"""Hermetic tests for the live player-chat measurement harness (#405)."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage
import pytest

from agent import assistant_graph
from tests.eval import run_player_chat_measurement as measurement
from tests.fakes.chat_model import ScriptedChatModel, StreamErrorTurn
from utils.model_metering import MeteringCallback

MODEL_ID = "deepseek-ai/DeepSeek-V4-Flash"


class _StepClock:
    def __init__(self, values):
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class ProviderTimeoutError(Exception):
    """Named so the harness classifies it as a timeout, like ``OpenAITimeoutError``."""


@pytest.fixture
def measurement_store(tmp_path):
    """A throwaway catalog + ledger store, independent of the configured data root."""
    from database.database_manager import DatabaseManager

    db = DatabaseManager(
        catalog_path=tmp_path / "catalog.db",
        ledgers_dir=tmp_path / "users",
        backups_dir=tmp_path / "backups",
    )
    try:
        yield db
    finally:
        db.catalog_conn.close()


def _turn(content: str, input_tokens: int, cached_input_tokens: int) -> AIMessage:
    return AIMessage(
        content=content,
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": 20,
            "total_tokens": input_tokens + 20,
            "input_token_details": {"cache_read": cached_input_tokens},
        },
    )


def _tool_call(input_tokens: int) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "get_player_weight_trend", "args": {}, "id": "wt-1"}],
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": 5,
            "total_tokens": input_tokens + 5,
            "input_token_details": {"cache_read": 0},
        },
    )


def _session_turns() -> list[AIMessage]:
    return [
        _turn("Keep the setup tight.", 1000, 0),
        _turn("Control the descent.", 1200, 900),
        _turn("Brace before you press.", 1200, 900),
        _turn("Add a small load step.", 1200, 900),
        _turn("Review it next week.", 1200, 900),
    ]


def _model(turns) -> ScriptedChatModel:
    return ScriptedChatModel(
        turns,
        model_name=MODEL_ID,
        chunk_size=6,
        callbacks=[MeteringCallback(MODEL_ID)],
    )


def _five_turns_with_cached(cached_by_turn: dict[int, int]) -> list[AIMessage]:
    return [
        _turn(f"Answer for turn {index}.", 1000 if index == 1 else 1200, cached_by_turn.get(index, 0))
        for index in range(1, 6)
    ]


def test_first_chunk_probe_records_first_output_time():
    model = _model(["Hello there."])
    clock = _StepClock([0.0, 5.0])
    probe = measurement.FirstChunkProbe(model, clock)

    list(probe.stream([HumanMessage(content="hi")]))

    assert probe.samples == [measurement.FirstChunkSample(0.0, 5.0)]
    assert probe.errors == []


def test_run_player_session_reports_first_visible_text_cache_and_cost(measurement_store):
    model = _model(_session_turns())
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model, ledger=ledger, store=measurement_store, max_seconds=None
        )

    assert len(session.turns) == 5
    assert all(turn.status == "ok" for turn in session.turns)
    assert all(len(turn.attempts) == 1 for turn in session.turns)
    assert all(
        turn.attempts[0].first_visible_text_seconds is not None for turn in session.turns
    )

    aggregate = measurement.summarize_session(session)
    assert aggregate["turns_measured"] == 5
    assert aggregate["attempts_total"] == 5
    assert aggregate["model_stream_samples"] == 5
    assert aggregate["first_visible_text_samples"] == 5
    assert aggregate["known_input_tokens"] == 5800
    assert aggregate["known_cached_input_tokens"] == 3600
    assert aggregate["from_turn_2_input_tokens"] == 4800
    assert aggregate["cached_input_share_from_turn_2"] == pytest.approx(0.75)
    assert aggregate["usage_complete"] is True
    assert aggregate["known_cost_per_turn_usd"] > 0
    assert aggregate["median_end_to_end_first_visible_text_seconds"] >= 0
    assert aggregate["median_successful_attempt_visible_latency_seconds"] >= 0
    assert aggregate["median_first_visible_text_within_2_seconds"] in {True, False}


def test_run_player_session_records_a_timeout_turn_as_failed(measurement_store):
    turns = [*_session_turns()]
    turns[1] = ProviderTimeoutError("provider timed out")
    model = _model(turns)
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model, ledger=ledger, store=measurement_store, max_seconds=None
        )

    aggregate = measurement.summarize_session(session)
    assert aggregate["turns_failed"] == 1
    assert aggregate["turns_measured"] == 4
    assert aggregate["attempts_failed"] == 1
    assert aggregate["attempts_timed_out"] == 1
    assert aggregate["attempts_unreported_usage"] == 1
    assert aggregate["usage_complete"] is False
    turn = session.turns[1]
    assert turn.status == "error"
    assert turn.attempts[0].timed_out is True
    assert turn.attempts[0].usage_unknown is True
    assert turn.attempts[0].usage_state == "unknown"


def test_run_player_session_retries_a_transient_turn_and_retains_the_failure(measurement_store):
    model = _model([ProviderTimeoutError("provider timed out"), *_session_turns()])
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model,
            ledger=ledger,
            store=measurement_store,
            max_seconds=None,
            max_turn_attempts=2,
            retry_backoff_seconds=0.0,
        )

    turn = session.turns[0]
    assert turn.status == "ok"
    assert [attempt.attempt for attempt in turn.attempts] == [1, 2]
    assert turn.attempts[0].status == "error"
    assert turn.attempts[0].usage_unknown is True
    # A failed attempt's pipeline error placeholder is not a first token.
    assert turn.attempts[0].first_visible_text_seconds is None
    assert turn.attempts[0].first_model_chunk_seconds is None
    assert turn.attempts[1].status == "ok"

    aggregate = measurement.summarize_session(session)
    assert aggregate["turns_measured"] == 5
    assert aggregate["attempts_total"] == 6
    assert aggregate["attempts_failed"] == 1
    assert aggregate["attempts_unreported_usage"] == 1
    assert aggregate["usage_complete"] is False


def test_run_player_session_does_not_retry_a_non_transient_error(measurement_store):
    model = _model([RuntimeError("boom"), *_session_turns()])
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model,
            ledger=ledger,
            store=measurement_store,
            max_seconds=None,
            max_turn_attempts=3,
            retry_backoff_seconds=0.0,
        )

    assert session.turns[0].status == "error"
    assert len(session.turns[0].attempts) == 1
    aggregate = measurement.summarize_session(session)
    assert aggregate["turns_measured"] == 4
    assert aggregate["attempts_total"] == 5


def test_run_player_session_retains_partial_usage_on_a_failed_attempt(measurement_store):
    model = _model(
        [
            _tool_call(800),
            StreamErrorTurn("partial ", ProviderTimeoutError("busy")),
            _turn("Add a small load step.", 1200, 900),
        ]
    )
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model,
            ledger=ledger,
            store=measurement_store,
            questions=("How do I know when to increase the weight on a lift?",),
            max_seconds=None,
            max_turn_attempts=2,
            retry_backoff_seconds=0.0,
        )

    turn = session.turns[0]
    assert turn.status == "ok"
    assert [attempt.attempt for attempt in turn.attempts] == [1, 2]
    first, second = turn.attempts
    assert first.status == "error"
    assert first.usage_reported is True
    assert first.usage_unknown is False
    assert first.usage_state == "partial"
    assert first.input_tokens == 800
    assert second.status == "ok"

    aggregate = measurement.summarize_session(session)
    assert aggregate["known_input_tokens"] == 2000
    assert aggregate["known_cached_input_tokens"] == 900
    assert aggregate["attempts_partial_usage"] == 1
    assert aggregate["attempts_unreported_usage"] == 0
    assert aggregate["usage_complete"] is False


def test_turn_latency_splits_end_to_end_wait_from_visible_latency():
    failed = measurement.AttemptMeasurement(
        turn=1,
        attempt=1,
        status="error",
        elapsed_seconds=2.0,
        first_visible_text_seconds=0.5,
        first_model_chunk_seconds=None,
        usage_unknown=True,
    )
    recovered = measurement.AttemptMeasurement(
        turn=1,
        attempt=2,
        status="ok",
        elapsed_seconds=4.0,
        retry_backoff_seconds=3.0,
        first_visible_text_seconds=1.5,
        first_model_chunk_seconds=1.0,
    )
    turn = measurement.TurnMeasurement(turn=1, query="q", status="ok", attempts=[failed, recovered])

    # User wait = failed attempt + backoff + the successful answer's own visible latency.
    assert measurement._turn_end_to_end_first_visible_text_seconds(turn) == pytest.approx(6.5)
    assert measurement._successful_attempt_visible_latency(turn) == pytest.approx(1.5)
    assert measurement._turn_end_to_end_seconds(turn) == pytest.approx(9.0)


def test_summarize_session_cached_share_uses_the_turn_2_population(measurement_store):
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            _model(_session_turns()), ledger=ledger, store=measurement_store, max_seconds=None
        )
    aggregate = measurement.summarize_session(session)

    # Independently worked: turns 2-5 carry 4 * 1200 input and 4 * 900 cached.
    assert aggregate["from_turn_2_input_tokens"] == 4800
    assert aggregate["from_turn_2_cached_input_tokens"] == 3600
    assert aggregate["cached_input_share_from_turn_2"] == pytest.approx(3600 / 4800)
    # The all-turn population is a different fraction, so the pair must not be mixed.
    all_turn_share = aggregate["known_cached_input_tokens"] / aggregate["known_input_tokens"]
    assert all_turn_share == pytest.approx(3600 / 5800)
    assert aggregate["cached_input_share_from_turn_2"] != pytest.approx(all_turn_share)


def test_render_markdown_fraction_matches_its_percentage(measurement_store):
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            _model(_session_turns()), ledger=ledger, store=measurement_store, max_seconds=None
        )
    report = measurement.build_report(
        session,
        provider="DeepInfra",
        model=MODEL_ID,
        api_base="https://api.deepinfra.com/v1/openai",
        timeout_seconds=60.0,
        max_seconds=300.0,
    )

    markdown = measurement.render_markdown(report)

    assert "75.0%" in markdown
    assert "(3600/4800 input tokens from turn 2 onward" in markdown
    assert "(3600/5800" not in markdown


def test_run_player_session_restores_the_configured_llm(measurement_store):
    original = assistant_graph.llm
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        measurement.run_player_session(
            _model(_session_turns()[:1]), ledger=ledger, store=measurement_store, max_seconds=None
        )
    assert assistant_graph.llm is original


def test_build_report_and_markdown_name_the_identity_and_samples(measurement_store):
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            _model(_session_turns()), ledger=ledger, store=measurement_store, max_seconds=None
        )
    report = measurement.build_report(
        session,
        provider="DeepInfra",
        model=MODEL_ID,
        api_base="https://api.deepinfra.com/v1/openai",
        timeout_seconds=60.0,
        max_seconds=300.0,
    )

    assert report["report_version"] == 2
    assert report["provider"] == "DeepInfra"
    assert report["model"] == MODEL_ID
    assert report["base_commit"]
    assert report["retry_policy"]["measurement"] != report["retry_policy"]["production"]
    assert report["aggregate"]["turns_total"] == 5
    assert len(report["turns"]) == 5
    assert all(len(turn["attempt_rows"]) == 1 for turn in report["turns"])

    # A full, successful five-turn session with nonzero reuse demonstrates the
    # cache/session criterion; the recorded-token share is not called a bound.
    cache_criterion = report["acceptance_criteria"]["nonzero_cached_share_from_turn_2_full_session"]
    assert cache_criterion["required_turns"] == 5
    assert cache_criterion["turns_measured"] == 5
    assert cache_criterion["status"] == "MET"

    markdown = measurement.render_markdown(report)
    assert "DeepInfra" in markdown
    assert MODEL_ID in markdown
    assert "Cached input share from turn 2" in markdown
    assert "End-to-end first text" in markdown
    assert "Per-attempt detail" in markdown
    assert "Successful-attempt visible latency" in markdown
    assert "provider TTFT" not in markdown
    assert "share among recorded tokens" in markdown
    assert "## Acceptance criteria" in markdown


def test_acceptance_criteria_marks_cache_session_partial_when_a_turn_fails(measurement_store):
    turns = [*_session_turns()]
    turns[1] = ProviderTimeoutError("provider timed out")
    model = _model(turns)
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model, ledger=ledger, store=measurement_store, max_seconds=None
        )
    report = measurement.build_report(
        session,
        provider="DeepInfra",
        model=MODEL_ID,
        api_base="https://api.deepinfra.com/v1/openai",
        timeout_seconds=60.0,
        max_seconds=300.0,
    )

    cache_criterion = report["acceptance_criteria"]["nonzero_cached_share_from_turn_2_full_session"]
    # Four of five turns succeeded, so the five-turn criterion is not demonstrated.
    assert cache_criterion["turns_measured"] == 4
    assert cache_criterion["status"] == "PARTIAL / NOT DEMONSTRATED"

    markdown = measurement.render_markdown(report)
    assert "PARTIAL / NOT DEMONSTRATED" in markdown
    # The recorded-token share is not a lower bound; its overall value is unknown.
    assert "overall share unknown — some usage unreported" in markdown


def test_acceptance_criteria_requires_turn_2_reuse_not_only_later_reuse(measurement_store):
    # Turn 2 records zero cached tokens; reuse appears only on turn 5. The positive
    # aggregate turn-2-onward share must not, by itself, certify the criterion.
    model = _model(_five_turns_with_cached({5: 900}))
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model, ledger=ledger, store=measurement_store, max_seconds=None
        )
    report = measurement.build_report(
        session,
        provider="DeepInfra",
        model=MODEL_ID,
        api_base="https://api.deepinfra.com/v1/openai",
        timeout_seconds=60.0,
        max_seconds=300.0,
    )

    assert report["aggregate"]["turns_measured"] == 5
    assert report["aggregate"]["cached_input_share_from_turn_2"] > 0
    cache_criterion = report["acceptance_criteria"]["nonzero_cached_share_from_turn_2_full_session"]
    assert cache_criterion["turn_2_cached_input_tokens"] == 0
    assert cache_criterion["status"] == "PARTIAL / NOT DEMONSTRATED"


def test_acceptance_criteria_marks_met_with_turn_2_reuse_even_if_later_turns_miss(measurement_store):
    # Reuse is recorded on logical turn 2; turns 3-5 miss cache and that is allowed.
    model = _model(_five_turns_with_cached({2: 900}))
    with measurement_store.open_ledger("ttft_probe_player") as ledger:
        session = measurement.run_player_session(
            model, ledger=ledger, store=measurement_store, max_seconds=None
        )
    report = measurement.build_report(
        session,
        provider="DeepInfra",
        model=MODEL_ID,
        api_base="https://api.deepinfra.com/v1/openai",
        timeout_seconds=60.0,
        max_seconds=300.0,
    )

    cache_criterion = report["acceptance_criteria"]["nonzero_cached_share_from_turn_2_full_session"]
    assert cache_criterion["turn_2_cached_input_tokens"] == 900
    assert cache_criterion["status"] == "MET"


def test_provider_name_maps_deepinfra_host():
    assert measurement._provider_name("https://api.deepinfra.com/v1/openai") == "DeepInfra"
    assert measurement._provider_name("https://example.invalid/v1/openai") == "example.invalid"


def test_main_without_key_does_not_run(capsys, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert measurement.main([]) == 2
    assert "LLM_API_KEY not set" in capsys.readouterr().err
