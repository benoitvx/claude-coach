# Claude Coach

> Ton coach sportif personnel, branché sur tes vraies données Strava, piloté par un subagent Claude Code. **100 % local. Tu gardes la data, tu gardes la décision.**

```
Strava ─► sync ─► SQLite locale ─► CLI (--json) ─► subagent coach ─► plan + séances ─┬─ .zwo ─► Zwift
                                        │                                            └─ Nolio ─► Suunto/Garmin
                              313 tests · mypy --strict · ruff
```

La boucle est fermée : tes données entrent par Strava, le coach raisonne, et la séance ressort
vers ton home trainer (`.zwo` Zwift, vélo) ou ta montre (API Nolio → Suunto 9, course à pied).

## Pourquoi ?

Trois constats :

- **Strava te montre la donnée, pas la décision.** Tu vois ta semaine, mais pas si tu pousses trop, pas où elle te mène, pas quoi faire demain.
- **Les apps coach sont fermées et abonnées.** Tu paies pour un algo opaque qui tourne sur des serveurs où ta data ne t'appartient plus.
- **Un LLM moderne fait mieux à la maison.** Calibré sur tes vraies métriques (FTP, VMA, FCmax), tes vraies données seconde par seconde, et des règles d'entraînement que tu peux lire et amender.

## Comment ça marche

1. **Import.** `claude-coach sync --full` télécharge ton historique Strava (activités, laps, streams seconde-par-seconde) dans une base SQLite locale. Tâche `launchd` quotidienne pour les nouvelles séances.
2. **Surface CLI typée.** Toutes les lectures sortent en JSON stable (`snake_case`, ISO 8601, `null` jamais omis) : activités, laps, streams, agrégats hebdo/mensuels, métriques athlète historisées.
3. **Subagent Claude Code.** Un agent `coach` vit dans `.claude/agents/coach.md`. Tu l'invoques depuis n'importe quelle session Claude Code dans le repo : *"demande au coach un état des lieux"*, *"…un plan vers mon trail d'octobre"*, *"…un débrief de ma séance"*. À chaque invocation il commence par un **rituel de démarrage** (sync incrémentale + briefing adhérence) — il ne raisonne jamais sur des données périmées.
4. **Garde-fou.** Toute écriture qui relève d'une décision (créer un plan, prescrire des blocs, abandonner) est proposée en bloc `bash`, jamais auto-exécutée. Seul l'appariement d'une séance réalisée à son activité Strava — un simple fait — est acté automatiquement.
5. **Sortie vers ta montre & Zwift.** Le coach prescrit des séances structurées : vélo en blocs de puissance % FTP → `.zwo` Zwift (`plan session export`) ; course à pied en allure/FC/durée/distance → poussées vers ta montre via l'API Nolio (`plan session push-nolio`), qui les synchronise en séances guidées sur ta Suunto 9 (le push API nécessite un **compte Nolio payant** — coach/premium). Plus besoin de re-saisir la séance à la main.

## Ce que le coach sait faire

- **Périodisation par bloc** : base → build → peak → taper, calibré sur ta date d'objectif.
- **Polarisé 80/20** : flagger les semaines passées dans le ventre mou Z3.
- **ACWR** (Acute:Chronic Workload Ratio) calculé spontanément (charge 7j / moyenne 28j), zones safe / attention / risque blessure.
- **Time-in-zone Z2** sur les longs : lit le stream cardio brut, calcule la distribution avec tes seuils, te dit si la séance était vraiment facile.
- **Spécificité par discipline** : run, ride/Zwift, swim, trail, swim&run, triathlon — chacune avec ses séances types et calibrations.
- **Data quality check** : si tes FTP/VMA semblent obsolètes par rapport au volume réel, il suggère un test (Cooper 6', FTP 20 min).
- **Semantic check** : si une séance renfo planifiée a été remplacée par un run, il le détecte avant le matching et te demande comment trancher.
- **Export `.zwo` Zwift** : il prescrit les blocs de puissance, tu génères le fichier et tu l'exécutes sur ton home trainer (FTP-relatif — Zwift applique ta FTP).
- **Push Nolio → Suunto** : pour la course, il prescrit les blocs (allure/FC/durée/distance) et les pousse dans Nolio via l'API (`plan session push-nolio`) ; Nolio les synchronise en séances guidées sur ta Suunto 9 (et Garmin).
- **Ressenti d'abord** : avant un débrief, il demande tes sensations (RPE, jambes, douleurs, sommeil) et les croise avec la data — la FC seule ment sur la fatigue.

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
| **Plans** | `plan add/list/show/complete/pause/abandon`, `plan match` (planifié ↔ Strava, ±1j) |
| **Séances** | `plan session add/list/done/skip/delete` |
| **Export Zwift** | `plan session set-blocks <id> "<DSL>"`, `plan session export <id>` (→ `.zwo`) |
| **Export Nolio** | `nolio auth/status`, `plan session push-nolio <id> [--dry-run]` (→ Suunto/Garmin) |

Toutes les commandes de lecture acceptent `--json`. Conventions détaillées : [`specs.md §11`](specs.md).

Les blocs d'une séance vélo s'expriment dans un mini-DSL (puissance en % de FTP) :

```bash
uv run claude-coach plan session set-blocks 14 "warmup:10m:50-65; 3x[12m@95;4m@60]; cooldown:8m:65-50"
uv run claude-coach plan session export 14        # → data/exports/<slug>.zwo + stdout
```

`warmup/cooldown:<durée>:<%début>-<%fin>` (rampe), `<durée>@<%>` (steady), `Nx[effort;récup]` (intervalles).

Les séances de **course à pied** ont leur propre mini-DSL (cibles allure/FC, durée ou distance),
poussé vers la montre via Nolio :

```bash
uv run claude-coach plan session set-blocks 14 "warmup:15min@h120-140; 6x[400m@p3:45;rest:90s]; cooldown:10min@h120"
uv run claude-coach plan session push-nolio 14    # → API Nolio → Suunto 9 (séance guidée)
```

Durée `<n>min`/`<n>s`, distance `<n>km`/`<n>m` ; cible `p<min:sec>` (allure/km), `h<bpm>` (FC),
plage possible (`p3:45-4:15`). Une fois Nolio connecté (`nolio auth`), le push est automatique
jusqu'à la montre. Config : `NOLIO_CLIENT_ID`/`NOLIO_CLIENT_SECRET`/`NOLIO_REDIRECT_URI`.

> ⚠️ **Compte Nolio payant requis pour le push.** L'écriture via l'API Nolio
> (`create/planned/training/`) est réservée aux comptes **coach ou premium** : sans
> abonnement, Nolio renvoie `403 "API access requires an active coach or premium
> subscription"`. L'OAuth et la génération de la séance fonctionnent sans abonnement —
> `push-nolio --dry-run` te donne alors le détail de la séance à recopier manuellement
> dans l'éditeur Nolio web (qui synchronise ensuite vers la montre).

## Stack

- **Python 3.12+**, **SQLite** (fichier local), **uv** (packaging + venv).
- **click** (CLI), **httpx** (HTTP Strava + Nolio, OAuth2 et rate limiting).
- **mypy --strict**, **ruff**, **pytest** (313 tests, dont integration tests avec faux serveur HTTP).
- **Export `.zwo`** via la stdlib (`xml.etree`) ; **push Nolio** via l'API REST (`httpx`) — zéro dépendance ajoutée.
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

Construit en sessions courtes avec **Claude Code** (Claude Opus 4.x). Le subagent coach est un cas d'usage du pattern "subagent + Bash CLI" — pas de MCP, pas de service externe, pas de tokens en clair côté agent. La DB locale et la CLI sont la seule interface entre le coach et tes données.

## Licence

Proprietary. Projet personnel — n'hésite pas à t'en inspirer, demande avant de réutiliser tel quel.
