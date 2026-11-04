"""Bounded in-process memos for pure, content-addressed artwork results.

A preparation is named by its content address (`prepare.cache_key`): the verified
source digest, the normalized settings, the preparation version and the Pillow
version. Its prepared pixels and its quality measures are a deterministic function
of exactly those, so a second build or preflight in the same process may reuse them
instead of preparing and measuring the same bytes again. Callers still read every
original and verify it against its pinned SHA-256 before looking a result up, so a
changed or missing file is never answered from memory. Nothing is written to disk;
the memo lives and dies with the process, holds at most its bounds (oldest entries
leave first) and is safe to share between threads.
"""

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from typing import Generic, TypeVar

Value = TypeVar("Value")


class Memo(Generic[Value]):
    def __init__(self, entries: int, size: int, measure: Callable[[Value], int]) -> None:
        self._entries = entries
        self._size = size  # Bound on the sum of `measure` over held values.
        self._measure = measure
        self._held = 0
        self._values: OrderedDict[str, Value] = OrderedDict()
        self._lock = Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Value | None:
        with self._lock:
            value = self._values.get(key)
            if value is None:
                self.misses += 1
                return None
            self._values.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: str, value: Value) -> None:
        cost = self._measure(value)
        if cost > self._size:
            return
        with self._lock:
            old = self._values.pop(key, None)
            if old is not None:
                self._held -= self._measure(old)
            self._values[key] = value
            self._held += cost
            while len(self._values) > self._entries or self._held > self._size:
                _, dropped = self._values.popitem(last=False)
                self._held -= self._measure(dropped)

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._held = 0
            self.hits = self.misses = 0

    def __len__(self) -> int:
        return len(self._values)
