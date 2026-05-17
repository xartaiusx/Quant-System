"""Small in-memory cache used by dry-run workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass
class MemoryCache(Generic[T]):
    """Simple key-value cache for non-critical dry-run data."""

    values: dict[str, T] = field(default_factory=dict)

    def get(self, key: str) -> T | None:
        return self.values.get(key)

    def set(self, key: str, value: T) -> None:
        self.values[key] = value

    def clear(self) -> None:
        self.values.clear()
