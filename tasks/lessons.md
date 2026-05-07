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


## Automatisation : crontab pour la sync incrémentale

Une fois le full import terminé, programmer une sync chaque soir suffit :

```cron
# Sync Strava chaque soir à 22h00 (logs dans ~/strava-sync.log)
0 22 * * * cd ~/Dev/strava-connect && /Users/<user>/.local/bin/uv run strava-connect sync >> ~/strava-sync.log 2>&1
```

À adapter au chemin réel de `uv` (`which uv`) — cron a un `$PATH` minimaliste qui ne
contient pas forcément `~/.local/bin`. Le `cd` est nécessaire pour que `uv` retrouve
le projet (et son `.venv`).

Pour tester sans attendre 22h : `crontab -l` pour visualiser, et lancer la commande
à la main d'abord pour valider.

<!--
Format :

## <date> — <titre court>
**Contexte** : ce qui a déclenché l'erreur
**Erreur** : ce qui a mal tourné
**Correction** : la bonne approche
**Pattern à retenir** : règle générale à appliquer la prochaine fois
-->
