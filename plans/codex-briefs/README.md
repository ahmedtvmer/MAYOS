# Codex briefs: P1 and P2, first wave

Briefs for the `codex-delegate` skill, one issue each. Dispatch with:

    node .claude/skills/codex-delegate/scripts/relay.mjs --brief plans/codex-briefs/<n>.xml --cd <worktree>

Each issue runs in its own git worktree off `feat/web-into-app`. Before landing an issue:
sync with the base branch, run `/code-review`, re-run the gates, then commit.

## Waves (grouped so parallel runs touch different areas)

| Wave | Issue | Area | Status |
|------|-------|------|--------|
| 1 | #229 band/bodyweight working sets | program generation, substitutes | queued |
| 1 | #227 MAYOS-authored staples | exercise library seed | queued |
| 1 | #238 Training profile editing | profile API + Flutter Settings | queued |
| 1 | #243 shared evaluation-report gate | Coach AI / Checkpoint gate | queued |
| 1 | #154 coach sign-up with invite code | registration, invites, auth screens | queued |
| 1 | #202 lapsing-first roster order | coach roster | queued |
| 2 | #226 Replace list ranking | exercise search (after #227, #229) | queued |
| 2 | #241 deload undo/apply via assistant | assistant router, commit (after #238) | queued |
| 2 | #155 become a coach from onboarding | Flutter onboarding + Settings (after #154, #238) | queued |

Later chains: #230 → #232 → #233/#234 → #235; #238 → #239, #242; #202 → #203 → #204.

## Environment prerequisites

- Network access must allow `api.openai.com` and `auth.openai.com`, then `codex login --device-auth`.
- Flutter SDK is not installed in the cloud container; mobile gates need it.
- Python deps: `uv pip install -r requirements.txt pytest ruff`; `huggingface.co` is blocked, so run
  tests with `SKIP_LLM_LOAD=true`.

Delete this folder once the wave has landed.
