## Agent skills

### Issue tracker

Specs and implementation tickets live in GitHub Issues.
See `docs/agents/issue-tracker.md`.

### Domain docs

This is a single-context repo. Read `CONTEXT.md` and relevant decisions
in `DECISIONS.md`. See `docs/agents/domain.md`.

## Delegation policy

GitHub issues are the implementation plan and source of truth.

For implementation tickets, use the `opencode-delegate` skill and delegate
implementation to the configured OpenCode implementer.

Do not create a redundant implementation plan before delegation unless the
issue is ambiguous, incomplete, conflicts with the codebase, or requires an
unresolved architectural decision.

For a sufficiently specified issue:

1. Read the issue and its blockers.
2. Read only the architectural/project context required to understand it.
3. Delegate implementation immediately using `opencode-delegate`.
4. Do not monitor, poll, inspect partial output, or supervise the delegate
   while it works. Wait for completion.
5. On completion, inspect the final report and `git diff`.
6. Review the implementation against every acceptance criterion.
7. Run or verify relevant tests.
8. Request a targeted delegated correction only when necessary.

Prefer delegation over direct implementation for implementation tickets.

The orchestrator should spend tokens on judgment, architectural correctness,
and final review—not on duplicating work already specified by the issue or
performed by the implementer.