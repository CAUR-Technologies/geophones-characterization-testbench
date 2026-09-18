#!/usr/bin/env python
"""
Récupère (ou re-corrèle) un balayage 3 axes `.dat` par SEGMENTATION du signal,
sans dépendre des sods de la GNSS de référence.

Motivation : la corrélation live du GUI (`correlate_dat_run`) aligne les `.dat`
sur les fenêtres temps-GPS (`sod_start/end`) capturées via la GNSS de référence
(ProPak). Si celle-ci perd le fix ou lague à un palier, ce point est droppé ou
désaligné → sensibilités fausses. Ici on IGNORE les sods : chaque palier de
fréquence est un tone stationnaire, on le RE-DÉTECTE dans le signal `.dat`
(lock-in glissant → plateau), puis on lock-in la voie sur la fenêtre détectée.
Seuls les timestamps PROPRES du `.dat` (horloge de l'unité) et les vitesses table
du CSV (mesurées par l'accéléro NI) sont nécessaires.

Écrit `<run>_RESULTS.csv` + `<run>_FIT.json` au format GUI (lus par synth_campaign).

Usage :
    python tools/recover_run.py                       # dernier run de data/3axis
    python tools/recover_run.py <streaming_csv>       # un run précis
"""
import csv
import datetime
import glob
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from equipment.geophone3axis.dat_reader import UNIT3AXIS_FULLSCALE_VPEAK_G1, axis_channel_ids
from equipment.geophone3axis.session import segment_correlate, channels_from_dat
from equipment.dsp import fit_geophone_response

DATA_DIR = "data/3axis"
FS = 250.0
CH_AXIS = {"1": "X", "2": "Y", "3": "Z"}


def _latest_csv():
    csvs = [f for f in glob.glob(os.path.join(DATA_DIR, "3axis_*_g*_*.csv"))
            if "_RESULTS" not in f and "summary" not in f]
    return max(csvs, key=os.path.getmtime) if csvs else None


def _parse_name(csv_path):
    """3axis_<serial>_<axis>_g<gain>_<ts>.csv → (serial, axis, gain, ts)."""
    b = os.path.basename(csv_path)[:-4]
    m = re.match(r"3axis_(.+)_(horizontal|vertical)_g(\d+)_(\d{8}_\d{6})", b)
    if not m:
        raise ValueError(f"nom de run non reconnu : {b}")
    return m.group(1), m.group(2), int(m.group(3)), m.group(4)


def recover(csv_path):
    serial, axis, gain, ts = _parse_name(csv_path)
    survey = "Bench_" + ts
    lsb_v = UNIT3AXIS_FULLSCALE_VPEAK_G1 / gain / (2 ** 31)
    rows = list(csv.DictReader(open(csv_path)))
    freqs = [float(r["freq_hz"]) for r in rows]
    vel = {float(r["freq_hz"]): float(r["table_velocity_mps"]) for r in rows}
    accel = {float(r["freq_hz"]): float(r["accel_g"]) for r in rows}

    files = sorted(glob.glob(os.path.join(DATA_DIR, f"*{survey}*{serial}*.dat")))
    T, X = channels_from_dat(files)          # {cid: sods}, {cid: data} (shared)
    if not X:
        print(f"survey {survey}: aucun .dat (introuvable ?)")
        return
    ref = max(X, key=lambda c: float(np.std(X[c])) if len(X[c]) else 0.0)
    print(f"run {serial} {axis} g{gain} — survey {survey} : {len(files)} fichiers, "
          f"voie forte {ref} {len(X[ref])} ech ({T[ref][-1]-T[ref][0]:.0f}s)")

    # Corrélation par segmentation (MÊME code que le GUI : session.segment_correlate).
    DAT = segment_correlate(T, X, freqs, vel, lsb_v)

    # Voies d'axe présentes : "1/2/3" (historique), "X/Y/Z" ou "X_GH"… (V3.2).
    cids = axis_channel_ids(DAT) or ["1", "2", "3"]
    head = "".join(f"{(c + ' V/(m/s)') if i == 0 else c:>{13 if i == 0 else 8}}"
                   for i, c in enumerate(cids))
    print(f"\n{'f(Hz)':>7}{'v(m/s)':>9}{head}{'n':>7}")
    for fq in freqs:
        line = f"{fq:>7}{vel[fq]:>9.5f}"
        for i, cid in enumerate(cids):
            d = DAT.get(cid, {}).get(fq)
            w = 13 if i == 0 else 8
            line += (f"{d['sens_v_per_mps']:>{w}.{1 if i == 0 else 2}f}" if d else f"{'-':>{w}}")
        d1 = DAT.get(cids[0], {}).get(fq)
        print(line + (f"{d1['n']:>7}" if d1 else f"{'-':>7}"))

    on_axis = max(DAT, key=lambda c: sum(v["counts_peak"] for v in DAT[c].values())
                  if DAT[c] else 0) if DAT else cids[0]
    ff = [f for f in freqs if f in DAT.get(on_axis, {})]
    ss = [DAT[on_axis][f]["sens_v_per_mps"] for f in ff]
    fit = fit_geophone_response(ff, ss) if len(ff) >= 4 else None

    print(f"\n=== FIT voie {on_axis} ({CH_AXIS.get(on_axis,'?')}) ===")
    if fit:
        z = fit["zeta"]
        pk = 1.0 / (2 * z * (1 - z ** 2) ** 0.5) if z < 0.707 else 1.0
        print(f"  G0={fit['G0']:.1f} V/(m/s)  f0={fit['f0']:.2f} Hz  zeta={fit['zeta']:.3f}  "
              f"pic x{pk:.2f}={fit['G0']*pk:.0f}  RMS={fit['rms_error_db']:.2f} dB (n={fit['n']})")
    else:
        print("  fit indisponible (< 4 points)")

    base = csv_path[:-4]
    # timestamp = celui du RUN (pas du traitement) → synth_campaign ordonne bien.
    run_iso = datetime.datetime.strptime(ts, "%Y%m%d_%H%M%S").isoformat(timespec="seconds")
    meta = {"serial": serial, "axis": axis, "gain": gain, "on_axis_channel": on_axis,
            "timestamp": run_iso, "fit": fit, "n_freqs": len(freqs),
            "method": "segmentation"}
    with open(base + "_FIT.json", "w", encoding="utf-8") as fp:
        json.dump(meta, fp, indent=2, ensure_ascii=False)
    with open(base + "_RESULTS.csv", "w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
        hdr = ["freq_hz", "accel_g", "on_axis_channel"]
        for c in cids:
            hdr += [f"ch{c}_S_V_per_mps", f"ch{c}_S_cnt_per_mps", f"ch{c}_counts_pk", f"ch{c}_n"]
        w.writerow(hdr)
        for f in freqs:
            row = [f"{f:g}", f"{accel.get(f, float('nan')):.6g}", on_axis]
            for c in cids:
                d = DAT.get(c, {}).get(f, {})
                row += [f"{d.get('sens_v_per_mps', float('nan')):.6g}",
                        f"{d.get('sens_counts_per_mps', float('nan')):.6g}",
                        f"{d.get('counts_peak', float('nan')):.6g}", d.get("n", "")]
            w.writerow(row)
    print(f"\n-> réécrit {os.path.basename(base)}_RESULTS.csv + _FIT.json (segmentation)")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else _latest_csv()
    if not path:
        print("aucun CSV de run trouvé dans", DATA_DIR)
    else:
        recover(path)
