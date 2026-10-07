"""
Gestionnaire de configuration INI persistante.

Le fichier config.ini est cree automatiquement avec les valeurs par defaut
au premier lancement, puis modifie par l'interface graphique.

Emplacement :
  - Executable PyInstaller : meme dossier que l'exe
  - Source Python         : racine du projet (dossier parent de config/)
"""

import configparser
import os
import sys

# Racine du projet (fonctionne en mode source ET en mode bundle PyInstaller)
if getattr(sys, "frozen", False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(_BASE_DIR, "config.ini")

# -----------------------------------------------------------------------
# Valeurs par defaut
# -----------------------------------------------------------------------
_DEFAULTS: dict[str, dict[str, str]] = {
    "ADS1285": {
        "bridge_port":     "9500",
        "sample_rate":     "4000",
        "num_samples":     "1024",
        "register_map":    r"C:\Program Files (x86)\Texas Instruments\ADS1285 EVM\Register Map.xml",
        "python32_path":   r"C:\Python311-32\python.exe",
        # Tension crete pleine echelle de l'entree (V) a la PGA gain utilisee.
        # ADS1285 : +/-2,5 V a gain 1 (independant de VREF). Diviser par le gain
        # PGA si un gain > 1 est programme. Sert au calcul de la vitesse max
        # geophone (anti-saturation).
        "full_scale_vpeak": "2.5",
    },
    "APS": {
        "baud":                       "19200",   # APS 0109 : 19200 baud (spec)
        "timeout":                    "2.0",
        "controller_vertical_port":   "COM3",
        "controller_horizontal_port": "COM4",
        "amplifier_vertical_port":    "COM5",
        "amplifier_horizontal_port":  "COM6",
        # Knobs de l'ampli APS 125 — saisie manuelle (ampli sans interface serie),
        # traces avec chaque etalonnage (regle d'invalidation "knobs modifies").
        # gain : Variable Gain (dB) -> definit H_banc.
        # current_limit : Current Limit A(RMS) -> protection, tracee pour
        #   tracabilite/diagnostic d'ecretage (n'entre pas dans le calcul).
        "amplifier_gain_vertical":          "",
        "amplifier_gain_horizontal":        "",
        "amplifier_current_limit_vertical":   "",
        "amplifier_current_limit_horizontal": "",
        # Tolerance overtravel (OTT, 0..1023) appliquee au demarrage de chaque
        # controleur. OTT=0 = trip au moindre ecart de position : sur l'axe
        # VERTICAL l'armature flue sous la gravite jusqu'a un petit creux
        # d'equilibre, donc OTT=0 trippe avant que le controleur ait developpe
        # sa force de maintien. OTT=50 (~4x le creux a vide) tient le droop tout
        # en restant loin de la butee +/-38 mm. L'axe HORIZONTAL ne droope pas
        # (pas de gravite sur son axe) -> OTT=0 suffit. Re-applique a chaque
        # connect car un power-cycle / RST usine du 0109 le remet a 0.
        "overtravel_tolerance_vertical":   "50",
        "overtravel_tolerance_horizontal": "0",
        # Démarrage hands-free de l'axe vertical via OTT TRANSITOIRE : au STA
        # souple l'armature plonge sous la gravité avant que le contrôleur ne
        # développe sa force ; la plongée dépasse l'OTT opérationnel et arme un
        # trip. On élargit donc l'OTT le temps que le contrôleur ramène l'armature
        # à zéro (start_settle_s), puis on resserre à overtravel_tolerance_*.
        # 0 = pas de séquence transitoire (STA simple) : cas de l'horizontal, qui
        # ne plonge pas. Évite de tenir l'armature à la main et tout SSS élevé
        # (donc aucun risque de slam en butée).
        # Settle long (15 s) : avec une charge (support géophone) le centrage
        # vertical est plus lent ; l'OTT doit rester large assez longtemps sinon
        # il se resserre avant que l'armature soit centrée → trip. start_vertical
        # élargi à 600 pour couvrir l'excursion de centrage chargé.
        "overtravel_tolerance_start_vertical":   "600",
        "overtravel_tolerance_start_horizontal": "0",
        "overtravel_start_settle_s":             "15.0",
    },
    "Wavetek": {
        "port":    "COM5",
        "baud":    "9600",
        "timeout": "2.0",
    },
    "NI": {
        "device_name":        "Dev1",
        "ai_channels":        "ai0,ai1",
        "sample_rate":        "10000",
        "samples_per_channel": "1000",
        # Index (dans ai_channels) de l'accelerometre de reference par axe :
        # un accelero par axe (ex. ai0=V -> 0, ai1=H -> 1).
        "ref_channel_vertical":   "0",
        "ref_channel_horizontal": "1",
    },
    "Shaker": {
        # APS 113 : demi-course mecanique +/-38 mm
        "stroke_mm":                 "38.0",
        # Fraction de l'enveloppe stroke visee (marge de securite overtravel)
        "envelope_fraction":         "0.6",
        # Plafond absolu d'acceleration en haute frequence (g)
        "accel_cap_g":               "1.0",
        # Acceleration plancher (g) — en dessous, point ignore (cible trop faible).
        # Tres bas pour autoriser les geophones tres sensibles aux basses freq.
        # (la qualite reelle est signalee par le SNR, pas par ce plancher).
        "accel_floor_g":             "0.0002",
        # Vitesse crete max (m/s) de SECOURS pour un geophone inconnu (absent de
        # equipment/geophones.py). Pour les geophones connus, v_max est calcule
        # automatiquement depuis leur sensibilite/amortissement.
        "geophone_max_velocity_mps": "0.01",
        # Fraction de la pleine echelle ADC visee au pic de reponse du geophone
        # (marge anti-saturation : 0,5 = sortie max a 50 % de la pleine echelle).
        "geophone_velocity_safety":  "0.5",
        # Ignorer la limite de vitesse pour le transfert banc / verif quotidienne.
        # true : aucun geophone monte pendant l'etalonnage du banc -> exciter a
        # pleine amplitude (enveloppe stroke/accel) pour un meilleur SNR de H_banc.
        "bench_transfer_ignore_velocity": "true",
        # Sensibilite chaine accelerometre NI : Silicon Designs 2240-005 = 800 mV/g.
        # Si la boite Spektra applique un gain, ajuster cette valeur.
        "accel_sensitivity_v_per_g": "0.8",
        # Servo d'amplitude en boucle fermee (volts Wavetek -> g mesure)
        "servo_tolerance":           "0.05",   # tolerance relative (5%)
        "servo_max_iter":            "8",       # iterations max du servo
        "servo_start_vpp":           "0.1",     # amplitude Wavetek de depart (Vpp)
        # Plafond d'amplitude Wavetek (Vpp). Au-dela, le servo declare la cible
        # inatteignable a ce gain APS 125 (sortie anticipee). 10 Vpp = sortie
        # typique max du 39A sur charge ouverte.
        "servo_vpp_max":             "10.0",
        # RATIO multiplicatif max de montée Vpp par itération du servo
        # (vpp_suivant = vpp * min(cible/mesuré, servo_max_step)). DOIT être > 1
        # sinon le servo ne peut jamais augmenter l'amplitude. 2.0 = montée douce
        # (×2 max/itér, vs ×3 d'origine) -> évite un claquage du Vpp à gain max.
        "servo_max_step":            "2.0",
        # Modele de geophone candidat en cours de test (metadonnee calibration)
        "geophone":                  "HG-5VHS",
        # Bareme de rigidite (STF) par axe, adapte a la frequence. Format :
        # "<seuil_Hz>:<STF>, ..., *:<STF>"  (STF applique si f < seuil ; '*' = au-dela).
        # Reglable par axe car le vertical (gravite) peut differer de l'horizontal.
        # A STF eleve le controleur annule la vibration ; trop bas -> derive.
        "stiffness_vertical":        "10:3, 50:5, *:8",
        "stiffness_horizontal":      "10:3, 50:5, *:8",
        # Acquisition ADAPTATIVE en fréquence (essentiel en basse fréquence).
        # La fenêtre d'acquisition (géophone + accéléro) est allongée en BF pour
        # capturer >= acq_min_cycles cycles -> le lock-in moyenne sur plus de
        # cycles -> meilleur SNR (sinon < 1 cycle sous 1 Hz). Plafonnée à
        # acq_max_duration_s pour borner la durée du balayage (ex. 0,1 Hz, 4
        # cycles = 40 s/point). En haute fréquence la fenêtre de base suffit.
        "acq_min_cycles":            "4",
        "acq_max_duration_s":        "60.0",
    },
    "Korad": {
        # Alimentation KORAD KA3005P (USB-serie Nuvoton VID:PID 0416:5011).
        # port = "auto" -> detection par VID:PID ; sinon COMx explicite.
        "port":    "auto",
        "baud":    "9600",
        "timeout": "0.5",
    },
    "General": {
        "data_output_dir": "data",
    },
}

_cfg = configparser.ConfigParser()


def load() -> None:
    """Charge config.ini ; cree le fichier avec les defauts si absent."""
    if os.path.exists(CONFIG_FILE):
        _cfg.read(CONFIG_FILE, encoding="utf-8")

    modified = False
    for section, values in _DEFAULTS.items():
        if not _cfg.has_section(section):
            _cfg.add_section(section)
            modified = True
        for key, val in values.items():
            if not _cfg.has_option(section, key):
                _cfg.set(section, key, val)
                modified = True

    if modified:
        save()


def save() -> None:
    """Ecrit config.ini sur disque."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        _cfg.write(fh)


def get(section: str, key: str) -> str:
    return _cfg.get(section, key)


def set_value(section: str, key: str, value: str) -> None:
    if not _cfg.has_section(section):
        _cfg.add_section(section)
    _cfg.set(section, key, str(value))


# Charge au premier import
load()
