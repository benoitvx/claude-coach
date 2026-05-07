#!/usr/bin/env bash
# Installe une tâche launchd qui lance `strava-connect sync --full` chaque jour.
#
# - Schedule par défaut : tous les jours à 12:30 (heure locale).
#   Le quota lecture Strava (1000 req/jour) reset à 00:00 UTC = 02:00 Paris.
#   Une exécution à 12:30 garantit que le Mac est probablement éveillé.
# - Logs dans ~/Library/Logs/strava-connect/sync.{out,err}.log
# - Idempotent : relancer le script remplace l'agent existant.
#
# Personnalisation : édite ensuite `~/Library/LaunchAgents/com.strava-connect.sync.plist`
# (clés StartCalendarInterval > Hour/Minute) puis relance ce script.

set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
  echo "Ce script cible macOS (launchd). Sur Linux : utilise cron / systemd." >&2
  exit 1
fi

LABEL="com.strava-connect.sync"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/strava-connect"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" ]]; then
  echo "Erreur : 'uv' introuvable dans le PATH." >&2
  echo "  Installe-le : curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

HOUR=12
MINUTE=30

mkdir -p "$LOG_DIR" "$(dirname "$PLIST_PATH")"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UV_BIN</string>
    <string>run</string>
    <string>strava-connect</string>
    <string>sync</string>
    <string>--full</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/sync.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/sync.err.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

# Recharge l'agent (idempotent).
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✓ Installé : $PLIST_PATH"
echo "✓ Schedule : tous les jours à $(printf '%02d:%02d' $HOUR $MINUTE) (locale)"
echo "✓ Logs    : $LOG_DIR/sync.{out,err}.log"
echo
echo "Pour vérifier que l'agent est chargé :"
echo "  launchctl list | grep strava"
echo
echo "Pour le désinstaller :"
echo "  launchctl unload \"$PLIST_PATH\" && rm \"$PLIST_PATH\""
echo
echo "Pour lancer une exécution manuelle (test immédiat) :"
echo "  launchctl start $LABEL"
