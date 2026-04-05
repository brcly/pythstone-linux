"""
app.py — Hearthstone Linux Launcher
Application entry point.  Wires all pages into the main window,
applies Wayland env-var workarounds to the current process before
QApplication starts, and kicks off the event loop.
"""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt

# ---------------------------------------------------------------------------
# Logs page (thin wrapper — just the shared LogWidget in a page layout)
# ---------------------------------------------------------------------------
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QVBoxLayout, QWidget

from launcher.config import (
    ConfigManager,
    SystemInfo,
    WaylandWorkaround,
)
from ui.home_page import HomePage
from ui.install_page import InstallPage
from ui.log_widget import LogLevel, LogWidget
from ui.login_page import LoginPage
from ui.main_window import MainWindow
from ui.settings_page import SettingsPage


class LogsPage(QWidget):
    """Dedicated full-screen log viewer (mirrors the installer output)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel("Logs")
        title.setStyleSheet("color: #e2e8f0; font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        self._log = LogWidget()
        layout.addWidget(self._log, stretch=1)

        self.setStyleSheet("background: #141f2e;")

    @property
    def log_widget(self) -> LogWidget:
        return self._log


# ---------------------------------------------------------------------------
# Application bootstrap
# ---------------------------------------------------------------------------


def _apply_wayland_workaround(config: ConfigManager) -> None:
    """
    Inject the configured Wayland env var BEFORE QApplication is created,
    so both QtWebEngine and the game process inherit it.
    """
    workaround = config.settings.wayland_workaround_enum
    if workaround != WaylandWorkaround.NONE:
        os.environ[workaround.value] = "1"


def _check_pyqt_webengine() -> bool:
    """Return True if PyQt6-WebEngine is available."""
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401

        return True
    except ImportError:
        return False


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """
    Construct and return the QApplication + MainWindow without starting the
    event loop.  Useful for testing.
    """
    if argv is None:
        argv = sys.argv

    # Load config first so we can apply env vars before QApplication
    config = ConfigManager.load()
    _apply_wayland_workaround(config)

    # High-DPI is enabled by default in Qt6; no extra flags needed.
    app = QApplication(argv)
    app.setApplicationName("pythstone-launcher")
    app.setApplicationDisplayName("Pythstone Linux Launcher")
    app.setOrganizationName("pythstone-launcher")

    # Dark palette base (widgets not covered by stylesheet)
    app.setStyle("Fusion")
    from PyQt6.QtGui import QColor, QPalette

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0f1923"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0d1117"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#111d2b"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#1e293b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e2e8f0"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#1e3a5f"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#f59e0b"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111d2b"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#e2e8f0"))
    app.setPalette(palette)

    # Build window
    window = MainWindow(config)

    # ── Pages (order must match NAV_ITEMS in main_window.py) ──────────
    # 0 — Home / Play
    home_page = HomePage(config)
    home_page.navigate_requested.connect(window.navigate_to)
    window.add_page(home_page)

    # 1 — Install
    install_page = InstallPage(config)
    install_page.install_complete.connect(
        lambda: _on_install_complete(window, home_page, install_page)
    )
    window.add_page(install_page)

    # 2 — Login
    if _check_pyqt_webengine():
        login_page = LoginPage(config)
        login_page.token_saved.connect(lambda _: _on_token_saved(window, home_page))
    else:
        login_page = _make_webengine_missing_page()
    window.add_page(login_page)

    # 3 — Settings
    settings_page = SettingsPage(config)
    settings_page.settings_saved.connect(
        lambda: _on_settings_saved(window, home_page, install_page, settings_page)
    )
    window.add_page(settings_page)

    # 4 — Logs  (shared: install page and home page both write here too)
    logs_page = LogsPage()
    window.add_page(logs_page)

    # Route installer log lines to the dedicated Logs page as well
    install_page.log_widget.append_line(
        "Installer output will appear here.", LogLevel.INFO
    )
    logs_page.log_widget.append_line(
        "Install and game output will appear here.", LogLevel.INFO
    )

    return app, window


def run(argv: list[str] | None = None) -> int:
    """Entry point — build the app and start the event loop."""
    app, window = build_app(argv)
    window.show()
    return app.exec()


# ---------------------------------------------------------------------------
# Cross-page callbacks
# ---------------------------------------------------------------------------


def _on_install_complete(
    window: MainWindow,
    home_page: HomePage,
    install_page: InstallPage,
) -> None:
    """Called after a successful install/update."""
    window.refresh_status()
    home_page.refresh()
    # Navigate to Play page automatically
    window.navigate_to(0)


def _on_token_saved(window: MainWindow, home_page: HomePage) -> None:
    """Called after a new token is written to disk."""
    window.refresh_status()
    home_page.refresh()


def _on_settings_saved(
    window: MainWindow,
    home_page: HomePage,
    install_page: InstallPage,
    settings_page: SettingsPage,
) -> None:
    """Called after the user saves settings."""
    window.refresh_status()
    home_page.refresh()
    install_page.refresh()
    settings_page.refresh()


def _make_webengine_missing_page() -> QWidget:
    """Fallback page shown when PyQt6-WebEngine isn't installed."""
    page = QWidget()
    page.setStyleSheet("background: #141f2e;")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(40, 40, 40, 40)
    layout.setSpacing(12)
    layout.addStretch()

    icon = QLabel("⚠")
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet("color: #fbbf24; font-size: 48px;")

    title = QLabel("PyQt6-WebEngine not installed")
    title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    title.setStyleSheet("color: #e2e8f0; font-size: 16px; font-weight: 700;")

    body = QLabel(
        "The Login tab requires PyQt6-WebEngine to embed the Battle.net browser.\n\n"
        "Install it with:\n\n"
        "    pip install PyQt6-WebEngine\n\n"
        "Then restart the launcher.\n\n"
        "Alternatively, use the upstream ./login binary from the hearthstone-linux\n"
        "tooling directory to generate your token manually."
    )
    body.setAlignment(Qt.AlignmentFlag.AlignCenter)
    body.setStyleSheet(
        "color: #94a3b8; font-size: 13px; font-family: monospace; line-height: 1.6;"
    )
    body.setWordWrap(True)

    layout.addWidget(icon)
    layout.addWidget(title)
    layout.addWidget(body)
    layout.addStretch()

    return page


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(run())
