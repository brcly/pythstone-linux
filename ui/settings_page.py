"""
settings_page.py — Hearthstone Linux Launcher
User-configurable settings page.

Sections:
  • Paths        — install dir, Unity dir
  • Game         — region, update check on launch
  • Wayland      — workaround selector + env var preview
  • Advanced     — extra env vars, extra launch args, ngdp cache management
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from launcher.config import (
    ConfigManager,
    DisplayServer,
    InstallState,
    Region,
    SystemInfo,
    WaylandWorkaround,
)

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
CLR_DANGER = "#7f1d1d"
CLR_DANGER_HOVER = "#991b1b"


# ---------------------------------------------------------------------------
# Shared widget helpers
# ---------------------------------------------------------------------------


def _section_header(text: str, subtitle: str = "") -> QWidget:
    """Gold-accented section heading with optional subtitle."""
    container = QWidget()
    col = QVBoxLayout(container)
    col.setContentsMargins(0, 16, 0, 4)
    col.setSpacing(2)

    title = QLabel(text)
    title.setStyleSheet(
        f"color: {CLR_ACCENT}; font-size: 12px; font-weight: 700; "
        f"letter-spacing: 1px; text-transform: uppercase;"
    )
    col.addWidget(title)

    if subtitle:
        sub = QLabel(subtitle)
        sub.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px;")
        sub.setWordWrap(True)
        col.addWidget(sub)

    return container


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {CLR_BORDER}; max-height: 1px; margin: 4px 0;")
    return line


def _field_style() -> str:
    return f"""
        QLineEdit {{
            background: #0d1117;
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            border-radius: 4px;
            padding: 5px 8px;
            font-size: 12px;
        }}
        QLineEdit:focus {{
            border-color: {CLR_ACCENT_DIM};
        }}
        QLineEdit:disabled {{
            color: {CLR_TEXT_MUTED};
            background: #0a0f18;
        }}
    """


def _browse_btn_style() -> str:
    return f"""
        QPushButton {{
            background: {CLR_PANEL};
            color: {CLR_TEXT_MUTED};
            border: 1px solid {CLR_BORDER};
            border-radius: 4px;
            padding: 5px 10px;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background: #1a2f45;
            color: {CLR_TEXT};
        }}
    """


def _primary_btn_style() -> str:
    return f"""
        QPushButton {{
            background: #1e3a5f;
            color: {CLR_TEXT};
            border: 1px solid {CLR_BORDER};
            border-radius: 4px;
            padding: 6px 16px;
            font-size: 12px;
            font-weight: 600;
        }}
        QPushButton:hover {{
            background: #254d7a;
        }}
    """


def _danger_btn_style() -> str:
    return f"""
        QPushButton {{
            background: {CLR_DANGER};
            color: #fca5a5;
            border: 1px solid #ef4444;
            border-radius: 4px;
            padding: 6px 16px;
            font-size: 12px;
        }}
        QPushButton:hover {{
            background: {CLR_DANGER_HOVER};
            color: #fee2e2;
        }}
    """


# ---------------------------------------------------------------------------
# Path row  (label + line edit + browse button)
# ---------------------------------------------------------------------------


class PathRow(QWidget):
    def __init__(
        self,
        label: str,
        placeholder: str = "",
        file_mode: bool = False,  # True = pick file, False = pick directory
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._file_mode = file_mode
        self._build(label, placeholder)

    def value(self) -> str:
        return self._edit.text().strip()

    def set_value(self, v: str) -> None:
        self._edit.setText(v)

    def _build(self, label: str, placeholder: str) -> None:
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 12px;")
        lbl.setFixedWidth(120)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(placeholder)
        self._edit.setStyleSheet(_field_style())

        btn = QPushButton("Browse…")
        btn.setFixedWidth(80)
        btn.setStyleSheet(_browse_btn_style())
        btn.clicked.connect(self._browse)

        grid.addWidget(lbl, 0, 0)
        grid.addWidget(self._edit, 0, 1)
        grid.addWidget(btn, 0, 2)
        grid.setColumnStretch(1, 1)

    def _browse(self) -> None:
        start = self._edit.text() or str(Path.home())
        if self._file_mode:
            path, _ = QFileDialog.getOpenFileName(self, "Select File", start)
        else:
            path = QFileDialog.getExistingDirectory(self, "Select Directory", start)
        if path:
            self._edit.setText(path)


# ---------------------------------------------------------------------------
# Wayland section
# ---------------------------------------------------------------------------


class WaylandSection(QWidget):
    def __init__(
        self,
        current: WaylandWorkaround,
        sys_info: SystemInfo,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._sys_info = sys_info
        self._build(current)

    def value(self) -> WaylandWorkaround:
        for w, rb in self._radios.items():
            if rb.isChecked():
                return w
        return WaylandWorkaround.NONE

    def _build(self, current: WaylandWorkaround) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Detection badge
        if self._sys_info.display_server == DisplayServer.WAYLAND:
            badge_text = "Wayland session detected"
            badge_colour = CLR_WARN
        elif self._sys_info.display_server == DisplayServer.X11:
            badge_text = "X11 session detected — workarounds unlikely needed"
            badge_colour = CLR_OK
        else:
            badge_text = "Display server unknown"
            badge_colour = CLR_TEXT_MUTED

        badge = QLabel(f"● {badge_text}")
        badge.setStyleSheet(f"color: {badge_colour}; font-size: 11px;")
        layout.addWidget(badge)

        # Suggested workaround hint
        suggested = self._sys_info.suggested_wayland_workaround
        if suggested != WaylandWorkaround.NONE:
            hint = QLabel(f"Suggested for your GPU: {suggested.value}")
            hint.setStyleSheet(
                f"color: {CLR_TEXT_MUTED}; font-size: 11px; font-style: italic;"
            )
            layout.addWidget(hint)

        # Radio buttons
        self._radios: dict[WaylandWorkaround, QRadioButton] = {}
        self._group = QButtonGroup(self)

        options = [
            (
                WaylandWorkaround.NONE,
                "None",
                "No workaround — use if the login tool works without one",
            ),
            (
                WaylandWorkaround.DISABLE_DMABUF,
                "WEBKIT_DISABLE_DMABUF_RENDERER=1",
                "Recommended for most Wayland setups (AMD/Intel)",
            ),
            (
                WaylandWorkaround.DISABLE_EXPLICIT_SYNC,
                "__NV_DISABLE_EXPLICIT_SYNC=1",
                "Recommended for NVIDIA + Wayland",
            ),
        ]

        for workaround, label, tip in options:
            rb = QRadioButton(label)
            rb.setChecked(workaround == current)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {CLR_TEXT};
                    font-size: 12px;
                    spacing: 8px;
                }}
                QRadioButton::indicator {{
                    width: 14px; height: 14px;
                    border: 1px solid {CLR_BORDER};
                    border-radius: 7px;
                    background: #0d1117;
                }}
                QRadioButton::indicator:checked {{
                    background: {CLR_ACCENT};
                    border-color: {CLR_ACCENT_DIM};
                }}
            """)
            rb.setToolTip(tip)
            self._group.addButton(rb)
            self._radios[workaround] = rb
            layout.addWidget(rb)

        # Env-var preview label
        self._preview = QLabel()
        self._preview.setStyleSheet(
            f"color: {CLR_TEXT_MUTED}; font-size: 11px; font-family: monospace;"
        )
        layout.addWidget(self._preview)
        self._group.buttonClicked.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self, *_) -> None:
        w = self.value()
        if w == WaylandWorkaround.NONE:
            self._preview.setText("No env var will be set.")
        else:
            self._preview.setText(f"Will set:  {w.value}=1")


# ---------------------------------------------------------------------------
# Extra env vars editor  (key=value, one per line)
# ---------------------------------------------------------------------------


class EnvVarEditor(QWidget):
    def __init__(
        self,
        current: dict[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._build(current)

    def value(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in self._edit.toPlainText().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k:
                    result[k] = v.strip()
        return result

    def _build(self, current: dict[str, str]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel("One KEY=VALUE per line. Lines starting with # are ignored.")
        hint.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(hint)

        initial = "\n".join(f"{k}={v}" for k, v in current.items())
        self._edit = QTextEdit()
        self._edit.setPlainText(initial)
        self._edit.setFixedHeight(80)
        self._edit.setStyleSheet(f"""
            QTextEdit {{
                background: #0d1117;
                color: {CLR_TEXT};
                border: 1px solid {CLR_BORDER};
                border-radius: 4px;
                padding: 6px;
                font-family: monospace;
                font-size: 12px;
            }}
        """)
        layout.addWidget(self._edit)


# ---------------------------------------------------------------------------
# Launch args editor
# ---------------------------------------------------------------------------


class LaunchArgsEditor(QWidget):
    def __init__(self, current: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build(current)

    def value(self) -> list[str]:
        return [a.strip() for a in self._edit.text().split() if a.strip()]

    def _build(self, current: list[str]) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        hint = QLabel("Extra arguments appended to Hearthstone.x86_64 at launch.")
        hint.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(hint)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText("e.g. -screen-width 2560 -screen-height 1440")
        self._edit.setText(" ".join(current))
        self._edit.setStyleSheet(_field_style())
        layout.addWidget(self._edit)


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------


class CacheSection(QWidget):
    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._build()
        self.refresh()

    def refresh(self) -> None:
        state = self._cfg.get_install_state()
        size = state.ngdp_cache_size_human
        self._size_lbl.setText(f"Current .ngdp cache size: {size}")

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._size_lbl = QLabel("Calculating…")
        self._size_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 12px;")

        clear_btn = QPushButton("Clear Cache")
        clear_btn.setStyleSheet(_danger_btn_style())
        clear_btn.setToolTip(
            "Deletes the .ngdp cache directory.\n"
            "The next update will re-download all changed files."
        )
        clear_btn.clicked.connect(self._on_clear)

        layout.addWidget(self._size_lbl, stretch=1)
        layout.addWidget(clear_btn)

    def _on_clear(self) -> None:
        reply = QMessageBox.question(
            self,
            "Clear .ngdp Cache?",
            "This will delete the .ngdp download cache.\n"
            "The next update will re-download all changed game files.\n\n"
            "Your installed game files will NOT be affected.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        cache_dir = self._cfg.settings.ngdp_cache_path
        if cache_dir.is_dir():
            import shutil

            try:
                shutil.rmtree(str(cache_dir))
                QMessageBox.information(
                    self, "Cache Cleared", "The .ngdp cache has been removed."
                )
            except OSError as exc:
                QMessageBox.critical(self, "Error", f"Could not clear cache:\n{exc}")
        else:
            QMessageBox.information(
                self, "Nothing to Clear", "No .ngdp cache directory found."
            )

        self.refresh()


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------


class SettingsPage(QWidget):
    """
    Full settings page.

    Signal:
        settings_saved — emitted after the user saves, so other pages
                         (e.g. install page) can re-read config.
    """

    settings_saved = pyqtSignal()

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = config
        self._sys_info = SystemInfo.detect()
        self._build_ui()
        self._apply_styles()
        self._populate()

    # ------------------------------------------------------------------ #
    # Public                                                              #
    # ------------------------------------------------------------------ #

    def refresh(self) -> None:
        self._cache_section.refresh()

    # ------------------------------------------------------------------ #
    # Build                                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # Outer layout just holds the scroll area
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Page title bar (outside the scroll)
        title_bar = QWidget()
        title_bar.setFixedHeight(56)
        title_bar.setStyleSheet(f"background: {CLR_BG};")
        tbl = QHBoxLayout(title_bar)
        tbl.setContentsMargins(24, 0, 24, 0)
        page_title = QLabel("Settings")
        page_title.setStyleSheet(
            f"color: {CLR_TEXT}; font-size: 18px; font-weight: 700;"
        )
        tbl.addWidget(page_title)
        tbl.addStretch()
        outer.addWidget(title_bar)
        outer.addWidget(_hline())

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {CLR_BG}; border: none; }}
            QScrollBar:vertical {{
                background: {CLR_BG}; width: 8px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {CLR_BORDER}; border-radius: 4px; min-height: 24px;
            }}
        """)

        content = QWidget()
        content.setStyleSheet(f"background: {CLR_BG};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 8, 24, 24)
        content_layout.setSpacing(0)

        # ── Paths ──────────────────────────────────────────────────────
        content_layout.addWidget(
            _section_header(
                "Paths",
                "Where the game is installed and where Unity engine files are cached.",
            )
        )
        self._install_path = PathRow(
            "Install Directory",
            placeholder=str(Path.home() / "Games" / "Hearthstone"),
        )
        self._unity_path = PathRow(
            "Unity Cache",
            placeholder=str(Path.home() / "Unity"),
        )
        content_layout.addWidget(self._install_path)
        content_layout.addWidget(self._unity_path)

        # ── Game ───────────────────────────────────────────────────────
        content_layout.addWidget(
            _section_header("Game", "Region and update behaviour.")
        )

        region_row = QWidget()
        region_layout = QHBoxLayout(region_row)
        region_layout.setContentsMargins(0, 0, 0, 0)
        region_layout.setSpacing(20)

        region_lbl = QLabel("Region")
        region_lbl.setFixedWidth(120)
        region_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 12px;")

        self._region_btns: dict[str, QRadioButton] = {}
        region_group = QButtonGroup(self)
        for r in Region:
            rb = QRadioButton(r.label)
            rb.setStyleSheet(f"""
                QRadioButton {{
                    color: {CLR_TEXT}; font-size: 12px; spacing: 8px;
                }}
                QRadioButton::indicator {{
                    width: 14px; height: 14px;
                    border: 1px solid {CLR_BORDER};
                    border-radius: 7px;
                    background: #0d1117;
                }}
                QRadioButton::indicator:checked {{
                    background: {CLR_ACCENT};
                    border-color: {CLR_ACCENT_DIM};
                }}
            """)
            region_group.addButton(rb)
            self._region_btns[r.value] = rb
            region_layout.addWidget(rb)
        region_layout.insertWidget(0, region_lbl)
        region_layout.addStretch()
        content_layout.addWidget(region_row)

        self._update_on_launch = QCheckBox("Check for game updates on launch")
        self._update_on_launch.setStyleSheet(f"""
            QCheckBox {{
                color: {CLR_TEXT}; font-size: 12px; spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {CLR_BORDER};
                border-radius: 3px;
                background: #0d1117;
            }}
            QCheckBox::indicator:checked {{
                background: {CLR_ACCENT};
                border-color: {CLR_ACCENT_DIM};
            }}
        """)
        content_layout.addWidget(self._update_on_launch)

        # ── Wayland ────────────────────────────────────────────────────
        content_layout.addWidget(
            _section_header(
                "Wayland",
                "Environment variable workarounds for the login browser on Wayland.",
            )
        )
        self._wayland = WaylandSection(
            self._cfg.settings.wayland_workaround_enum,
            self._sys_info,
        )
        content_layout.addWidget(self._wayland)

        # ── Advanced ───────────────────────────────────────────────────
        content_layout.addWidget(
            _section_header(
                "Advanced",
                "Extra environment variables and launch arguments injected at game start.",
            )
        )
        self._env_editor = EnvVarEditor(self._cfg.settings.extra_env_vars)
        self._args_editor = LaunchArgsEditor(self._cfg.settings.launch_args)
        content_layout.addWidget(
            self._labelled("Extra environment variables:", self._env_editor)
        )
        content_layout.addWidget(
            self._labelled("Extra launch arguments:", self._args_editor)
        )

        # ── Cache ──────────────────────────────────────────────────────
        content_layout.addWidget(
            _section_header(
                "Cache",
                "The .ngdp directory stores raw download files used by keg. "
                "It can grow large but speeds up incremental updates.",
            )
        )
        self._cache_section = CacheSection(self._cfg)
        content_layout.addWidget(self._cache_section)

        content_layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # ── Save bar ───────────────────────────────────────────────────
        save_bar = self._build_save_bar()
        outer.addWidget(save_bar)

    def _labelled(self, label_text: str, widget: QWidget) -> QWidget:
        """Wrap a widget with a label above it."""
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 4, 0, 0)
        col.setSpacing(4)
        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 11px;")
        col.addWidget(lbl)
        col.addWidget(widget)
        return container

    def _build_save_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(f"""
            QWidget {{
                background: {CLR_PANEL};
                border-top: 1px solid {CLR_BORDER};
            }}
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(10)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {CLR_TEXT_MUTED}; font-size: 12px;")

        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setStyleSheet(_danger_btn_style())
        reset_btn.clicked.connect(self._on_reset)

        save_btn = QPushButton("Save Settings")
        save_btn.setStyleSheet(_primary_btn_style())
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)

        layout.addWidget(self._status_lbl, stretch=1)
        layout.addWidget(reset_btn)
        layout.addWidget(save_btn)

        return bar

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"background: {CLR_BG};")

    # ------------------------------------------------------------------ #
    # Populate from config
    # ------------------------------------------------------------------ #

    def _populate(self) -> None:
        s = self._cfg.settings
        self._install_path.set_value(s.install_dir)
        self._unity_path.set_value(s.unity_dir)

        for val, rb in self._region_btns.items():
            rb.setChecked(val == s.region)

        self._update_on_launch.setChecked(s.check_for_updates_on_launch)

    # ------------------------------------------------------------------ #
    # Slots
    # ------------------------------------------------------------------ #

    def _on_save(self) -> None:
        s = self._cfg.settings

        s.install_dir = self._install_path.value() or s.install_dir
        s.unity_dir = self._unity_path.value() or s.unity_dir

        old_region = s.region
        for val, rb in self._region_btns.items():
            if rb.isChecked():
                s.region = val
                break
        region_changed = s.region != old_region

        s.check_for_updates_on_launch = self._update_on_launch.isChecked()
        s.wayland_workaround = self._wayland.value().value
        s.extra_env_vars = self._env_editor.value()
        s.launch_args = self._args_editor.value()

        self._cfg.save()

        # If region changed, rewrite client.config / .region / .locale
        if region_changed:
            self._apply_region(s.region, Path(s.install_dir))

        self._status_lbl.setText("✓  Settings saved.")
        self._status_lbl.setStyleSheet(f"color: {CLR_OK}; font-size: 12px;")
        self.settings_saved.emit()

    def _apply_region(self, region: str, install_dir: Path) -> None:
        """Rewrite region-sensitive config files when the region changes."""
        from launcher.installer import REGION_LOCALE_MAP, _build_client_config

        try:
            # client.config
            config_path = install_dir / "client.config"
            if config_path.parent.is_dir():
                config_path.write_text(_build_client_config(region), encoding="utf-8")
            # .region
            (install_dir / ".region").write_text(region, encoding="utf-8")
            # .locale
            locale = REGION_LOCALE_MAP.get(region, "enUS")
            (install_dir / ".locale").write_text(locale, encoding="utf-8")
            self._status_lbl.setText(
                f"✓  Settings saved. Region changed to {region.upper()} — "
                f"config files updated."
            )
        except OSError as exc:
            self._status_lbl.setText(
                f"⚠  Settings saved but config update failed: {exc}"
            )
            self._status_lbl.setStyleSheet(f"color: {CLR_WARN}; font-size: 12px;")

    def _on_reset(self) -> None:
        reply = QMessageBox.question(
            self,
            "Reset Settings?",
            "This will reset all settings to their defaults.\n"
            "Your installed game files will not be affected.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._cfg.reset_to_defaults()
        self._populate()
        self._status_lbl.setText("Settings reset to defaults.")
        self._status_lbl.setStyleSheet(f"color: {CLR_WARN}; font-size: 12px;")
        self.settings_saved.emit()
