# Protocole série Arduino ⇄ serveur

Liaison USB à **115200 bauds**, une trame **JSON par ligne** (`\n`). Les lignes qui ne commencent pas par `{`
(messages de démarrage, diagnostics) sont seulement affichées dans le journal du service.

## Arduino → serveur

| Trame | Signification |
|---|---|
| `{"event":"badge","uid":"B3063709","bits":34}` | Badge lu (UID hexadécimal majuscule ; 34 bits = WG34, 26 bits = WG26) |
| `{"event":"key_change","pin":24,"status":"ABSENT"}` | Clé retirée (`PRESENT` = remise). `pin` 20-49 = clés 1-30 |
| `{"event":"door","status":"OPEN"}` | Porte ouverte (`CLOSED` = fermée) |
| `{"event":"ack","cmd":"leds"}` | Accusé de réception d'une commande |

Au démarrage, l'Arduino envoie l'état des 30 clés et de la porte (synchronisation, sans entrée au journal).

## Serveur → Arduino

| Commande | Effet |
|---|---|
| `{"cmd":"unlock","ms":5000}` | Active le relais `ms` millisecondes (porte déverrouillée), voyant vert, bip du lecteur |
| `{"cmd":"lock"}` | Relais au repos (porte verrouillée) |
| `{"cmd":"leds","map":"GGRYOO…"}` | Une lettre par clé 1→30 : `G` vert, `R` rouge, `Y` jaune clignotant, `O` éteinte |
| `{"cmd":"leds_off"}` | Éteint les LED des clés |
| `{"cmd":"deny"}` | Badge refusé : 3 éclairs rouges du voyant, 3 bips |
| `{"cmd":"status"}` | Demande l'état complet (clés + porte) |

Le serveur renvoie une commande non confirmée par `ack` (jusqu'à 3 essais, 0,8 s d'intervalle) : FastLED coupe
les interruptions pendant la mise à jour du ruban et un caractère reçu à ce moment peut être perdu.

## Logique côté serveur (`armoire.py`)

1. Badge actif → session (`session_s`), `unlock` avec la durée réglée.
2. Porte ouverte → LED allumées : vert / rouge, jaune pour les clés que cette personne avait prises lors d'un
   passage précédent. Clés non paramétrées (sans nom) : `O`.
3. Clé retirée pendant la session → emprunt au nom de la personne (table `key_loan`) ; sans session → « Non identifié » + alerte.
4. Clé remise → emprunt clôturé (« remise par … »).
5. Porte refermée → fin de session, `lock`, LED éteintes.
