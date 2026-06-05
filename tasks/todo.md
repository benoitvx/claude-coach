# Tâche en cours

## Lot 5d.3 — Statut `abandoned` pour les plans

Symétriser le pattern `goal abandon` côté `plan` : aujourd'hui un plan
abandonné est forcé en `completed`, ce qui fausse l'historique. Bug remonté
par le coach pendant le dogfood (plan S22 marqué `completed` faute de mieux).

### Plan

**Code**
- [x] `src/claude_coach/db.py:809` — ajouter `"abandoned"` à `PLAN_STATUSES`
- [x] `src/claude_coach/cli.py` — ajouter commande `plan abandon <ID>` après `plan_pause` (copie pattern `plan_complete` + texte d'aide aligné sur `goal_abandon`)

**Docs**
- [x] `specs.md:366` — `status` row de `training_plans` : `active / completed / paused / abandoned`
- [x] `CLAUDE.md` — section CLI : ajouter `claude-coach plan abandon <ID>`
- [x] `.claude/agents/coach.md` — section "Écriture" : ajouter `plan abandon` + précision quand l'utiliser
- [x] `backlog.md` — créer une entrée `5d.3 plan abandon` cochée

**Tests**
- [x] `tests/test_cli_coach.py` — ajouter `test_plan_abandon_updates_status`
- [x] `tests/test_cli_coach.py` — ajouter `test_plan_abandon_unknown_errors`

**Validation**
- [x] `make validate` passe
- [x] Test manuel CLI : add → abandon → list --status abandoned --json
- [x] **Corriger plan S22 réel** : `plan list --status completed --json` → identifier ID → `plan abandon <ID>`
- [x] Commit

### Résultat

- `PLAN_STATUSES` étendu à `("active", "completed", "paused", "abandoned")`.
- Nouvelle commande `claude-coach plan abandon <ID>` (cli.py, après `plan pause`).
- 2 tests ajoutés (`test_plan_abandon_updates_status`, `test_plan_abandon_unknown_errors`).
- Docs synchronisées : `specs.md`, `CLAUDE.md`, `coach.md`, `backlog.md`.
- `make validate` ✅ — 214 tests verts (+2).
- **Fix appliqué** : plan #2 "S22 - Reprise post-op 25-31 mai" repassé de `completed` → `abandoned`.

---

## Contexte historique conservé

**Phase dogfood ouverte (2026-05-11).**

## État du projet (2026-05-11)

Lots 0 à 5 livrés et poussés sur `origin/main`. 212 tests verts.

- **Lot 5d clos** avec subagent `.claude/agents/coach.md` et 4 patterns d'analyse
  (laps pour intervalles, streams pour long Z2, ACWR, data quality check,
  semantic check planifié↔réalisé).
- **Surface CLI complète** côté lectures (`--json` partout) + transitions de
  statut (`goal abandon`, `plan complete/pause`, `plan session skip`).

## Validation en cours : dogfood W20 (11-17 mai)

Le coach a planifié 6 séances W20. Chaque jour, après sync incrémentale 10:00,
l'utilisateur lance `plan match` et demande un débrief au coach. Patterns à
observer pour itérer ensuite :

- ACWR calculé spontanément sur chaque "état des lieux" ?
- Workflow laps déclenché sur les séances `intervals` (lun, dim) ?
- Workflow stream Z2 déclenché sur les séances `long`/`endurance` (mer Zwift,
  jeu run easy, ven long Mervent) ?
- Semantic check actif sur sam (renfo planifié) si substitution ?
- Data quality flag VMA / FTP encore visible ?

## Prochaines pistes (à arbitrer après dogfood)

1. **Lot 6.2 — Export Zwift `.zwo`** : générer fichiers XML pour les séances
   vélo Z2 planifiées (drag-and-drop dans Zwift Workouts/Custom).
2. **`activity time-in-zone`** dédié : si le pattern Python inline du coach
   pour les longs Z2 devient répétitif (vu sur 2-3 débriefs).
3. **Lot 5d.x** : autres itérations selon angles morts révélés par dogfood.

Les lessons de cette phase remontent dans `tasks/lessons.md` au fil de l'eau.

<!--
Format d'une tâche :

## <titre>

### Plan
- [ ] étape 1
- [ ] étape 2

### Résultat
(à remplir une fois terminée)
-->
