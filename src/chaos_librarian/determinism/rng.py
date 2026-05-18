"""Per-stream recording RNG.

RngStreams derives a sub-seed per stream name from
``sha256(f"{resolved_seed}/{name}").digest()[:8]``, caches one RngStream
per name, and records every user-facing draw in the trace. RngStream
wraps a private ``random.Random`` rather than subclassing it — see the
Sprint 2 design spec rationale on nested-recording / undocumented
``random.Random`` internals.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from typing import TypeVar

from chaos_librarian.determinism.trace import TraceRecorder

T = TypeVar("T")


def _derive_subseed(resolved_seed: int, stream_name: str) -> int:
    digest = hashlib.sha256(f"{resolved_seed}/{stream_name}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class RngStream:
    """Recording RNG for a single named stream.

    Wraps one private ``random.Random`` and records exactly one
    ``RngTraceEntry`` per user-facing call. Methods that return ``None``
    (e.g. ``random.Random.shuffle``) are deliberately excluded — their
    trace value would not capture the operation result. Callers needing
    random reordering use ``sample(seq, k=len(seq))``.
    """

    def __init__(self, name: str, subseed: int, recorder: TraceRecorder) -> None:
        self._name = name
        self._random = random.Random(subseed)
        self._recorder = recorder

    def _record(self, value: object) -> None:
        self._recorder.record_rng(stream=self._name, value=repr(value))

    def random(self) -> float:
        value = self._random.random()
        self._record(value)
        return value

    def randint(self, a: int, b: int) -> int:
        value = self._random.randint(a, b)
        self._record(value)
        return value

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        if stop is None:
            if step != 1:
                raise ValueError("randrange step has no effect when stop is omitted")
            value = self._random.randrange(start)
        else:
            value = self._random.randrange(start, stop, step)
        self._record(value)
        return value

    def randbytes(self, n: int) -> bytes:
        value = self._random.randbytes(n)
        self._record(value)
        return value

    def choice(self, seq: Sequence[T]) -> T:
        value = self._random.choice(seq)
        self._record(value)
        return value

    def choices(self, seq: Sequence[T], k: int = 1) -> list[T]:
        """Equal-weight choice with replacement.

        ``weights`` / ``cum_weights`` from random.Random.choices are not exposed.
        """
        value = self._random.choices(seq, k=k)
        self._record(value)
        return value

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        """Random sample without replacement.

        ``counts`` from random.Random.sample is not exposed.
        """
        value = self._random.sample(seq, k)
        self._record(value)
        return value

    def uniform(self, a: float, b: float) -> float:
        value = self._random.uniform(a, b)
        self._record(value)
        return value

    def gauss(self, mu: float, sigma: float) -> float:
        value = self._random.gauss(mu, sigma)
        self._record(value)
        return value


class RngStreams:
    """Factory of cached, named RngStream instances seeded sub-deterministically."""

    def __init__(self, resolved_seed: int, recorder: TraceRecorder) -> None:
        self._resolved_seed = resolved_seed
        self._recorder = recorder
        self._cache: dict[str, RngStream] = {}

    def stream(self, name: str) -> RngStream:
        """Return the cached RngStream for ``name``, constructing on first lookup."""
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        stream = RngStream(
            name=name,
            subseed=_derive_subseed(self._resolved_seed, name),
            recorder=self._recorder,
        )
        self._cache[name] = stream
        return stream
