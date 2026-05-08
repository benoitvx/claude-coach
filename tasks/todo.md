# Tâche en cours

## Rename projet : strava-connect → claude-coach + README

### Plan

- [x] `git mv src/strava_connect → src/claude_coach`
- [x] `sed -i` bulk : `strava_connect` → `claude_coach`, `strava-connect` → `claude-coach` (30+ fichiers : src, tests, docs, agent, scripts)
- [x] `pyproject.toml` : project name, scripts entry, packages, description, readme
- [x] `scripts/install-launchd-sync.sh` : `LABEL=com.claude-coach.sync`, `LOG_DIR=~/Library/Logs/claude-coach`, message d'aide `grep claude-coach`
- [x] Créer `README.md` (description, quickstart, surface CLI, subagent coach, dev)
- [x] `make install` (rebuild venv) puis `make validate` (194 tests verts)
- [x] Commit + push

### À faire côté utilisateur après pull

1. **Désinstaller l'ancien launchd** (label `com.strava-connect.sync` toujours en place mais pointe sur l'ex-CLI) :
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.strava-connect.sync.plist
   rm ~/Library/LaunchAgents/com.strava-connect.sync.plist
   ```
2. **Réinstaller le launchd** avec le nouveau label :
   ```bash
   SYNC_HOUR=10 SYNC_MINUTE=0 bash scripts/install-launchd-sync.sh
   ```
3. **(Optionnel)** Renommer le repo GitHub : `gh repo rename claude-coach -R benoitvx/strava-connect`, puis `git remote set-url origin git@github.com:benoitvx/claude-coach.git`.
4. **(Optionnel)** Renommer le dossier de travail local : `mv ~/Dev/strava-connect ~/Dev/claude-coach`.

### Conservé tel quel (volontaire)

- `STRAVA_DB_PATH`, `STRAVA_TOKEN_FILE`, `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` — réfèrent à la **source** Strava, pas au projet.
- `data/strava.db`, `data/tokens.json`, `data/config.json` — fichiers de données Strava.
- Toutes les mentions textuelles de "Strava" (l'API / la source) dans la doc.

### Résultat

Rename livré en un commit (`refactor`). 194 tests verts. La doc projet et le
subagent coach utilisent désormais `claude-coach`. Le repo GitHub garde son
nom (renommage manuel à la discrétion de l'utilisateur).
