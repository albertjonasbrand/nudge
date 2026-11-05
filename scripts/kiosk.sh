#!/usr/bin/env bash
# Started by xinit from nudge-kiosk.service: bare X, no window manager chrome,
# Chromium fullscreen on the 5" panel pointed at the local service.
xset s off -dpms
xset s noblank
unclutter -idle 0.5 -root &
# wait for the service
for i in $(seq 1 60); do curl -sf localhost:8765/state >/dev/null && break; sleep 1; done
exec chromium-browser --kiosk --noerrdialogs --disable-infobars --no-first-run \
  --disable-translate --disable-features=TranslateUI --overscroll-history-navigation=0 \
  --touch-events=enabled --window-size=800,480 --window-position=0,0 \
  --check-for-update-interval=31536000 --autoplay-policy=no-user-gesture-required \
  http://localhost:8765/
