# Codex briefs: P1 and P2, first wave

Briefs for the `codex-delegate` skill, one issue each. Dispatch with:

    node .claude/skills/codex-delegate/scripts/relay.mjs --brief plans/codex-briefs/<n>.xml --cd <worktree>

Each issue runs in its own git worktree off `feat/web-into-app`. Before landing an issue:
sync with the base branch, run `/code-review`, re-run the gates, then commit.

## Waves (grouped so parallel runs touch different areas)

| Wave | Issue | Area | Status |
|------|-------|------|--------|
| 1 | #229 band/bodyweight working sets | program generation, substitutes | landed |
| 1 | #227 MAYOS-authored staples | exercise library seed | landed |
| 1 | #238 Training profile editing | profile API + Flutter Settings | landed |
| 1 | #243 shared evaluation-report gate | Coach AI / Checkpoint gate | landed |
| 1 | #154 coach sign-up with invite code | registration, invites, auth screens | landed |
| 1 | #202 lapsing-first roster order | coach roster | landed |
| 2 | #226 Replace list ranking | exercise search (after #227, #229) | landed |
| 2 | #241 deload undo/apply via assistant | assistant router, commit (after #238) | landed |
| 2 | #155 become a coach from onboarding | Flutter onboarding + Settings (after #154, #238) | landed |

Later chains: #230 → #232 → #233/#234 → #235; #238 → #239, #242; #202 → #203 → #204.

## Wave 1 review notes

- All six went through Codex, two-axis `/code-review`, one Codex correction round (#202 needed only doc fixes), then landing in order #202, #243, #154, #238, #229, #227 with per-merge gates. Combined branch: ruff clean, pytest 2264 passed, flutter test 742 passed.
- Owner decisions taken: #229 keeps ExerciseDB "weighted" rows (weighted dips/chin-ups) out for Commercial gym, allows them for Home gym. #227 adds the alias "hip thrust" to 3562 so the plain query still resolves to the Barbell Hip Thrust.
- Needs owner review: #227 authored instruction texts (database/exercise_library/authored.py), especially the Kelso shrug (cable, chest on an incline bench).
- Known flaky test, pre-existing: tests/test_google_sign_in.py::test_concurrent_completion_creates_one_account_and_one_link (both racers sometimes succeed for the same account).
- #238 refuses unknown profile fields (422); the legacy Streamlit editor's Save will now fail until #242 removes it.

## Wave 2 review notes

- #226, #241, #155 went through Codex, two-axis `/code-review` and one Codex correction round, then landed in order #226, #155, #241. Combined branch: ruff clean, pytest 2270 passed (only the known flaky Google sign-in race failed once), flutter analyze clean, flutter test 743 passed.
- Full-suite collision check caught two regressions after landing, both fixed before pushing: #226's find_exercises_by_name signature needed the public-surface snapshot refreshed; #241 had widened the clinical guard ("my <joint> hurts"), breaking tier-0 context gating, so the guard was restored and its test now asserts pain messages never become a Deload command.
- #241 safety: pain messages never route to the Deload action, Arabic patterns are anchored and negation-aware, the clinical check runs first. Ledger schema v18 -> v19 adds deload_choices.
- #155 uses "I'm a coach — enter coach code" (CONTEXT.md avoids "invite code"), not the issue's literal label.
- Pre-existing, out of scope: the clinical guard misses compound messages such as "my shoulder is injured, apply the deload" (routes to Q&A; same on the base branch).

## Environment prerequisites

- Network access must allow `api.openai.com` and `auth.openai.com`, then `codex login --device-auth`.
- Flutter SDK is not installed in the cloud container; mobile gates need it.
- Python deps: `uv pip install -r requirements.txt pytest ruff`. Tests need `data/processed_exercises.csv` (git-ignored) and a seeded `db/catalog.db` (`scripts/intialize_db.py` then `scripts/seed_vectors.py`, as in CI); run with `SKIP_LLM_LOAD=true HF_HUB_OFFLINE=1` once the embedding model is cached.

Delete this folder once the wave has landed.
