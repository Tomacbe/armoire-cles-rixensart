import re
from flask import Flask, jsonify, request
from models import db, User, KeySlot, EventLog
from serial_worker import start_serial_listener

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///keybox.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with app.app_context():
    db.create_all()
    # Initialisation des pins 20 à 49 (30 clés) si la base est vide
    if KeySlot.query.count() == 0:
        for i, pin in enumerate(range(20, 50), start=1):
            slot = KeySlot(pin=pin, key_number=i, label=f"Clé n°{i}", status="PRESENT")
            db.session.add(slot)
        db.session.commit()

# Démarrer l'écoute du port série en arrière-plan
start_serial_listener(app)

# Sessions, emprunts et LED
from armoire import armoire_bp
app.register_blueprint(armoire_bp)

# Pages de configuration (badges, clés, journal, réglages)
from badges_admin import badges_bp
app.register_blueprint(badges_bp)

# Veille de l'écran (DPMS) : délai réglé dans Configuration › Réglages
import screen
from armoire import get_settings
screen.start(lambda: get_settings()["screen_sleep_min"])

@app.route('/')
def kiosk():
    return app.send_static_file('kiosk/index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    """Renvoie l'état en temps réel de toutes les clés"""
    keys = KeySlot.query.all()
    result = [{
        "key_number": k.key_number,
        "pin": k.pin,
        "label": k.label,
        "status": k.status,
        "last_updated": k.last_updated.isoformat()
    } for k in keys]
    return jsonify(result)

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """Renvoie les derniers historiques"""
    # ordre d'enregistrement (id) et non par date : si l'horloge du mini-PC recule (pile du BIOS),
    # les nouveaux événements restent en tête
    limit = min(request.args.get('limit', 100, type=int), 500)
    logs = EventLog.query.order_by(EventLog.id.desc()).limit(limit).all()
    result = [{
        "id": l.id,
        "timestamp": l.timestamp.isoformat(),
        "type": l.event_type,
        "details": public_details(l.details),
        "user": l.user_name
    } for l in logs]
    return jsonify(result)


def public_details(text):
    """Écran public : retire les UID de badge (« (UID: B3063709) », « … : B3063709 »)."""
    text = re.sub(r"\s*\(UID\s*:?\s*[0-9A-Fa-f:]+\)", "", text or "")
    text = re.sub(r"(Badge inconnu ou désactivé)\s*:\s*[0-9A-Fa-f:]+", r"\1", text)
    return text

@app.route('/api/users', methods=['GET', 'POST'])
def manage_users():
    """Gestion des utilisateurs et badges"""
    if request.method == 'POST':
        data = request.json
        new_user = User(name=data.get('name'), badge_uid=data.get('badge_uid'))
        db.session.add(new_user)
        db.session.commit()
        return jsonify({"status": "success", "message": "Utilisateur ajouté"}), 201
    
    users = User.query.all()
    return jsonify([{"id": u.id, "name": u.name, "badge_uid": u.badge_uid, "active": u.is_active} for u in users])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
