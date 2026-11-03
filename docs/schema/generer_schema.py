"""Schéma de câblage de l'armoire à clés (A3 paysage, unités en mm) → schema_armoire.svg"""

W, H = 420, 297
out = []
SW = 0.35  # épaisseur des fils


def add(s):
    out.append(s)


def wire(*pts, dash=False, color="#000"):
    d = " ".join(f"{x},{y}" for x, y in pts)
    extra = ' stroke-dasharray="2,1.2"' if dash else ""
    add(f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="{SW}" stroke-linejoin="round"{extra}/>')


def dot(x, y):
    add(f'<circle cx="{x}" cy="{y}" r="0.9" fill="#000"/>')


def text(x, y, s, size=3.0, anchor="start", weight="normal", color="#000", italic=False):
    style = ' font-style="italic"' if italic else ""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    add(f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{color}"{style}>{s}</text>')


def box(x, y, w, h, title=None, ref=None, fill="#fff", dash=False):
    extra = ' stroke-dasharray="3,1.5"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#000" stroke-width="0.5"{extra}/>')
    if ref:
        text(x, y - 1.5, ref, 3.2, weight="bold")
    if title:
        text(x + w / 2, y + 6, title, 3.4, "middle", "bold")


def pin_l(x, y, name, length=0):
    """Broche sur le côté gauche d'un boîtier : nom à l'intérieur."""
    text(x + 1.8, y + 1.1, name, 2.8)


def pin_r(x, y, name):
    text(x - 1.8, y + 1.1, name, 2.8, "end")


def gnd(x, y):
    """Symbole de masse sous le point (x, y)."""
    wire((x, y), (x, y + 3))
    add(f'<line x1="{x-3}" y1="{y+3}" x2="{x+3}" y2="{y+3}" stroke="#000" stroke-width="0.45"/>')
    add(f'<line x1="{x-2}" y1="{y+4.2}" x2="{x+2}" y2="{y+4.2}" stroke="#000" stroke-width="0.45"/>')
    add(f'<line x1="{x-1}" y1="{y+5.4}" x2="{x+1}" y2="{y+5.4}" stroke="#000" stroke-width="0.45"/>')


def rail_label(x, y, name, anchor="start"):
    text(x, y - 1.2, name, 2.8, anchor, "bold")


def resistor_h(x1, x2, y, ref, val):
    """Résistance horizontale (symbole CEI rectangle) entre x1 et x2."""
    mid = (x1 + x2) / 2
    wire((x1, y), (mid - 5, y))
    add(f'<rect x="{mid-5}" y="{y-1.6}" width="10" height="3.2" fill="#fff" stroke="#000" stroke-width="0.4"/>')
    wire((mid + 5, y), (x2, y))
    text(mid, y - 2.8, f"{ref}  {val}", 2.6, "middle")


def cap_v(x, y1, y2, ref, val):
    """Condensateur polarisé vertical (+ en haut)."""
    mid = (y1 + y2) / 2
    wire((x, y1), (x, mid - 1))
    add(f'<line x1="{x-3}" y1="{mid-1}" x2="{x+3}" y2="{mid-1}" stroke="#000" stroke-width="0.5"/>')
    add(f'<path d="M{x-3},{mid+1.6} Q{x},{mid+0.4} {x+3},{mid+1.6}" fill="none" stroke="#000" stroke-width="0.5"/>')
    wire((x, mid + 1), (x, y2))
    text(x - 4.2, mid - 1.6, "+", 2.8, "middle")
    text(x + 4.5, mid - 0.5, ref, 2.6)
    text(x + 4.5, mid + 2.6, val, 2.6)


def diode_v(x, y1, y2, ref, val):
    """Diode verticale, cathode en haut (montage roue libre)."""
    mid = (y1 + y2) / 2
    wire((x, y1), (x, mid - 2))
    add(f'<line x1="{x-2.2}" y1="{mid-2}" x2="{x+2.2}" y2="{mid-2}" stroke="#000" stroke-width="0.45"/>')
    add(f'<polygon points="{x-2.2},{mid+2} {x+2.2},{mid+2} {x},{mid-2}" fill="#fff" stroke="#000" stroke-width="0.4"/>')
    wire((x, mid + 2), (x, y2))
    text(x + 3.2, mid - 0.5, ref, 2.6, weight="bold")
    text(x + 3.2, mid + 2.6, val, 2.4)


def switch_v(x, y1, y2, ref, label=None, reed=False):
    """Interrupteur (contact) vertical normalement ouvert."""
    mid = (y1 + y2) / 2
    wire((x, y1), (x, mid - 2.5))
    dot(x, mid - 2.5)
    add(f'<line x1="{x}" y1="{mid+2.5}" x2="{x-2.8}" y2="{mid-2.2}" stroke="#000" stroke-width="0.4"/>')
    wire((x, mid + 2.5), (x, y2))
    if reed:
        add(f'<ellipse cx="{x-0.8}" cy="{mid}" rx="3.6" ry="5.2" fill="none" stroke="#000" stroke-width="0.3" stroke-dasharray="1,0.7"/>')
    text(x + 3.2, mid - 0.5, ref, 2.6)
    if label:
        text(x + 3.2, mid + 2.6, label, 2.4)


# ======================================================================== cadre
add(f'<rect x="5" y="5" width="{W-10}" height="{H-10}" fill="none" stroke="#000" stroke-width="0.7"/>')

# ======================================================================== alimentations
# PSU1 12 V
box(14, 18, 34, 22, "ALIM 12 V", "PS1")
text(28, 30, "≥ 2 A", 2.4, "middle")
pin_r(48, 31, "+12V"); pin_r(48, 37, "0V")
# rail +12 V (passe au-dessus du mini-PC)
wire((48, 31), (54, 31), (54, 11), (375, 11))
rail_label(58, 11, "+12V")
wire((48, 37), (52, 37), (52, 42)); gnd(52, 42)

# PSU2 5 V LED
box(352, 228, 34, 22, "ALIM 5 V", "PS2")
text(369, 240, "3 A (ruban LED)", 2.4, "middle")
pin_l(352, 234, "+5V"); pin_l(352, 245, "0V")

# ======================================================================== mini-PC
box(178, 18, 54, 20, "MINI-PC", "PC1")
text(205, 30, "Ubuntu · Flask keybox", 2.5, "middle")
text(205, 33.5, "/dev/serial/by-id/usb-1a86…", 2.2, "middle", italic=True)
wire((205, 38), (205, 58), dash=True)
text(207, 47, "USB (alimentation 5 V", 2.4)
text(207, 50, "+ liaison série 115200)", 2.4)

# ======================================================================== Arduino Mega
AX1, AX2, AY1, AY2 = 160, 250, 58, 222
box(AX1, AY1, AX2 - AX1, AY2 - AY1, None, "U1")
text(205, 66, "ARDUINO MEGA 2560", 3.6, "middle", "bold")
text(205, 70.5, "sketch armoire_cles v5", 2.4, "middle", italic=True)
text(205, 74.5, "(CH340, USB)", 2.4, "middle", italic=True)
text(205, AY1 - 1.5, "USB", 2.6, "middle")

# broches côté gauche (lecteur, reed)
LPINS = {"D2 (INT4)": 86, "D3 (INT5)": 98, "D8": 110, "D9": 122, "D4": 156, "GND": 206}
for n, y in LPINS.items():
    pin_l(AX1, y, n)
# broches côté droit
RPINS = {"5V": 86, "D7": 104, "GND ": 122, "D6": 156}
for n, y in RPINS.items():
    pin_r(AX2, y, n.strip())
# bus des contacts de clés en bas
text(205, 212, "D20 … D49", 2.8, "middle")
text(205, 216, "(INPUT_PULLUP)", 2.3, "middle", italic=True)

# ======================================================================== lecteur Wiegand
RX1, RX2, RY1, RY2 = 18, 72, 60, 148
box(RX1, RY1, RX2 - RX1, RY2 - RY1, "LECTEUR BADGE", "U2")
text(45, 70, "Wiegand 12 V · ID + IC", 2.5, "middle")
text(45, 73.5, "sortie WG34", 2.5, "middle")
READER = [("VCC +12V", "rouge", 78), ("D0", "vert", 86), ("D1", "blanc", 98), ("LED", "bleu", 110),
          ("BEEP", "jaune", 122), ("WG26/34", "gris", 132), ("GND", "noir", 142)]
for n, c, y in READER:
    pin_r(RX2, y, n)
    text(RX2 + 1.5, y - 1.0, c, 2.2, italic=True, color="#555")
# VCC → rail +12V
wire((RX2, 78), (86, 78), (86, 11)); dot(86, 11)
# D0, D1, LED, BEEP → Arduino
for (n, c, y), ay in zip(READER[1:5], [86, 98, 110, 122]):
    wire((RX2, y), (AX1, ay))
# WG → masse (WG34) ; GND → masse
wire((RX2, 132), (80, 132), (80, 142)); dot(80, 142)
wire((RX2, 142), (92, 142)); gnd(92, 142)
text(81.5, 137.5, "gris → GND = WG34", 2.2, italic=True, color="#555")

# ======================================================================== capteur reed porte
wire((AX1, 156), (120, 156), (120, 162))
switch_v(120, 162, 182, "S1", "reed porte", reed=True)
gnd(120, 182)
text(124, 192, "fermé = porte fermée", 2.3, italic=True, color="#555")
text(124, 195.5, "ouvert = porte ouverte", 2.3, italic=True, color="#555")

# masse Arduino côté gauche
wire((AX1, 206), (140, 206)); gnd(140, 206)

# ======================================================================== module relais
KX1, KX2, KY1, KY2 = 282, 330, 76, 132
box(KX1, KY1, KX2 - KX1, KY2 - KY1, "RELAIS 1 VOIE", "K1")
text(306, 89, "module 5 V", 2.4, "middle")
pin_l(KX1, 86, "DC+"); pin_l(KX1, 104, "IN1"); pin_l(KX1, 122, "DC−")
text(KX2 + 1.5, 90.8, "COM", 2.6); text(KX2 + 1.5, 102.8, "NC", 2.6); text(KX2 + 1.5, 114.8, "NO", 2.6)
# symbole interne : bobine + contact
add(f'<rect x="{KX1+12}" y="96" width="8" height="12" fill="none" stroke="#000" stroke-width="0.35"/>')
add(f'<line x1="{KX1+13}" y1="106" x2="{KX1+19}" y2="98" stroke="#000" stroke-width="0.3"/>')
wire((KX1 + 20, 102), (KX1 + 26, 102), dash=True)
wire((KX2 - 16, 92), (KX2, 92)); dot(KX2 - 16, 92)
add(f'<line x1="{KX2-16}" y1="92" x2="{KX2-9}" y2="103.3" stroke="#000" stroke-width="0.35"/>')
wire((KX2 - 10, 104), (KX2, 104))
wire((KX2 - 10, 116), (KX2, 116))
text(306, 128, "repos : COM–NC fermé", 2.2, "middle", italic=True, color="#555")
# commande
wire((AX2, 86), (KX1, 86)); text(262, 84.8, "+5V", 2.4)
wire((AX2, 104), (KX1, 104))
wire((KX1, 122), (270, 122), (270, 128)); gnd(270, 128)
wire((AX2, 122), (258, 122), (258, 128)); gnd(258, 128)
# puissance : +12V → COM ; NC → ventouse
wire((375, 11), (375, 70))
wire((375, 70), (345, 70), (345, 92), (KX2, 92))

wire((KX2, 104), (375, 104), (375, 112))
# ventouse L1 (électro-aimant)
add('<rect x="371" y="112" width="8" height="20" fill="#fff" stroke="#000" stroke-width="0.45"/>')
add('<line x1="371" y1="114" x2="379" y2="130" stroke="#000" stroke-width="0.3"/>')
text(366, 119, "L1", 2.8, "end", "bold")
text(366, 122.5, "électro-aimant", 2.4, "end")
text(366, 125.5, "(ventouse) 12 V", 2.4, "end")
wire((375, 132), (375, 146)); dot(375, 146); gnd(375, 146)
# diode de roue libre en parallèle
wire((375, 108), (392, 108)); dot(375, 108)
diode_v(392, 108, 146, "D1", "1N4007")
wire((392, 146), (375, 146))
text(392, 157, "D1 : si la ventouse n'a pas", 2.2, "middle", italic=True, color="#555")
text(392, 160, "de diode intégrée", 2.2, "middle", italic=True, color="#555")

# ======================================================================== ruban LED WS2812B
LX1, LX2, LY1, LY2 = 300, 344, 176, 212
box(LX1, LY1, LX2 - LX1, LY2 - LY1, "RUBAN WS2812B", "U3")
text(322, 191, "50 LED", 2.6, "middle")
text(322, 194.5, "0–29 : clés 1–30", 2.3, "middle")
text(322, 197.5, "49 : voyant d'état", 2.3, "middle")
pin_l(LX1, 184, "+5V"); pin_l(LX1, 196, "DIN"); pin_l(LX1, 206, "GND")
# D6 → R1 → DIN
wire((AX2, 156), (270, 156), (270, 196))
resistor_h(270, LX1, 196, "R1", "330 Ω")
# +5V LED depuis PS2 (rail à droite du ruban)
wire((352, 234), (348, 234), (348, 172), (294, 172), (294, 184), (LX1, 184))
rail_label(310, 172, "+5V LED")
# condensateur de découplage près du ruban
dot(348, 190)
wire((348, 190), (356, 190))
cap_v(356, 190, 212, "C1", "1000 µF")
gnd(356, 212)
# masse du ruban et de PS2
wire((LX1, 206), (292, 206), (292, 214)); gnd(292, 214)
wire((352, 245), (346, 245), (346, 252)); gnd(346, 252)

# ======================================================================== contacts des clés
KY = 222
wire((205, AY2), (205, 230))
dot(205, 230)
wire((150, 230), (262, 230))
text(150, 228.5, "bus D20 … D49 (une broche par clé)", 2.4)
for x, ref, lab in [(160, "SW1", "clé 1 · D20"), (180, "SW2", "clé 2 · D21"), (240, "SW30", "clé 30 · D49")]:
    wire((x, 230), (x, 236))
    switch_v(x, 236, 254, ref, None)
    text(x, 262, lab, 2.3, "middle")
    gnd(x, 254)
    dot(x, 230)
text(210, 246, "…", 6, "middle")
text(205, 268, "contact fermé (LOW) = clé présente", 2.5, "middle", italic=True, color="#555")

# ======================================================================== notes
NX, NY = 14, 160
box(NX, NY, 92, 108, None, None, "#fafafa")
text(NX + 3, NY + 6, "NOTES", 3.2, weight="bold")
notes = [
    "1. Toutes les masses sont communes : 0V PS1,",
    "   0V PS2 et GND de l'Arduino reliés.",
    "2. L'Arduino est alimenté par l'USB du mini-PC.",
    "3. D0/D1 du lecteur : mesurer ≤ 5 V au repos",
    "   avant branchement (sinon pont diviseur",
    "   10 kΩ / 6,8 kΩ sur chaque fil).",
    "4. Ne rien brancher sur D0 / D1 de l'Arduino",
    "   (RX0 / TX0 = liaison USB).",
    "5. Relais câblé sur NC : bobine alimentée",
    "   uniquement pendant l'ouverture (sécurité :",
    "   porte verrouillée si l'Arduino s'arrête).",
    "6. Module relais actif à l'état bas",
    "   (RELAY_ACTIVE LOW dans le sketch).",
    "7. LED et BEEP du lecteur : actifs à la masse,",
    "   pilotés en collecteur ouvert par D8 / D9.",
    "8. Ordre des couleurs du ruban : COLOR_ORDER",
    "   (RGB ou GRB) en tête du sketch.",
    "9. Contacts de clés, reed : pull-up internes,",
    "   aucune résistance externe.",
    "10. Clés sans nom dans la configuration :",
    "    LED éteinte (non paramétrées).",
]
for i, line in enumerate(notes):
    indent = 4 if line.startswith(" ") else 0
    text(NX + 3 + indent, NY + 12 + i * 4.4, line.strip(), 2.5)

# ======================================================================== cartouche
CX, CY = 300, 258
add(f'<rect x="{CX}" y="{CY}" width="{W-5-CX}" height="{H-5-CY}" fill="#fff" stroke="#000" stroke-width="0.5"/>')
add(f'<line x1="{CX}" y1="{CY+12}" x2="{W-5}" y2="{CY+12}" stroke="#000" stroke-width="0.3"/>')
add(f'<line x1="{CX}" y1="{CY+24}" x2="{W-5}" y2="{CY+24}" stroke="#000" stroke-width="0.3"/>')
add(f'<line x1="{CX+60}" y1="{CY+12}" x2="{CX+60}" y2="{H-5}" stroke="#000" stroke-width="0.3"/>')
text(CX + 3, CY + 5.5, "ARMOIRE À CLÉS CONNECTÉE", 3.6, weight="bold")
text(CX + 3, CY + 9.8, "Commune de Rixensart · Service technique", 2.6)
text(CX + 3, CY + 17, "Schéma de câblage", 2.6, weight="bold")
text(CX + 3, CY + 21, "Arduino Mega 2560", 2.6)
text(CX + 63, CY + 17, "Sketch : armoire_cles v5", 2.4)
text(CX + 63, CY + 21, "Date : 01/11/2026", 2.4)
text(CX + 3, CY + 29.5, "Format A3 · Folio 1/1", 2.4)
text(CX + 63, CY + 29.5, "Rév. A", 2.4)

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}" '
       f'font-family="DejaVu Sans, Arial, sans-serif">\n<rect width="{W}" height="{H}" fill="#fff"/>\n'
       + "\n".join(out) + "\n</svg>\n")
open("schema_cablage_armoire.svg", "w", encoding="utf-8").write(svg)
print("ok", len(out))
