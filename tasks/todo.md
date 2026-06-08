# Lot 8 — Base de plans de référence (Decathlon Coach)

## Objectif
Constituer une base de plans d'entraînement de référence, curée, que le
**subagent coach lit comme source d'inspiration** (structure, périodisation,
types de séances) — JAMAIS à appliquer tel quel. Source : decathloncoach.com
(contenu public, usage perso).

## Décisions actées (avec l'utilisateur)
- **Curation ciblée** : ~12-15 plans représentatifs, choisis pour coller aux
  objectifs réels (reprise post-op, trail 50km oct 2026, swim&run sept 2026,
  70.3 printemps 2027). Pas d'aspiration exhaustive (~400 variantes existent).
- **Stockage** : fichiers markdown dans `references/decathlon-plans/`, lus par
  le coach via `Read`. Pas de table DB, pas de CLI, pas de migration.

## Sélection cible (à affiner pendant le harvest)
- **Course à pied** : reprise (155), course route (162), trail montagne longue
  ~12 sem (170, le plus proche du 50km), VMA confirmé (176)
- **Natation** : renforcement à sec (803) [+ mobilité (804) si pertinent]
- **Triathlon** : prépa (229)
- **Vélo indoor** : home trainer (239), cycling (567)
- **Vélo route** : renforcement (618)
- **Ski** : prépa saison (551)
- **Musculation** : un niveau (209) + articulations (213, pertinent blessures)

## Plan d'exécution
1. [ ] **Harvest URLs** : pour chaque goal retenu, naviguer (browser) → extraire
       les liens `sport-program/<hash>` → choisir la/les bonne(s) variante(s).
2. [ ] **Fetch détail** : WebFetch chaque plan choisi → extraire nom, sport,
       durée, fréquence, objectif, et le détail séance par séance.
3. [ ] **Écrire les markdown** : `references/decathlon-plans/<sport>-<slug>.md`
       (format homogène : front-matter léger + tableau séances) + `README.md`
       index (liste + source + disclaimer usage perso).
4. [ ] **Intégration coach** : pointer dans `.claude/agents/coach.md` — le coach
       consulte `references/decathlon-plans/` pour s'inspirer, avec garde-fou
       FORT : inspiration only, jamais appliquer tel quel, toujours adapter à
       l'athlète (objectifs, post-op, ACWR, créneaux/lieux, FC/allures chiffrées).
5. [ ] **Docs** : note dans CLAUDE.md (arborescence `references/`).
6. [ ] `make validate` (pas de code touché, sanity) ; commit sur demande.

## Résultat

Lot 8 livré. `make validate` vert (270 tests — aucun code touché, base 100 % markdown).

- **13 plans curés** dans `references/decathlon-plans/` + `README.md` (index + disclaimer).
- Harvest via chrome-devtools (catalogue = SPA, ~400 variantes au total → curation
  ciblée), détail via WebFetch. Plans longs (triathlon L 64 séances, vélo indoor)
  condensés en structure + patterns + séances repères.
- Couverture : trail 50 km, 10 km, semi, VMA, triathlon L (≈70.3), 2× vélo indoor,
  renfo cycliste, natation à sec, ski, muscu 12 sem, prévention genou + épaule.
- **Coach** : section dédiée dans `coach.md` (lecture `references/` pour s'inspirer)
  + garde-fou FORT « inspiration only, jamais appliquer tel quel » + étape 4 bis du
  workflow « Plan vers event ». Test subagent OK.
- **Docs** : arborescence `references/` dans CLAUDE.md.

### Skips assumés (curation)
- Goal « reprise course » (155) : que du grand débutant → hors profil.
- Cycling/RPM (567) : redondant avec home trainer.
- Marche, pilates, foot, boxe, tennis, yoga, basket, cardio-fitness : hors objectifs.
- Variantes mineures (mêmes séances en 8/10/12 sem) : un seul représentant gardé.

### Reste
- [ ] Commit + push (sur demande).
