from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project folder. .env is looked for here, not in the working directory: an
# MCP client that starts the server over stdio does not say where it runs it.
ROOT = Path(__file__).resolve().parent.parent

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class Settings(BaseSettings):
    """Settings from environment variables or the project's .env file."""

    # The ArchiMate API: its root URL (without /api/v2) and the key the server uses.
    # A key with the role "reader" is enough for every reading tool; writing needs
    # ALLOW_WRITE and a key with the role "editor".
    api_url: str = "http://127.0.0.1:8000"
    api_key: str = ""
    # Seconds one request to the API may take.
    api_timeout: float = Field(60, gt=0)

    # The model a tool reads when it is not told which: an id or a name. Empty:
    # the only model there is; with several, the tool asks.
    default_model: str = ""
    # Most items in one list of an answer (search results, a view's elements,
    # an element's relationships...). Tools take a smaller `limit`, never a larger one.
    max_results: int = Field(100, ge=1, le=1000)
    # The ArchiMate Browser, e.g. http://127.0.0.1:8090/. When set, answers carry
    # links that open what they describe there as a diagram. Empty: no links.
    browser_url: str = ""

    # MCP-35 (1.12.0): images of diagrams (diagram_image), drawn by the ArchiMate Browser in Chrome or Edge
    # without a window. The Browser's folder (empty: ArchiMateBrowser next to this server's folder); the server
    # starts a Browser server of its own from it, on a free port.
    browser_dir: str = ""
    # Where images are saved: a folder (relative to the server's folder); a tool's `file` stays inside it.
    image_dir: str = "images"
    # The browser to draw in: auto (Chrome, else Edge), chrome, msedge, or the path of a Chromium-based browser.
    render_browser: str = "auto"
    # Seconds one diagram may take to draw; seconds without an image after which the browser stops (0: never).
    render_timeout: float = Field(120, gt=0)
    render_idle: float = Field(300, ge=0)

    # The HTTP transport (`python -m app http`, `archimatemcp.bat start`).
    # 127.0.0.1 rather than localhost, as in the API: on Windows localhost
    # resolves to ::1 first. A loopback HOST listens on 127.0.0.1 and ::1.
    host: str = "127.0.0.1"
    port: int = Field(8100, ge=0, le=65535)
    # Clients of the HTTP transport send it as "Authorization: Bearer <token>",
    # and all of them work with the server's API_KEY.
    mcp_token: str = ""
    # MU-2 (1.7.0): instead, every HTTP client sends its own key of the ArchiMate
    # API as "Authorization: Bearer <key>"; the server works with that key for
    # that client, so the API sees the person. Then API_KEY may stay empty.
    # One of the two is required unless HOST is a loopback address.
    client_keys: bool = False

    # MCP-15 (D11): the write tools are offered only with ALLOW_WRITE=true and a
    # key with the role "editor" or "admin".
    allow_write: bool = False
    # D20: every write is recorded, one JSON line each, in this file (relative to
    # the server's folder); empty (the default since 1.7.0): in the server's log
    # only. The ArchiMate API keeps the record that counts (3.11.0, model_history).
    change_log: str = ""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    @property
    def api_base(self) -> str:
        return self.api_url.rstrip("/") + "/api/v2"

    @property
    def image_path(self) -> Path:
        path = Path(self.image_dir.strip() or "images")
        return (path if path.is_absolute() else ROOT / path).resolve()

    @property
    def change_log_path(self) -> Path | None:
        if not self.change_log.strip():
            return None
        path = Path(self.change_log.strip())
        return path if path.is_absolute() else ROOT / path


def load_settings() -> Settings:
    return Settings()
