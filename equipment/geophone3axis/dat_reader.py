"""
Lecture des enregistrements `.dat` des unités géophone 3 axes.

Format (cf. geophones-product `docs/data-format.md`) : **miniSEED v3 (FDSN)**,
écrit par le firmware via **libmseed** (fork CAUR). Caractéristiques :
  * échantillons **int32** (ADC 24 bits signé étendu), records 4096 o ;
  * fichier = `survey-data/{survey_id}/{sn}_{YYYYMMDDTHHMMSS}.dat`, 1 record
    d'en-tête puis des records d'échantillons **par voie** ;
  * voie ADC dans l'extra-header **`caurtech.channel`** : "1" | "2" | "3"
    (historique), "X" | "Y" | "Z" (V3.1 depuis le SID FDSN) ou "X_GH"… (V3.2) —
    voir `channel_axis()` ;
  * horodatage en **nanosecondes depuis l'époque Unix (UTC)**, RTC disciplinée
    par le 1PPS GNSS.

Backend Python : **simplemseed** (pur Python, lit le miniSEED **v3** FDSN). ⚠️ NE
PAS utiliser `obspy.read(format="MSEED")` : ObsPy ne gère que le miniSEED **v2** et
échoue sur ces fichiers (magic `MS\\x03`, `julday out of bounds`). Le lecteur est
**découplé** : `read_dat` renvoie une liste de `Channel3Axis` neutres, indépendante
du backend, pour pouvoir basculer sur d'autres bindings libmseed sans toucher au banc.

VALIDÉ contre un vrai `.dat` (unité CG0-000008, 2026-08-10) :
  * record d'en-tête (numSamples=0) → `caurtech.*` fichier (device_sn, geophone,
    gps_position, adc_gain, software_version, tilt…) ;
  * records de données → `caurtech.channel` = "1" | "2" | "3", samples int32 ;
  * extra-headers lus via `record.eh` (dict) — `header.extraHeadersStr` reste vide
    dans simplemseed 1.0.2, ne pas s'y fier.
"""

import datetime
import os
import struct
from dataclasses import dataclass, field

import numpy as np

_EPOCH_UTC = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

# Pleine échelle des unités 3 axes = ADS1285. Datasheet (Documents/ads1285.pdf) :
# VIN pleine échelle = ±VREF / (1,6384 × Gain) pour VREF = 4,096 V → **±2,5 V à
# gain 1** (la datasheet normalise à ±2,5 V quelle que soit la réf : 5V/2, 4,096V/
# 1,6384, 2,5V/1 valent tous ±2,5 V). C'est la MÊME valeur que l'ADS1285 EVM du banc
# (config full_scale_vpeak = 2,5 V, validée ST-2A 265 vs 260 datasheet).
# ⚠️ CORRIGÉ 2026-08-11 : était 2,048 V (±VREF/2, erroné) → sous-estimait la
# sensibilité 3 axes de ×1,22. 1 LSB @ g1 = 2,5 / 2³¹ ≈ 1,16 nV.
#
# ⚠️ NE PAS se contenter de changer cette constante quand le convertisseur changera
# (annoncé pour la carte V3.2) : elle rendrait fausses, en silence et d'un facteur
# invisible à la lecture, toutes les conversions des enregistrements déjà archivés.
# Passer par `fullscale_vpeak_g1()`, qui interroge l'en-tête du fichier.
UNIT3AXIS_FULLSCALE_VPEAK_G1 = 2.5

# Pleine échelle [V crête à gain 1] par révision matérielle, telle que rapportée dans
# l'en-tête `caurtech.hardware_revision`. Une seule entrée aujourd'hui : la V2 comme la
# V3.1 portent l'ADS1285, et toutes deux **strappent la révision 1**.
#
# La V2 et la V3.1 rapportent toutes deux 1 : elles ne se discriminaient pas, faute
# d'en avoir eu besoin. La V3.2 change de convertisseur, donc de pleine échelle, et
# strappera `I0` au 3V pour rapporter **2** (décidé 2026-09-04 ; ⚠️ pas encore reporté
# dans les fichiers de conception à cette date). Voir
# `geophones-firmware/doc/hardware/board-revisions.md`.
FULLSCALE_VPEAK_G1_BY_HWREV = {
    1: 2.5,  # V2 et V3.1 — ADS1285, VREF 4,096 V (REF6041)
    2: 2.4,  # V3.2 — ADS131E08, référence interne 2,4 V (CONFIG3 PD_REFBUF=1, VREF_4V=0),
             # PGA 1 : ±2,4 V différentiels (Oliver Munroe, 2026-09-08). Le firmware V3.2
             # écrit aussi `adc_full_scale_v` dans l'en-tête (header_version 2), qui prime.
             # ⚠ V3.2 = 24 bits sign-extended sur 32 : le rapport counts/FS reste 2^31.
             # ⚠ Voies GH (×25 analogique) : le gain de la chaîne est `analog_gain` × `adc_gain`.
}


# --- Identifiants de voie (`caurtech.channel`) -------------------------------
# Trois générations d'étiquettes coexistent dans les fichiers :
#   * "1" | "2" | "3"          firmware V3.1 jusqu'au SID FDSN (2026-09) ;
#   * "X" | "Y" | "Z"          firmware V3.1 à partir du SID (J4/J5/J6 = X/Y/Z) ;
#   * "X_GH", "X_GL", ...      carte V3.2 (deux chemins de gain par axe), plus
#                              "AUX1"/"AUX2" pour les entrées d'extension.
# Repère de l'unité : X = est, Y = nord, Z = haut (geophones-product,
# convention-orientation-polarite.md). "1"/"2"/"3" valent X/Y/Z (J4/J5/J6).
_LEGACY_AXIS = {"1": "X", "2": "Y", "3": "Z"}
AXES = ("X", "Y", "Z")


def channel_axis(channel_id: str) -> str | None:
    """Axe ("X" | "Y" | "Z") d'une voie, ou None si ce n'est pas une voie d'axe
    (AUX, étiquette inconnue). Accepte les trois générations d'étiquettes."""
    cid = str(channel_id)
    if cid in _LEGACY_AXIS:
        return _LEGACY_AXIS[cid]
    head = cid.split("_", 1)[0]
    return head if head in AXES else None


def axis_channel_ids(present) -> list[str]:
    """Voies d'axe présentes, rangées X, Y, Z (puis GH avant GL à axe égal).

    `present` : itérable d'identifiants (clés d'un dict de résultats, par ex.).
    Les voies qui ne sont pas des axes (AUX) sont écartées.
    """
    ids = [str(c) for c in present if channel_axis(c) is not None]
    return sorted(ids, key=lambda c: (AXES.index(channel_axis(c)), c))


def missing_axes(present) -> list[str]:
    """Axes (parmi X, Y, Z) qu'aucune voie de `present` ne couvre."""
    covered = {channel_axis(c) for c in present}
    return [a for a in AXES if a not in covered]


def fullscale_vpeak_g1(meta: dict | None = None) -> float:
    """Pleine échelle [V crête à gain 1] de l'unité qui a produit un enregistrement.

    Résout dans cet ordre, du plus fiable au moins fiable :

    1. `caurtech.adc_full_scale_v` de l'en-tête, si le firmware l'écrit. Ce champ
       n'existe pas encore ; le prévoir rend les fichiers auto-descriptifs et
       dispense définitivement le banc de maintenir une table.
    2. `caurtech.hardware_revision` via `FULLSCALE_VPEAK_G1_BY_HWREV`.
    3. `UNIT3AXIS_FULLSCALE_VPEAK_G1` par défaut, ce qui suppose l'ADS1285.

    Passer le `meta` d'un `Channel3Axis` (ou son sous-dictionnaire `file`).
    """
    if not meta:
        return UNIT3AXIS_FULLSCALE_VPEAK_G1
    # Accepte indifféremment le meta de la voie ou l'en-tête de fichier lui-même.
    header = meta.get("file", meta) if isinstance(meta, dict) else {}
    if not isinstance(header, dict):
        return UNIT3AXIS_FULLSCALE_VPEAK_G1

    explicit = header.get("adc_full_scale_v")
    if explicit:
        try:
            return float(explicit)
        except (TypeError, ValueError):
            pass

    rev = header.get("hardware_revision")
    if rev is not None:
        try:
            return FULLSCALE_VPEAK_G1_BY_HWREV[int(rev)]
        except (TypeError, ValueError):
            pass
        except KeyError:
            # Révision inconnue : mieux vaut une conversion visiblement suspecte
            # qu'une conversion silencieusement fausse. Message en ASCII pur — une
            # console cp1252 lève sur un emoji, et un avertissement ne doit jamais
            # faire tomber l'appelant.
            print(f"[dat_reader] ATTENTION: revision materielle {rev!r} inconnue - "
                  f"pleine echelle supposee {UNIT3AXIS_FULLSCALE_VPEAK_G1} V "
                  f"(ADS1285). Completer FULLSCALE_VPEAK_G1_BY_HWREV.")
    return UNIT3AXIS_FULLSCALE_VPEAK_G1


def counts_to_volts(counts, gain: int = 1, *, meta: dict | None = None,
                    full_scale_vpeak: float | None = None) -> np.ndarray:
    """Convertit des counts int32 d'une unité 3 axes en volts.

    L'ADS1285 est un convertisseur **32 bits** (fiche §1), pas un 24 bits étendu :
    la pleine échelle correspond bien à 2³¹, comme le fait le calcul ci-dessous.

    Pleine échelle divisée par le gain PGA (le gain est dans l'en-tête .dat
    `caurtech.adc_gain` / renvoyé par CONFIG?). Sert au calcul de sensibilité
    3 axes counts/(m/s) -> V/(m/s).

    Passer `meta` (celui d'un `Channel3Axis`) pour que la pleine échelle soit tirée
    de l'en-tête du fichier plutôt que supposée — indispensable dès que deux
    générations de convertisseur coexistent. `full_scale_vpeak` force la valeur.
    À défaut des deux, l'ADS1285 est supposé.
    """
    fs = full_scale_vpeak if full_scale_vpeak else fullscale_vpeak_g1(meta)
    return (np.asarray(counts, dtype=np.float64)
            * (fs / float(gain)) / (2 ** 31))


@dataclass
class Channel3Axis:
    """Une voie (axe) d'un enregistrement 3 axes, indépendante du backend.

    `start_time_ns` + `sample_rate_hz` décrivent une grille RÉGULIÈRE, ce que
    veulent les traitements en aval (lock-in, Welch, corrélation). Mais le
    fichier porte **un horodatage RTC par record**, et cette grille les ignore
    tous sauf le premier : toute divergence entre l'horloge de l'unité et le
    taux nominal s'accumule alors en silence. `segments` conserve la vérité
    brute et `timing_report()` chiffre l'écart — voir ces deux-là avant de
    croire un alignement temporel sur un fichier long.
    """
    channel_id: str                 # "1".."3", "X".."Z" ou "X_GH"… : voir channel_axis()
    data: np.ndarray                # échantillons int32 (counts ADC)
    start_time_ns: int              # ns depuis l'époque Unix (UTC) du 1er échantillon
    sample_rate_hz: float
    meta: dict = field(default_factory=dict)   # extra-headers caurtech.* utiles
    segments: list = field(default_factory=list)  # [(start_ns, n_samples)] par record

    @property
    def sample_times_ns(self) -> np.ndarray:
        """Temps UTC (ns Unix) de chaque échantillon, grille régulière nominale.

        Ancre le 1er record puis compte au taux nominal. Inchangé : c'est le
        contrat historique. Sur un fichier long, préférer
        `sample_times_ns_anchored` et lire d'abord `timing_report()`.
        """
        step = 1e9 / self.sample_rate_hz
        return self.start_time_ns + (np.arange(len(self.data)) * step).astype(np.int64)

    @property
    def sample_times_ns_anchored(self) -> np.ndarray:
        """Idem, mais chaque record est ancré sur SON PROPRE horodatage RTC.

        Ne laisse rien s'accumuler : l'erreur reste celle d'un seul record
        (quelques µs) au lieu de croître avec la durée du fichier. En échange,
        la grille n'est plus rigoureusement uniforme — les frontières de record
        portent la gigue d'horodatage (~20 µs sur un firmware à prescaler
        corrigé, ~1,6 ms avant). Retombe sur la grille nominale si les segments
        ne sont pas disponibles.
        """
        if not self.segments:
            return self.sample_times_ns
        step = 1e9 / self.sample_rate_hz
        out = np.empty(len(self.data), dtype=np.int64)
        i = 0
        for start_ns, n in self.segments:
            out[i:i + n] = start_ns + (np.arange(n) * step).astype(np.int64)
            i += n
        return out

    @property
    def full_scale_vpeak_g1(self) -> float:
        """Pleine échelle [V crête à gain 1] de l'unité qui a produit cette voie.

        Tirée de l'en-tête du fichier, pas d'une constante du banc : une voie sait
        de quelle génération de matériel elle vient. Voir `fullscale_vpeak_g1()`.
        """
        return fullscale_vpeak_g1(self.meta)

    def to_volts(self, gain: int | None = None) -> np.ndarray:
        """Échantillons de cette voie en volts, pleine échelle résolue par l'en-tête.

        `gain` par défaut = `caurtech.adc_gain` du fichier, donc le gain réellement
        employé à l'enregistrement plutôt qu'une valeur fournie de l'extérieur.
        """
        if gain is None:
            gain = int(self.meta.get("file", {}).get("adc_gain", 1) or 1)
        return counts_to_volts(self.data, gain, meta=self.meta)

    def timing_report(self, *, gap_tolerance_ns: int = 20_000_000) -> dict:
        """Confronte les horodatages RTC des records à la grille nominale.

        C'est ici qu'on voit le décalage plutôt que de le subir. Ajuste une
        droite (moindres carrés) sur les débuts de records en fonction de
        l'indice cumulé d'échantillon : la pente donne la période réelle, donc
        la cadence mesurée contre l'UTC, et les résidus donnent la gigue.

        Retour :
          * `n_records`, `duration_s`
          * `sample_rate_measured_hz` / `drift_ppm` — cadence réelle vs nominale
          * `jitter_rms_ns` / `jitter_max_ns` — résidus à la droite ajustée
          * `nominal_divergence_ns` — écart, au DERNIER record, entre la grille
            nominale et l'horodatage RTC. C'est l'erreur que `sample_times_ns`
            commet en fin de fichier.
          * `gaps` — [(index, delta_observe_ns, delta_attendu_ns)] pour tout
            enchaînement qui s'écarte de plus de `gap_tolerance_ns` du nominal :
            record manquant, ou recalage brutal de la RTC.

        `{}` si moins de deux records (rien à confronter).
        """
        if len(self.segments) < 2:
            return {}
        starts = np.array([s for s, _ in self.segments], dtype=np.int64)
        counts = np.array([n for _, n in self.segments], dtype=np.int64)
        # Indice cumulé du 1er échantillon de chaque record.
        idx = np.concatenate(([0], np.cumsum(counts)[:-1])).astype(np.float64)
        # Régression sur des ns RELATIFS : l'époque Unix en 2026 (~1,8e18 ns)
        # dépasse les entiers exacts d'un float64, une régression sur les temps
        # absolus perdrait ~250 ns avant même de commencer.
        rel = (starts - starts[0]).astype(np.float64)
        slope, intercept = np.polyfit(idx, rel, 1)      # ns par échantillon
        resid = rel - (slope * idx + intercept)

        step_nominal = 1e9 / self.sample_rate_hz
        fs_measured = 1e9 / slope if slope > 0 else float("nan")
        # Ce que la grille nominale prédit pour le dernier record, vs le RTC.
        divergence = float(rel[-1] - step_nominal * idx[-1])

        gaps = []
        for k in range(len(starts) - 1):
            observed = int(starts[k + 1] - starts[k])
            expected = int(round(step_nominal * counts[k]))
            if abs(observed - expected) > gap_tolerance_ns:
                gaps.append((k, observed, expected))

        return {
            "n_records": len(starts),
            "duration_s": float(rel[-1] / 1e9),
            "sample_rate_nominal_hz": self.sample_rate_hz,
            "sample_rate_measured_hz": float(fs_measured),
            "drift_ppm": float((fs_measured - self.sample_rate_hz)
                               / self.sample_rate_hz * 1e6),
            "jitter_rms_ns": float(np.sqrt(np.mean(resid ** 2))),
            "jitter_max_ns": float(np.max(np.abs(resid))),
            "nominal_divergence_ns": divergence,
            "gaps": gaps,
        }


def _caurtech(rec) -> dict:
    """Section `caurtech` de l'extra-header d'un record simplemseed (`record.eh`)."""
    eh = getattr(rec, "eh", None)
    if isinstance(eh, dict):
        caur = eh.get("caurtech")
        if isinstance(caur, dict):
            return caur
    return {}


def _start_ns(rec) -> int:
    """Instant du 1er échantillon d'un record → ns depuis l'époque Unix (UTC).

    `record.starttime` est un `datetime` aware (précision µs, suffisante à
    250 Hz) ; le mseed3 porte la ns mais l'alignement banc se fait au 1PPS et au
    lock-in, pas au ns.

    Conversion en arithmétique ENTIÈRE : `timestamp()` rend un float, et l'époque
    Unix en ns (~1,8e18) dépasse les entiers exacts d'un float64 — la
    multiplication par 1e9 introduirait ~250 ns de flou. Sans conséquence sur une
    grille à 3,9 ms, mais plus du tout négligeable depuis que les horodatages
    valent ~30 µs.
    """
    t0 = rec.starttime
    delta = t0 - _EPOCH_UTC
    return ((delta.days * 86400 + delta.seconds) * 1_000_000_000
            + delta.microseconds * 1000)


def read_dat(path: str) -> list[Channel3Axis]:
    """Lit un `.dat` miniSEED v3 → liste de `Channel3Axis` (une par voie présente).

    Les records d'une même voie (`caurtech.channel`) sont concaténés dans l'ordre
    temporel. Le record d'en-tête (numSamples=0) fournit les métadonnées fichier
    (device_sn, geophone, gps_position, adc_gain…), recopiées dans `meta` de chaque
    voie.
    """
    try:
        import simplemseed
        from simplemseed.mseed3 import Miniseed3Exception
        try:
            from simplemseed.exceptions import CodecException
        except ImportError:                      # emplacement selon version
            from simplemseed import CodecException
    except ImportError:
        raise ImportError(
            "Lecture des .dat 3 axes : simplemseed requis (miniSEED v3). "
            "Installer : pip install .[mseed]  (ObsPy ne lit PAS le miniSEED v3)."
        )

    file_meta: dict = {}
    by_ch: dict[str, list] = {}      # voie -> [(start_ns, sample_rate, samples)]
    skipped = 0
    # Lecture TOLÉRANTE : un record corrompu ne doit PAS jeter tout le fichier ni
    # tout le run. La corruption (transfert GET/CDC — byte flippé, ou queue tronquée
    # au STOP) se manifeste de plusieurs façons SELON l'octet touché :
    #   * CRC fail (data)           -> Miniseed3Exception
    #   * décompression invalide    -> CodecException
    #   * identifiant/extra-header  -> UnicodeDecodeError (décodés AVANT le CRC)
    #   * en-tête fixe corrompu     -> struct.error / ValueError
    # `readMSeed3Records` lève dès le 1er record invalide et le générateur meurt ;
    # on garde tous les BONS records lus avant, et on abandonne la suite de CE
    # fichier seulement (les autres `.dat` restent lus normalement).
    _CORRUPT = (Miniseed3Exception, CodecException, UnicodeDecodeError,
                struct.error, ValueError)
    with open(path, "rb") as fp:
        it = simplemseed.readMSeed3Records(fp)
        while True:
            try:
                rec = next(it)
                caur = _caurtech(rec)
                if rec.header.numSamples == 0:
                    # Record d'en-tête fichier : métadonnées globales.
                    file_meta.update(caur)
                    continue
                ch = str(caur.get("channel") or (len(by_ch) + 1))
                samples = np.asarray(rec.decompress(), dtype=np.int32)
                by_ch.setdefault(ch, []).append(
                    (_start_ns(rec), float(rec.header.sampleRate), samples))
            except StopIteration:
                break
            except _CORRUPT as e:
                skipped += 1
                print(f"[dat_reader] {os.path.basename(path)} : record corrompu "
                      f"ignoré ({type(e).__name__}: {e}) — "
                      f"{sum(len(v) for v in by_ch.values())} bons records conservés.")
                break
    if skipped:
        file_meta = {**file_meta, "records_skipped": skipped}

    channels: list[Channel3Axis] = []
    for ch, segs in sorted(by_ch.items()):
        segs.sort(key=lambda s: s[0])
        data = np.concatenate([s[2] for s in segs])
        meta = {"segments": len(segs), "file": file_meta}
        channels.append(Channel3Axis(
            channel_id=ch,
            data=data,
            start_time_ns=segs[0][0],
            sample_rate_hz=segs[0][1],
            meta=meta,
            # Horodatage RTC de CHAQUE record, conservé tel quel. Les échantillons
            # sont concaténés pour l'aval, mais la datation d'origine ne doit pas
            # disparaître avec eux : c'est la seule trace d'un trou ou d'un
            # recalage d'horloge une fois les records soudés bout à bout.
            segments=[(s[0], len(s[2])) for s in segs],
        ))
    return channels
