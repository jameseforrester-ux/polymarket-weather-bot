from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CacheItem:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, CacheItem] = {}

    def get(self, key: str) -> Optional[Any]:
        item = self._items.get(key)
        if not item:
            return None
        if item.expires_at < time.time():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds or self.ttl_seconds
        self._items[key] = CacheItem(value=value, expires_at=time.time() + ttl)

    def clear(self) -> None:
        self._items.clear()
