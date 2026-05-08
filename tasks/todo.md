# Tâche en cours

## Lot 5c — surface CLI orientée agent coach

Plan complet : `~/.claude/plans/keen-seeking-marshmallow.md`.

### Plan

**5c.1 — Helpers DB de lecture/agrégation**
- [x] Ajouter dataclass `ActivityBucket` dans `models.py`
- [x] Ajouter `list_activities(conn, *, since, until, sport_types, limit)` dans `db.py`
- [x] Ajouter `aggregate_activities(conn, *, since, until, sport_types, group_by)` dans `db.py`
- [x] Étendre `tests/conftest.py` avec une fixture `seed_activities`
- [x] Tests dans `tests/test_db.py` (filtres date/sport, agrégation sport/week/month, base vide)
- [x] `make validate` puis commit `feat: Helpers DB list/aggregate activités (Lot 5c.1)`

**5c.2 — Commandes `strava-connect activity *`**
- [x] Nouveau groupe `activity` dans `cli.py` : `list`, `show`, `stats`
- [x] Flags texte + `--json` (sortie JSON stable, ISO dates, snake_case)
- [x] Tests dans `tests/test_cli_activity.py` (incluant `json.loads(result.output)`)
- [x] `make validate` puis commit `feat: Commandes CLI activity list/show/stats (Lot 5c.2)`

**5c.3 — Flag `--json` sur les lectures existantes**
- [x] `goal list/show`, `plan list/show/match`, `plan session list`, `athlete show/history`, `status`
- [x] Helper interne `_emit_json` + sérialiseurs
- [x] Tests `--json` dans les fichiers existants (au moins un parse JSON par commande convertie)
- [x] `specs.md` §11 nouveau : conventions JSON
- [x] Cocher `backlog.md` 5.4
- [x] `make validate` puis commit `feat: Sortie --json sur commandes de lecture (Lot 5c.3)`

### Résultat

Lot 5c livré en 3 commits :
- 5c.1 (1237ab1) : `db.list_activities` + `db.aggregate_activities` + `ActivityBucket`.
- 5c.2 (e2ba38d) : groupe CLI `activity list/show/stats` + module `serializers.py`.
- 5c.3 : flag `--json` sur `status`, `goal list/show`, `plan list/show/match`,
  `plan session list`, `athlete show/history` + doc `specs.md` §11.

187 tests verts (162 → 176 → 187, +25 tests). Lot 5d (subagent coach) reste à
attaquer.

### Hors scope (volontaire)

- Streams/laps détaillés (à introduire en 5d quand l'agent les demandera).
- TSS, IF, zones de FC dérivées.
- Pagination cursor/offset.
- Format CSV/Markdown.

### Résultat
(à remplir une fois la tâche terminée)
