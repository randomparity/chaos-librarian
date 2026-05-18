# Superpowers plans

This directory holds implementation plans authored under the
[superpowers](https://github.com/jasonkneen/claude-superpowers) `writing-plans`
/ `executing-plans` workflow. Each plan is a self-contained, step-by-step
script for a discrete unit of work — a sprint, a bugfix, an issue follow-up —
written in advance of the code change it drives.

## Directory layout

```
docs/superpowers/
├── README.md                          (this file)
└── plans/
    ├── 2026-05-17-sprint-0-skeleton.md            (in-flight)
    ├── 2026-05-17-issue-2-cli-path-validation.md  (in-flight)
    └── archive/
        ├── sprint-0/
        │   └── 2026-05-17-sprint-0-skeleton.md    (after PR #5 merges)
        └── issues/
            └── 2026-05-17-issue-2-cli-path-validation.md   (after #2 closes)
```

- **`plans/`** — plans for the currently active sprint and any open issue
  whose work has not yet shipped.
- **`plans/archive/<sprint-id>/`** — plans whose owning PR has merged.
  Sprint plans go under `archive/sprint-<n>/`; standalone issue plans go
  under `archive/issues/`.

Filenames stay `YYYY-MM-DD-<slug>.md` whether the plan is in-flight or
archived — the date prefix is the authoring date, not the archive date.

## Lifecycle

1. **Author** the plan in `plans/` before touching code. Reference it from
   the PR description (and from the commit body where it helps reviewers).
2. **Execute** the plan; commit code changes and the plan in the same branch.
3. **Archive** when the owning PR merges:
   ```bash
   mkdir -p docs/superpowers/plans/archive/sprint-<n>
   git mv docs/superpowers/plans/<plan>.md \
          docs/superpowers/plans/archive/sprint-<n>/<plan>.md
   ```
   This typically lands as part of the next sprint's kickoff commit, not in
   the PR being archived. Archiving in the same PR churns the diff and makes
   the plan harder to find while review is in progress.
4. **Issue plans** archive to `plans/archive/issues/` once the issue closes.

## Why this split exists

`plans/` doubles as a directory listing of work that is still in motion. Once
shipped plans accumulate there, the signal disappears — a new contributor
can't tell at a glance which plan describes the active sprint. Moving
completed plans to `archive/` keeps the in-flight set short and the history
intact. See [issue #4](https://github.com/randomparity/chaos-librarian/issues/4)
for the original discussion.
