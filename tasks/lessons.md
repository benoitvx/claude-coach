# Leçons apprises

_Cumulatif des patterns d'erreur rencontrés. À relire au début de chaque session._

## 2026-05-07 — Strava `/activities/{id}/zones` : 402 pour comptes non-Summit
**Contexte** : Premier smoke test de `sync --full --limit 5`.
**Erreur** : Crash `httpx.HTTPStatusError: 402 Payment Required` sur `/zones`.
**Correction** : Élargir la liste des codes "ressource indisponible" dans `client.get_zones`
de `(403, 404)` à `(402, 403, 404)`.
**Pattern à retenir** : ne pas deviner les status d'API à partir de la sémantique HTTP.
402 est rarement utilisé mais Strava s'en sert pour les fonctionnalités payantes Summit.
Quand on traite un endpoint optionnel (Summit-only ici), tester d'abord avec un compte
réel ou consulter explicitement la doc Strava au lieu de lister 403/404 par habitude.


## 2026-05-07 — Strava `/activities/{id}/streams` : 404 pour activités manuelles
**Contexte** : `sync --full` plante après ~85 activités sur une activité manuelle
(saisie sans données capteur, type "Étirements").
**Erreur** : Crash `httpx.HTTPStatusError: 404 Not Found` sur `/streams`.
**Correction** :
1. `client.get_streams` retourne `{}` sur 404 (mêmes manières que `get_zones`).
2. `has_complete_activity` ne vérifie plus que l'existence dans `activities` (la transaction
   unique de `insert_full_activity` garantit l'atomicité — pas besoin de vérifier streams/laps).
**Pattern à retenir** : si un check de "complétude" exige des sous-ressources optionnelles,
il forcera des re-fetchs perpétuels pour les activités qui n'en ont pas. Préférer un
critère minimal (existence) quand l'insertion est transactionnelle.


## 2026-05-11 — Subagent coach : sous-exploitation des données par défaut

**Contexte** : 1ʳᵉ séance d'intervalles (6×30") matchée lundi 11 mai. Le coach
a fait un débrief en regardant seulement `activity show --json`, et a halluciné
"pas de laps en DB, la montre n'a pas segmenté" alors que `activity_laps`
contenait 15 lignes parfaitement alignées sur les blocs vifs.

**Erreur** : `activity show --json` exclut volontairement les laps et streams
(décision 5c.2 : compactness). Le subagent n'avait aucune commande pour les
récupérer → il a inféré "absent" depuis l'absence de champ.

**Correction** : nouveau lot 5c.4 (`activity laps <ID>`) puis 5c.5 (`activity
streams <ID>`), avec mise à jour de `coach.md` pour les déclencher dans le
workflow Post-séance selon `session_type`.

**Pattern à retenir** : pour un subagent qui interroge la DB via CLI, **chaque
décision "exclus volontairement" côté sérialiseur est un trou cognitif** tant
qu'aucune commande dédiée n'expose la donnée séparément. Avant de cacher
quelque chose pour rester compact, prévoir la commande "détail" en regard, ou
au moins documenter le trou dans le prompt du subagent.


## 2026-05-11 — Mise à jour de prompt sans CLI correspondante

**Contexte** : Lot 5d.2 ajoute un "semantic check" dans `coach.md` qui dit à
l'agent : *"si mismatch, propose à l'athlète de passer la session en `skipped`
puis créer une session ad-hoc"*. Mais la CLI ne couvrait pas l'écriture du
statut `skipped` — seul `plan session done` existait. Le workflow était
silencieusement cassé.

**Erreur** : le prompt instruisait une action que la surface outil ne
permettait pas. Découvert par observation utilisateur (« il manque `goal
abandon` »).

**Correction** : Lot 5c.6 — ajout des transitions manquantes (`goal abandon`,
`plan complete`, `plan pause`, `plan session skip`) en parallèle de leurs
homologues `complete` / `done` existants.

**Pattern à retenir** : **quand on étend un prompt agent pour instruire une
action downstream (Bash, CLI, MCP), vérifier que la surface outil supporte
l'action**. Sinon le prompt est aspirational, pas opérationnel. Règle pratique :
toute mention d'un nouveau verbe (`skip`, `abandon`, `reopen`) dans `coach.md`
exige soit la commande, soit une note explicite "indisponible pour l'instant".


## Automatisation : sync planifiée (macOS)

Préférer **launchd** plutôt que cron : un Mac qui dort à l'heure prévue rate
le cron sans rattrapage, alors qu'avec launchd on peut au moins programmer
à une heure où la machine est probablement éveillée.

**Installation one-shot** (par défaut : 02:05 chaque jour, quota Strava frais à 02:00 Paris) :

```bash
bash scripts/install-launchd-sync.sh
```

Override de l'heure via env vars :
```bash
SYNC_HOUR=12 SYNC_MINUTE=30 bash scripts/install-launchd-sync.sh
```

Le script auto-détecte le chemin de `uv`, écrit `~/Library/LaunchAgents/com.claude-coach.sync.plist`
et le charge via `launchctl`. Il est idempotent : relancer remplace l'agent
existant. Logs dans `~/Library/Logs/claude-coach/sync.{out,err}.log`.

Tip : pendant l'import historique initial (le Mac peut être laissé allumé la
nuit), 02:05 est idéal. Une fois l'historique fini, basculer vers une heure
de jour plus tolérante à un Mac qui dort la nuit.

**État actuel** (mis à jour 2026-05-08) : import historique terminé
(357 activités sur 2 ans, status `success`), launchd basculé sur **10:00
heure locale Paris** :

```bash
SYNC_HOUR=10 SYNC_MINUTE=0 bash scripts/install-launchd-sync.sh
```

Note : `StartCalendarInterval` de launchd est en heure locale système, pas UTC.
Le créneau s'adapte automatiquement été/hiver.

Pour tester sans attendre :
```bash
launchctl start com.claude-coach.sync
```

Désinstallation :
```bash
launchctl unload ~/Library/LaunchAgents/com.claude-coach.sync.plist
rm ~/Library/LaunchAgents/com.claude-coach.sync.plist
```

**Note** : le quota lecture Strava reset à 00:00 UTC = 02:00 Paris. Une exécution
à 12:30 garantit que le Mac est éveillé tout en disposant du quota frais. Tant
que l'import historique n'est pas fini, le script utilise `sync --full` (skip
les activités déjà complètes via `has_complete_activity` → coût marginal).
Une fois historique complet, basculer vers `sync` (incrémentale, plus économe)
en éditant la plist.

Sur Linux : utiliser cron classique ou systemd timer (pas couvert ici, projet
ciblé macOS).

<!--
Format :

## <date> — <titre court>
**Contexte** : ce qui a déclenché l'erreur
**Erreur** : ce qui a mal tourné
**Correction** : la bonne approche
**Pattern à retenir** : règle générale à appliquer la prochaine fois
-->

## 2026-06-06 — Coach : sync + ressenti avant débrief
**Contexte** : test matinal. L'athlète demande "analyse ma dernière course et compare-la au plan". Le coach a débriefé une course du 11 mai alors que la vraie dernière séance datait de la veille (5 juin), non encore synchronisée (launchd 10:00 passé avant la sortie). Il a aussi débriefé sans demander le ressenti.
**Erreur** : (1) règle "ne lance jamais sync" trop stricte → le coach analyse une activité périmée. La sync launchd 10:00 ne couvre pas les séances faites après 10:00 le jour même. (2) Débrief 100 % data, sans le ressenti qui distingue "FC haute mais facile" de "FC normale mais jambes lourdes".
**Correction** : `.claude/agents/coach.md` — (1) le rituel de démarrage lance désormais `sync` **incrémentale** systématiquement (jamais `sync --full`) pour garantir la vraie dernière séance. (2) Workflow Post-séance : étape 0 = demander le ressenti (RPE, jambes, souffle, douleurs, sommeil) et **attendre la réponse** avant d'analyser.
**Pattern à retenir** : un coach qui analyse doit d'abord garantir la fraîcheur de ses données (sync légère systématique) et recueillir le subjectif avant l'objectif — la donnée seule ment sur la fatigue.

## 2026-06-06 — Coach : acter une séance faite ne se demande pas
**Contexte** : la séance du 5 juin était réalisée et apparieable (clean match en dry-run), mais le coach ne l'avait pas notée dans le plan — il s'est contenté de proposer `plan match` et d'attendre le feu vert. L'athlète : "ça devrait être un comportement par défaut — la séance est faite, donc je note dans le plan".
**Erreur** : la règle d'écriture du coach traitait *toutes* les écritures pareil (confirmation obligatoire). Or `plan match` n'est pas une décision : c'est acter un fait, réversible et idempotent (il met `status=done` + lie l'activité). La confirmation systématique créait une friction inutile.
**Correction** : `coach.md` + `CLAUDE.md` — carve-out : `plan match` propre (date ±1 j, même famille, semantic check OK) s'applique **tout seul** au démarrage et en Post-séance, puis est signalé. Tout le reste (créer/modifier plan, skip, abandon, athlete set) reste sous confirmation. Exception à l'exception : mismatch/substitution → on demande.
**Pattern à retenir** : distinguer write *factuel réversible* (à appliquer par défaut) de write *décisionnel* (à confirmer). Ne pas mettre une barrière de confirmation sur l'enregistrement d'un fait déjà accompli.

## 2026-06-08 — Venv desync : pre-commit "disparaissait" sans cesse
**Contexte** : à chaque commit, `pre-commit` introuvable dans le venv → commit bloqué. Corrigé plusieurs fois à la main par `uv sync --extra dev`, mais le problème revenait.
**Erreur** : les outils de dev (ruff, mypy, pytest, pre-commit) étaient en `[project.optional-dependencies] dev` = un **extra**. Les extras ne sont jamais installés par défaut. Or `uv run claude-coach ...` (lancé en permanence) re-synchronise le venv sur le set par défaut (sans l'extra dev) et **prune** donc les outils de dev à chaque appel.
**Correction** : migrer vers `[dependency-groups] dev` (PEP 735) + `[tool.uv] default-groups = ["dev"]`. uv synchronise le groupe `dev` par défaut, y compris sur `uv run` → plus de pruning. Makefile et CI repassés de `uv sync --extra dev` à `uv sync`. Vérifié : un `uv run` nu ne supprime plus `pre-commit`.
**Pattern à retenir** : pour des outils de dev qui doivent rester présents dans un projet uv, utiliser un **dependency-group** (`[dependency-groups]`), pas un **extra** (`[project.optional-dependencies]`). L'extra est pour des features optionnelles destinées aux consommateurs du package, pas pour l'outillage local que `uv run` doit préserver.

## 2026-06-08 — Export Suunto : pas d'import fichier, le backlog se trompait de cible
**Contexte** : Lot 9 « export vers Suunto ». Le backlog prévoyait (6.3) de générer des fichiers `.fit` Suunto, par analogie avec le `.zwo` Zwift (fichier déposé par l'utilisateur).
**Erreur** : la prémisse était fausse. Recherche (FAQ + forum Suunto officiels) : **Suunto n'accepte aucun import de fichier de séance structurée** sur la montre — ni `.fit`, ni format propriétaire. La seule voie pour une séance *guidée* est un sync cloud via un partenaire (intervals.icu, TrainingPeaks, **Nolio**). Générer un FIT aurait été un cul-de-sac.
**Correction** : pivot vers l'**API Nolio** (OAuth2 + `POST create/planned/training/` avec `structured_workout`) que l'utilisateur utilise déjà (sync Nolio→Suunto fonctionnelle). Pas de FIT, pas de dépendance. Lot 6.3 marqué *remplacé*.
**Pattern à retenir** : avant d'architecturer un export « fichier déposé sur l'appareil », **vérifier que l'appareil accepte réellement cet import** — ne pas raisonner par analogie avec un autre écosystème (Zwift ≠ Suunto). Un connecteur grand public peut n'avoir **aucune** voie fichier-local et n'exposer que du sync cloud partenaire. Confirmer le chemin d'ingestion réel (doc/forum constructeur) avant d'écrire une ligne de code.

## 2026-06-10 — API partenaire « gratuite » : vérifier que l'**écriture** n'est pas premium-gated
**Contexte** : Lot 9 (Nolio) tout codé et validé en dry-run, mais le push réel renvoie `403 "API access requires an active coach or premium subscription"` sur `create/planned/training/`. La voie running→Suunto était donc inutilisable sans abonnement payant. Lot 10 = pivot vers **intervals.icu** (réellement gratuit, API ouverte clé perso + upload natif Suunto).
**Erreur** : on a supposé qu'une API documentée et accessible en OAuth était utilisable gratuitement. En réalité l'auth marchait (lecture OK), mais l'**endpoint d'écriture** était réservé aux comptes payants — détail invisible tant qu'on ne pousse pas pour de vrai.
**Correction** : pour le lot 10, **confirmer la gratuité du chemin précis visé** (ici : créer un événement planifié + sync montre) AVANT de coder — recherche pricing + forum. intervals.icu : modèle don, aucune feature derrière un paywall, Suunto upload gratuit. Garder Nolio en place mais reléguer en fallback.
**Pattern à retenir** : « API gratuite/ouverte » ≠ « l'opération que je veux est gratuite ». Avant de bâtir sur une API partenaire, **identifier l'endpoint exact** (souvent une écriture) et vérifier qu'il n'est pas premium-gated — via doc *pricing* + forum, ou un vrai appel de test tôt. Le succès d'un OAuth/d'une lecture ne garantit rien sur les writes.

## 2026-06-10 — intervals.icu : préférer le `workout_doc` structuré au parsing de texte
**Contexte** : lot 10, mapping des blocs canoniques vers intervals.icu. 1ère implémentation = générer le **texte** « workout builder » (champ `description`), que le serveur parse en steps. Le push réel a réussi (event créé) **mais la séance arrivait en texte brut sur la montre, sans structure**.
**Erreur** : le parseur de *texte* d'intervals.icu **a parsé les durées mais ignoré silencieusement la cible FC** (`130-148 HR`). Diagnostic par GET de l'event créé → `workout_doc.steps` montrait `{"duration":1500}` sans `hr`. Test empirique de variantes : la FC **en bpm absolus n'est PAS supportée en texte** (seulement zones `Z2 HR` ou %FCmax `70-80% HR`) ; l'allure, si (`4:30/km Pace` OK). Or les séances de l'utilisateur sont en **FC absolue**.
**Correction** : envoyer le **`workout_doc` JSON structuré** directement (champ `workout_doc` du payload event), pas du texte. Mapping complet round-trippé contre l'API réelle (warmup/cooldown `text`, `reps`/`steps`, `pace` secs/km, `power` w) avant de figer le code + les tests. (NB : la FC, elle, a nécessité un 2e fix — voir leçon suivante.)
**Pattern à retenir** : (1) quand une API offre **à la fois** un format texte « pratique » et un format structuré, **préférer le structuré** — le parseur de texte est une boîte noire à pertes silencieuses (il peut ignorer un champ sans erreur). (2) Après un premier push « réussi », **GET la ressource créée** pour vérifier ce que le serveur a *réellement* stocké, ne pas se fier au 200. (3) Lever les inconnues de format par **test empirique sur events jetables** (create → GET → delete) plutôt qu'en se fiant à de la doc de forum résumée.

## 2026-06-10 — intervals.icu→Suunto : FC en bpm absolus rejetée (250), convertir en %FCmax
**Contexte** : lot 10. Le `workout_doc` avec FC en bpm (`{"hr":{"units":"bpm","start":130,"end":148}}`) était accepté par intervals.icu (stocké tel quel), MAIS l'upload vers Suunto échouait : `push_errors` = `POST cloudapi.suunto.com/v2/guides/files 400: Invalid 'guide.steps.N.fields.0.value': value is larger than the allowed maximum (250.0)`.
**Erreur** : on croyait la FC bpm OK car intervals.icu l'acceptait. En réalité, à la génération du **guide Suunto**, intervals.icu convertit la FC en interne et déborde (>250). Matrice de tests (create→GET push_errors→delete) : `units:"bpm"` **échoue toujours** ; `pace`, `hr_zone`, `%hr`, sans-cible **passent**.
**Piège dans le diagnostic** : intervals.icu n'uploade vers Suunto que **la semaine à venir** de séances. Mes 1ers tests datés à +3 semaines avaient `push_errors` vide → faux « OK » (jamais tentés). Il a fallu **dater les events dans la fenêtre (~7 j)** pour obtenir un vrai verdict.
**Correction** : convertir `bpm → %FCmax` (`{"hr":{"units":"%hr",...}}`) avec la FCmax de l'athlète (`get_latest_metrics().fc_max`). La montre reconvertit en bpm avec SA FCmax → bpm correct si les deux coïncident. `push-intervals` exige donc une FCmax dès qu'il y a une cible FC. Vérifié : FC 130-148 → 68-77 %FCmax → upload Suunto **sans erreur**.
**Pattern à retenir** : (1) « le serveur intermédiaire accepte mon payload » ≠ « le système final l'accepte » — vérifier le **dernier maillon** (ici l'upload Suunto via `push_errors`). (2) Pour un test asynchrone à fenêtre, **reproduire les conditions de déclenchement** (date dans la fenêtre) sinon l'absence d'erreur ne prouve rien. (3) Un format absolu peut devoir être exprimé en **relatif** (%FCmax) côté cible — garder le canonique en absolu, convertir au mapping.

## 2026-06-10 — intervals.icu : POST ne dé-duplique pas → upsert obligatoire pour l'idempotence
**Contexte** : lot 10. On voulait qu'un re-push d'une séance (ex. après édition) ne crée pas de doublon. Le payload portait un `external_id="claude-coach-<id>"` en pensant que ça suffirait (comme `id_partner` côté Nolio, qui renvoie 400 si déjà créé).
**Erreur** : `POST /events` avec un `external_id` déjà utilisé **crée quand même un 2e event** (vérifié : 2 events au même jour). intervals.icu ne traite pas `external_id` comme une clé d'unicité au POST.
**Correction** : `IntervalsClient.upsert_event` = GET events à la date, filtrer par `external_id`, puis **PUT** l'existant sinon **POST**. Idempotence vérifiée en vrai (2 pushes → même event id, 1 seul event).
**Pattern à retenir** : ne jamais **supposer** qu'un champ « external id » d'une API rend les écritures idempotentes — beaucoup d'APIs le stockent juste comme métadonnée. Tester le re-push réellement ; si ça duplique, implémenter un upsert explicite (lookup + PUT/POST).
