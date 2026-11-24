"""
Images of diagrams (MCP-35, 1.12.0): the ArchiMate Browser draws them, this module drives it.

The first image starts, for this server alone:

* the Browser's own server (``server/serve.py`` of the Browser's folder, BROWSER_DIR) on a free port of
  127.0.0.1, passing requests on to API_URL. It gets no key: every request of the page carries the key in its
  ``X-API-Key`` header (Playwright adds it), so the key is in no URL, command line or file. It ends with this
  server (``--exit-with-stdin``), however this one ends.
* Chrome or Edge without a window (Playwright, with the browser that is installed; RENDER_BROWSER), with a
  profile of its own that is thrown away, opening the Browser in render mode (``/?render``, the Browser's
  ``js/app/render.js``).

Both stay for RENDER_IDLE seconds after the last image (a report with many diagrams starts them once), then
stop. Playwright runs in one thread of its own (its sync API), apart from the server's event loop.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app.config import ROOT, Settings

logger = logging.getLogger("app.render")

# What the browsers are called in Playwright (channels), in the order tried when RENDER_BROWSER is "auto"
CHANNELS = ("chrome", "msedge")
# The Browser version that has the render mode
MIN_BROWSER_VERSION = (2, 29, 0)
# Seconds the Browser's server may take to start, and a page to load
START_TIMEOUT = 30
# The largest PNG side and area the Browser's canvas allows (js/viewsvg.js); a preview is smaller
PREVIEW_MAX = 1200


# Draw a link's diagram in the render page, within a time limit (ms)
DRAW = """([link, opts, ms]) => Promise.race([
  window.archiRender.draw(link, opts),
  new Promise((_, fail) => setTimeout(() => fail(new Error(`Drawing took longer than ${ms / 1000} s (RENDER_TIMEOUT).`)), ms)),
])"""


class RenderError(Exception):
    """An image could not be made; the message says why, for the assistant."""


@dataclass
class Image:
    title: str
    width: int  # the diagram's size in its own units (px at scale 1)
    height: int
    info: str = ""
    svg: str | None = None
    png: bytes | None = None
    png_size: tuple[int, int] | None = None
    png_scale: float | None = None
    preview: bytes | None = None
    notes: list[str] = field(default_factory=list)


def browser_dir(settings: Settings) -> Path | None:
    """The ArchiMate Browser's folder: BROWSER_DIR, else ArchiMateBrowser next to this server's folder."""
    if settings.browser_dir.strip():
        path = Path(settings.browser_dir.strip())
        return path if path.is_absolute() else (ROOT / path).resolve()
    candidate = ROOT.parent / "ArchiMateBrowser"
    return candidate if candidate.is_dir() else None


def browser_version(folder: Path) -> tuple[int, ...] | None:
    """The version of the Browser in `folder` (js/version.js), or None."""
    try:
        text = (folder / "js" / "version.js").read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"APP_VERSION\s*=\s*'(\d+)\.(\d+)\.(\d+)'", text)
    return tuple(int(x) for x in found.groups()) if found else None


class Renderer:
    """Makes images of diagrams; one at a time, in its own thread."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="archimate-render")
        self._lock = asyncio.Lock()
        # used only in the render thread
        self._proc: subprocess.Popen | None = None
        self._base = ""
        self._pw = None
        self._browser = None
        self._channel = ""
        self._pages: dict[str, object] = {}  # one page (and browser context) per API key, by its hash
        self._last_use = 0.0
        self._idle_timer: threading.Timer | None = None

    # ---------------------------------------------------------------- the server's side

    async def render(self, link: str, api_key: str, *, formats: tuple[str, ...], direction: str,
                     png_scale: float, preview: bool) -> Image:
        """Draw the diagram of a Browser link and return it in `formats` ("svg", "png")."""
        async with self._lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._executor, self._render, link, api_key, formats, direction, png_scale, preview)

    async def aclose(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._stop)
        self._executor.shutdown(wait=False)

    def close(self) -> None:
        """Stop everything (at exit; from any thread)."""
        try:
            self._executor.submit(self._stop).result(timeout=20)
        except Exception:  # noqa: BLE001 - at exit, whatever is left goes with the process
            pass
        self._executor.shutdown(wait=False)

    # ---------------------------------------------------------------- the render thread

    def _render(self, link: str, api_key: str, formats, direction: str, png_scale: float, preview: bool) -> Image:
        if self._idle_timer:
            self._idle_timer.cancel()
        try:
            page = self._page(api_key)
            try:
                # Playwright's evaluate() waits as long as the page takes: the time limit is the page's
                drawn = page.evaluate(DRAW, [link, {"direction": direction}, self.settings.render_timeout * 1000])
            except Exception as e:  # noqa: BLE001 - Playwright's errors carry the page's message
                message = _page_error(e)
                if "RENDER_TIMEOUT" in message:
                    self._drop_page(api_key)  # it may still be drawing: the next image gets a fresh page
                raise RenderError(message) from None
            image = Image(title=drawn.get("title") or "", width=int(drawn["width"]), height=int(drawn["height"]),
                          info=drawn.get("info") or "")
            if "svg" in formats:
                image.svg = page.evaluate("() => window.archiRender.svg()")
            if "png" in formats:
                out = page.evaluate("s => window.archiRender.png(s)", png_scale)
                image.png = base64.b64decode(out["base64"])
                image.png_size = (out["width"], out["height"])
                image.png_scale = out["scale"]
                if out["scale"] < png_scale - 1e-6:
                    image.notes.append(f"The diagram is large: the PNG was made at scale {out['scale']:.2f} instead "
                                       f"of {png_scale:g} (the browser's limit for an image). The SVG has no limit.")
            if preview:
                scale = min(1.0, PREVIEW_MAX / max(image.width, image.height, 1))
                out = page.evaluate("s => window.archiRender.png(s)", scale)
                image.preview = base64.b64decode(out["base64"])
            return image
        except RenderError:
            raise
        except Exception as e:  # noqa: BLE001
            # something broke underneath (the browser closed, the Browser's server stopped): start afresh next time
            logger.warning("Rendering failed, starting afresh next time: %s", e)
            self._stop()
            raise RenderError(f"The image could not be made: {_page_error(e)}") from None
        finally:
            self._last_use = time.monotonic()
            self._arm_idle_timer()

    def _arm_idle_timer(self) -> None:
        idle = self.settings.render_idle
        if idle <= 0:
            return
        self._idle_timer = threading.Timer(idle, lambda: self._executor.submit(self._stop_if_idle))
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _stop_if_idle(self) -> None:
        if self._base and time.monotonic() - self._last_use >= self.settings.render_idle - 0.5:
            logger.info("No image for %s s: stopping the Browser used for images.", self.settings.render_idle)
            self._stop()

    def _page(self, api_key: str):
        """The render page for this key: the Browser's server, the browser and the page started as needed."""
        if self._proc is not None and self._proc.poll() is not None:
            self._stop()  # the Browser's server has stopped meanwhile
        if self._proc is None:
            self._start_server()
        if self._browser is None or not self._browser.is_connected():
            self._start_browser()
        key = hashlib.sha256(api_key.encode()).hexdigest()
        page = self._pages.get(key)
        if page is not None and not page.is_closed():
            return page
        context = self._browser.new_context(
            extra_http_headers={"X-API-Key": api_key} if api_key else {},
            color_scheme="light", locale="en-US", viewport={"width": 1600, "height": 1000},
            service_workers="block", accept_downloads=False)
        page = context.new_page()
        page.set_default_timeout(self.settings.render_timeout * 1000)
        page.on("dialog", lambda dialog: dialog.dismiss())  # nothing may wait for an answer
        try:
            page.goto(self._base + "?render", wait_until="load", timeout=START_TIMEOUT * 1000)
            page.wait_for_function("document.documentElement.dataset.render === 'ready'", timeout=START_TIMEOUT * 1000)
        except Exception as e:  # noqa: BLE001
            context.close()
            raise RenderError(f"The ArchiMate Browser at {self._base} did not start its render mode: {_page_error(e)}"
                              " (it needs version 2.29.0 or later).") from None
        self._pages[key] = page
        return page

    def _drop_page(self, api_key: str) -> None:
        page = self._pages.pop(hashlib.sha256(api_key.encode()).hexdigest(), None)
        if page is not None:
            try:
                page.context.close()
            except Exception:  # noqa: BLE001
                pass

    def _start_server(self) -> None:
        folder = browser_dir(self.settings)
        if folder is None or not (folder / "server" / "serve.py").is_file():
            raise RenderError("The ArchiMate Browser was not found: set BROWSER_DIR in the MCP server's .env to "
                              "its folder (the one with server\\serve.py)." if folder is None else
                              f"No ArchiMate Browser in {folder} (server\\serve.py is missing): check BROWSER_DIR.")
        version = browser_version(folder)
        if version is not None and version < MIN_BROWSER_VERSION:
            raise RenderError(f"The ArchiMate Browser in {folder} is version {'.'.join(map(str, version))}; images "
                              f"need {'.'.join(map(str, MIN_BROWSER_VERSION))} or later.")
        # no key of the Browser's .env or environment: the page sends the key itself
        env = {k: v for k, v in os.environ.items() if not k.startswith("ARCHIXMI_")}
        command = [sys.executable, "-u", str(folder / "server" / "serve.py"), "--port", "0", "--bind", "127.0.0.1",
                   "--api", self.settings.api_url.rstrip("/"), "--exit-with-stdin"]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen(command, cwd=folder, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                    creationflags=flags)
        except OSError as e:
            raise RenderError(f"The ArchiMate Browser's server could not be started: {e}") from None
        first = _read_line(proc, START_TIMEOUT)
        found = re.search(r"(http://127\.0\.0\.1:\d+/)", first or "")
        if not found:
            proc.kill()
            raise RenderError(f"The ArchiMate Browser's server did not start (it said: {first or 'nothing'!r}).")
        self._proc, self._base = proc, found.group(1)
        # its further output is not needed; read it so that the pipe never fills
        threading.Thread(target=_drain, args=(proc,), daemon=True).start()
        logger.info("ArchiMate Browser for images at %s (%s)", self._base, folder)

    def _start_browser(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RenderError("Images need the Python package playwright: run archimatemcp.bat install again "
                              "(or pip install -r requirements.txt in the server's .venv).") from None
        if self._pw is None:
            self._pw = sync_playwright().start()
        wanted = self.settings.render_browser.strip()
        channels = CHANNELS if wanted in ("", "auto") else (wanted,)
        errors = []
        for channel in channels:
            try:
                if Path(channel).suffix.lower() == ".exe" or os.sep in channel or "/" in channel:
                    self._browser = self._pw.chromium.launch(executable_path=channel)
                else:
                    self._browser = self._pw.chromium.launch(channel=channel)
                self._channel = channel
                logger.info("Images drawn in %s %s (no window)", channel, self._browser.version)
                return
            except Exception as e:  # noqa: BLE001
                errors.append(f"{channel}: {str(e).splitlines()[0]}")
        raise RenderError("No browser to draw in: install Google Chrome or Microsoft Edge, or set RENDER_BROWSER "
                          "(" + "; ".join(errors) + ").")

    def _stop(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
            self._idle_timer = None
        for page in self._pages.values():
            try:
                page.context.close()
            except Exception:  # noqa: BLE001
                pass
        self._pages.clear()
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None
        if self._proc is not None:
            try:
                self._proc.stdin.close()  # --exit-with-stdin: it ends by itself
                self._proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._proc.kill()
            self._proc = None
        self._base = ""


def _read_line(proc: subprocess.Popen, timeout: float) -> str | None:
    """The first line `proc` prints, or None when it prints none within `timeout` seconds."""
    out: list[str] = []
    reader = threading.Thread(target=lambda: out.append(proc.stdout.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    return out[0].strip() if out else None


def _drain(proc: subprocess.Popen) -> None:
    try:
        for _ in proc.stdout:
            pass
    except (OSError, ValueError):
        pass


def _page_error(e: Exception) -> str:
    """The reason in a Playwright error: the page's own message without Playwright's frame."""
    text = str(e).strip()
    found = re.search(r"Error: (.+?)(?:\n|$)", text)
    message = found.group(1) if found else text.splitlines()[0] if text else type(e).__name__
    return message.removeprefix("Error: ").strip()
