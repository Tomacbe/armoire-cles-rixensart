# Dépannage

Commande de base : `journalctl -u keybox -f` (lignes `[-> Arduino]` envoyées, `[Arduino OK]` reçues).

| Symptôme | Cause probable | Solution |
|---|---|---|
| Pastille « Arduino déconnecté » | Port série renommé (`ttyUSB0` → `ttyUSB1`) après un rebranchement | Utiliser le nom fixe `/dev/serial/by-id/…` (`KEYBOX_SERIAL_PORT`, voir installation) |
| Adaptateur CH340 qui disparaît aussitôt branché | `brltty` (Ubuntu) s'empare du port | `sudo apt remove brltty`, rebrancher |
| Téléversement : `timeout`, `getsync() failed`, `unable to open port` | Port occupé (service `keybox` ou moniteur série de l'IDE) | `sudo systemctl stop keybox`, fermer le moniteur série (`sudo fuser -v /dev/ttyUSB0`) |
| Téléversement impossible avec le lecteur branché | Lecteur câblé sur les broches 0/1 (RX0/TX0) | Vert sur **D2**, blanc sur **D3** |
| Aucun badge lu, le lecteur ne bipe pas | Lecteur non alimenté (0 A) | Vérifier rouge sur +12 V, noir sur 0 V ; le lecteur doit s'allumer et biper au passage d'un badge |
| Le lecteur bipe mais aucune trame | Pas de masse commune | Relier le noir du lecteur au GND de l'Arduino |
| Trames de 26 bits au lieu de 34 | Fil gris en position WG26 | Changer la position du fil gris (lecteur hors tension) |
| Rouge et vert inversés sur le ruban | Ordre des couleurs | `COLOR_ORDER` `RGB` ↔ `GRB` ; au démarrage le ruban doit afficher rouge puis vert puis bleu |
| Une clé allume la LED d'à côté | Correspondance clé → LED | Bouton « Repérer », adapter `LED_OF_KEY[]` |
| LED qui ne suivent pas le serveur | Sketch sans accusé de réception / mauvaise version | Configuration › Clés › Test des LED ; vérifier `Arduino pret - sketch armoire v5` au démarrage |
| État de porte inversé | Type de capteur reed | `DOOR_OPEN_LEVEL` `HIGH` ↔ `LOW` |
| Relais actif au repos | Module actif à l'état haut | `RELAY_ACTIVE HIGH` ou cavalier du module |
| Écran noir sur la sortie VGA | Sortie non activée par X | `DISPLAY=:0 xrandr` puis `xrandr --output DP-3 --auto --primary` (nom à adapter), à mettre dans `openbox-autostart` |
| Mot de passe demandé au démarrage | Connexion automatique absente | `getty-autologin.conf` (pas de gestionnaire graphique sur ce système) |
| Pas de son d'alerte | Politique d'autolecture de Chromium | Option `--autoplay-policy=no-user-gesture-required` dans `kiosk.sh` |
| Pas de son (haut-parleur de l'écran relié à la sortie casque) | Aucun serveur de son, sortie muette ou mauvaise sortie par défaut | Voir « Son » ci-dessous ; tester avec Configuration › Réglages › Tester le son |
| Journal de l'écran d'accueil vide alors que les événements sont dans Configuration › Journal | Horloge du mini-PC remise à zéro (pile du BIOS) : nouveaux événements datés dans le passé | Corrigé : l'écran trie par ordre d'enregistrement. Remplacer la pile CR2032, puis `timedatectl` (voir « Horloge » ci-dessous) |
| L'écran ne se met pas en veille | `xset -dpms` encore dans `kiosk.sh`, ou délai à 0 | Reprendre `kiosk.sh` du dépôt ; Configuration › Réglages › Veille de l'écran |
| Écran vertical mais le toucher ne tombe pas au bon endroit | `xinput` absent, ou écran tactile non géré par libinput | `sudo apt install xinput`, puis Réglages › Enregistrer ; vérifier `DISPLAY=:0 xinput list` |
| Orientation sans effet | Sortie vidéo non trouvée | Forcer la sortie : `Environment=KEYBOX_OUTPUT=DP-3` dans un fichier `/etc/systemd/system/keybox.service.d/` |
| L'écran ne se rallume pas au badge | Le service n'accède pas à l'affichage X | Le service doit tourner sous le même utilisateur que la session graphique ; sinon `KEYBOX_DISPLAY` / `KEYBOX_XAUTHORITY` |

## Son

```bash
aplay -l                                   # cartes son : repérer « Analog » / « Headphones »
sudo apt install -y pipewire pipewire-pulse wireplumber alsa-utils pulseaudio-utils
sudo reboot                                # le serveur de son démarre avec la session
pactl list short sinks                     # sorties disponibles
pactl set-default-sink <nom …analog-stereo>
pactl set-sink-mute @DEFAULT_SINK@ 0 && pactl set-sink-volume @DEFAULT_SINK@ 80%
```

Si la sortie analogique reste muette : `alsamixer` (F6 pour choisir la carte), monter **Master**,
**Headphone** et **Speaker**, touche `M` pour enlever la sourdine (`MM` → `00`), puis `sudo alsactl store`.
Câble jack branché sur la sortie **casque** (vert) du mini-PC et sur l'entrée **audio** de l'écran.

## Horloge

```bash
timedatectl                                # « System clock synchronized: yes » attendu
sudo timedatectl set-ntp true              # synchronisation automatique (internet requis)
sudo timedatectl set-ntp false && sudo timedatectl set-time "2026-11-03 21:00:00"   # sans internet
```

Une pile du BIOS (CR2032) usée remet l'horloge à zéro à chaque coupure de courant : la remplacer.

