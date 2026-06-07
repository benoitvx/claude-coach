# Spécifications — claude-coach

## 1. Vue d'ensemble

**claude-coach** est un connecteur CLI qui synchronise les activités sportives depuis l'API Strava vers une base SQLite locale. Il sert de source de données pour un futur agent coach sportif IA opérant dans Claude Code.

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

1. L'utilisateur lance `claude-coach auth`
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
`claude-coach sync --full` chaque jour. Préféré à cron parce que la plist
est éditable, les logs sont centralisés (`~/Library/Logs/claude-coach/`)
et l'agent est rechargeable de façon idempotente.

Schedule par défaut du script : **02:05 heure locale** — juste après le reset
du quota journalier Strava (00:00 UTC = 02:00 Paris). Override possible via
env vars : `SYNC_HOUR=12 SYNC_MINUTE=30 bash scripts/install-launchd-sync.sh`
(idempotent, remplace l'agent existant).

Deux phases :
1. **Pendant l'import historique initial** (Mac laissé allumé la nuit) :
   `02:05` est optimal — quota frais, plage longue avant le réveil.
2. **Une fois l'historique terminé** (status `success` complet sur la fenêtre
   `history_days`) : basculer vers une heure de jour, plus tolérante à un Mac
   qui dort la nuit. **État actuel : 10:00 heure locale** (basculement
   2026-05-08, après import des 357 activités sur 2 ans).

Le script utilise `sync --full` quelle que soit la phase — le coût d'un `--full`
en steady state est marginal grâce à `has_complete_activity` (skip immédiat des
activités déjà en DB). L'usage typique en steady state : ~10-15 requêtes/jour
sur un quota de 1000.

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
- `claude-coach auth` : flow OAuth2 complet (faux Strava → callback → tokens en DB)
- `claude-coach sync --full` : pagination + détail + streams → vérifier données en DB
- `claude-coach sync` : sync incrémentale, ne re-télécharge pas les activités existantes
- `claude-coach status` : affichage correct après un sync
- Rate limiting : vérifier que le client pause quand les headers indiquent une limite proche

Le faux serveur retourne des fixtures JSON réalistes (activités de différents types : run, ride, swim, multisport).

### Pas de tests E2E automatisés

Pas de tests contre la vraie API Strava : consomme du rate limit, lent, flaky, nécessite des vrais tokens. La vérification contre la vraie API se fait manuellement par l'utilisateur.

### Couverture cible

- 70% minimum pour le code nouveau
- 90%+ pour les chemins critiques : auth, sync, rate limiting, reprise après interruption

## 9. Vision future (hors scope v1)

### Agent coach IA (lot 5)

L'agent Claude Code accède à la DB via **commandes CLI lues en Bash** (pas MCP).
Hébergé en **subagent Claude Code** dans `.claude/agents/` (pas de service Python
autonome). L'agent :
- Analyse l'historique d'entraînement (charge, progression, patterns)
- Prend en compte les données athlète (poids, FTP, FCmax, VMA)
- Génère des plans séance par séance vers les objectifs définis (cf. §10)
- Compare séances réalisées vs planifiées pour ajuster le plan

Découpage en sous-lots :
- **5a** : modèle de données objectifs/plans/séances ✅ (cf. §10)
- **5b** : matching planifié vs réalisé (date + sport_type) ✅ (cf. §10)
- **5c** : commandes CLI orientées agent (queries riches, sortie JSON) ✅ (cf. §11)
- **5d** : subagent + system prompt avec règles d'entraînement ✅ (`.claude/agents/coach.md`)

### Export workouts (lot 6)

Exporter les séances planifiées par l'agent vers :
- **Suunto** : fichiers `.fit` ou via Suunto API
- **Zwift** : fichiers `.zwo` (format XML natif Zwift)

Permettre à l'utilisateur de suivre le programme directement sur sa montre ou dans Zwift.

## 10. Modèle de données — objectifs et planification

<!-- Lots 5a-5b livrés ; 5c-5d à venir -->

Migration 003 (lot 5a) introduit trois tables qui supportent la planification
d'entraînement et serviront de base à l'agent coach (lot 5c/5d). Le matching
automatique `planned_sessions.actual_activity_id` ↔ `activities.id` est livré
en lot 5b via le module `coach.py` et la commande `claude-coach plan match`.

### Table `goals`

Objectifs sportifs (courses, événements cibles).

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | |
| name | TEXT NOT NULL | Ex: "Swim&Run Sept 2026" |
| discipline | TEXT | run / swim_run / trail / triathlon / ride / swim / other |
| target_date | TEXT | ISO date (YYYY-MM-DD) |
| description | TEXT | Description libre |
| success_criteria | TEXT | Critères de réussite |
| status | TEXT NOT NULL | active / completed / abandoned (default 'active') |
| created_at | TEXT NOT NULL | ISO 8601 UTC |
| updated_at | TEXT NOT NULL | ISO 8601 UTC |

Index : `idx_goals_target_date(target_date)`.

### Table `training_plans`

Plan d'entraînement, optionnellement rattaché à un goal.

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | |
| goal_id | INTEGER FK → goals(id) ON DELETE SET NULL | nullable (rebuild block sans event) |
| name | TEXT NOT NULL | |
| start_date | TEXT NOT NULL | ISO date |
| end_date | TEXT NOT NULL | ISO date |
| status | TEXT NOT NULL | active / completed / paused / abandoned (default 'active') |
| notes | TEXT | |
| created_at | TEXT NOT NULL | |
| updated_at | TEXT NOT NULL | |

Index : `idx_training_plans_goal(goal_id)`.

### Table `planned_sessions`

Séances planifiées par l'agent (ou saisies manuellement).

| Colonne | Type | Description |
|---------|------|-------------|
| id | INTEGER PK | |
| training_plan_id | INTEGER NOT NULL FK → training_plans(id) ON DELETE CASCADE | |
| planned_date | TEXT NOT NULL | ISO date locale |
| sport_type | TEXT NOT NULL | Conforme à `activities.sport_type` (Run, Ride, Swim, TrailRun, ...) |
| session_type | TEXT | endurance / threshold / intervals / long / race / recovery / renfo |
| target_duration_s | INTEGER | Durée cible en secondes |
| target_distance_m | REAL | Distance cible en mètres |
| target_intensity | TEXT | easy / moderate / threshold / vo2max / race |
| description | TEXT | Détail séance (ex "10' éch + 5×3' VMA r=2' + 10' RAC") |
| actual_activity_id | INTEGER FK → activities(id) ON DELETE SET NULL | Rempli par le matching (lot 5b) |
| status | TEXT NOT NULL | planned / done / skipped / missed (default 'planned') |
| notes | TEXT | |
| created_at | TEXT NOT NULL | |
| updated_at | TEXT NOT NULL | |

Index : `idx_planned_sessions_plan_date(training_plan_id, planned_date)`,
`idx_planned_sessions_actual_activity(actual_activity_id)`.

### Commandes CLI (lots 5a + 5b)

```bash
# Objectifs
claude-coach goal add --name <NAME> [--target-date YYYY-MM-DD] [--discipline ...] [--description ...] [--success-criteria ...]
claude-coach goal list [--status active|completed|abandoned]
claude-coach goal show <ID>
claude-coach goal complete <ID>

# Plans d'entraînement
claude-coach plan add --name <NAME> --start YYYY-MM-DD --end YYYY-MM-DD [--goal-id <ID>] [--notes ...]
claude-coach plan list [--goal-id <ID>] [--status ...]
claude-coach plan show <ID>          # affiche plan + ses planned_sessions (+ ligne réalisé si match)
claude-coach plan match [--plan-id <ID>] [--dry-run]  # apparie séances ↔ activités (lot 5b)

# Séances planifiées (sous-groupe `plan session`)
claude-coach plan session add --plan-id <ID> --date YYYY-MM-DD --sport <SPORT> [--session-type ...] [--duration <S>] [--distance <M>] [--intensity ...] [--description ...]
claude-coach plan session list --plan-id <ID> [--status ...]
claude-coach plan session done <ID>  # marquage manuel sans lien vers une activité Strava
claude-coach plan session skip <ID>  # séance passée volontairement (substitution, repos)
claude-coach plan session delete <ID>  # supprime une séance non réalisée (report/replanif), refus si statut ≠ planned
```

Validation des enums : `click.Choice(...)` côté CLI seulement, pas de CHECK SQL
(cohérent avec le reste du projet). Les contraintes Python sont dans
`db.GOAL_STATUSES`, `db.PLAN_STATUSES`, `db.SESSION_STATUSES`.

### Matching planifié vs réalisé (lot 5b)

Le module `src/claude_coach/coach.py` apparie chaque `planned_session` en
statut `planned` à l'`Activity` la plus probable :

- **Familles de sport** (table `SPORT_FAMILIES` dans `coach.py`) : `Run` / `TrailRun` / `VirtualRun` → famille `run` ; `Ride` / `VirtualRide` / `GravelRide` / `EBikeRide` / `MountainBikeRide` → `ride` ; `Walk` / `Hike` → `walk` ; etc. Les sports non listés sont leur propre famille (`sport_type.lower()`).
- **Fenêtre de date** : `start_date_local` de l'activité doit être dans `[planned_date - 1j, planned_date + 1j]`.
- **Tri des candidats** : (1) même jour calendaire avant ±1 jour, (2) `moving_time_s` décroissant, (3) `id` croissant pour départager.
- **Algorithme greedy chronologique** : les séances sont traitées par `planned_date` croissante. Si deux séances peuvent réclamer la même activité, la plus ancienne gagne. Une activité ne peut être liée qu'à une seule séance.
- **Effets de bord** : la séance matchée passe en `status = 'done'` et `actual_activity_id` est rempli. Les séances déjà `done` / `skipped` sont ignorées.
- **Idempotence** : relancer `plan match` ne re-matche pas les séances déjà liées et n'utilise pas les activités déjà liées.
- **Sans `--plan-id`** : matche les séances de tous les plans `active`. Avec `--plan-id <N>` : ce plan uniquement (peu importe son statut).
- **`--dry-run`** : affiche les matchings sans écrire en DB.

Les écarts (durée / distance) sont calculés à la volée via `coach.session_deltas`
et affichés dans `plan show` sous la forme :

```
   1  2026-06-15  Run     intervals  60min   10.0km  done   ...
        ↳ réalisé : 58 min, 9.8 km, FCmoy 158 (Δdurée -2 min, Δdist -0.2 km)
```

Pas de stockage des deltas en DB (recalculés à chaque lecture).

## 11. Surface CLI orientée agent (lot 5c)

Le futur subagent coach (lot 5d) lit la base via la CLI, en exécutant des
commandes Bash. Pour qu'il puisse parser les sorties sans fragilité, les
commandes de lecture acceptent `--json`.

### Commandes avec `--json`

- `status` (DB + tokens + dernière sync + métriques athlète)
- `goal list`, `goal show`
- `plan list`, `plan show` (séances embarquées + bloc `realized` quand match)
- `plan match` (matched/unmatched + `dry_run` + `plan_id`)
- `plan session list`
- `athlete show` (objet ou `null` si pas de saisie), `athlete history`
- `activity list`, `activity show`, `activity stats` (lot 5c.2)
- `activity laps <ID>` (lot 5c.4 — laps segmentés par la montre, hors `show` pour rester compact)
- `activity streams <ID> [--type ...]` (lot 5c.5 — streams seconde-par-seconde, filtrable par type)

Les commandes d'écriture (`add`, `complete`, `done`, `set`, `auth`, `sync`)
n'ont pas de `--json` — l'agent se base sur le code de retour.

### Conventions JSON

| Aspect | Convention |
|--------|------------|
| Listes | array JSON direct (`[...]`), pas d'enveloppe `{"items": ...}`. |
| Show | objet plat. |
| Casing | `snake_case` partout (cohérent avec la DB). |
| Dates | ISO 8601 (`2026-04-22` ou `2026-04-22T10:00:00+00:00`). |
| Champs absents | `null`, jamais omis — l'agent peut compter sur la présence des clés. |
| Secrets | jamais sérialisés (`access_token`, `refresh_token` exclus de `status`). |
| `raw_json` / `map_polyline` / `splits_metric` | exclus côté `activity` (bruit). |
| Laps | exposés via commande dédiée `activity laps <ID>`, pas dans `show` (évite de charger les laps sur listes massives). |

### Schéma `activity stats --json`

```json
{
  "group_by": "month",
  "buckets": [
    {"key": "2026-04", "count": 12, "distance_m": 145000.0,
     "moving_time_s": 32400, "elevation_gain_m": 1850.0}
  ],
  "total": {"count": 12, "distance_m": 145000.0,
            "moving_time_s": 32400, "elevation_gain_m": 1850.0}
}
```

### Stabilité

Tout changement de format JSON doit être signalé dans le message de commit.
La sérialisation est centralisée dans `src/claude_coach/serializers.py`
(une fonction par modèle).
