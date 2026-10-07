# CLAUDE.md

## Matériel : KORAD KA3005P — alimentation de laboratoire 0-30 V / 0-5 A

Alimentation programmable monovoie, utilisée comme source d'alimentation de
paillasse (unités géophone, cartes CAUR, électronique de test). Elle **ne fait
pas partie de la chaîne d'étalonnage du banc** : aucune de ses valeurs n'entre
dans `H_banc` ni dans `H_géo`.

> Protocole vérifié en direct sur l'appareil (firmware **V1.5**, SN 01639635)
> le 2026-09-22. Le jeu de commandes est celui de la famille KA30xxP, partagé
> avec les clones Tenma 72-2535, RND 320 et Velleman LABPS3005D.

### Liaison série (USB)
- Pont USB-série **Nuvoton, VID:PID `0416:5011`** — pilote détectable sans
  configuration (`KoradKA3005P.find_ports()`), d'où `port = auto` par défaut.
- 9600 baud, 8 bits, parité aucune, 1 stop, **aucun contrôle de flux**.
- ⚠️ **Aucun terminateur**, ni à l'émission ni à la réception : ni CR, ni LF.
  On lit donc par **longueur attendue** (5 octets pour les valeurs, 1 pour le
  statut) et par timeout pour `*IDN?` dont la longueur varie.
- Laisser **≥ 50 ms entre deux commandes** (`_CMD_GAP_S`) : l'appareil ignore
  silencieusement les commandes trop rapprochées.

### Commandes utilisées par le driver

| Fonction | Commande | Réponse |
|----------|----------|---------|
| Identification | `*IDN?` | `KORAD KA3005P V1.5 SN:01639635` |
| Statut | `STATUS?` | 1 octet de bits |
| Consigne tension | `VSET1:12.34` / `VSET1?` | `12.34` (2 décimales) |
| Consigne courant | `ISET1:1.234` / `ISET1?` | `1.234` (3 décimales) |
| Tension mesurée | `VOUT1?` | `12.34` |
| Courant mesuré | `IOUT1?` | `1.234` |
| Sortie | `OUT1` / `OUT0` | — |
| Protections | `OVP1`/`OVP0`, `OCP1`/`OCP0` | — |
| Bip touches | `BEEP1` / `BEEP0` | — |
| Mémoires | `SAV1..5` / `RCL1..5` | — |

Le suffixe `1` est le numéro de voie : le KA3005P n'en a qu'une.

### Octet de statut (`STATUS?`)

| Bit | Signification |
|-----|---------------|
| 0 | mode voie 1 : **1 = CV**, 0 = CC |
| 1 | mode voie 2 (inexistant ici) |
| 2-3 | tracking série/parallèle (multi-voies, sans objet) |
| 4 | bip touches actif |
| 5 | verrouillage clavier (interprétation variable selon firmware) |
| 6 | **sortie activée** |
| 7 | réservé |

⚠️ L'état **OVP/OCP n'est pas relisible** de façon fiable via `STATUS?` sur ce
firmware. Le pilote mémorise localement la dernière valeur envoyée
(`ovp_enabled` / `ocp_enabled`) ; après une coupure secteur, cet état est
inconnu — le renvoyer explicitement.

### Pièges connus
- `STATUS?` peut renvoyer l'octet `0x00`, qu'un `strip()` réduit à une chaîne
  vide : ne **pas** en conclure à une absence de réponse (cas couvert par le
  test `test_status_zero_byte_is_decoded`).
- Certains firmwares ajoutent un octet parasite en fin de réponse numérique ;
  le parsing filtre les caractères non numériques avant conversion.
- Le mode **CC** (bit 0 à 0) signale que la limite de courant est atteinte :
  la tension de sortie n'est alors plus celle de la consigne.

### Interfaces
- `python korad_gui.py` — interface Tkinter (sortie, consignes, mesures en
  continu, protections, mémoires).
- `python korad_cli.py <commande>` — ligne de commande, dont
  `monitor --csv <fichier>` pour journaliser la consommation.
- `from equipment.korad import KoradKA3005P` — usage programmatique, gestion de
  contexte (`with`) et lecture groupée `read_all()`.
