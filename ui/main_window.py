"""
main_window.py — Hearthstone Linux Launcher
Top-level application window.

Layout:
    ┌─────────────────────────────────────────────┐
    │  Header (logo wordmark + version badge)      │
    ├──────────┬──────────────────────────────────┤
    │          │                                  │
    │ Sidebar  │   Page stack (QStackedWidget)    │
    │  nav     │                                  │
    │          │                                  │
    ├──────────┴──────────────────────────────────┤
    │  Status bar  (install state · token · ver)  │
    └─────────────────────────────────────────────┘

Pages (added externally by app.py):
    0 — Home / Play
    1 — Install / Update
    2 — Login
    3 — Settings
    4 — Logs
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from launcher.config import ConfigManager, InstallState, SystemInfo

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_NAME = "Pythstone Launcher"
APP_VERSION = "0.1.0"

# Sidebar nav items: (label, icon_char, page_index)
NAV_ITEMS = [
    ("Play", "▶", 0),
    ("Install", "⬇", 1),
    ("Login", "🔑", 2),
    ("Settings", "⚙", 3),
]

# Design tokens
CLR_BG_BASE = "#0f1923"  # deepest background
CLR_BG_SIDEBAR = "#111d2b"  # slightly lighter sidebar
CLR_BG_HEADER = "#0a1520"  # darker header strip
CLR_BG_CONTENT = "#141f2e"  # content area
CLR_ACCENT = "#f59e0b"  # Hearthstone gold
CLR_ACCENT_DIM = "#92400e"  # dimmed gold (borders)
CLR_TEXT_PRIMARY = "#e2e8f0"
CLR_TEXT_MUTED = "#64748b"
CLR_TEXT_HEADER = "#f8fafc"
CLR_BORDER = "#1e3a5f"
CLR_NAV_HOVER = "#1a2f45"
CLR_NAV_ACTIVE = "#1e3a5f"
CLR_STATUS_OK = "#4ade80"
CLR_STATUS_WARN = "#fbbf24"
CLR_STATUS_ERR = "#f87171"

SIDEBAR_WIDTH = 160
HEADER_HEIGHT = 56
STATUS_HEIGHT = 28


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


class HeaderBar(QWidget):
    """Slim top bar with the app wordmark and build version."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(12)

        # Wordmark
        self._wordmark = QLabel(
            "⬡  Hearthstone  <span style='color:#f59e0b'>Linux</span>"
        )
        self._wordmark.setTextFormat(Qt.TextFormat.RichText)

        # Version badge
        self._badge = QLabel(f"v{APP_VERSION}")

        layout.addWidget(self._wordmark)
        layout.addStretch()
        layout.addWidget(self._badge)

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"background-color: {CLR_BG_HEADER};")

        wordmark_font = QFont()
        wordmark_font.setPointSize(14)
        wordmark_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        wordmark_font.setWeight(QFont.Weight.DemiBold)
        self._wordmark.setFont(wordmark_font)
        self._wordmark.setStyleSheet(f"color: {CLR_TEXT_HEADER};")

        self._badge.setStyleSheet(f"""
            color: {CLR_ACCENT};
            background: {CLR_ACCENT_DIM}44;
            border: 1px solid {CLR_ACCENT_DIM};
            border-radius: 3px;
            padding: 1px 7px;
            font-size: 11px;
        """)


# ---------------------------------------------------------------------------
# Sidebar nav button
# ---------------------------------------------------------------------------


class NavButton(QPushButton):
    """A single sidebar navigation item."""

    def __init__(
        self, icon_char: str, label: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # Outer layout: indicator bar | content
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Active indicator — a narrow colored bar on the left edge
        self._indicator = QFrame()
        self._indicator.setFixedWidth(3)
        self._indicator.setStyleSheet(f"background: transparent; border: none;")
        outer.addWidget(self._indicator)

        # Content: icon + label
        inner = QHBoxLayout()
        inner.setContentsMargins(13, 0, 16, 0)
        inner.setSpacing(12)

        self._icon_lbl = QLabel(icon_char)
        self._icon_lbl.setFixedWidth(18)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")

        self._text_lbl = QLabel(label)
        self._text_lbl.setStyleSheet("background: transparent;")

        inner.addWidget(self._icon_lbl)
        inner.addWidget(self._text_lbl)
        inner.addStretch()
        outer.addLayout(inner)

        self._apply_styles()

    def _apply_styles(self) -> None:
        self._text_lbl.setStyleSheet(
            f"color: {CLR_TEXT_MUTED}; font-size: 13px; background: transparent;"
        )
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton:hover {{
                background: {CLR_NAV_HOVER};
            }}
            QPushButton:checked {{
                background: {CLR_NAV_ACTIVE};
            }}
        """)

    def enterEvent(self, event) -> None:
        if not self.isChecked():
            self._indicator.setStyleSheet(
                f"background: {CLR_ACCENT_DIM}; border: none;"
            )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if not self.isChecked():
            self._indicator.setStyleSheet("background: transparent; border: none;")
        super().leaveEvent(event)

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        colour = CLR_TEXT_PRIMARY if active else CLR_TEXT_MUTED
        weight = "600" if active else "400"
        self._text_lbl.setStyleSheet(
            f"color: {colour}; font-size: 13px; font-weight: {weight}; "
            f"background: transparent;"
        )
        bar_colour = CLR_ACCENT if active else "transparent"
        self._indicator.setStyleSheet(f"background: {bar_colour}; border: none;")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


class Sidebar(QWidget):
    """Left navigation panel."""

    page_requested = pyqtSignal(int)  # emitted when user clicks a nav item

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_WIDTH)
        self._buttons: list[NavButton] = []
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)

        for label, icon, page_idx in NAV_ITEMS:
            btn = NavButton(icon, label)
            btn.clicked.connect(lambda _, idx=page_idx: self._on_nav_clicked(idx))
            self._buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()

        # Activate first item by default
        if self._buttons:
            self._buttons[0].set_active(True)

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
             QWidget#Sidebar {{
                background-color: {CLR_BG_SIDEBAR};
                border-right: 1px solid {CLR_BORDER};
            }}
        """)

    def set_active_page(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.set_active(i == index)

    def _on_nav_clicked(self, page_idx: int) -> None:
        self.set_active_page(page_idx)
        self.page_requested.emit(page_idx)


# ---------------------------------------------------------------------------
# Status bar
# ---------------------------------------------------------------------------


class StatusFooter(QWidget):
    """
    Bottom strip showing install state, token presence, and game version.
    Refreshed by calling refresh(install_state).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(STATUS_HEIGHT)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(0)

        self._install_dot = QLabel("●")
        self._install_lbl = QLabel("Not installed")
        self._sep1 = QLabel("  ·  ")
        self._token_dot = QLabel("●")
        self._token_lbl = QLabel("No token")
        self._sep2 = QLabel("  ·  ")
        self._version_lbl = QLabel("–")

        for w in (self._install_dot, self._token_dot):
            w.setFixedWidth(14)

        self._sep1.setStyleSheet(f"color: {CLR_BORDER};")
        self._sep2.setStyleSheet(f"color: {CLR_BORDER};")

        layout.addWidget(self._install_dot)
        layout.addWidget(self._install_lbl)
        layout.addWidget(self._sep1)
        layout.addWidget(self._token_dot)
        layout.addWidget(self._token_lbl)
        layout.addWidget(self._sep2)
        layout.addWidget(self._version_lbl)
        layout.addStretch()

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {CLR_BG_HEADER};
                border-top: 1px solid {CLR_BORDER};
            }}
            QLabel {{
                font-size: 11px;
                color: {CLR_TEXT_MUTED};
            }}
        """)

    def refresh(self, state: InstallState) -> None:
        """Update all status indicators from an InstallState snapshot."""
        # Install status
        if state.is_installed:
            self._install_dot.setStyleSheet(f"color: {CLR_STATUS_OK}; font-size: 10px;")
            self._install_lbl.setText("Installed")
        else:
            self._install_dot.setStyleSheet(
                f"color: {CLR_STATUS_ERR}; font-size: 10px;"
            )
            self._install_lbl.setText("Not installed")

        # Token status
        if state.has_token:
            self._token_dot.setStyleSheet(f"color: {CLR_STATUS_OK}; font-size: 10px;")
            self._token_lbl.setText("Token OK")
        else:
            self._token_dot.setStyleSheet(f"color: {CLR_STATUS_WARN}; font-size: 10px;")
            self._token_lbl.setText("Not logged in")

        # Version
        ver = state.installed_version
        self._version_lbl.setText(f"v{ver}" if ver else "–")

    def set_message(self, text: str, level: str = "info") -> None:
        """Temporarily display a plain message (e.g. 'Updating…')."""
        colour = {
            "ok": CLR_STATUS_OK,
            "warn": CLR_STATUS_WARN,
            "err": CLR_STATUS_ERR,
        }.get(level, CLR_TEXT_MUTED)
        self._version_lbl.setText(f"<span style='color:{colour}'>{text}</span>")
        self._version_lbl.setTextFormat(Qt.TextFormat.RichText)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class MainWindow(QMainWindow):
    """
    Top-level application window.

    Pages are registered externally (by app.py) via add_page().
    The sidebar drives navigation; pages can also request navigation
    programmatically via navigate_to().
    """

    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self._cfg = config
        self._pages: list[QWidget] = []

        self.setWindowTitle("Pythstone Linux Launcher")
        self.setMinimumSize(860, 560)
        self.resize(980, 640)

        self._build_ui()
        self._apply_global_styles()
        self._refresh_status()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def add_page(self, widget: QWidget) -> int:
        """Register a page widget. Returns the page index."""
        idx = self._stack.addWidget(widget)
        self._pages.append(widget)
        return idx

    def navigate_to(self, index: int) -> None:
        """Switch to a page by index and sync the sidebar highlight."""
        self._stack.setCurrentIndex(index)
        self._sidebar.set_active_page(index)

    def refresh_status(self) -> None:
        """Re-read install state from disk and update the status bar."""
        self._refresh_status()

    @property
    def status_footer(self) -> StatusFooter:
        return self._status

    # ------------------------------------------------------------------ #
    # Layout                                                              #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        self._header = HeaderBar()
        root.addWidget(self._header)

        # Divider
        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setStyleSheet(f"color: {CLR_BORDER}; max-height: 1px;")
        root.addWidget(hline)

        # Body: sidebar + page stack
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_requested.connect(self._on_nav_requested)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background-color: {CLR_BG_CONTENT};")

        body.addWidget(self._sidebar)
        body.addWidget(self._stack, stretch=1)
        root.addLayout(body, stretch=1)

        # Status footer
        self._status = StatusFooter()
        root.addWidget(self._status)

    # ------------------------------------------------------------------ #
    # Styles                                                              #
    # ------------------------------------------------------------------ #

    def _apply_global_styles(self) -> None:
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {CLR_BG_BASE};
                color: {CLR_TEXT_PRIMARY};
                font-family: 'IBM Plex Sans', 'Noto Sans', 'Cantarell', sans-serif;
                font-size: 13px;
            }}
            QScrollBar:vertical {{
                background: {CLR_BG_BASE};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {CLR_BORDER};
                border-radius: 4px;
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {CLR_ACCENT_DIM};
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0;
            }}
            QScrollBar:horizontal {{
                height: 0;
            }}
            QToolTip {{
                background-color: {CLR_BG_SIDEBAR};
                color: {CLR_TEXT_PRIMARY};
                border: 1px solid {CLR_BORDER};
                padding: 4px 8px;
                border-radius: 3px;
            }}
        """)

    # ------------------------------------------------------------------ #
    # Slots / internal                                                    #
    # ------------------------------------------------------------------ #

    def _on_nav_requested(self, page_idx: int) -> None:
        self._stack.setCurrentIndex(page_idx)

    def _refresh_status(self) -> None:
        state = self._cfg.get_install_state()
        self._status.refresh(state)
