# Issue tracker: GitHub

Specs and tickets live as GitHub issues in this repo. Use `gh` from the repo root.

For implementation branches, pull requests, CI and merges to master, follow
[the pull request flow](pull-requests.md). Master ruleset activation requires
Thomas's explicit yes in chat; it is separate from implementing the ticket.

## Player-visible changes

Every ticket that changes what a Player can see must add or update an entry in `mobile/lib/src/features/player/tour/feature_list.dart`: id, English and Arabic title and one-sentence copy, a target registered by a `TourTarget` on the real widget, location, `audience: 'lifter'`, and release. For a new feature, use `currentFeatureRelease + 1` and bump `currentFeatureRelease` and server `CURRENT_FEATURE_RELEASE` together; keep unshipped entries above the current release. The Feature list check in `mobile/test/feature_list_test.dart` validates entries.

## Operations

- Create, read, list, comment on, label, and close issues with `gh issue`.
- For multiline issue bodies, write the exact text to a temporary file and pass `--body-file`.
- Infer the repository from the GitHub remote.
- When a skill says “publish to the issue tracker,” create a GitHub issue.
- When a skill says “fetch the relevant ticket,” read the issue body, labels, and comments.

## Pull requests as a triage surface

PRs as a request surface: no.

## Blocking relationships

Use GitHub’s native issue dependencies where available. If unavailable, put
`Blocked by: #<number>` references in the dependent issue body. A ticket is
ready when all its blockers are closed.
