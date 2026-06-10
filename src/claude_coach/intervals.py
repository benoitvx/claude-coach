"""Client API intervals.icu + mapping des blocs vers `workout_doc` (lot 10).

Alternative **gratuite** à Nolio (`nolio.py`) pour la voie running→Suunto :
intervals.icu expose une API ouverte (clé perso, Basic auth `API_KEY:<clé>`) et
synchronise nativement les séances planifiées vers la montre Suunto (SuuntoPlus
Guides : cibles allure, FC, distance). On crée/maj un événement calendrier via
`/api/v1/athlete/{id}/events` ; intervals.icu génère un guide Suunto et le pousse.

On envoie le **`workout_doc` JSON structuré** (pas le texte « workout builder ») :
le parseur de texte ignore la FC en bpm absolus, le `workout_doc` est sans ambiguïté.
Décisions clés, **toutes vérifiées contre l'API + l'upload Suunto réels** :

- Unités `workout_doc` : duration=s, distance=m, pace=`secs/km`, power=`w`.
- **FC → `%hr` (% de FCmax), JAMAIS `bpm`** : un guide Suunto avec FC en bpm absolus
  est rejeté (`value > 250`). On convertit bpm→%FCmax avec la FCmax de l'athlète ;
  la montre reconvertit en bpm avec sa propre FCmax (cf. `_target_doc`).
- Répétition → `{"reps": N, "steps": [...]}` ; label warmup/cooldown/rest → `text`.
- **Idempotence** : `POST` ne dé-duplique pas sur `external_id` → `upsert_event`
  fait GET (filtre `external_id`) puis PUT si l'event existe, sinon POST.

Les blocs canoniques (`workout.py`, allure en m/s, FC en bpm) sont réutilisés tels
quels — seul le mapping diffère de Nolio (qui, lui, accepte les bpm).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx

from claude_coach.auth import AuthError, ConfigError
from claude_coach.models import IntervalsConfig, PlannedSession
from claude_coach.workout import Repetition, Step, WorkoutItem

MAX_ATTEMPTS = 3
HTTP_TIMEOUT_S = 30.0

INTERVALS_API_BASE = "https://intervals.icu/api/v1"
CONFIG_FILE_DEFAULT = Path("data/config.json")

SleepFn = Callable[[float], None]

# sport_type Strava → `type` intervals.icu (séances non-vélo ; le vélo reste .zwo).
INTERVALS_SPORT_TYPES: dict[str, str] = {
    "Run": "Run",
    "TrailRun": "Run",
    "VirtualRun": "Run",
    "Swim": "Swim",
    "Walk": "Walk",
    "Hike": "Hike",
}


def load_intervals_config(
    env: dict[str, str] | None = None,
    path: Path = CONFIG_FILE_DEFAULT,
) -> IntervalsConfig:
    """Charge la config intervals.icu. Priorité : env vars > data/config.json."""
    env = env if env is not None else dict(os.environ)
    api_key = env.get("INTERVALS_API_KEY")
    athlete_id = env.get("INTERVALS_ATHLETE_ID")

    file_data: dict[str, Any] = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            file_data = json.load(f)

    api_key = api_key or file_data.get("intervals_api_key")
    athlete_id = athlete_id or file_data.get("intervals_athlete_id")
    if not api_key or not athlete_id:
        raise ConfigError(
            "Config intervals.icu manquante : définir INTERVALS_API_KEY et "
            "INTERVALS_ATHLETE_ID (ou les clés intervals_api_key/intervals_athlete_id "
            "dans data/config.json). Clé API : intervals.icu → Settings → Developer Settings."
        )
    return IntervalsConfig(api_key=str(api_key), athlete_id=str(athlete_id))


def intervals_sport_type(sport_type: str) -> str:
    """`type` intervals.icu pour un sport_type Strava. Lève `ValueError` si non mappé."""
    mapped = INTERVALS_SPORT_TYPES.get(sport_type)
    if mapped is None:
        known = ", ".join(sorted(INTERVALS_SPORT_TYPES))
        raise ValueError(f"Sport '{sport_type}' non mappé vers intervals.icu (connus : {known})")
    return mapped


# --- Mapping blocs canoniques → workout_doc structuré --------------------------
#
# IMPORTANT : on envoie le `workout_doc` JSON **structuré**, pas du texte. Le
# parseur de texte d'intervals.icu n'interprète PAS la FC en bpm absolus (seulement
# zones `Z2 HR` ou %FCmax `70-80% HR`), alors que le `workout_doc` accepte les bpm
# directement (`{"hr": {"units": "bpm", "start": 130, "end": 148}}`). On préserve
# donc les cibles absolues (vérifié contre l'API réelle).
#
# Unités workout_doc : duration = s, distance = m, pace = `secs/km`, hr = `bpm`,
# power = `w`. Cible simple → `value` ; plage → `start`/`end`.

_INTENSITY_LABELS = {"warmup": "Warmup", "cooldown": "Cooldown", "rest": "Recovery"}


def _mps_to_secs_per_km(mps: float) -> int:
    """Vitesse m/s → secondes par km (inverse de `workout._pace_to_mps`)."""
    return round(1000 / mps)


def _range_payload(units: str, lo: int, hi: int) -> dict[str, Any]:
    """Cible simple (`value`) si lo == hi, sinon plage (`start`/`end`)."""
    if lo == hi:
        return {"units": units, "value": lo}
    return {"units": units, "start": lo, "end": hi}


def _target_doc(step: Step, max_hr: int | None) -> tuple[str, dict[str, Any]] | None:
    """(`clé`, payload) de la cible workout_doc, ou `None` si pas de cible.

    ⚠️ FC : on émet du **`%hr` (% de FCmax)**, PAS des bpm absolus. Vérifié contre
    l'API réelle : un guide Suunto avec FC en bpm est rejeté (`value > 250`) car
    intervals.icu convertit en interne et déborde. On convertit donc bpm→%FCmax
    avec la FCmax de l'athlète ; la montre reconvertit en bpm avec SA FCmax (=
    la même valeur si l'athlète l'a réglée pareil) → affichage bpm correct.
    """
    if step.target_min is None or step.target_max is None:
        return None
    if step.target_type == "pace":
        # m/s : target_max = plus rapide (secs/km plus petit) = `start`.
        fast = _mps_to_secs_per_km(step.target_max)
        slow = _mps_to_secs_per_km(step.target_min)
        return ("pace", _range_payload("secs/km", fast, slow))
    if step.target_type == "heartrate":
        if not max_hr:
            raise ValueError(
                "FCmax requise pour pousser une cible FC vers intervals.icu/Suunto : "
                "la FC en bpm absolus n'est pas acceptée par le guide Suunto, on la "
                "convertit en %FCmax. Renseigne-la via "
                "`claude-coach athlete set --fc-max <bpm>`."
            )
        lo = round(step.target_min / max_hr * 100)
        hi = round(step.target_max / max_hr * 100)
        return ("hr", _range_payload("%hr", lo, hi))
    if step.target_type == "power":
        return ("power", _range_payload("w", round(step.target_min), round(step.target_max)))
    return None


def _step_to_doc(step: Step, max_hr: int | None) -> dict[str, Any]:
    d: dict[str, Any] = {}
    label = _INTENSITY_LABELS.get(step.intensity)
    if label:
        d["text"] = label
    if step.duration_type == "distance":
        d["distance"] = step.duration_value
    else:
        d["duration"] = step.duration_value
    target = _target_doc(step, max_hr)
    if target:
        key, payload = target
        d[key] = payload
    return d


def workout_doc_from_items(
    items: list[WorkoutItem], *, max_hr: int | None = None
) -> dict[str, Any]:
    """Convertit les blocs canoniques (`workout.py`) en `workout_doc` intervals.icu.

    Une `Repetition` devient `{"reps": N, "steps": [...]}`. Le top-level ne porte
    que `steps` ; intervals.icu calcule durée/distance/charge à la réception.
    `max_hr` (FCmax) est requis dès qu'une cible FC est présente (conversion en %FCmax).
    """
    steps: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, Repetition):
            steps.append(
                {"reps": item.repeat, "steps": [_step_to_doc(s, max_hr) for s in item.steps]}
            )
        else:
            steps.append(_step_to_doc(item, max_hr))
    return {"steps": steps}


def build_event_payload(
    session: PlannedSession,
    *,
    plan_name: str,
    sport_type: str,
    workout_doc: dict[str, Any],
    description: str | None = None,
) -> dict[str, Any]:
    """Construit le corps de `POST /api/v1/athlete/{id}/events`.

    `start_date_local` doit finir par `T00:00:00`. `external_id` (= id séance)
    identifie l'événement côté intervals.icu. `description` (optionnelle) porte le
    contexte humain de la séance ; la structure est dans `workout_doc`.
    """
    payload: dict[str, Any] = {
        "start_date_local": f"{session.planned_date.isoformat()}T00:00:00",
        "category": "WORKOUT",
        "type": intervals_sport_type(sport_type),
        "name": f"{plan_name} — {session.planned_date.isoformat()}",
        "external_id": f"claude-coach-{session.id}",
        "workout_doc": workout_doc,
    }
    if description:
        payload["description"] = description
    return payload


class IntervalsClientError(RuntimeError):
    pass


class IntervalsClient:
    """Wrapper minimaliste de l'API intervals.icu (upsert d'événements planifiés).

    Auth = Basic `API_KEY:<clé>` (clé perso). Retries sur 5xx / timeouts (backoff
    exponentiel) et 429 (Retry-After). Pas de refresh de token (clé statique).
    `upsert_event` est **idempotent** : un re-push met à jour l'event existant
    (même `external_id`) au lieu de créer un doublon.
    """

    BASE_URL = INTERVALS_API_BASE

    def __init__(
        self,
        config: IntervalsConfig,
        *,
        base_url: str | None = None,
        http_client: httpx.Client | None = None,
        sleep: SleepFn = time.sleep,
    ) -> None:
        self.config = config
        self.base_url = (base_url or config.base_url or self.BASE_URL).rstrip("/")
        self._client = http_client or httpx.Client(timeout=HTTP_TIMEOUT_S)
        self._owns_client = http_client is None
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> IntervalsClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def upsert_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Crée l'événement, ou met à jour celui qui porte déjà le même `external_id`.

        intervals.icu ne dé-duplique PAS au POST : un re-push créerait un doublon.
        On cherche donc l'event existant à la date (`external_id`) et on le **PUT**
        s'il existe, sinon on **POST**. → idempotent (re-push = mise à jour).
        """
        events_path = f"/athlete/{self.config.athlete_id}/events"
        external_id = payload.get("external_id")
        date = str(payload.get("start_date_local", ""))[:10]
        existing_id = self._find_event_id(date, external_id) if external_id and date else None

        if existing_id is not None:
            result = self._request("PUT", f"{events_path}/{existing_id}", json_body=payload)
        else:
            result = self._request("POST", events_path, json_body=payload)
        if not isinstance(result, dict):
            raise IntervalsClientError("Réponse inattendue (non-objet) de /events")
        return result

    # --- internal -----------------------------------------------------------

    def _find_event_id(self, date: str, external_id: str) -> int | None:
        """id de l'event à `date` portant `external_id`, ou `None`."""
        path = f"/athlete/{self.config.athlete_id}/events"
        result = self._request("GET", path, params={"oldest": date, "newest": date})
        if not isinstance(result, list):
            return None
        for ev in result:
            if isinstance(ev, dict) and ev.get("external_id") == external_id:
                event_id = ev.get("id")
                if isinstance(event_id, int):
                    return event_id
        return None

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        auth = ("API_KEY", self.config.api_key)
        last_exc: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.request(
                    method, url, json=json_body, params=params, auth=auth
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt + 1 < MAX_ATTEMPTS:
                    self._sleep(2**attempt)
                    continue
                raise

            if response.status_code in (401, 403):
                raise AuthError(
                    "401/403 reçu d'intervals.icu — vérifie INTERVALS_API_KEY / "
                    "INTERVALS_ATHLETE_ID (clé API dans Settings → Developer Settings)."
                )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after else 2**attempt)
                continue
            if 400 <= response.status_code < 500:
                raise IntervalsClientError(
                    f"{response.status_code} d'intervals.icu sur {path} : {response.text.strip()}"
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
        raise IntervalsClientError(f"Échec après {MAX_ATTEMPTS} tentatives sur {path}")
