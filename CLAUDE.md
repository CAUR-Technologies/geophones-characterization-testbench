# Projet : Étalonnage de géophones pour ANT

Système automatisé de caractérisation de la réponse en fréquence de géophones
(0,1–100 Hz) pour l'Ambient Noise Tomography (ANT).

## Matériel

| Rôle | Modèle | Interface |
|------|--------|-----------|
| Shaker | APS 113 (ELEKTRO-SEIS), stroke ±38 mm, force max 133 N | — |
| Contrôleur position | APS 0109 (SPEKTRA) | RS232 19200 baud, terminaison `\x00` |
| Amplificateur | APS 125, 500 VA | **MANUEL** — pas de RS232 |
| Générateur | Wavetek 39A | RS232 (SCPI-like, CRLF) |
| Accéléromètre réf. | Silicon Designs 2240-005 (800 mV/g) → boîte Spektra | NI USB-6221 (nidaqmx) |
| Géophone testé (DUT) | sélectionnable (HG-5VHS, HG-6, VAS-200, ST-2A…) | **ADS1285 EVM** |

### Chaîne du signal
**Câblage parallèle**, pas série : le Wavetek est splitté et va **directement**
aux deux appareils (Signal IN du 0109 ET Signal IN du 125). Le Signal Out (BNC)
du 0109 **n'est pas utilisé**. Le 0109 sert de **moniteur de position** (zéro,
overtravel, pression) et peut **muter l'ampli via l'interface SPC 24 V**
(connecteur multi-broches arrière) sans toucher au signal AC.

```
                 ┌─► APS 0109 V (Signal IN — position monitor)  ──┐
                 │                                                 │ SPC 24 V
                 │                                                 │ (interlock)
                 ├─► APS 125 V (Signal IN — ampli) ◄───────────────┘
Wavetek ─►splitter┤                          └─► Shaker V ─► accéléro réf. V (NI ai0)
                 │
                 ├─► APS 0109 H (Signal IN — position monitor)  ──┐
                 │                                                 │ SPC 24 V
                 │                                                 │ (interlock)
                 └─► APS 125 H (Signal IN — ampli) ◄───────────────┘
                                              └─► Shaker H ─► accéléro réf. H (NI ai1)
                                                              géophone (DUT) ─► ADS1285 EVM
```

- **2 chaînes indépendantes** (V/H), chacune : contrôleur APS 0109 (position +
  interlock seulement) + ampli APS 125 + shaker APS 113 + accéléromètre de
  référence (canal NI dédié).
- Le **splitter** alimente les deux chaînes avec **une amplitude commune** (le
  Wavetek) ; chaque axe est dosé par le gain de son APS 125. Le servo d'amplitude
  ne pilote qu'**un axe à la fois** (l'accéléromètre de référence de cet axe).
- L'**interface SPC** (cf. doc APS 0109 §5.1) relie chaque 0109 à son ampli :
  outputs côté 0109 = `zero reached / Overtravel / No air / Stop` ; inputs côté
  ampli = `amplifier reset / amplifier interlock`. Si le 0109 trip une protection
  (Overtravel notamment), il **mute l'ampli** électriquement → ampli affiche 0 V/0 A
  même si le Wavetek envoie un signal.
- Pas de re-routage manuel : le logiciel bascule d'axe via le canal NI + le
  contrôleur APS correspondants.

### Lecture du géophone — architecture bridge
Le géophone est numérisé par une carte **ADS1285 EVM** de Texas Instruments,
pilotée par une DLL 32-bit (`tiPHIChar.dll`). Comme le reste du code est 64-bit :
```
gui.py / equipment (64-bit) ──TCP JSON──► bridge/bridge32.py (32-bit) ──► tiPHIChar.dll ──► ADS1285 EVM
```
Voir `bridge/` et `equipment/ads1285/`.

## Règles absolues
- **Ne jamais** modifier les knobs de l'APS 125 sans refaire l'étalonnage complet
  du banc (il n'a aucune interface série : tout changement est invisible au logiciel).
- **Toujours** vérifier l'enveloppe mécanique (`equipment/aps/shaker_physics.py`)
  avant d'envoyer un signal. La cible = intersection de trois limites :
  **déplacement** `A(f) = a/(2πf)² ≤ S_max`, **vitesse** (`v_max·2πf/g`,
  anti-saturation du géophone, calculée par géophone dans `equipment/geophones.py`)
  et **accélération** (plafond g). La limite de vitesse est désactivée pour le
  transfert banc (aucun géophone monté, `bench_transfer_ignore_velocity`).
- L'APS 0109 doit atteindre la position zéro (centrage ZER) **avant** tout signal AC.
- Adapter la **stiffness** à la fréquence : bande passante contrôleur ≪ f_test (≥ 1 décade).
- Stopper immédiatement toute séquence sur **overtravel** (`GES`).
- Constantes matérielles immuables dans `constants.py` ; réglages par installation
  dans `config.ini` (via `config/settings.py`). Ne pas dupliquer.

## Stack réel
- Python **3.11** (64-bit, version épinglée — **pas 3.12**) + un interpréteur
  **32-bit** dédié 3.11 (`C:\Python311-32`) pour `bridge32.py`. Le bridge n'a pas
  d'équivalent 3.12 32-bit → rester sur 3.11 même si un 3.12 coexiste sur la machine.
- `pyserial` (APS 0109, Wavetek), `numpy`/`scipy`, `matplotlib` (GUI Tkinter)
- `nidaqmx` (accéléromètre NI), `ctypes` (bridge ↔ DLL TI)
- Config : `config.ini` (PAS de yaml) via `config/config_manager.py`
- Pas de framework `BaseInstrument` ni de `loguru`/`pyvisa` : chaque classe
  d'instrument est autonome dans `equipment/<nom>/`.

## Organisation du code
```
constants.py                     constantes physiques/matérielles immuables
config/                          config.ini + settings.py (réglages)
equipment/
  CLAUDE.md                      physique du banc (enveloppe, stiffness, ZER)
  dsp.py                         détection cohérente / lock-in
  testbench.py                   orchestrateur TestBench (calibration)
  aps/        CLAUDE.md + aps_controller.py + shaker_physics.py
  wavetek/    CLAUDE.md + wavetek.py
  accelerometer/                 accelerometer.py (NI, mesure en g)
  ads1285/                       classe géophone (via bridge 32-bit)
  korad/      CLAUDE.md + korad.py (alimentation KA3005P, hors chaîne d'étalonnage)
bridge/                          bridge32.py + DLL TI + binaires PHI
gui.py                           interface Tkinter + matplotlib
korad_gui.py / korad_cli.py      contrôle de l'alimentation de paillasse KORAD
docs/CALIBRATION_PROTOCOL.md     protocole métrologique complet
tests/                           tests unitaires (physique, dsp…)
```

## Méthode de calibration
Deux étapes (voir `docs/CALIBRATION_PROTOCOL.md`) :
1. **Fonction de transfert du banc** `H_banc(f) = a_table(f) / V_wavetek(f)` [g/V]
   — mesurée avec l'accéléromètre de référence.
2. **Sensibilité du géophone** `H_géo(f) = V_géo(f) / (V_wavetek(f) · H_banc(f))`
   — soit, en simplifiant, `V_géo(f) / a_table(f)`.
