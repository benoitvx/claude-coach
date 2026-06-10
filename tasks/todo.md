# Lot 10 — Push séances running vers Suunto via intervals.icu (alternative gratuite à Nolio)

Plan complet : `~/.claude/plans/mutable-discovering-summit.md`.

## Contexte
API Nolio = comptes payants → bloque la voie running→Suunto. intervals.icu est
gratuit (API clé perso + upload natif des séances planifiées vers Suunto via
SuuntoPlus Guides). On clone-adapte la couche Nolio, on **garde Nolio en place**.
Auth = **clé API perso** (Basic `API_KEY:<clé>`), pas d'OAuth.

## Grammaire workout intervals.icu (vérifiée — forum/quick-guide)
- Step : `- [Label] <durée|distance> <cible>`
- **`m` = minutes** (pas mètres !). Distance : `km` ou `mtr` (ex `400mtr`, `5km`).
- Temps : `10m`, `30s`, combiné `5m30s`.
- Pace absolue : `4:30/km Pace`, plage `4:30-5:00/km Pace` (rapide→lent).
- FC absolue : `150 HR`, plage `145-155 HR`.
- Puissance : `200W`.
- Label warmup/cooldown : `- Warmup 10m ...`.
- Répétition : ligne `Nx` puis les steps ; blocs séparés par ligne vide.
- Endpoint : `POST /api/v1/athlete/{id}/events`, body `{start_date_local "…T00:00:00",
  category:"WORKOUT", type:"Run", name, description, external_id}`.

## Étapes
- [ ] 1. `models.py` : dataclass `IntervalsConfig` (api_key, athlete_id, base_url opt.)
- [ ] 2. `intervals.py` (neuf) :
  - [ ] `INTERVALS_API_BASE`, `load_intervals_config` (env > config.json)
  - [ ] `INTERVALS_SPORT_TYPES` + `intervals_sport_type()`
  - [ ] `workout_description_from_items()` (mapper blocs → texte)
  - [ ] `build_event_payload()` (start_date_local T00:00:00, category=WORKOUT, external_id)
  - [ ] `IntervalsClient` (Basic auth API_KEY:clé, retries 5xx/429/timeout, `create_event`)
- [ ] 3. `cli.py` : groupe `intervals status [--json]` + `plan session push-intervals <id> [--dry-run]`
- [ ] 4. `tests/test_intervals.py` : config, mapping texte, payload, client (httpserver)
- [ ] 5. tests CLI `push-intervals` dans `tests/test_cli_coach.py`
- [ ] 6. docs : CLAUDE.md (CLI), specs.md (lot 10), backlog.md
- [ ] 7. `make validate` vert

## Note de simplification (vs plan)
Pas de fichier `intervals_auth.py` séparé : pas d'OAuth, juste une clé API.
`IntervalsConfig` → `models.py`, `load_intervals_config` → `intervals.py`.
Tests de config → `tests/test_intervals.py` (pas de fichier auth dédié).

## Risque #1 (à lever au test manuel)
Grammaire exacte pace/FC à confirmer contre l'API réelle + rendu montre.
Idempotence `external_id` : à vérifier (re-push = pas de doublon ?).

## Résultat

Lot 10 **livré ET validé bout-en-bout (upload Suunto inclus)** (10.7 ✅). `make validate`
vert : **337 tests** (23 nouveaux), ruff + mypy --strict clean. **Zéro dépendance ajoutée**.

⚠️ **3 fixs majeurs trouvés en smoke test** (tous via tests jetables create→GET→delete,
cf. lessons.md) :
1. **Texte → `workout_doc` structuré** : la 1ère version générait le texte « workout
   builder », mais la séance arrivait en texte brut sur la montre. Bascule sur le JSON.
2. **FC bpm → %FCmax** : le `workout_doc` avec FC en bpm est accepté par intervals.icu
   MAIS **rejeté par l'upload Suunto** (`value > 250`). Conversion `bpm → %FCmax` (avec
   `fc_max` DB) requise. Diag via `event.push_errors` + dates dans la fenêtre d'upload.
3. **Upsert** : `POST` ne dé-duplique pas sur `external_id` → `upsert_event` (GET+PUT/POST).

Livré :
- `models.py` : `IntervalsConfig` (api_key, athlete_id, base_url opt.).
- `intervals.py` : `load_intervals_config` (env > config.json), `intervals_sport_type`,
  `workout_doc_from_items` (blocs canoniques → `workout_doc` structuré : pace `secs/km`,
  **hr `bpm` absolu**, power `w`, `reps`/`steps`, labels `text`), `build_event_payload`
  (external_id=`claude-coach-<id>`), `IntervalsClient.upsert_event` (GET+PUT/POST
  idempotent, Basic `API_KEY:<clé>`, retries 5xx/429/timeout, 401/403→AuthError).
- `cli.py` : groupe `intervals status`, `plan session push-intervals <ID> [--dry-run]`.
- Tests : `test_intervals.py` (mapping workout_doc, payload, client POST+upsert) + CLI.
- Docs : `CLAUDE.md`, `specs.md` (lot 10), `backlog.md`, `.claude/agents/coach.md`,
  `tasks/lessons.md` (2 leçons : texte vs structuré, idempotence upsert).

**Smoke test (2026-06-10)** : config posée (athlete `i609642`), « Upload planned
workouts » coché. Push séance #18 (Run, FC 130-148 bpm) → event **structuré** dans le
calendrier + descente Suunto 9 OK. Re-push idempotent confirmé (même event id 115354348,
1 seul event).
