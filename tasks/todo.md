# Tâche en cours

## Lot 5c.5 + 5d.2 — Streams CLI + itérations coach

Suite du dogfood :
- Le coach raisonne sur ACWR / data quality / semantic check de façon implicite ;
  on l'encode pour stabiliser.
- Pour analyser un long Z2 (% temps en zone FC), il manque l'accès aux streams.
- `activity_zones` est vide (compte non-Summit) → on ne l'expose pas.

### 5c.5 — Streams CLI

- [x] `db.list_streams(conn, activity_id, stream_types=None)` + `_row_to_stream`
- [x] `serializers.stream_to_dict` (active inclut le JSON `data` parsé en list[float|int])
- [x] CLI `activity streams <ID> [--type heartrate|watts|velocity_smooth|...] [--json]`
- [x] Tests DB (filtre par type, vide, inconnu) + CLI (JSON, human résumé "X samples")
- [x] Smoke vraie DB : `activity streams 18461924018 --type heartrate --json | jq '.[0].data | length'`
- [x] Commit + push

### 5d.2 — Coach itérations

- [x] `.claude/agents/coach.md` : 3 sections nouvelles
  - **ACWR** dans "Principes d'entraînement" : formule explicite + zones safe/risque
  - **Data quality check** dans "État des lieux" : flag métriques athlète obsolètes / incohérentes
  - **Semantic check** dans "Post-séance" : détecter substitution (planifié renfo / réalisé run)
  - **Pattern d'analyse streams** dans "Workflows" : pour séance longue, lire heartrate stream + calculer % en zones via `python -c`
- [x] `tests/test_subagent_coach.py` : markers `"ACWR"`, `"data quality"` (au moins un)
- [x] Doc : CLAUDE.md mention rapide
- [x] Commit + push

### Hors scope (volontaire)

- `activity zones` (table vide pour non-Summit) — pas d'exposition CLI utile.
- Commande `activity time-in-zone` calculée côté CLI — le coach le fait via `python -c` sur le stream brut. À ajouter si le pattern devient répétitif.
- Multi-agents — toujours un seul coach.
- Auto-execution writes — toujours propose-then-confirm.

### Résultat

Livré en 2 commits :

- **5c.5** (`fc69ae9`) : `activity streams <ID> [--type T] [--json]` — expose
  les streams seconde-par-seconde (357 activités couvertes, dont 315 avec
  heartrate). `activity_zones` skippé (0 activité Summit).
- **5d.2** : `coach.md` enrichi avec 4 patterns d'analyse :
  - **ACWR** (charge 7j / moyenne hebdo 28j, fourchettes safe/attention/risque).
  - **Data quality check** — flagger métriques athlète obsolètes ou
    incohérentes avec le volume récent, suggérer test (Cooper, FTP 20 min).
  - **Semantic check** planifié ↔ réalisé avant `plan match` — bloque la
    validation en cas de mismatch fort, propose `skipped` + session ad-hoc.
  - **Pattern stream long Z2** — script Python ad-hoc inline pour calculer
    time-in-zone via `activity streams --type heartrate --json | python3`.
    Seuil objectif : ≥ 80 % du temps en Z1+Z2 pour un long réussi.

207 tests verts (201 → 207, +6 tests streams). Smoke markers du subagent
mis à jour (`acwr`, `data quality`, `semantic check`, `activity streams`)
pour qu'un retour en arrière soit détecté.

Prochaine itération possible (selon dogfood) : ajouter une commande
`activity time-in-zone <ID>` qui fait le calcul en SQL+Python côté CLI au
lieu du `python3 -c` inline. À ouvrir si le pattern devient répétitif.
