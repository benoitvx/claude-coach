# Lot 9 — Export des séances structurées vers Nolio (→ Suunto 9)

Plan complet : `~/.claude/plans/pr-pare-le-projet-lot-sunny-taco.md`.

**Découverte clé** : Suunto n'importe aucun fichier de séance → on passe par **l'API Nolio**
(OAuth2 + `POST /api/create/planned/training/` avec `structured_workout`). Pas de FIT, pas de
nouvelle dépendance (`httpx` déjà là). Cibles : allure (m/s), FC (bpm), durée (s), distance (m).

## Schéma API réel (doc Nolio, vérifié)

- OAuth : Basic auth `client_id:client_secret` sur `/api/token/`, réponse `expires_in` (86400s),
  refresh **rotatif** → persister avant retour. authorize `GET /api/authorize/`.
- `create/planned/training/` : `id_partner` (int, idempotence = id séance), `sport_id` (int,
  sport-map : Running=2, Trail running=52, Road cycling=14, Virtual ride=18, Swimming=19…),
  `name`, `date_start` "YYYY-MM-DD" ; optionnels `structured_workout`, `duration` (s),
  `distance` (**km**), `description`, `athlete_id` (**omis** pour son propre compte).
- `structured_workout` : steps `{type, intensity_type(warmup/active/rest/cooldown), step_duration_type(duration|distance), step_duration_value, target_type(pace/speed/power/heartrate/no_target), target_value_min, target_value_max}` ; répétitions `{type:repetition, value:N, steps:[...]}`.
- **Unités** : pace = **m/s**, speed = km/h, power = W, HR = bpm, distance = m, durée = s.

## Étapes

- [ ] 1. `models.py` : ajouter `NolioConfig` (client_id/secret/redirect_uri) + `NolioTokens`
      (access/refresh/expires_at, sans athlete_id).
- [ ] 2. `workout.py` (neuf) : DSL running structuré → `Step`/`Repetition` canoniques.
      DSL : `[warmup|cooldown|active|rest:]<dur><@target>` ; dur = `min|s` (temps) / `km|m`
      (distance) ; target = `p<m:ss>[-..]` (allure→m/s), `h<bpm>[-..]`, `w<W>[-..]`, ou absent.
      Répétitions `Nx[step;step;...]`. Réutilise `_split_top_level` de `zwo.py`. `workout_to_json`/
      `workout_from_json`. Branche vélo `.zwo` (`zwo.py`) **intacte**.
- [ ] 3. `nolio_auth.py` (neuf) : OAuth2 Nolio (authorize/exchange Basic auth/refresh rotatif/
      get_valid_tokens, save/load `data/nolio_tokens.json` 0o600). Réutilise le callback server
      générique de `auth.py`.
- [ ] 4. `nolio.py` (neuf) : sport-map + `structured_workout_from_items` + `build_planned_training_payload`
      + `NolioClient` (httpx **POST**, Bearer, 401→AuthError, 429→Retry-After, 5xx→retry, 400→erreur claire).
- [ ] 5. `cli.py` : router `_blocks_json_or_raise` par famille (vélo→zwo, autre→workout) ;
      groupe `nolio` (`auth`, `status`) ; `plan session push-nolio <ID> [--dry-run] [--athlete-id]`.
- [ ] 6. Tests : `test_workout.py` (parsing valide/invalide, round-trip), `test_nolio.py`
      (mapping structured_workout + conversion allure m/s, sport-map, payload, client POST via
      pytest-httpserver : 401/429/400), `test_nolio_auth.py` (Basic auth, expires_in→expires_at,
      refresh rotatif persisté, flow OAuth happy/state-mismatch).
- [ ] 7. Docs : `specs.md` (§9/§10), `backlog.md` (6.3 remplacé + Lot 9), `README.md`,
      `.claude/agents/coach.md` (proposer `push-nolio`, confirmation requise).
- [ ] 8. `make validate` vert (couverture ≥70% neuf, ≥90% auth/client).
- [ ] 9. Smoke test réel (accès dispo) : `nolio auth` → `push-nolio` → vérifier séance structurée
      dans Nolio + arrivée Suunto 9 ; **confirmer l'unité d'allure** (m/s) et ajuster si besoin.

## Décisions actées
- v1 Nolio = sports **non-vélo** (running surtout). Le vélo garde `.zwo`→Zwift (`export`).
  Bike→Nolio (watts via FTP) = hors scope v1.
- Cibles **absolues** dans le DSL (le coach calcule bpm/allure depuis `athlete show`).
- `athlete_id` omis (push sur son propre compte Nolio).

## Résultat

Lot 9 livré (sauf 9.8, smoke test réel — à lancer par l'utilisateur). `make validate`
vert : **313 tests** (49 nouveaux : workout 23, nolio 10, nolio_auth 6, CLI 10), ruff +
mypy --strict clean. **Zéro dépendance ajoutée** (`httpx` réutilisé).

Livré :
- `workout.py` : DSL running multi-cibles (allure→m/s, FC, durée/distance, répétitions),
  blocs canoniques `Step`/`Repetition`, round-trip JSON. Branche vélo `.zwo` intacte.
- `nolio_auth.py` : OAuth2 Nolio (Basic auth, `expires_in`, refresh rotatif persisté avant
  retour, tokens `data/nolio_tokens.json` 0o600). Réutilise le callback server d'`auth.py`.
- `nolio.py` : `NolioClient` (httpx POST, 401/429/400/5xx), sport-map, mapping
  `structured_workout`, payload idempotent (`id_partner` = id séance).
- `cli.py` : groupe `nolio` (`auth`/`status`), `plan session push-nolio <ID> [--dry-run]`,
  routage des blocs par famille de sport.
- Docs : `specs.md`, `backlog.md` (6.3 remplacé + Lot 9), `README.md`, `CLAUDE.md`,
  `.claude/agents/coach.md` (coach propose `push-nolio`, confirmation requise).

Dry-run E2E vérifié (TrailRun → sport_id 52, allure 3:45/km → 4.444 m/s, payload conforme
au schéma Nolio).

**Reste 9.8 (smoke test réel)** : `nolio auth` (renseigner `NOLIO_CLIENT_ID/SECRET/REDIRECT_URI`
— le `redirect_uri` doit matcher l'enregistrement Nolio), puis `push-nolio` d'une vraie séance.
Confirmer alors l'unité d'allure (m/s) et le nom du champ id dans la réponse Nolio.
