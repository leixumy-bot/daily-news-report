"""Simple file-based cache with TTL."""

import json
import os
import time
from pathlib import Path


class FileCache:
    """File-based cache. Each key is a JSON file under root_dir."""

    def __init__(self, root_dir: str | Path, default_ttl: int = 1800):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.default_ttl = default_ttl

    def _path(self, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.root / f"{safe}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("expires_at", 0) > time.time():
                return data.get("value")
            path.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError):
            path.unlink(missing_ok=True)
        return None

    def set(self, key: str, value, ttl: int | None = None) -> None:
        path = self._path(key)
        expires_at = time.time() + (ttl if ttl is not None else self.default_ttl)
        path.write_text(
            json.dumps({"expires_at": expires_at, "value": value}, ensure_ascii=False),
            encoding="utf-8",
        )

    def clear_expired(self) -> int:
        """Remove expired cache entries. Returns count removed."""
        now = time.time()
        removed = 0
        for f in self.root.iterdir():
            if f.suffix == ".json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if data.get("expires_at", 0) <= now:
                        f.unlink()
                        removed += 1
                except (json.JSONDecodeError, OSError):
                    f.unlink(missing_ok=True)
                    removed += 1
        return removed
