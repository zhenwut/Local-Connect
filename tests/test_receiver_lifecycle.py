import unittest
from unittest.mock import Mock, patch

from connection import ConnectionManager
from receiver_lifecycle import ReceiverLifecycle


class ReceiverLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.reset = Mock()
        self.shutdown = Mock()
        self.lifecycle = ReceiverLifecycle(self.reset, self.shutdown, clock=lambda: self.now)

    def test_does_not_stop_before_first_page_opens(self):
        self.now = 1000
        self.assertFalse(self.lifecycle.check())
        self.shutdown.assert_not_called()

    def test_open_resets_once_reconnect_does_not(self):
        self.lifecycle.open("first")
        self.lifecycle.open("first")
        stream = self.lifecycle.connect("first")
        self.lifecycle.disconnect("first", stream)
        self.now = 4
        self.lifecycle.open("first")
        self.lifecycle.connect("first")
        self.reset.assert_called_once()
        self.now = 1000  # Long-lived background tabs need no JavaScript heartbeat.
        self.assertFalse(self.lifecycle.check())

    def test_reload_resets_records_but_cancels_shutdown(self):
        self.lifecycle.open("old-page")
        self.lifecycle.close("old-page")
        self.now = 5
        self.lifecycle.open("reloaded-page")
        self.lifecycle.connect("reloaded-page")
        self.now = 50
        self.assertFalse(self.lifecycle.check())
        self.assertEqual(self.reset.call_count, 2)

    def test_only_last_tab_closure_stops_service_after_grace(self):
        for tab in ("first", "second"):
            self.lifecycle.open(tab)
            self.lifecycle.connect(tab)
        self.lifecycle.close("first")
        self.now = 100
        self.assertFalse(self.lifecycle.check())
        self.lifecycle.close("second")
        self.now = 107
        self.assertFalse(self.lifecycle.check())
        self.now = 108
        self.assertTrue(self.lifecycle.check())
        self.assertFalse(self.lifecycle.open("too-late"))
        self.assertFalse(self.lifecycle.check())
        self.shutdown.assert_called_once()

    def test_socket_disconnect_stops_even_when_close_beacon_is_missing(self):
        self.lifecycle.open("crashed")
        stream = self.lifecycle.connect("crashed")
        self.lifecycle.disconnect("crashed", stream)
        self.now = 9
        self.assertTrue(self.lifecycle.check())

    def test_late_disconnect_of_old_stream_does_not_close_new_stream(self):
        self.lifecycle.open("page")
        old = self.lifecycle.connect("page")
        new = self.lifecycle.connect("page")
        self.lifecycle.disconnect("page", old)
        self.now = 99
        self.assertFalse(self.lifecycle.check())
        self.assertTrue(self.lifecycle.is_connected("page", new))

    @patch("connection.os.name", "posix")
    def test_page_exit_stops_used_hotspot_even_if_it_was_already_on(self):
        connection = ConnectionManager("ABCD2345", 8766, None)
        connection.used_hotspot = True
        with patch.object(connection, "_run_helper") as helper:
            connection.close(stop_active_hotspot=True)
            helper.assert_called_once_with("stop")
