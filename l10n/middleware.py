"""Simple in-memory rate limiting middleware for sensitive endpoints.

Limits POST requests to login, pipeline, and import endpoints by IP address.
Uses Django's cache framework so it works with any cache backend.
"""

import time
from collections import defaultdict
from threading import Lock

from django.http import HttpResponse


class _RateBucket:
    """Thread-safe sliding-window counter per IP."""

    def __init__(self):
        self._lock = Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str, max_hits: int, window_seconds: int) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            # Prune expired entries
            cutoff = now - window_seconds
            self._hits[key] = hits = [t for t in hits if t > cutoff]
            if len(hits) >= max_hits:
                return True
            hits.append(now)
            return False


# Rate limit rules: path prefix -> (max POST requests, window in seconds)
_RATE_RULES: dict[str, tuple[int, int]] = {
    "/login/": (10, 300),       # 10 login attempts per 5 minutes
    "/pipeline/": (5, 600),     # 5 pipeline triggers per 10 minutes
    "/import/": (10, 600),      # 10 CSV imports per 10 minutes
}

_bucket = _RateBucket()


def _get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class RateLimitMiddleware:
    """Rate-limit POST requests to sensitive endpoints."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST":
            path = request.path_info
            for prefix, (max_hits, window) in _RATE_RULES.items():
                if path.endswith(prefix) or path == prefix:
                    ip = _get_client_ip(request)
                    key = f"{prefix}:{ip}"
                    if _bucket.is_limited(key, max_hits, window):
                        return HttpResponse(
                            "Too many requests. Please try again later.",
                            status=429,
                            content_type="text/plain",
                        )
                    break

        return self.get_response(request)
