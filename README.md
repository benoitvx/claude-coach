# 🏃 Claude Coach

> Ton coach sportif personnel, propulsé par l'IA et branché sur tes **vraies** données Strava.
> **100 % local. Gratuit. Sans abonnement. C'est toi qui gardes la data et la décision.**

Claude Coach transforme ton historique Strava en un coaching qui raisonne : il analyse ta
charge, bâtit des plans périodisés vers tes objectifs, et **pousse tes séances structurées
directement sur ta montre, ton compteur vélo ou Zwift** — automatiquement. Tu lui parles en
langage naturel depuis Claude Code, il fait le reste.

```
Strava ─► SQLite locale ─► coach IA (Claude Code) ─► plan + séances ─► intervals.icu ─► montre / GPS / Zwift
```

Pas de cloud tiers, pas d'algo opaque, pas de données qui t'échappent. Juste ton coach, tes
chiffres, et des règles d'entraînement que tu peux lire et amender.

---

## ✨ Ce que Claude Coach fait pour toi

### 📊 Il comprend vraiment ta charge
- **ACWR** (Acute:Chronic Workload Ratio) — charge 7 j vs moyenne 28 j, avec zones safe /
  attention / risque blessure. Tu sais si tu montes trop vite **avant** de te blesser.
- **Polarisation 80/20** — il repère les semaines passées dans le « ventre mou » Z3 : de la
  fatigue sans le stimulus qui fait progresser.
- **Temps en zone** — il lit ton stream cardio **seconde par seconde** et te dit si ton
  footing « facile » l'était vraiment, ou si ta sortie longue a dérivé.

### 🎯 Il planifie vers tes objectifs
- **Périodisation par bloc** : base → build → peak → taper, calé sur ta date de course.
- **Spécificité par discipline** : course, trail, vélo, natation, swim&run, triathlon —
  chacune avec ses séances types et ses calibrations.
- **Calibré sur tes métriques** : FTP, VMA, FCmax, FC repos — historisées, pas figées.

### ⌚ Il envoie tes séances sur ton appareil — sans rien re-saisir
- **Une seule commande, tous les sports.** Le coach prescrit des séances structurées
  (intervalles, allures, zones de FC, blocs de puissance) et les pousse via **intervals.icu**
  (gratuit), qui les relaie vers **ta montre, ton compteur GPS et Zwift** selon le sport.
- **Course / natation** → guide sur ta montre (allure, FC, distance).
- **Vélo outdoor** → ton compteur / ta montre (FC, puissance, distance, durée).
- **Vélo home-trainer** → workout structuré dans **Zwift** (puissance % FTP).
- Tu te lèves, tu synchronises, la séance du jour est là. **Plus jamais de re-saisie manuelle.**

### 🧠 Il s'adapte à toi
- **Le ressenti d'abord** : avant chaque débrief il demande tes sensations (RPE, jambes,
  douleurs, sommeil) et les croise avec la data — parce que la FC seule ment sur la fatigue.
- **Data quality check** : si ta VMA/FTP semble obsolète par rapport à ton volume réel, il te
  propose un test (Cooper 6', FTP 20 min) pour recaler tes zones.
- **Semantic check** : si une séance renfo planifiée a été remplacée par un run, il le détecte
  et te demande comment trancher — au lieu de fausser ton suivi.

### 🔒 Il respecte ta donnée
- **100 % local** : tout vit dans une base SQLite sur ta machine. Rien n'est envoyé ailleurs.
- **Garde-fou** : toute écriture qui relève d'une décision est **proposée** et jamais
  auto-exécutée. Tu valides, tu gardes la main.

---

## 👀 En action

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
  [le coach propose le plan + les séances à valider]
```

Une fois le plan validé, le coach pousse chaque séance sur tes appareils :

```bash
uv run claude-coach plan session push-intervals 14    # → ta montre / GPS / Zwift
```

---

## 🚀 Démarrer en 4 commandes

```bash
git clone https://github.com/benoitvx/claude-coach.git && cd claude-coach
make install                                  # venv + dépendances (uv)
uv run claude-coach auth                      # connexion Strava (OAuth2, une fois)
uv run claude-coach sync --full               # import de ton historique
```

Puis, depuis Claude Code (CLI ou IDE) ouvert dans le repo, parle à ton coach :

```
demande au coach un état des lieux de ma forme
demande au coach un plan vers mon trail d'octobre
demande au coach de débriefer ma séance de ce matin
```

**Sync auto** (macOS) : `bash scripts/install-launchd-sync.sh` programme l'import quotidien
des nouvelles activités — ton coach raisonne toujours sur des données fraîches.

**Envoi sur tes appareils** (gratuit, une fois) : crée une clé API sur intervals.icu, connectes-y
ta montre / ton compteur / Zwift, et coche « Upload planned workouts ». Le coach s'occupe du reste.

---

## 🧰 Surface CLI

Tout est piloté par le coach en langage naturel, mais la CLI `claude-coach` est aussi
utilisable directement. Toutes les commandes de lecture sortent en **JSON stable** (`--json`).

| Groupe | Commandes |
|--------|-----------|
| **Système** | `auth`, `sync [--full]`, `status` |
| **Athlète** | `athlete set/show/history` (poids, FTP, FCmax, FC repos, VMA — historisés) |
| **Activités** | `activity list/show/laps/streams/stats` (filtres date/sport, agrégats hebdo/mensuels) |
| **Objectifs** | `goal add/list/show/complete/abandon` |
| **Plans** | `plan add/list/show/complete/pause/abandon`, `plan match` (planifié ↔ réalisé) |
| **Séances** | `plan session add/list/done/skip/delete` |
| **Envoi appareils** | `plan session set-blocks`, `plan session push-intervals` (→ montre / GPS / Zwift), `intervals status` |

Les séances structurées s'écrivent dans un mini-DSL lisible — allures, FC, distances, durées,
intervalles, blocs de puissance — que le coach génère pour toi :

```bash
# Course / natation / vélo outdoor (allure, FC, distance, durée)
uv run claude-coach plan session set-blocks 14 "warmup:15min@h120-140; 6x[400m@p3:45;rest:90s]; cooldown:10min@h120"

# Vélo home-trainer (puissance % FTP → Zwift)
uv run claude-coach plan session set-blocks 14 "warmup:10m:50-65; 3x[12m@95;4m@60]; cooldown:8m:65-50"

uv run claude-coach plan session push-intervals 14    # → tes appareils, via intervals.icu
```

Détails et conventions : [`specs.md`](specs.md).

---

## 🛠️ Sous le capot

- **Python 3.12+**, **SQLite** (fichier local), **uv** (packaging + venv).
- **click** (CLI), **httpx** (Strava + intervals.icu, OAuth2 + rate limiting respectueux).
- **mypy --strict**, **ruff**, **pytest** — **321 tests**, intégration incluse (faux serveur HTTP).
- **Zéro dépendance superflue** : génération de fichiers via la stdlib, push via API REST.
- **Subagent Claude Code** pour le coach : pas de service à héberger, pas d'API à exposer, pas
  de tokens en clair côté agent. La DB locale et la CLI sont la seule interface.

### Développement

```bash
make validate          # ruff + mypy --strict + pytest
make test              # pytest seul
make format            # ruff format auto-fix
```

Pre-commit : `gitleaks` (scan de secrets) + `make validate`.

---

## 📚 Aller plus loin

- [`specs.md`](specs.md) — spec technique, modèle de données, stratégie de tests, conventions JSON.
- [`backlog.md`](backlog.md) — avancement par lot, fonctionnalités supportées.
- [`CLAUDE.md`](CLAUDE.md) — guide Claude Code, conventions du projet.

## Crédits

Construit en sessions courtes avec **Claude Code** (Claude Opus 4.x). Un cas d'usage du pattern
« subagent + CLI locale » : pas de MCP, pas de service externe, ta donnée ne quitte jamais ta machine.

## Licence

Projet personnel. Inspire-t'en librement ; demande avant de réutiliser tel quel.
