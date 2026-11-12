#!/usr/bin/env bash
# Started by xinit from nudge-kiosk.service: bare X, no window manager,
# a fullscreen WebKit window on the 5" panel pointed at the local service.
xset s off -dpms
xset s noblank
unclutter -idle 0.5 -root &
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# wait for the service
for i in $(seq 1 60); do curl -sf localhost:8765/state >/dev/null && break; sleep 1; done
exec python3 "$ROOT/scripts/kiosk_webview.py" http://localhost:8765/
