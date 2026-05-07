# Spécifications — strava-connect

## 1. Vue d'ensemble

**strava-connect** est un connecteur CLI qui synchronise les activités sportives depuis l'API Strava vers une base SQLite locale. Il sert de source de données pour un futur agent coach sportif IA opérant dans Claude Code.

### Utilisateur cible

Sportif multi-disciplines (triathlon, trail, natation, vélo, course, renfo) utilisant Strava comme agrégateur de données provenant de Suunto, Garmin et Zwift.

### Objectif à terme

Alimenter un agent IA qui :
- Analyse l'historique d'entraînement
- Génère des plans d'entraînement séance par séance
- Compare les séances réalisées vs planifiées pour ajuster le plan
- Exporte les workouts planifiés vers Suunto / Zwift

## 2. Stack technique

| Composant | Choix | Justification |
|-----------|-------|---------------|
| Langage | Python 3.12+ | Écosystème data/IA, stdlib riche, facile à maintenir |
| Base de données | SQLite | Fichier local, zero config, portable, suffisant pour mono-utilisateur |
| Packaging | uv | Rapide, gère venv + deps + scripts |
| CLI | click | Standard Python, simple, bien documenté |
| HTTP | httpx | Async-ready, timeout natif, meilleur que requests |
| Tests | pytest | Standard Python |
| Linting | ruff | Rapide, remplace flake8+isort+black |
| Types | mypy --strict | Sécurité du typage |

### Pourquoi pas Infomaniak mutualisé ?

L'hébergement mutualisé Infomaniak est PHP/MySQL uniquement. Python n'y est pas supporté. Pour un outil CLI + agent local, une base SQLite locale est plus simple et suffisante. Si besoin futur d'un serveur (webhooks, multi-device), migrer vers un VPS.

## 3. Authentification Strava (OAuth2)

### Flow

1. L'utilisateur lance `strava-connect auth`
2. Le CLI ouvre le navigateur vers `https://www.strava.com/oauth/authorize` avec les paramètres :
   - `client_id` (depuis config)
   - `redirect_uri=http://localhost:8000/callback`
   - `response_type=code`
   - `scope=read,activity:read_all`
   - `approval_prompt=auto`
3. Un serveur HTTP local temporaire écoute sur `localhost:8000`
4. L'utilisateur autorise l'app dans Strava
5. Strava redirige vers `localhost:8000/callback?code=XXX`
6. Le CLI échange le code contre un access_token + refresh_token via `POST /oauth/token`
7. Les tokens sont stockés dans `data/tokens.json` (gitignored)

### Refresh automatique

Avant chaque appel API :
- Vérifier si `access_token` expire dans < 5 minutes
- Si oui, appeler `POST /oauth/token` avec `grant_type=refresh_token`
- Stocker le nouveau `refresh_token` immédiatement (l'ancien est invalidé)

### Prérequis utilisateur

Créer une application sur https://www.strava.com/settings/api :
- **Application Name** : au choix
- **Authorization Callback Domain** : `localhost`
- Récupérer `client_id` et `client_secret`

Les stocker dans `data/config.json` ou via variables d'environnement `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET`.

## 4. Modèle de données

### Table `athletes`

Données athlète manuelles (pas récupérées de Strava).

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | Strava athlete ID |
| weight_kg | REAL | Poids en kg |
| ftp_watts | INTEGER | Functional Threshold Power |
| fc_max | INTEGER | Fréquence cardiaque max |
| fc_repos | INTEGER | Fréquence cardiaque au repos |
| vma_kmh | REAL | Vitesse Maximale Aérobie |
| updated_at | TEXT | ISO 8601 |

### Table `activities`

Données résumé + détail de chaque activité.

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | Strava activity ID |
| athlete_id | INTEGER FK | Ref athletes |
| name | TEXT | Nom de l'activité |
| sport_type | TEXT | Type Strava (Run, Ride, Swim, etc.) |
| start_date | TEXT | ISO 8601 UTC |
| start_date_local | TEXT | ISO 8601 local |
| timezone | TEXT | Timezone string |
| distance_m | REAL | Distance en mètres |
| moving_time_s | INTEGER | Temps en mouvement (secondes) |
| elapsed_time_s | INTEGER | Temps total (secondes) |
| total_elevation_gain_m | REAL | Dénivelé positif (mètres) |
| average_speed_ms | REAL | Vitesse moyenne (m/s) |
| max_speed_ms | REAL | Vitesse max (m/s) |
| average_heartrate | REAL | FC moyenne |
| max_heartrate | REAL | FC max |
| average_watts | REAL | Puissance moyenne (si dispo) |
| max_watts | REAL | Puissance max |
| average_cadence | REAL | Cadence moyenne |
| calories | REAL | Calories estimées |
| suffer_score | INTEGER | Score d'effort Strava |
| description | TEXT | Description de l'activité |
| device_name | TEXT | Appareil utilisé |
| gear_id | TEXT | Équipement Strava |
| has_heartrate | BOOLEAN | FC disponible |
| has_power | BOOLEAN | Puissance disponible |
| trainer | BOOLEAN | Activité indoor/trainer |
| map_polyline | TEXT | Polyline encodée |
| splits_metric | TEXT | JSON des splits métriques |
| raw_json | TEXT | JSON brut Strava (DetailedActivity) |
| synced_at | TEXT | Date de dernière sync |

### Table `activity_streams`

Données seconde par seconde. Chaque type de stream est une ligne.

| Colonne | Type | Description |
|---------|------|-------------|
| activity_id | INTEGER FK | Ref activities |
| stream_type | TEXT | time, latlng, distance, altitude, heartrate, cadence, watts, temp, velocity_smooth, grade_smooth, moving |
| data | TEXT | JSON array des valeurs |
| resolution | TEXT | "high" ou "low" |
| PK | | (activity_id, stream_type) |

### Table `activity_laps`

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | Strava lap ID |
| activity_id | INTEGER FK | Ref activities |
| name | TEXT | Nom du lap |
| lap_index | INTEGER | Index du lap |
| distance_m | REAL | Distance |
| moving_time_s | INTEGER | Temps en mouvement |
| elapsed_time_s | INTEGER | Temps total |
| start_index | INTEGER | Index début dans le stream |
| end_index | INTEGER | Index fin dans le stream |
| average_speed_ms | REAL | |
| max_speed_ms | REAL | |
| average_heartrate | REAL | |
| max_heartrate | REAL | |
| average_watts | REAL | |
| average_cadence | REAL | |
| total_elevation_gain_m | REAL | |

### Table `activity_zones`

| Colonne | Type | Description |
|---------|------|-------------|
| activity_id | INTEGER FK | Ref activities |
| zone_type | TEXT | heartrate, power, pace |
| data | TEXT | JSON des zones (distribution) |
| PK | | (activity_id, zone_type) |

### Table `sync_log`

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK AUTOINCREMENT | |
| started_at | TEXT | Début de sync |
| finished_at | TEXT | Fin de sync |
| sync_type | TEXT | "full" ou "incremental" |
| activities_fetched | INTEGER | Nombre d'activités récupérées |
| status | TEXT | "success", "partial", "error" |
| error_message | TEXT | Détail si erreur |

## 5. Synchronisation

### Import complet (`sync --full`)

1. Calculer la date "il y a 2 ans"
2. Paginer `GET /athlete/activities?after={epoch}&per_page=30`
3. Pour chaque activité :
   a. `GET /activities/{id}` → detail
   b. `GET /activities/{id}/streams` → streams
   c. `GET /activities/{id}/laps` → laps
   d. `GET /activities/{id}/zones` → zones (si Summit)
4. Insérer/mettre à jour en DB
5. Logger dans `sync_log`

### Sync incrémentale (`sync`)

1. Lire la date de la dernière activité en DB
2. `GET /athlete/activities?after={epoch}` pour les nouvelles
3. Même traitement par activité que l'import complet
4. Logger dans `sync_log`

### Gestion du rate limiting

- **100 lectures / 15 min** : pacer à ~25 activités complètes / 15 min (4 req/activité)
- Lire les headers `X-ReadRateLimit-Usage` après chaque requête
- Si usage > 90% de la limite 15 min → `sleep()` jusqu'à la prochaine fenêtre (:00, :15, :30, :45)
- Si limite journalière atteinte → sauvegarder la progression et reprendre le lendemain
- L'import complet est **reprise-safe** : ne re-télécharge pas les activités déjà en DB

### Prévention de la mise en veille

L'import complet dure plusieurs heures réparties sur 2 jours. Pour empêcher la mise en veille de la machine pendant le sync :
- **macOS** : le CLI lance `caffeinate -i` en sous-processus pendant la durée du sync
- **Linux** : `systemd-inhibit` si disponible
- Afficher un avertissement au lancement si aucun mécanisme n'est disponible

### Gestion des erreurs

- Retry automatique avec backoff exponentiel sur erreurs 5xx et timeouts
- Sur erreur 429 (rate limit) : pause et retry après le délai indiqué
- Sur erreur 401 : tenter un refresh token, puis re-auth si échec
- Log de chaque erreur dans `sync_log`

### Sync planifiée (macOS)

`scripts/install-launchd-sync.sh` installe une tâche **launchd** qui exécute
`strava-connect sync --full` chaque jour. Préféré à cron parce que la plist
est éditable, les logs sont centralisés (`~/Library/Logs/strava-connect/`)
et l'agent est rechargeable de façon idempotente.

Schedule par défaut : **02:05 heure locale** — juste après le reset du quota
journalier Strava (00:00 UTC = 02:00 Paris). Override possible via env vars :
`SYNC_HOUR=12 SYNC_MINUTE=30 bash scripts/install-launchd-sync.sh`.

Pendant l'import historique initial (Mac laissé allumé la nuit), 02:05 est
optimal. Une fois l'historique fini, basculer vers une heure de jour (ex 12:30)
plus tolérante à un Mac qui dort la nuit. Le script utilise `sync --full`
pour rester compatible avec les deux phases — le coût d'un `--full`
incrémental est marginal grâce à `has_complete_activity`.

Voir `tasks/lessons.md` pour les commandes de vérification et désinstallation.

Sur Linux : non couvert (cron classique ou systemd timer feraient l'affaire).

## 6. Configuration

Fichier `data/config.json` (gitignored) :

```json
{
  "client_id": "123456",
  "client_secret": "abcdef...",
  "history_days": 730
}
```

Alternative : variables d'environnement `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`.

Priorité : env vars > config.json.

## 7. Sécurité

- `data/` entier dans `.gitignore` (tokens, config avec secrets, DB)
- Jamais de secrets en dur dans le code
- `gitleaks` en pre-commit pour détecter les fuites
- Les tokens Strava ont une durée de vie courte (6h) + refresh automatique

## 8. Stratégie de tests

### Tests unitaires (pytest)

Majorité de la couverture. Testent la logique métier isolément avec des mocks :
- **db.py** : CRUD, migrations, requêtes (utilise une DB SQLite en mémoire)
- **auth.py** : échange de code, refresh token, détection d'expiration (mock HTTP)
- **client.py** : parsing des réponses Strava, gestion des erreurs HTTP, rate limiter (mock HTTP)
- **sync.py** : orchestration, reprise après interruption, détection de doublons (mock client + DB)
- **models.py** : conversion JSON Strava → modèles internes

### Tests d'intégration (pytest + faux serveur HTTP)

Testent les commandes CLI de bout en bout avec un faux serveur HTTP local qui simule l'API Strava :
- `strava-connect auth` : flow OAuth2 complet (faux Strava → callback → tokens en DB)
- `strava-connect sync --full` : pagination + détail + streams → vérifier données en DB
- `strava-connect sync` : sync incrémentale, ne re-télécharge pas les activités existantes
- `strava-connect status` : affichage correct après un sync
- Rate limiting : vérifier que le client pause quand les headers indiquent une limite proche

Le faux serveur retourne des fixtures JSON réalistes (activités de différents types : run, ride, swim, multisport).

### Pas de tests E2E automatisés

Pas de tests contre la vraie API Strava : consomme du rate limit, lent, flaky, nécessite des vrais tokens. La vérification contre la vraie API se fait manuellement par l'utilisateur.

### Couverture cible

- 70% minimum pour le code nouveau
- 90%+ pour les chemins critiques : auth, sync, rate limiting, reprise après interruption

## 9. Vision future (hors scope v1)

### Agent coach IA (lot 3)

L'agent Claude Code accède directement à la DB SQLite pour :
- Analyser l'historique d'entraînement (charge, progression, patterns)
- Prendre en compte les données athlète (poids, FTP, FCmax, VMA)
- Générer des plans séance par séance vers des objectifs définis :
  - Swim & Run (13.5km run + 3.5km nage) — septembre 2026
  - Trail 50km / 2000m D+ — octobre 2026
  - Ironman 70.3 — printemps 2027
- Comparer séances réalisées vs planifiées pour ajuster le plan
- Stocker les plans et objectifs dans des tables dédiées (à spécifier en lot 3)

### Export workouts (lot 4)

Exporter les séances planifiées par l'agent vers :
- **Suunto** : fichiers `.fit` ou via Suunto API
- **Zwift** : fichiers `.zwo` (format XML natif Zwift)

Permettre à l'utilisateur de suivre le programme directement sur sa montre ou dans Zwift.
