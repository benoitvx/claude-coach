# Tâche en cours

## Lot 5c.5 + 5d.2 — Streams CLI + itérations coach

Suite du dogfood :
- Le coach raisonne sur ACWR / data quality / semantic check de façon implicite ;
  on l'encode pour stabiliser.
- Pour analyser un long Z2 (% temps en zone FC), il manque l'accès aux streams.
- `activity_zones` est vide (compte non-Summit) → on ne l'expose pas.

### 5c.5 — Streams CLI

- [ ] `db.list_streams(conn, activity_id, stream_types=None)` + `_row_to_stream`
- [ ] `serializers.stream_to_dict` (active inclut le JSON `data` parsé en list[float|int])
- [ ] CLI `activity streams <ID> [--type heartrate|watts|velocity_smooth|...] [--json]`
- [ ] Tests DB (filtre par type, vide, inconnu) + CLI (JSON, human résumé "X samples")
- [ ] Smoke vraie DB : `activity streams 18461924018 --type heartrate --json | jq '.[0].data | length'`
- [ ] Commit + push

### 5d.2 — Coach itérations

- [ ] `.claude/agents/coach.md` : 3 sections nouvelles
  - **ACWR** dans "Principes d'entraînement" : formule explicite + zones safe/risque
  - **Data quality check** dans "État des lieux" : flag métriques athlète obsolètes / incohérentes
  - **Semantic check** dans "Post-séance" : détecter substitution (planifié renfo / réalisé run)
  - **Pattern d'analyse streams** dans "Workflows" : pour séance longue, lire heartrate stream + calculer % en zones via `python -c`
- [ ] `tests/test_subagent_coach.py` : markers `"ACWR"`, `"data quality"` (au moins un)
- [ ] Doc : CLAUDE.md mention rapide
- [ ] Commit + push

### Hors scope (volontaire)

- `activity zones` (table vide pour non-Summit) — pas d'exposition CLI utile.
- Commande `activity time-in-zone` calculée côté CLI — le coach le fait via `python -c` sur le stream brut. À ajouter si le pattern devient répétitif.
- Multi-agents — toujours un seul coach.
- Auto-execution writes — toujours propose-then-confirm.

### Résultat
(à remplir une fois la tâche terminée)
