# Backlog — claude-coach

## Lot 0 — Setup projet

- [x] **0.1** Initialiser le repo : `pyproject.toml` (uv), structure `src/claude_coach/`, `tests/`, `data/`, `tasks/`
- [x] **0.2** Configurer ruff, mypy, pytest dans `pyproject.toml`
- [x] **0.3** Écrire le `Makefile` (install, validate, test, lint, format, typecheck)
- [x] **0.4** Configurer `.gitignore` (data/, .venv/, __pycache__, etc.)
- [x] **0.5** Configurer pre-commit : gitleaks + make validate (framework `pre-commit`)
- [x] **0.6** CI GitHub Actions : lint + typecheck + tests sur push/PR
- [x] **0.7** Initialiser `tasks/todo.md` et `tasks/lessons.md`

## Lot 1 — Authentification & base de données

- [x] **1.1** Créer le schéma SQLite (tables : athletes, activities, activity_streams, activity_laps, activity_zones, sync_log) avec migrations versionnées
- [x] **1.2** Implémenter la couche DB (`db.py`) : connexion, migrations, CRUD de base
- [x] **1.3** Implémenter le flow OAuth2 (`auth.py`) : ouverture navigateur, serveur callback local, échange code → tokens, stockage dans `data/tokens.json`
- [x] **1.4** Implémenter le refresh automatique des tokens
- [x] **1.5** Commande CLI `claude-coach auth` : flow complet d'authentification
- [x] **1.6** Commande CLI `claude-coach status` : état de la DB, dernière sync, nombre d'activités
- [x] **1.7** Tests unitaires : DB CRUD avec SQLite en mémoire, migrations, refresh token (mock HTTP)
- [x] **1.8** Tests intégration : commande `auth` complète avec faux serveur HTTP simulant Strava

## Lot 2 — Import historique

- [x] **2.1** Implémenter le client API Strava (`client.py`) : wrapper httpx avec auth header, gestion des erreurs HTTP
- [x] **2.2** Implémenter le rate limiter : lecture des headers `X-ReadRateLimit-Usage`, pause automatique, respect des fenêtres 15 min
- [x] **2.3** Implémenter la récupération paginée des activités (`GET /athlete/activities`)
- [x] **2.4** Implémenter la récupération détaillée par activité : detail, streams, laps, zones
- [x] **2.5** Implémenter la logique de sync complète (`sync.py`) : orchestration, reprise après interruption, logging dans `sync_log`
- [x] **2.6** Commande CLI `claude-coach sync --full` : import complet avec barre de progression et `caffeinate` (macOS) pour empêcher la mise en veille
- [x] **2.7** Tests unitaires : client API (mock HTTP), rate limiter (simulation headers), sync logic, reprise après interruption
- [x] **2.8** Tests intégration : `sync --full` complet avec faux serveur (fixtures multi-types : run, ride, swim), vérification des données en DB

## Lot 3 — Sync incrémentale

- [x] **3.1** Implémenter la sync incrémentale : détection des nouvelles activités depuis la dernière sync
- [x] **3.2** Commande CLI `claude-coach sync` (sans `--full`) : sync incrémentale
- [~] **3.3** Gestion des activités modifiées/supprimées sur Strava _(scope-out — règle utilisateur : pas de modif/suppression Strava après upload)_
- [x] **3.4** Script/commande pour lancer la sync via cron ou manuellement après une séance _(doc dans `tasks/lessons.md`)_
- [x] **3.5** Tests unitaires : détection de doublons, activités supprimées
- [x] **3.6** Tests intégration : `sync` incrémentale avec faux serveur, vérifier qu'on ne re-télécharge pas les activités existantes

## Lot 4 — Données athlète

- [x] **4.1** Commande CLI `claude-coach athlete set --weight 75 --ftp 250 --fc-max 190 --fc-repos 48 --vma 17.5`
- [x] **4.2** Commande CLI `claude-coach athlete show` : afficher les données actuelles
- [x] **4.3** Historisation des valeurs (pouvoir voir l'évolution du poids, FTP, etc.) _(table `athlete_metrics` + commande `athlete history`)_
- [x] **4.4** Tests

## Lot 5 — Agent coach IA

Découpé en sous-lots après planification :
- **5a** : modèle de données objectifs/plans/séances (5.1, 5.2) ✅
- **5b** : matching planifié vs réalisé (5.3, 5.6 partiel) ✅
- **5c** : commandes CLI orientées agent (5.4) — sortie `--json` + groupe `activity` ✅
- **5d** : subagent coach dans `.claude/agents/coach.md` + system prompt (5.5) ✅

Itérations post-livraison (mai 2026, suite au dogfood) :
- **5c.4** : `activity laps` + intégration coach (séances intervals/threshold)
- **5c.5** : `activity streams` (long Z2, time-in-zone via Python ad-hoc)
- **5c.6** : status transitions manquantes (`goal abandon`, `plan complete/pause`, `plan session skip`)
- **5d.1** : workflow laps dans `coach.md` (Post-séance)
- **5d.2** : ACWR formel + data quality check + semantic check planifié↔réalisé + pattern stream long Z2
- **5d.3** : statut `abandoned` pour les plans (symétrique `goal abandon`)
- **5d.4** : coach — sync incrémentale systématique au démarrage + demande du ressenti avant tout débrief
- **5d.5** : coach — auto-applique `plan match` sur clean match (acter une séance faite = comportement par défaut, plus seulement proposé)
- **5d.6** : `plan session delete` — supprimer une séance non réalisée (report/replanif) sans polluer l'adhérence comme le ferait `skip`

- [x] **5.1** Définir le modèle de données pour les objectifs (table `goals` : type, date cible, description, critères de réussite) _(Lot 5a, migration 003)_
- [x] **5.2** Définir le modèle de données pour les plans d'entraînement (tables `training_plans`, `planned_sessions`) _(Lot 5a, migration 003)_
- [x] **5.3** Implémenter la comparaison séance planifiée vs réalisée (matching par date/type, calcul des deltas) _(Lot 5b, module `coach.py` + `plan match`)_
- [x] **5.4** Créer les outils MCP ou les commandes CLI que l'agent utilisera pour lire/écrire dans la DB _(Lot 5c — décision : CLI via Bash, sortie `--json` + groupe `activity` list/show/stats)_
- [x] **5.5** Écrire le system prompt de l'agent coach avec les règles d'entraînement (périodisation, charge progressive, récupération, spécificité par discipline) _(Lot 5d, `.claude/agents/coach.md` — polarisé 80/20, périodisation base/build/peak/taper, calibration FTP/VMA/FCmax)_
- [x] **5.6** Tests : matching planifié/réalisé _(Lot 5b — `tests/test_coach.py`)_ + smoke structurel du subagent _(Lot 5d — `tests/test_subagent_coach.py`)_. Cohérence des plans générés relève du dogfood (itération sur `coach.md`)

## Lot 6 — Export workouts vers services tiers

> À spécifier en détail quand le lot 5 est terminé. Grandes lignes :

- [x] **6.1** Rechercher les formats acceptés par Suunto (API ou fichiers .fit) et Zwift (fichiers .zwo) _(zwift = .zwo XML FTP-relatif ; choix module `zwo.py` stdlib)_
- [x] **6.2** Générer des fichiers `.zwo` (XML) pour les séances vélo Zwift _(module `zwo.py` + blocs structurés `blocks_json` migration 004 + mini-DSL)_
- [~] **6.3** ~~Générer des fichiers `.fit` pour les séances Suunto~~ **REMPLACÉ par le Lot 9** : Suunto n'importe **aucun** fichier de séance (FAQ/forum Suunto) → le chemin réaliste est l'API Nolio (sync auto Nolio→Suunto). Pas de génération FIT.
- [~] **6.4** Commande CLI export _(branche zwift livrée via `plan session export` ; le push Suunto passe par `plan session push-nolio`, lot 9 — pas de commande unifiée)_
- [x] **6.5** Tests : génération de fichiers, validation des formats _(zwift — `tests/test_zwo.py` + tests CLI)_

## Lot 9 — Export des séances structurées vers Nolio (→ Suunto 9)

Suunto n'accepte aucun import de fichier de séance directement sur la montre. La
voie réaliste (déjà fonctionnelle chez l'utilisateur) : **API Nolio** → la séance
structurée est synchronisée automatiquement en SuuntoPlus Guide vers la Suunto 9
(et Garmin). Pas de FIT, pas de nouvelle dépendance (`httpx` déjà présent).

- [x] **9.1** Recherche schéma API Nolio (OAuth2 Basic auth, `create/planned/training/`, `structured_workout`, sport-map, unités pace=m/s) _(doc `github.com/NolioApp/NolioAPI-Documentation`)_
- [x] **9.2** DSL running multi-cibles + blocs canoniques `Step`/`Repetition` _(module `workout.py` : allure/FC/durée/distance, notation `min`/`s`/`km`/`m`)_
- [x] **9.3** OAuth2 Nolio _(module `nolio_auth.py` : Basic auth, `expires_in`, refresh rotatif, tokens `data/nolio_tokens.json` 0o600)_
- [x] **9.4** Client API + mapping `structured_workout` + payload _(module `nolio.py` : `NolioClient` POST, sport-map, idempotence `id_partner`)_
- [x] **9.5** CLI : groupe `nolio` (`auth`/`status`), `plan session push-nolio <ID> [--dry-run]`, routage blocs vélo/running
- [x] **9.6** Tests : `test_workout.py`, `test_nolio.py`, `test_nolio_auth.py` + CLI dry-run
- [x] **9.7** Docs : `specs.md`, `backlog.md`, `README.md`, `.claude/agents/coach.md`
- [~] **9.8** Smoke test réel : OAuth `nolio auth` ✅, payload validé en dry-run ✅. **Push bloqué** : Nolio renvoie `403 "API access requires an active coach or premium subscription"` sur `create/planned/training/` → l'écriture API est réservée aux comptes coach/premium. Code OK (gestion 4xx ajoutée). **Reste** : abonnement Nolio premium/coach pour débloquer le push (puis confirmer l'unité d'allure m/s sur la montre), ou fallback saisie manuelle via `--dry-run`.

## Lot 7 — Débriefs de séance (ressenti / RPE / douleurs)

Persistance du ressenti subjectif d'une séance : le coach recueillait RPE /
sensations / douleurs en conversation sans rien stocker. Brique clé du suivi
surcharge (croisement `pain` récurrent ↔ ACWR).

- [x] **7.1** Table `session_debriefs` (migration 005) : `debrief_date` requise, liens optionnels `activity_id` + `planned_session_id` (ON DELETE SET NULL), `rpe` (CHECK 1-10), `feeling`, `pain`
- [x] **7.2** CRUD `db.py` (`insert/get/list/update/delete_debrief`) + sérialiseur `debrief_to_dict`
- [x] **7.3** Groupe CLI `debrief` : `add` / `list` / `show` / `edit` / `delete` (+ `--json` sur list/show)
- [x] **7.4** Intégration coach : `debrief add` auto (comme clean match), `debrief list` pour calibrer la charge, note Zwift/timezone
- [x] **7.5** Tests : migration, CRUD, CHECK rpe, ON DELETE SET NULL, CLI bout-en-bout _(`tests/test_db_debrief.py`, `tests/test_cli_debrief.py`)_
- [x] **7.6** Docs : `specs.md` §10 + CLI, `CLAUDE.md`, `.claude/agents/coach.md`

---

## Objectifs sportifs de référence

Ces objectifs guident la conception de l'agent coach (lot 5) :

| Objectif | Date cible | Détails |
|----------|-----------|---------|
| Swim & Run | Septembre 2026 | 13.5 km course + 3.5 km nage |
| Trail | Octobre 2026 | 50 km / 2000 m D+ |
| Ironman 70.3 | Printemps 2027 | 1.9 km nage + 90 km vélo + 21.1 km course |

## Estimation du volume de données

- ~20 activités/mois × 24 mois = **~480 activités** à importer
- ~4 requêtes API par activité = **~1920 requêtes** pour l'import complet
- Rate limit lectures : 1000/jour → **import complet en ~2 jours**
- Streams : quelques Mo par activité → **DB totale estimée ~500 Mo - 1 Go**
