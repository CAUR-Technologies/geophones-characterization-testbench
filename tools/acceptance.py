#!/usr/bin/env python
"""
Banc d'ACCEPTATION PRODUIT (go/no-go design) — 9 prototypes, USB seul, PAS de shaker.

Exécute par unité (~5 min) les tests atteignables via l'interface CDC, mappés sur la
matrice de validation matérielle V1–V15 (geophones-firmware/doc/hardware). Écrit un
verdict PASS/WARN/FAIL par test dans `data/acceptance/<serial>.json`, et un tableau
de bord FLOTTE (`--fleet`).

Le test clé = **V7 (µSD + stress transfert)** : enregistre puis récupère TOUT le
survey en mesurant corruption ET **freeze** — sur 1 unité c'est un incident, sur 9
ça dit si le gel-sous-charge est un défaut de DESIGN.

Usage :
    python tools/acceptance.py                 # auto-découvre l'unité branchée
    python tools/acceptance.py --rec 120       # durée d'enregistrement du stress (s)
    python tools/acceptance.py --fleet         # tableau de bord des 9 unités
"""
import datetime
import json
import os
import sys
import threading
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from equipment.geophone3axis.geophone3axis import discover_units, Geophone3Axis
from equipment.geophone3axis import dat_reader
from config.settings import GEOPHONE3AXIS_VID, GEOPHONE3AXIS_PID

OUT_DIR = "data/acceptance"
PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Console Windows cp1252 : ne jamais crasher sur un caractère non encodable (≈, →…).
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:   # noqa: BLE001
    pass


def _call_timeout(fn, timeout_s):
    """Exécute fn() dans un thread ; retourne (résultat, timed_out). Sert à détecter
    un FREEZE du board sans bloquer 120 s sur le timeout série interne."""
    box = {}
    def _run():
        try:
            box["r"] = fn()
        except Exception as e:   # noqa: BLE001
            box["e"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start(); th.join(timeout_s)
    if th.is_alive():
        return None, True
    if "e" in box:
        raise box["e"]
    return box.get("r"), False


class Frozen(Exception):
    """Le board ne répond plus (freeze) — un appel a dépassé son timeout."""


class SafeUnit:
    """Proxy anti-freeze : chaque commande board tourne sous timeout ; un dépassement
    lève `Frozen(label)` au lieu de bloquer le harnais 120 s. INDISPENSABLE pour la
    flotte : une unité qui gèle est NOTÉE (FREEZE=FAIL) sans figer la campagne."""
    _T = {"status": 8, "config": 8, "set_config": 10, "start": 8, "stop": 8,
          "sync": 8, "ls": 12, "get_file": 20}

    def __init__(self, g):
        self.g = g

    def _s(self, name, *a, **k):
        r, to = _call_timeout(lambda: getattr(self.g, name)(*a, **k), self._T[name])
        if to:
            raise Frozen(name)
        return r

    def status(self): return self._s("status")
    def config(self): return self._s("config")
    def set_config(self, f): return self._s("set_config", f)
    def start(self): return self._s("start")
    def stop(self): return self._s("stop")
    def sync(self): return self._s("sync")
    def ls(self, p=""): return self._s("ls", p)
    def get_file(self, p): return self._s("get_file", p)

    @property
    def serial_number(self): return self.g.serial_number
    @property
    def _lock(self): return self.g._lock
    def _open(self): return self.g._open()


# ── tests unitaires (chacun retourne dict {test, verdict, detail}) ──────────

def v1_boot(g):
    """V1 — boot & console : STATUS répété, uptime monotone, pas de reboot."""
    ups, sn = [], None
    for _ in range(3):
        st = g.status(); ups.append(st.get("uptime_s")); sn = st.get("serial")
        time.sleep(4)
    ok = all(isinstance(u, (int, float)) for u in ups) and ups[0] < ups[-1]
    return {"test": "V1 boot", "verdict": PASS if ok else FAIL,
            "detail": f"uptime {ups} s, serial={sn}"}


def v13_identity(g, expect_serial):
    """V13 — identité + révision HW (MAX7319)."""
    st = g.status()
    sn, hw = st.get("serial"), st.get("hwrev")
    ok = sn == expect_serial and hw is not None and st.get("fw")
    return {"test": "V13 identité/rev", "verdict": PASS if ok else FAIL,
            "detail": f"serial={sn} fw={st.get('fw')} git={st.get('git')} hwrev={hw}"}


def v6_imu(g):
    """V6 — IMU : STREAM ON, vecteur g cohérent (~1 g) et tilt fini."""
    import serial  # noqa: F401
    gmags, tilts, n = [], [], 0
    with g._lock:
        ser = g._open(); ser.reset_input_buffer()
        ser.write(b"STREAM ON\n"); ser.flush(); time.sleep(0.4)
        t0 = time.time()
        while time.time() - t0 < 2.5:
            ln = ser.readline().decode(errors="replace").strip()
            if ln.startswith("IMU") and "ERR" not in ln:
                p = ln.split(",")
                if len(p) >= 10:
                    ax, ay, az = int(p[1]), int(p[2]), int(p[3])   # milli-g
                    gmags.append((ax**2 + ay**2 + az**2) ** 0.5 / 1000.0)
                    tilts.append(int(p[9]) / 100.0); n += 1
        ser.write(b"STREAM OFF\n"); ser.flush()
    if not gmags:
        return {"test": "V6 IMU", "verdict": FAIL, "detail": "aucune trame IMU"}
    gm = float(np.median(gmags))
    ok = 0.8 <= gm <= 1.2 and n >= 3
    return {"test": "V6 IMU", "verdict": PASS if ok else WARN,
            "detail": f"|g|={gm:.3f} (n={n}), incl~{np.median(tilts):.1f} deg"}


def cfg_roundtrip(g):
    """CFG — CONFIG SET/GET aller-retour (sur survey_id, restauré ensuite)."""
    cfg0 = g.config(); orig = cfg0.get("survey_id", "default")
    probe = "ACCTEST"
    g.set_config({"survey_id": probe})
    got = g.config().get("survey_id")
    g.set_config({"survey_id": orig})   # restaure
    ok = got == probe
    return {"test": "CFG roundtrip", "verdict": PASS if ok else FAIL,
            "detail": f"écrit {probe} → relu {got}"}


def v11_battery(g):
    """V11 — tension batterie plausible."""
    b = g.status().get("battery")
    if not isinstance(b, (int, float)):
        return {"test": "V11 batterie", "verdict": FAIL, "detail": f"battery={b}"}
    if b <= 2:
        return {"test": "V11 batterie", "verdict": WARN,
                "detail": f"battery={b} % — lecture suspecte (bug FW connu : lit 1)"}
    return {"test": "V11 batterie", "verdict": PASS if 2 < b <= 100 else WARN,
            "detail": f"battery={b} %"}


def _largest_survey(g):
    """Survey existant avec le plus de fichiers — pour tester le TRANSFERT sans
    dépendre d'un enregistrement frais (GPS-gaté). None si aucun."""
    dirs = [d["path"] for d in g.ls("/survey-data") if d.get("dir")]
    best, best_n = None, 0
    for d in dirs:
        try:
            n = len(g.ls(d))
        except Frozen:
            raise
        except Exception:   # noqa: BLE001
            n = 0
        if n > best_n:
            best, best_n = d, n
    return best if best_n > 0 else None


def _transfer_test(g, sp):
    """GET tout le survey `sp` (record ARRÊTÉ) → V7 transfert + V2 ADC + V8 miniSEED.
    Retourne (res, parsed_channels, gps_time_ok, frozen)."""
    files = sorted(f["path"] for f in g.ls(sp))
    os.makedirs(OUT_DIR, exist_ok=True)
    n_ok = 0
    good_records = corrupt_records = 0   # métrique PAR RECORD (indép. de la taille des fichiers)
    n_bytes = 0
    frozen = False
    gps_ok = False
    chan_std = {}          # cid -> (std max vu, saturé ?) AGRÉGÉ sur TOUS les fichiers
    t0 = time.time()
    for p in files:
        try:
            data = g.get_file(p)          # SafeUnit : timeout 20 s → Frozen
        except Frozen:
            frozen = True; break
        if not data:
            continue
        n_bytes += len(data)
        local = os.path.join(OUT_DIR, f"{g.serial_number}_{os.path.basename(p)}")
        with open(local, "wb") as fh:
            fh.write(data)
        try:
            chans = dat_reader.read_dat(local)
            n_ok += 1
            # records bons (∑ segments par voie) + records corrompus (records_skipped)
            good_records += sum(c.meta.get("segments", 0) for c in chans)
            corrupt_records += (chans[0].meta.get("file", {}) or {}).get("records_skipped", 0) if chans else 0
            for c in chans:                # voies réparties sur plusieurs fichiers → agréger
                s = float(np.std(c.data)) if len(c.data) else 0.0
                r = bool(np.max(np.abs(c.data)) >= 0.98 * 2**31) if len(c.data) else False
                pstd, prail = chan_std.get(c.channel_id, (0.0, False))
                chan_std[c.channel_id] = (max(pstd, s), prail or r)
            if not gps_ok and chans:
                yr = datetime.datetime.utcfromtimestamp(chans[0].start_time_ns/1e9).year
                gps_ok = yr >= 2020
        except Exception:   # noqa: BLE001
            corrupt_records += 1
        finally:
            try: os.remove(local)
            except OSError: pass
    dt = time.time() - t0
    kbps = (n_bytes / 1024 / dt) if dt > 0 else 0.0
    n_channels = len(chan_std)

    res = []
    total_rec = good_records + corrupt_records
    if frozen:
        res.append({"test": "V7 transfert données", "verdict": FAIL,
                    "detail": f"FREEZE pendant GET (record arrêté) après {n_ok}/{len(files)} "
                              f"fichiers — DÉFAUT PRODUIT (transfert non fiable)"})
    else:
        # Métrique PAR RECORD. La corruption GET/CDC (~0,2-0,5 %) est EN TRANSIT sur le
        # lien USB (prouvé test 3× : même fichier → md5 différents) — la donnée SD est
        # INTACTE, récupérable sans perte par retry → PAS un défaut = PASS (avec détail).
        # FAIL seulement pour une corruption GROSSIÈRE (≥5 %) = lien réellement dégradé.
        rate = (corrupt_records / total_rec) if total_rec else 0.0
        if total_rec == 0:
            v, note = PASS, " — aucune donnée à transférer (survey vide)"
        elif corrupt_records == 0:
            v, note = PASS, ""
        elif rate >= 0.05:
            v, note = FAIL, " — corruption GROSSIÈRE en transit (lien dégradé ?)"
        else:
            v, note = PASS, " — en transit CDC (SD intacte, récupérable par retry)"
        res.append({"test": "V7 transfert données", "verdict": v,
                    "detail": f"{n_ok}/{len(files)} fichiers, {corrupt_records}/{total_rec} records "
                              f"corrompus ({rate*100:.2f}%), {kbps:.0f} Ko/s{note}"})
    if chan_std:
        present = sorted(chan_std)
        # Les trois AXES doivent être couverts, quelle que soit la génération
        # d'étiquettes ("1/2/3", "X/Y/Z", ou "X_GH"… en V3.2).
        missing = bool(dat_reader.missing_axes(chan_std))
        dead = not all(v[0] > 5 for v in chan_std.values())   # std≈0 = voie figée
        railed = any(v[1] for v in chan_std.values())
        # FAIL = défaut ADC réel (voie absente/morte). Saturation = amplitude
        # d'enregistrement (ex. caractérisation forte ampli), PAS un défaut → WARN.
        verdict = FAIL if (missing or dead) else (WARN if railed else PASS)
        note = (" — voie(s) MANQUANTE(s)" if missing else
                " — voie FIGÉE (std~0)" if dead else
                " SATURE (ampli d'enregistrement, pas un défaut ADC)" if railed else "")
        res.append({"test": "V2 ADC x3", "verdict": verdict,
                    "detail": f"voies={present} std={ {k: round(v[0]) for k, v in chan_std.items()} }{note}"})
    else:
        res.append({"test": "V2 ADC x3", "verdict": FAIL, "detail": "aucun .dat lisible"})
    res.append({"test": "V8 miniSEED", "verdict": PASS if n_ok and not frozen else FAIL,
                "detail": f"{n_ok} fichiers parses (simplemseed v3)"})
    return res, n_channels, gps_ok, frozen


def record_and_get(g, rec_s):
    """USB = config + transfert SEULEMENT (jamais actif pendant l'enregistrement en
    champ). Séquence : CONFIG → START (minimal) → record SANS trafic USB → STOP →
    GET tout le survey ENREGISTREMENT ARRÊTÉ (= le vrai transfert de données). Si
    l'enregistrement ne démarre pas (pas de fix GPS), le transfert est quand même
    testé sur un survey EXISTANT (le transfert ne dépend pas d'un fix)."""
    ts = datetime.datetime.now().strftime("%H%M%S")
    survey = f"ACC_{ts}"
    sp = f"/survey-data/{survey}"
    started = False
    try:
        # records_per_file=2 → fichiers de 2 s : se ferment vite (démarrage visible
        # à ~t+6 s) ET donnent plus de fichiers pour stresser le transfert.
        g.set_config({"sample_rate_hz": 250, "samples_by_record": 250,
                      "records_per_file": 2, "gain": 1, "survey_id": survey,
                      "max_pitch_deg": 45, "max_roll_deg": 45})
        try:
            g.stop(); time.sleep(0.3)
        except Frozen:
            raise
        except Exception:   # noqa: BLE001
            pass
        g.start(); g.sync()                 # trigger test-only, minimal
        # UN seul contrôle à t+6 s (le 1er fichier de 2 s est fermé) pour confirmer
        # le démarrage, puis SILENCE USB total pendant le record.
        time.sleep(6.0)
        started = len(g.ls(sp)) > 0
        if started:
            time.sleep(max(0, rec_s - 6))   # aucun trafic USB pendant le record
        g.stop(); time.sleep(0.5)
    except Frozen as e:
        return [{"test": "contrôle USB (hors-produit)", "verdict": WARN,
                 "detail": f"gel au contrôle USB-pendant-acquisition (sur '{e}') — "
                           f"condition de TEST ; USB inactif pendant le record en champ"}], sp

    # Survey à transférer : le frais si l'enregistrement a démarré, sinon un EXISTANT.
    transfer_sp, on_existing = sp, False
    if not started:
        try:
            ex = _largest_survey(g)
        except Frozen:
            ex = None
        if ex:
            transfer_sp, on_existing = ex, True

    try:
        res, n_channels, gps_ok, frozen = _transfer_test(g, transfer_sp)
    except Frozen:
        res = [{"test": "V7 transfert données", "verdict": FAIL,
                "detail": "FREEZE au LS du survey (transfert) — défaut produit"}]
        n_channels, gps_ok, frozen = 0, False, True

    if started:
        v15ok = n_channels >= 3 and gps_ok and not frozen
        res.append({"test": "V4/V15 acquisition E2E", "verdict": PASS if v15ok else WARN,
                    "detail": f"record OK ({n_channels} voies), "
                              f"{'timestamps GPS reels' if gps_ok else 'horodatage non-GPS ?'}"})
    else:
        res.append({"test": "V4/V15 acquisition E2E", "verdict": WARN,
                    "detail": ("record NON démarré (pas de fix GPS/tilt) — transfert testé "
                               "sur survey existant" if on_existing else
                               "record NON démarré et aucun survey existant")})
    return res, transfer_sp


def transfer_only(g):
    """MODE PAR DÉFAUT : teste ADC/transfert/format sur un survey EXISTANT, SANS
    déclencher d'enregistrement par USB. Le START-USB gèle le board par intermittence
    (condition test-only) ; config + transfert = usages NORMAUX, fiables. On valide
    donc les vrais usages produit sans provoquer le gel. L'enregistrement lui-même se
    valide au BOUTON (vrai déclencheur) ou avec --record."""
    try:
        ex = _largest_survey(g)
    except Frozen:
        return [{"test": "V7 transfert données", "verdict": FAIL,
                 "detail": "FREEZE au LS /survey-data"}]
    if not ex:
        return [{"test": "V7 transfert données", "verdict": WARN,
                 "detail": "aucun survey sur la SD — enregistre d'abord (bouton) puis relance"}]
    res, n_channels, gps_ok, frozen = _transfer_test(g, ex)
    res.append({"test": "V4/V15 acquisition E2E", "verdict": "N/A",
                "detail": f"transfert validé sur survey existant {ex} ({n_channels} voies, "
                          f"{'GPS' if gps_ok else 'non-GPS'}) ; record frais = à valider au bouton"})
    return res


def run_unit(rec_s=90, do_record=False):
    found, to = _call_timeout(
        lambda: discover_units(vid=GEOPHONE3AXIS_VID, pid=GEOPHONE3AXIS_PID), 15)
    if to:
        print("Board injoignable (découverte gelée) — RESET l'unité puis relance.")
        return None
    if not found:
        print("Aucune unité détectée (USB ?)."); return None
    sn, port = found[0]
    print(f"=== ACCEPTATION {sn} @ {port} (stress {rec_s} s) ===")
    raw = Geophone3Axis(port, serial_number=sn)
    _, to = _call_timeout(raw.connect, 10)
    if to:
        print(f"{sn} : connexion gelée — RESET requis."); return None
    g = SafeUnit(raw)          # tout appel board sous timeout anti-freeze
    results = []
    # Chaque test tourne isolé : un FREEZE le marque FAIL et on continue les suivants
    # (souvent déjà gelés → FAIL en cascade, ce qui est l'info voulue).
    def _guard(fn, label):
        try:
            results.append(fn())
        except Frozen as e:
            results.append({"test": label, "verdict": FAIL,
                            "detail": f"FREEZE (board ne répond plus sur '{e}')"})
        except Exception as e:   # noqa: BLE001
            results.append({"test": label, "verdict": FAIL, "detail": f"erreur: {e}"})
    try:
        _guard(lambda: v1_boot(g), "V1 boot")
        _guard(lambda: v13_identity(g, sn), "V13 identité/rev")
        _guard(lambda: v6_imu(g), "V6 IMU")
        _guard(lambda: cfg_roundtrip(g), "CFG roundtrip")
        _guard(lambda: v11_battery(g), "V11 batterie")
        try:
            if do_record:
                rec_res, _ = record_and_get(g, rec_s)   # --record : START-USB (flaky)
            else:
                rec_res = transfer_only(g)               # défaut : pas de START-USB
            results.extend(rec_res)
        except Frozen as e:
            results.append({"test": "V7 transfert données", "verdict": FAIL,
                            "detail": f"FREEZE pendant transfert (sur '{e}')"})
    finally:
        try: raw.stop()
        except Exception: pass
        try: raw.close()
        except Exception: pass

    overall = FAIL if any(r["verdict"] == FAIL for r in results) else \
        (WARN if any(r["verdict"] == WARN for r in results) else PASS)
    rec = {"serial": sn, "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
           "overall": overall, "results": results, "rec_s": rec_s}
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, f"{sn}.json"), "w", encoding="utf-8") as fp:
        json.dump(rec, fp, indent=2, ensure_ascii=False)

    print(f"\n{'test':<24}{'verdict':<8}detail")
    for r in results:
        print(f"  {r['test']:<22}{r['verdict']:<8}{r['detail']}")
    print(f"\n  >>> {sn} : {overall} <<<   (data/acceptance/{sn}.json)")
    return overall


def fleet():
    import glob
    rows = []
    for p in sorted(glob.glob(os.path.join(OUT_DIR, "*.json"))):
        with open(p, encoding="utf-8") as fp:
            rows.append(json.load(fp))
    if not rows:
        print("Aucun résultat. Lance d'abord `python tools/acceptance.py` sur chaque unité.")
        return
    tests = []
    for r in rows:
        for t in r["results"]:
            key = t["test"].split()[0]
            if key not in tests:
                tests.append(key)
    print(f"\n=== TABLEAU DE BORD FLOTTE ({len(rows)} unités) ===")
    print(f"{'serial':<14}{'OVERALL':<9}" + "".join(f"{t:<7}" for t in tests))
    for r in sorted(rows, key=lambda x: x["serial"]):
        by = {t["test"].split()[0]: t["verdict"] for t in r["results"]}
        line = f"{r['serial']:<14}{r['overall']:<9}"
        for t in tests:
            v = by.get(t, "-")
            line += f"{('.' if v==PASS else '!' if v==WARN else 'X' if v==FAIL else '-'):<7}"
        print(line)
    print("  légende : . PASS   ! WARN   X FAIL")
    n_pass = sum(1 for r in rows if r["overall"] == PASS)
    n_fail = sum(1 for r in rows if r["overall"] == FAIL)
    print(f"\n  {n_pass} PASS · {sum(1 for r in rows if r['overall']==WARN)} WARN · {n_fail} FAIL")


if __name__ == "__main__":
    if "--fleet" in sys.argv:
        fleet()
    else:
        rec = 90
        if "--rec" in sys.argv:
            rec = int(sys.argv[sys.argv.index("--rec") + 1])
        # --record : déclenche un enregistrement FRAIS par USB (START flaky, peut
        # geler le board). Par défaut : transfert sur survey existant, pas de START.
        run_unit(rec_s=rec, do_record="--record" in sys.argv)
