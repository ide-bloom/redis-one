from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass


@dataclass(slots=True)
class _Entry:
    value: bytes
    deadline: float | None = None


class Store:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._data: dict[bytes, _Entry] = {}
        self._clock = clock

    def _entry(self, key: bytes) -> _Entry | None:
        entry = self._data.get(key)
        if entry is not None and entry.deadline is not None and self._clock() >= entry.deadline:
            del self._data[key]
            return None
        return entry

    def get(self, key: bytes) -> bytes | None:
        entry = self._entry(key)
        return None if entry is None else entry.value

    def set(self, key: bytes, value: bytes, *, ttl_ms: int | None = None,
            keep_ttl: bool = False) -> None:
        previous = self._entry(key)
        deadline = self._clock() + ttl_ms / 1000 if ttl_ms is not None else None
        if keep_ttl and previous is not None:
            deadline = previous.deadline
        self._data[key] = _Entry(value, deadline)

    def delete(self, key: bytes) -> bool:
        if self._entry(key) is None:
            return False
        del self._data[key]
        return True

    def rename(self, source: bytes, destination: bytes) -> bool:
        entry = self._entry(source)
        if entry is None:
            return False
        if source != destination:
            self._data[destination] = entry
            del self._data[source]
        return True

    def keys(self) -> Iterator[bytes]:
        for key in tuple(self._data):
            if self._entry(key) is not None:
                yield key

    def clear(self) -> None:
        self._data.clear()
