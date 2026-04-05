"""
home_page.py — Hearthstone Linux Launcher
The Play / Home page — the first thing the user sees.

Shows:
  • Current install status (version, token, disk usage)
  • A big Play button
  • Inline warnings if something needs attention
  • Live game process output while the game is running
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from launcher.config import ConfigManager
from launcher.game import GameProcess, check_ready_to_launch
from ui.log_widget import LogLevel, LogWidget

# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

CLR_BG = "#141f2e"
CLR_PANEL = "#111d2b"
CLR_BORDER = "#1e3a5f"
CLR_ACCENT = "#f59e0b"
CLR_ACCENT_DIM = "#92400e"
CLR_TEXT = "#e2e8f0"
CLR_TEXT_MUTED = "#64748b"
CLR_OK = "#4ade80"
CLR_WARN = "#fbbf24"
CLR_ERR = "#f87171"


# ---------------------------------------------------------------------------
# Status card — shows install state at a glance
# ---------------------------------------------------------------------------


class StatusCard(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._apply_styles()

    def refresh(self, config: ConfigManager) -> None:
        state = config.get_install_state()

        if state.is_installed:
            ver = state.installed_version or "unknown"
            self._version_lbl.setText(f"Version  {ver}")
            self._version_lbl.setStyleSheet(
                f"color: {CLR_OK}; font-size: 13px; font-weight: 600;"
            )
        else:
            self._version_lbl.setText("Not installed")
            self._version_lbl.setStyleSheet(
                f"color: {CLR_ERR}; font-size: 13px; font-weight: 600;"
            )

        if state.has_token:
            self._token_lbl.setText("● Token present")
            self._token_lbl.setStyleSheet(f"color: {CLR_OK}; font-size: 12px;")
        else:
            self._token_lbl.setText("● Not logged in")
            self._token_lbl.setStyleSheet(f"color: {CLR_WARN}; font-size: 12px;")

        region = config.settings.region_enum.label
        self._region_lbl.setText(f"Region: {region}")

        cache = state.ngdp_cache_size_human
        self._cache_lbl.setText(f"Cache: {cache}")

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(32)

        self._version_lbl = QLabel("—")
        self._token_lbl = QLabel("—")
        self._region_lbl = QLabel("—")
        self._cache_lbl = QLabel("—")

        for lbl in (
            self._version_lbl,
            self._token_lbl,
            self._region_lbl,
            self._cache_lbl,
        ):
            lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 12px;")
            layout.addWidget(lbl)

        layout.addStretch()

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{
                background: {CLR_PANEL};
                border: 1px solid {CLR_BORDER};
                border-radius: 6px;
            }}
        """)


# ---------------------------------------------------------------------------
# Warning banner — shown when pre-launch checks fail
# ---------------------------------------------------------------------------


class WarningBanner(QWidget):
    navigate_requested = pyqtSignal(int)  # page index to navigate to

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.hide()

    def show_issues(self, issues: list[str]) -> None:
        if not issues:
            self.hide()
            return
        self._text.setText("\n".join(f"  • {i}" for i in issues))
        self.show()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon = QLabel("⚠")
        icon.setStyleSheet(
            f"color: {CLR_WARN}; font-size: 16px; background: transparent;"
        )
        title = QLabel("Action required before launching:")
        title.setStyleSheet(
            f"color: {CLR_WARN}; font-size: 13px; font-weight: 600; background: transparent;"
        )
        header.addWidget(icon)
        header.addWidget(title)
        header.addStretch()

        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setStyleSheet(
            f"color: {CLR_WARN}; font-size: 12px; background: transparent;"
        )

        btn_row = QHBoxLayout()
        install_btn = QPushButton("→ Go to Install")
        login_btn = QPushButton("→ Go to Login")
        for btn, idx in ((install_btn, 1), (login_btn, 2)):
            btn.clicked.connect(lambda _, i=idx: self.navigate_requested.emit(i))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #2d1f00;
                    color: {CLR_WARN};
                    border: 1px solid {CLR_ACCENT_DIM};
                    border-radius: 3px;
                    padding: 4px 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{
                    background: #3d2a00;
                }}
            """)
            btn_row.addWidget(btn)
        btn_row.addStretch()

        layout.addLayout(header)
        layout.addWidget(self._text)
        layout.addLayout(btn_row)

        self.setStyleSheet(f"""
            QWidget {{
                background: #1f1500;
                border: 1px solid {CLR_ACCENT_DIM};
                border-radius: 6px;
            }}
        """)


# ---------------------------------------------------------------------------
# Play button
# ---------------------------------------------------------------------------


class PlayButton(QPushButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("▶  Play", parent)
        self.setFixedHeight(54)
        self.setMinimumWidth(200)
        self._set_idle()

    def set_state_idle(self) -> None:
        self.setEnabled(True)
        self.setText("▶  Play")
        self._set_idle()

    def set_state_running(self) -> None:
        self.setEnabled(True)
        self.setText("■  Stop Game")
        self._set_running()

    def set_state_disabled(self) -> None:
        self.setEnabled(False)
        self.setText("▶  Play")
        self._set_idle()

    def _set_idle(self) -> None:
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #d97706, stop:1 #b45309
                );
                color: #fff;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f59e0b, stop:1 #d97706
                );
            }}
            QPushButton:disabled {{
                background: #374151;
                color: {CLR_TEXT_MUTED};
            }}
        """)

    def _set_running(self) -> None:
        self.setStyleSheet(f"""
            QPushButton {{
                background: #1e3a5f;
                color: {CLR_ERR};
                border: 1px solid #ef4444;
                border-radius: 6px;
                font-size: 16px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: #254d7a;
            }}
        """)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------


class HomePage(QWidget):
    """
    The Play / Home page.

    Signals:
        navigate_requested(int) — ask the main window to switch to a page
    """

    navigate_requested = pyqtSignal(int)

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._process = GameProcess(config, self)
        self._build_ui()
        self._apply_styles()
        self._wire_process()
        self.refresh()

    # ------------------------------------------------------------------ #
    # Public                                                              #
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        self._status_card.refresh(self._cfg)
        issues = check_ready_to_launch(self._cfg)
        self._warning_banner.show_issues(issues)
        if issues:
            self._play_btn.set_state_disabled()
        elif not self._process.is_running:
            self._play_btn.set_state_idle()

    @property
    def log_widget(self) -> LogWidget:
        return self._log

    # ------------------------------------------------------------------ #
    # Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # Title
        title = QLabel("Play")
        title.setStyleSheet(f"color: {CLR_TEXT}; font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        # Status card
        self._status_card = StatusCard()
        root.addWidget(self._status_card)

        # Warning banner
        self._warning_banner = WarningBanner()
        self._warning_banner.navigate_requested.connect(self.navigate_requested)
        root.addWidget(self._warning_banner)

        # Play button row
        btn_row = QHBoxLayout()
        self._play_btn = PlayButton()
        self._play_btn.clicked.connect(self._on_play_clicked)
        btn_row.addStretch()
        btn_row.addWidget(self._play_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {CLR_BORDER};")
        root.addWidget(line)

        # Game output log
        log_label = QLabel("Game Output")
        log_label.setStyleSheet(
            f"color: {CLR_ACCENT}; font-size: 11px; font-weight: 600; "
            f"letter-spacing: 1px; text-transform: uppercase;"
        )
        root.addWidget(log_label)

        self._log = LogWidget()
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        root.addWidget(self._log, stretch=1)

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"background: {CLR_BG};")

    # ------------------------------------------------------------------ #
    # Process wiring                                                      #
    # ------------------------------------------------------------------ #

    def _wire_process(self) -> None:
        self._process.started.connect(self._on_game_started)
        self._process.finished.connect(self._on_game_finished)
        self._process.log_line.connect(lambda line: self._log.append_line(line))
        self._process.error.connect(self._on_game_error)

        # Timer for tailing Player.log while game is running
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(500)
        self._log_timer.timeout.connect(self._tail_player_log)
        self._log_file_pos = 0

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    @pyqtSlot()
    def _on_play_clicked(self) -> None:
        if self._process.is_running:
            self._process.terminate()
        else:
            self._log.clear()
            if self._cfg.settings.check_for_updates_on_launch:
                self._check_for_update_then_launch()
            else:
                self._process.launch()

    def _check_for_update_then_launch(self) -> None:
        """Quick online version check before launching."""
        import urllib.request

        from launcher.installer import NGDP_PRODUCT, REGION_NGDP_HOSTS, Installer

        region = self._cfg.settings.region
        host = REGION_NGDP_HOSTS.get(region, REGION_NGDP_HOSTS["us"])
        url = f"http://{host}/{NGDP_PRODUCT}/versions"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                content = resp.read().decode("utf-8")
            online = Installer._parse_ngdp_version(content)
            installed = self._cfg.get_install_state().installed_version
            if online and installed and online != installed:
                from PyQt6.QtWidgets import QMessageBox

                reply = QMessageBox.question(
                    self,
                    "Update Available",
                    f"A new version is available!\n\n"
                    f"Installed: {installed}\nAvailable: {online}\n\n"
                    "Update now before launching?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Cancel:
                    return
                if reply == QMessageBox.StandardButton.Yes:
                    self.navigate_requested.emit(1)  # Go to Install page
                    return
        except Exception:
            pass  # Network unavailable — just launch anyway
        self._process.launch()

    @pyqtSlot()
    def _on_game_started(self) -> None:
        self._play_btn.set_state_running()
        self._token_expiry_notified = False  # reset per session
        # Reset and start tailing Player.log
        self._log_file_pos = 0
        player_log = self._player_log_path()
        if player_log.is_file():
            # Seek to end so we only show new output
            self._log_file_pos = player_log.stat().st_size
        self._log_timer.start()

    def _player_log_path(self) -> Path:
        install = self._cfg.settings.install_path
        # Unity writes Player.log to XDG config dir
        return (
            Path.home()
            / ".config"
            / "unity3d"
            / "Blizzard Entertainment"
            / "Hearthstone"
            / "Player.log"
        )

    @pyqtSlot()
    def _tail_player_log(self) -> None:
        log_path = self._player_log_path()
        if not log_path.is_file():
            return
        try:
            size = log_path.stat().st_size
            if size <= self._log_file_pos:
                return
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._log_file_pos)
                new_text = f.read()
            self._log_file_pos = size
            for line in new_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Detect token expiry
                if (
                    "login_failure" in line.lower()
                    or "failed to get token" in line.lower()
                    or "network_login_failure" in line.lower()
                ):
                    self._log.append_line(line, LogLevel.ERROR)
                    self._notify_token_expired()
                    continue
                if any(
                    x in line for x in ("error", "Error", "ERROR", "failed", "Failed")
                ):
                    level = LogLevel.ERROR
                elif any(x in line for x in ("warn", "Warn", "WARNING")):
                    level = LogLevel.WARNING
                else:
                    level = LogLevel.INFO
                self._log.append_line(line, level)
        except OSError:
            pass

    def _notify_token_expired(self) -> None:
        """Show a one-time prompt when login failure is detected in the log."""
        if getattr(self, "_token_expiry_notified", False):
            return
        self._token_expiry_notified = True
        from PyQt6.QtWidgets import QMessageBox

        reply = QMessageBox.warning(
            self,
            "Login Failed",
            "The game was unable to log you in through Blizzard services.\n\n"
            "Your token may have expired. Would you like to go to the Login tab "
            "to generate a new token?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.navigate_requested.emit(2)  # Login page index

    @pyqtSlot(int)
    def _on_game_finished(self, exit_code: int) -> None:
        self._log_timer.stop()
        self._tail_player_log()  # flush any remaining output
        self._play_btn.set_state_idle()
        self.refresh()
        if exit_code != 0:
            self._surface_crash_info(exit_code)

    def _surface_crash_info(self, exit_code: int) -> None:
        """Extract the most relevant lines from Player.log after a crash."""
        log_path = self._player_log_path()
        if not log_path.is_file():
            self._log.append_line(
                f"Game exited with code {exit_code}. No Player.log found.",
                LogLevel.ERROR,
            )
            return
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        # Collect the last crash-relevant lines
        relevant = []
        keywords = (
            "fatal",
            "crash",
            "sigsegv",
            "sigabrt",
            "error",
            "exception",
            "failed to load",
            "could not load",
            "unable to",
        )
        for line in lines[-200:]:
            low = line.lower()
            if any(k in low for k in keywords):
                relevant.append(line.strip())
        if relevant:
            self._log.append_line(
                f"── Game crashed (exit {exit_code}) — relevant log lines ──",
                LogLevel.ERROR,
            )
            for line in relevant[-10:]:  # last 10 relevant lines
                self._log.append_line(f"  {line}", LogLevel.ERROR)

    @pyqtSlot(str)
    def _on_game_error(self, message: str) -> None:
        self._log.append_line(f"error: {message}", LogLevel.ERROR)
        if not self._process.is_running:
            self._play_btn.set_state_idle()
        self.refresh()
