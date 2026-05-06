# Backlog — strava-connect

## Lot 0 — Setup projet

- [x] **0.1** Initialiser le repo : `pyproject.toml` (uv), structure `src/strava_connect/`, `tests/`, `data/`, `tasks/`
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
- [x] **1.5** Commande CLI `strava-connect auth` : flow complet d'authentification
- [x] **1.6** Commande CLI `strava-connect status` : état de la DB, dernière sync, nombre d'activités
- [x] **1.7** Tests unitaires : DB CRUD avec SQLite en mémoire, migrations, refresh token (mock HTTP)
- [x] **1.8** Tests intégration : commande `auth` complète avec faux serveur HTTP simulant Strava

## Lot 2 — Import historique

- [ ] **2.1** Implémenter le client API Strava (`client.py`) : wrapper httpx avec auth header, gestion des erreurs HTTP
- [ ] **2.2** Implémenter le rate limiter : lecture des headers `X-ReadRateLimit-Usage`, pause automatique, respect des fenêtres 15 min
- [ ] **2.3** Implémenter la récupération paginée des activités (`GET /athlete/activities`)
- [ ] **2.4** Implémenter la récupération détaillée par activité : detail, streams, laps, zones
- [ ] **2.5** Implémenter la logique de sync complète (`sync.py`) : orchestration, reprise après interruption, logging dans `sync_log`
- [ ] **2.6** Commande CLI `strava-connect sync --full` : import complet avec barre de progression et `caffeinate` (macOS) pour empêcher la mise en veille
- [ ] **2.7** Tests unitaires : client API (mock HTTP), rate limiter (simulation headers), sync logic, reprise après interruption
- [ ] **2.8** Tests intégration : `sync --full` complet avec faux serveur (fixtures multi-types : run, ride, swim), vérification des données en DB

## Lot 3 — Sync incrémentale

- [ ] **3.1** Implémenter la sync incrémentale : détection des nouvelles activités depuis la dernière sync
- [ ] **3.2** Commande CLI `strava-connect sync` (sans `--full`) : sync incrémentale
- [ ] **3.3** Gestion des activités modifiées/supprimées sur Strava
- [ ] **3.4** Script/commande pour lancer la sync via cron ou manuellement après une séance
- [ ] **3.5** Tests unitaires : détection de doublons, activités supprimées
- [ ] **3.6** Tests intégration : `sync` incrémentale avec faux serveur, vérifier qu'on ne re-télécharge pas les activités existantes

## Lot 4 — Données athlète

- [ ] **4.1** Commande CLI `strava-connect athlete set --weight 75 --ftp 250 --fc-max 190 --fc-repos 48 --vma 17.5`
- [ ] **4.2** Commande CLI `strava-connect athlete show` : afficher les données actuelles
- [ ] **4.3** Historisation des valeurs (pouvoir voir l'évolution du poids, FTP, etc.)
- [ ] **4.4** Tests

## Lot 5 — Agent coach IA

> À spécifier en détail quand les lots 1-4 sont terminés. Grandes lignes :

- [ ] **5.1** Définir le modèle de données pour les objectifs (table `goals` : type, date cible, description, critères de réussite)
- [ ] **5.2** Définir le modèle de données pour les plans d'entraînement (tables `training_plans`, `planned_sessions`)
- [ ] **5.3** Implémenter la comparaison séance planifiée vs réalisée (matching par date/type, calcul des deltas)
- [ ] **5.4** Créer les outils MCP ou les commandes CLI que l'agent utilisera pour lire/écrire dans la DB
- [ ] **5.5** Écrire le system prompt de l'agent coach avec les règles d'entraînement (périodisation, charge progressive, récupération, spécificité par discipline)
- [ ] **5.6** Tests : matching planifié/réalisé, cohérence des plans générés

## Lot 6 — Export workouts vers services tiers

> À spécifier en détail quand le lot 5 est terminé. Grandes lignes :

- [ ] **6.1** Rechercher les formats acceptés par Suunto (API ou fichiers .fit) et Zwift (fichiers .zwo)
- [ ] **6.2** Générer des fichiers `.zwo` (XML) pour les séances vélo Zwift
- [ ] **6.3** Générer des fichiers `.fit` pour les séances Suunto
- [ ] **6.4** Commande CLI `strava-connect export --target zwift|suunto --session <id>`
- [ ] **6.5** Tests : génération de fichiers, validation des formats

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
