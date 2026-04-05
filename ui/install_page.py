"""
install_page.py — Hearthstone Linux Launcher
Install / Update page with step indicators, progress bar, and live log.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from launcher.config import ConfigManager, Region, SystemInfo
from launcher.installer import STEPS, InstallCancelled, Installer, InstallError
from ui.log_widget import LogLevel, LogWidget

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
CLR_BTN_PRIMARY = "#b45309"
CLR_BTN_HOVER = "#d97706"
CLR_BTN_CANCEL = "#1e293b"
CLR_BTN_CANCEL_HOVER = "#263548"


class InstallerWorker(QObject):
    log_line = pyqtSignal(str, str)
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal()
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, config, mode, cancel_event):
        super().__init__()
        self._config = config
        self._mode = mode
        self._cancel = cancel_event

    @pyqtSlot()
    def run(self):
        from ui.log_widget import _detect_level

        def log_cb(text):
            self.log_line.emit(text, _detect_level(text).value)

        def prog_cb(c, t, l):
            self.progress.emit(c, t, l)

        installer = Installer(self._config, log_cb, prog_cb, self._cancel)
        try:
            if self._mode == "update":
                installer.run_update()
            else:
                installer.run_install()
            self.finished.emit()
        except InstallCancelled:
            self.cancelled.emit()
        except InstallError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(f"Unexpected error: {e}")


class StepIndicator(QWidget):
    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self._steps = steps
        self._current = -1
        self._done = -1
        self._pills = []
        self._build()

    def reset(self):
        self._current = -1
        self._done = -1
        self._refresh()

    def set_step(self, i):
        self._done = i - 1
        self._current = i
        self._refresh()

    def complete(self):
        self._done = len(self._steps) - 1
        self._current = -1
        self._refresh()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)
        for i, step in enumerate(self._steps):
            pill = QLabel(str(i + 1))
            pill.setFixedSize(22, 22)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QLabel(step)
            name.setStyleSheet(f"color:{CLR_TEXT_MUTED};font-size:9px;")
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(pill, alignment=Qt.AlignmentFlag.AlignCenter)
            col.addWidget(name, alignment=Qt.AlignmentFlag.AlignCenter)
            self._pills.append(pill)
            layout.addLayout(col)
            if i < len(self._steps) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFixedHeight(2)
                line.setStyleSheet(f"background:{CLR_BORDER};border:none;")
                layout.addWidget(line, stretch=1)
        self._refresh()

    def _refresh(self):
        for i, pill in enumerate(self._pills):
            if i <= self._done:
                pill.setStyleSheet(
                    f"QLabel{{background:{CLR_OK};color:#0d1117;border-radius:11px;font-size:10px;font-weight:700;}}"
                )
            elif i == self._current:
                pill.setStyleSheet(
                    f"QLabel{{background:{CLR_ACCENT};color:#0d1117;border-radius:11px;font-size:10px;font-weight:700;}}"
                )
            else:
                pill.setStyleSheet(
                    f"QLabel{{background:{CLR_PANEL};color:{CLR_TEXT_MUTED};border:1px solid {CLR_BORDER};border-radius:11px;font-size:10px;}}"
                )


def _section_label(text):
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color:{CLR_ACCENT};font-size:11px;font-weight:600;letter-spacing:1px;padding-bottom:2px;"
    )
    return lbl


def _hline():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color:{CLR_BORDER};max-height:1px;margin:0;")
    return line


class DepWarningBanner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        icon = QLabel("⚠")
        icon.setStyleSheet(f"color:{CLR_WARN};font-size:16px;")
        icon.setFixedWidth(20)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setStyleSheet(f"color:{CLR_WARN};font-size:12px;")
        layout.addWidget(icon)
        layout.addWidget(self._text, stretch=1)
        self.setStyleSheet(
            f"QWidget{{background:#2d1f00;border:1px solid {CLR_ACCENT_DIM};border-radius:4px;}}"
        )
        self.hide()

    def populate(self, info):
        issues = []
        if info.missing_required_tools:
            issues.append("Missing tools: " + ", ".join(info.missing_required_tools))
        if info.missing_libs:
            issues.append("Missing libraries: " + ", ".join(info.missing_libs))
        if issues:
            self._text.setText(
                "Dependency issues detected — installation may fail.\n"
                + "\n".join(issues)
            )
            self.show()
        else:
            self.hide()


class ConfigPanel(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(_section_label("Install Directory"))
        dir_row = QHBoxLayout()
        dir_row.setSpacing(6)
        self._install_edit = QLineEdit()
        self._install_edit.setPlaceholderText("e.g. /home/you/Games/Hearthstone")
        self._install_browse = QPushButton("Browse…")
        self._install_browse.setFixedWidth(90)
        self._install_browse.clicked.connect(self._browse_install)
        dir_row.addWidget(self._install_edit)
        dir_row.addWidget(self._install_browse)
        layout.addLayout(dir_row)
        opt = QHBoxLayout()
        opt.setSpacing(20)
        rc = QVBoxLayout()
        rc.setSpacing(4)
        rc.addWidget(_section_label("Region"))
        self._region_combo = QComboBox()
        for r in Region:
            self._region_combo.addItem(r.label, userData=r.value)
        self._region_combo.setFixedWidth(140)
        rc.addWidget(self._region_combo)
        opt.addLayout(rc)
        mc = QVBoxLayout()
        mc.setSpacing(4)
        mc.addWidget(_section_label("macOS Install Source  (optional)"))
        mr = QHBoxLayout()
        mr.setSpacing(6)
        self._macos_edit = QLineEdit()
        self._macos_edit.setPlaceholderText(
            "Skip download — use existing /Applications/Hearthstone"
        )
        self._macos_browse = QPushButton("Browse…")
        self._macos_browse.setFixedWidth(90)
        self._macos_browse.clicked.connect(self._browse_macos)
        mr.addWidget(self._macos_edit)
        mr.addWidget(self._macos_browse)
        mc.addLayout(mr)
        opt.addLayout(mc, stretch=1)
        layout.addLayout(opt)
        field = f"QLineEdit{{background:#0d1117;color:{CLR_TEXT};border:1px solid {CLR_BORDER};border-radius:4px;padding:5px 8px;font-size:12px;}}QLineEdit:disabled{{color:{CLR_TEXT_MUTED};}}"
        combo = f"QComboBox{{background:#0d1117;color:{CLR_TEXT};border:1px solid {CLR_BORDER};border-radius:4px;padding:5px 8px;font-size:12px;}}QComboBox::drop-down{{border:none;width:24px;}}QComboBox QAbstractItemView{{background:#111d2b;color:{CLR_TEXT};border:1px solid {CLR_BORDER};}}"
        browse = f"QPushButton{{background:{CLR_PANEL};color:{CLR_TEXT_MUTED};border:1px solid {CLR_BORDER};border-radius:4px;padding:5px 8px;font-size:12px;}}QPushButton:hover{{background:#1a2f45;color:{CLR_TEXT};}}"
        self._install_edit.setStyleSheet(field)
        self._macos_edit.setStyleSheet(field)
        self._region_combo.setStyleSheet(combo)
        self._install_browse.setStyleSheet(browse)
        self._macos_browse.setStyleSheet(browse)
        s = config.settings
        self._install_edit.setText(s.install_dir)
        for i in range(self._region_combo.count()):
            if self._region_combo.itemData(i) == s.region:
                self._region_combo.setCurrentIndex(i)
                break
        self._macos_edit.setText(s.macos_install_path)

    def get_install_dir(self):
        return self._install_edit.text().strip()

    def get_region(self):
        return self._region_combo.currentData()

    def get_macos_path(self):
        return self._macos_edit.text().strip()

    def set_enabled(self, e):
        for w in (
            self._install_edit,
            self._install_browse,
            self._region_combo,
            self._macos_edit,
            self._macos_browse,
        ):
            w.setEnabled(e)

    def _browse_install(self):
        p = QFileDialog.getExistingDirectory(
            self,
            "Select Install Directory",
            self._install_edit.text() or str(Path.home()),
        )
        if p:
            self._install_edit.setText(p)

    def _browse_macos(self):
        p = QFileDialog.getExistingDirectory(
            self,
            "Select macOS Hearthstone Folder",
            self._macos_edit.text() or str(Path.home()),
        )
        if p:
            self._macos_edit.setText(p)


class ActionBar(QWidget):
    install_requested = pyqtSignal()
    update_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "install"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)
        pc = QVBoxLayout()
        pc.setSpacing(3)
        self._progress_label = QLabel("")
        self._progress_label.setStyleSheet(f"color:{CLR_TEXT_MUTED};font-size:11px;")
        self._progress = QProgressBar()
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setStyleSheet(
            f"QProgressBar{{background:{CLR_BORDER};border:none;border-radius:3px;}}QProgressBar::chunk{{background:{CLR_ACCENT};border-radius:3px;}}"
        )
        pc.addWidget(self._progress_label)
        pc.addWidget(self._progress)
        pc.addStretch()
        layout.addLayout(pc, stretch=1)
        self._cancel_btn = QPushButton("✕  Cancel")
        self._cancel_btn.setFixedSize(110, 36)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.setStyleSheet(
            f"QPushButton{{background:{CLR_BTN_CANCEL};color:{CLR_TEXT_MUTED};border:1px solid {CLR_BORDER};border-radius:4px;font-size:13px;}}QPushButton:hover{{background:{CLR_BTN_CANCEL_HOVER};color:{CLR_TEXT};}}"
        )
        self._action_btn = QPushButton("⬇  Install")
        self._action_btn.setFixedSize(170, 36)
        self._action_btn.clicked.connect(self._clicked)
        self._action_btn.setStyleSheet(
            f"QPushButton{{background:{CLR_BTN_PRIMARY};color:#fff;border:none;border-radius:4px;font-size:13px;font-weight:600;}}QPushButton:hover{{background:{CLR_BTN_HOVER};}}QPushButton:disabled{{background:#374151;color:{CLR_TEXT_MUTED};}}"
        )
        layout.addWidget(self._cancel_btn)
        layout.addWidget(self._action_btn)

    def set_mode_install(self):
        self._mode = "install"
        self._progress.setVisible(False)
        self._action_btn.setText("⬇  Install")
        self._action_btn.setVisible(True)
        self._cancel_btn.setVisible(False)
        self._action_btn.setEnabled(True)

    def set_mode_update(self):
        self._mode = "update"
        self._progress.setVisible(False)
        self._action_btn.setText("↑  Check for Updates")
        self._action_btn.setVisible(True)
        self._cancel_btn.setVisible(False)
        self._action_btn.setEnabled(True)

    def set_mode_running(self):
        self._mode = "running"
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)
        self._action_btn.setVisible(False)
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)

    def set_mode_done(self, success):
        self._progress.setRange(0, 100)
        self._progress.setValue(100 if success else 0)
        self._action_btn.setVisible(True)
        self._cancel_btn.setVisible(False)
        self._action_btn.setEnabled(True)

    def update_progress(self, c, t, l):
        if t > 0:
            self._progress.setRange(0, t)
            self._progress.setValue(c)
        self._progress_label.setText(l)

    def _clicked(self):
        if self._mode == "update":
            self.update_requested.emit()
        else:
            self.install_requested.emit()


class InstallPage(QWidget):
    install_complete = pyqtSignal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._thread = None
        self._worker = None
        self._cancel_event = threading.Event()
        self._sys_info = SystemInfo.detect()
        self._build_ui()
        self.setStyleSheet(f"background-color:{CLR_BG};")
        self._refresh_action_mode()
        self._dep_banner.populate(self._sys_info)

    @property
    def log_widget(self):
        return self._log

    def refresh(self):
        self._refresh_action_mode()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        title = QLabel("Install / Update")
        title.setStyleSheet(f"color:{CLR_TEXT};font-size:18px;font-weight:700;")
        root.addWidget(title)
        self._dep_banner = DepWarningBanner()
        root.addWidget(self._dep_banner)
        root.addWidget(_hline())
        self._config_panel = ConfigPanel(self._cfg)
        root.addWidget(self._config_panel)
        root.addWidget(_hline())
        self._step_indicator = StepIndicator(STEPS)
        root.addWidget(self._step_indicator)
        root.addWidget(_hline())
        self._step_label = QLabel("Ready.")
        self._step_label.setStyleSheet(
            f"color:{CLR_TEXT_MUTED};font-size:11px;font-style:italic;"
        )
        root.addWidget(self._step_label)
        lh = QHBoxLayout()
        lh.addWidget(_section_label("Output"))
        lh.addStretch()
        root.addLayout(lh)
        self._log = LogWidget()
        self._log.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self._log, stretch=1)
        self._action_bar = ActionBar()
        self._action_bar.install_requested.connect(self._on_install)
        self._action_bar.update_requested.connect(self._on_update)
        self._action_bar.cancel_requested.connect(self._on_cancel)
        root.addWidget(self._action_bar)

    def _refresh_action_mode(self):
        state = self._cfg.get_install_state()
        if state.is_installed:
            self._action_bar.set_mode_update()
        else:
            self._action_bar.set_mode_install()

    def _save_config(self):
        s = self._cfg.settings
        s.install_dir = self._config_panel.get_install_dir()
        s.region = self._config_panel.get_region()
        s.macos_install_path = self._config_panel.get_macos_path()
        self._cfg.save()

    def _start_worker(self, mode):
        if self._thread and self._thread.isRunning():
            return
        self._save_config()
        self._cancel_event.clear()
        self._log.clear()
        self._step_indicator.reset()
        self._step_label.setText("Starting…")
        self._config_panel.set_enabled(False)
        self._action_bar.set_mode_running()
        self._thread = QThread()
        self._worker = InstallerWorker(self._cfg, mode, self._cancel_event)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_line.connect(self._on_log_line)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @pyqtSlot()
    def _on_install(self):
        if not self._sys_info.all_clear:
            r = QMessageBox.question(
                self,
                "Missing Dependencies",
                "Some required tools or libraries appear to be missing.\n"
                "The installation may fail. Continue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self._start_worker("install")

    @pyqtSlot()
    def _on_update(self):
        self._start_worker("update")

    @pyqtSlot()
    def _on_cancel(self):
        self._log.append_line("Cancellation requested…", LogLevel.WARNING)
        self._cancel_event.set()
        self._action_bar._cancel_btn.setEnabled(False)

    @pyqtSlot(str, str)
    def _on_log_line(self, text, level_value):
        try:
            level = LogLevel(level_value)
        except ValueError:
            level = LogLevel.INFO
        self._log.append_line(text, level)

    @pyqtSlot(int, int, str)
    def _on_progress(self, current, total, label):
        self._action_bar.update_progress(current, total, label)
        self._step_label.setText(f"Step {current + 1}/{total}: {label}")
        if 0 <= current < total:
            self._step_indicator.set_step(current)

    @pyqtSlot()
    def _on_finished(self):
        self._log.append_line("✓ Operation completed successfully.", LogLevel.SUCCESS)
        self._step_indicator.complete()
        self._step_label.setText("Complete ✓")
        self._action_bar.set_mode_done(success=True)
        self._config_panel.set_enabled(True)
        self._refresh_action_mode()
        self.install_complete.emit()

    @pyqtSlot(str)
    def _on_failed(self, message):
        self._log.append_line(f"error: {message}", LogLevel.ERROR)
        self._step_label.setText("Failed — see log for details.")
        self._action_bar.set_mode_done(success=False)
        self._config_panel.set_enabled(True)
        self._refresh_action_mode()
        QMessageBox.critical(
            self,
            "Installation Failed",
            f"The installation encountered an error:\n\n{message}\n\n"
            "Check the output log for details.",
        )

    @pyqtSlot()
    def _on_cancelled(self):
        self._log.append_line("Installation cancelled.", LogLevel.WARNING)
        self._step_label.setText("Cancelled.")
        self._action_bar.set_mode_done(success=False)
        self._config_panel.set_enabled(True)
        self._refresh_action_mode()
