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


## Automatisation : sync planifiée (macOS)

Préférer **launchd** plutôt que cron : un Mac qui dort à l'heure prévue rate
le cron sans rattrapage, alors qu'avec launchd on peut au moins programmer
à une heure où la machine est probablement éveillée.

**Installation one-shot** (par défaut : 12:30 chaque jour) :

```bash
bash scripts/install-launchd-sync.sh
```

Le script auto-détecte le chemin de `uv`, écrit `~/Library/LaunchAgents/com.strava-connect.sync.plist`
et le charge via `launchctl`. Il est idempotent : relancer remplace l'agent
existant. Logs dans `~/Library/Logs/strava-connect/sync.{out,err}.log`.

Pour changer l'heure : édite la plist (`Hour` / `Minute`) et relance le script.

Pour tester sans attendre :
```bash
launchctl start com.strava-connect.sync
```

Désinstallation :
```bash
launchctl unload ~/Library/LaunchAgents/com.strava-connect.sync.plist
rm ~/Library/LaunchAgents/com.strava-connect.sync.plist
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
