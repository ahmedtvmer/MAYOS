@AGENTS.md

## Claude orchestrator overrides

These apply to Claude Code sessions acting as orchestrator. Where they differ from AGENTS.md, they take precedence. Implementers ignore this section.

### Implementer and reviewer (owner choice, 2026-11-17)

- **Implementer**: OpenCode Go `opencode-go/glm-5.3-flash`, through the `opencode-delegate` skill. This replaces `codex-delegate` and `gpt-6-luna` from the Delegation policy above:
  ```
  node C:/Users/Thomas/.claude/skills/opencode-delegate/scripts/relay.mjs --brief <brief> --model opencode-go/glm-5.3-flash --cd F:/MAYOS-<worktree> --timeout 2h --out-dir <dir>
  ```
- **Correction rounds** resume the implementer's own session instead of starting fresh, so it keeps its context. Send only a delta brief. The session id (`ses_…`) is in the run's `result.json`:
  ```
  node C:/Users/Thomas/.claude/skills/opencode-delegate/scripts/relay.mjs --brief <delta-brief> --session <ses_id> --model opencode-go/glm-5.3-flash --cd F:/MAYOS-<worktree> --timeout 2h --out-dir <dir>
  ```
- **Debate review**: use the `/debate-review` skill. It replaces the hand-written review briefs and Sol (`gpt-6.1-sol`). The two debaters are **the orchestrator (Claude) and Kimi**, OpenCode Go `opencode-go/kimi-k2.7-code`, run read-only. Kimi never debates itself or another model.
  - Claude reviews the diff independently and challenges Kimi's findings with evidence. Kimi challenges Claude's in turn. Only findings that survive the debate count.
  - Each finding is graded P1/P2 (blocking) or P3 (nonblocking). The review ends with "Overall: merge" or "Overall: fix first".
  - Kimi's read-only run, if the skill needs a manual command:
    ```
    node C:/Users/Thomas/.claude/skills/opencode-delegate/scripts/relay.mjs --brief <review-brief> --model opencode-go/kimi-k2.7-code --read-only --cd F:/MAYOS-<worktree> --timeout 45m --out-dir <dir>
    ```
- Both are Flash- or code-tier models. Keep each brief to one specific task with the context it needs. Split large tickets into server and app parts. Check diffs more strictly against every acceptance criterion, and watch for tests being weakened instead of code being fixed.
- Every brief says that tests must not run locally. The first line of the report must still be `ROLE: implementer #<ticket>`.
- **Numbers in every brief.** Each brief names the exact ledger migration version and Feature list release to use: the next free version on the branch's master base, and the unshipped release from `docs/agents/issue-tracker.md`. No placeholder or no-op migrations: a no-op step can stamp a database past another branch's real migration, so that migration never runs. If another branch lands first, the orchestrator renumbers at merge.
- **Usage limits.** If an implementer or reviewer run stops on a provider usage limit, resume the same session with `--session <ses_id>` once the limit resets, without asking. If the reset is more than a few hours away, tell Thomas the reset time and ask whether to wait or switch model.

### Orchestrator limits

- The orchestrator never writes the fix itself, even when the implementer struggles. It may resolve merge conflicts and write its own tooling scripts.
- Tests run only on the test server (`deploy@169.58.154.182`, via WSL), one server run at a time.

### Ticket flow (owner-agreed, 2026-11-17)

1. **Decide.** Thomas and the orchestrator settle the design together; then the orchestrator files the GitHub issue.
2. **Implement.** GLM 5.3 Flash (OpenCode Go) works from the orchestrator's brief in the ticket's own worktree. Corrections continue in the same session (`--session`).
3. **Check.** The orchestrator confirms the report starts with the ROLE line and reads the diff against every acceptance criterion.
4. **Quick server check.** Only the affected tests run on the server. Any failure goes back to GLM.
5. **Debate review (`/debate-review`).** The orchestrator debates Kimi K2.7 Code, which runs read-only, for at most 3 rounds. After round 3, only P1s and P2s a normal Player would hit block the merge. The orchestrator makes that call and writes its reasoning into a follow-up issue, which takes the remaining findings and links back to the ticket.
6. **Full suite per batch.** Green, reviewed tickets go onto one combined branch for a single full Python and Flutter run. Fall back to per-ticket suites only to find a failure.
7. **Land.** Merge each PR to master, deploy staging, then send Thomas what changed and what to test.
8. **Production.** Only with Thomas's explicit OK.
