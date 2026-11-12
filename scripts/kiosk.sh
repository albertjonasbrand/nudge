#!/usr/bin/env bash
# Started by xinit from nudge-kiosk.service: bare X, no window manager,
# a fullscreen WebKit window on the 5" panel pointed at the local service.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# If X came up while the panel was between signals (it drops out for a second on
# every X restart) it has no video mode and shows nothing. Bail out; systemd
# restarts us 3 s later and the panel is back by then.
for i in 1 2 3 4 5; do
  if xrandr 2>/dev/null | grep -qE "^\s+[0-9]+x[0-9]+"; then break; fi
  [ "$i" = 5 ] && { echo "kiosk: display has no modes, restarting X" >&2; exit 1; }
  sleep 1
done
xrandr --output "$(xrandr | awk '/ connected/{print $1; exit}')" --auto 2>/dev/null

xset s off -dpms
xset s noblank
unclutter -idle 0.5 -root &
# wait for the service
for i in $(seq 1 60); do curl -sf localhost:8765/state >/dev/null && break; sleep 1; done
exec python3 "$ROOT/scripts/kiosk_webview.py" http://localhost:8765/
