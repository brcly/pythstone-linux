"""
config.py — Hearthstone Linux Launcher
Configuration, paths, and persisted settings.

Settings are stored in ~/.config/hs-launcher/settings.json
The install directory defaults to ~/Games/Hearthstone
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Region(str, Enum):
    US = "us"
    EU = "eu"
    ASIA = "asia"

    @property
    def label(self) -> str:
        return {"us": "Americas", "eu": "Europe", "asia": "Asia"}[self.value]

    @classmethod
    def from_str(cls, value: str) -> "Region":
        try:
            return cls(value.lower())
        except ValueError:
            return cls.US


class DisplayServer(str, Enum):
    """Detected display server — affects env-var workarounds."""

    X11 = "x11"
    WAYLAND = "wayland"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Wayland workaround options (mirrors the FAQ in the upstream README)
# ---------------------------------------------------------------------------


class WaylandWorkaround(str, Enum):
    NONE = "none"
    DISABLE_DMABUF = "WEBKIT_DISABLE_DMABUF_RENDERER"
    DISABLE_EXPLICIT_SYNC = "__NV_DISABLE_EXPLICIT_SYNC"


# ---------------------------------------------------------------------------
# Fixed / derived paths (not user-configurable)
# ---------------------------------------------------------------------------

# Where we store launcher config + logs
CONFIG_DIR: Path = Path.home() / ".config" / "pythstone-launcher"
SETTINGS_FILE: Path = CONFIG_DIR / "settings.json"
LAUNCHER_LOG_FILE: Path = CONFIG_DIR / "launcher.log"


# Relative paths *inside* the install directory
REL_BINARY = Path("Bin") / "Hearthstone.x86_64"
REL_TOKEN = Path("token")
REL_CLIENT_CONFIG = Path("client.config")
REL_NGDP_CACHE = Path(".ngdp")
REL_LOGS_DIR = Path("Bin") / "Logs"
REL_VERSION_FILE = (
    Path("Bin") / "Hearthstone_Data" / "app.info"
)  # contains build version

# Directory where keg venv lives
KEG_DIR: Path = CONFIG_DIR / "keg-env"

# Unity engine files are downloaded to ~/Unity by the upstream script;
# we keep the same default so users with an existing setup aren't broken.
DEFAULT_UNITY_DIR: Path = Path.home() / "Unity"


# ---------------------------------------------------------------------------
# Persisted settings dataclass
# ---------------------------------------------------------------------------


@dataclass
class LauncherSettings:
    """
    All user-configurable settings.  Serialised to / from JSON automatically.
    Only plain types and enums are used so (de)serialisation stays trivial.
    """

    # --- Core ---
    install_dir: str = str(Path.home() / "Games" / "Hearthstone")
    region: str = Region.US.value
    unity_dir: str = str(DEFAULT_UNITY_DIR)

    # --- Login ---
    # Last Battle.net username used (display only — never store passwords)
    last_username: str = ""

    # --- Wayland ---
    wayland_workaround: str = WaylandWorkaround.NONE.value

    # --- Launch options ---
    extra_env_vars: dict[str, str] = field(default_factory=dict)
    """Arbitrary extra environment variables injected at launch time."""

    launch_args: list[str] = field(default_factory=list)
    """Extra CLI arguments appended to the Hearthstone binary."""

    # --- Install source ---
    # If the user has a local macOS Hearthstone folder they want to use
    # instead of downloading, they can specify it here.
    macos_install_path: str = ""

    # --- Misc ---
    check_for_updates_on_launch: bool = True
    show_advanced_settings: bool = False

    # ------------------------------------------------------------------ #
    # Derived / convenience properties                                    #
    # ------------------------------------------------------------------ #

    @property
    def install_path(self) -> Path:
        return Path(self.install_dir)

    @property
    def binary_path(self) -> Path:
        return self.install_path / REL_BINARY

    @property
    def token_path(self) -> Path:
        return self.install_path / REL_TOKEN

    @property
    def client_config_path(self) -> Path:
        return self.install_path / REL_CLIENT_CONFIG

    @property
    def ngdp_cache_path(self) -> Path:
        return self.install_path / REL_NGDP_CACHE

    @property
    def game_logs_path(self) -> Path:
        return self.install_path / REL_LOGS_DIR

    @property
    def region_enum(self) -> Region:
        return Region.from_str(self.region)

    @property
    def wayland_workaround_enum(self) -> WaylandWorkaround:
        try:
            return WaylandWorkaround(self.wayland_workaround)
        except ValueError:
            return WaylandWorkaround.NONE

    @property
    def macos_install_path_or_none(self) -> Optional[Path]:
        p = self.macos_install_path.strip()
        return Path(p) if p else None

    @property
    def unity_path(self) -> Path:
        return Path(self.unity_dir)

    # ------------------------------------------------------------------ #
    # Serialisation                                                       #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LauncherSettings":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Install-state detection
# ---------------------------------------------------------------------------


@dataclass
class InstallState:
    """
    A snapshot of what is (and isn't) present on disk for a given install dir.
    Computed fresh each time — never cached.
    """

    install_dir: Path

    @property
    def is_installed(self) -> bool:
        """True when the game binary exists."""
        return (self.install_dir / REL_BINARY).is_file()

    @property
    def has_token(self) -> bool:
        """True when a non-empty token file exists."""
        t = self.install_dir / REL_TOKEN
        return t.is_file() and t.stat().st_size > 0

    @property
    def has_client_config(self) -> bool:
        return (self.install_dir / REL_CLIENT_CONFIG).is_file()

    @property
    def installed_version(self) -> Optional[str]:
        """
        Returns the installed version string if readable, else None.
        Checks (in order):
          1. .version file written by ngdp install (most reliable)
          2. app.info file in the game data directory
        """
        # Primary: .version file written by our installer after ngdp install
        version_file = self.install_dir / ".version"
        if version_file.is_file():
            val = version_file.read_text(encoding="utf-8").strip()
            if val:
                return val

        # Fallback: app.info contains lines like: Hearthstone\n30.2.0.12345
        vf = self.install_dir / REL_VERSION_FILE
        try:
            lines = vf.read_text(encoding="utf-8").splitlines()
            return lines[1].strip() if len(lines) >= 2 else lines[0].strip()
        except (OSError, IndexError):
            return None

    @property
    def ngdp_cache_size_bytes(self) -> int:
        """Disk usage of the .ngdp cache directory in bytes."""
        cache = self.install_dir / REL_NGDP_CACHE
        if not cache.is_dir():
            return 0
        total = 0
        for dirpath, _, filenames in os.walk(cache):
            for fname in filenames:
                try:
                    total += (Path(dirpath) / fname).stat().st_size
                except OSError:
                    pass
        return total

    @property
    def ngdp_cache_size_human(self) -> str:
        return _human_bytes(self.ngdp_cache_size_bytes)

    def as_dict(self) -> dict:
        return {
            "is_installed": self.is_installed,
            "has_token": self.has_token,
            "has_client_config": self.has_client_config,
            "installed_version": self.installed_version,
            "ngdp_cache_size": self.ngdp_cache_size_human,
        }


# ---------------------------------------------------------------------------
# System / environment detection
# ---------------------------------------------------------------------------


@dataclass
class SystemInfo:
    """Detected system capabilities. Used to pre-fill settings and show warnings."""

    display_server: DisplayServer = DisplayServer.UNKNOWN
    has_gcc: bool = False
    has_git: bool = False
    has_curl: bool = False
    has_python3: bool = False
    missing_libs: list[str] = field(default_factory=list)
    """System libraries that the upstream project requires but appear absent."""

    @classmethod
    def detect(cls) -> "SystemInfo":
        info = cls()

        # Display server
        xdg = os.environ.get("XDG_SESSION_TYPE", "").lower()
        wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
        if xdg == "wayland" or wayland_display:
            info.display_server = DisplayServer.WAYLAND
        elif xdg == "x11" or os.environ.get("DISPLAY"):
            info.display_server = DisplayServer.X11

        # CLI tools
        info.has_gcc = _cmd_exists("gcc")
        info.has_git = _cmd_exists("git")
        info.has_curl = _cmd_exists("curl")
        info.has_python3 = _cmd_exists("python3")

        # Required shared libraries.
        # pkg-config is tried first; if no .pc file exists (e.g. crypto++ on
        # Arch ships the library but no .pc), we fall back to header detection
        # via _header_exists() and library detection via _lib_exists().
        lib_checks = [
            {
                "pkg_names": ["cryptopp", "libcrypto++", "crypto++"],
                "headers": ["cryptopp/aes.h", "crypto++/aes.h"],
                "lib_names": ["libcryptopp.so", "libcrypto++.so"],
                "display": "libcrypto++ (libcrypto++-dev / crypto++ / cryptopp-devel)",
            },
            {
                "pkg_names": ["webkit2gtk-4.1", "webkit2gtk-4.0", "webkit2gtk"],
                "headers": ["webkit2/webkit2.h"],
                "lib_names": ["libwebkit2gtk-4.1.so", "libwebkit2gtk-4.0.so"],
                "display": "WebKit2GTK (libwebkit2gtk-4.1-dev / webkit2gtk / webkit2gtk3-devel)",
            },
        ]
        for spec in lib_checks:
            found = (
                any(_pkg_config_exists(p) for p in spec["pkg_names"])
                or any(_header_exists(h) for h in spec["headers"])
                or any(_lib_exists(l) for l in spec["lib_names"])
            )
            if not found:
                info.missing_libs.append(spec["display"])

        return info

    @property
    def is_wayland(self) -> bool:
        return self.display_server == DisplayServer.WAYLAND

    @property
    def suggested_wayland_workaround(self) -> WaylandWorkaround:
        """
        Heuristic: NVIDIA drivers are more likely to need the explicit-sync
        workaround; everything else benefits from disabling dma-buf.
        """
        if not self.is_wayland:
            return WaylandWorkaround.NONE
        gpu = _detect_gpu_vendor()
        if gpu == "nvidia":
            return WaylandWorkaround.DISABLE_EXPLICIT_SYNC
        return WaylandWorkaround.DISABLE_DMABUF

    @property
    def missing_required_tools(self) -> list[str]:
        missing = []
        if not self.has_gcc:
            missing.append("gcc (build-essential / base-devel)")
        if not self.has_git:
            missing.append("git")
        if not self.has_curl:
            missing.append("curl")
        if not self.has_python3:
            missing.append("python3")
        return missing

    @property
    def all_clear(self) -> bool:
        return not self.missing_required_tools and not self.missing_libs


# ---------------------------------------------------------------------------
# Config manager  (load / save / singleton access)
# ---------------------------------------------------------------------------


class ConfigManager:
    """
    Manages loading and saving of LauncherSettings.

    Usage:
        cfg = ConfigManager.load()
        cfg.settings.region = Region.EU.value
        cfg.save()
    """

    def __init__(self, settings: LauncherSettings) -> None:
        self._settings = settings

    @property
    def settings(self) -> LauncherSettings:
        return self._settings

    # -- Persistence --

    @classmethod
    def load(cls) -> "ConfigManager":
        """Load settings from disk, or return defaults if no file exists yet."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if SETTINGS_FILE.is_file():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                settings = LauncherSettings.from_dict(data)
                return cls(settings)
            except (json.JSONDecodeError, TypeError):
                # Corrupted settings — fall back to defaults
                pass
        return cls(LauncherSettings())

    def save(self) -> None:
        """Persist current settings to disk."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(self._settings.to_dict(), indent=2),
            encoding="utf-8",
        )

    def reset_to_defaults(self) -> None:
        self._settings = LauncherSettings()
        self.save()

    # -- Convenience helpers --

    def get_install_state(self) -> InstallState:
        return InstallState(self._settings.install_path)

    def build_launch_env(self) -> dict[str, str]:
        """
        Build the environment dict to use when launching the game.
        Starts from the current process environment, injects Wayland
        workarounds and any user-defined extra vars.
        """
        env = os.environ.copy()

        workaround = self._settings.wayland_workaround_enum
        if workaround != WaylandWorkaround.NONE:
            env[workaround.value] = "1"

        env.update(self._settings.extra_env_vars)
        return env


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cmd_exists(cmd: str) -> bool:
    """Return True if `cmd` is found on PATH."""
    try:
        subprocess.run(
            ["which", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _pkg_config_exists(pkg: str) -> bool:
    """Return True if pkg-config knows about `pkg`."""
    try:
        subprocess.run(
            ["pkg-config", "--exists", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _header_exists(header: str) -> bool:
    """
    Return True if a C/C++ header is findable in standard include paths.
    Covers /usr/include, /usr/local/include, and any paths in CPATH.
    """
    import os

    search_dirs = [
        "/usr/include",
        "/usr/local/include",
        "/usr/include/x86_64-linux-gnu",
    ]
    # Also respect CPATH / C_INCLUDE_PATH environment variables
    for env_var in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH"):
        val = os.environ.get(env_var, "")
        if val:
            search_dirs.extend(val.split(":"))

    from pathlib import Path

    for d in search_dirs:
        if (Path(d) / header).is_file():
            return True
    return False


def _lib_exists(libname: str) -> bool:
    """
    Return True if a shared library is findable by ldconfig or in standard
    library paths.  Handles both exact names and prefix matching.
    """
    import os

    # Try ldconfig cache first (fastest, most reliable)
    try:
        result = subprocess.run(
            ["ldconfig", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if libname in result.stdout:
            return True
    except FileNotFoundError:
        pass

    # Fall back to scanning common library directories
    search_dirs = [
        "/usr/lib",
        "/usr/local/lib",
        "/usr/lib64",
        "/usr/local/lib64",
        "/usr/lib/x86_64-linux-gnu",
    ]
    # Also check LD_LIBRARY_PATH
    ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    if ld_path:
        search_dirs.extend(ld_path.split(":"))

    from pathlib import Path

    for d in search_dirs:
        base = Path(d)
        if not base.is_dir():
            continue
        # Exact match or starts-with match (e.g. libcryptopp.so.8)
        for f in base.iterdir():
            if f.name == libname or f.name.startswith(libname):
                return True
    return False


def _detect_gpu_vendor() -> str:
    """Best-effort GPU vendor detection. Returns 'nvidia', 'amd', 'intel', or ''."""
    try:
        out = subprocess.check_output(
            ["lspci"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        low = out.lower()
        if "nvidia" in low:
            return "nvidia"
        if "amd" in low or "radeon" in low:
            return "amd"
        if "intel" in low:
            return "intel"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return ""


def _human_bytes(n: float) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cfg = ConfigManager.load()
    s = cfg.settings
    print("=== LauncherSettings ===")
    print(json.dumps(s.to_dict(), indent=2))

    print("\n=== InstallState ===")
    state = cfg.get_install_state()
    print(json.dumps(state.as_dict(), indent=2))

    print("\n=== SystemInfo ===")
    info = SystemInfo.detect()
    print(f"  Display server     : {info.display_server.value}")
    print(f"  Missing tools      : {info.missing_required_tools or 'none'}")
    print(f"  Missing libs       : {info.missing_libs or 'none'}")
    print(f"  Suggested workaround: {info.suggested_wayland_workaround.value}")
    print(f"  All clear          : {info.all_clear}")
