# Installation

Mini-PC sous Ubuntu (testé sur 26.04), Arduino Mega 2560 relié en USB. Les exemples utilisent le compte
`armoire` (compte local du mini-PC) et le dossier `~/smart_key_box` : à adapter.

## 1. Serveur Flask

```bash
sudo apt install -y python3-venv git curl
git clone <url-du-dépôt> ~/armoire-cles-rixensart
mkdir -p ~/smart_key_box && cp -r ~/armoire-cles-rixensart/serveur/* ~/smart_key_box/
cd ~/smart_key_box
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout $USER          # accès au port série (se reconnecter ensuite)
```

Au premier démarrage, la base `instance/keybox.db` est créée avec 30 emplacements (broches 20 à 49).

### Service systemd

```bash
sudo cp ~/armoire-cles-rixensart/deploiement/keybox.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/keybox.service.d

# port série : nom fixe de l'adaptateur (voir « ls /dev/serial/by-id/ »)
sudo cp ~/armoire-cles-rixensart/deploiement/keybox-serial.conf.example /etc/systemd/system/keybox.service.d/serial.conf

# code admin des pages de configuration
sudo cp ~/armoire-cles-rixensart/deploiement/keybox-admin.conf.example /etc/systemd/system/keybox.service.d/admin.conf
sudo nano /etc/systemd/system/keybox.service.d/admin.conf      # remplacer ChangerCeCode
sudo chmod 600 /etc/systemd/system/keybox.service.d/admin.conf

sudo systemctl daemon-reload
sudo systemctl enable --now keybox
journalctl -u keybox -f                 # suivi en direct
```

Variables d'environnement reconnues :

| Variable | Rôle | Défaut |
|---|---|---|
| `KEYBOX_SERIAL_PORT` | Port série de l'Arduino | `/dev/ttyUSB0` |
| `KEYBOX_ADMIN_PASSWORD` | Code des pages de configuration (vide = accès libre) | — |
| `KEYBOX_SESSION_S` | Durée de session par défaut (modifiable ensuite dans Réglages) | `120` |
| `KEYBOX_SECRET` | Clé des cookies de session (sinon générée dans `instance/secret_key`) | — |

L'écran est accessible sur `http://<ip-du-mini-pc>:5000/`, la configuration via le bouton **Configuration**.

## 2. Écran kiosque au démarrage

Pour un Ubuntu **sans bureau** (`systemctl get-default` = `multi-user.target`, ou `graphical.target` sans
gestionnaire de connexion) : X minimal + Openbox + Chromium.

```bash
sudo apt install -y --no-install-recommends xorg xinit openbox unclutter x11-xserver-utils curl
sudo snap install chromium

# connexion automatique sur tty1
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo cp ~/armoire-cles-rixensart/deploiement/getty-autologin.conf /etc/systemd/system/getty@tty1.service.d/autologin.conf

# interface graphique au login, Openbox, kiosque
cat ~/armoire-cles-rixensart/deploiement/bash_profile.snippet >> ~/.bash_profile
cp ~/armoire-cles-rixensart/deploiement/xinitrc ~/.xinitrc
mkdir -p ~/.config/openbox
cp ~/armoire-cles-rixensart/deploiement/openbox-autostart ~/.config/openbox/autostart
cp ~/armoire-cles-rixensart/deploiement/kiosk.sh ~/kiosk.sh && chmod +x ~/kiosk.sh
sudo reboot
```

- **Sortie vidéo** : `DISPLAY=:0 xrandr` liste les sorties. Sur le mini-PC utilisé, la prise VGA est vue comme
  `DP-3` ; adapter la ligne `xrandr --output …` de `openbox-autostart`.
- **Écran tactile** : aucun réglage en général. Le curseur est masqué (`startx -- -nocursor`) et un clavier
  s'affiche à l'écran dans les pages de configuration.
- **Son des alertes** : autorisé par `--autoplay-policy=no-user-gesture-required` dans `kiosk.sh`.

## 3. Arduino

1. Arduino IDE : installer la bibliothèque **FastLED** (Outils › Gérer les bibliothèques).
2. Ouvrir `firmware/armoire_cles/armoire_cles.ino`, carte **Arduino Mega or Mega 2560**, processeur **ATmega2560**.
3. Vérifier les réglages en tête du sketch :

| Constante | Rôle | Défaut |
|---|---|---|
| `COLOR_ORDER` | Ordre des couleurs du ruban (si rouge/vert inversés : `RGB` ↔ `GRB`) | `RGB` |
| `LED_OF_KEY[]` | LED (0-49) de chaque clé (1-30) | 0 → 29 |
| `RELAY_ACTIVE` | Niveau qui active le relais | `LOW` |
| `DOOR_OPEN_LEVEL` | Niveau lu porte ouverte (reed) | `HIGH` |
| `RELOCK_ON_OPEN` | Réalimenter l'aimant dès l'ouverture | `true` |
| `BRIGHTNESS` | Luminosité des LED (0-255) | `50` |

4. **Téléverser** : le port série doit être libre.
   - Depuis le mini-PC : `sudo systemctl stop keybox`, téléverser, puis `sudo systemctl start keybox`.
   - Fermer le moniteur série de l'IDE pendant le téléversement.
5. Vérifier au démarrage, dans `journalctl -u keybox -f`, la ligne `Arduino pret - sketch armoire v5 …`.
   Le ruban affiche 1 s rouge, 1 s vert, 1 s bleu (contrôle de l'ordre des couleurs).

Pour tester le lecteur seul : `firmware/test_wiegand/test_wiegand.ino` (moniteur série 115200).

## 4. Mise en service

1. **Configuration › Clés** : nommer chaque clé utilisée et indiquer son bâtiment (une clé sans nom est
   considérée comme non paramétrée : pas de LED, pas de couleur à l'écran).
2. **Configuration › Clés › Test des LED** : « Afficher le statut », puis « Repérer » sur quelques clés pour
   vérifier que chaque LED est en face de la bonne clé.
3. **Configuration › Badges** : ajouter les personnes (« Scanner le badge » ou import CSV/Excel).
4. **Configuration › Réglages** : durée d'ouverture du relais, durée de session, délais d'alerte ;
   « Tester l'ouverture ».

## Mise à jour

```bash
cd ~/armoire-cles-rixensart && git pull
cp -r serveur/*.py serveur/static ~/smart_key_box/
sudo systemctl restart keybox && pkill chrome      # le kiosque se relance seul
```

La base et les réglages (`instance/`) ne sont pas touchés.
