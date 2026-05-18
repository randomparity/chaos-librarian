"""Smoke test that the Sprint 2 public surface imports cleanly and behaves."""

from __future__ import annotations

from chaos_librarian import determinism as determinism_module
from chaos_librarian.determinism import (
    Clock,
    IdAllocator,
    IdAllocatorOverflow,
    RngStreams,
    TraceRecorder,
    format_duration_human,
    format_duration_json,
    resolve_seed,
    scenario_content_hash,
)


def test_public_surface_matches_spec() -> None:
    """All nine names import from chaos_librarian.determinism.

    WHY: downstream sprints import only from this package; the submodule
    layout is implementation detail. If a re-export is missed, Sprint 3
    would have to reach into private submodules and the package boundary
    would leak.
    """
    rec = TraceRecorder()
    rng = RngStreams(resolved_seed=42, recorder=rec)
    # Cached stream returns identical instance — the exit-criteria smoke from
    # the design spec.
    assert rng.stream("video_source") is rng.stream("video_source")
    alloc = IdAllocator(recorder=rec)
    assert alloc.next_version_id() == "version_0001"
    clk = Clock()
    clk.advance(1_000)
    assert clk.now() == 1_000
    assert format_duration_human(0) == "0s"
    assert format_duration_json(0) == 0
    assert isinstance(resolve_seed(7), int)
    assert isinstance(scenario_content_hash(b"x"), str)
    # IdAllocatorOverflow is a public exception — verify it is a proper exception type.
    assert issubclass(IdAllocatorOverflow, Exception)


def test_dunder_all_is_alphabetised_and_exact() -> None:
    """__all__ lists exactly the nine names from the spec, in alphabetical order.

    WHY: __all__ is part of the public contract. Adding a name here is
    additive (and intentional); reordering or removing one is a break.
    """
    assert determinism_module.__all__ == [
        "Clock",
        "IdAllocator",
        "IdAllocatorOverflow",
        "RngStreams",
        "TraceRecorder",
        "format_duration_human",
        "format_duration_json",
        "resolve_seed",
        "scenario_content_hash",
    ]
