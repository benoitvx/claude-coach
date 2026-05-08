# Tâche en cours

## Lot 5d — Subagent coach sportif

Plan complet : `~/.claude/plans/keen-seeking-marshmallow.md`.

### Plan

- [x] Créer `.claude/agents/coach.md` (frontmatter `name`/`description`/`model`/`tools` + body avec rôle, surface CLI, contexte athlète, principes d'entraînement, workflows, garde-fous)
- [x] Créer `tests/test_subagent_coach.py` (smoke structurel : frontmatter parsé, marqueurs clés présents)
- [x] Mettre à jour `CLAUDE.md` (section "Subagent coach (lot 5d)")
- [x] Mettre à jour `specs.md` §9 (cocher 5d, pointer vers `.claude/agents/coach.md`)
- [x] Mettre à jour `backlog.md` (cocher 5.5 et fermer 5.6)
- [x] `make validate` puis commit + push `feat: Subagent coach sportif (Lot 5d)`

### Hors scope (volontaire)

- Génération auto d'un plan complet 12+ semaines en un coup — l'agent propose semaine par semaine.
- Calculs TSS / IF / zones FC dérivées via streams — reportable.
- Multi-agents spécialisés (analyzer / planner / reviewer) — un seul coach pour MVP.
- Auto-application de `plan match` post-sync — reste manuel.
- Synchronisation iCal / Apple Calendar.

### Résultat

Lot 5d livré en un commit. `.claude/agents/coach.md` (~150 lignes) encode :
polarisé 80/20, périodisation base/build/peak/taper, calibrations par
discipline (run/ride/swim/swim_run/trail/triathlon), workflows types
("état des lieux", "plan vers event", "post-séance"), garde-fous
(propose-then-confirm pour les writes, pas de fabrication de données).

194 tests verts (187 → 194, +7 tests structurels du subagent). Le lot 5
(agent coach) est complet ; lot 6 (export workouts vers Suunto/Zwift)
reste à attaquer.

Validation manuelle en dogfood : invoquer le coach via "demande au coach …"
depuis une session Claude Code dans le repo et vérifier la qualité des
sorties. Itérer sur `coach.md` si nécessaire (lot 5d.x).
