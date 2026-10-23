# Path-shape fixtures (#232)

## Problem
ASCII-only locators hide consumer failures unrelated to media bytes (#232).

## Scope
Extend existing CORE_FS rename events and coverage accounting, plus one scanner recipe
and focused proofs. No ownership transition, schema, CLI, renderer, or containment change.
The recipe uses one tiny generated original, same-content copies and an in-root symlink;
existing rename actions place them at unusual locators without title normalization.
Coverage classifies actual rename destinations independently of media properties.
CORE_FS guarantees Unicode basename/parent and leading-dash cells using existing events.
Recipe-only shapes remain explicit rather than making every fuzz run platform-sensitive.
Exclusions/owners: dangling/escaping links #195; HTTP/idempotency voom-v2/#731;
new schemas/renderer semantics maintainer via separate explicit design approval.

### Failure model
Supported deployment: UTF-8 POSIX filesystem, ffmpeg/ffprobe >=7; Linux CI and macOS.
Bounded matrix: multibyte basename and parent; NFC/NFD in separate parents to avoid
normalization collisions; 250-byte ASCII component (below common 255-byte limits);
relative path >512 bytes across modest components; leading dash; spaces plus shell
metacharacters; newline/tab via explicit paths (verified accepted by current validation);
in-root relative symlink pointing at its final, stable referent.
NUL and separators cannot be individual-name cases. Display-derived controls remain
unsupported; raw-path controls are exercised only through supported existing actions.
Filesystem spelling may normalize: record actual directory entries in test properties,
compare canonical equivalence only for NFC/NFD, preserve exact intended oracle strings.
Platform limits or unsupported symlinks produce named test skips, never a passing case;
equipped Linux CI must have zero skips. No promise of Windows support.

## Success
Issue #232 Expected is met by a checked-in recipe, deterministic CORE_FS coverage,
filesystem/replay proofs and documented consumer run-mode materialization/replay invocation.
Same-content copies preserve identical hashes while their path cells differ.
Manifest/journal preserve intended paths; filesystem assertions prove actual link targets.
Ordinary scenarios and all guardrails remain green.

## Validation
- Mode: focused-test. Generator/coverage: tests/generation/test_path_shapes.py;
  red: missing required Unicode/parent/dash cells; green:
  `uv run pytest tests/generation/test_path_shapes.py --no-cov`.
- Mode: focused-test. Recipe structure/validation: tests/recipes/test_path_shape_recipe.py;
  red: missing recipe or matrix/byte-budget mismatch; green:
  `uv run pytest tests/recipes/test_path_shape_recipe.py --no-cov`.
- Mode: focused-test. Materialized entries, equal bytes, links, JSON names and replay:
  tests/integration/test_path_shapes_real.py; red: missing recipe/shape or replay mismatch;
  green: `uv run pytest tests/integration/test_path_shapes_real.py --no-cov -ra`.
- Mode: task-test-not-applicable. Consumer instructions/platform matrix are prose;
  CLI invocations are exercised by the integration proof; no prose snapshot test.
