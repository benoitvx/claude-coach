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

<!--
Format :

## <date> — <titre court>
**Contexte** : ce qui a déclenché l'erreur
**Erreur** : ce qui a mal tourné
**Correction** : la bonne approche
**Pattern à retenir** : règle générale à appliquer la prochaine fois
-->
