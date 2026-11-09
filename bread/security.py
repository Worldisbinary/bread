"""Passwords, session tokens, API keys and rate limits."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque

USERNAME = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
COMMUNITY = re.compile(r"^[A-Za-z0-9_]{3,21}$")
RESERVED = {
    "admin",
    "administrator",
    "bread",
    "automod",
    "moderator",
    "mod",
    "mods",
    "root",
    "system",
    "support",
    "deleted",
    "removed",
    "help",
    "api",
    "null",
    "undefined",
    "all",
    "popular",
    "home",
    "staff",
    "official",
}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt, digest = stored.split("$")
    test = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(test.hex(), digest)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class RateLimiter:
    """Sliding-window limits kept in memory: enough for one server process."""

    def __init__(self) -> None:
        self.hits: dict[tuple, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, bucket: str, key, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[(bucket, key)]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


LIMITS = {  # bucket: (count, seconds)
    "signup": (5, 3600),
    "login": (20, 600),
    "post": (5, 600),
    "comment": (30, 600),
    "vote": (200, 600),
    "report": (20, 600),
    "community": (3, 86400),
    "ad": (5, 86400),
}
limiter = RateLimiter()


def allowed(bucket: str, key) -> bool:
    count, window = LIMITS[bucket]
    if os.environ.get("BREAD_RELAX_LIMITS") == "1":  # local demos and load tests only
        count *= 100
    return limiter.allow(bucket, key, count, window)
