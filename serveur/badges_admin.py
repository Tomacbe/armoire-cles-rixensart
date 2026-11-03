"""
Gestion des badges — page /admin/badges et API /api/badges.

S'appuie sur le modèle User existant (name, badge_uid, is_active) et sur EventLog :
aucune modification de la base n'est nécessaire.

Intégration dans app.py (après start_serial_listener(app)) :
    from badges_admin import badges_bp
    app.register_blueprint(badges_bp)

Protection : si la variable d'environnement KEYBOX_ADMIN_PASSWORD est définie,
les pages de configuration demandent ce code (bouton « Configuration » de l'écran d'accueil).
La session admin expire après 15 minutes sans activité.
"""
import csv
import hmac
import io
import os
import re
import secrets
import time
import unicodedata
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Blueprint, Response, jsonify, redirect, request, session, current_app
from sqlalchemy import or_
from models import db, User, EventLog

badges_bp = Blueprint("badges", __name__)

UID_RE = re.compile(r"^[0-9A-F]{4,20}$")
ADMIN_IDLE = timedelta(minutes=15)


@badges_bp.record_once
def _setup(state):
    """Clé secrète des sessions : variable KEYBOX_SECRET ou fichier instance/secret_key (créé une fois)."""
    app = state.app
    if not app.secret_key:
        key = os.environ.get("KEYBOX_SECRET")
        if not key:
            path = Path(app.instance_path) / "secret_key"
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(secrets.token_hex(32))
                path.chmod(0o600)
            key = path.read_text().strip()
        app.secret_key = key
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", ADMIN_IDLE)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")


# ---------------------------------------------------------------------- protection
def admin_password():
    return os.environ.get("KEYBOX_ADMIN_PASSWORD", "")


def is_admin():
    if not admin_password():
        return True  # pas de code configuré : accès libre
    t = session.get("admin_until", 0)
    if t < time.time():
        return False
    session["admin_until"] = time.time() + ADMIN_IDLE.total_seconds()  # prolonge à chaque action
    return True


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not is_admin():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Session admin expirée, reconnectez-vous"}), 401
            return redirect("/?admin=1")
        return view(*args, **kwargs)
    return wrapper


@badges_bp.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    password = admin_password()
    if not password:
        return jsonify({"ok": True, "next": "/admin/badges"})
    if hmac.compare_digest(str(data.get("code", "")), password):
        session.permanent = True
        session["admin_until"] = time.time() + ADMIN_IDLE.total_seconds()
        session["admin_name"] = None
        db.session.add(EventLog(event_type="admin_login", details="Connexion aux pages de configuration (code maître)"))
        db.session.commit()
        return jsonify({"ok": True, "next": "/admin/badges"})
    time.sleep(1)  # ralentit les essais au hasard
    db.session.add(EventLog(event_type="admin_denied", details="Code admin erroné"))
    db.session.commit()
    return jsonify({"ok": False, "error": "Code incorrect"}), 401


@badges_bp.route("/api/admin/badge-login", methods=["POST"])
def admin_badge_login():
    """Connexion par badge : la borne échange le jeton à usage unique reçu dans /api/state."""
    import armoire
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Uniquement depuis la borne"}), 403
    token = str((request.get_json(silent=True) or {}).get("token", ""))
    with armoire._lock:
        g = armoire.STATE["admin_grant"]
        valid = bool(g and token and g["expires"] > time.time() and hmac.compare_digest(token, g["token"]))
        armoire.STATE["admin_grant"] = None
    if not valid:
        return jsonify({"ok": False, "error": "Accès expiré, repassez le badge"}), 401
    session.permanent = True
    session["admin_until"] = time.time() + ADMIN_IDLE.total_seconds()
    session["admin_name"] = g["name"]
    return jsonify({"ok": True, "next": "/admin/badges", "name": g["name"]})


@badges_bp.route("/api/admin/me")
@admin_required
def admin_me():
    return jsonify({"name": session.get("admin_name") or "Code maître"})


@badges_bp.route("/admin/logout")
def admin_logout():
    session.pop("admin_until", None)
    session.pop("admin_name", None)
    return redirect("/")


@badges_bp.route("/admin")
def admin_home():
    return redirect("/admin/badges")


# ---------------------------------------------------------------------- utilitaires
def normalize_uid(value):
    """'e9 e5:a8-b0' → 'E9E5A8B0'. Renvoie '' si vide."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"[\s:\-]", "", str(value)).upper()


def uid_error(uid):
    if not uid:
        return "UID manquant"
    if not UID_RE.match(uid):
        return "UID invalide (4 à 20 caractères hexadécimaux 0-9 A-F)"
    return None


def config_ids():
    from armoire import ConfigAccess
    return {c.user_id for c in ConfigAccess.query.all()}


def user_dict(u, cfg=None):
    cfg = config_ids() if cfg is None else cfg
    return {"id": u.id, "name": u.name, "badge_uid": u.badge_uid, "active": bool(u.is_active),
            "config": u.id in cfg}


def set_config_access(u, allowed):
    from armoire import ConfigAccess
    row = db.session.get(ConfigAccess, u.id)
    if allowed and not row:
        db.session.add(ConfigAccess(user_id=u.id))
        log_event("user_admin", f"{u.name} : accès à la configuration par badge autorisé")
    elif not allowed and row:
        db.session.delete(row)
        log_event("user_admin", f"{u.name} : accès à la configuration par badge retiré")


def log_event(event_type, details):
    try:
        # qui a fait la modification : nom de la personne connectée par badge, sinon « code maître »
        who = session.get("admin_name") if session else None
        db.session.add(EventLog(event_type=event_type, details=details, user_name=who or "code maître"))
    except Exception:  # le journal ne doit jamais bloquer une modification
        current_app.logger.exception("journal")


def parse_bool(value, default=True):
    if value is None or str(value).strip() == "":
        return default
    if isinstance(value, bool):
        return value
    s = strip_accents(str(value)).strip().lower()
    if s in ("1", "oui", "yes", "y", "o", "true", "vrai", "x", "actif", "active", "ok"):
        return True
    if s in ("0", "non", "no", "n", "false", "faux", "inactif", "inactive", "desactive", "desactivee", "bloque"):
        return False
    return default


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# ---------------------------------------------------------------------- page
@badges_bp.route("/admin/badges")
@admin_required
def admin_page():
    return current_app.send_static_file("admin/badges.html")


# ---------------------------------------------------------------------- CRUD
@badges_bp.route("/api/badges", methods=["GET"])
@admin_required
def list_badges():
    users = User.query.order_by(User.name).all()
    cfg = config_ids()
    return jsonify([user_dict(u, cfg) for u in users])


@badges_bp.route("/api/badges", methods=["POST"])
@admin_required
def create_badge():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    uid = normalize_uid(data.get("badge_uid"))
    if not name:
        return jsonify({"error": "Le nom est obligatoire"}), 400
    err = uid_error(uid)
    if err:
        return jsonify({"error": err}), 400
    existing = User.query.filter_by(badge_uid=uid).first()
    if existing:
        return jsonify({"error": f"Ce badge est déjà attribué à {existing.name}"}), 409
    u = User(name=name, badge_uid=uid)
    u.is_active = parse_bool(data.get("active"), True)
    db.session.add(u)
    log_event("user_admin", f"Badge {uid} attribué à {name}")
    db.session.flush()
    if parse_bool(data.get("config"), False):
        set_config_access(u, True)
    db.session.commit()
    return jsonify(user_dict(u)), 201


@badges_bp.route("/api/badges/<int:user_id>", methods=["PUT", "PATCH"])
@admin_required
def update_badge(user_id):
    u = db.session.get(User, user_id)
    if not u:
        return jsonify({"error": "Personne introuvable"}), 404
    data = request.get_json(force=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "Le nom est obligatoire"}), 400
        u.name = name
    if "badge_uid" in data:
        uid = normalize_uid(data.get("badge_uid"))
        err = uid_error(uid)
        if err:
            return jsonify({"error": err}), 400
        other = User.query.filter(User.badge_uid == uid, User.id != u.id).first()
        if other:
            return jsonify({"error": f"Ce badge est déjà attribué à {other.name}"}), 409
        u.badge_uid = uid
    if "active" in data:
        u.is_active = parse_bool(data.get("active"), u.is_active)
        log_event("user_admin", f"Badge {u.badge_uid} ({u.name}) {'activé' if u.is_active else 'désactivé'}")
    if "config" in data:
        set_config_access(u, parse_bool(data.get("config"), False))
    db.session.commit()
    return jsonify(user_dict(u))


@badges_bp.route("/api/badges/<int:user_id>", methods=["DELETE"])
@admin_required
def delete_badge(user_id):
    u = db.session.get(User, user_id)
    if not u:
        return jsonify({"error": "Personne introuvable"}), 404
    log_event("user_admin", f"Badge {u.badge_uid} ({u.name}) supprimé")
    set_config_access(u, False)
    db.session.delete(u)
    db.session.commit()
    return jsonify({"status": "deleted"})


# ---------------------------------------------------------------------- scan d'un badge sur le lecteur
# serial_worker.py écrit chaque badge lu dans EventLog (badge_scan / badge_unknown) avec l'UID
# dans le texte. La page demande « le dernier badge lu après l'événement n° X ».
_UID_IN_TEXT = re.compile(r"(?:UID:\s*|:\s*)([0-9A-Fa-f:\- ]{4,30}?)\)?\s*$")


@badges_bp.route("/api/badges/last-scan")
@admin_required
def last_scan():
    after = request.args.get("after", type=int)
    if after is None:  # point de départ : dernier événement connu
        last = EventLog.query.order_by(EventLog.id.desc()).first()
        return jsonify({"after": last.id if last else 0})
    ev = (EventLog.query
          .filter(EventLog.id > after, EventLog.event_type.in_(["badge_scan", "badge_unknown"]))
          .order_by(EventLog.id.desc()).first())
    if not ev:
        return jsonify({"uid": None})
    m = _UID_IN_TEXT.search(ev.details or "")
    uid = normalize_uid(m.group(1)) if m else ""
    owner = User.query.filter_by(badge_uid=uid).first() if uid else None
    return jsonify({"uid": uid, "event_id": ev.id, "owner": user_dict(owner) if owner else None})


# ---------------------------------------------------------------------- import CSV / Excel
NAME_KEYS = {"nom", "name", "nom complet", "nom et prenom", "nom prenom", "utilisateur", "personne", "agent", "full name"}
FIRST_KEYS = {"prenom", "first name", "firstname"}
LAST_KEYS = {"nom de famille", "last name", "lastname"}
UID_KEYS = {"uid", "badge", "badge uid", "badge_uid", "uid badge", "numero badge", "n badge", "no badge", "code badge",
            "code", "rfid", "carte", "numero de badge", "id badge"}
ACTIVE_KEYS = {"actif", "active", "is_active", "statut", "etat", "status", "acces"}


def _key(h):
    s = strip_accents(str(h or "")).lower().strip()
    s = re.sub(r"[°#_\.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def read_table(filename, raw):
    """Renvoie une liste de lignes (listes de cellules), en-tête comprise."""
    ext = os.path.splitext(filename.lower())[1]
    if ext in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Lecture Excel indisponible : installer openpyxl (venv/bin/pip install openpyxl)")
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if ext == ".xls":
        try:
            import xlrd
        except ImportError:
            raise ValueError("Ancien format .xls : enregistrez le fichier en .xlsx ou en .csv depuis Excel")
        book = xlrd.open_workbook(file_contents=raw)
        sh = book.sheet_by_index(0)
        return [sh.row_values(i) for i in range(sh.nrows)]
    if ext in (".csv", ".txt", ""):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";" if text.count(";") > text.count(",") else ","
        return [row for row in csv.reader(io.StringIO(text), dialect)]
    raise ValueError("Format non reconnu : utilisez .csv ou .xlsx")


def analyse_rows(rows):
    rows = [r for r in rows if r and any(str(c or "").strip() for c in r)]
    if not rows:
        raise ValueError("Le fichier est vide")
    header = [_key(h) for h in rows[0]]

    def find(keys):
        for i, h in enumerate(header):
            if h in keys:
                return i
        return None

    i_name, i_first, i_last = find(NAME_KEYS), find(FIRST_KEYS), find(LAST_KEYS)
    i_uid, i_active = find(UID_KEYS), find(ACTIVE_KEYS)
    if i_uid is None or (i_name is None and i_first is None and i_last is None):
        raise ValueError("Colonnes introuvables : il faut au moins « nom » et « uid » (ou « badge ») en première ligne")

    existing = {u.badge_uid: u for u in User.query.all()}
    seen = {}
    out = []
    for n, r in enumerate(rows[1:], start=2):
        cell = lambda i: (r[i] if i is not None and i < len(r) else None)
        first = str(cell(i_first) or "").strip()
        last = str(cell(i_last) or cell(i_name) or "").strip() if i_last is not None else str(cell(i_name) or "").strip()
        name = " ".join(p for p in (first, last) if p)
        uid = normalize_uid(cell(i_uid))
        active = parse_bool(cell(i_active), True)
        item = {"line": n, "name": name, "badge_uid": uid, "active": active}
        err = uid_error(uid) or (None if name else "Nom manquant")
        if err:
            item.update(action="error", message=err)
        elif uid in seen:
            item.update(action="error", message=f"UID déjà présent ligne {seen[uid]}")
        elif uid in existing:
            u = existing[uid]
            if u.name == name and bool(u.is_active) == active:
                item.update(action="same", message="Déjà à jour")
            else:
                changes = []
                if u.name != name:
                    changes.append(f"nom : {u.name} → {name}")
                if bool(u.is_active) != active:
                    changes.append("activé" if active else "désactivé")
                item.update(action="update", message=", ".join(changes), id=u.id)
        else:
            item.update(action="new", message="Nouvelle personne")
        if uid and uid not in seen:
            seen[uid] = n
        out.append(item)
    return out


@badges_bp.route("/api/badges/import", methods=["POST"])
@admin_required
def import_badges():
    """multipart : file=<fichier>, commit=0 (aperçu) ou 1 (enregistrer)."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "Aucun fichier reçu"}), 400
    try:
        rows = analyse_rows(read_table(f.filename, f.read()))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.exception("import")
        return jsonify({"error": f"Fichier illisible ({e.__class__.__name__})"}), 400

    summary = {k: sum(1 for r in rows if r["action"] == k) for k in ("new", "update", "same", "error")}
    if request.form.get("commit") != "1":
        return jsonify({"rows": rows, "summary": summary})

    for r in rows:
        if r["action"] == "new":
            u = User(name=r["name"], badge_uid=r["badge_uid"])
            u.is_active = r["active"]
            db.session.add(u)
        elif r["action"] == "update":
            u = db.session.get(User, r["id"])
            u.name, u.is_active = r["name"], r["active"]
    log_event("user_admin", f"Import {f.filename} : {summary['new']} ajout(s), {summary['update']} mise(s) à jour")
    db.session.commit()
    return jsonify({"rows": rows, "summary": summary, "committed": True})


@badges_bp.route("/api/badges/export.csv")
@admin_required
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["nom", "uid", "actif"])
    for u in User.query.order_by(User.name).all():
        w.writerow([u.name, u.badge_uid, "oui" if u.is_active else "non"])
    data = "\ufeff" + buf.getvalue()  # BOM : Excel ouvre correctement les accents
    return Response(data, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=badges_armoire.csv"})


# ---------------------------------------------------------------------- configuration des clés (nom + bâtiment)
@badges_bp.route("/admin/cles")
@admin_required
def keys_page():
    return current_app.send_static_file("admin/cles.html")


def _key_dict(slot, metas, loans):
    from armoire import default_label
    loan = loans.get(slot.key_number)
    return {
        "key_number": slot.key_number, "pin": slot.pin,
        "label": slot.label or default_label(slot.key_number),
        "custom": bool(slot.label and slot.label != default_label(slot.key_number)),
        "building": metas.get(slot.key_number) or "",
        "status": slot.status,
        "borrower": loan.user_name if (loan and slot.status != "PRESENT") else None,
    }


@badges_bp.route("/api/keys", methods=["GET"])
@admin_required
def list_keys():
    from armoire import buildings, open_loans
    from models import KeySlot
    metas, loans = buildings(), open_loans()
    return jsonify([_key_dict(s, metas, loans) for s in KeySlot.query.order_by(KeySlot.key_number).all()])


@badges_bp.route("/api/keys/<int:number>", methods=["PATCH", "PUT"])
@admin_required
def update_key(number):
    from armoire import KeyMeta, buildings, default_label, open_loans
    from models import KeySlot
    slot = KeySlot.query.filter_by(key_number=number).first()
    if not slot:
        return jsonify({"error": "Clé introuvable"}), 404
    data = request.get_json(force=True) or {}
    changes = []
    if "label" in data:
        label = (data.get("label") or "").strip()[:100] or default_label(number)
        if label != slot.label:
            changes.append(f"nom « {label} »")
            slot.label = label
    if "building" in data:
        building = (data.get("building") or "").strip()[:120] or None
        meta = db.session.get(KeyMeta, number)
        old = meta.building if meta else None
        if building != old:
            changes.append(f"bâtiment « {building or '—'} »")
            if meta:
                meta.building = building
            else:
                db.session.add(KeyMeta(key_number=number, building=building))
    if changes:
        log_event("user_admin", f"Clé #{number:02d} : " + ", ".join(changes))
    db.session.commit()
    return jsonify(_key_dict(slot, buildings(), open_loans()))


# ---------------------------------------------------------------------- journal : consultation et export
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Brussels")
except Exception:  # pragma: no cover
    LOCAL_TZ = None

JOURNAL_TYPES = {
    "badge": ["badge_scan", "badge_unknown"],
    "keys": ["key_change"],
    "door": ["door", "session_end"],
    "admin": ["user_admin", "admin_login", "admin_badge", "admin_denied"],
}
TYPE_LABELS = {"badge_scan": "Badge", "badge_unknown": "Badge refusé", "key_change": "Clé", "door": "Porte",
               "session_end": "Session", "user_admin": "Configuration", "admin_login": "Connexion admin",
               "admin_badge": "Connexion par badge", "admin_denied": "Accès admin refusé"}


def _local(dt_utc):
    """Les dates de la base sont en UTC sans fuseau : conversion à l'heure belge."""
    from datetime import timezone
    if dt_utc is None:
        return None
    d = dt_utc.replace(tzinfo=timezone.utc)
    return d.astimezone(LOCAL_TZ) if LOCAL_TZ else d


def _utc_bounds():
    """Paramètres from / to (AAAA-MM-JJ, heure belge) → bornes UTC naïves."""
    from datetime import datetime as dt, time as dtime, timedelta, timezone
    out = []
    for name, end in (("from", False), ("to", True)):
        v = request.args.get(name)
        if not v:
            out.append(None)
            continue
        day = dt.strptime(v, "%Y-%m-%d").date()
        local = dt.combine(day + timedelta(days=1) if end else day, dtime.min)
        local = local.replace(tzinfo=LOCAL_TZ) if LOCAL_TZ else local.replace(tzinfo=timezone.utc)
        out.append(local.astimezone(timezone.utc).replace(tzinfo=None))
    return out


def _journal_query():
    q = EventLog.query
    start, end = _utc_bounds()
    if start:
        q = q.filter(EventLog.timestamp >= start)
    if end:
        q = q.filter(EventLog.timestamp < end)
    kind = request.args.get("type", "all")
    if kind == "alert":
        q = q.filter(or_(EventLog.event_type.in_(["badge_unknown", "admin_denied"]),
                            EventLog.details.like("%sans badge%")))
    elif kind in JOURNAL_TYPES:
        q = q.filter(EventLog.event_type.in_(JOURNAL_TYPES[kind]))
    text = (request.args.get("q") or "").strip()
    if text:
        like = f"%{text}%"
        q = q.filter(or_(EventLog.details.like(like), EventLog.user_name.like(like)))
    return q.order_by(EventLog.id.desc())   # ordre d'enregistrement, même si l'horloge a été déréglée


@badges_bp.route("/admin/journal")
@admin_required
def journal_page():
    return current_app.send_static_file("admin/journal.html")


@badges_bp.route("/api/journal")
@admin_required
def api_journal():
    try:
        limit = min(int(request.args.get("limit", 500)), 2000)
        q = _journal_query()
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    total = q.count()
    rows = q.limit(limit).all()
    return jsonify({"total": total, "rows": [{
        "id": e.id, "t": _local(e.timestamp).strftime("%d/%m/%Y %H:%M:%S"),
        "type": e.event_type, "type_label": TYPE_LABELS.get(e.event_type, e.event_type),
        "details": e.details, "user": e.user_name} for e in rows]})


def _csv_response(header, rows, filename):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@badges_bp.route("/api/journal/export.csv")
@admin_required
def journal_export():
    try:
        rows = _journal_query().all()
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    stamp = time.strftime("%Y%m%d")
    return _csv_response(
        ["date", "heure", "type", "détails", "personne"],
        [[_local(e.timestamp).strftime("%d/%m/%Y"), _local(e.timestamp).strftime("%H:%M:%S"),
          TYPE_LABELS.get(e.event_type, e.event_type), e.details or "", e.user_name or ""] for e in rows],
        f"journal_armoire_{stamp}.csv")


@badges_bp.route("/api/loans/export.csv")
@admin_required
def loans_export():
    from armoire import KeyLoan, buildings
    from models import KeySlot
    try:
        start, end = _utc_bounds()
    except ValueError:
        return jsonify({"error": "Date invalide"}), 400
    q = KeyLoan.query
    if start:
        q = q.filter(KeyLoan.taken_at >= start)
    if end:
        q = q.filter(KeyLoan.taken_at < end)
    labels = {k.key_number: k.label for k in KeySlot.query.all()}
    blds = buildings()
    rows = []
    for l in q.order_by(KeyLoan.taken_at.desc()).all():
        taken, back = _local(l.taken_at), _local(l.returned_at)
        dur = ""
        if l.returned_at:
            minutes = int((l.returned_at - l.taken_at).total_seconds() // 60)
            dur = f"{minutes // 60}h{minutes % 60:02d}"
        rows.append([f"#{l.key_number:02d}", labels.get(l.key_number, ""), blds.get(l.key_number, ""), l.user_name,
                     taken.strftime("%d/%m/%Y %H:%M"), back.strftime("%d/%m/%Y %H:%M") if back else "toujours sortie",
                     l.returned_by or "", dur])
    return _csv_response(["clé", "nom", "bâtiment", "empruntée par", "sortie", "retour", "remise par", "durée"],
                         rows, f"emprunts_cles_{time.strftime('%Y%m%d')}.csv")


# ---------------------------------------------------------------------- réglages (relais, session)
@badges_bp.route("/admin/reglages")
@admin_required
def settings_page():
    return current_app.send_static_file("admin/reglages.html")


@badges_bp.route("/api/settings", methods=["GET", "PUT"])
@admin_required
def api_settings():
    import armoire
    if request.method == "PUT":
        data = request.get_json(force=True) or {}
        try:
            before = armoire.get_settings()
            after = armoire.save_settings(data)
        except (ValueError, TypeError) as e:
            return jsonify({"error": str(e)}), 400
        names = {"unlock_s": "ouverture du relais", "session_s": "durée de session",
                 "door_alert_s": "alerte porte ouverte", "door_grace_s": "alerte porte sans badge",
                 "screen_sleep_min": "veille de l'écran", "cabinet_name": "nom de l'armoire",
                 "screen_rotation": "orientation de l'écran"}
        units = {"screen_sleep_min": " min", "cabinet_name": "", "screen_rotation": ""}
        labels = {"normal": "horizontal", "left": "vertical (gauche)", "right": "vertical (droite)",
                  "inverted": "horizontal retourné"}
        show = lambda k, v: labels.get(v, v) if k == "screen_rotation" else v
        changes = [f"{names.get(k, k)} {show(k, before[k])} → {show(k, after[k])}{units.get(k, ' s')}"
                   for k in after if after[k] != before[k]]
        if before["screen_sleep_min"] != after["screen_sleep_min"]:
            import screen
            screen.set_timeout(after["screen_sleep_min"])
        if before["screen_rotation"] != after["screen_rotation"]:
            import screen
            screen.set_rotation(after["screen_rotation"])
        if changes:
            log_event("user_admin", "Réglages : " + ", ".join(changes))
            db.session.commit()
    spec = {k: {"min": lo, "max": hi, "default": d} for k, (d, lo, hi) in armoire.SETTINGS_SPEC.items()}
    spec.update({k: {"maxlength": n, "default": d} for k, (d, n) in armoire.TEXT_SETTINGS.items()})
    spec.update({k: {"choices": list(c), "default": d} for k, (d, c) in armoire.CHOICE_SETTINGS.items()})
    return jsonify({"values": armoire.get_settings(), "spec": spec})


@badges_bp.route("/api/settings/test-unlock", methods=["POST"])
@admin_required
def test_unlock():
    import armoire
    if not armoire.STATE["serial"]["connected"]:
        return jsonify({"error": "Arduino non connecté au serveur"}), 409
    s = armoire.get_settings()
    armoire.send({"cmd": "unlock", "ms": s["unlock_s"] * 1000})
    log_event("user_admin", f"Test d'ouverture de la porte ({s['unlock_s']} s)")
    db.session.commit()
    return jsonify({"ok": True, "unlock_s": s["unlock_s"]})


# ---------------------------------------------------------------------- test des LED (page Clés)
@badges_bp.route("/api/leds/test", methods=["POST"])
@admin_required
def leds_test():
    """mode=status : statut réel (vert/rouge) ; mode=identify&key=N : seule la LED de la clé N clignote ; mode=off."""
    import armoire
    if not armoire.STATE["serial"]["connected"]:
        return jsonify({"error": "Arduino non connecté au serveur (port série fermé)"}), 409
    data = request.get_json(silent=True) or {}
    mode = data.get("mode", "status")
    if mode == "off":
        cmd = {"cmd": "leds_off"}
    elif mode == "identify":
        from models import KeySlot
        n = int(data.get("key", 0))
        total = KeySlot.query.count()
        if not 1 <= n <= total:
            return jsonify({"error": "Numéro de clé invalide"}), 400
        cmd = {"cmd": "leds", "map": "".join("Y" if i == n else "O" for i in range(1, total + 1))}
    else:
        cmd = {"cmd": "leds", "map": armoire.led_map()}
    armoire.send(cmd)
    return jsonify({"sent": cmd, "t": time.time()})


@badges_bp.route("/api/leds/ack")
@admin_required
def leds_ack():
    import armoire
    return jsonify({"last_ack": armoire.STATE.get("last_ack"), "serial": armoire.STATE["serial"], "t": time.time()})


@badges_bp.route("/api/badges/modele.csv")
@admin_required
def template_csv():
    data = "\ufeffnom;uid;actif\nJean Dupont;E9E5A8B0;oui\nMarie Lambert;04A21C7F;non\n"
    return Response(data, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=modele_import_badges.csv"})


# ---------------------------------------------------------------------- état du système (onglet Réglages)
@badges_bp.route("/api/system")
@admin_required
def api_system():
    """Liaison Arduino, horloge du mini-PC et synchronisation NTP : affichés dans Réglages, plus sur l'écran d'accueil."""
    import subprocess
    import armoire
    from datetime import datetime as dt, timezone
    ntp = None
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip() in ("yes", "no"):
            ntp = r.stdout.strip() == "yes"
    except (OSError, subprocess.SubprocessError):
        pass
    now = dt.now(timezone.utc)
    local = now.astimezone(LOCAL_TZ) if LOCAL_TZ else now
    last = EventLog.query.order_by(EventLog.id.desc()).first()
    return jsonify({
        "serial": armoire.STATE["serial"],
        "door": armoire.STATE["door"],
        "time": local.strftime("%d/%m/%Y %H:%M:%S"),
        "year": local.year,
        "ntp": ntp,
        # l'horloge a reculé : le dernier événement enregistré est daté plus tard que maintenant
        "clock_behind": bool(last and last.timestamp and last.timestamp > now.replace(tzinfo=None)),
    })
