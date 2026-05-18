# chaos-librarian developer tasks.
# Run `just --list` to see available recipes.

set shell := ["bash", "-euo", "pipefail", "-c"]

# Bootstrap a development environment: Python toolchain, deps, git hooks.
setup:
    @command -v uv >/dev/null 2>&1 || { \
        echo "error: uv is required. Install: https://docs.astral.sh/uv/getting-started/installation/" >&2; \
        exit 1; \
    }
    @command -v prek >/dev/null 2>&1 || { \
        echo "error: prek is required. Install: cargo install prek  (or see https://github.com/j178/prek)" >&2; \
        exit 1; \
    }
    uv python install 3.13
    uv sync --all-extras --dev
    prek install
