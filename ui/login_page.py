"""
login_page.py — Hearthstone Linux Launcher

The key problem: Battle.net redirects to http://localhost:0/?ST=<token>
after login. Port 0 is on Chromium's hard-blocked port list, so the
request is rejected with ERR_UNSAFE_PORT *before* acceptNavigationRequest
ever fires.

Fix: use a QWebEngineUrlRequestInterceptor, which runs at the network
layer before Chromium's port blacklist is applied. We intercept the
localhost:0 request there, extract the token from the URL, and block
the request so the error page is never shown.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineProfile,
        QWebEngineSettings,
        QWebEngineUrlRequestInfo,
        QWebEngineUrlRequestInterceptor,
    )
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_AVAILABLE = True
except ImportError:
    _WEBENGINE_AVAILABLE = False
    QWebEnginePage = object  # type: ignore[assignment,misc]
    QWebEngineProfile = object  # type: ignore[assignment]
    QWebEngineSettings = object  # type: ignore[assignment]
    QWebEngineUrlRequestInfo = object  # type: ignore[assignment]
    QWebEngineUrlRequestInterceptor = object  # type: ignore[assignment,misc]
    QWebEngineView = QWidget  # type: ignore[assignment,misc]

from launcher.config import ConfigManager
from launcher.login import (
    REGION_LOGIN_URLS,
    extract_token_from_url,
    is_token_redirect,
    read_token_from_config,
    token_appears_valid,
    write_token,
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


# ---------------------------------------------------------------------------
# Request interceptor — fires BEFORE Chromium's port blacklist
# ---------------------------------------------------------------------------


class TokenRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """
    Intercepts all outgoing web requests from the login browser.
    When a localhost:0 (or wtcg://) redirect is detected, the token
    is extracted and the request is blocked so no error page is shown.

    Signal:
        token_url_intercepted(str) — the full redirect URL string
    """

    # Can't use pyqtSignal on a non-QObject subclass easily, so we use
    # a callback instead.
    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback  # callable(url_str: str)

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url_str = info.requestUrl().toString()
        if is_token_redirect(url_str):
            # Block the request so Chromium never tries to fetch it
            info.block(True)
            # Fire the callback on the main thread via the URL string
            self._callback(url_str)


# ---------------------------------------------------------------------------
# Browser toolbar
# ---------------------------------------------------------------------------


class BrowserToolbar(QWidget):
    reload_requested = pyqtSignal()
    back_requested = pyqtSignal()
    region_changed = pyqtSignal(str)

    def __init__(self, current_region: str, parent=None):
        super().__init__(parent)
        self._current_region = current_region
        self._build_ui()
        self._apply_styles()

    def set_url(self, url: str):
        self._url_label.setText(url)

    def set_loading(self, loading: bool):
        self._reload_btn.setText("✕" if loading else "↻")

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._back_btn = QPushButton("←")
        self._back_btn.setFixedSize(28, 28)
        self._back_btn.setToolTip("Back")
        self._back_btn.clicked.connect(self.back_requested)

        self._reload_btn = QPushButton("↻")
        self._reload_btn.setFixedSize(28, 28)
        self._reload_btn.setToolTip("Reload")
        self._reload_btn.clicked.connect(self.reload_requested)

        self._url_label = QLabel()
        self._url_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._url_label.setTextFormat(Qt.TextFormat.PlainText)
        self._url_label.setStyleSheet(
            f"color:{CLR_TEXT_MUTED};font-size:11px;padding:0 6px;"
            f"background:#0d1117;border:1px solid {CLR_BORDER};border-radius:3px;"
        )

        regions = [("🌎 US", "us"), ("🌍 EU", "eu"), ("🌏 KR", "asia")]
        self._region_btns: dict[str, QPushButton] = {}
        for label, val in regions:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setCheckable(True)
            btn.setChecked(val == self._current_region)
            btn.clicked.connect(lambda _, v=val: self._on_region_clicked(v))
            self._region_btns[val] = btn

        layout.addWidget(self._back_btn)
        layout.addWidget(self._reload_btn)
        layout.addWidget(self._url_label, stretch=1)
        for btn in self._region_btns.values():
            layout.addWidget(btn)

    def _apply_styles(self):
        self.setStyleSheet(
            f"background:{CLR_PANEL};border-bottom:1px solid {CLR_BORDER};"
        )
        nav = (
            f"QPushButton{{background:#1e293b;color:{CLR_TEXT_MUTED};"
            f"border:1px solid {CLR_BORDER};border-radius:4px;font-size:14px;}}"
            f"QPushButton:hover{{background:#263548;color:{CLR_TEXT};}}"
        )
        self._back_btn.setStyleSheet(nav)
        self._reload_btn.setStyleSheet(nav)
        reg = (
            f"QPushButton{{background:#1e293b;color:{CLR_TEXT_MUTED};"
            f"border:1px solid {CLR_BORDER};border-radius:4px;font-size:11px;padding:0 8px;}}"
            f"QPushButton:hover{{background:#263548;color:{CLR_TEXT};}}"
            f"QPushButton:checked{{background:{CLR_ACCENT_DIM}55;color:{CLR_ACCENT};"
            f"border-color:{CLR_ACCENT_DIM};}}"
        )
        for btn in self._region_btns.values():
            btn.setStyleSheet(reg)

    def _on_region_clicked(self, region: str):
        for val, btn in self._region_btns.items():
            btn.setChecked(val == region)
        self._current_region = region
        self.region_changed.emit(region)


# ---------------------------------------------------------------------------
# Status banner
# ---------------------------------------------------------------------------


class TokenStatusBanner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self.set_idle()

    def set_idle(self):
        self._show(
            "🔑",
            "Log in with your Battle.net account to generate a token.",
            CLR_TEXT_MUTED,
        )

    def set_success(self, preview: str):
        self._show("✓", f"Token saved successfully.  Preview: {preview}", CLR_OK)

    def set_error(self, msg: str):
        self._show("✕", f"Login failed: {msg}", CLR_ERR)

    def set_existing(self, preview: str):
        self._show(
            "●",
            f"Existing token found: {preview}  —  Log in again to refresh.",
            CLR_WARN,
        )

    def set_loading(self):
        self._show("…", "Loading Battle.net login page…", CLR_TEXT_MUTED)

    def _show(self, icon: str, text: str, colour: str):
        self._icon.setText(icon)
        self._icon.setStyleSheet(
            f"color:{colour};font-size:14px;background:transparent;"
        )
        self._text.setText(text)
        self._text.setStyleSheet(
            f"color:{colour};font-size:12px;background:transparent;"
        )

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        self._icon = QLabel()
        self._icon.setFixedWidth(18)
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text = QLabel()
        self._text.setWordWrap(True)
        self._text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._icon)
        layout.addWidget(self._text, stretch=1)
        self.setStyleSheet(
            f"QWidget{{background:{CLR_PANEL};border-bottom:1px solid {CLR_BORDER};}}"
        )


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


class LoginPage(QWidget):
    """
    Full Login page. Only instantiated by app.py when _WEBENGINE_AVAILABLE.

    Signals:
        token_saved(str) — emitted after token is written to disk.
    """

    token_saved = pyqtSignal(str)

    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._cfg = config
        self._current_region = config.settings.region
        self._build_ui()
        self._apply_styles()
        self._check_existing_token()

    def navigate_to_login(self, clear_cookies: bool = False):
        """Navigate to the Battle.net login page for the current region.

        Pass clear_cookies=True to force a fresh login form (e.g. after
        a successful token save, so the user can log in as a different
        account or refresh an expired token).
        """
        url = REGION_LOGIN_URLS.get(self._current_region, REGION_LOGIN_URLS["us"])
        self._status.set_loading()
        if clear_cookies:
            # Clear cookies so Battle.net shows the login form rather than
            # auto-redirecting with the existing session.
            store = self._profile.cookieStore()
            if store:
                store.deleteAllCookies()
        self._view.load(QUrl(url))

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        self._status = TokenStatusBanner()
        root.addWidget(self._status)

        self._toolbar = BrowserToolbar(self._current_region)
        self._toolbar.back_requested.connect(self._on_back)
        self._toolbar.reload_requested.connect(self._on_reload)
        self._toolbar.region_changed.connect(self._on_region_changed)
        root.addWidget(self._toolbar)

        # Profile with persistent cookies so login survives restarts
        self._profile = QWebEngineProfile("hs-launcher-login", self)
        self._profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
        )

        # Install the request interceptor on the profile — this fires
        # before Chromium's port blacklist, so localhost:0 is caught here.
        self._interceptor = TokenRequestInterceptor(
            self._on_token_url_intercepted, self
        )
        self._profile.setUrlRequestInterceptor(self._interceptor)

        self._page = QWebEnginePage(self._profile, self)

        self._view = QWebEngineView(self)
        self._view.setPage(self._page)
        self._view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._view.urlChanged.connect(lambda u: self._toolbar.set_url(u.toString()))
        self._view.loadStarted.connect(lambda: self._toolbar.set_loading(True))
        self._view.loadFinished.connect(lambda _: self._toolbar.set_loading(False))

        s = self._page.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)

        root.addWidget(self._view, stretch=1)
        root.addWidget(self._build_action_bar())

    def _build_header(self):
        w = QWidget()
        layout = QHBoxLayout(w)
        layout.setContentsMargins(24, 16, 24, 12)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel("Battle.net Login")
        title.setStyleSheet(f"color:{CLR_TEXT};font-size:18px;font-weight:700;")
        sub = QLabel("Your token is stored locally and never sent to any third party.")
        sub.setStyleSheet(f"color:{CLR_TEXT_MUTED};font-size:12px;")
        col.addWidget(title)
        col.addWidget(sub)
        layout.addLayout(col)
        layout.addStretch()
        w.setStyleSheet(f"background:{CLR_BG};")
        return w

    def _build_action_bar(self):
        w = QWidget()
        w.setFixedHeight(52)
        layout = QHBoxLayout(w)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(10)
        note = QLabel(
            "Log in above — the token will be captured automatically after login."
        )
        note.setStyleSheet(f"color:{CLR_TEXT_MUTED};font-size:11px;")
        note.setWordWrap(True)
        btn = QPushButton("↻  Reload Login Page")
        btn.setFixedHeight(34)
        btn.clicked.connect(lambda: self.navigate_to_login(clear_cookies=True))
        btn.setStyleSheet(
            f"QPushButton{{background:#1e3a5f;color:{CLR_TEXT};"
            f"border:1px solid {CLR_BORDER};border-radius:4px;"
            f"font-size:12px;padding:0 14px;}}"
            f"QPushButton:hover{{background:#254d7a;}}"
        )
        layout.addWidget(note, stretch=1)
        layout.addWidget(btn)
        w.setStyleSheet(
            f"QWidget{{background:{CLR_PANEL};border-top:1px solid {CLR_BORDER};}}"
        )
        return w

    def _apply_styles(self):
        self.setStyleSheet(f"background:{CLR_BG};")

    def _check_existing_token(self):
        existing = read_token_from_config(self._cfg.settings.install_path)
        if existing and token_appears_valid(existing):
            self._status.set_existing(_token_preview(existing))
        else:
            self._status.set_idle()

    def _save_token(self, token: str):
        try:
            write_token(token, self._cfg.settings.install_path)
        except (ValueError, OSError, ImportError) as exc:
            self._status.set_error(str(exc))
            return
        self._cfg.save()
        self._status.set_success(_token_preview(token))
        self.token_saved.emit(token)
        # After saving, reload with fresh cookies so user can log in again
        # if they want to switch accounts or refresh the token.
        self.navigate_to_login(clear_cookies=True)

    # ------------------------------------------------------------------ #
    # Called by the interceptor callback (may be on a non-GUI thread,    #
    # so we route through invokeMethod for safety)                        #
    # ------------------------------------------------------------------ #

    def _on_token_url_intercepted(self, url_str: str):
        from PyQt6.QtCore import Q_ARG, QMetaObject, Qt

        QMetaObject.invokeMethod(
            self,
            "_handle_token_url",
            Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, url_str),
        )

    @pyqtSlot(str)
    def _handle_token_url(self, url_str: str):
        token = extract_token_from_url(url_str)
        if token and token_appears_valid(token):
            self._save_token(token)
        else:
            self._status.set_error(
                f"Could not extract a valid token from redirect URL.\n"
                f"URL: {url_str[:120]}{'…' if len(url_str) > 120 else ''}"
            )

    @pyqtSlot()
    def _on_back(self):
        if self._view.history().canGoBack():
            self._view.back()

    @pyqtSlot()
    def _on_reload(self):
        self._view.reload()

    @pyqtSlot(str)
    def _on_region_changed(self, region: str):
        self._current_region = region
        self._cfg.settings.region = region
        self._cfg.save()
        self.navigate_to_login()

    def showEvent(self, event):
        super().showEvent(event)
        if self._view.url().isEmpty() or self._view.url() == QUrl("about:blank"):
            self.navigate_to_login()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_preview(token: str) -> str:
    t = token.strip()
    return t if len(t) <= 16 else f"{t[:8]}…{t[-6:]}"
