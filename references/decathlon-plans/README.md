# Plans de référence — Decathlon Coach

Base de plans d'entraînement curés, extraits de [decathloncoach.com](https://www.decathloncoach.com)
(contenu public, **usage personnel**), pour servir de **source d'inspiration au
subagent coach** : structure, périodisation, types de séances, progression.

## Crédits / source

Tous les plans ci-dessous proviennent de **Decathlon Coach** :
<https://www.decathloncoach.com/fr/home/coaching/programs/sport>

Chaque fichier porte l'URL exacte du programme d'origine dans son front-matter
(`source_url`). Contenu reproduit ici de façon condensée à des fins d'inspiration
personnelle ; les droits restent à Decathlon Coach et à leurs coachs respectifs
(crédités dans chaque fichier via le champ `coach`).

> ⚠️ **Inspiration, jamais application telle quelle.** Ces plans sont génériques
> (allures en % FC/VMA/FTP abstraits, volumes standardisés, pas de prise en compte
> blessure/post-op/créneaux). Le coach DOIT les adapter à l'athlète : objectifs
> réels, état du moment (reprise post-op), ACWR, créneaux/lieux, matériel, et
> calibration FC/allures/watts sur `athlete show`. Voir le garde-fou dans
> `.claude/agents/coach.md`.

Curation ciblée sur les objectifs de l'athlète : **Swim&Run sept 2026**,
**Trail 50 km / 2000 m D+ oct 2026**, **Ironman 70.3 printemps 2027**, +
prévention (antécédents genou/épaule).

## Index

| Fichier | Discipline | Durée | Pertinence |
|---|---|---|---|
| `course-trail-montagne-50km-12sem.md` | Trail montagne 42-69 km, Confirmé | 12 sem | Trail 50 km oct 2026 |
| `course-route-10km-45min-6sem.md` | 10 km route, Confirmé | 6 sem | Vitesse spécifique course |
| `course-route-semi-marathon-10sem.md` | Semi-marathon, Confirmé | 10 sem | Endurance longue (jambe course swim&run) |
| `course-vma-confirme-8sem.md` | VMA, Confirmé | 8 sem | Banque de séances VMA/côtes |
| `triathlon-L-70.3-16sem.md` | Triathlon L (≈70.3) | 16 sem | **70.3 printemps 2027** (distances quasi identiques) |
| `velo-indoor-cycliste-complet-9sem.md` | Vélo indoor, Confirmé | 9 sem | Banque séances HT structurées |
| `velo-indoor-endurance-9sem.md` | Vélo indoor, Intermédiaire | 9 sem | Base aérobie HT (créneau ≤ 1h) |
| `renfo-cyclistes-poids-corps-6sem.md` | Renfo cycliste (sans matériel) | 6 sem | Renfo vélo/posture, déplacement |
| `natation-renfo-puissance-4sem.md` | Renfo à sec nageur | 4 sem | Soutien natation 70.3 |
| `ski-prepa-physique-4sem.md` | Prépa physique ski | 4 sem | Saison ski + proprioception |
| `musculation-12sem.md` | Musculation full-body, Inter. | 12 sem | Renfo général périodisé |
| `prevention-genou-stable-2sem.md` | Prévention genou, Confirmé | 2 sem | **Antécédent LCA + arthrose genou D** |
| `prevention-epaule-souple-forte-2sem.md` | Prévention épaule, Confirmé | 2 sem | **Tendinite épaule D en rééduc** |

## Format des fichiers

Chaque fichier a un front-matter YAML (`source_url`, `sport`, `niveau`,
`duree_semaines`, `seances_par_semaine`, `objectif`, `pertinence_athlete`, …)
suivi de la structure du plan et des séances. Les plans très longs (triathlon L,
vélo indoor) sont **condensés** : structure + patterns + séances repères plutôt
que les 64 séances verbatim. L'URL source permet de retrouver le détail complet.

## Maintenance

Ajouter un plan : créer un `<discipline>-<slug>.md` avec le même front-matter et
l'ajouter à l'index ci-dessus. Les variantes mineures (mêmes séances en 8 vs 12
semaines) ne sont pas dupliquées — on garde un représentant par objectif.
