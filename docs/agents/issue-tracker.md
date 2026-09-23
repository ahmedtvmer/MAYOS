# Issue tracker: GitHub

Specs and tickets live as GitHub issues in this repo. Use `gh` from the repo root.

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
