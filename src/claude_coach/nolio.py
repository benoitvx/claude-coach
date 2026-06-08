"""Client API Nolio + mapping des blocs vers `structured_workout` (lot 9).

Pousse une séance planifiée structurée vers Nolio via
`POST /api/create/planned/training/`. Nolio la marque « structurée » dans le
calendrier et la synchronise automatiquement vers la montre (Suunto 9 via
SuuntoPlus Guides, Garmin, …).

Unités Nolio : durée = s, distance = m, allure (`pace`) = m/s, FC = bpm,
puissance = W. Le DSL/canonique (`workout.py`) produit déjà ces unités.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from claude_coach.auth import AuthError
from claude_coach.models import NolioConfig, PlannedSession
from claude_coach.nolio_auth import NOLIO_API_BASE, get_valid_tokens
from claude_coach.workout import Repetition, Step, WorkoutItem

MAX_ATTEMPTS = 3
HTTP_TIMEOUT_S = 30.0

SleepFn = Callable[[float], None]

# sport_type Strava → sport_id Nolio (cf. sport-map Nolio Training-Object).
NOLIO_SPORT_IDS: dict[str, int] = {
    "Run": 2,
    "TrailRun": 52,
    "VirtualRun": 24,  # Treadmill
    "Ride": 14,  # Road cycling
    "GravelRide": 14,
    "EBikeRide": 14,
    "MountainBikeRide": 15,
    "VirtualRide": 18,
    "Swim": 19,
    "Walk": 45,
    "Hike": 16,
}


def nolio_sport_id(sport_type: str) -> int:
    """sport_id Nolio pour un sport_type Strava. Lève `ValueError` si non mappé."""
    sport_id = NOLIO_SPORT_IDS.get(sport_type)
    if sport_id is None:
        known = ", ".join(sorted(NOLIO_SPORT_IDS))
        raise ValueError(f"Sport '{sport_type}' non mappé vers Nolio (connus : {known})")
    return sport_id


def _step_to_nolio(step: Step) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": "step",
        "intensity_type": step.intensity,
        "step_duration_type": step.duration_type,
        "step_duration_value": step.duration_value,
        "target_type": step.target_type,
    }
    if step.target_type != "no_target":
        # target_value_max est requis dès qu'il y a une cible ; min reste optionnel.
        if step.target_min is not None:
            d["target_value_min"] = step.target_min
        d["target_value_max"] = step.target_max if step.target_max is not None else step.target_min
    return d


def structured_workout_from_items(items: list[WorkoutItem]) -> list[dict[str, Any]]:
    """Convertit les blocs canoniques (`workout.py`) en `structured_workout` Nolio."""
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Repetition):
            out.append(
                {
                    "type": "repetition",
                    "value": item.repeat,
                    "steps": [_step_to_nolio(s) for s in item.steps],
                }
            )
        else:
            out.append(_step_to_nolio(item))
    return out


def build_planned_training_payload(
    session: PlannedSession,
    *,
    plan_name: str,
    sport_id: int,
    structured_workout: list[dict[str, Any]] | None,
    athlete_id: int | None = None,
) -> dict[str, Any]:
    """Construit le corps de `POST /api/create/planned/training/`.

    `id_partner` = id de la séance → idempotent (un re-push ne duplique pas).
    `athlete_id` est omis par défaut (push sur le compte connecté).
    """
    payload: dict[str, Any] = {
        "id_partner": session.id,
        "sport_id": sport_id,
        "name": f"{plan_name} — {session.planned_date.isoformat()}",
        "date_start": session.planned_date.isoformat(),
    }
    if structured_workout:
        payload["structured_workout"] = structured_workout
    if session.target_duration_s:
        payload["duration"] = session.target_duration_s
    if session.target_distance_m:
        # Nolio attend la distance en kilomètres (entier).
        km = round(session.target_distance_m / 1000)
        if km > 0:
            payload["distance"] = km
    description = session.description or session.notes
    if description:
        payload["description"] = description
    if athlete_id is not None:
        payload["athlete_id"] = athlete_id
    return payload


class NolioClientError(RuntimeError):
    pass


class NolioClient:
    """Wrapper minimaliste de l'API Nolio (POST séances planifiées).

    - Refresh automatique des tokens (via `nolio_auth.get_valid_tokens`)
    - Retries sur 5xx / timeouts (backoff exponentiel) et 429 (Retry-After)
    """

    BASE_URL = NOLIO_API_BASE

    def __init__(
        self,
        config: NolioConfig,
        tokens_path: Path,
        *,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
        sleep: SleepFn = time.sleep,
    ) -> None:
        self.config = config
        self.tokens_path = tokens_path
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._client = http_client or httpx.Client(timeout=HTTP_TIMEOUT_S)
        self._owns_client = http_client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> NolioClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def create_planned_training(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._post("/create/planned/training/", payload)
        if not isinstance(result, dict):
            raise NolioClientError("Réponse inattendue (non-objet) de create/planned/training")
        return result

    # --- internal -----------------------------------------------------------

    def _post(self, path: str, json_body: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            tokens = get_valid_tokens(self.config, self.tokens_path)
            headers = {"Authorization": f"Bearer {tokens.access_token}"}
            try:
                response = self._client.post(url, json=json_body, headers=headers)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(2**attempt)
                    continue
                raise

            if response.status_code == 401:
                raise AuthError(
                    "401 reçu de Nolio — relance `claude-coach nolio auth` pour ré-autoriser."
                )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after else 2**attempt)
                continue
            if response.status_code == 400:
                raise NolioClientError(
                    f"400 de Nolio sur {path} : {response.text.strip()} "
                    "(la séance existe peut-être déjà — même id_partner)"
                )
            if 400 <= response.status_code < 500:
                # Autre erreur client non-réessayable (403 droits insuffisants, 404, ...).
                raise NolioClientError(
                    f"{response.status_code} de Nolio sur {path} : {response.text.strip()}"
                )
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

        if last_exc:
            raise last_exc
        raise NolioClientError(f"Échec après {MAX_ATTEMPTS} tentatives sur {path}")
