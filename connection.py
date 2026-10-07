"""Windows hotspot control and hotspot-only phone connection instructions."""

import io
import json
import os
import secrets
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "qr_lib"))
import segno


ROOT = Path(__file__).resolve().parent
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def wifi_payload(ssid, password):
    """ZXing Wi-Fi QR format; escape its separators inside credentials."""
    def escape(value):
        return "".join("\\" + char if char in "\\;,:\"" else char for char in value)

    return f"WIFI:T:WPA;S:{escape(ssid)};P:{escape(password)};;"


def qr_svg(value):
    output = io.BytesIO()
    segno.make(value, error="m").save(output, kind="svg", scale=6, border=4)
    return output.getvalue()


class ConnectionManager:
    def __init__(self, code, port, lan_ip):
        self.code = code
        self.port = port
        self.lock = threading.Lock()
        self.hotspot = {"active": False}
        self.password = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(24))
        self.listening_ip = None
        self.previous_config = None
        self.ssid = None
        self.owns_hotspot = False
        self.used_hotspot = False
        self.stop_event = threading.Event()
        if os.name == "nt":
            self.hotspot = self._run_helper("start", {"password": self.password})
            self.previous_config = self.hotspot.pop("previous_config", None)
            self.ssid = self.hotspot.get("ssid")
            self.owns_hotspot = bool(self.hotspot.get("started_by_app"))
            self.used_hotspot = self.owns_hotspot
            if self.hotspot.get("active"):
                threading.Thread(target=self._monitor, daemon=True).start()

    @staticmethod
    def _run_helper(action, payload=None):
        try:
            process = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(ROOT / "hotspot.ps1"), action],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                input=json.dumps(payload) if payload is not None else None,
                timeout=55 if action == "start" else 25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return json.loads(process.stdout) if process.returncode == 0 else {"active": False, "error": process.stderr.strip()}
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return {"active": False}

    def _monitor(self):
        while not self.stop_event.wait(3):
            status = self._run_helper("status")
            with self.lock:
                if status.get("active") and (status.get("password") != self.password or status.get("ssid") != self.ssid):
                    status = {"active": False, "error": "Hotspot configuration changed outside Local Connect."}
                self.hotspot = status

    def close(self, stop_active_hotspot=False):
        self.stop_event.set()
        if self.owns_hotspot or (stop_active_hotspot and self.used_hotspot):
            self._run_helper("stop", {"previous_config": self.previous_config, "expected_password": self.password})

    def set_listening_ip(self, ip):
        with self.lock:
            self.listening_ip = ip

    def snapshot(self):
        with self.lock:
            hotspot = self.hotspot.copy()
            listening_ip = self.listening_ip
        active = bool(hotspot.get("active") and hotspot.get("ip") and hotspot.get("ssid")
                      and hotspot.get("password") == self.password and hotspot.get("ip") == listening_ip)
        if active:
            connected = int(hotspot.get("clients") or 0) > 0
            return {
                "mode": "web" if connected else "wifi",
                "ssid": hotspot["ssid"],
                "password": hotspot["password"],
                "wifi_qr": wifi_payload(hotspot["ssid"], hotspot["password"]),
                "web_qr": f"http://{hotspot['ip']}:{self.port}/#code={self.code}",
                "web_url": f"http://{hotspot['ip']}:{self.port}/",
                "clients": int(hotspot.get("clients") or 0),
                "code": self.code,
            }
        return {
            "mode": "manual",
            "web_url": None,
            "code": self.code,
            "reason": ("hotspot_address_missing" if hotspot.get("active") and not hotspot.get("ip") else
                       "hotspot_listener_pending" if hotspot.get("active") and hotspot.get("ip") != listening_ip else
                       hotspot.get("error")),
        }
