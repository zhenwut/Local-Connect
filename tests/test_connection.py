import threading
import unittest
from unittest.mock import patch

from connection import ConnectionManager, PASSWORD_ALPHABET, qr_svg, wifi_payload


class ConnectionTests(unittest.TestCase):
    def make_manager(self, hotspot):
        manager = object.__new__(ConnectionManager)
        manager.code = "ABCD2345"
        manager.port = 8000
        manager.lan_ip = "192.168.1.7"
        manager.lock = threading.Lock()
        manager.hotspot = hotspot
        manager.password = hotspot.get("password")
        manager.listening_ip = hotspot.get("ip")
        return manager

    def test_two_qr_phases_and_no_lan_fallback(self):
        manager = self.make_manager({
            "active": True, "ip": "192.168.137.1", "ssid": "A;B:WiFi",
            "password": 'pw,"\\x', "clients": 0,
        })
        first = manager.snapshot()
        self.assertEqual(first["mode"], "wifi")
        self.assertEqual(first["wifi_qr"], wifi_payload("A;B:WiFi", 'pw,"\\x'))
        self.assertIn(r"S:A\;B\:WiFi", first["wifi_qr"])
        self.assertTrue(qr_svg(first["wifi_qr"]).startswith(b"<?xml"))
        manager.hotspot["clients"] = 1
        second = manager.snapshot()
        self.assertEqual(second["mode"], "web")
        self.assertEqual(second["web_qr"], "http://192.168.137.1:8000/#code=ABCD2345")
        manager.hotspot["active"] = False
        fallback = manager.snapshot()
        self.assertEqual(fallback["mode"], "manual")
        self.assertIsNone(fallback["web_url"])

    @patch("connection.os.name", "posix")
    def test_non_windows_skips_hotspot(self):
        manager = ConnectionManager("ABCD2345", 8000, "192.168.1.7")
        self.assertEqual(manager.snapshot()["mode"], "manual")
        manager.close()

    def test_hotspot_waits_for_address_without_reporting_start_failure(self):
        manager = self.make_manager({
            "active": True, "ip": None, "ssid": "Local Connect",
            "password": "testpass123", "clients": 0,
        })
        waiting = manager.snapshot()
        self.assertEqual(waiting["reason"], "hotspot_address_missing")
        self.assertNotIn("wifi_qr", waiting)
        manager.hotspot["ip"] = "192.168.137.1"
        manager.set_listening_ip("192.168.137.1")
        ready = manager.snapshot()
        self.assertEqual(ready["mode"], "wifi")
        self.assertIn("wifi_qr", ready)

    def test_unbound_or_changed_hotspot_never_shows_phone_url(self):
        manager = self.make_manager({"active": True, "ip": "192.168.137.1", "ssid": "Local Connect",
                                     "password": "randompassword123456789012", "clients": 1})
        manager.set_listening_ip(None)
        self.assertIsNone(manager.snapshot()["web_url"])
        self.assertEqual(manager.snapshot()["reason"], "hotspot_listener_pending")
        manager.set_listening_ip("192.168.137.1")
        manager.hotspot["password"] = "changed outside app"
        self.assertEqual(manager.snapshot()["mode"], "manual")

    @patch.object(ConnectionManager, "_run_helper")
    def test_each_start_uses_new_strong_password(self, helper):
        helper.return_value = {"active": False}
        first = ConnectionManager("ABCD2345", 8000, None)
        first_password = helper.call_args.args[1]["password"]
        second = ConnectionManager("ABCD2345", 8000, None)
        second_password = helper.call_args.args[1]["password"]
        self.assertEqual(len(first_password), 24)
        self.assertTrue(set(first_password) <= set(PASSWORD_ALPHABET))
        self.assertNotEqual(first_password, second_password)
        first.close()
        second.close()
