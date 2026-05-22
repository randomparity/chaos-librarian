"""Probe comparison helpers for adapter divergence reports."""

from __future__ import annotations

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream

_DURATION_TOLERANCE_SECONDS = 0.05


def compare_probed_media(
    expected: ProbedMedia, observed: ProbedMedia
) -> list[tuple[str, object, object]]:
    """Return field-level probe differences, ignoring size_bytes."""
    differences: list[tuple[str, object, object]] = []
    if expected.container != observed.container:
        differences.append(("container", expected.container, observed.container))
    if abs(expected.duration_seconds - observed.duration_seconds) > _DURATION_TOLERANCE_SECONDS:
        differences.append(
            ("duration_seconds", expected.duration_seconds, observed.duration_seconds)
        )
    if len(expected.streams) != len(observed.streams):
        differences.append(("streams.length", len(expected.streams), len(observed.streams)))
    for index, (expected_stream, observed_stream) in enumerate(
        zip(expected.streams, observed.streams, strict=False)
    ):
        differences.extend(_compare_stream(index, expected_stream, observed_stream))
    return differences


def _compare_stream(
    index: int, expected: ProbedStream, observed: ProbedStream
) -> list[tuple[str, object, object]]:
    differences: list[tuple[str, object, object]] = []
    for field_name in (
        "kind",
        "codec",
        "language",
        "width",
        "height",
        "channels",
        "sample_rate",
        "default",
        "forced",
    ):
        expected_value = getattr(expected, field_name)
        observed_value = getattr(observed, field_name)
        if expected_value != observed_value:
            differences.append((f"streams.{index}.{field_name}", expected_value, observed_value))
    return differences
