import threading
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import HTTPException, Request

from .config import settings
from .netutil import resolve_client_ip

ALL_LIMITERS: list["RateLimiter"] = []
MAX_KEYS = 20000  # Obergrenze gemerkter Schlüssel (Schutz vor Speicher-Erschöpfung durch viele gefälschte Quellen)


def client_ip(request: Request) -> str:
    """Echte Client-IP. X-Forwarded-For zählt nur, wenn TRUST_PROXY gesetzt ist UND die direkte Verbindung
    von einem Proxy aus TRUSTED_PROXIES kommt (siehe netutil.resolve_client_ip)."""
    peer = request.client.host if request.client else None
    return resolve_client_ip(peer, request.headers.get("x-forwarded-for"), settings.trust_proxy,
                             settings.trusted_proxies)


class RateLimiter:
    """Sliding-Window-Limiter (pro Prozess; bewusst genau ein Backend-Worker, siehe entrypoint.sh)."""

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()
        self._last_sweep = time.monotonic()
        ALL_LIMITERS.append(self)

    def _sweep(self, now: float) -> None:
        """Entfernt abgelaufene Schlüssel, damit der Speicher nicht unbegrenzt wächst."""
        if now - self._last_sweep < 60 and len(self.hits) < MAX_KEYS:
            return
        self._last_sweep = now
        for k in [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]:
            del self.hits[k]
        if len(self.hits) >= MAX_KEYS:   # Notbremse: älteste Hälfte verwerfen
            for k in list(self.hits)[: MAX_KEYS // 2]:
                del self.hits[k]

    def hit(self, key: str) -> None:
        if not settings.rate_limit_enabled:
            return
        now = time.monotonic()
        with self.lock:
            self._sweep(now)
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "Zu viele Anfragen. Bitte später erneut versuchen.",
                                    headers={"Retry-After": str(self.window)})
            q.append(now)

    def __call__(self, request: Request) -> None:
        self.hit(client_ip(request))

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


login_limiter = RateLimiter(10, 60)             # je IP
login_account_limiter = RateLimiter(10, 900)    # je Konto (E-Mail): bremst verteilte Passwort-Rateversuche
sensitive_limiter = RateLimiter(5, 300)
upload_limiter = RateLimiter(30, 300)
api_limiter = RateLimiter(600, 60)              # allgemeine Obergrenze je IP für alle /api-Aufrufe


def limit_account(email: Optional[str]) -> None:
    if email:
        login_account_limiter.hit(email.strip().lower())
