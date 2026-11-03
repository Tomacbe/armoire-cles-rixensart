#!/bin/bash
# Diagnostic du son du mini-PC : est-ce que quelque chose sort de la carte son ?
# Usage : bash ~/diag-son.sh        (brancher si possible un casque / des écouteurs dans la prise jack)

echo "=== 1. Carte son vue par le matériel (PCI) ==="
lspci 2>/dev/null | grep -i -E "audio|sound" || echo "AUCUNE carte son PCI : vérifier dans le BIOS que « HD Audio » est activé (la pile du BIOS a pu remettre les réglages à zéro)"

echo; echo "=== 2. Cartes son vues par Linux (ALSA) ==="
aplay -l 2>&1 || echo "aplay absent : sudo apt install alsa-utils"

echo; echo "=== 3. Écran : sortie vidéo utilisée ==="
DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority xrandr 2>/dev/null | grep " connected" || echo "(xrandr indisponible)"

echo; echo "=== 4. Serveur de son ==="
if command -v pactl >/dev/null && pactl info >/dev/null 2>&1; then
  pactl info | grep -E "Server Name|Default Sink"
  echo "Sorties :"; pactl list short sinks
else
  echo "Pas de serveur de son (pipewire-pulse) : Chromium ne peut jouer AUCUN son"
fi

echo; echo "=== 5. Volumes / sourdines (carte par carte) ==="
for c in $(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]*\):.*/\1/p' | sort -u); do
  echo "--- carte $c"
  amixer -c "$c" scontents 2>/dev/null | grep -E "Simple mixer|Playback.*\[(on|off)\]|Auto-Mute" | head -20
done

echo; echo "=== 6. Déblocage : volumes à 80 %, sourdine retirée ==="
for c in $(aplay -l 2>/dev/null | sed -n 's/^card \([0-9]*\):.*/\1/p' | sort -u); do
  for ctl in Master Headphone Speaker PCM Front "Line Out"; do
    amixer -c "$c" -q sset "$ctl" 80% unmute 2>/dev/null
  done
  amixer -c "$c" -q sset "Auto-Mute Mode" Disabled 2>/dev/null
done
command -v pactl >/dev/null && pactl set-sink-mute @DEFAULT_SINK@ 0 2>/dev/null && pactl set-sink-volume @DEFAULT_SINK@ 80% 2>/dev/null
echo "fait"

echo; echo "=== 7. Test direct de chaque sortie (voix « Front Left / Front Right ») ==="
aplay -l 2>/dev/null | sed -n 's/^card \([0-9]*\): [^[]*\[\([^]]*\)\], device \([0-9]*\): [^[]*\[\([^]]*\)\].*/\1 \3 \2 — \4/p' |
while read -r card dev name; do
  echo; echo ">>> carte $card, sortie $dev : $name"
  echo "    Écoutez maintenant (écran ET casque)…"
  timeout 8 speaker-test -D "plughw:$card,$dev" -c 2 -t wav -l 1 >/dev/null 2>&1
  case $? in
    0)   echo "    → son envoyé sans erreur sur cette sortie" ;;
    124) echo "    → son envoyé (test interrompu au bout de 8 s)" ;;
    *)   echo "    → carte occupée, je réessaie par le serveur de son…"
         command -v paplay >/dev/null && [ -f /usr/share/sounds/alsa/Front_Center.wav ] && \
           timeout 8 paplay /usr/share/sounds/alsa/Front_Center.wav && echo "    → son envoyé par le serveur de son (sortie par défaut)" ;;
  esac
  sleep 1
done

echo; echo "=== Fin. Copiez tout ce texte pour le diagnostic. ==="
