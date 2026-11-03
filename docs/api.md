# API HTTP

Serveur Flask sur le port 5000. Les routes marquées 🔒 demandent la session admin (code
`KEYBOX_ADMIN_PASSWORD`, saisi via `POST /api/admin/login`) quand ce code est défini.

## Écran (public)

| Méthode | Route | Réponse |
|---|---|---|
| GET | `/` | Écran kiosque |
| GET | `/api/status` | Clés : `key_number`, `pin`, `label`, `status` (`PRESENT`/`ABSENT`), `last_updated` (UTC) |
| GET | `/api/logs?limit=` | Derniers événements (100 par défaut, 500 maxi), dans l'ordre d'enregistrement : `id`, `timestamp`, `type`, `details` (sans UID de badge), `user` |
| GET | `/api/state` | État temps réel : `session` (nom, sans UID), `door`, `serial`, `loans` (emprunteur par clé), `buildings`, `settings` (dont `cabinet_name`, `screen_sleep_min`), `flash` |
| GET | `/api/keys/<n>/history` | 50 derniers emprunts d'une clé (qui, sortie, retour) — fenêtre « historique » de l'écran |
| POST | `/api/screen/wake` | Rallume l'écran et remet à zéro le délai de veille |
| POST | `/api/screen/apply` | Borne seulement (127.0.0.1) : applique l'orientation et la veille (appelé par `kiosk.sh`) |
| POST | `/api/admin/badge-wait` | Borne seulement : fenêtre Configuration ouverte `{"on": true}` → un badge autorisé y donne accès pendant 60 s |
| POST | `/api/admin/badge-login` | Borne seulement : `{"token"}` reçu dans `/api/state.admin_grant` → session admin |
| POST | `/api/session/end` | Termine la session en cours |
| GET | `/api/loans` | 200 derniers emprunts |

## Administration 🔒

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/api/admin/login` | `{"code": "…"}` → cookie de session (15 min d'inactivité) |
| GET | `/admin/logout` | Déconnexion |
| GET | `/admin/badges`, `/admin/cles`, `/admin/journal`, `/admin/reglages` | Pages de configuration |
| GET / POST | `/api/badges` | Liste / ajout `{"name","badge_uid","active","config"}` (`config` : accès à la configuration par badge) |
| PUT/PATCH, DELETE | `/api/badges/<id>` | Modification / suppression |
| GET | `/api/badges/last-scan[?after=<id>]` | Dernier badge lu (pour « Scanner le badge ») |
| POST | `/api/badges/import` | Fichier CSV / XLSX, `commit=0` aperçu, `commit=1` enregistrement |
| GET | `/api/badges/export.csv`, `/api/badges/modele.csv` | Export, modèle d'import |
| GET | `/api/keys` | Clés avec nom, bâtiment, état, emprunteur |
| PATCH | `/api/keys/<n>` | `{"label","building"}` (nom vide = « Clé n°n », non paramétrée) |
| GET | `/api/journal?from=&to=&type=&q=` | Journal filtré (`type` : `keys`, `badge`, `door`, `alert`, `admin`) |
| GET | `/api/journal/export.csv`, `/api/loans/export.csv` | Exports CSV (`;`, UTF-8 BOM, heure belge) |
| GET / PUT | `/api/settings` | `cabinet_name`, `unlock_s`, `session_s`, `door_alert_s`, `door_grace_s`, `screen_sleep_min`, `retro_s`, `screen_rotation` (`normal`, `left`, `right`, `inverted`) |
| GET | `/api/system` | Liaison Arduino, porte, heure du mini-PC, synchronisation NTP |
| POST | `/api/settings/test-unlock` | Ouvre la porte avec la durée réglée |
| POST | `/api/leds/test` | `{"mode": "status" / "identify" / "off", "key": n}` |
| GET | `/api/leds/ack` | Dernier accusé de réception de l'Arduino |
