# Tâche : intervals.icu = hub unique d'envoi des séances (vélo + course)

Plan complet : `~/.claude/plans/encapsulated-cuddling-haven.md`.

## Contexte
intervals.icu sait fan-outer les séances planifiées vers Suunto + Garmin Connect + Zwift
(config UI web). On en fait le point d'entrée unique : `push-intervals` pour TOUS les sports.
- Run/TrailRun/Swim → Suunto (FC %FCmax) — inchangé
- Vélo outdoor (Ride/GravelRide/MountainBikeRide) → Garmin (FC/distance/durée, pas de puissance)
- Vélo HT (VirtualRide) → Zwift (puissance %FTP)
- `.zwo` gardé en fallback (VirtualRide seul) ; **Nolio supprimé**.

## Étapes
- [x] 1. `coach.py` : `INDOOR_POWER_SPORTS` + `is_indoor_power_ride`
- [x] 2. `cli.py` `_blocks_json_or_raise` : router sur `is_indoor_power_ride` + aide `--blocks`/`set-blocks`
- [x] 3. `cli.py` garde `export` `.zwo` : `is_indoor_power_ride` (VirtualRide seul)
- [x] 4. `intervals.py` : étendre `INTERVALS_SPORT_TYPES` + docstring
- [x] 5. `intervals.py` : `workout_doc_from_blocks` (puissance %FTP, constante `POWER_FTP_UNITS`)
- [x] 6. `cli.py` `push-intervals` : retirer rejet vélo + brancher VirtualRide / autres
- [x] 7. Supprimer Nolio (fichiers, commandes, modèles, imports, tests)
- [x] 8. Tests (intervals, coach, cli) + retirer tests nolio
- [x] 9. Docs : coach.md, CLAUDE.md, README.md, specs.md, backlog.md
- [x] 10. `make validate` + vérif manuelle dry-run

## Risque #1 (à lever au push live)
Chaîne d'unité puissance `workout_doc` (`%ftp` inféré) → isolée dans `POWER_FTP_UNITS`.

## Résultat

**Livré.** `make validate` vert : **321 tests**, ruff + mypy --strict clean. Zéro dépendance.

`push-intervals` est désormais le **hub unique** pour tous les sports : intervals.icu
fan-oute par sport (course/swim→Suunto, vélo outdoor→Garmin, VirtualRide→Zwift). Routage
de DSL par `is_indoor_power_ride` (`coach.py`) : VirtualRide→`zwo.py` (%FTP) via le nouveau
`workout_doc_from_blocks` ; tout le reste→`workout.py` (FC/allure/distance). Nolio supprimé.
`.zwo` export conservé en fallback offline VirtualRide.

Vérif manuelle dry-run OK : VirtualRide→type `VirtualRide` + power `%ftp` (rampes/reps) ;
Ride outdoor→type `Ride` + distance/durée ; `.zwo` rejette le Ride outdoor.

**Reste (smoke test live, lot 11.7-11.8, hors code)** : lier Garmin+Zwift sur intervals.icu,
confirmer l'unité `%ftp` au 1er push réel (sinon ajuster `POWER_FTP_UNITS`), vérifier la
descente Zwift/Garmin et la FC `%hr` sur Garmin.
