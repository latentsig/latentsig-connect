import asyncio
from collections import defaultdict
from time import monotonic

from fastapi import HTTPException, Request

from app.core.config import settings

_hits: dict[str, list[float]] = defaultdict(list)
_lock = asyncio.Lock()
_redis = None


def rate_limit(bucket: str):
    if bucket == "ocr":
        limit, window = settings.ocr_rate_limit_count, settings.ocr_rate_limit_window_seconds
    elif bucket == "auth":
        limit, window = settings.auth_rate_limit_count, settings.auth_rate_limit_window_seconds
    else:
        limit, window = settings.lead_rate_limit_count, settings.lead_rate_limit_window_seconds

    async def enforce(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"rate:{bucket}:{ip}"
        if settings.redis_url:
            global _redis
            try:
                if _redis is None:
                    from redis.asyncio import Redis
                    _redis = Redis.from_url(settings.redis_url, decode_responses=True)
                count = await _redis.incr(key)
                if count == 1:
                    await _redis.expire(key, window)
            except Exception:
                if settings.app_env.lower() == "production":
                    raise HTTPException(status_code=503, detail="Submission service is temporarily unavailable.") from None
                count = await _memory_hit(key, window)
        else:
            if settings.app_env.lower() == "production":
                raise HTTPException(status_code=503, detail="Rate limiting is not configured.")
            count = await _memory_hit(key, window)
        if count > limit:
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a moment and try again.")

    return enforce


async def _memory_hit(key: str, window: int) -> int:
    now = monotonic()
    async with _lock:
        recent = [hit for hit in _hits[key] if now - hit < window]
        recent.append(now)
        _hits[key] = recent
        return len(recent)
