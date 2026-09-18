"""
Tests de la corrélation 3 axes en voie STREAM (Characterize3AxisSession).

Valide la MATH de `measure_point_stream` (co-acquisition + lock-in par voie →
sensibilité) sur des sinus synthétiques, sans matériel : bench et unité mockés.

Lancer : python tests/test_characterize3axis.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equipment.geophone3axis.session import Characterize3AxisSession

F = 10.0                     # fréquence d'excitation (Hz)
SENS_V_PER_G = 0.8           # sensibilité chaîne accéléro (V/g)
ACCEL_G = 0.1                # accélération table imposée (g)
G = 9.80665
COUNTS_PEAK = {"1": 1_000_000.0, "2": 500_000.0, "3": 200_000.0}


class _MockAccel:
    """Accéléro renvoyant un sinus pur à F, amplitude = ACCEL_G·SENS (volts)."""
    sensitivity_v_per_g = SENS_V_PER_G
    sample_rate = 1000

    def acquire_seconds(self, duration_s, sample_rate=None):
        fs = sample_rate or self.sample_rate
        n = int(fs * duration_s)
        t = np.arange(n) / fs
        ref = ACCEL_G * SENS_V_PER_G * np.sin(2 * np.pi * F * t)
        return np.vstack([ref, np.zeros(n)])   # (2 voies, N) ; ref = voie 0


class _MockUnit:
    """Unité 3 axes renvoyant 3 sinus purs à F (amplitudes COUNTS_PEAK)."""
    def stream_geo(self, duration_s, rate_hz=50):
        fs = 50.0
        n = int(fs * duration_s)
        t = np.arange(n) / fs
        chans = {ch: (amp * np.sin(2 * np.pi * F * t)).astype(np.int64)
                 for ch, amp in COUNTS_PEAK.items()}
        return fs, chans


class _MockBench:
    def __init__(self):
        self._accel = _MockAccel()
        self._ref_channel = 0


def approx(a, b, tol=2e-2):
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def test_measure_point_stream_sensitivity():
    """Lock-in par voie → accel_g, vitesse table et sensibilité correctes."""
    sess = Characterize3AxisSession(_MockBench(), _MockUnit(),
                                    gnss=None, pps=None, data_dir="data/3axis")
    r = sess.measure_point_stream(F, n_cycles=10, excite=False)

    assert not r["skipped"]
    assert approx(r["accel_g"], ACCEL_G)
    exp_v = ACCEL_G * G / (2 * np.pi * F)          # v = a/(2πf)
    assert approx(r["table_velocity_mps"], exp_v)

    for ch, amp in COUNTS_PEAK.items():
        c = r["channels"][ch]
        assert approx(c["counts_peak"], amp), (ch, c["counts_peak"], amp)
        assert approx(c["sens_counts_per_g"], amp / ACCEL_G)
        assert approx(c["sens_counts_per_mps"], amp / exp_v)


def test_skipped_point_out_of_envelope():
    """Un point hors enveloppe (excite=True → set_frequency_safe skipped) remonte."""
    class _BenchSkip(_MockBench):
        def set_frequency_safe(self, freq_hz, target_g=None):
            return {"skipped": True, "note": "hors course"}
    sess = Characterize3AxisSession(_BenchSkip(), _MockUnit(), None, None, "data/3axis")
    r = sess.measure_point_stream(0.1, excite=True)
    assert r["skipped"] and r["channels"] == {}


def test_correlate_gps_aligned():
    """Corrélation TEMPS-GPS : sensibilité ET phase récupérées sur deux signaux
    datés en temps GPS mais échantillonnés sur des HORLOGES DIFFÉRENTES (fs et
    instants de départ distincts) — ce que fait le banc (unité .dat vs accéléro NI)."""
    from equipment.geophone3axis.dat_reader import Channel3Axis
    F, SENS_V_PER_G, G = 8.0, 0.8, 9.80665
    lsb_v = 2.048 / 1 / (2 ** 31)
    ACCEL_G = 0.05
    vel = ACCEL_G * G / (2 * np.pi * F)
    COUNTS_PK = 1.5e6
    PH_UNIT, PH_REF = np.deg2rad(30.0), np.deg2rad(-10.0)   # phases vs GPS t=0

    sod0 = 45000.0
    t_end = sod0 + 10.0
    # Référence NI : fs 500 Hz, départ sod0.
    tr = sod0 + np.arange(int((t_end - sod0) * 500.0)) / 500.0
    ref = ACCEL_G * SENS_V_PER_G * np.sin(2 * np.pi * F * tr + PH_REF)   # volts
    # Unité : fs 250 Hz, départ décalé de 0,137 s (horloge différente).
    u0 = sod0 + 0.137
    tu = u0 + np.arange(int((t_end - u0) * 250.0)) / 250.0
    counts = (COUNTS_PK * np.sin(2 * np.pi * F * tu + PH_UNIT)).astype(np.int64)
    ch = Channel3Axis(channel_id="1", data=counts,
                      start_time_ns=int(u0 * 1e9), sample_rate_hz=250.0)

    sess = Characterize3AxisSession.__new__(Characterize3AxisSession)  # sans matériel
    schedule = [{"freq_hz": F, "sod_start": sod0 + 0.5, "sod_end": t_end - 0.5}]
    res = sess.correlate(schedule, ref, tr, sens_v_per_g=SENS_V_PER_G, lsb_v=lsb_v,
                         unit_channels=[ch])
    r = res["1"][F]
    assert approx(r["accel_g"], ACCEL_G, tol=0.03), r["accel_g"]
    assert approx(r["sens_counts_per_mps"], COUNTS_PK / vel, tol=0.03)
    assert approx(r["sens_v_per_mps"], COUNTS_PK * lsb_v / vel, tol=0.03)
    exp_phase = np.rad2deg(PH_UNIT - PH_REF)   # = 40°, le -π/2 des sinus s'annule
    assert abs(r["phase_deg"] - exp_phase) < 2.0, (r["phase_deg"], exp_phase)


class _RecUnit:
    """Unité mockée pour la garde `start_unit` : `ls` grandit si `recording`."""
    def __init__(self, recording: bool):
        self.recording = recording
        self._n = 3
        self.stopped = False
    def start(self): pass
    def stop(self): self.stopped = True
    def sync(self): pass
    def ls(self, path=""):
        if self.recording:
            self._n += 1        # de nouveaux .dat apparaissent
        return [{"path": f"f{i}"} for i in range(self._n)]


def test_start_unit_verify_ok():
    """Enregistrement qui démarre : `start_unit` confirme (retour sans exception)."""
    sess = Characterize3AxisSession(_MockBench(), _RecUnit(recording=True),
                                    None, None, "data/3axis")
    sess.start_unit("/survey-data/Run", verify_timeout_s=4.0)   # ne lève pas


def test_start_unit_verify_aborts_when_no_files():
    """Firmware « OK START » mais AUCUN fichier → abort explicite (anti-sweep à vide)."""
    from equipment.testbench import TestBenchAborted
    u = _RecUnit(recording=False)
    sess = Characterize3AxisSession(_MockBench(), u, None, None, "data/3axis")
    try:
        sess.start_unit("/survey-data/Run", verify_timeout_s=3.0)
        raise AssertionError("aurait dû lever TestBenchAborted")
    except TestBenchAborted:
        assert u.stopped, "doit STOP l'unité avant d'abandonner"


def test_read_dat_tolerates_corrupt_record():
    """Un record corrompu (CRC fail — corruption de transfert GET/CDC observée sur
    1 fichier/134) ne doit PAS jeter tout le fichier : on garde les BONS records lus
    avant, et le run reste exploitable."""
    try:
        from simplemseed import MSeed3Record, MSeed3Header
    except ImportError:
        return   # simplemseed absent : test sauté
    import datetime, tempfile, os
    from equipment.geophone3axis.dat_reader import read_dat

    def _rec(ch, t):
        h = MSeed3Header(); h.sampleRatePeriod = 250.0
        h.starttime = datetime.datetime(2026, 8, 12, 14, 0, t, tzinfo=datetime.timezone.utc)
        return MSeed3Record(h, "FDSN:XX_STA_00_H_H_1",
                            np.arange(250, dtype=np.int32),
                            extraHeaders={"caurtech": {"channel": ch}}).pack()

    good1, good2 = _rec("1", 0), _rec("1", 1)
    # Deux modes de corruption réellement observés au banc, selon l'octet touché :
    #   -4  = zone data      -> CRC fail (Miniseed3Exception)
    #   55  = identifiant/eh -> décodage UTF-8 invalide (UnicodeDecodeError)
    for offset, val in ((-4, None), (55, 0xBB)):
        bad = bytearray(_rec("1", 2))
        bad[offset] = (bad[offset] ^ 0xFF) if val is None else val
        path = os.path.join(tempfile.gettempdir(), "test_corrupt_3axis.dat")
        with open(path, "wb") as fp:
            fp.write(good1 + good2 + bytes(bad))
        try:
            chans = read_dat(path)
        finally:
            os.remove(path)
        assert chans, f"offset {offset} : doit récupérer une voie malgré la corruption"
        c = chans[0]
        assert len(c.data) == 500, (offset, len(c.data), "2 bons records (2×250) conservés")
        assert c.meta["file"].get("records_skipped") == 1, offset


def test_segment_correlate_recovers_sweep():
    """`segment_correlate` retrouve la sensibilité par voie sur un balayage
    synthétique (3 paliers concaténés dans le temps), SANS sods de référence —
    c'est ce qui sauve un run quand la GNSS de réf. perd son fix."""
    from equipment.geophone3axis.session import segment_correlate
    fs = 250.0
    lsb_v = 2.5 / (2 ** 31)
    sweep = [(20.0, 150.0, 0.0060), (10.0, 150.0, 0.0058), (5.0, 240.0, 0.0062)]
    #         freq   sens_cible    vitesse (pic à 5 Hz)
    t_all, x1 = [], []
    sod = 50000.0
    for f, sens, v in sweep:
        n = int(fs * 8.0)                      # 8 s par palier
        t = sod + np.arange(n) / fs
        counts = sens * v / lsb_v              # amplitude counts pour cette sensib.
        x1.append(counts * np.sin(2 * np.pi * f * (t - sod)))
        t_all.append(t)
        # gap de settling (2 s quasi-silence) entre paliers, comme le servo au banc
        # → sépare proprement les paliers (pas de dilution en frontière au lock-in).
        sod = t[-1] + 1 / fs
        ng = int(fs * 2.0)
        tg = sod + np.arange(ng) / fs
        x1.append(np.zeros(ng))
        t_all.append(tg)
        sod = tg[-1] + 1 / fs
    T = np.concatenate(t_all)
    X1 = np.concatenate(x1)
    chan_t = {"1": T, "2": T, "3": T}
    chan_x = {"1": X1, "2": X1 * 0.02, "3": X1 * 0.03}   # 2,3 = fuite transverse
    vel = {f: v for f, _, v in sweep}
    dat = segment_correlate(chan_t, chan_x, [f for f, _, _ in sweep], vel, lsb_v)

    for f, sens, _ in sweep:
        got = dat["1"][f]["sens_v_per_mps"]
        assert approx(got, sens, tol=0.05), (f, got, sens)
    # voie sur-axe = 1 (plus forte), transverse ~2-3 %
    assert dat["1"][5.0]["counts_peak"] > 20 * dat["2"][5.0]["counts_peak"]


def test_time_offset_from_phase_slope():
    """TIME-05 : l'offset d'horloge unité↔référence se retrouve par la pente de la
    rampe de phase HF (360·f·Δt par-dessus la phase capteur plate)."""
    from tools.time_offset import clock_offset_from_phases
    dt_us = 180.0
    phases = {f: -8.0 + 360.0 * f * (dt_us * 1e-6) + 0.3 * np.sin(f)
              for f in (20, 30, 50, 70, 100)}
    r = clock_offset_from_phases(phases, f_min_hz=20.0)
    assert r is not None and abs(r["offset_us"] - dt_us) < 5.0, r


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  OK   {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} tests passes")
    sys.exit(1 if failed else 0)


def test_channel_ids_accept_the_three_label_generations():
    """`caurtech.channel` : "1/2/3" (historique), "X/Y/Z" (V3.1 avec SID FDSN),
    "X_GH"... (V3.2). Les outils raisonnent par AXE, pas par etiquette."""
    from equipment.geophone3axis.dat_reader import (
        axis_channel_ids, channel_axis, missing_axes)

    assert [channel_axis(c) for c in ("1", "2", "3")] == ["X", "Y", "Z"]
    assert [channel_axis(c) for c in ("X", "Y", "Z")] == ["X", "Y", "Z"]
    assert channel_axis("Z_GL") == "Z" and channel_axis("X_GH") == "X"
    assert channel_axis("AUX1") is None and channel_axis("?") is None

    assert axis_channel_ids({"3": 0, "1": 0, "2": 0}) == ["1", "2", "3"]
    assert axis_channel_ids(["Z", "X", "Y"]) == ["X", "Y", "Z"]
    # V3.2 : ordre X, Y, Z puis GH avant GL ; les AUX ne sont pas des axes.
    assert axis_channel_ids(["AUX1", "Z_GL", "X_GL", "X_GH", "Y_GH"]) == [
        "X_GH", "X_GL", "Y_GH", "Z_GL"]

    assert missing_axes(["1", "2", "3"]) == []
    assert missing_axes(["X_GH", "Y_GL"]) == ["Z"]
    assert missing_axes(["AUX1"]) == ["X", "Y", "Z"]
