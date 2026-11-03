from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    badge_uid = db.Column(db.String(50), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class KeySlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pin = db.Column(db.Integer, unique=True, nullable=False)  # ex: 20 à 49
    key_number = db.Column(db.Integer, nullable=False)         # ex: 1 à 30
    label = db.Column(db.String(100), nullable=True)          # ex: "Clé Véhicule A"
    status = db.Column(db.String(20), default="ABSENT")        # "PRESENT" ou "ABSENT"
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

class EventLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    event_type = db.Column(db.String(50), nullable=False)     # "badge_scan", "key_change", etc.
    details = db.Column(db.String(255), nullable=False)
    user_name = db.Column(db.String(100), nullable=True)
