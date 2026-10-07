"""
Contrôle en ligne de commande de l'alimentation KORAD KA3005P.

Exemples :
    python korad_cli.py status                  # consignes, mesures, statut
    python korad_cli.py set -v 5.0 -i 0.5       # règle les consignes
    python korad_cli.py on                      # active la sortie
    python korad_cli.py off                     # désactive la sortie
    python korad_cli.py monitor -n 20 -p 0.5    # journalise 20 lectures
    python korad_cli.py monitor --csv mesures.csv
    python korad_cli.py ovp on                  # protection surtension
    python korad_cli.py recall 2                # rappelle la mémoire M2
    python korad_cli.py ports                   # liste les ports KORAD

Option globale --port COMx (par défaut : [Korad] port de config.ini, "auto"
= détection par VID:PID USB).
"""

import argparse
import csv
import sys
import time
from datetime import datetime

from config.settings import KORAD_PORT
from equipment.korad import KoradKA3005P, KoradReading


def _fmt(r: KoradReading) -> str:
    st = r.status
    return (f"VSET {r.v_set:6.2f} V   ISET {r.i_set:6.3f} A   |   "
            f"VOUT {r.v_out:6.2f} V   IOUT {r.i_out:6.3f} A   "
            f"P {r.power_w:6.2f} W   |   {st.mode}   "
            f"sortie {'ON' if st.output_on else 'OFF'}"
            f"{'   bip' if st.beep else ''}"
            f"{'   verrou' if st.lock else ''}")


def cmd_status(psu: KoradKA3005P, args) -> int:
    print(psu.identify())
    print(_fmt(psu.read_all()))
    return 0


def cmd_set(psu: KoradKA3005P, args) -> int:
    if args.voltage is None and args.current is None:
        print("Rien à régler : préciser -v et/ou -i.", file=sys.stderr)
        return 2
    if args.voltage is not None:
        psu.set_voltage(args.voltage)
    if args.current is not None:
        psu.set_current(args.current)
    time.sleep(0.2)
    print(_fmt(psu.read_all()))
    return 0


def cmd_on(psu: KoradKA3005P, args) -> int:
    psu.output_on()
    time.sleep(0.3)
    print(_fmt(psu.read_all()))
    return 0


def cmd_off(psu: KoradKA3005P, args) -> int:
    psu.output_off()
    time.sleep(0.3)
    print(_fmt(psu.read_all()))
    return 0


def cmd_monitor(psu: KoradKA3005P, args) -> int:
    writer = None
    fh = None
    if args.csv:
        fh = open(args.csv, "w", newline="", encoding="utf-8")
        writer = csv.writer(fh)
        writer.writerow(["horodatage", "v_set_V", "i_set_A",
                         "v_out_V", "i_out_A", "p_W", "mode", "sortie"])
    count = 0
    try:
        while args.count == 0 or count < args.count:
            r = psu.read_all()
            ts = datetime.now()
            print(f"{ts:%H:%M:%S}  {_fmt(r)}", flush=True)
            if writer is not None:
                writer.writerow([ts.isoformat(timespec="milliseconds"),
                                 f"{r.v_set:.2f}", f"{r.i_set:.3f}",
                                 f"{r.v_out:.2f}", f"{r.i_out:.3f}",
                                 f"{r.power_w:.3f}", r.status.mode,
                                 int(r.status.output_on)])
                fh.flush()
            count += 1
            if args.count == 0 or count < args.count:
                time.sleep(args.period)
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
    finally:
        if fh is not None:
            fh.close()
            print(f"CSV écrit : {args.csv}", file=sys.stderr)
    return 0


def cmd_ovp(psu: KoradKA3005P, args) -> int:
    psu.set_ovp(args.state == "on")
    print(f"OVP {args.state.upper()}")
    return 0


def cmd_ocp(psu: KoradKA3005P, args) -> int:
    psu.set_ocp(args.state == "on")
    print(f"OCP {args.state.upper()}")
    return 0


def cmd_beep(psu: KoradKA3005P, args) -> int:
    psu.set_beep(args.state == "on")
    print(f"Bip {args.state.upper()}")
    return 0


def cmd_save(psu: KoradKA3005P, args) -> int:
    psu.save_memory(args.slot)
    print(f"Consignes sauvées en M{args.slot}")
    return 0


def cmd_recall(psu: KoradKA3005P, args) -> int:
    psu.recall_memory(args.slot)
    time.sleep(0.3)
    print(_fmt(psu.read_all()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Contrôle de l'alimentation KORAD KA3005P.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__)
    p.add_argument("--port", default=KORAD_PORT,
                   help='Port série ("auto" = détection USB VID:PID).')
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ports", help="Liste les ports KORAD détectés.")
    sub.add_parser("status", help="Affiche consignes, mesures et statut.")

    s = sub.add_parser("set", help="Règle les consignes.")
    s.add_argument("-v", "--voltage", type=float, help="Tension en V (0-30).")
    s.add_argument("-i", "--current", type=float, help="Courant en A (0-5).")
    s.set_defaults(func=cmd_set)

    sub.add_parser("on", help="Active la sortie.").set_defaults(func=cmd_on)
    sub.add_parser("off", help="Désactive la sortie.").set_defaults(func=cmd_off)

    m = sub.add_parser("monitor", help="Lecture périodique (Ctrl+C pour finir).")
    m.add_argument("-n", "--count", type=int, default=0,
                   help="Nombre de lectures (0 = sans fin).")
    m.add_argument("-p", "--period", type=float, default=1.0,
                   help="Période en s (défaut 1,0).")
    m.add_argument("--csv", help="Fichier CSV de sortie.")
    m.set_defaults(func=cmd_monitor)

    for name, fn, helptxt in (("ovp", cmd_ovp, "Protection surtension."),
                              ("ocp", cmd_ocp, "Protection surcourant."),
                              ("beep", cmd_beep, "Bip des touches.")):
        c = sub.add_parser(name, help=helptxt)
        c.add_argument("state", choices=["on", "off"])
        c.set_defaults(func=fn)

    for name, fn, helptxt in (("save", cmd_save, "Sauve les consignes en M1..M5."),
                              ("recall", cmd_recall, "Rappelle M1..M5.")):
        c = sub.add_parser(name, help=helptxt)
        c.add_argument("slot", type=int, choices=list(KoradKA3005P.MEMORY_SLOTS))
        c.set_defaults(func=fn)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "ports":
        found = KoradKA3005P.find_ports()
        print("\n".join(found) if found else "Aucun KORAD détecté.")
        return 0 if found else 1

    func = getattr(args, "func", cmd_status)
    try:
        with KoradKA3005P(port=args.port) as psu:
            return func(psu, args)
    except Exception as exc:  # noqa: BLE001
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
