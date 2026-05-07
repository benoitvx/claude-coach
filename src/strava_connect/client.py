from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from strava_connect.auth import AuthError, get_valid_tokens
from strava_connect.models import Config
from strava_connect.rate_limiter import RateLimiter

DEFAULT_STREAMS = (
    "time",
    "latlng",
    "distance",
    "altitude",
    "heartrate",
    "cadence",
    "watts",
    "temp",
    "velocity_smooth",
    "grade_smooth",
    "moving",
)

MAX_ATTEMPTS = 3
HTTP_TIMEOUT_S = 30.0

SleepFn = Callable[[float], None]


class StravaClient:
    """Wrapper minimaliste de l'API Strava v3.

    - Refresh automatique des tokens (via auth.get_valid_tokens)
    - Rate limiting (RateLimiter)
    - Retries sur 5xx / timeouts (backoff exponentiel) et 429 (attente jusqu'au prochain
      quart d'heure ou Retry-After).
    """

    BASE_URL = "https://www.strava.com/api/v3"

    def __init__(
        self,
        config: Config,
        tokens_path: Path,
        *,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
        rate_limiter: RateLimiter | None = None,
        sleep: SleepFn = time.sleep,
    ) -> None:
        self.config = config
        self.tokens_path = tokens_path
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._client = http_client or httpx.Client(timeout=HTTP_TIMEOUT_S)
        self._owns_client = http_client is None
        self._rate_limiter = rate_limiter or RateLimiter()
        self._sleep = sleep

    @property
    def rate_limiter(self) -> RateLimiter:
        return self._rate_limiter

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> StravaClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # --- public API ---------------------------------------------------------

    def list_activities(
        self, after_epoch: int, *, page: int = 1, per_page: int = 30
    ) -> list[dict[str, Any]]:
        result = self._get(
            "/athlete/activities",
            params={"after": after_epoch, "page": page, "per_page": per_page},
        )
        if not isinstance(result, list):
            raise StravaClientError(f"/athlete/activities a retourné {type(result).__name__}")
        return result

    def get_activity(self, activity_id: int) -> dict[str, Any]:
        result = self._get(f"/activities/{activity_id}")
        if not isinstance(result, dict):
            raise StravaClientError(f"/activities/{activity_id} a retourné {type(result).__name__}")
        return result

    def get_streams(
        self, activity_id: int, types: tuple[str, ...] = DEFAULT_STREAMS
    ) -> dict[str, dict[str, Any]]:
        result = self._get(
            f"/activities/{activity_id}/streams",
            params={"keys": ",".join(types), "key_by_type": "true"},
        )
        if not isinstance(result, dict):
            raise StravaClientError(
                f"/activities/{activity_id}/streams a retourné {type(result).__name__}"
            )
        return result

    def get_laps(self, activity_id: int) -> list[dict[str, Any]]:
        result = self._get(f"/activities/{activity_id}/laps")
        if not isinstance(result, list):
            raise StravaClientError(f"/activities/{activity_id}/laps a retourné non-liste")
        return result

    def get_zones(self, activity_id: int) -> list[dict[str, Any]] | None:
        """Retourne None si l'utilisateur n'est pas Summit (402/403/404)."""
        try:
            result = self._get(f"/activities/{activity_id}/zones")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (402, 403, 404):
                return None
            raise
        if not isinstance(result, list):
            raise StravaClientError(f"/activities/{activity_id}/zones a retourné non-liste")
        return result

    # --- internal -----------------------------------------------------------

    def _get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            self._rate_limiter.before_request()
            tokens = get_valid_tokens(self.config, self.tokens_path)
            headers = {"Authorization": f"Bearer {tokens.access_token}"}
            try:
                response = self._client.get(url, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(2**attempt)
                    continue
                raise

            self._rate_limiter.update(response.headers)

            if response.status_code == 401:
                raise AuthError(
                    "401 reçu de Strava — relance `strava-connect auth` pour ré-autoriser."
                )
            if response.status_code == 429:
                self._rate_limiter.wait_after_429(response.headers, sleep=self._sleep)
                continue
            if 500 <= response.status_code < 600:
                last_exc = httpx.HTTPStatusError(
                    f"{response.status_code} {response.reason_phrase}",
                    request=response.request,
                    response=response,
                )
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(2**attempt)
                    continue
                response.raise_for_status()

            response.raise_for_status()
            return response.json()

        # Si on sort de la boucle sans return : on a épuisé les tentatives.
        if last_exc:
            raise last_exc
        raise StravaClientError(f"Échec après {MAX_ATTEMPTS} tentatives sur {path}")


class StravaClientError(RuntimeError):
    pass
