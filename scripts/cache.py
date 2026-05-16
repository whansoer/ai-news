"""Gemini API response cache — content-hash-based, persists across pipeline runs.

Usage:
    from cache import Cache
    c = Cache("translate")  # loads data/cache/translate.json

    key = c.make_key(item_id, title, summary)  # hash of content
    cached = c.get(key)
    if cached:
        return cached  # skip API call
    result = call_gemini(...)
    c.set(key, result)
    c.save()  # write to disk
"""

import hashlib
import json
import os
import time

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

# Entries older than this (seconds) are considered stale
# 0 = never expire (cache is content-addressed, not time-addressed)
STALE_SECONDS = 0


class Cache:
    def __init__(self, name: str, stale_seconds: int = STALE_SECONDS):
        self.name = name
        self.stale_seconds = stale_seconds
        self.path = os.path.join(CACHE_DIR, f"{name}.json")
        self.data: dict = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        os.makedirs(CACHE_DIR, exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data = loaded.get("entries", {})
            except Exception:
                self.data = {}
        self._loaded = True

    def make_key(self, *parts: str) -> str:
        """Create a content-based cache key from one or more strings."""
        content = "|".join(p.strip() for p in parts if p)
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        return h

    def get(self, key: str):
        """Return cached value or None."""
        self._load()
        entry = self.data.get(key)
        if not entry:
            return None
        if self.stale_seconds > 0:
            ts = entry.get("_ts", 0)
            if time.time() - ts > self.stale_seconds:
                return None
        return entry.get("v")

    def set(self, key: str, value):
        """Store a value in cache (in-memory, call save() to persist)."""
        self._load()
        self.data[key] = {"v": value, "_ts": int(time.time())}

    def save(self):
        """Write cache to disk."""
        os.makedirs(CACHE_DIR, exist_ok=True)
        # Prune: keep at most 5000 entries
        if len(self.data) > 5000:
            # Keep newest 5000
            sorted_keys = sorted(
                self.data.keys(),
                key=lambda k: self.data[k].get("_ts", 0),
                reverse=True,
            )
            self.data = {k: self.data[k] for k in sorted_keys[:5000]}
        output = {
            "name": self.name,
            "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(self.data),
            "entries": self.data,
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    def hits(self) -> int:
        """Count entries (proxy for cache usefulness)."""
        return len(self.data)
