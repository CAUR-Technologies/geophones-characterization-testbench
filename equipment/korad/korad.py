"""
Module KORAD KA3005P — alimentation de laboratoire programmable 0-30 V / 0-5 A.
Interface USB-série (puce Nuvoton, VID:PID 0416:5011) via pyserial.

Protocole (commun aux KA30xxP / Tenma 72-2535 / RND 320 / Velleman LABPS3005D) :
- Série : 9600 baud, 8 bits, sans parité, 1 stop, pas de contrôle de flux
- Commandes ASCII SANS terminateur (ni CR ni LF) ; réponses SANS terminateur
  non plus -> lecture par longueur attendue ou par timeout
- Un seul canal (suffixe "1") ; laisser >= 50 ms entre deux commandes
- Commandes :
    *IDN?          -> "KORAD KA3005P V1.5 SN:01639635"
    STATUS?        -> 1 octet (bits, voir KoradStatus)
    VSET1:12.34    / VSET1?  -> "12.34"   consigne tension (V, 2 décimales)
    ISET1:1.234    / ISET1?  -> "1.234"   consigne courant (A, 3 décimales)
    VOUT1?         -> "12.34"             tension mesurée en sortie
    IOUT1?         -> "1.234"             courant mesuré en sortie
    OUT1 / OUT0                           sortie activée / désactivée
    OVP1 / OVP0                           protection surtension
    OCP1 / OCP0                           protection surcourant
    BEEP1 / BEEP0                         bip touches
    SAV1..5 / RCL1..5                     mémoires de consignes

Vérifié en direct sur l'appareil (firmware V1.5) le 2026-09-22.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from config.settings import KORAD_PORT, KORAD_BAUD, KORAD_TIMEOUT
from equipment.instrlog import get_logger


@dataclass(frozen=True)
class KoradStatus:
    """Décodage de l'octet renvoyé par STATUS?.

    bit 0 : mode CH1 — 0 = CC (courant constant), 1 = CV (tension constante)
    bit 1 : mode CH2 (inexistant sur KA3005P)
    bits 2-3 : tracking (multi-canaux, sans objet ici)
    bit 4 : bip touches actif
    bit 5 : verrouillage clavier (selon firmware ; peut refléter OVP/OCP)
    bit 6 : sortie activée
    bit 7 : réservé

    NB : l'état OVP/OCP n'est PAS lisible de façon fiable via STATUS? sur ce
    firmware ; le pilote mémorise localement les dernières valeurs envoyées.
    """
    raw: int
    cv_mode: bool       # True = CV, False = CC
    beep: bool
    lock: bool
    output_on: bool

    @classmethod
    def from_byte(cls, b: int) -> "KoradStatus":
        return cls(
            raw=b,
            cv_mode=bool(b & 0x01),
            beep=bool(b & 0x10),
            lock=bool(b & 0x20),
            output_on=bool(b & 0x40),
        )

    @property
    def mode(self) -> str:
        return "CV" if self.cv_mode else "CC"


@dataclass(frozen=True)
class KoradReading:
    """Photo instantanée de l'alimentation (consignes + mesures + statut)."""
    v_set: float
    i_set: float
    v_out: float
    i_out: float
    status: KoradStatus

    @property
    def power_w(self) -> float:
        return self.v_out * self.i_out


class KoradKA3005P:
    """Contrôle l'alimentation KORAD KA3005P via USB-série."""

    USB_VID = 0x0416
    USB_PID = 0x5011

    MIN_VOLTAGE = 0.0
    MAX_VOLTAGE = 30.0
    MIN_CURRENT = 0.0
    MAX_CURRENT = 5.0
    MEMORY_SLOTS = (1, 2, 3, 4, 5)

    # Délai minimal entre deux commandes (l'appareil ignore les commandes
    # trop rapprochées, valeur empirique communément admise : 50 ms).
    _CMD_GAP_S = 0.05

    def __init__(self, port: str = KORAD_PORT, baud: int = KORAD_BAUD,
                 timeout: float = KORAD_TIMEOUT):
        self._port = port
        self._baud = baud
        self._timeout = timeout
        self._serial: serial.Serial | None = None
        self._lock = threading.RLock()
        self._last_cmd_t = 0.0
        self._log = get_logger("Korad")
        # États non relisibles : mémorisés côté pilote.
        self.ovp_enabled: bool | None = None
        self.ocp_enabled: bool | None = None

    # ─────────────────────────────────────────────────────────────────────
    # Détection / connexion
    # ─────────────────────────────────────────────────────────────────────

    @classmethod
    def find_ports(cls) -> list[str]:
        """Ports COM dont le VID:PID USB correspond au KORAD."""
        return sorted(
            p.device for p in list_ports.comports()
            if p.vid == cls.USB_VID and p.pid == cls.USB_PID
        )

    @property
    def port(self) -> str:
        return self._port

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self) -> str:
        """Ouvre la liaison série et retourne la chaîne d'identification.

        Si le port configuré vaut "auto", le premier port au VID:PID KORAD est
        utilisé. Lève RuntimeError si l'appareil ne répond pas à *IDN?.
        """
        port = self._port
        if not port or port.lower() == "auto":
            found = self.find_ports()
            if not found:
                raise RuntimeError(
                    "Aucun KORAD détecté (VID:PID 0416:5011). "
                    "Renseigner [Korad] port dans config.ini.")
            port = found[0]
        with self._lock:
            self._serial = serial.Serial(
                port=port,
                baudrate=self._baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self._timeout,
                write_timeout=self._timeout,
            )
            self._port = port
            self._serial.reset_input_buffer()
            idn = self.identify()
        if not idn:
            self.disconnect()
            raise RuntimeError(f"Pas de réponse à *IDN? sur {port}.")
        self._log.info(f"Connecté sur {port} : {idn}")
        print(f"KORAD connecté sur {port} : {idn}")
        return idn

    def disconnect(self) -> None:
        with self._lock:
            if self._serial is not None:
                try:
                    self._serial.close()
                finally:
                    self._serial = None
        self._log.info("Déconnecté.")

    def __enter__(self) -> "KoradKA3005P":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    # ─────────────────────────────────────────────────────────────────────
    # Couche transport
    # ─────────────────────────────────────────────────────────────────────

    def _require(self) -> serial.Serial:
        if not self.is_connected:
            raise RuntimeError("KORAD non connecté : appeler connect() d'abord.")
        return self._serial  # type: ignore[return-value]

    def _write(self, cmd: str) -> None:
        """Envoie une commande brute (sans terminateur), en respectant le gap."""
        with self._lock:
            ser = self._require()
            gap = self._CMD_GAP_S - (time.monotonic() - self._last_cmd_t)
            if gap > 0:
                time.sleep(gap)
            ser.reset_input_buffer()
            ser.write(cmd.encode("ascii"))
            ser.flush()
            self._last_cmd_t = time.monotonic()
            self._log.debug(f"TX {cmd!r}")

    def _query(self, cmd: str, length: int | None = None) -> str:
        """Envoie une requête et lit la réponse.

        length : nombre d'octets attendus (réponse à longueur fixe) ; None
        = lecture jusqu'au timeout (réponse de longueur variable, ex. *IDN?).
        """
        with self._lock:
            self._write(cmd)
            ser = self._require()
            if length is not None:
                raw = ser.read(length)
            else:
                raw = ser.read(64)
            self._log.debug(f"RX {raw!r}")
        return raw.decode("ascii", errors="replace").strip("\x00\r\n ")

    @staticmethod
    def _parse_float(text: str, cmd: str) -> float:
        # Certains firmwares ajoutent un octet parasite en fin de réponse.
        cleaned = "".join(ch for ch in text if ch in "0123456789.")
        try:
            return float(cleaned)
        except ValueError:
            raise RuntimeError(f"Réponse illisible à {cmd} : {text!r}") from None

    # ─────────────────────────────────────────────────────────────────────
    # Identification / statut
    # ─────────────────────────────────────────────────────────────────────

    def identify(self) -> str:
        return self._query("*IDN?")

    def get_status(self) -> KoradStatus:
        raw = self._query("STATUS?", length=1)
        if not raw:
            # Un statut à 0x00 est décodé comme chaîne vide par strip() :
            # relire l'octet brut.
            with self._lock:
                self._write("STATUS?")
                data = self._require().read(1)
            if not data:
                raise RuntimeError("Pas de réponse à STATUS?.")
            return KoradStatus.from_byte(data[0])
        return KoradStatus.from_byte(ord(raw[0]))

    def read_all(self) -> KoradReading:
        """Lit consignes, mesures et statut en une passe (pour le polling)."""
        with self._lock:
            return KoradReading(
                v_set=self.get_voltage_setpoint(),
                i_set=self.get_current_setpoint(),
                v_out=self.read_voltage(),
                i_out=self.read_current(),
                status=self.get_status(),
            )

    # ─────────────────────────────────────────────────────────────────────
    # Consignes
    # ─────────────────────────────────────────────────────────────────────

    def set_voltage(self, volts: float) -> None:
        if not self.MIN_VOLTAGE <= volts <= self.MAX_VOLTAGE:
            raise ValueError(
                f"Tension {volts} V hors plage "
                f"[{self.MIN_VOLTAGE}, {self.MAX_VOLTAGE}] V")
        self._write(f"VSET1:{volts:05.2f}")
        self._log.info(f"Consigne tension {volts:.2f} V")

    def get_voltage_setpoint(self) -> float:
        return self._parse_float(self._query("VSET1?", length=5), "VSET1?")

    def set_current(self, amps: float) -> None:
        if not self.MIN_CURRENT <= amps <= self.MAX_CURRENT:
            raise ValueError(
                f"Courant {amps} A hors plage "
                f"[{self.MIN_CURRENT}, {self.MAX_CURRENT}] A")
        self._write(f"ISET1:{amps:05.3f}")
        self._log.info(f"Consigne courant {amps:.3f} A")

    def get_current_setpoint(self) -> float:
        # Certains firmwares renvoient 6 octets (octet parasite) : lecture
        # à 5 suffit, le 6e est purgé par le reset_input_buffer suivant.
        return self._parse_float(self._query("ISET1?", length=5), "ISET1?")

    # ─────────────────────────────────────────────────────────────────────
    # Mesures
    # ─────────────────────────────────────────────────────────────────────

    def read_voltage(self) -> float:
        """Tension réellement présente en sortie (V)."""
        return self._parse_float(self._query("VOUT1?", length=5), "VOUT1?")

    def read_current(self) -> float:
        """Courant réellement débité (A)."""
        return self._parse_float(self._query("IOUT1?", length=5), "IOUT1?")

    # ─────────────────────────────────────────────────────────────────────
    # Sortie / protections
    # ─────────────────────────────────────────────────────────────────────

    def set_output(self, on: bool) -> None:
        self._write("OUT1" if on else "OUT0")
        self._log.info(f"Sortie {'ON' if on else 'OFF'}")

    def output_on(self) -> None:
        self.set_output(True)

    def output_off(self) -> None:
        self.set_output(False)

    def set_ovp(self, on: bool) -> None:
        self._write("OVP1" if on else "OVP0")
        self.ovp_enabled = on
        self._log.info(f"OVP {'ON' if on else 'OFF'}")

    def set_ocp(self, on: bool) -> None:
        self._write("OCP1" if on else "OCP0")
        self.ocp_enabled = on
        self._log.info(f"OCP {'ON' if on else 'OFF'}")

    def set_beep(self, on: bool) -> None:
        self._write("BEEP1" if on else "BEEP0")

    # ─────────────────────────────────────────────────────────────────────
    # Mémoires
    # ─────────────────────────────────────────────────────────────────────

    def save_memory(self, slot: int) -> None:
        if slot not in self.MEMORY_SLOTS:
            raise ValueError(f"Mémoire {slot} invalide (1..5)")
        self._write(f"SAV{slot}")

    def recall_memory(self, slot: int) -> None:
        if slot not in self.MEMORY_SLOTS:
            raise ValueError(f"Mémoire {slot} invalide (1..5)")
        self._write(f"RCL{slot}")
