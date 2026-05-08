# Claude Coach

Coach sportif personnel piloté par Claude. Synchronise l'historique d'activités
depuis l'API Strava dans une base SQLite locale, expose une CLI structurée
(sortie `--json`), et héberge un subagent Claude Code (`coach`) qui analyse
la charge, propose des plans périodisés et compare planifié vs réalisé.

Brique de données : **Strava** (Suunto / Garmin / Zwift agrégés). Cible :
**Swim&Run sept 2026**, **Trail 50k oct 2026**, **Ironman 70.3 printemps 2027**.

## Quickstart

```bash
make install                                  # venv + dépendances
uv run claude-coach auth                      # OAuth2 Strava (une fois)
uv run claude-coach sync --full               # import historique (~2 jours, rate-limit)
uv run claude-coach status                    # état DB + tokens + dernière sync
```

Une fois l'historique importé, sync incrémentale après chaque séance :

```bash
uv run claude-coach sync                      # ne re-télécharge rien
```

Sur macOS, planification automatique tous les jours :

```bash
bash scripts/install-launchd-sync.sh          # 02:05 par défaut (override SYNC_HOUR/MINUTE)
```

## Surface CLI

| Groupe | Commandes |
|--------|-----------|
| Système | `auth`, `sync [--full]`, `status` |
| Athlète | `athlete set/show/history` (poids, FTP, FCmax, FCrepos, VMA) |
| Activités | `activity list/show/stats` (filtres date/sport/famille, agrégats sport/week/month) |
| Objectifs | `goal add/list/show/complete` |
| Plans | `plan add/list/show`, `plan match` (planifié ↔ Strava) |
| Séances | `plan session add/list/done` |

Toutes les commandes de **lecture** acceptent `--json` : sortie stable
(snake_case, ISO 8601, `null` jamais omis). Conventions détaillées dans
[`specs.md`](specs.md) §11.

## Subagent coach

Un subagent Claude Code vit dans [`.claude/agents/coach.md`](.claude/agents/coach.md)
et joue le rôle de coach personnel. Depuis une session Claude Code dans le
repo :

```
demande au coach un état des lieux de ma forme actuelle
demande au coach de me proposer le premier bloc Swim&Run
demande au coach de débriefer ma séance de ce matin
```

Le coach lit la DB via la CLI, applique périodisation polarisée 80/20,
charge progressive et spécificité par discipline. Il **propose** les
commandes d'écriture en bloc bash et **demande confirmation** avant
exécution — pas d'auto-application silencieuse.

## Développement

```bash
make validate          # ruff + mypy --strict + pytest
make test              # pytest seul
make test-one F=tests/test_db.py
make format            # ruff format auto-fix
```

Stack : Python 3.12+, SQLite, `uv`, `click`, `httpx`, `pytest`, `mypy --strict`,
`ruff`. Pre-commit : `gitleaks` + `make validate`.

Détails d'architecture, modèle de données et stratégie de tests :
[`specs.md`](specs.md).
Avancement et lots livrés : [`backlog.md`](backlog.md).
Guide Claude Code (conventions, principes) : [`CLAUDE.md`](CLAUDE.md).

## Licence

Proprietary. Projet personnel.
