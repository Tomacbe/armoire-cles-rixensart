import json
import os
import threading
import time
import serial

import armoire

SERIAL_PORT = os.environ.get("KEYBOX_SERIAL_PORT", "/dev/ttyUSB0")
BAUD_RATE = 115200

_ser = None
_write_lock = threading.Lock()
_pending = {}     # commandes pas encore confirmées par l'Arduino : groupe -> [obj, heure, essais]
# leds/leds_off et unlock/lock se remplacent : on ne renvoie jamais une commande devenue obsolète
_GROUP = {"leds": "leds", "leds_off": "leds", "unlock": "door", "lock": "door"}


def _write(obj):
    _ser.write((json.dumps(obj, separators=(",", ":")) + "\n").encode())


def send_command(obj):
    """Envoie une commande JSON (une ligne) à l'Arduino ; renvoyée si aucun accusé de réception."""
    global _pending
    with _write_lock:
        if _ser is None:
            return
        _write(obj)
        cmd = obj.get("cmd")
        _pending[_GROUP.get(cmd, cmd)] = [obj, time.time(), 1]
        print(f"[-> Arduino] {obj}")


def _acknowledged(cmd):
    with _write_lock:
        group = _GROUP.get(cmd, cmd)
        if group in _pending and _pending[group][0].get("cmd") == cmd:
            del _pending[group]


def _retry_unacknowledged():
    """Un caractère peut se perdre pendant la mise à jour des LED (FastLED coupe les interruptions) : on renvoie."""
    with _write_lock:
        if _ser is None:
            _pending.clear()
            return
        for cmd, (obj, t, tries) in list(_pending.items()):
            if time.time() - t < 0.8:
                continue
            if tries >= 3:
                print(f"[Arduino] pas d'accusé de réception pour {obj} après 3 essais")
                del _pending[cmd]
                continue
            _write(obj)
            _pending[cmd] = [obj, time.time(), tries + 1]
            print(f"[-> Arduino] renvoi {obj} (essai {tries + 1})")


def handle_line(app, line):
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        print(f"[Erreur JSON] Ligne invalide reçue : {line}")
        return
    event = data.get("event")
    with app.app_context():  # contexte neuf à chaque trame : données toujours à jour
        try:
            if event == "badge":
                print(f"[Badge scanné] UID: {data.get('uid')}")
                armoire.handle_badge(data.get("uid"))
            elif event == "key_change":
                print(f"[Changement Clé] Pin {data.get('pin')} -> {data.get('status')}")
                armoire.handle_key_change(data.get("pin"), data.get("status"))
            elif event == "ack":
                # accusé de réception envoyé par armoire_leds.h : prouve que l'Arduino lit les commandes
                armoire.STATE["last_ack"] = {"cmd": data.get("cmd"), "t": time.time()}
                _acknowledged(data.get("cmd"))
                print(f"[Arduino OK] commande {data.get('cmd')} reçue")
            elif event == "door":
                print(f"[Porte] {data.get('status')}")
                armoire.handle_door(data.get("status"))
            else:
                print(f"[Arduino] trame ignorée : {line}")
        except Exception as e:
            armoire.db.session.rollback()
            print(f"[Erreur traitement] {e!r} sur {line}")


def process_serial_data(app):
    global _ser
    print(f"[*] Démarrage de l'écoute du port série {SERIAL_PORT}...")
    armoire.set_writer(send_command)
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            with _write_lock:
                _ser = ser
            armoire.set_serial(True, SERIAL_PORT)
            print(f"[*] Arduino connecté sur {SERIAL_PORT}")
            while True:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                # Ignorer les messages textuels de démarrage de l'Arduino
                if not line.startswith("{"):
                    print(f"[Arduino Info] {line}")
                    continue
                handle_line(app, line)
        except (serial.SerialException, OSError) as e:
            print(f"[Erreur Série] Connexion perdue ({e}), nouvelle tentative dans 5 secondes...")
        with _write_lock:
            # fermer l'ancien port : sinon Linux garde ttyUSB0 réservé et l'Arduino rebranché devient ttyUSB1
            try:
                if _ser is not None:
                    _ser.close()
            except Exception:
                pass
            _ser = None
        armoire.set_serial(False, SERIAL_PORT)
        time.sleep(5)


def session_timer(app):
    n = 0
    while True:
        time.sleep(0.25)
        n += 1
        try:
            _retry_unacknowledged()
            if n % 4 == 0:
                with app.app_context():
                    armoire.tick()
        except Exception as e:
            print(f"[Erreur minuterie] {e!r}")


def start_serial_listener(app):
    threading.Thread(target=process_serial_data, args=(app,), daemon=True).start()
    threading.Thread(target=session_timer, args=(app,), daemon=True).start()
