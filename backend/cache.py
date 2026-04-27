"""
Simple in-memory cache with TTL support.
Production: replace with Redis.
"""

import time
from typing import Any, Dict, Optional

class Cache:
    def __init__(self, ttl: int = 300):  # 5 minutes default
        self.ttl = ttl
        self.store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get value if not expired."""
        if key not in self.store:
            return None
        
        entry = self.store[key]
        if time.time() - entry["timestamp"] > self.ttl:
            del self.store[key]
            return None
        
        return entry["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value with optional custom TTL."""
        self.store[key] = {
            "value": value,
            "timestamp": time.time(),
            "ttl": ttl or self.ttl
        }

    def delete(self, key: str) -> None:
        """Delete a key."""
        if key in self.store:
            del self.store[key]

    def clear(self) -> None:
        """Clear all entries."""
        self.store.clear()

    def stats(self) -> Dict[str, int]:
        """Get cache stats."""
        return {
            "entries": len(self.store),
            "ttl": self.ttl
        }


# Global cache instance
cache = Cache(ttl=300)
