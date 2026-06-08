# Tâche en cours

## Lot 6.2 — Export `.zwo` (Zwift) des séances vélo

Générer un fichier `.zwo` à partir d'une séance planifiée vélo, via des blocs
structurés stockés en DB (mini-DSL). FTP-relatif. Sortie fichier + stdout.
Commande dédiée `plan session export`.

### Plan

**Module zwo**
- [x] `src/claude_coach/zwo.py` — `parse_blocks`, `blocks_to_json`/`blocks_from_json`, `generate_zwo`, `is_bike`

**DB / modèle**
- [x] `models.py` — `PlannedSession.blocks_json: str | None = None`
- [x] `db.py` — migration `004` (ADD COLUMN blocks_json) + ajout à `MIGRATIONS`
- [x] `db.py` — `_SESSION_COLS`, `_row_to_planned_session`, `insert_planned_session`
- [x] `db.py` — `update_planned_session_blocks(...)`
- [x] `serializers.py` — `planned_session_to_dict` expose `blocks`

**CLI**
- [x] `cli.py` — `plan session add --blocks`
- [x] `cli.py` — `plan session set-blocks <id> "<DSL>"`
- [x] `cli.py` — `plan session export <id> [--output] [--no-stdout]`

**Tests**
- [x] `tests/test_zwo.py` — parse DSL, erreurs, round-trip, generate_zwo
- [x] `tests/test_cli_coach.py` — add --blocks / set-blocks / export + erreurs

**Docs**
- [x] `specs.md`, `CLAUDE.md`, `.claude/agents/coach.md`, `backlog.md`

**Validation**
- [x] `make validate` passe
- [x] Test manuel : add --blocks → list --json (blocks peuplé) → export (fichier + stdout)
- [ ] Commit

### Résultat

- Nouveau module `src/claude_coach/zwo.py` : mini-DSL → blocs canoniques →
  XML `.zwo` (stdlib `xml.etree`, **aucune dépendance ajoutée**). FTP-relatif.
- Migration `004` : colonne `planned_sessions.blocks_json` (additive, appliquée
  sans souci sur la DB réelle, données intactes).
- 3 surfaces CLI : `plan session add --blocks`, `plan session set-blocks`,
  `plan session export` (fichier `data/exports/` + stdout). Garde-fous : sport
  vélo only, blocs requis pour export, DSL invalide → erreur explicite.
- `plan session list/show --json` exposent désormais `blocks` (`null` si absent).
- 28 tests ajoutés (`test_zwo.py` 21 + 7 CLI). `make validate` ✅ — **247 tests verts**.
- Docs synchronisées : `specs.md` (§4 + section export), `CLAUDE.md`, `coach.md`, `backlog.md` (6.2 coché).
- **Hors scope** (assumé) : `6.3` Suunto `.fit` ; commande unifiée `export --target` (6.4) à refondre plus tard.
- Smoke Zwift réel (drag-and-drop) : à faire par l'athlète.
