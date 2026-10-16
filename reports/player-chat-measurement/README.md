# Player chat measurement reports

Paired JSON + Markdown reports from `tests/eval/run_player_chat_measurement.py`,
run against the real `agent.assistant_graph.stream_assistant_turn` generator.

## report_version 2 (corrected per-attempt accounting)

- `player_chat_measurement_20261015T211659Z.{json,md}` — the corrected evidence.
  Every attempt of a logical turn is retained with its elapsed time, retry
  backoff, error and known usage. Latency is split into the end-to-end user wait
  (to the successful answer's first visible text, including prior failed attempts
  and backoff) and the successful attempt's **visible latency** (its own
  first-visible text, which includes graph/output work and is not a pure
  provider/model-stream TTFT; first model chunk time is reported separately). A
  failed attempt's pipeline error placeholder is not counted as a first token.
  Usage totals sum every known row, **including the known rows of partial
  attempts**; only the unreported remainder of a failed attempt is unknown and
  excluded (never counted as zero), so the known token and cost sums are a lower
  bound when any usage is unreported. The recorded-token cache share is **not** a
  lower bound: it is the fraction among reported tokens, and the overall share is
  unknown while usage is incomplete. This run: 4/5 turns measured, 10 attempts
  (6 failed, 4 unknown + 2 partial usage), median user wait 16.149 s, median
  successful-attempt visible latency 12.489 s, cached share from turn 2 53.0%
  (4864/9172, share among recorded tokens), known cost $0.000780 (lower bound).

  Acceptance criteria (from #405 / #192):

  - **Median time to first token ≤ 2.0 s — UNMET.** Median user wait 16.149 s;
    median successful-attempt visible latency 12.489 s. Provider-bound.
  - **Nonzero cached share from turn 2 in a 5-turn live session, with cost per
    turn — PARTIAL / NOT DEMONSTRATED.** Five turns were attempted but only four
    succeeded (turn 1 exhausted its retries); successful turns 2 and 3 recorded
    zero cached tokens, and later reuse is observed (turns 4/5). The aggregate
    53.0% is therefore a share among recorded tokens, not evidence of nonzero
    reuse at turn 2 nor of five successful answers. The automatic status requires
    recorded nonzero cache reuse on logical turn 2 (later misses are allowed); a
    positive aggregate share alone is not sufficient.
  - **Byte-identical stable prompt prefix — N/A** (no prompt-order change).

## report_version 1 (historical — lossy final-attempt-only accounting)

These four reports are kept as historical evidence only. They were produced by
the earlier reviewed candidate and record only the *final* attempt of each
logical turn: a failed or retried attempt's elapsed time, retry backoff, error
and model usage were discarded when a later attempt replaced it. Their totals
therefore understate latency and cost, and a turn that retried can appear with
zero failures. Do not treat their `total_*` fields as complete.

- `player_chat_measurement_20261015T191612Z.{json,md}`
- `player_chat_measurement_20261015T191852Z.{json,md}`
- `player_chat_measurement_20261015T192036Z.{json,md}`
- `player_chat_measurement_20261015T192446Z.{json,md}` — its turn 3 used two
  attempts but reports only the successful attempt's 9.740 s and usage.

Missing prior-attempt data for those runs was not fabricated; the raw
per-attempt records were never captured. Use the version-2 report above for
accounting that retains every attempt.
