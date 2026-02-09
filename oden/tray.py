"""
Native system tray icon for Oden.

Provides Start/Stop control, Open Web GUI, and version display
via a cross-platform system tray icon using pystray.

On macOS the NSApplication event loop must run on the main thread,
so ``icon.run(setup=...)`` is used: it blocks the main thread while
the watcher logic runs in the *setup* callback thread.

On Linux / Windows ``run_detached()`` works fine, but for consistency
all platforms use the same ``run()`` approach.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports – set by _ensure_imports()
pystray: Any = None
PILImage: Any = None


def _ensure_imports() -> bool:
    """Lazily import pystray and PIL. Returns True if available."""
    global pystray, PILImage  # noqa: PLW0603
    if pystray is not None:
        return True
    try:
        import pystray as _pystray
        from PIL import Image as _Image

        pystray = _pystray
        PILImage = _Image
        return True
    except ImportError:
        logger.warning("pystray or Pillow not installed — tray icon disabled")
        return False


def _load_icon() -> Any:
    """Load the Oden logo for the tray icon.

    Tries the bundled logo first (PyInstaller), then the source tree.
    Falls back to a generated icon if the file is not found.
    """
    search_paths: list[Path] = []

    # PyInstaller bundle path
    if getattr(sys, "frozen", False):
        bundle_dir = Path(sys._MEIPASS)
        search_paths.append(bundle_dir / "images" / "logo_small.jpg")
        search_paths.append(bundle_dir / "images" / "logo.png")
        # macOS .app – resources may be next to the .app bundle
        if sys.platform == "darwin":
            app_dir = Path(os.path.dirname(sys.executable)).parent.parent.parent
            search_paths.append(app_dir / "images" / "logo_small.jpg")

    # Source tree
    source_root = Path(__file__).parent.parent
    search_paths.append(source_root / "images" / "logo_small.jpg")
    search_paths.append(source_root / "images" / "logo.png")

    for path in search_paths:
        if path.exists():
            try:
                img = PILImage.open(path)
                img = img.resize((64, 64), PILImage.Resampling.LANCZOS)
                logger.debug("Loaded tray icon from %s", path)
                return img
            except Exception as e:
                logger.warning("Failed to load icon from %s: %s", path, e)

    # Fallback: generate a simple blue circle
    logger.debug("Generating fallback tray icon")
    from PIL import ImageDraw

    img = PILImage.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#4A90D9")
    return img


class OdenTray:
    """System tray icon controller for Oden.

    Provides Start/Stop toggle for the watcher loop,
    Open Web GUI button, and Quit.

    Usage::

        tray = OdenTray(version="1.0", web_port=8080)
        tray.set_callbacks(on_start=..., on_stop=..., on_quit=...)

        # Blocks the main thread (required for macOS NSApp loop).
        # *on_ready* is called in a background thread once the icon is visible.
        tray.run(on_ready=lambda: run_watcher_loop(tray))
    """

    def __init__(self, version: str, web_port: int) -> None:
        self._version = version
        self._web_port = web_port
        self._running = False
        self._icon: Any = None
        self._on_start: Callable[[], None] | None = None
        self._on_stop: Callable[[], None] | None = None
        self._on_quit: Callable[[], None] | None = None
        self._ready = threading.Event()
        self.quit_event = threading.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the watcher loop is currently running."""
        return self._running

    @running.setter
    def running(self, value: bool) -> None:
        self._running = value
        if self._icon is not None:
            with contextlib.suppress(Exception):
                self._icon.update_menu()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_callbacks(
        self,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        """Set callback functions for tray menu actions.

        Args:
            on_start: Called when user clicks Start.
            on_stop: Called when user clicks Stop.
            on_quit: Called when user clicks Quit.
        """
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_quit = on_quit

    # ------------------------------------------------------------------
    # Menu helpers (private)
    # ------------------------------------------------------------------

    def _get_start_stop_text(self, item: Any) -> str:
        """Dynamic text for the Start/Stop menu item."""
        return "⏹ Stoppa" if self._running else "▶ Starta"

    def _on_start_stop(self, icon: Any, item: Any) -> None:
        """Handle Start/Stop menu click."""
        if self._running:
            logger.info("Tray: Stop requested")
            if self._on_stop:
                self._on_stop()
        else:
            logger.info("Tray: Start requested")
            if self._on_start:
                self._on_start()

    def _on_open_gui(self, icon: Any, item: Any) -> None:
        """Open the web GUI in the default browser."""
        url = f"http://127.0.0.1:{self._web_port}"
        logger.info("Tray: Opening web GUI at %s", url)
        try:
            webbrowser.open(url)
        except Exception as e:
            logger.error("Failed to open browser: %s", e)

    def _on_quit_clicked(self, icon: Any, item: Any) -> None:
        """Handle Quit menu click."""
        logger.info("Tray: Quit requested")
        self.quit_event.set()
        if self._on_quit:
            self._on_quit()
        # Note: self.stop() is NOT called here — the watcher loop's
        # finally block handles tray cleanup after the async lifecycle
        # has finished shutting down all components.

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self) -> bool:
        """Build the icon and menu. Call before :meth:`run`.

        Returns:
            True if pystray is available and the icon was created.
        """
        if not _ensure_imports():
            return False

        image = _load_icon()

        menu = pystray.Menu(
            pystray.MenuItem(f"Oden v{self._version}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._get_start_stop_text, self._on_start_stop),
            pystray.MenuItem("🌐 Öppna Web GUI", self._on_open_gui),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Avsluta", self._on_quit_clicked),
        )

        self._icon = pystray.Icon("Oden", image, "Oden", menu)
        logger.info("System tray icon created")
        return True

    def run(self, on_ready: Callable[[], None] | None = None) -> None:
        """Start the tray event loop (**blocks the calling thread**).

        On macOS this runs the NSApplication loop on the main thread.
        *on_ready* is invoked in a background thread once the icon is
        visible — put your app logic there.

        Returns only after :meth:`stop` has been called (e.g. via *Quit*).

        Args:
            on_ready: Callback executed in a background thread once the
                      tray icon is visible.
        """
        if self._icon is None:
            return

        def _setup(icon: Any) -> None:
            icon.visible = True
            self._ready.set()
            logger.info("System tray icon visible")
            if on_ready:
                on_ready()

        try:
            self._icon.run(setup=_setup)
        except Exception as e:
            logger.error("Tray event loop error: %s", e)

    def stop(self) -> None:
        """Remove the tray icon and exit the tray event loop."""
        if self._icon is not None:
            try:
                self._icon.stop()
                logger.info("System tray icon stopped")
            except Exception:
                pass
            self._icon = None
