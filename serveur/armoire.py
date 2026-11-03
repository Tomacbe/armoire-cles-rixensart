"""
Logique de l'armoire : session après badge, emprunts liés à la personne, LED, état pour l'écran.

Scénario :
  1. badge autorisé → session ouverte (SESSION_S secondes), {"cmd":"unlock"} et LED allumées :
       vert  = clé présente
       rouge = clé sortie (par quelqu'un d'autre, ou prise pendant cette session)
       jaune clignotant = clé que CETTE personne avait prise lors d'un passage précédent → à remettre
  2. chaque clé retirée pendant la session est liée à la personne (table key_loan) ;
     chaque clé remise clôture l'emprunt en cours ; les LED sont mises à jour aussitôt
  3. fin de session : porte refermée, bouton « Terminer la session », ou délai écoulé
     → {"cmd":"leds_off"} et {"cmd":"lock"}

Intégration dans app.py :
    from armoire import armoire_bp
    app.register_blueprint(armoire_bp)
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify
from models import db, User, KeySlot, EventLog
import screen

armoire_bp = Blueprint("armoire", __name__)

EXTEND_S = 30                                                    # prolongation à chaque mouvement de clé
UNKNOWN = "Non identifié"

# ---------------------------------------------------------------------- réglages (onglet Réglages de la configuration)
SETTINGS_FILE = Path(__file__).resolve().parent / "instance" / "armoire_settings.json"
SETTINGS_SPEC = {
    # clé: (défaut, minimum, maximum)
    "unlock_s": (5, 1, 60),          # temporisation du relais : durée d'ouverture de l'électro-aimant
    "session_s": (int(os.environ.get("KEYBOX_SESSION_S", "120")), 30, 1800),  # délai de session après le badge
    "door_alert_s": (120, 10, 3600),  # alerte si la porte reste ouverte plus longtemps pendant une session
    "door_grace_s": (15, 5, 600),     # alerte si la porte est ouverte sans session (forcée, session finie)
    "screen_sleep_min": (5, 0, 60),   # mise en veille de l'écran après N minutes sans toucher (0 = jamais)
}
CHOICE_SETTINGS = {
    # clé: (défaut, valeurs possibles)
    "screen_rotation": ("normal", ("normal", "left", "right", "inverted")),   # orientation de l'écran
}
TEXT_SETTINGS = {
    # clé: (défaut, longueur maxi)
    "cabinet_name": ("Armoire 01", 40),   # nom affiché sur l'écran d'accueil
}


def get_settings():
    data = {}
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        pass
    out = {}
    for k, (default, lo, hi) in SETTINGS_SPEC.items():
        try:
            out[k] = min(hi, max(lo, int(data.get(k, default))))
        except (TypeError, ValueError):
            out[k] = default
    for k, (default, maxlen) in TEXT_SETTINGS.items():
        v = str(data.get(k) or "").strip()[:maxlen]
        out[k] = v or default
    for k, (default, choices) in CHOICE_SETTINGS.items():
        out[k] = data.get(k) if data.get(k) in choices else default
    return out


def save_settings(values):
    current = get_settings()
    for k, (default, lo, hi) in SETTINGS_SPEC.items():
        if k in values:
            v = int(values[k])
            if not lo <= v <= hi:
                raise ValueError(f"{k} doit être entre {lo} et {hi}")
            current[k] = v
    for k, (default, maxlen) in TEXT_SETTINGS.items():
        if k in values:
            v = " ".join(str(values[k] or "").split())
            if not v:
                raise ValueError("Le nom de l'armoire ne peut pas être vide")
            if len(v) > maxlen:
                raise ValueError(f"Nom de l'armoire : {maxlen} caractères maximum")
            current[k] = v
    for k, (default, choices) in CHOICE_SETTINGS.items():
        if k in values:
            if values[k] not in choices:
                raise ValueError(f"{k} : valeur inconnue")
            current[k] = values[k]
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(current, indent=1), encoding="utf-8")
    return current


class KeyLoan(db.Model):
    """Un emprunt : qui a sorti quelle clé, et quand elle est revenue."""
    __tablename__ = "key_loan"
    id = db.Column(db.Integer, primary_key=True)
    key_number = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=True)
    user_name = db.Column(db.String(120), nullable=False)
    taken_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    returned_at = db.Column(db.DateTime, nullable=True, index=True)
    returned_by = db.Column(db.String(120), nullable=True)


class ConfigAccess(db.Model):
    """Personnes autorisées à ouvrir la configuration avec leur badge (en plus du code maître)."""
    __tablename__ = "config_access"
    user_id = db.Column(db.Integer, primary_key=True)


def has_config_access(user):
    return bool(user and user.is_active and db.session.get(ConfigAccess, user.id))


class KeyMeta(db.Model):
    """Informations de configuration d'une clé en plus de KeySlot.label (son nom) : le bâtiment."""
    __tablename__ = "key_meta"
    key_number = db.Column(db.Integer, primary_key=True)
    building = db.Column(db.String(120), nullable=True)


@armoire_bp.record_once
def _create_table(state):
    with state.app.app_context():
        KeyLoan.__table__.create(db.engine, checkfirst=True)
        KeyMeta.__table__.create(db.engine, checkfirst=True)
        ConfigAccess.__table__.create(db.engine, checkfirst=True)


def default_label(n):
    return f"Clé n°{n}"


def buildings():
    return {m.key_number: m.building for m in KeyMeta.query.all() if m.building}


def key_desc(slot, building=None):
    """« Clé #05 Chaufferie (Bâtiment B) » — sans répéter le nom par défaut « Clé n°5 »."""
    n = slot.key_number
    label = (slot.label or "").strip()
    text = f"Clé #{n:02d}"
    if label and label != default_label(n):
        text += f" {label}"
    if building is None:
        m = db.session.get(KeyMeta, n)
        building = m.building if m else None
    if building:
        text += f" ({building})"
    return text


# ---------------------------------------------------------------------- état en mémoire (partagé entre threads)
_lock = threading.RLock()
STATE = {
    "session": None,       # {"user_id","name","uid","started","expires"}
    "door": None,          # {"status": "OPEN"|"CLOSED", "since": epoch} ; None = capteur jamais entendu
    "serial": {"connected": False, "port": None},
    "flash": None,         # {"id", "kind", "text"} message bref pour l'écran
    "last_ack": None,      # dernier accusé de réception de l'Arduino {"cmd", "t"}
    "leds_on": False,      # LED des clés allumées (pour n'envoyer « leds_off » qu'une fois)
    "admin_wait": 0,       # fenêtre « Configuration » ouverte sur la borne : un badge autorisé y donne accès
    "admin_grant": None,   # {"token", "name", "expires"} accès configuration accordé par badge, à usage unique
}
_writer = None             # fonction d'envoi vers l'Arduino, fournie par serial_worker
_flash_id = 0


def set_writer(fn):
    global _writer
    _writer = fn


def send(obj):
    if _writer:
        try:
            _writer(obj)
        except Exception as e:
            print(f"[Envoi Arduino impossible] {e}")


def set_serial(connected, port=None):
    with _lock:
        STATE["serial"] = {"connected": connected, "port": port}


def flash(kind, text):
    global _flash_id
    with _lock:
        _flash_id += 1
        STATE["flash"] = {"id": _flash_id, "kind": kind, "text": text, "t": time.time()}


def log(event_type, details, user_name=None):
    db.session.add(EventLog(event_type=event_type, details=details, user_name=user_name))


def open_loans():
    return {l.key_number: l for l in KeyLoan.query.filter(KeyLoan.returned_at.is_(None)).all()}


# ---------------------------------------------------------------------- LED
def is_configured(slot):
    """Une clé sans nom (« Clé n°X » par défaut) est considérée comme non paramétrée : ni LED, ni couleur."""
    label = (slot.label or "").strip()
    return bool(label) and label != default_label(slot.key_number)


def led_map():
    """Une lettre par clé, dans l'ordre des numéros : G vert, R rouge, Y jaune clignotant, O éteinte."""
    s = STATE["session"]
    loans = open_loans()
    started = datetime.utcfromtimestamp(s["started"]) if s else None
    out = []
    for k in KeySlot.query.order_by(KeySlot.key_number).all():
        if not is_configured(k):
            out.append("O")
            continue
        if k.status == "PRESENT":
            out.append("G")
            continue
        loan = loans.get(k.key_number)
        mine_before = (s and loan and loan.user_name == s["name"] and loan.taken_at < started)
        out.append("Y" if mine_before else "R")
    return "".join(out)


def leds_wanted():
    """LED allumées quand la porte est ouverte. Sans capteur de porte (jamais entendu) : pendant la session."""
    door = STATE["door"]
    if door is None:
        return STATE["session"] is not None
    return door["status"] == "OPEN"


def refresh_leds():
    if leds_wanted():
        send({"cmd": "leds", "map": led_map()})
        STATE["leds_on"] = True
    elif STATE["leds_on"]:
        send({"cmd": "leds_off"})
        STATE["leds_on"] = False


# ---------------------------------------------------------------------- session
def end_session(reason):
    with _lock:
        s = STATE["session"]
        if not s:
            return
        STATE["session"] = None
        log("session_end", f"Session de {s['name']} terminée ({reason})", s["name"])
        db.session.commit()
    send({"cmd": "lock"})
    refresh_leds()   # porte encore ouverte : vert/rouge sans le jaune ; porte fermée : LED éteintes
    print(f"-> Session terminée ({reason})")


def grant_config(user, how):
    """Accès à la configuration par badge : jeton à usage unique, remis uniquement à la borne (127.0.0.1)."""
    import secrets
    with _lock:
        STATE["admin_wait"] = 0
        STATE["admin_grant"] = {"token": secrets.token_urlsafe(24), "name": user.name, "expires": time.time() + 15}
    log("admin_badge", f"Accès à la configuration par badge ({how}) : {user.name}", user.name)
    db.session.commit()
    flash("ok", f"Configuration — {user.name}")
    print(f"-> Configuration ouverte par badge pour {user.name}")


def handle_badge(uid):
    uid = str(uid or "").upper().replace(" ", "").replace(":", "")
    screen.wake()
    user = User.query.filter_by(badge_uid=uid, is_active=True).first()
    # 1) fenêtre « Configuration » ouverte sur la borne : le badge sert à se connecter, pas à ouvrir la porte
    if user and STATE["admin_wait"] > time.time():
        if has_config_access(user):
            grant_config(user, "fenêtre Configuration")
        else:
            log("admin_denied", f"Badge sans accès à la configuration : {user.name}", user.name)
            db.session.commit()
            flash("deny", f"{user.name} : pas d'accès à la configuration")
            send({"cmd": "deny"})
        return
    # 2) badge repassé pendant sa propre session par une personne autorisée : accès à la configuration
    s = STATE["session"]
    if user and s and s["user_id"] == user.id and time.time() - s["started"] > 2 and has_config_access(user):
        grant_config(user, "badge repassé")
        return
    if not user:
        known = User.query.filter_by(badge_uid=uid).first()
        log("badge_unknown", f"Badge inconnu ou désactivé : {uid}")
        db.session.commit()
        flash("deny", "Badge désactivé" if known else "Badge non autorisé")
        send({"cmd": "deny"})
        print("-> Accès refusé")
        return
    now = time.time()
    settings = get_settings()
    with _lock:
        STATE["session"] = {"user_id": user.id, "name": user.name, "uid": uid,
                            "started": now, "expires": now + settings["session_s"]}
        log("badge_scan", f"Badge reconnu : {user.name} (UID: {uid})", user.name)
        db.session.commit()
    send({"cmd": "unlock", "ms": settings["unlock_s"] * 1000})
    refresh_leds()
    print(f"-> Accès autorisé pour {user.name}")


def handle_key_change(pin, status):
    status = "PRESENT" if str(status).upper() in ("PRESENT", "IN", "1", "TRUE") else "ABSENT"
    slot = KeySlot.query.filter_by(pin=pin).first()
    if not slot:
        print(f"[Clé] pin {pin} inconnu")
        return
    if slot.status == status:
        return
    screen.wake()
    slot.status = status
    slot.last_updated = datetime.utcnow()
    if not is_configured(slot):
        # emplacement sans clé paramétrée : on suit l'état sans emprunt ni alerte
        db.session.commit()
        return
    with _lock:
        s = STATE["session"]
        who = s["name"] if s else None
        if s:
            s["expires"] = max(s["expires"], time.time() + EXTEND_S)
    loans = open_loans()
    loan = loans.get(slot.key_number)
    if status == "ABSENT":
        if loan:  # ne devrait pas arriver : on referme l'ancien emprunt
            loan.returned_at = datetime.utcnow()
        db.session.add(KeyLoan(key_number=slot.key_number, user_id=s["user_id"] if s else None,
                               user_name=who or UNKNOWN))
        if not who:
            flash("deny", f"{key_desc(slot)} retirée sans badge")
    else:
        if loan:
            loan.returned_at = datetime.utcnow()
            loan.returned_by = who or UNKNOWN
    desc = key_desc(slot)
    if status == "ABSENT":
        details = f"{desc} retirée par {who}" if who else f"{desc} retirée sans badge"
        user = who
    else:
        owner = loan.user_name if loan else None
        if who and owner and owner != who:
            details = f"{desc} remise par {who} (empruntée par {owner})"
        elif who or owner:
            details = f"{desc} remise par {who or owner}"
        else:
            details = f"{desc} remise"
        user = who or owner
    log("key_change", details, user)
    db.session.commit()
    refresh_leds()
    print(f"[Clé] #{slot.key_number} {status} ({who or 'sans session'})")


def handle_door(status):
    status = "OPEN" if str(status).upper() in ("OPEN", "OUVERTE", "1") else "CLOSED"
    with _lock:
        prev = STATE["door"]
        if prev and prev["status"] == status:
            return
        STATE["door"] = {"status": status, "since": time.time()}
        s = STATE["session"]
    screen.wake()
    if prev is None:
        # premier état reçu (démarrage de l'Arduino) : synchronisation, rien à journaliser
        refresh_leds()
        return
    if status == "OPEN":
        log("door", "Porte ouverte" if s else "Porte ouverte sans badge", s["name"] if s else None)
        db.session.commit()
        refresh_leds()
    else:
        log("door", "Porte refermée", s["name"] if s else None)
        db.session.commit()
        end_session("porte refermée")
        refresh_leds()


def tick():
    """Appelée chaque seconde : fin de session au délai dépassé."""
    s = STATE["session"]
    if s and time.time() > s["expires"]:
        end_session("délai dépassé")


# ---------------------------------------------------------------------- API pour l'écran
@armoire_bp.route("/api/state")
def api_state():
    with _lock:
        s = STATE["session"]
        # taken_at est en UTC sans fuseau : conversion en secondes depuis 1970
        loans = {str(k): {"name": l.user_name, "since": (l.taken_at - datetime(1970, 1, 1)).total_seconds()}
                 for k, l in open_loans().items()}
        return jsonify({
            "server_time": time.time(),
            # pas d'UID de badge sur l'écran public : le nom suffit
            "session": {k: s[k] for k in ("name", "started", "expires")} if s else None,
            "door": STATE["door"],
            "serial": STATE["serial"],
            "loans": loans,
            "buildings": {str(k): v for k, v in buildings().items()},
            "settings": {k: v for k, v in get_settings().items()
                         if k in ("door_alert_s", "door_grace_s", "session_s", "screen_sleep_min", "cabinet_name")},
            "flash": STATE["flash"] if STATE["flash"] and time.time() - STATE["flash"]["t"] < 10 else None,
            # jeton de connexion par badge : seulement pour le navigateur de la borne elle-même
            "admin_grant": ({"token": STATE["admin_grant"]["token"]}
                            if is_local() and STATE["admin_grant"] and STATE["admin_grant"]["expires"] > time.time()
                            else None),
        })


def is_local():
    from flask import request
    return request.remote_addr in ("127.0.0.1", "::1")


@armoire_bp.route("/api/admin/badge-wait", methods=["POST"])
def api_badge_wait():
    """La borne ouvre / ferme la fenêtre Configuration : pendant 60 s, un badge autorisé y donne accès."""
    from flask import request
    if not is_local():
        return jsonify({"error": "Uniquement depuis la borne"}), 403
    on = bool((request.get_json(silent=True) or {}).get("on"))
    with _lock:
        STATE["admin_wait"] = time.time() + 60 if on else 0
    return jsonify({"ok": True})


@armoire_bp.route("/api/session/end", methods=["POST"])
def api_end_session():
    end_session("fin demandée à l'écran")
    return jsonify({"ok": True})


@armoire_bp.route("/api/loans")
def api_loans():
    """Historique des emprunts (200 derniers)."""
    rows = KeyLoan.query.order_by(KeyLoan.taken_at.desc()).limit(200).all()
    return jsonify([{"key_number": l.key_number, "user": l.user_name,
                     "taken_at": l.taken_at.isoformat(), "returned_at": l.returned_at.isoformat() if l.returned_at else None,
                     "returned_by": l.returned_by} for l in rows])


@armoire_bp.route("/api/screen/wake", methods=["POST"])
def api_screen_wake():
    """L'écran demande à rester allumé (session, porte ouverte, alerte)."""
    screen.wake()
    return jsonify({"ok": True})


@armoire_bp.route("/api/screen/apply", methods=["POST"])
def api_screen_apply():
    """Appelé par kiosk.sh au démarrage de la session graphique : orientation et veille."""
    if not is_local():
        return jsonify({"error": "Uniquement depuis la borne"}), 403
    s = get_settings()
    result = screen.apply_rotation(s["screen_rotation"])
    screen.set_timeout(s["screen_sleep_min"])
    return jsonify(result)


def _epoch(dt):
    return (dt - datetime(1970, 1, 1)).total_seconds() if dt else None


@armoire_bp.route("/api/keys/<int:number>/history")
def api_key_history(number):
    """Historique d'une clé pour l'écran : qui l'a sortie, quand, et quand elle est revenue."""
    slot = KeySlot.query.filter_by(key_number=number).first()
    if not slot:
        return jsonify({"error": "Clé inconnue"}), 404
    meta = db.session.get(KeyMeta, number)
    # ordre d'enregistrement (id) : reste juste même si l'horloge du mini-PC a été déréglée
    rows = KeyLoan.query.filter_by(key_number=number).order_by(KeyLoan.id.desc()).limit(50).all()
    return jsonify({
        "key_number": number,
        "label": slot.label if is_configured(slot) else "",
        "building": meta.building if meta else "",
        "status": slot.status,
        "loans": [{"user": l.user_name, "taken": _epoch(l.taken_at), "returned": _epoch(l.returned_at),
                   "returned_by": l.returned_by} for l in rows],
    })
