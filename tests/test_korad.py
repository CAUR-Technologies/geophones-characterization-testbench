"""
Tests unitaires du pilote KORAD KA3005P (liaison série moquée).
Aucune connexion matérielle requise.
"""

import unittest
from unittest.mock import MagicMock, patch

from equipment.korad import KoradKA3005P, KoradStatus


def _fake_psu(read_returns=None):
    """Instancie un pilote avec un port série factice déjà 'ouvert'."""
    psu = KoradKA3005P(port="COM99")
    ser = MagicMock()
    ser.is_open = True
    if read_returns is not None:
        ser.read.side_effect = read_returns
    psu._serial = ser
    psu._CMD_GAP_S = 0.0
    return psu, ser


def _sent(ser) -> list[str]:
    return [c.args[0].decode() for c in ser.write.call_args_list]


class TestKoradStatus(unittest.TestCase):
    def test_decode_output_on_cv(self):
        st = KoradStatus.from_byte(0x51)      # 0b0101_0001
        self.assertTrue(st.cv_mode)
        self.assertTrue(st.output_on)
        self.assertTrue(st.beep)
        self.assertFalse(st.lock)
        self.assertEqual(st.mode, "CV")

    def test_decode_output_off_cc(self):
        st = KoradStatus.from_byte(0x00)
        self.assertFalse(st.cv_mode)
        self.assertFalse(st.output_on)
        self.assertEqual(st.mode, "CC")


class TestKoradCommands(unittest.TestCase):
    def test_set_voltage_format(self):
        psu, ser = _fake_psu()
        psu.set_voltage(5.0)
        self.assertIn("VSET1:05.00", _sent(ser))

    def test_set_current_format(self):
        psu, ser = _fake_psu()
        psu.set_current(0.5)
        self.assertIn("ISET1:0.500", _sent(ser))

    def test_output_commands(self):
        psu, ser = _fake_psu()
        psu.output_on()
        psu.output_off()
        self.assertEqual(_sent(ser), ["OUT1", "OUT0"])

    def test_protection_commands_track_state(self):
        psu, ser = _fake_psu()
        psu.set_ovp(True)
        psu.set_ocp(False)
        self.assertEqual(_sent(ser), ["OVP1", "OCP0"])
        self.assertTrue(psu.ovp_enabled)
        self.assertFalse(psu.ocp_enabled)

    def test_voltage_out_of_range_raises(self):
        psu, _ = _fake_psu()
        with self.assertRaises(ValueError):
            psu.set_voltage(31.0)
        with self.assertRaises(ValueError):
            psu.set_voltage(-1.0)

    def test_current_out_of_range_raises(self):
        psu, _ = _fake_psu()
        with self.assertRaises(ValueError):
            psu.set_current(5.5)

    def test_invalid_memory_slot_raises(self):
        psu, _ = _fake_psu()
        with self.assertRaises(ValueError):
            psu.save_memory(9)
        with self.assertRaises(ValueError):
            psu.recall_memory(0)

    def test_commands_require_connection(self):
        psu = KoradKA3005P(port="COM99")
        with self.assertRaises(RuntimeError):
            psu.set_voltage(1.0)


class TestKoradQueries(unittest.TestCase):
    def test_read_voltage_parses(self):
        psu, _ = _fake_psu([b"12.34"])
        self.assertAlmostEqual(psu.read_voltage(), 12.34)

    def test_read_current_parses(self):
        psu, _ = _fake_psu([b"1.234"])
        self.assertAlmostEqual(psu.read_current(), 1.234)

    def test_setpoint_parsing_tolerates_trailing_junk(self):
        psu, _ = _fake_psu([b"07.40\x00"])
        self.assertAlmostEqual(psu.get_voltage_setpoint(), 7.40)

    def test_unreadable_reply_raises(self):
        psu, _ = _fake_psu([b""])
        with self.assertRaises(RuntimeError):
            psu.read_voltage()

    def test_status_zero_byte_is_decoded(self):
        # b"\x00" -> strip() donne une chaine vide : le pilote doit relire
        # l'octet brut au lieu de conclure a une absence de reponse.
        psu, _ = _fake_psu([b"\x00", b"\x00"])
        st = psu.get_status()
        self.assertEqual(st.raw, 0)
        self.assertFalse(st.output_on)

    def test_read_all_aggregates(self):
        psu, _ = _fake_psu([b"05.00", b"1.000", b"04.98", b"0.250", b"\x51"])
        r = psu.read_all()
        self.assertAlmostEqual(r.v_set, 5.0)
        self.assertAlmostEqual(r.i_set, 1.0)
        self.assertAlmostEqual(r.v_out, 4.98)
        self.assertAlmostEqual(r.i_out, 0.25)
        self.assertTrue(r.status.output_on)
        self.assertAlmostEqual(r.power_w, 4.98 * 0.25)


class TestKoradDiscovery(unittest.TestCase):
    @patch("equipment.korad.korad.list_ports.comports")
    def test_find_ports_filters_on_vid_pid(self, mock_comports):
        good = MagicMock(device="COM8", vid=0x0416, pid=0x5011)
        bad = MagicMock(device="COM3", vid=0x0483, pid=0x2545)
        mock_comports.return_value = [bad, good]
        self.assertEqual(KoradKA3005P.find_ports(), ["COM8"])

    @patch("equipment.korad.korad.list_ports.comports", return_value=[])
    def test_connect_auto_without_device_raises(self, _mock):
        psu = KoradKA3005P(port="auto")
        with self.assertRaises(RuntimeError):
            psu.connect()


if __name__ == "__main__":
    unittest.main()
