# Arabic coach evaluation (#248)

The reviewed question fixture is `tests/eval/datasets/arabic_coach_templates.json`. It retains the 16 base IDs, English originals where present, the exact #245 Arabic wording, existing Egyptian variants, answer types and truth keys. Its `source_review_status` copies the existing review metadata; it does not record a new review.

`tests/eval/datasets/arabic_coach_facts_seed_248.json` contains the synthetic Player facts and roster. The runner computes truth directly from those facts. Single-player runs call `run_coach_evaluation.run_suite`, which uses the production `coach_ai.render_context`, `coach_ai.build_messages`, extraction path, and `coach_rubric`. Roster runs in this #248 evaluation use an explicitly harness-built briefing; they do not exercise the production roster conversation. The production `POST /coach/assistant/roster` route has its separate #311 evaluation in `tests/eval/run_coach_roster_evaluation.py`. `{needle}` resolves to `PLR-003` from that seeded roster.

There are 16 base runs and 5 separately identified Egyptian input variants. Variant rows keep their base template ID and use `variant_identity: "egyptian"`; they do not increase the base count. `reports/arabic_coach_eval_mock.json` is the deterministic plumbing report, not a hosted model result. The Arabic report never participates in the Coach AI enablement gate or changes `reports/coach_ai_eval.json`.

## Reproduction

From the repository root, activate the main checkout's `.venv`. Run from a temporary working directory so the existing application logger writes inside `/tmp`:

```sh
MAYOS_REPO_ROOT="$(git rev-parse --show-toplevel)"
mkdir -p /tmp/mayos-arabic-coach-eval/run
cd /tmp/mayos-arabic-coach-eval/run
python "$MAYOS_REPO_ROOT/tests/eval/run_arabic_coach_evaluation.py" --mock --write-report "$MAYOS_REPO_ROOT/reports/arabic_coach_eval_mock.json"
```

From a new shell at the repository root, the configured hosted coach model run that records today's results is:

```sh
MAYOS_REPO_ROOT="$(git rev-parse --show-toplevel)"
cd /tmp/mayos-arabic-coach-eval/run
LLM_MAX_RETRIES=8 LLM_REQUEST_TIMEOUT=120 python "$MAYOS_REPO_ROOT/tests/eval/run_arabic_coach_evaluation.py" --live --write-report "$MAYOS_REPO_ROOT/reports/arabic_coach_eval.json"
```

The live command uses the repo's configured coach model and `.env`; run it once, sequentially. The report records `mode`, `run_status`, model identity, prompt hash, per-case expected and observed outcomes, and check results. `run_status` distinguishes `completed`, `incomplete` and `runner_error`; runner errors include their type and a redacted, length-limited message. A runner error exits with code 2; a completed run with failed checks exits with code 1. A mock report may show deterministic scoring passing, but its top-level `pass` remains false and `production_gate_eligible` is always false. A live report's `pass` is true only when every expected run completes and passes its checks.

Output-language checks require Western digits. Single-player Egyptian Arabic and roster simple standard Arabic use lexical heuristics only: single-player output must include an Arabic-script answer and a listed Egyptian marker; roster output must include Arabic script and avoid those markers. These checks can miss dialect cues or flag words shared with standard Arabic; they are not a linguistic judge and do not rewrite retained input wording.
