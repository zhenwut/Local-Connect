"""Install the project's Python dependencies, then open Local Connect."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEPENDENCIES = ROOT / ".deps"
REQUIREMENTS = ROOT / "requirements.txt"
CHECK_CODE = """
import importlib
import importlib.metadata
import json
import sys

sys.path.insert(0, sys.argv[1])
required = json.loads(sys.argv[2])
for package, expected in required.items():
    if importlib.metadata.version(package) != expected:
        sys.exit(1)
    importlib.import_module({"Pillow": "PIL"}.get(package, package.replace("-", "_")))
"""


def required_versions():
    versions = {}
    for raw_line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            raise SystemExit(f"无法自动检查依赖 / Unsupported requirement: {line}")
        package, version = (part.strip() for part in line.split("==", 1))
        versions[package] = version
    return versions


def dependencies_ready(versions):
    result = subprocess.run(
        [sys.executable, "-c", CHECK_CODE, str(DEPENDENCIES), json.dumps(versions)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def ensure_dependencies():
    versions = required_versions()
    if dependencies_ready(versions):
        return
    print("正在安装项目依赖 / Installing project dependencies...", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
         "--upgrade", "--target", str(DEPENDENCIES), "-r", str(REQUIREMENTS)],
        cwd=ROOT,
        check=False,
    )
    if result.returncode or not dependencies_ready(versions):
        raise SystemExit("依赖安装失败，请检查网络与 pip。 / Dependency setup failed; check network and pip.")


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("需要 Python 3.10 或更新版本。 / Python 3.10 or newer is required.")
    ensure_dependencies()
    sys.argv = [str(ROOT / "server.py"), "--open-browser", *sys.argv[1:]]
    from server import main as server_main
    server_main()


if __name__ == "__main__":
    main()
