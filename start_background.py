"""Start the local transfer server independently of the current terminal."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / ".server.log"
ERRORS = ROOT / ".server-error.log"
LOCAL_URL = "http://127.0.0.1:8766/api/latest"


def is_running():
    try:
        with urlopen(LOCAL_URL, timeout=1) as response:
            data = json.load(response)
        return isinstance(data, dict) and "photos" in data and "version" in data
    except (URLError, TimeoutError, ValueError, OSError):
        return False


def show_access():
    print("电脑接收页 / Receiver: http://localhost:8766/receiver")
    try:
        with urlopen("http://127.0.0.1:8766/api/connect", timeout=2) as response:
            connection = json.load(response)
        if connection["mode"] == "manual":
            print("热点入口尚未就绪，请查看电脑接收页。 / Hotspot endpoint is not ready; check the receiver page.")
            print(f"本次访问码 / Session access code: {connection['code']}")
        else:
            print("请在电脑接收页依次扫描两个二维码。 / Scan both QR codes on the receiver page.")
    except (URLError, TimeoutError, ValueError, OSError, KeyError):
        print("请打开电脑接收页查看连接状态。 / Open the receiver page to check the connection.")


def main():
    if is_running():
        show_access()
        return
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NO_WINDOW |
            subprocess.DETACHED_PROCESS |
            subprocess.CREATE_NEW_PROCESS_GROUP
        )
    with OUTPUT.open("w", encoding="utf-8") as output, ERRORS.open("w", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=errors,
            env=environment,
            creationflags=flags,
            start_new_session=os.name != "nt",
            close_fds=True,
        )
    for _ in range(400):
        if is_running():
            print(f"后台服务已启动，进程 ID：{process.pid} / Background service started, PID: {process.pid}")
            show_access()
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)
    detail = ERRORS.read_text(encoding="utf-8", errors="replace").strip() if ERRORS.is_file() else ""
    raise SystemExit(f"服务启动失败 / Service failed to start: {detail or '请检查 8766 端口是否被占用 / Check whether port 8766 is in use'}")


if __name__ == "__main__":
    main()
