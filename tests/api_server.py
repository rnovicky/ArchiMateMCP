"""
The ArchiMate API the tests run against: the real one, from the folder next to
this project (../ArchiMateAPI, or ARCHIMATE_API_DIR), on a throwaway SQLite
database, with the API's synthetic and basic test models imported.

It runs with ARCHIMATE_API_PYTHON, else the API's own .venv, else the Python
this project's .venv was made from (which then needs the API's packages).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
# Earlier names of the API's folder, so that an older checkout is found too.
API_DIR_NAMES = ("ArchiMateAPI", "ArchimateXMIAPI", "ArchiXMIAPI")
SYNTHETIC_MODEL = Path("tests") / "fixtures" / "Synthetic_Model.xml"
BASIC_MODEL = Path("tests") / "fixtures" / "Basic_Model.xml"

ADMIN_KEY = "mcp-tests-admin-key"
READER_KEY = "mcp-tests-reader-key"
EDITOR_KEY = "mcp-tests-editor-key"


class ApiNotAvailable(RuntimeError):
    """The API cannot be started: the message says what is missing."""


def find_api_dir() -> Path | None:
    if os.environ.get("ARCHIMATE_API_DIR"):
        return Path(os.environ["ARCHIMATE_API_DIR"])
    for name in API_DIR_NAMES:
        candidate = PROJECT.parent / name
        if (candidate / "app" / "main.py").is_file():
            return candidate
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _api_python(api_dir: Path) -> str:
    if os.environ.get("ARCHIMATE_API_PYTHON"):
        return os.environ["ARCHIMATE_API_PYTHON"]
    for candidate in (api_dir / ".venv" / "Scripts" / "python.exe", api_dir / ".venv" / "bin" / "python"):
        if candidate.is_file():
            return str(candidate)
    # Not this project's .venv: it has none of the API's packages.
    return getattr(sys, "_base_executable", sys.executable)


class TestApi:
    """A real API on a temporary database, holding the synthetic and the basic test model."""

    __test__ = False  # not a test class, for pytest

    def __init__(self, require_if_match: bool | None = None):
        # REQUIRE_IF_MATCH of the test API (1.12.0): as given, else ARCHIMATE_TEST_REQUIRE_IF_MATCH, else true.
        # On, the API refuses a change that says no version, so the suite shows that every write tool sends
        # one; ARCHIMATE_TEST_REQUIRE_IF_MATCH=false runs it against an API that does not ask
        if require_if_match is None:
            require_if_match = os.environ.get("ARCHIMATE_TEST_REQUIRE_IF_MATCH", "true").lower() not in ("0", "false", "no")
        self.require_if_match = require_if_match
        self.api_dir = find_api_dir()
        if not self.api_dir:
            raise ApiNotAvailable("The tests run against the real ArchiMate API and did not find its folder. "
                                  "Put it next to this one as ArchiMateAPI, or set ARCHIMATE_API_DIR.")
        self.tmp = Path(tempfile.mkdtemp(prefix="archimate-mcp-api-"))
        self.log_path = self.tmp / "api.log"
        self.proc: subprocess.Popen | None = None
        self.url = ""
        self.models: dict[str, int] = {}

    def start(self) -> "TestApi":
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}"
        keys = self.tmp / "keys.json"
        keys.write_text(json.dumps([
            {"name": "mcp-tests-reader", "role": "reader", "sha256": hashlib.sha256(READER_KEY.encode()).hexdigest()},
            {"name": "mcp-tests-editor", "role": "editor", "sha256": hashlib.sha256(EDITOR_KEY.encode()).hexdigest()},
        ]), encoding="utf-8")
        env = {
            **os.environ,
            "DB_URL": f"sqlite:///{(self.tmp / 'test.db').as_posix()}",
            "API_KEY": ADMIN_KEY, "API_KEYS_FILE": str(keys),
            "HOST": "127.0.0.1", "PORT": str(port),
            "XSD_DIR": str(self.api_dir / "xsd"),
            "CORS_ORIGINS": "", "LINKED_FILES_DIRS": str(self.tmp / "linked"), "LINK_SCHEDULER": "false",
            # the API's own .env (read from its folder) must not change how it answers
            "REQUIRE_IF_MATCH": "true" if self.require_if_match else "false",
        }
        (self.tmp / "linked").mkdir()  # 1.10.0: a model linked to a file there (test_write)
        python = _api_python(self.api_dir)
        try:
            migrate = subprocess.run([python, "-m", "alembic", "upgrade", "head"], cwd=self.api_dir, env=env,
                                     capture_output=True, text=True, errors="replace")
        except OSError as e:
            raise ApiNotAvailable(f"Cannot run {python}: {e}") from e
        if migrate.returncode:
            raise ApiNotAvailable(f"Creating the API's test database failed ({python} -m alembic upgrade head in "
                                  f"{self.api_dir}). Are the API's packages installed?\n{migrate.stderr[-1500:]}")
        with open(self.log_path, "w", encoding="utf-8") as log:
            self.proc = subprocess.Popen([python, "-m", "app"], cwd=self.api_dir, env=env,
                                         stdout=log, stderr=subprocess.STDOUT)
        for _ in range(120):
            if self.proc.poll() is not None:
                raise ApiNotAvailable(f"The API stopped while starting:\n{self.log_tail()}")
            try:
                with urllib.request.urlopen(self.url + "/health", timeout=2):
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.25)
        else:
            raise ApiNotAvailable(f"The API did not answer /health within 30 s:\n{self.log_tail()}")
        self.models["synthetic"] = self.import_model("synthetic.xml", (self.api_dir / SYNTHETIC_MODEL).read_bytes())
        # A second model, so that the tools must be told which one
        self.models["basic"] = self.import_model("basic.xml", (self.api_dir / BASIC_MODEL).read_bytes())
        return self

    def log_tail(self, lines: int = 25) -> str:
        try:
            return "\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
        except OSError:
            return ""

    def call(self, method: str, path: str, *, data: bytes | None = None, content_type: str | None = None):
        request = urllib.request.Request(self.url + path, data=data, method=method, headers={"X-API-Key": ADMIN_KEY})
        if method in ("PUT", "DELETE"):
            # the tests' own writes stand for someone else, who does not check what they change
            request.add_header("If-Match", "*")
        if content_type:
            request.add_header("Content-Type", content_type)
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
        return json.loads(body) if body else None

    def import_model(self, name: str, xml: bytes) -> int:
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f"Content-Type: application/xml\r\n\r\n").encode() + xml + f"\r\n--{boundary}--\r\n".encode()
        try:
            result = self.call("POST", "/api/v2/models/import?asNew=true", data=body,
                               content_type=f"multipart/form-data; boundary={boundary}")
        except urllib.error.HTTPError as e:
            raise ApiNotAvailable(f"The API refused {name}: {e.code} {e.read().decode(errors='replace')[:1500]}") from e
        return result["model"]["id"]

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)
