"""
Interface graphique de contrôle de l'alimentation KORAD KA3005P.

Fonctions : connexion (port auto-détecté par VID:PID), activation /
désactivation de la sortie, consignes tension / courant, lecture en continu
des valeurs mesurées (V, A, W) et du statut (CV/CC, sortie, bip, verrou),
protections OVP / OCP, mémoires M1..M5.

Usage :
    python korad_gui.py
"""

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from serial.tools import list_ports

import config.config_manager as _cfg_mgr
from config.settings import KORAD_PORT
from equipment.korad import KoradKA3005P, KoradReading

POLL_PERIOD_S = 0.5
UI_TICK_MS = 100

COLOR_ON = "#2e9e44"
COLOR_OFF = "#c0392b"
COLOR_IDLE = "#7f8c8d"


class KoradApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("KORAD KA3005P — contrôle")
        self.resizable(False, False)

        self._psu: KoradKA3005P | None = None
        self._poll_thread: threading.Thread | None = None
        self._poll_stop = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._last_reading: KoradReading | None = None

        self._build_ui()
        self._refresh_ports()
        self.after(UI_TICK_MS, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────────────────────────────────────────────────────────────
    # Construction de l'interface
    # ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 6, "pady": 4}
        root = ttk.Frame(self, padding=8)
        root.grid(sticky="nsew")

        # --- Connexion ---------------------------------------------------
        fr_conn = ttk.LabelFrame(root, text="Connexion", padding=6)
        fr_conn.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr_conn, text="Port :").grid(row=0, column=0, sticky="w")
        self.var_port = tk.StringVar(value=KORAD_PORT or "auto")
        self.cb_port = ttk.Combobox(fr_conn, textvariable=self.var_port,
                                    width=34, state="readonly")
        self.cb_port.grid(row=0, column=1, sticky="w", padx=4)
        ttk.Button(fr_conn, text="↻", width=3,
                   command=self._refresh_ports).grid(row=0, column=2)
        self.btn_connect = ttk.Button(fr_conn, text="Connecter",
                                      command=self._toggle_connection)
        self.btn_connect.grid(row=0, column=3, padx=(10, 0))
        self.var_idn = tk.StringVar(value="Non connecté")
        ttk.Label(fr_conn, textvariable=self.var_idn,
                  foreground=COLOR_IDLE).grid(row=1, column=0, columnspan=4,
                                              sticky="w", pady=(4, 0))

        # --- Mesures -----------------------------------------------------
        fr_meas = ttk.LabelFrame(root, text="Mesures", padding=6)
        fr_meas.grid(row=1, column=0, sticky="nsew", **pad)
        big = ("Consolas", 26, "bold")
        self.var_vout = tk.StringVar(value="--.-- V")
        self.var_iout = tk.StringVar(value="-.--- A")
        self.var_pout = tk.StringVar(value="--.-- W")
        self.lbl_vout = tk.Label(fr_meas, textvariable=self.var_vout,
                                 font=big, width=9, anchor="e")
        self.lbl_iout = tk.Label(fr_meas, textvariable=self.var_iout,
                                 font=big, width=9, anchor="e")
        self.lbl_pout = tk.Label(fr_meas, textvariable=self.var_pout,
                                 font=("Consolas", 16), width=9, anchor="e")
        self.lbl_vout.grid(row=0, column=0, sticky="e")
        self.lbl_iout.grid(row=1, column=0, sticky="e")
        self.lbl_pout.grid(row=2, column=0, sticky="e")
        self.var_mode = tk.StringVar(value="--")
        self.lbl_mode = tk.Label(fr_meas, textvariable=self.var_mode,
                                 font=("Segoe UI", 14, "bold"), width=4,
                                 fg="white", bg=COLOR_IDLE)
        self.lbl_mode.grid(row=0, column=1, rowspan=2, padx=(12, 0))
        ttk.Label(fr_meas, text="mode").grid(row=2, column=1)

        # --- Sortie ------------------------------------------------------
        fr_out = ttk.LabelFrame(root, text="Sortie", padding=6)
        fr_out.grid(row=1, column=1, sticky="nsew", **pad)
        self.btn_output = tk.Button(fr_out, text="SORTIE\n--",
                                    font=("Segoe UI", 14, "bold"),
                                    fg="white", bg=COLOR_IDLE, width=10,
                                    height=3, state="disabled",
                                    command=self._toggle_output)
        self.btn_output.pack(fill="both", expand=True)
        ttk.Label(fr_out, text="Cliquer pour basculer",
                  foreground=COLOR_IDLE).pack(pady=(4, 0))

        # --- Consignes ---------------------------------------------------
        fr_set = ttk.LabelFrame(root, text="Consignes", padding=6)
        fr_set.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr_set, text="Tension (V) :").grid(row=0, column=0, sticky="w")
        self.var_vset = tk.StringVar(value="0.00")
        self.sp_v = ttk.Spinbox(fr_set, textvariable=self.var_vset, width=8,
                                from_=0.0, to=KoradKA3005P.MAX_VOLTAGE,
                                increment=0.1, format="%.2f")
        self.sp_v.grid(row=0, column=1, padx=4)
        ttk.Button(fr_set, text="Appliquer",
                   command=self._apply_voltage).grid(row=0, column=2)
        self.var_vset_dev = tk.StringVar(value="appareil : --")
        ttk.Label(fr_set, textvariable=self.var_vset_dev,
                  foreground=COLOR_IDLE).grid(row=0, column=3, padx=8, sticky="w")

        ttk.Label(fr_set, text="Courant (A) :").grid(row=1, column=0, sticky="w")
        self.var_iset = tk.StringVar(value="0.000")
        self.sp_i = ttk.Spinbox(fr_set, textvariable=self.var_iset, width=8,
                                from_=0.0, to=KoradKA3005P.MAX_CURRENT,
                                increment=0.01, format="%.3f")
        self.sp_i.grid(row=1, column=1, padx=4)
        ttk.Button(fr_set, text="Appliquer",
                   command=self._apply_current).grid(row=1, column=2)
        self.var_iset_dev = tk.StringVar(value="appareil : --")
        ttk.Label(fr_set, textvariable=self.var_iset_dev,
                  foreground=COLOR_IDLE).grid(row=1, column=3, padx=8, sticky="w")

        ttk.Button(fr_set, text="Appliquer les deux",
                   command=self._apply_both).grid(row=2, column=1, columnspan=2,
                                                  pady=(6, 0), sticky="ew")
        ttk.Button(fr_set, text="Relire depuis l'appareil",
                   command=self._load_setpoints).grid(row=2, column=3,
                                                      pady=(6, 0), sticky="w",
                                                      padx=8)
        for w in (self.sp_v, self.sp_i):
            w.bind("<Return>", lambda e: self._apply_both())

        # --- Protections / options ---------------------------------------
        fr_prot = ttk.LabelFrame(root, text="Protections et options", padding=6)
        fr_prot.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)
        self.var_ovp = tk.BooleanVar(value=False)
        self.var_ocp = tk.BooleanVar(value=False)
        self.var_beep = tk.BooleanVar(value=False)
        ttk.Checkbutton(fr_prot, text="OVP (surtension)", variable=self.var_ovp,
                        command=lambda: self._send(
                            lambda p: p.set_ovp(self.var_ovp.get()))
                        ).grid(row=0, column=0, padx=4)
        ttk.Checkbutton(fr_prot, text="OCP (surcourant)", variable=self.var_ocp,
                        command=lambda: self._send(
                            lambda p: p.set_ocp(self.var_ocp.get()))
                        ).grid(row=0, column=1, padx=4)
        ttk.Checkbutton(fr_prot, text="Bip touches", variable=self.var_beep,
                        command=lambda: self._send(
                            lambda p: p.set_beep(self.var_beep.get()))
                        ).grid(row=0, column=2, padx=4)
        ttk.Label(fr_prot, text="(OVP/OCP non relisibles : état = dernier envoi)",
                  foreground=COLOR_IDLE).grid(row=1, column=0, columnspan=3,
                                              sticky="w")

        # --- Mémoires ----------------------------------------------------
        fr_mem = ttk.LabelFrame(root, text="Mémoires", padding=6)
        fr_mem.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Label(fr_mem, text="Rappeler :").grid(row=0, column=0, sticky="w")
        ttk.Label(fr_mem, text="Sauver :").grid(row=1, column=0, sticky="w")
        for n in KoradKA3005P.MEMORY_SLOTS:
            ttk.Button(fr_mem, text=f"M{n}", width=4,
                       command=lambda n=n: self._recall(n)
                       ).grid(row=0, column=n, padx=2)
            ttk.Button(fr_mem, text=f"M{n}", width=4,
                       command=lambda n=n: self._save(n)
                       ).grid(row=1, column=n, padx=2)

        # --- Journal -----------------------------------------------------
        fr_log = ttk.LabelFrame(root, text="Journal", padding=6)
        fr_log.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)
        self.txt_log = tk.Text(fr_log, height=6, width=56, state="disabled",
                               font=("Consolas", 9))
        self.txt_log.pack(fill="both", expand=True)

        self._set_controls_enabled(False)

    # ─────────────────────────────────────────────────────────────────────
    # Aides
    # ─────────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", f"{ts}  {msg}\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _refresh_ports(self):
        korad = KoradKA3005P.find_ports()
        others = [p.device for p in list_ports.comports()
                  if p.device not in korad]
        values = ["auto"] + [f"{p} (KORAD)" for p in korad] + sorted(others)
        self.cb_port["values"] = values
        if self.var_port.get() not in values:
            self.var_port.set("auto")

    def _selected_port(self) -> str:
        return self.var_port.get().split(" ")[0]

    def _set_controls_enabled(self, on: bool):
        state = "normal" if on else "disabled"
        for w in (self.sp_v, self.sp_i):
            w.configure(state=state)
        self.btn_output.configure(state=state)
        if not on:
            self.btn_output.configure(bg=COLOR_IDLE, text="SORTIE\n--")
            self.lbl_mode.configure(bg=COLOR_IDLE)
            self.var_mode.set("--")

    def _send(self, action, label: str | None = None):
        """Exécute une action sur le pilote (thread-safe) avec gestion d'erreur."""
        if self._psu is None:
            return
        try:
            action(self._psu)
            if label:
                self._log(label)
        except Exception as exc:  # noqa: BLE001
            self._log(f"ERREUR : {exc}")
            messagebox.showerror("KORAD", str(exc))

    # ─────────────────────────────────────────────────────────────────────
    # Connexion
    # ─────────────────────────────────────────────────────────────────────

    def _toggle_connection(self):
        if self._psu is None:
            self._connect()
        else:
            self._disconnect()

    def _connect(self):
        port = self._selected_port()
        psu = KoradKA3005P(port=port)
        try:
            idn = psu.connect()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Connexion KORAD", str(exc))
            self._log(f"ERREUR connexion : {exc}")
            return
        self._psu = psu
        self.var_idn.set(f"{idn}  [{psu.port}]")
        self.btn_connect.configure(text="Déconnecter")
        self.cb_port.configure(state="disabled")
        self._set_controls_enabled(True)
        self._log(f"Connecté sur {psu.port} : {idn}")
        if psu.port != KORAD_PORT and port != "auto":
            _cfg_mgr.set_value("Korad", "port", psu.port)
            _cfg_mgr.save()
        self._load_setpoints()
        self._start_polling()

    def _disconnect(self):
        self._stop_polling()
        if self._psu is not None:
            self._psu.disconnect()
            self._psu = None
        self.var_idn.set("Non connecté")
        self.btn_connect.configure(text="Connecter")
        self.cb_port.configure(state="readonly")
        self._set_controls_enabled(False)
        self.var_vout.set("--.-- V")
        self.var_iout.set("-.--- A")
        self.var_pout.set("--.-- W")
        self._log("Déconnecté.")

    def _on_close(self):
        self._disconnect()
        self.destroy()

    # ─────────────────────────────────────────────────────────────────────
    # Polling
    # ─────────────────────────────────────────────────────────────────────

    def _start_polling(self):
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop,
                                             daemon=True)
        self._poll_thread.start()

    def _stop_polling(self):
        self._poll_stop.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3.0)
            self._poll_thread = None

    def _poll_loop(self):
        while not self._poll_stop.is_set():
            psu = self._psu
            if psu is None:
                break
            t0 = time.monotonic()
            try:
                reading = psu.read_all()
                self._events.put(("reading", reading))
            except Exception as exc:  # noqa: BLE001
                self._events.put(("error", str(exc)))
            rest = POLL_PERIOD_S - (time.monotonic() - t0)
            if rest > 0:
                self._poll_stop.wait(rest)

    def _drain_events(self):
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "reading":
                    self._show_reading(payload)
                elif kind == "error":
                    self._log(f"ERREUR lecture : {payload}")
        except queue.Empty:
            pass
        self.after(UI_TICK_MS, self._drain_events)

    def _show_reading(self, r: KoradReading):
        self._last_reading = r
        self.var_vout.set(f"{r.v_out:5.2f} V")
        self.var_iout.set(f"{r.i_out:5.3f} A")
        self.var_pout.set(f"{r.power_w:5.2f} W")
        self.var_vset_dev.set(f"appareil : {r.v_set:.2f} V")
        self.var_iset_dev.set(f"appareil : {r.i_set:.3f} A")
        self.var_mode.set(r.status.mode)
        self.lbl_mode.configure(bg=COLOR_ON if r.status.cv_mode else "#d68910")
        if r.status.output_on:
            self.btn_output.configure(bg=COLOR_ON, text="SORTIE\nON")
        else:
            self.btn_output.configure(bg=COLOR_OFF, text="SORTIE\nOFF")
        self.var_beep.set(r.status.beep)

    # ─────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────

    def _toggle_output(self):
        if self._psu is None or self._last_reading is None:
            return
        on = not self._last_reading.status.output_on
        self._send(lambda p: p.set_output(on),
                   f"Sortie {'ON' if on else 'OFF'}")

    def _parse_entry(self, var: tk.StringVar, name: str) -> float | None:
        try:
            return float(var.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("KORAD", f"{name} : valeur invalide.")
            return None

    def _apply_voltage(self):
        v = self._parse_entry(self.var_vset, "Tension")
        if v is not None:
            self._send(lambda p: p.set_voltage(v), f"VSET {v:.2f} V")

    def _apply_current(self):
        i = self._parse_entry(self.var_iset, "Courant")
        if i is not None:
            self._send(lambda p: p.set_current(i), f"ISET {i:.3f} A")

    def _apply_both(self):
        self._apply_voltage()
        self._apply_current()

    def _load_setpoints(self):
        def act(p: KoradKA3005P):
            self.var_vset.set(f"{p.get_voltage_setpoint():.2f}")
            self.var_iset.set(f"{p.get_current_setpoint():.3f}")
        self._send(act, "Consignes relues.")

    def _recall(self, n: int):
        self._send(lambda p: p.recall_memory(n), f"Mémoire M{n} rappelée")
        self.after(300, self._load_setpoints)

    def _save(self, n: int):
        if messagebox.askyesno("KORAD", f"Écraser la mémoire M{n} avec les "
                               f"consignes actuelles ?"):
            self._send(lambda p: p.save_memory(n), f"Mémoire M{n} sauvée")


if __name__ == "__main__":
    KoradApp().mainloop()
