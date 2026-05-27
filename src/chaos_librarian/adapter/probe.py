"""Probe comparison helpers for adapter divergence reports."""

from __future__ import annotations

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind

_DURATION_TOLERANCE_SECONDS = 0.05
_UNKNOWN_LANGUAGE_VALUES = frozenset({None, "und"})
_UNKNOWN_LANGUAGE_STREAM_KINDS = frozenset({StreamKind.AUDIO, StreamKind.VIDEO})


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
        "channel_layout",
        "sample_rate",
        "title",
        "role",
        "default",
        "forced",
    ):
        expected_value = getattr(expected, field_name)
        observed_value = getattr(observed, field_name)
        if _unknown_language_values_equal(
            field_name,
            expected,
            observed,
            expected_value,
            observed_value,
        ):
            continue
        if expected_value != observed_value:
            differences.append((f"streams.{index}.{field_name}", expected_value, observed_value))
    return differences


def _unknown_language_values_equal(
    field_name: str,
    expected: ProbedStream,
    observed: ProbedStream,
    expected_value: object,
    observed_value: object,
) -> bool:
    if field_name != "language":
        return False
    if expected.kind not in _UNKNOWN_LANGUAGE_STREAM_KINDS:
        return False
    if observed.kind not in _UNKNOWN_LANGUAGE_STREAM_KINDS:
        return False
    return expected_value in _UNKNOWN_LANGUAGE_VALUES and observed_value in _UNKNOWN_LANGUAGE_VALUES
