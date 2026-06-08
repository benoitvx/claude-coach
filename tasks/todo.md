# Lot 7 — Débriefs de séance (ressenti / RPE / douleurs)

## Contexte
Le coach recueille en conversation le ressenti d'une séance (RPE, sensations,
signaux douleur) mais rien ne le persiste. Trou identifié quand le débrief du
run de dimanche n'a pas pu être retrouvé. Besoin renforcé par le suivi
mollet/ACWR : un historique RPE + douleurs requêtable est central pour
détecter la surcharge.

## Décisions actées (avec l'utilisateur)
- **Rattachement** : table dédiée `session_debriefs`, date obligatoire, liens
  optionnels `activity_id` ET/OU `planned_session_id`. Couvre séance planifiée,
  activité non planifiée (natation bonus), et ressenti sans activité Strava.
- **Champs structurés** : `rpe` (entier 1-10), `feeling` (ressenti, texte libre),
  `pain` (signaux douleur, texte libre). Pas de module wellness complet (hors scope).

## Décision actée — qui écrit
- [x] **Le coach écrit le débrief lui-même** sur la base de l'échange conversationnel
      (RPE/ressenti/douleurs donnés par l'utilisateur), puis le signale. Acter un
      fait réversible que l'utilisateur vient d'énoncer — même logique que le clean match.

## Plan d'implémentation

### 1. Modèle de données
- [ ] `models.py` : dataclass `SessionDebrief` (id, activity_id?, planned_session_id?,
      debrief_date, rpe?, feeling?, pain?, created_at, updated_at)
- [ ] `db.py` : `_migration_005_session_debriefs` + ajout à `MIGRATIONS`
      - table `session_debriefs`, FK `activity_id`→activities(ON DELETE SET NULL),
        `planned_session_id`→planned_sessions(ON DELETE SET NULL)
      - CHECK `rpe BETWEEN 1 AND 10` (nullable)
      - index sur `debrief_date`
- [ ] `db.py` : CRUD `add_debrief`, `get_debrief`, `list_debriefs`
      (filtres : `since`/`until` sur debrief_date, `activity_id`, `planned_session_id`),
      `update_debrief`, `delete_debrief`, `row_to_debrief`

### 2. CLI (groupe `debrief`)
- [ ] `claude-coach debrief add [--activity ID] [--session ID] [--date YYYY-MM-DD]
      [--rpe N] [--feeling TXT] [--pain TXT]` (date défaut = aujourd'hui ;
      au moins un lien OU une date)
- [ ] `claude-coach debrief list [--from] [--to] [--activity] [--session] [--json]`
- [ ] `claude-coach debrief show <ID> [--json]`
- [ ] `claude-coach debrief edit <ID> [opts]` + `debrief delete <ID>`

### 3. Sérialisation `--json`
- [ ] `serializers.py` : `serialize_debrief` (snake_case, ISO 8601, null jamais omis)
- [ ] Optionnel : enrichir `activity show --json` et `plan session list --json`
      d'un sous-objet `debrief` si présent (à trancher — peut-être lot suivant)

### 4. Intégration coach
- [ ] `.claude/agents/coach.md` : le coach lit les débriefs (`debrief list --json`)
      pour calibrer la charge, et écrit le débrief selon le garde-fou validé ci-dessus
- [ ] Note Zwift/timezone : signaler que VirtualRide + timezone GMT = heure locale
      potentiellement décalée (ne pas conclure à un lever 6h42)

### 5. Docs
- [ ] `specs.md` : §4 (modèle de données) + section CLI
- [ ] `CLAUDE.md` : bloc CLI + mention dans le subagent coach
- [ ] `backlog.md` : cocher lot 7

### 6. Tests
- [ ] Unit : migration 005 (idempotence, version), CRUD debrief, CHECK rpe,
      ON DELETE SET NULL
- [ ] Unit : serialize_debrief
- [ ] Integration CLI : add (avec/sans lien), list (filtres), show, edit, delete, --json
- [ ] `make validate` vert

### 7. Premier usage réel (data)
- [ ] Consigner le débrief d'aujourd'hui : VirtualRide #18833271761 / session S24
      vélo, RPE 3/10, RAS
- [ ] Consigner rétroactivement le run de dimanche 7 juin (J3 post-op) — demander
      à l'utilisateur RPE + état mollet/cicatrice pour renseigner `pain`

## Résultat

Lot 7 livré. `make validate` vert (270 tests, +23 nouveaux).

- **DB** : migration 005 (`session_debriefs`) + CRUD `insert/get/list/update/delete_debrief`.
- **CLI** : groupe `debrief` (add/list/show/edit/delete), `--json` sur list/show.
- **Sérialiseur** : `debrief_to_dict` (snake_case, ISO, null jamais omis).
- **Coach** : `debrief add` en write autonome (exception comme clean match),
  lecture `debrief list` pour suivi surcharge, note Zwift/timezone, étape 8 du
  workflow Post-séance. Test subagent OK.
- **Docs** : specs.md §10 (table + CLI), CLAUDE.md, backlog.md (lot 7 coché).
- **Tests** : `test_db_debrief.py` (12), `test_cli_debrief.py` (11) — migration,
  CHECK rpe, ON DELETE SET NULL, filtres, edit partiel, bout-en-bout CLI.
- **Data** : débrief #1 consigné (08/06, VirtualRide #18833271761 / séance #14,
  RPE 3, RAS).

### Reste à faire (input utilisateur)
- [ ] Débrief rétroactif du run de dimanche 7 juin (J3 post-op) — besoin du RPE
      + état mollet/cicatrice (conversation passée non disponible dans cette session).
- [ ] Commit (sur demande).
- [ ] Décision optionnelle : enrichir `activity show --json` / `plan session list --json`
      d'un sous-objet `debrief` — reporté, à trancher si le coach en a besoin.
