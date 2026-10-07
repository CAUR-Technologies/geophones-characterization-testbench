"""
Configuration centralisee — valeurs lues depuis config.ini.
Modifier config.ini (ou l'interface graphique) pour changer les parametres.
"""

import math

from config.config_manager import get

# --- ADS1285 EVM ---
ADS1285_REGISTER_MAP  = get("ADS1285", "register_map")
ADS1285_BRIDGE_PORT   = int(get("ADS1285", "bridge_port"))
ADS1285_PYTHON32_PATH = get("ADS1285", "python32_path")
ADS1285_SAMPLE_RATE   = int(get("ADS1285", "sample_rate"))
ADS1285_NUM_SAMPLES   = int(get("ADS1285", "num_samples"))
ADS1285_FULL_SCALE_VPEAK = float(get("ADS1285", "full_scale_vpeak"))

# --- Table de vibration APS ---
APS_BAUD    = int(get("APS", "baud"))
APS_TIMEOUT = float(get("APS", "timeout"))

APS_CONTROLLER_VERTICAL_PORT   = get("APS", "controller_vertical_port")
APS_CONTROLLER_HORIZONTAL_PORT = get("APS", "controller_horizontal_port")
APS_AMPLIFIER_VERTICAL_PORT    = get("APS", "amplifier_vertical_port")
APS_AMPLIFIER_HORIZONTAL_PORT  = get("APS", "amplifier_horizontal_port")
APS125_GAIN_VERTICAL           = get("APS", "amplifier_gain_vertical")
APS125_GAIN_HORIZONTAL         = get("APS", "amplifier_gain_horizontal")
APS125_CURRENT_LIMIT_VERTICAL   = get("APS", "amplifier_current_limit_vertical")
APS125_CURRENT_LIMIT_HORIZONTAL = get("APS", "amplifier_current_limit_horizontal")

# Tolerance overtravel (OTT) appliquee au demarrage de chaque controleur 0109.
# Voir config_manager pour le pourquoi (OTT=0 trippe le V sur le droop gravite).
APS_OVERTRAVEL_TOLERANCE = {
    "vertical":   int(get("APS", "overtravel_tolerance_vertical")),
    "horizontal": int(get("APS", "overtravel_tolerance_horizontal")),
}

# OTT TRANSITOIRE de demarrage (large) par axe ; 0 = STA simple (horizontal).
# Permet un STA vertical hands-free : large pendant la plongee gravite, puis
# resserrage a APS_OVERTRAVEL_TOLERANCE apres start_settle_s.
APS_OVERTRAVEL_START = {
    "vertical":   int(get("APS", "overtravel_tolerance_start_vertical")),
    "horizontal": int(get("APS", "overtravel_tolerance_start_horizontal")),
}
APS_OVERTRAVEL_START_SETTLE_S = float(get("APS", "overtravel_start_settle_s"))

# --- Wavetek Model 39A ---
WAVETEK_PORT    = get("Wavetek", "port")
WAVETEK_BAUD    = int(get("Wavetek", "baud"))
WAVETEK_TIMEOUT = float(get("Wavetek", "timeout"))

# --- Alimentation KORAD KA3005P ---
KORAD_PORT    = get("Korad", "port")
KORAD_BAUD    = int(get("Korad", "baud"))
KORAD_TIMEOUT = float(get("Korad", "timeout"))

# --- Accelerometres (NI USB-6221) ---
NI_DEVICE_NAME        = get("NI", "device_name")
NI_AI_CHANNELS        = get("NI", "ai_channels")
NI_SAMPLE_RATE        = int(get("NI", "sample_rate"))
NI_SAMPLES_PER_CHANNEL = int(get("NI", "samples_per_channel"))
NI_REF_CHANNEL_VERTICAL   = int(get("NI", "ref_channel_vertical"))
NI_REF_CHANNEL_HORIZONTAL = int(get("NI", "ref_channel_horizontal"))

# --- Banc shaker / calibration geophone ---
SHAKER_STROKE_MM          = float(get("Shaker", "stroke_mm"))
SHAKER_ENVELOPE_FRACTION  = float(get("Shaker", "envelope_fraction"))
SHAKER_ACCEL_CAP_G        = float(get("Shaker", "accel_cap_g"))
SHAKER_ACCEL_FLOOR_G      = float(get("Shaker", "accel_floor_g"))
SHAKER_GEOPHONE_MAX_VELOCITY_MPS = float(get("Shaker", "geophone_max_velocity_mps"))
SHAKER_GEOPHONE_VELOCITY_SAFETY = float(get("Shaker", "geophone_velocity_safety"))
SHAKER_BENCH_IGNORE_VELOCITY = (
    get("Shaker", "bench_transfer_ignore_velocity").strip().lower()
    in ("1", "true", "yes", "oui", "on"))
ACCEL_SENSITIVITY_V_PER_G = float(get("Shaker", "accel_sensitivity_v_per_g"))
SHAKER_SERVO_TOLERANCE    = float(get("Shaker", "servo_tolerance"))
SHAKER_SERVO_MAX_ITER     = int(get("Shaker", "servo_max_iter"))
SHAKER_SERVO_START_VPP    = float(get("Shaker", "servo_start_vpp"))
SHAKER_SERVO_VPP_MAX      = float(get("Shaker", "servo_vpp_max"))
SHAKER_SERVO_MAX_STEP     = float(get("Shaker", "servo_max_step"))
SHAKER_GEOPHONE           = get("Shaker", "geophone")


def _parse_stiffness_schedule(spec: str):
    """'10:3, 50:5, *:8' -> [(10.0, 3), (50.0, 5), (inf, 8)] (trié par seuil).

    Retourne None si le format est invalide (le code retombe alors sur le
    barème par défaut de shaker_physics)."""
    try:
        bands = []
        for part in spec.split(","):
            thr_s, val_s = part.split(":")
            thr_s = thr_s.strip()
            thr = math.inf if thr_s == "*" else float(thr_s)
            bands.append((thr, int(val_s.strip())))
        bands.sort(key=lambda b: b[0])
        return bands or None
    except Exception:
        return None


SHAKER_STIFFNESS_SCHEDULE = {
    "vertical":   _parse_stiffness_schedule(get("Shaker", "stiffness_vertical")),
    "horizontal": _parse_stiffness_schedule(get("Shaker", "stiffness_horizontal")),
}

# Acquisition adaptative en fréquence (meilleur SNR en basse fréquence).
SHAKER_ACQ_MIN_CYCLES     = int(get("Shaker", "acq_min_cycles"))
SHAKER_ACQ_MAX_DURATION_S = float(get("Shaker", "acq_max_duration_s"))

# --- Acquisition generale ---
DATA_OUTPUT_DIR = get("General", "data_output_dir")
