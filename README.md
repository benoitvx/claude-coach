# Claude Coach

> Ton coach sportif personnel, branché sur tes vraies données Strava, piloté par un subagent Claude Code. **100 % local. Tu gardes la data, tu gardes la décision.**

```
Strava API ─► sync ─► SQLite locale ─► CLI (--json) ─► subagent coach ─► toi
                                                  ▲
                                                  └── 212 tests, mypy --strict, ruff
```

## Pourquoi ?

Trois constats :

- **Strava te montre la donnée, pas la décision.** Tu vois ta semaine, mais pas si tu pousses trop, pas où elle te mène, pas quoi faire demain.
- **Les apps coach sont fermées et abonnées.** Tu paies pour un algo opaque qui tourne sur des serveurs où ta data ne t'appartient plus.
- **Un LLM moderne fait mieux à la maison.** Calibré sur tes vraies métriques (FTP, VMA, FCmax), tes vraies données seconde par seconde, et des règles d'entraînement que tu peux lire et amender.

## Comment ça marche

1. **Import.** `claude-coach sync --full` télécharge ton historique Strava (activités, laps, streams seconde-par-seconde) dans une base SQLite locale. Tâche `launchd` quotidienne pour les nouvelles séances.
2. **Surface CLI typée.** Toutes les lectures sortent en JSON stable (`snake_case`, ISO 8601, `null` jamais omis) : activités, laps, streams, agrégats hebdo/mensuels, métriques athlète historisées.
3. **Subagent Claude Code.** Un agent `coach` vit dans `.claude/agents/coach.md`. Tu l'invoques depuis n'importe quelle session Claude Code dans le repo : *"demande au coach un état des lieux"*, *"…un plan vers mon trail d'octobre"*, *"…un débrief de ma séance"*. Il lit la DB via Bash + CLI, raisonne, te répond.
4. **Garde-fou.** Toute écriture (créer un plan, marquer une séance, etc.) est proposée en bloc `bash`, jamais auto-exécutée. Tu valides, tu joues.

## Ce que le coach sait faire

- **Périodisation par bloc** : base → build → peak → taper, calibré sur ta date d'objectif.
- **Polarisé 80/20** : flagger les semaines passées dans le ventre mou Z3.
- **ACWR** (Acute:Chronic Workload Ratio) calculé spontanément (charge 7j / moyenne 28j), zones safe / attention / risque blessure.
- **Time-in-zone Z2** sur les longs : lit le stream cardio brut, calcule la distribution avec tes seuils, te dit si la séance était vraiment facile.
- **Spécificité par discipline** : run, ride/Zwift, swim, trail, swim&run, triathlon — chacune avec ses séances types et calibrations.
- **Data quality check** : si tes FTP/VMA semblent obsolètes par rapport au volume réel, il suggère un test (Cooper 6', FTP 20 min).
- **Semantic check** : si une séance renfo planifiée a été remplacée par un run, il le détecte avant le matching et te demande comment trancher.

## Aperçu

```
> demande au coach un état des lieux

Diagnostic en bref

- Charge : ACWR 1,38 → zone d'attention. La semaine dernière (242 min)
  a été un saut trop brutal vs moyenne 28j (175 min).
- Polarisation : 0 séance dure, 1 vraiment facile, 10 en Z3 modéré.
  Tu t'entraînes dans le ventre mou — fatigue sans stimulus.
- Disciplines : 69 % run, 18 % vélo, 0 % nage sur 6 sem. La nage est
  ta priorité absolue vers ton objectif principal.

Drapeau data quality
  Ta VMA enregistrée (12 km/h) semble incohérente avec ton volume :
  tu cours régulièrement à 5'30/km en endurance (≈ 10,9 km/h moyen Z2,
  → suggère VMA ≥ 15). Un test 6' ou Cooper recalibrerait les zones.

Reco prochaine semaine

Bloc transition, volume stable, introduction polarisation + nage.

[bloc bash de plan_add / plan_session_add à valider]
```

## Quickstart

```bash
git clone https://github.com/benoitvx/claude-coach.git && cd claude-coach
make install                                  # venv + dépendances (uv)
uv run claude-coach auth                      # OAuth2 Strava (une fois)
uv run claude-coach sync --full               # import historique (~2 jours, rate-limit Strava)
uv run claude-coach status                    # vérif DB + tokens
```

Sync quotidienne automatique sur macOS :

```bash
bash scripts/install-launchd-sync.sh          # 02:05 par défaut, override SYNC_HOUR/MINUTE
```

Puis depuis Claude Code (CLI ou IDE) dans le repo :

```
demande au coach un état des lieux
```

## Surface CLI (extrait)

| Groupe | Commandes |
|--------|-----------|
| **Système** | `auth`, `sync [--full]`, `status` |
| **Athlète** | `athlete set/show/history` (poids, FTP, FCmax, FCrepos, VMA, historisés) |
| **Activités** | `activity list/show/laps/streams/stats` (filtres date/sport/famille, agrégats) |
| **Objectifs** | `goal add/list/show/complete/abandon` |
| **Plans** | `plan add/list/show/complete/pause`, `plan match` (planifié ↔ Strava, ±1j) |
| **Séances** | `plan session add/list/done/skip` |

Toutes les commandes de lecture acceptent `--json`. Conventions détaillées : [`specs.md §11`](specs.md).

## Stack

- **Python 3.12+**, **SQLite** (fichier local), **uv** (packaging + venv).
- **click** (CLI), **httpx** (HTTP Strava avec rate limiter sur les headers `X-ReadRateLimit-Usage`).
- **mypy --strict**, **ruff**, **pytest** (212 tests, dont integration tests avec faux serveur HTTP).
- **Claude Code subagent** pour le coach — pas de service Python autonome, pas d'API à exposer.

## Développement

```bash
make validate          # ruff + mypy --strict + pytest
make test              # pytest seul
make test-one F=tests/test_db.py
make format            # ruff format auto-fix
```

Pre-commit : `gitleaks` + `make validate`.

## Aller plus loin

- [`specs.md`](specs.md) — spec technique, modèle de données, stratégie de tests, conventions JSON.
- [`backlog.md`](backlog.md) — avancement par lot, objectifs sportifs supportés.
- [`CLAUDE.md`](CLAUDE.md) — guide Claude Code, conventions du projet.
- [`tasks/lessons.md`](tasks/lessons.md) — leçons apprises (rate-limit Strava, design subagent, etc.).

## Crédits & inspiration

Construit en sessions courtes avec **Claude Code** (Claude Opus 4.7). Le subagent coach est un cas d'usage du pattern "subagent + Bash CLI" — pas de MCP, pas de service externe, pas de tokens en clair côté agent. La DB locale et la CLI sont la seule interface entre le coach et tes données.

## Licence

Proprietary. Projet personnel — n'hésite pas à t'en inspirer, demande avant de réutiliser tel quel.
