/*
  Armoire à clés — Commune de Rixensart
  Arduino Mega : 30 contacts de clés (pins 20-49), lecteur de badge Wiegand 12 V (D0→D2, D1→D3, LED→D8, BEEP→D9), relais d'électro-aimant (D7), capteur reed de porte (D4),
  ruban de 50 LED WS2812B sur D6 (LED 0-29 = clés 1-30, LED 49 = voyant d'état).

  Le mini-PC (Flask) décide des couleurs ; l'Arduino lit les capteurs, envoie les événements
  et exécute les commandes. Aucune attente bloquante (pas de delay long) : les clés restent
  surveillées en permanence.

  Arduino → mini-PC (une ligne JSON) :
    {"event":"badge","uid":"E9E5A8B0"}
    {"event":"key_change","pin":24,"status":"ABSENT"}      (ou "PRESENT")
    {"event":"door","status":"OPEN"}                        capteur de porte (ou "CLOSED")
    {"event":"ack","cmd":"leds"}                            accusé de réception d'une commande

  Mini-PC → Arduino (une ligne JSON) :
    {"cmd":"leds","map":"GGRY..."}   une lettre par clé 1→30 : G vert, R rouge, Y jaune clignotant, O éteinte
    {"cmd":"leds_off"}               éteint les LED des clés
    {"cmd":"unlock","ms":5000}       ouvre l'électro-aimant pendant ms millisecondes (défaut UNLOCK_MS), voyant vert
    {"cmd":"lock"}                   reverrouille tout de suite
    {"cmd":"deny"}                   voyant rouge qui clignote 3 fois
    {"cmd":"status"}                 renvoie l'état de toutes les clés (synchronisation au démarrage)

  Bibliothèque : FastLED (le lecteur Wiegand est lu sans bibliothèque).
*/
#include <FastLED.h>

// ------------------------------------------------------------------ câblage
// Lecteur Wiegand (fil vert D0, fil blanc D1) : broches d'interruption du Mega
#define WG_D0_PIN        2
#define WG_D1_PIN        3
// LED et bip du lecteur (fil bleu, fil jaune) : actifs quand reliés à la masse
#define READER_LED_PIN   8
#define READER_BEEP_PIN  9
#define DATA_PIN         6
// Module relais 1 voie (DC+ → 5V, DC- → GND, IN1 → D7) : coupe l'alimentation de l'électro-aimant pour ouvrir.
// Câblage des contacts : 12 V + → COM, NC → + électro-aimant  (repos = aimant alimenté = porte verrouillée).
#define RELAY_PIN        7
// Niveau qui ACTIVE le relais (le relais « claque ») : LOW pour la plupart des modules, HIGH si cavalier sur « H ».
#define RELAY_ACTIVE     LOW

// Capteur reed de porte : un fil → D4, l'autre → GND.
// Aimant devant le capteur (porte fermée) = contact fermé ; capteur ouvert = porte ouverte.
#define DOOR_PIN         4
// Niveau lu quand la porte est OUVERTE : HIGH pour un reed « normalement ouvert » (le plus courant).
// Mettre LOW si ton capteur indique l'inverse.
#define DOOR_OPEN_LEVEL  HIGH
#define DOOR_DEBOUNCE_MS 150
// Reverrouiller (réalimenter l'aimant) dès que la porte s'ouvre : elle se bloquera en se refermant.
#define RELOCK_ON_OPEN   true
#define TOTAL_STRIP      50
#define NUM_KEYS         30
#define START_KEY_PIN    20        // clé 1 = pin 20 ... clé 30 = pin 49
#define STATUS_LED_INDEX 49

// ------------------------------------------------------------------ réglages
// Ordre des couleurs du ruban : si le rouge et le vert sont inversés, passer de RGB à GRB (ou l'inverse)
#define COLOR_ORDER      RGB
#define COLOR_ORDER_NAME "RGB"   // affiché dans le journal du serveur au démarrage
#define BRIGHTNESS       50
#define UNLOCK_MS        5000      // durée d'ouverture par défaut ; le mini-PC envoie la valeur de l'onglet Réglages
#define BLINK_MS         400       // clignotement jaune des clés à remettre
#define DEBOUNCE_MS      60        // anti-rebond des contacts de clés
#define BADGE_REPEAT_MS  2000      // ignore le même badge relu dans ce délai

// LED de chaque clé (index 0-49). Par défaut clé 1 → LED 0, clé 2 → LED 1...
const uint8_t LED_OF_KEY[NUM_KEYS] = {
   0,  1,  2,  3,  4,  5,  6,  7,  8,  9,
  10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
  20, 21, 22, 23, 24, 25, 26, 27, 28, 29
};

// Avant la première commande du mini-PC (ou s'il est éteint) : afficher quand même l'état local ?
//   false = LED éteintes, true = vert si présente / éteinte si absente (ancien comportement)
#define LOCAL_FALLBACK   false

CRGB leds[TOTAL_STRIP];

// ------------------------------------------------------------------ état
bool keyPresent[NUM_KEYS];          // état stable, envoyé au mini-PC
bool keyRaw[NUM_KEYS];              // dernière lecture brute
unsigned long keyChangedAt[NUM_KEYS];

char keyColor[NUM_KEYS];            // 'G' 'R' 'Y' 'O' — fixé par le mini-PC
bool ledsFromServer = false;        // le mini-PC a pris la main sur les LED
bool blinkPhase = false;
unsigned long lastBlink = 0;

unsigned long unlockUntil = 0;      // 0 = verrouillé
int denyFlashes = 0;
unsigned long lastFlash = 0;

// Wiegand : bits reçus par interruption
volatile uint64_t wgBits = 0;
volatile uint8_t  wgCount = 0;
volatile unsigned long wgLastBitAt = 0;
uint32_t lastCard = 0;
unsigned long lastCardAt = 0;

// retour visuel / sonore du lecteur
unsigned long readerLedUntil = 0;   // LED du lecteur allumée (vert) jusqu'à
int beepsLeft = 0;                  // nombre de demi-périodes de bip restantes
unsigned long beepToggleAt = 0;
bool beepOn = false;

char lineBuf[128];
uint8_t lineLen = 0;
bool ledsDirty = true;

void readerFeedback(bool ok);   // défini plus bas (retour LED/bip du lecteur)

// ------------------------------------------------------------------ envoi au mini-PC
void sendKey(int i) {
  Serial.print(F("{\"event\":\"key_change\",\"pin\":"));
  Serial.print(START_KEY_PIN + i);
  Serial.print(F(",\"status\":\""));
  Serial.print(keyPresent[i] ? F("PRESENT") : F("ABSENT"));
  Serial.println(F("\"}"));
}

void sendAck(const char* cmd) {
  Serial.print(F("{\"event\":\"ack\",\"cmd\":\""));
  Serial.print(cmd);
  Serial.println(F("\"}"));
}

// ------------------------------------------------------------------ électro-aimant (sécurité positive : HIGH = verrouillé)
void lockDoor()   { digitalWrite(RELAY_PIN, !RELAY_ACTIVE); unlockUntil = 0; ledsDirty = true; }                  // relais au repos : aimant alimenté
void unlockDoor(unsigned long ms) { digitalWrite(RELAY_PIN, RELAY_ACTIVE); unlockUntil = millis() + ms; if (unlockUntil == 0) unlockUntil = 1; ledsDirty = true; }  // relais activé : aimant coupé

// ------------------------------------------------------------------ capteur de porte (reed)
bool doorOpen = false;            // état stable envoyé au mini-PC
bool doorRaw = false;
unsigned long doorChangedAt = 0;

void sendDoor() {
  Serial.print(F("{\"event\":\"door\",\"status\":\""));
  Serial.print(doorOpen ? F("OPEN") : F("CLOSED"));
  Serial.println(F("\"}"));
}

void scanDoor() {
  unsigned long now = millis();
  bool raw = (digitalRead(DOOR_PIN) == DOOR_OPEN_LEVEL);
  if (raw != doorRaw) { doorRaw = raw; doorChangedAt = now; }
  if (raw != doorOpen && now - doorChangedAt >= DOOR_DEBOUNCE_MS) {
    doorOpen = raw;
    sendDoor();
    if (doorOpen && RELOCK_ON_OPEN && unlockUntil) lockDoor();   // porte ouverte : l'aimant se réalimente
  }
}

// ------------------------------------------------------------------ LED
CRGB colorOf(char c) {
  switch (c) {
    case 'G': return CRGB::Green;
    case 'R': return CRGB::Red;
    case 'Y': return blinkPhase ? CRGB(255, 160, 0) : CRGB::Black;
    default:  return CRGB::Black;
  }
}

void drawLeds() {
  for (int i = 0; i < NUM_KEYS; i++) {
    CRGB c = CRGB::Black;
    if (ledsFromServer) c = colorOf(keyColor[i]);
    else if (LOCAL_FALLBACK && keyPresent[i]) c = CRGB::Green;
    if (LED_OF_KEY[i] < TOTAL_STRIP) leds[LED_OF_KEY[i]] = c;
  }
  // voyant d'état : rouge pendant le refus, vert pendant l'ouverture, sinon éteint
  if (denyFlashes > 0)     leds[STATUS_LED_INDEX] = (denyFlashes % 2) ? CRGB::Red : CRGB::Black;
  else if (unlockUntil)    leds[STATUS_LED_INDEX] = CRGB::Green;
  else                     leds[STATUS_LED_INDEX] = CRGB::Black;
  FastLED.show();
  ledsDirty = false;
}

// ------------------------------------------------------------------ commandes JSON (sans bibliothèque)
bool jsonValue(const char* src, const char* key, char* out, uint8_t size) {
  char pattern[16];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char* p = strstr(src, pattern);
  if (!p) return false;
  p = strchr(p + strlen(pattern), ':');
  if (!p) return false;
  p = strchr(p, '"');
  if (!p) return false;
  p++;
  uint8_t n = 0;
  while (*p && *p != '"' && n < size - 1) out[n++] = *p++;
  out[n] = 0;
  return true;
}

// Valeur numérique : "cle":1234 → 1234 (ou valeur par défaut)
long jsonNumber(const char* src, const char* key, long fallback) {
  char pattern[16];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char* p = strstr(src, pattern);
  if (!p) return fallback;
  p = strchr(p + strlen(pattern), ':');
  if (!p) return fallback;
  p++;
  while (*p == ' ') p++;
  if (*p < '0' || *p > '9') return fallback;
  return atol(p);
}

void handleCommand(const char* line) {
  char cmd[16];
  if (!jsonValue(line, "cmd", cmd, sizeof(cmd))) {
    // compatibilité avec l'ancien format texte
    if (strcmp(line, "CMD:UNLOCK") == 0) strcpy(cmd, "unlock");
    else if (strcmp(line, "CMD:DENY") == 0) strcpy(cmd, "deny");
    else return;
  }
  sendAck(cmd);

  if (strcmp(cmd, "leds") == 0) {
    char map[NUM_KEYS + 1];
    if (jsonValue(line, "map", map, sizeof(map))) {
      uint8_t n = strlen(map);
      for (int i = 0; i < NUM_KEYS; i++) keyColor[i] = (i < n) ? map[i] : 'O';
      ledsFromServer = true;
    }
  } else if (strcmp(cmd, "leds_off") == 0) {
    for (int i = 0; i < NUM_KEYS; i++) keyColor[i] = 'O';
    ledsFromServer = true;
  } else if (strcmp(cmd, "unlock") == 0) {
    // durée envoyée par le mini-PC (onglet Réglages), bornée entre 0,5 s et 60 s
    long ms = jsonNumber(line, "ms", UNLOCK_MS);
    if (ms < 500) ms = 500;
    if (ms > 60000) ms = 60000;
    unlockDoor(ms);
    readerFeedback(true);
  } else if (strcmp(cmd, "lock") == 0) {
    lockDoor();
  } else if (strcmp(cmd, "deny") == 0) {
    denyFlashes = 6;          // 3 allumages + 3 extinctions
    readerFeedback(false);
    lastFlash = 0;
  } else if (strcmp(cmd, "status") == 0) {
    for (int i = 0; i < NUM_KEYS; i++) sendKey(i);
    sendDoor();
  }
  ledsDirty = true;
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) { lineBuf[lineLen] = 0; handleCommand(lineBuf); lineLen = 0; }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

// ------------------------------------------------------------------ lecteur Wiegand
void wgD0() { wgBits <<= 1;            wgCount++; wgLastBitAt = micros(); }   // impulsion sur D0 = bit 0
void wgD1() { wgBits = (wgBits << 1) | 1; wgCount++; wgLastBitAt = micros(); } // impulsion sur D1 = bit 1

// Sorties « collecteur ouvert » vers le lecteur : à la masse = actif, en haute impédance = repos.
// Ainsi l'Arduino n'envoie jamais de tension dans les fils du lecteur.
int8_t readerPinState[2] = { -1, -1 };    // dernier état appliqué (LED, BEEP)
void readerPin(int pin, bool active) {
  int8_t &st = readerPinState[pin == READER_BEEP_PIN ? 1 : 0];
  if (st == (int8_t)active) return;        // rien à changer
  st = active;
  if (active) { digitalWrite(pin, LOW); pinMode(pin, OUTPUT); }
  else        { pinMode(pin, INPUT); }
}

void readerFeedback(bool ok) {
  if (ok) { readerLedUntil = millis() + 2000; beepsLeft = 2; }   // LED verte 2 s + 1 bip
  else    { beepsLeft = 6; }                                     // 3 bips courts
  beepToggleAt = 0;
}

// Parité Wiegand : 1re moitié paire, 2e moitié impaire
bool wgParityOk(uint64_t bits, uint8_t n) {
  uint8_t half = n / 2;
  uint8_t ones = 0;
  for (uint8_t i = 0; i < half; i++) if (bits >> (n - 1 - i) & 1) ones++;
  if (ones % 2 != 0) return false;
  ones = 0;
  for (uint8_t i = half; i < n; i++) if (bits >> (n - 1 - i) & 1) ones++;
  return ones % 2 == 1;
}

void readWiegand() {
  // lecture atomique : l'interruption peut modifier wgLastBitAt pendant qu'on le lit (4 octets sur AVR)
  noInterrupts();
  uint8_t pending = wgCount;
  unsigned long lastBit = wgLastBitAt;
  interrupts();
  if (pending == 0) return;
  if (micros() - lastBit < 50000UL) return;          // trame en cours : attendre 50 ms de silence

  noInterrupts();
  uint64_t bits = wgBits;
  uint8_t n = wgCount;
  wgBits = 0;
  wgCount = 0;
  interrupts();

  if (n != 26 && n != 34) {                         // autre format (clavier, bruit) : ignoré
    Serial.print(F("Wiegand : trame de ")); Serial.print(n); Serial.println(F(" bits ignoree"));
    return;
  }
  if (!wgParityOk(bits, n)) {
    Serial.print(F("Wiegand : erreur de parite (")); Serial.print(n); Serial.println(F(" bits), rebadger"));
    return;
  }
  uint32_t card = (uint32_t)((bits >> 1) & ((n == 26) ? 0xFFFFFFUL : 0xFFFFFFFFUL));

  if (card == lastCard && millis() - lastCardAt < BADGE_REPEAT_MS) return;  // même badge relu
  lastCard = card;
  lastCardAt = millis();

  char uid[9];
  if (n == 26) snprintf(uid, sizeof(uid), "%06lX", (unsigned long)card);
  else         snprintf(uid, sizeof(uid), "%08lX", (unsigned long)card);

  Serial.print(F("{\"event\":\"badge\",\"uid\":\""));
  Serial.print(uid);
  Serial.print(F("\",\"bits\":"));
  Serial.print(n);
  Serial.println(F("}"));
}

void updateReader(unsigned long now) {
  readerPin(READER_LED_PIN, readerLedUntil && (long)(readerLedUntil - now) > 0);
  if (beepsLeft > 0 && (long)(now - beepToggleAt) >= 0) {
    beepOn = !beepOn;
    readerPin(READER_BEEP_PIN, beepOn);
    beepsLeft--;
    beepToggleAt = now + (beepOn ? 120 : 100);
    if (beepsLeft == 0) { beepOn = false; readerPin(READER_BEEP_PIN, false); }
  }
}

// ------------------------------------------------------------------ contacts de clés (avec anti-rebond)
void scanKeys() {
  unsigned long now = millis();
  for (int i = 0; i < NUM_KEYS; i++) {
    bool raw = (digitalRead(START_KEY_PIN + i) == LOW);   // LOW = contact fermé = clé présente
    if (raw != keyRaw[i]) { keyRaw[i] = raw; keyChangedAt[i] = now; }
    if (raw != keyPresent[i] && now - keyChangedAt[i] >= DEBOUNCE_MS) {
      keyPresent[i] = raw;
      sendKey(i);
      if (!ledsFromServer && LOCAL_FALLBACK) ledsDirty = true;
    }
  }
}

// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);

  digitalWrite(RELAY_PIN, !RELAY_ACTIVE); // verrouillé au démarrage (fixé avant pinMode : pas de « claquement »)
  pinMode(RELAY_PIN, OUTPUT);

  pinMode(DOOR_PIN, INPUT_PULLUP);
  doorOpen = doorRaw = (digitalRead(DOOR_PIN) == DOOR_OPEN_LEVEL);

  for (int i = 0; i < NUM_KEYS; i++) {
    pinMode(START_KEY_PIN + i, INPUT_PULLUP);
    keyPresent[i] = keyRaw[i] = (digitalRead(START_KEY_PIN + i) == LOW);
    keyChangedAt[i] = 0;
    keyColor[i] = 'O';
  }

  // lecteur Wiegand : les sorties D0/D1 du lecteur tirent vers la masse à chaque bit
  pinMode(WG_D0_PIN, INPUT_PULLUP);
  pinMode(WG_D1_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(WG_D0_PIN), wgD0, FALLING);
  attachInterrupt(digitalPinToInterrupt(WG_D1_PIN), wgD1, FALLING);
  readerPin(READER_LED_PIN, false);
  readerPin(READER_BEEP_PIN, false);

  FastLED.addLeds<WS2812B, DATA_PIN, COLOR_ORDER>(leds, TOTAL_STRIP);
  FastLED.setBrightness(BRIGHTNESS);

  // Test des couleurs au démarrage (indépendant du serveur) :
  //   1 s ROUGE, puis 1 s VERT, puis 1 s BLEU sur les 30 LED des clés.
  //   Si tu vois VERT puis ROUGE, l'ordre des couleurs est faux : changer COLOR_ORDER (RGB <-> GRB).
  CRGB testColors[3] = { CRGB(255, 0, 0), CRGB(0, 255, 0), CRGB(0, 0, 255) };
  for (int c = 0; c < 3; c++) {
    for (int i = 0; i < NUM_KEYS; i++) leds[LED_OF_KEY[i]] = testColors[c];
    FastLED.show();
    delay(1000);
  }
  for (int i = 0; i < TOTAL_STRIP; i++) leds[i] = CRGB::Black;
  FastLED.show();

  Serial.println(F("Arduino pret - sketch armoire v5 Wiegand+porte - ordre couleurs " COLOR_ORDER_NAME));
  for (int i = 0; i < NUM_KEYS; i++) sendKey(i);   // synchronise l'état des clés avec le mini-PC
  sendDoor();                                      // et l'état de la porte
}

void loop() {
  unsigned long now = millis();

  readSerial();
  readWiegand();
  updateReader(now);
  scanKeys();
  scanDoor();

  // fin d'ouverture de l'électro-aimant
  if (unlockUntil && (long)(now - unlockUntil) >= 0) lockDoor();

  // éclairs rouges du voyant (badge refusé)
  if (denyFlashes > 0 && now - lastFlash >= 150) {
    lastFlash = now;
    denyFlashes--;
    ledsDirty = true;
  }

  // clignotement jaune
  if (now - lastBlink >= BLINK_MS) {
    lastBlink = now;
    blinkPhase = !blinkPhase;
    for (int i = 0; i < NUM_KEYS; i++) if (keyColor[i] == 'Y') { ledsDirty = true; break; }
  }

  if (ledsDirty && wgCount == 0) drawLeds();   // pas pendant la réception d'un badge
}
