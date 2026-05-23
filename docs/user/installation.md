# Installation

## Prerequisites

- Python 3.13 or newer.
- `uv`.
- ffmpeg 7.0+ and ffprobe 7.0+ for `materialize` and `run`.
- mkvmerge from MKVToolNix 80+ for full media-mutation readiness.

## Project Setup

```bash
uv sync
uv run chaos-librarian --help
```

## Capability Check

```bash
uv run chaos-librarian capabilities --json
```

Read `ready_for.materialize_static`,
`ready_for.materialize_filesystem_mutations`, and
`ready_for.materialize_media_mutations` before enabling media-heavy tests in CI.

## Plan-Only Setup

Plan-only workflows require only Python dependencies. Use `plan` when the
machine does not have media tools or when authoring scenario behavior before
generating real files.
