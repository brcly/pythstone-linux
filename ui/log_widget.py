"""
log_widget.py — Hearthstone Linux Launcher
A reusable live log output widget with coloured message levels and
auto-scroll.  Thread-safe: append_line() may be called from any thread.
"""

from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Log levels → colours
# ---------------------------------------------------------------------------

class LogLevel(Enum):
    DEBUG   = "debug"
    INFO    = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR   = "error"
    CMD     = "cmd"       # shell commands echoed from the installer
    STEP    = "step"      # high-level step headers


# Maps each level to an RGB hex colour that pops on the dark background
_LEVEL_COLOURS: dict[LogLevel, str] = {
    LogLevel.DEBUG:   "#6b7280",   # muted grey
    LogLevel.INFO:    "#cbd5e1",   # soft white
    LogLevel.SUCCESS: "#4ade80",   # green
    LogLevel.WARNING: "#fbbf24",   # amber
    LogLevel.ERROR:   "#f87171",   # red
    LogLevel.CMD:     "#7dd3fc",   # sky blue  ($ commands)
    LogLevel.STEP:    "#f59e0b",   # gold      (── Step N ──)
}

# Prefixes used to auto-detect level from plain strings (installer output)
_PREFIX_MAP: list[tuple[str, LogLevel]] = [
    ("✓",    LogLevel.SUCCESS),
    ("──",   LogLevel.STEP),
    ("$ ",   LogLevel.CMD),
    ("warn", LogLevel.WARNING),
    ("error",LogLevel.ERROR),
    ("fail", LogLevel.ERROR),
]


def _detect_level(line: str) -> LogLevel:
    low = line.lower()
    for prefix, level in _PREFIX_MAP:
        if low.startswith(prefix.lower()) or line.startswith(prefix):
            return level
    return LogLevel.INFO


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

class LogWidget(QWidget):
    """
    A self-contained log viewer widget.

    Usage:
        log = LogWidget(parent)
        log.append_line("Downloading game files…")
        log.append_line("$ keg sync …", level=LogLevel.CMD)
        log.append_line("✓ Done", level=LogLevel.SUCCESS)
        log.clear()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._auto_scroll = True
        self._setup_ui()
        self._apply_styles()

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #

    def append_line(
        self,
        text: str,
        level: LogLevel | None = None,
    ) -> None:
        """
        Append a single line to the log.  Safe to call from any thread —
        marshals onto the Qt main thread via invokeMethod if needed.
        """
        if level is None:
            level = _detect_level(text)

        # Cross-thread safety: schedule on the main thread
        QMetaObject.invokeMethod(
            self,
            "_append_line_main_thread",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, text),
            Q_ARG(str, level.value),
        )

    def clear(self) -> None:
        self._text.clear()

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled
        self._scroll_btn.setChecked(not enabled)

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    @pyqtSlot(str, str)
    def _append_line_main_thread(self, text: str, level_value: str) -> None:
        try:
            level = LogLevel(level_value)
        except ValueError:
            level = LogLevel.INFO

        colour = _LEVEL_COLOURS.get(level, "#cbd5e1")

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colour))

        # Step headers get a subtle bold treatment
        if level == LogLevel.STEP:
            fmt.setFontWeight(700)
        else:
            fmt.setFontWeight(400)

        cursor.insertText(text + "\n", fmt)

        if self._auto_scroll:
            self._text.setTextCursor(cursor)
            self._text.ensureCursorVisible()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(8, 4, 8, 4)
        toolbar.setSpacing(8)

        self._scroll_btn = QPushButton("⏸  Pause scroll")
        self._scroll_btn.setCheckable(True)
        self._scroll_btn.setFixedHeight(26)
        self._scroll_btn.clicked.connect(self._on_scroll_toggle)

        self._clear_btn = QPushButton("✕  Clear")
        self._clear_btn.setFixedHeight(26)
        self._clear_btn.clicked.connect(self.clear)

        toolbar.addStretch()
        toolbar.addWidget(self._scroll_btn)
        toolbar.addWidget(self._clear_btn)

        # Text area
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        root.addLayout(toolbar)
        root.addWidget(self._text)

    def _apply_styles(self) -> None:
        mono = QFont("JetBrains Mono, Fira Code, Cascadia Code, Consolas, monospace")
        mono.setPointSize(9)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._text.setFont(mono)

        self._text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0d1117;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 4px;
                padding: 8px;
                selection-background-color: #1e3a5f;
            }
        """)

        btn_style = """
            QPushButton {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
                border-radius: 3px;
                padding: 2px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #263548;
                color: #cbd5e1;
            }
            QPushButton:checked {
                background-color: #292524;
                color: #fbbf24;
                border-color: #92400e;
            }
        """
        self._scroll_btn.setStyleSheet(btn_style)
        self._clear_btn.setStyleSheet(btn_style)

        self.setStyleSheet("background-color: #111827;")

    def _on_scroll_toggle(self, checked: bool) -> None:
        self._auto_scroll = not checked
        self._scroll_btn.setText("▶  Resume scroll" if checked else "⏸  Pause scroll")
