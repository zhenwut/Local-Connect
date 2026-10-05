"""Track actual receiver connections, without relying on background-tab timers."""

import secrets
import threading
import time


class ReceiverLifecycle:
    def __init__(self, reset, shutdown, grace=8, connect_timeout=20, clock=time.monotonic):
        self.reset = reset
        self.shutdown = shutdown
        self.grace = grace
        self.connect_timeout = connect_timeout
        self.clock = clock
        self.instance_id = secrets.token_hex(16)
        self.lock = threading.Lock()
        self.pages = {}
        self.opened = False
        self.empty_since = None
        self.closing = False
        self.stopped = threading.Event()

    def start(self):
        threading.Thread(target=self._monitor, daemon=True, name="receiver-lifecycle").start()

    def open(self, page_id):
        with self.lock:
            if self.closing:
                return False
            if page_id not in self.pages:
                self.reset()
                self.pages[page_id] = {"streams": set(), "deadline": self.clock() + self.connect_timeout}
            self.opened = True
            self.empty_since = None
            return True

    def connect(self, page_id):
        with self.lock:
            if self.closing or page_id not in self.pages:
                return None
            stream_id = secrets.token_hex(8)
            self.pages[page_id]["streams"].add(stream_id)
            self.empty_since = None
            return stream_id

    def is_connected(self, page_id, stream_id):
        with self.lock:
            return page_id in self.pages and stream_id in self.pages[page_id]["streams"]

    def disconnect(self, page_id, stream_id):
        with self.lock:
            page = self.pages.get(page_id)
            if page and stream_id in page["streams"]:
                page["streams"].remove(stream_id)
                # EventSource can reconnect before this short grace expires.
                page["deadline"] = self.clock() + self.grace

    def close(self, page_id):
        with self.lock:
            self.pages.pop(page_id, None)
            if not self.pages and self.opened and self.empty_since is None:
                self.empty_since = self.clock()

    def check(self):
        with self.lock:
            now = self.clock()
            expired = [key for key, page in self.pages.items() if not page["streams"] and page["deadline"] <= now]
            deadlines = [self.pages[key]["deadline"] for key in expired]
            for key in expired:
                del self.pages[key]
            if self.pages or not self.opened or self.closing:
                return False
            if self.empty_since is None:
                # Disconnects have already waited for reconnection.
                self.empty_since = min(deadlines) - self.grace if deadlines else now
            if now - self.empty_since < self.grace:
                return False
            self.closing = True
        self.shutdown()
        return True

    def _monitor(self):
        while not self.stopped.wait(0.5):
            if self.check():
                return
