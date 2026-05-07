from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from strava_connect.models import RateLimitState


class DailyLimitReached(Exception):
    """Quota journalier Strava atteint — sortie propre, reprise demain."""


# Type aliases pour rendre l'injection de temps lisible dans les tests.
SleepFn = Callable[[float], None]
NowFn = Callable[[], float]


def _next_quarter_hour(now_ts: float) -> float:
    """Retourne le timestamp UTC de la prochaine frontière :00/:15/:30/:45."""
    quarter = 15 * 60
    return ((int(now_ts) // quarter) + 1) * quarter


def _parse_pair(value: str) -> tuple[int, int]:
    """Parse '10,1000' → (10, 1000). Renvoie (0,0) si format invalide."""
    parts = value.split(",")
    if len(parts) != 2:
        return 0, 0
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0


class RateLimiter:
    """Respecte les limites de lecture Strava.

    - Pause préventive avant chaque requête si l'usage 15 min approche la limite.
    - Lève `DailyLimitReached` si l'usage journalier atteint le seuil.
    - Sait attendre après un 429 (header Retry-After ou prochaine fenêtre).
    """

    SAFE_15MIN_RATIO = 0.9
    SAFE_DAILY_RATIO = 0.95

    def __init__(self, state: RateLimitState | None = None) -> None:
        self.state = state or RateLimitState()

    def update(self, headers: Mapping[str, str]) -> None:
        usage = headers.get("X-ReadRateLimit-Usage") or headers.get("x-readratelimit-usage")
        limit = headers.get("X-ReadRateLimit-Limit") or headers.get("x-readratelimit-limit")
        if usage:
            u15, ud = _parse_pair(usage)
            self.state.usage_15min = u15
            self.state.usage_daily = ud
        if limit:
            l15, ld = _parse_pair(limit)
            if l15:
                self.state.limit_15min = l15
            if ld:
                self.state.limit_daily = ld
        self.state.last_seen = datetime.now(tz=UTC)

    def before_request(
        self,
        *,
        sleep: SleepFn = time.sleep,
        now: NowFn = time.time,
    ) -> None:
        """À appeler juste avant chaque requête sortante."""
        s = self.state
        if s.limit_daily and s.usage_daily / s.limit_daily >= self.SAFE_DAILY_RATIO:
            raise DailyLimitReached(
                f"Quota journalier Strava atteint ({s.usage_daily}/{s.limit_daily}). "
                "Reprends le sync demain."
            )
        if s.limit_15min and s.usage_15min / s.limit_15min >= self.SAFE_15MIN_RATIO:
            now_ts = now()
            wait_s = _next_quarter_hour(now_ts) - now_ts
            if wait_s > 0:
                sleep(wait_s)
            # Après l'attente, l'usage 15min est implicitement reset côté Strava.
            s.usage_15min = 0

    def wait_after_429(
        self,
        headers: Mapping[str, str],
        *,
        sleep: SleepFn = time.sleep,
        now: NowFn = time.time,
    ) -> None:
        retry_after = headers.get("Retry-After") or headers.get("retry-after")
        if retry_after:
            try:
                sleep(float(retry_after))
                return
            except ValueError:
                pass
        now_ts = now()
        wait_s = _next_quarter_hour(now_ts) - now_ts
        if wait_s > 0:
            sleep(wait_s)
