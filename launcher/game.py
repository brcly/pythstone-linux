"""
game.py — Hearthstone Linux Launcher
Handles launching the Hearthstone process and monitoring it.

Key constraints from the upstream project:
  • The binary MUST be launched with CWD = the install directory.
    The game reads `token` and `client.config` relative to CWD.
  • stdout/stderr from the game process are not very useful but we
    capture them anyway so they show up in the Logs page.
  • The game manages its own window; we just need to track whether it's
    still running so the launcher can update its UI state.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import (
    QObject,
    QProcess,
    QProcessEnvironment,
    pyqtSignal,
    pyqtSlot,
)

from launcher.config import ConfigManager, InstallState

# ---------------------------------------------------------------------------
# Callback types
# ---------------------------------------------------------------------------

LogCallback = Callable[[str], None]


# ---------------------------------------------------------------------------
# Pre-launch checks
# ---------------------------------------------------------------------------


class LaunchError(Exception):
    """Raised when a pre-launch check fails."""


def check_ready_to_launch(config: ConfigManager) -> list[str]:
    """
    Return a list of human-readable problems that would prevent launch.
    An empty list means we're clear to go.
    """
    issues: list[str] = []
    state = config.get_install_state()

    if not state.is_installed:
        issues.append(
            "Game binary not found. "
            "Please complete the installation on the Install tab first."
        )
    if not state.has_token:
        issues.append(
            "No login token found. Please log in on the Login tab before launching."
        )
    if not state.has_client_config:
        issues.append(
            "client.config is missing. Try re-running the installer to regenerate it."
        )
    return issues


# ---------------------------------------------------------------------------
# Game process manager
# ---------------------------------------------------------------------------


class GameProcess(QObject):
    """
    Wraps QProcess around the Hearthstone binary.

    Signals:
        started      — game process has started successfully
        finished     — game process has exited (exit_code: int)
        log_line     — a line of stdout/stderr output from the game
        error        — a human-readable error string (pre-launch or runtime)
    """

    started = pyqtSignal()
    finished = pyqtSignal(int)  # exit code
    log_line = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, config: ConfigManager, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._process: Optional[QProcess] = None

    # ------------------------------------------------------------------ #
    # Public                                                              #
    # ------------------------------------------------------------------ #

    @property
    def is_running(self) -> bool:
        return (
            self._process is not None
            and self._process.state() != QProcess.ProcessState.NotRunning
        )

    def launch(self) -> None:
        """
        Perform pre-launch checks then start the game process.
        Any failure emits error() instead of raising.
        """
        if self.is_running:
            self.error.emit("The game is already running.")
            return

        issues = check_ready_to_launch(self._cfg)
        if issues:
            self.error.emit("\n".join(f"• {i}" for i in issues))
            return

        settings = self._cfg.settings
        install_dir = settings.install_path
        binary = install_dir / "Bin" / "Hearthstone.x86_64"

        # Ensure client.config has the correct flat format before every launch.
        # write_token() used to overwrite it with the old ini format; guard against that.
        self._ensure_client_config(install_dir, settings.region)

        self._process = QProcess(self)
        self._process.setWorkingDirectory(str(install_dir))
        self._process.setProcessEnvironment(self._build_env())

        # Merge stdout and stderr into one channel
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)

        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.started.connect(self._on_started)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error_occurred)

        args = settings.launch_args or []
        self.log_line.emit(f"$ {binary} {' '.join(args)}".strip())
        self._process.start(str(binary), args)

    def terminate(self) -> None:
        """Ask the game to exit gracefully, then kill if it doesn't."""
        if self._process and self.is_running:
            self.log_line.emit("Sending terminate signal to game process…")
            self._process.terminate()
            # QProcess.waitForFinished default is 30s; we use 5s then kill
            if not self._process.waitForFinished(5000):
                self.log_line.emit("Process did not exit — sending kill.")
                self._process.kill()

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    def _ensure_client_config(self, install_dir, region: str) -> None:
        """
        Guarantee client.config has the flat key=value format the game requires.
        Rewrites it if it looks like the old ini-style format.
        """
        from launcher.installer import REGION_SERVER_MAP, _build_client_config

        config_path = install_dir / "client.config"
        needs_rewrite = True
        if config_path.is_file():
            content = config_path.read_text(encoding="utf-8", errors="replace")
            # Correct format has Aurora.Env= not [Aurora]
            if "Aurora.Env=" in content and "Aurora.ClientCheck=false" in content:
                needs_rewrite = False
        if needs_rewrite:
            self.log_line.emit("Rewriting client.config to correct format…")
            config_path.write_text(_build_client_config(region), encoding="utf-8")

    def _build_env(self) -> QProcessEnvironment:
        """
        Build the process environment:
          - start from the current process environment
          - apply Wayland workaround env var if configured
          - apply user-defined extra env vars
        """
        env = QProcessEnvironment.systemEnvironment()

        workaround = self._cfg.settings.wayland_workaround_enum
        from launcher.config import WaylandWorkaround

        if workaround != WaylandWorkaround.NONE:
            env.insert(workaround.value, "1")

        for key, val in self._cfg.settings.extra_env_vars.items():
            env.insert(key, val)

        return env

    # ------------------------------------------------------------------ #
    # Slots                                                               #
    # ------------------------------------------------------------------ #

    @pyqtSlot()
    def _on_started(self) -> None:
        self.log_line.emit(f"✓ Hearthstone started (PID {self._process.processId()})")
        self.started.emit()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if exit_status == QProcess.ExitStatus.NormalExit:
            self.log_line.emit(f"Game exited normally (code {exit_code}).")
        else:
            self.log_line.emit(f"Game crashed or was killed (code {exit_code}).")
        self.finished.emit(exit_code)

    @pyqtSlot()
    def _on_output(self) -> None:
        if self._process:
            data = self._process.readAllStandardOutput().data()
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = repr(data)
            for line in text.splitlines():
                if line.strip():
                    self.log_line.emit(line)

    @pyqtSlot(QProcess.ProcessError)
    def _on_error_occurred(self, proc_error: QProcess.ProcessError) -> None:
        messages = {
            QProcess.ProcessError.FailedToStart: (
                "Failed to start the game binary. "
                "Check that the file exists and is executable."
            ),
            QProcess.ProcessError.Crashed: "The game process crashed.",
            QProcess.ProcessError.Timedout: "Process operation timed out.",
            QProcess.ProcessError.WriteError: "Write error communicating with process.",
            QProcess.ProcessError.ReadError: "Read error communicating with process.",
            QProcess.ProcessError.UnknownError: "An unknown process error occurred.",
        }
        self.error.emit(messages.get(proc_error, f"Process error: {proc_error}"))
