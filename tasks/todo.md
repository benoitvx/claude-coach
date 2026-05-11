# Tâche en cours

## Lot 5c.4 / 5d.1 — Commande `activity laps` + intégration coach

Plan complet : `~/.claude/plans/keen-seeking-marshmallow.md`.

Origine : le débrief de la séance d'intervalles du 11 mai a révélé que le
coach n'a pas accès aux laps (exclus volontairement de `activity show` en
5c.2). Sans ça, il sous-exploite les séances `intervals`/`threshold`.

### Plan

- [x] `src/claude_coach/db.py` : `_row_to_lap` + `list_laps(conn, activity_id)`
- [x] `src/claude_coach/serializers.py` : `lap_to_dict`
- [x] `src/claude_coach/cli.py` : `activity laps <ID> [--json]` (texte tableau + JSON array)
- [x] `.claude/agents/coach.md` : ajouter la commande à la section CLI + étape "lire laps si intervals/threshold" dans le workflow post-séance
- [x] `tests/test_db.py` : 3 tests `list_laps` (tri ASC, pas de laps, activité inconnue)
- [x] `tests/test_cli_activity.py` : 4 tests `activity laps` (human, JSON, vide, ID inconnu)
- [x] `tests/test_subagent_coach.py` : marker `"activity laps"` dans les expected
- [x] `CLAUDE.md` + `specs.md` §11 : doc
- [x] `make validate` puis commit + push

### Hors scope

- Streams (FC seconde par seconde) — pas nécessaire pour débriefs d'intervalles.
- `activity zones` (distribution FC/puissance) — à ouvrir si le coach le demande.
- Pagination des laps — toujours < 50 par activité.
- Augmenter `activity show` avec les laps — décision préservée (compactness).

### Résultat

Livré en un commit. Smoke sur la vraie DB (activité 18461924018) :
- 15 laps Suunto bien exposés (1 éch + 6 vif + 6 récup + 1 retour + 1 reste)
- FC max sur blocs vifs : 141 → 168 sur 6 répétitions (visible dérive)
- Allure vif 4'28-4'49/km, récup 6'00-7'00/km

201 tests verts (194 → 201, +7 tests). Le coach peut désormais débriefer
les séances `intervals`/`threshold` avec les vraies données par bloc.
