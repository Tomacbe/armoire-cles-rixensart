/*
  TEST DU LECTEUR WIEGAND — sans bibliothèque
  Branchement :
    Rouge  (+12 V) → + alimentation 12 V
    Noir   (GND)   → − alimentation 12 V  ET  GND de l'Arduino   ← indispensable
    Vert   (D0)    → pin 2 du Mega
    Blanc  (D1)    → pin 3 du Mega
  Moniteur série : 115200 bauds.
*/
#define PIN_D0 2
#define PIN_D1 3

volatile uint64_t bits = 0;
volatile uint8_t count = 0;
volatile unsigned long lastBit = 0;
volatile unsigned long pulsesD0 = 0, pulsesD1 = 0;

void onD0() { bits <<= 1;            count++; pulsesD0++; lastBit = micros(); }
void onD1() { bits = (bits << 1) | 1; count++; pulsesD1++; lastBit = micros(); }

bool parityOk(uint64_t b, uint8_t n) {           // 1re moitié paire, 2e moitié impaire
  uint8_t half = n / 2, ones = 0;
  for (uint8_t i = 0; i < half; i++) if ((b >> (n - 1 - i)) & 1) ones++;
  if (ones % 2) return false;
  ones = 0;
  for (uint8_t i = half; i < n; i++) if ((b >> (n - 1 - i)) & 1) ones++;
  return ones % 2 == 1;
}

void printHex(uint32_t v, uint8_t digits) {
  for (int8_t i = digits - 1; i >= 0; i--) Serial.print((v >> (i * 4)) & 0xF, HEX);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_D0, INPUT_PULLUP);
  pinMode(PIN_D1, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_D0), onD0, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_D1), onD1, FALLING);

  Serial.println(F("=== Test lecteur Wiegand ==="));
  Serial.print(F("Lignes au repos : D0 (pin 2) = "));
  Serial.print(digitalRead(PIN_D0) ? F("HAUT") : F("BAS"));
  Serial.print(F(", D1 (pin 3) = "));
  Serial.println(digitalRead(PIN_D1) ? F("HAUT") : F("BAS"));
  Serial.println(F("(les deux doivent etre HAUT au repos)"));
  Serial.println(F("Passe un badge devant le lecteur..."));
}

void loop() {
  // lecture atomique : l'interruption peut modifier lastBit pendant qu'on le lit (4 octets sur AVR)
  noInterrupts();
  uint8_t c = count;
  unsigned long lb = lastBit;
  interrupts();
  if (c > 0 && micros() - lb > 50000UL) {            // 50 ms sans bit = fin de trame
    noInterrupts();
    uint64_t b = bits; uint8_t n = count;
    unsigned long p0 = pulsesD0, p1 = pulsesD1;
    bits = 0; count = 0; pulsesD0 = 0; pulsesD1 = 0;
    interrupts();

    Serial.print(F("\nTrame recue : ")); Serial.print(n); Serial.print(F(" bits  ("));
    Serial.print(p0); Serial.print(F(" sur D0, ")); Serial.print(p1); Serial.println(F(" sur D1)"));

    Serial.print(F("Binaire : "));
    for (int8_t i = n - 1; i >= 0; i--) Serial.print((uint8_t)((b >> i) & 1));
    Serial.println();

    if (n == 26 || n == 34) {
      uint32_t card = (uint32_t)((b >> 1) & (n == 26 ? 0xFFFFFFUL : 0xFFFFFFFFUL));
      Serial.print(F("Format WG")); Serial.print(n);
      Serial.print(F("  parite : ")); Serial.println(parityOk(b, n) ? F("OK") : F("ERREUR"));
      Serial.print(F("UID (hexa) : ")); printHex(card, n == 26 ? 6 : 8); Serial.println();
      Serial.print(F("UID (decimal) : ")); Serial.println(card);
      if (n == 26) Serial.println(F("-> WG26 : 24 bits seulement. Change la position du fil gris pour avoir WG34."));
    } else if (n == 4 || n == 8) {
      Serial.println(F("-> Trame courte : touche de clavier ?"));
    } else {
      Serial.println(F("-> Nombre de bits inhabituel : verifier la masse commune et le cablage."));
    }
  }
}
