# Tâche en cours

Aucune tâche en cours — **phase dogfood**.

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
