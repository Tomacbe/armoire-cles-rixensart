"""
Mise en veille de l'écran (DPMS de X11) : l'écran s'éteint après N minutes sans toucher,
se rallume au toucher (géré par X) ou quand le serveur le demande (badge, porte, clé, alerte).

Le service keybox tourne sous le même utilisateur que la session graphique : il pilote X avec
`xset` sur l'affichage :0 (variables KEYBOX_DISPLAY et KEYBOX_XAUTHORITY pour changer).
"""
import os
import shutil
import subprocess
import threading
import time

DISPLAY = os.environ.get("KEYBOX_DISPLAY", ":0")
XAUTHORITY = os.environ.get("KEYBOX_XAUTHORITY", os.path.expanduser("~/.Xauthority"))

_lock = threading.Lock()
_last_wake = 0.0
_sleep_min = None          # dernier délai appliqué à X


def _xset(*args):
    exe = shutil.which("xset")
    if not exe:
        return False
    env = dict(os.environ, DISPLAY=DISPLAY, XAUTHORITY=XAUTHORITY)
    try:
        r = subprocess.run([exe, *args], env=env, capture_output=True, timeout=3)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _apply_timeout(minutes):
    """Règle le délai de veille de X (0 = jamais)."""
    global _sleep_min
    if minutes <= 0:
        ok = _xset("-dpms")
    else:
        s = str(int(minutes) * 60)
        ok = _xset("+dpms") and _xset("dpms", s, s, s)
    if ok:
        _sleep_min = minutes
    return ok


def set_timeout(minutes):
    threading.Thread(target=_apply_timeout, args=(minutes,), daemon=True).start()


def _wake(minutes):
    if _sleep_min != minutes:
        _apply_timeout(minutes)
    _xset("dpms", "force", "on")
    _xset("s", "reset")          # remet à zéro le compteur d'inactivité de X


def wake(minutes=None):
    """Rallume l'écran (sans bloquer l'appelant). Limité à un appel par seconde."""
    global _last_wake
    if minutes is None:
        from armoire import get_settings
        minutes = get_settings()["screen_sleep_min"]
    with _lock:
        if time.time() - _last_wake < 1:
            return
        _last_wake = time.time()
    threading.Thread(target=_wake, args=(minutes,), daemon=True).start()


def start(get_minutes):
    """Au démarrage du serveur : applique le délai dès que la session graphique est prête."""
    def loop():
        for _ in range(120):                 # jusqu'à 10 minutes d'attente de X
            if _apply_timeout(get_minutes()):
                print(f"[Écran] veille après {get_minutes()} min (0 = jamais)")
                return
            time.sleep(5)
        print("[Écran] affichage X introuvable : veille non réglée")
    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------------------- orientation (horizontal / vertical)
# Matrice appliquée aux écrans tactiles pour que le toucher suive la rotation de l'image
_TOUCH_MATRIX = {
    "normal":   "1 0 0 0 1 0 0 0 1",
    "left":     "0 -1 1 1 0 0 0 0 1",
    "right":    "0 1 0 -1 0 1 0 0 1",
    "inverted": "-1 0 1 0 -1 1 0 0 1",
}


def _run(args):
    exe = shutil.which(args[0])
    if not exe:
        return None
    env = dict(os.environ, DISPLAY=DISPLAY, XAUTHORITY=XAUTHORITY)
    try:
        r = subprocess.run([exe, *args[1:]], env=env, capture_output=True, text=True, timeout=5)
        return r if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _output_name():
    """Sortie vidéo utilisée : variable KEYBOX_OUTPUT, sinon la sortie principale, sinon la première connectée."""
    if os.environ.get("KEYBOX_OUTPUT"):
        return os.environ["KEYBOX_OUTPUT"]
    r = _run(["xrandr", "--query"])
    if not r:
        return None
    connected = [l.split()[0] for l in r.stdout.splitlines() if " connected" in l]
    primary = [l.split()[0] for l in r.stdout.splitlines() if " connected primary" in l]
    return (primary or connected or [None])[0]


def _touch_devices():
    """Écrans tactiles vus par X (pilote libinput : propriété « libinput Calibration Matrix »)."""
    r = _run(["xinput", "list", "--id-only"])
    if not r:
        return []
    out = []
    for dev in r.stdout.split():
        props = _run(["xinput", "list-props", dev])
        if props and "libinput Calibration Matrix" in props.stdout:
            out.append(dev)
    return out


def apply_rotation(rotation):
    """Tourne l'image (xrandr) et le toucher (xinput). Renvoie ce qui a été fait, pour l'affichage."""
    if rotation not in _TOUCH_MATRIX:
        rotation = "normal"
    output = _output_name()
    if not output:
        return {"ok": False, "error": "Affichage X introuvable (xrandr)"}
    if not _run(["xrandr", "--output", output, "--rotate", rotation]):
        return {"ok": False, "error": f"xrandr n'a pas pu tourner la sortie {output}"}
    if not shutil.which("xinput"):
        return {"ok": True, "output": output, "touch": 0,
                "warning": "xinput absent (sudo apt install xinput) : le toucher ne suit pas la rotation"}
    devices = _touch_devices()
    for dev in devices:
        _run(["xinput", "set-prop", dev, "Coordinate Transformation Matrix", *_TOUCH_MATRIX[rotation].split()])
    return {"ok": True, "output": output, "touch": len(devices)}


def set_rotation(rotation):
    threading.Thread(target=apply_rotation, args=(rotation,), daemon=True).start()
