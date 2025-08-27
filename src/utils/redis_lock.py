# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Optional
import redis


class RedisLock:
    def __init__(self, redis_client: redis.Redis, prefix: str = "lock:", ttl_seconds: int = 30):
        self.r = redis_client
        self.prefix = prefix
        self.ttl = ttl_seconds

    def acquire(self, key: str, token: Optional[str] = None) -> bool:
        token = token or str(time.time_ns())
        namespaced = self.prefix + key
        ok = self.r.set(namespaced, token, nx=True, ex=self.ttl)
        return bool(ok)

    def release(self, key: str):
        namespaced = self.prefix + key
        try:
            self.r.delete(namespaced)
        except Exception:
            pass
