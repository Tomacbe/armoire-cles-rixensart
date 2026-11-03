#!/bin/bash
# ~/kiosk.sh — écran de l'armoire en plein écran (Chromium), relancé s'il se ferme
# Pas d'économiseur d'écran X ; la veille (DPMS) est réglée par le serveur :
# Configuration › Réglages › Veille de l'écran (5 min par défaut)
xset s off
xset s noblank
xset +dpms
xset dpms 300 300 300
until curl -s http://127.0.0.1:5000/ > /dev/null; do sleep 1; done
# orientation (horizontal / vertical) et veille réglées dans Configuration › Réglages
curl -s -X POST http://127.0.0.1:5000/api/screen/apply > /dev/null
sleep 1
BROWSER=$(command -v chromium || command -v chromium-browser || echo /snap/bin/chromium)
while true; do
  "$BROWSER" --kiosk --disable-pinch --overscroll-history-navigation=0 \
    --noerrdialogs --disable-infobars --incognito --password-store=basic \
    --autoplay-policy=no-user-gesture-required \
    --disable-session-crashed-bubble --check-for-update-interval=31536000 \
    http://127.0.0.1:5000/
  sleep 2
done
