# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

Connecteur API Strava qui récupère et stocke l'historique d'activités sportives dans une base locale. Brique data d'un futur agent coach sportif IA tournant dans Claude Code.

## Stack technique

- **Langage** : Python 3.12+
- **Base de données** : SQLite (fichier local `data/strava.db`)
- **Gestion de projet** : `uv` (packaging, venv, scripts)
- **Linting** : `ruff`
- **Type checking** : `mypy --strict`
- **Tests** : `pytest`
- **Pre-commit** : `gitleaks` + `make validate`

## Commandes

```bash
make install           # Créer le venv et installer les dépendances
make validate          # ruff check + mypy + pytest (point d'entrée unique)
make test              # pytest seul
make test-one F=<path> # Lancer un seul test
make lint              # ruff check + ruff format --check
make format            # ruff format (auto-fix)
make typecheck         # mypy --strict
make sync              # Lancer la synchro Strava (équivalent CLI)
```

## CLI

```bash
# Auth & sync (lots 1-3)
strava-connect auth           # Lancer le flow OAuth2 (une seule fois)
strava-connect sync --full    # Import complet historique (2 ans)
strava-connect sync           # Sync incrémentale (nouvelles activités)
strava-connect status         # État de la DB et dernière sync

# Données athlète historisées (lot 4)
strava-connect athlete set --weight 75 --ftp 260 --fc-max 190 --fc-repos 48 --vma 17.5
strava-connect athlete show
strava-connect athlete history [--limit N]

# Objectifs et planification (lot 5a)
strava-connect goal add --name <NAME> [--target-date YYYY-MM-DD] [--discipline ...]
strava-connect goal list [--status ...]
strava-connect goal show <ID>
strava-connect goal complete <ID>

strava-connect plan add --name <NAME> --start <DATE> --end <DATE> [--goal-id <ID>]
strava-connect plan list [--goal-id <ID>] [--status ...]
strava-connect plan show <ID>
strava-connect plan match [--plan-id <ID>] [--dry-run]   # apparie séances ↔ activités (lot 5b)

strava-connect plan session add --plan-id <ID> --date <DATE> --sport <Run|Ride|Swim|...> [opts]
strava-connect plan session list --plan-id <ID> [--status ...]
strava-connect plan session done <ID>

# Lecture activités pour l'agent coach (lot 5c)
strava-connect activity list  [--from <DATE>] [--to <DATE>] [--sport ...] [--family run|ride|swim|...] [--limit N]
strava-connect activity show  <ID>
strava-connect activity stats [--from <DATE>] [--to <DATE>] [--sport ...] [--family ...] [--by sport|week|month]
```

Toutes les commandes de lecture (`status`, `goal list/show`, `plan list/show/match`,
`plan session list`, `athlete show/history`, `activity list/show/stats`)
acceptent `--json` : sortie stable parseable (snake_case, ISO 8601, `null`
jamais omis). Conventions détaillées dans `specs.md` §11.

## Subagent coach (lot 5d)

Le repo embarque un subagent Claude Code dans `.claude/agents/coach.md`.
Il joue le rôle de coach sportif personnel : lit la DB locale via la CLI
`strava-connect`, analyse la charge, propose des plans périodisés vers les
objectifs (Swim&Run sept 2026, Trail oct 2026, 70.3 printemps 2027), et
ajuste après chaque séance.

**Invocation** : depuis une session Claude Code dans le repo, dis simplement
"demande au coach …" — Claude délègue automatiquement au subagent. Exemples :

- "demande au coach un état des lieux de ma forme actuelle"
- "demande au coach de me proposer le premier bloc Swim&Run"
- "demande au coach de débriefer ma séance de ce matin"

**Garde-fou** : le coach a accès à `Bash` (pour la CLI) et `Read` (pour
les specs) mais **propose** toujours les commandes d'écriture dans un bloc
` ```bash ` et **demande confirmation** avant exécution. Pas d'auto-application
silencieuse. Le système prompt encode : polarisé 80/20, charge progressive,
périodisation par bloc, spécificité par discipline, calibration sur
`athlete show --json`.

## Architecture

```
strava-connect/
├── src/strava_connect/
│   ├── cli.py            # Point d'entrée CLI (click)
│   ├── auth.py           # OAuth2 Strava (tokens, refresh)
│   ├── client.py         # Client API Strava (rate-limited)
│   ├── models.py         # Modèles de données (dataclasses)
│   ├── db.py             # Couche SQLite (migrations, CRUD)
│   ├── sync.py           # Logique de synchronisation
│   ├── coach.py          # Matching planifié vs réalisé (lot 5b)
│   └── serializers.py    # Sérialisation modèle → dict pour `--json` (lot 5c)
├── tests/
├── data/                 # DB SQLite + tokens (gitignored)
├── tasks/
│   ├── todo.md           # Plan de la tâche en cours
│   └── lessons.md        # Erreurs rencontrées (cumulatif)
└── Makefile
```

## API Strava — contraintes clés

- **Rate limits** : 100 lectures/15min, 1000 lectures/jour (par application)
- **Pas de bulk export** : pagination via `GET /athlete/activities` (max 30/page)
- **Import complet** : ~4 requêtes/activité (detail + streams + laps + zones) → ~1920 requêtes pour 2 ans (~480 activités) → **import sur 2 jours**
- **Tokens** : access_token expire en 6h, refresh_token à usage unique → toujours stocker le dernier refresh_token
- **Scopes requis** : `read,activity:read_all`

## Principes de développement

### Think Before Coding
Ne pas assumer. Si incertain sur le besoin ou l'approche, demander. Si une approche plus simple existe, la proposer avant de coder.

Pour toute tâche non triviale (3+ étapes ou décision d'architecture) :
1. Écrire le plan dans `tasks/todo.md` avec des items checkables
2. Valider le plan avant d'implémenter
3. Cocher les items au fur et à mesure
4. Ajouter une section "résultat" à la fin
5. Si ça déraille : STOP et re-planifier avant de continuer

### Simplicity First
Pas de features non demandées. Pas d'abstractions pour du code à usage unique. Si 200 lignes peuvent être 50, simplifier. Pour tout changement non trivial, se demander : "y a-t-il une solution plus élégante ?"

### Surgical Changes
Toucher uniquement ce qui est nécessaire. Ne pas "améliorer" le code adjacent. Chaque ligne modifiée doit tracer directement vers la demande.

### Goal-Driven Execution
Définir les critères de succès et boucler jusqu'à vérification. Écrire le test d'abord, puis le faire passer. Face à un bug : le corriger directement en s'appuyant sur les logs et erreurs.

### Self-Improvement Loop
Après toute correction utilisateur :
1. Mettre à jour `tasks/lessons.md` avec le pattern d'erreur
2. Relire `tasks/lessons.md` au début de chaque session

## Stratégie de tests

| Niveau | Quoi | Comment |
|--------|------|---------|
| **Unit** | Logique métier (rate limiter, parsing, DB CRUD, models) | Mocks, rapide, majorité de la couverture |
| **Integration** | Commandes CLI complètes (auth → sync → DB) | Faux serveur HTTP local simulant l'API Strava |
| **Smoke test** | Vérification manuelle contre la vraie API | Non automatisé, lancé par l'utilisateur |

Pas de tests E2E automatisés contre la vraie API Strava (consomme du rate limit, flaky, lent).

Couverture cible : 70% minimum pour le code nouveau, 90%+ pour les chemins critiques (auth, sync, rate limiting).

### Definition of Done

Une tâche est terminée quand :
1. `make validate` passe (lint + typecheck + tests)
2. Test manuel du comportement attendu (CLI, données en DB)
3. Si un problème est trouvé, fix et retour à l'étape 1

## Dépendances

Ne jamais ajouter une dépendance sans validation explicite. Avant d'installer un package :
1. Vérifier si la fonctionnalité existe déjà dans la stdlib Python
2. Préférer la stdlib quand c'est possible
3. Demander validation avant `uv add`

## Git

### Commits
Format : `type: Description en français`

```
feat: Ajouter l'import complet des activités Strava
fix: Corriger le refresh token expiré
refactor: Simplifier la gestion du rate limiting
test: Ajouter les tests du client API
```

Types : `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `style`, `data`

### Branches
```
feat/description-courte
fix/description-courte
```

### Pre-commit
`gitleaks` (scan de secrets) et `make validate` tournent sur chaque commit. Ne jamais bypass avec `--no-verify`.

## CI — GitHub Actions

Lint + typecheck + tests + build sur chaque push et PR.

## Maintien des documents projet

### `specs.md` — source de vérité technique

Ce fichier reflète l'état actuel du projet, pas un état cible figé. Le mettre à jour à chaque changement significatif :

- **Nouveau choix technique** (dépendance ajoutée, pattern adopté) → mettre à jour la section concernée
- **Modèle de données modifié** (nouvelle table, colonne ajoutée/supprimée) → mettre à jour la section 4
- **Comportement de sync modifié** (nouveau endpoint, changement de logique) → mettre à jour la section 5
- **Lot terminé** → déplacer de "Vision future" vers la section principale si applicable
- **Décision d'architecture prise** qui contredit les specs → corriger les specs, pas l'inverse

Marquer les sections en cours d'implémentation avec `<!-- EN COURS: lot X -->` et les sections spéculatives (lots futurs) avec `> À spécifier en détail [...]`.

### `backlog.md` — avancement

Cocher les items au fur et à mesure (`- [x]`). Ne pas supprimer les items terminés.
