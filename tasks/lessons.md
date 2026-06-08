# Leçons apprises

_Cumulatif des patterns d'erreur rencontrés. À relire au début de chaque session._

## 2026-05-07 — Strava `/activities/{id}/zones` : 402 pour comptes non-Summit
**Contexte** : Premier smoke test de `sync --full --limit 5`.
**Erreur** : Crash `httpx.HTTPStatusError: 402 Payment Required` sur `/zones`.
**Correction** : Élargir la liste des codes "ressource indisponible" dans `client.get_zones`
de `(403, 404)` à `(402, 403, 404)`.
**Pattern à retenir** : ne pas deviner les status d'API à partir de la sémantique HTTP.
402 est rarement utilisé mais Strava s'en sert pour les fonctionnalités payantes Summit.
Quand on traite un endpoint optionnel (Summit-only ici), tester d'abord avec un compte
réel ou consulter explicitement la doc Strava au lieu de lister 403/404 par habitude.


## 2026-05-07 — Strava `/activities/{id}/streams` : 404 pour activités manuelles
**Contexte** : `sync --full` plante après ~85 activités sur une activité manuelle
(saisie sans données capteur, type "Étirements").
**Erreur** : Crash `httpx.HTTPStatusError: 404 Not Found` sur `/streams`.
**Correction** :
1. `client.get_streams` retourne `{}` sur 404 (mêmes manières que `get_zones`).
2. `has_complete_activity` ne vérifie plus que l'existence dans `activities` (la transaction
   unique de `insert_full_activity` garantit l'atomicité — pas besoin de vérifier streams/laps).
**Pattern à retenir** : si un check de "complétude" exige des sous-ressources optionnelles,
il forcera des re-fetchs perpétuels pour les activités qui n'en ont pas. Préférer un
critère minimal (existence) quand l'insertion est transactionnelle.


## 2026-05-11 — Subagent coach : sous-exploitation des données par défaut

**Contexte** : 1ʳᵉ séance d'intervalles (6×30") matchée lundi 11 mai. Le coach
a fait un débrief en regardant seulement `activity show --json`, et a halluciné
"pas de laps en DB, la montre n'a pas segmenté" alors que `activity_laps`
contenait 15 lignes parfaitement alignées sur les blocs vifs.

**Erreur** : `activity show --json` exclut volontairement les laps et streams
(décision 5c.2 : compactness). Le subagent n'avait aucune commande pour les
récupérer → il a inféré "absent" depuis l'absence de champ.

**Correction** : nouveau lot 5c.4 (`activity laps <ID>`) puis 5c.5 (`activity
streams <ID>`), avec mise à jour de `coach.md` pour les déclencher dans le
workflow Post-séance selon `session_type`.

**Pattern à retenir** : pour un subagent qui interroge la DB via CLI, **chaque
décision "exclus volontairement" côté sérialiseur est un trou cognitif** tant
qu'aucune commande dédiée n'expose la donnée séparément. Avant de cacher
quelque chose pour rester compact, prévoir la commande "détail" en regard, ou
au moins documenter le trou dans le prompt du subagent.


## 2026-05-11 — Mise à jour de prompt sans CLI correspondante

**Contexte** : Lot 5d.2 ajoute un "semantic check" dans `coach.md` qui dit à
l'agent : *"si mismatch, propose à l'athlète de passer la session en `skipped`
puis créer une session ad-hoc"*. Mais la CLI ne couvrait pas l'écriture du
statut `skipped` — seul `plan session done` existait. Le workflow était
silencieusement cassé.

**Erreur** : le prompt instruisait une action que la surface outil ne
permettait pas. Découvert par observation utilisateur (« il manque `goal
abandon` »).

**Correction** : Lot 5c.6 — ajout des transitions manquantes (`goal abandon`,
`plan complete`, `plan pause`, `plan session skip`) en parallèle de leurs
homologues `complete` / `done` existants.

**Pattern à retenir** : **quand on étend un prompt agent pour instruire une
action downstream (Bash, CLI, MCP), vérifier que la surface outil supporte
l'action**. Sinon le prompt est aspirational, pas opérationnel. Règle pratique :
toute mention d'un nouveau verbe (`skip`, `abandon`, `reopen`) dans `coach.md`
exige soit la commande, soit une note explicite "indisponible pour l'instant".


## Automatisation : sync planifiée (macOS)

Préférer **launchd** plutôt que cron : un Mac qui dort à l'heure prévue rate
le cron sans rattrapage, alors qu'avec launchd on peut au moins programmer
à une heure où la machine est probablement éveillée.

**Installation one-shot** (par défaut : 02:05 chaque jour, quota Strava frais à 02:00 Paris) :

```bash
bash scripts/install-launchd-sync.sh
```

Override de l'heure via env vars :
```bash
SYNC_HOUR=12 SYNC_MINUTE=30 bash scripts/install-launchd-sync.sh
```

Le script auto-détecte le chemin de `uv`, écrit `~/Library/LaunchAgents/com.claude-coach.sync.plist`
et le charge via `launchctl`. Il est idempotent : relancer remplace l'agent
existant. Logs dans `~/Library/Logs/claude-coach/sync.{out,err}.log`.

Tip : pendant l'import historique initial (le Mac peut être laissé allumé la
nuit), 02:05 est idéal. Une fois l'historique fini, basculer vers une heure
de jour plus tolérante à un Mac qui dort la nuit.

**État actuel** (mis à jour 2026-05-08) : import historique terminé
(357 activités sur 2 ans, status `success`), launchd basculé sur **10:00
heure locale Paris** :

```bash
SYNC_HOUR=10 SYNC_MINUTE=0 bash scripts/install-launchd-sync.sh
```

Note : `StartCalendarInterval` de launchd est en heure locale système, pas UTC.
Le créneau s'adapte automatiquement été/hiver.

Pour tester sans attendre :
```bash
launchctl start com.claude-coach.sync
```

Désinstallation :
```bash
launchctl unload ~/Library/LaunchAgents/com.claude-coach.sync.plist
rm ~/Library/LaunchAgents/com.claude-coach.sync.plist
```

**Note** : le quota lecture Strava reset à 00:00 UTC = 02:00 Paris. Une exécution
à 12:30 garantit que le Mac est éveillé tout en disposant du quota frais. Tant
que l'import historique n'est pas fini, le script utilise `sync --full` (skip
les activités déjà complètes via `has_complete_activity` → coût marginal).
Une fois historique complet, basculer vers `sync` (incrémentale, plus économe)
en éditant la plist.

Sur Linux : utiliser cron classique ou systemd timer (pas couvert ici, projet
ciblé macOS).

<!--
Format :

## <date> — <titre court>
**Contexte** : ce qui a déclenché l'erreur
**Erreur** : ce qui a mal tourné
**Correction** : la bonne approche
**Pattern à retenir** : règle générale à appliquer la prochaine fois
-->

## 2026-06-06 — Coach : sync + ressenti avant débrief
**Contexte** : test matinal. L'athlète demande "analyse ma dernière course et compare-la au plan". Le coach a débriefé une course du 11 mai alors que la vraie dernière séance datait de la veille (5 juin), non encore synchronisée (launchd 10:00 passé avant la sortie). Il a aussi débriefé sans demander le ressenti.
**Erreur** : (1) règle "ne lance jamais sync" trop stricte → le coach analyse une activité périmée. La sync launchd 10:00 ne couvre pas les séances faites après 10:00 le jour même. (2) Débrief 100 % data, sans le ressenti qui distingue "FC haute mais facile" de "FC normale mais jambes lourdes".
**Correction** : `.claude/agents/coach.md` — (1) le rituel de démarrage lance désormais `sync` **incrémentale** systématiquement (jamais `sync --full`) pour garantir la vraie dernière séance. (2) Workflow Post-séance : étape 0 = demander le ressenti (RPE, jambes, souffle, douleurs, sommeil) et **attendre la réponse** avant d'analyser.
**Pattern à retenir** : un coach qui analyse doit d'abord garantir la fraîcheur de ses données (sync légère systématique) et recueillir le subjectif avant l'objectif — la donnée seule ment sur la fatigue.

## 2026-06-06 — Coach : acter une séance faite ne se demande pas
**Contexte** : la séance du 5 juin était réalisée et apparieable (clean match en dry-run), mais le coach ne l'avait pas notée dans le plan — il s'est contenté de proposer `plan match` et d'attendre le feu vert. L'athlète : "ça devrait être un comportement par défaut — la séance est faite, donc je note dans le plan".
**Erreur** : la règle d'écriture du coach traitait *toutes* les écritures pareil (confirmation obligatoire). Or `plan match` n'est pas une décision : c'est acter un fait, réversible et idempotent (il met `status=done` + lie l'activité). La confirmation systématique créait une friction inutile.
**Correction** : `coach.md` + `CLAUDE.md` — carve-out : `plan match` propre (date ±1 j, même famille, semantic check OK) s'applique **tout seul** au démarrage et en Post-séance, puis est signalé. Tout le reste (créer/modifier plan, skip, abandon, athlete set) reste sous confirmation. Exception à l'exception : mismatch/substitution → on demande.
**Pattern à retenir** : distinguer write *factuel réversible* (à appliquer par défaut) de write *décisionnel* (à confirmer). Ne pas mettre une barrière de confirmation sur l'enregistrement d'un fait déjà accompli.

## 2026-06-08 — Venv desync : pre-commit "disparaissait" sans cesse
**Contexte** : à chaque commit, `pre-commit` introuvable dans le venv → commit bloqué. Corrigé plusieurs fois à la main par `uv sync --extra dev`, mais le problème revenait.
**Erreur** : les outils de dev (ruff, mypy, pytest, pre-commit) étaient en `[project.optional-dependencies] dev` = un **extra**. Les extras ne sont jamais installés par défaut. Or `uv run claude-coach ...` (lancé en permanence) re-synchronise le venv sur le set par défaut (sans l'extra dev) et **prune** donc les outils de dev à chaque appel.
**Correction** : migrer vers `[dependency-groups] dev` (PEP 735) + `[tool.uv] default-groups = ["dev"]`. uv synchronise le groupe `dev` par défaut, y compris sur `uv run` → plus de pruning. Makefile et CI repassés de `uv sync --extra dev` à `uv sync`. Vérifié : un `uv run` nu ne supprime plus `pre-commit`.
**Pattern à retenir** : pour des outils de dev qui doivent rester présents dans un projet uv, utiliser un **dependency-group** (`[dependency-groups]`), pas un **extra** (`[project.optional-dependencies]`). L'extra est pour des features optionnelles destinées aux consommateurs du package, pas pour l'outillage local que `uv run` doit préserver.
