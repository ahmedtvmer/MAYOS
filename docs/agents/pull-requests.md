# Master changes through pull requests

ADR 098's amendment of 2026-11-02 requires this flow for Thomas and the
orchestrator as well as the factory. The repository files prepare protection;
they do not activate it. Applying the ruleset and recording the live acceptance
evidence below remain orchestrator work after Thomas says yes in chat.

## Branch, review and merge

1. Read the GitHub issue and its blockers using [the issue tracker
   guidance](issue-tracker.md). Start an isolated worktree branch from current
   `origin/master`; never implement on `master`. For example, from the main
   checkout, replacing `N` with the ticket number:

   ```sh
   git fetch origin
   git worktree add ../MAYOS-N -b issue-N origin/master
   ```

2. Delegate implementation under `AGENTS.md`. The implementer edits the worktree
   and does not commit. After completion, the orchestrator reviews the final
   diff against the acceptance criteria and verifies relevant CI results.
   Follow [backend test guidance](backend-tests.md) for backend changes. Any
   restriction on running programs on the workstation still applies; use CI
   or the approved server instead.

3. The orchestrator commits the reviewed files on `issue-N` and pushes that
   branch. From its worktree, create a pull request targeting `master`. Write
   the exact PR description, validation and `Closes #N` to a body file first:

   ```sh
   git push -u origin issue-N
   gh pr create --base master --head issue-N --title "Describe the change" --body-file PR_BODY_FILE
   gh pr checks PR_NUMBER --watch
   ```

   Replace `PR_BODY_FILE` with the prepared file path and `PR_NUMBER` with the
   returned PR number. Do not add the temporary body file to the commit.
   Check all CI, including checks beyond the three required ones. The ruleset
   requires the branch to be up to date; if master advances, merge current
   `origin/master` into the worktree branch, push, and wait for fresh CI and
   approval. Reviewable pushes dismiss stale approvals.

4. Obtain one approval. Changes matching `.github/CODEOWNERS` require Thomas
   (`@ahmedtvmer`) as code owner. Those paths are also denied to the factory by
   ADR 098: a factory run must stop with `factory-blocked` before opening a PR
   touching them. CODEOWNERS enforces review, not a file-write prohibition.
   It does not replace the factory's separate deny list.

5. After review and green CI, the orchestrator merges an authorized PR:

   ```sh
   gh pr merge PR_NUMBER --squash --match-head-commit REVIEWED_HEAD_SHA
   ```

   Replace `REVIEWED_HEAD_SHA` with the exact head commit reviewed. The factory
   App never approves or merges its own work. Keep its credential separate from
   Thomas's admin credential. Thomas can merge his own PR using his sole-admin
   bypass because GitHub does not allow authors to approve their own PRs:

   ```sh
   gh pr merge PR_NUMBER --admin --squash --match-head-commit REVIEWED_HEAD_SHA
   ```

   This is an explicit owner action after reviewing the exact head and CI; the
   orchestrator does not silently use `--admin` to get past a failed gate.
   The bypass permits PR merges only, never direct pushes to master.

## Required check names

| Workflow source | Required check context |
| --- | --- |
| `.github/workflows/ci.yml`, job `test` | `Unit, Concurrency & Telemetry Tests` |
| `.github/workflows/ci.yml`, job `image-smoke` | `Production Image Smoke Test` |
| `.github/workflows/mobile.yml`, job `test` | `Mobile Tests` |

These are job display names, not workflow titles. The mobile job is explicitly
named `Mobile Tests`; without that name its context would be `test`. Both
workflows trigger on every PR to master. Mobile setup and tests run only when
mobile files or that workflow change; the job still reports on other PRs.
Preserve these contexts if the workflows change.

`.github/dependabot.yml` checks GitHub Actions weekly. This also covers commit
pins on `mayos-factory` reusable workflows once the thin callers are added;
Thomas reviews their proposed pin bumps.

## Activation: owner confirmation required

Do not run the commands in this section during implementation. The
orchestrator must first confirm blockers #517, #606, #603 and #580 are resolved,
this PR's files are on master, and all three named checks are green and visible
on a recent PR. In particular, the mobile job rename must be merged before
requiring `Mobile Tests`. Show Thomas the exact
[ruleset payload](master-ruleset.json) and obtain his yes in chat before applying
it. Do not treat approval of a code PR as permission to change repository rules.

The sole bypass entry is repository role `5` (admin), in `pull_request` mode.
Thomas must remain the only repository admin. Do not add the factory App,
write/maintain roles, deploy keys or an `always` bypass. The factory App has no
administration permission. Check repository access in Settings before applying;
adding another admin later would also grant that admin the bypass.

Run from this repository with Thomas's administration-authorized GitHub CLI
session. `{owner}` and `{repo}` are resolved by `gh` from this checkout's remote
(rather than relying on an old repository spelling in the README). First list
existing rulesets and inspect any rules already applying to master:

```sh
gh api 'repos/{owner}/{repo}/rulesets' --paginate
gh api 'repos/{owner}/{repo}/rules/branches/master'
```

If no ruleset with this name exists, apply the exact checked-in payload:

```sh
gh api --method POST 'repos/{owner}/{repo}/rulesets' --input docs/agents/master-ruleset.json
```

Record the returned `id` in #608. Do not repeat POST on retries: if the ruleset
already exists, inspect it first and, only within Thomas's confirmed scope,
update that id with the same payload (replace `RULESET_ID`):

```sh
gh api --method PUT 'repos/{owner}/{repo}/rulesets/RULESET_ID' --input docs/agents/master-ruleset.json
```

On an API validation or permission error, stop and inspect the response; do not
weaken the payload to make the request succeed. Other rulesets and legacy branch
protection can impose additional restrictions; inspect them if a merge is still
blocked after this ruleset's requirements are met.

## Verify and record live evidence

These are post-activation checks for the orchestrator, not implementation
results. No live protection or merge behavior was exercised when these files
were prepared. Keep #608 open until the following evidence is recorded there.

Read back the ruleset using the owner session (so bypass actors are visible),
then inspect effective rules and a recent PR's actual check-run names:

```sh
gh api 'repos/{owner}/{repo}/rulesets/RULESET_ID'
gh api 'repos/{owner}/{repo}/rules/branches/master'
gh api 'repos/{owner}/{repo}/commits/PR_HEAD_SHA/check-runs' --paginate --jq '.check_runs[] | {name, conclusion, app: .app.slug}'
gh pr checks PR_NUMBER
```

Replace `PR_HEAD_SHA` with the PR's head SHA. Confirm `active`, only
`refs/heads/master`, one admin-role bypass in `pull_request` mode, deletion and
non-fast-forward rules, one approval with code-owner review, and all three exact
contexts above. Confirm the check runs originate from GitHub Actions.

Use disposable worktrees and harmless probe commits for the behavioral checks;
run them only after the ruleset readback is correct. Do not force-push or delete
master as a probe.

1. **Direct push rejected, including for the owner.** In a fresh disposable
   branch at current `origin/master`, create an empty commit and attempt a real
   push with Thomas's credential:

   ```sh
   git commit --allow-empty -m "Verify master PR requirement (#608)"
   git push origin HEAD:refs/heads/master
   ```

   Record the remote rejection and confirm master did not advance. A no-op
   push or `--dry-run` does not prove server enforcement. If this unexpectedly
   succeeds, stop and report the failure; do not mark protection verified.

2. **Owner merges own PR.** Thomas opens a PR with a harmless documentation
   change, waits for the three checks to pass, reviews it, and uses the explicit
   `gh pr merge ... --admin` command above with its reviewed SHA. Record the PR
   URL, check results and successful merge. This proves the PR-only bypass works
   despite the missing self-approval.

3. **Failing required check blocks ordinary merge.** Open a disposable PR with
   a deliberately failing Flutter test under `mobile/test/`, so the real
   `Mobile Tests` job runs and fails. Have Thomas approve the current head to
   isolate the check gate from the approval gate. Using a non-bypass write
   identity (for example the factory App session for this controlled probe),
   attempt an immediate merge without `--admin` or `--auto`:

   ```sh
   gh pr checks PR_NUMBER
   gh pr merge PR_NUMBER --squash --match-head-commit PR_HEAD_SHA
   ```

   This is a controlled acceptance probe, not permission for the factory to
   merge ordinary work. Record the failed required check, rejected merge and
   still-open PR; then close the probe without merging its failing test.
   If the merge succeeds, stop and report the failed acceptance criterion.

GitHub references: [ruleset API](https://docs.github.com/en/rest/repos/rules),
[rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets),
[`gh api`](https://cli.github.com/manual/gh_api),
[`gh pr create`](https://cli.github.com/manual/gh_pr_create),
[`gh pr checks`](https://cli.github.com/manual/gh_pr_checks), and
[`gh pr merge`](https://cli.github.com/manual/gh_pr_merge).
