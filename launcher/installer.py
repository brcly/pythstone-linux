"""
installer.py — Hearthstone Linux Launcher
Handles installation, assembly, and updates of the Linux Hearthstone client.

This is a Python reimplementation of the upstream craft.sh script, designed
to run in a background thread and emit progress updates to the UI via
callbacks rather than blocking.

Pipeline:
    1. Ensure tooling repo (hearthstone-linux) is cloned / up to date
    2. Set up Python venv + install keg (the Blizzard CDN downloader)
    3. Fetch the online game version for the selected region
    4. Download game files via keg  (or copy from a local macOS install)
    5. Query Unity release API → download + extract Linux engine binaries
    6. Build C stubs (CoreFoundation, OSXWindowManagement, blz_commerce)
    7. Assemble everything into the install directory
    8. Write client.config
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Callable, Optional

from launcher.config import (
    KEG_DIR,
    REL_BINARY,
    REL_CLIENT_CONFIG,
    REL_TOKEN,
    ConfigManager,
    InstallState,
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Callback signatures used to push progress to the UI:
#   LogCallback(message: str)            — a line of log output
#   ProgressCallback(current, total, label)  — for determinate progress bars
LogCallback = Callable[[str], None]
ProgressCallback = Callable[[int, int, str], None]


class InstallError(Exception):
    """Raised when any installation step fails unrecoverably."""


class InstallCancelled(Exception):
    """Raised when the user requests cancellation mid-install."""


# ---------------------------------------------------------------------------
# Step definitions  (used to report high-level stage to the UI)
# ---------------------------------------------------------------------------

STEPS = [
    "Setting up keg",
    "Checking game version",
    "Downloading game files",
    "Fetching Unity engine",
    "Building stubs",
    "Assembling install",
    "Writing configuration",
]


# ---------------------------------------------------------------------------
# URLs / constants
# ---------------------------------------------------------------------------

# Blizzard's NGDP (Next Generation Distribution Pipeline) endpoints
NGDP_BASE_URL = "http://us.patch.battle.net:1119"
NGDP_PRODUCT = "hsb"  # Hearthstone product code

REGION_NGDP_HOSTS = {
    "us": "us.patch.battle.net:1119",
    "eu": "eu.patch.battle.net:1119",
    "asia": "kr.patch.battle.net:1119",
}

# Unity release GraphQL endpoint (same one craft.sh uses)
UNITY_RELEASE_API = "https://services.api.unity.com/unity/editor/release/v1/releases"
UNITY_GRAPHQL_API = "https://release-graphql.services.api.unity.com/graphql"

# Relative paths inside the Unity tar that we need
UNITY_ENGINE_SUBPATH = "Editor/Data/PlaybackEngines/LinuxStandaloneSupport/Variations/linux64_player_nondevelopment_mono"

# client.config — flat key=value format (matches upstream hearthstone-linux repo).
# Aurora.Env tells the client which Battle.net server to connect to.
# Localization.Locale sets the in-game language.
REGION_SERVER_MAP = {
    "eu": "eu.actual.battle.net",
    "us": "us.actual.battle.net",
    "asia": "kr.actual.battle.net",
    "cn": "cn.actual.battle.net",
}
REGION_LOCALE_MAP = {
    "eu": "enGB",
    "us": "enUS",
    "asia": "koKR",
    "cn": "zhCN",
}


def _build_client_config(region: str) -> str:
    server = REGION_SERVER_MAP.get(region, "eu.actual.battle.net")
    locale = REGION_LOCALE_MAP.get(region, "enUS")
    return (
        f"Aurora.ClientCheck=false\n"
        f"Aurora.Env.Override=1\n"
        f"Aurora.Env={server}\n"
        f"Localization.Locale={locale}\n"
    )


# The three stub libraries that need to be compiled from the stubs/ dir
STUB_SOURCES = {
    "CoreFoundation": {
        "built": "CoreFoundation.so",  # actual Makefile output filename
        "output": "Bin/Hearthstone_Data/Plugins/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation.so",
    },
    "OSXWindowManagement": {
        "built": "libOSXWindowManagement.so",
        "output": "Bin/Hearthstone_Data/Plugins/libOSXWindowManagement.so",
    },
    "blz_commerce": {
        "built": "libblz_commerce_sdk_plugin.so",
        "output": "Bin/Hearthstone_Data/Plugins/libblz_commerce_sdk_plugin.so",
    },
}


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------


class Installer:
    """
    Orchestrates the full install / update pipeline.

    Designed to run entirely in a background thread.  The UI hands it two
    callbacks and a cancel event, then calls run_install() or run_update().

    Example (pseudocode):
        cancel = threading.Event()
        installer = Installer(config_manager, log_cb, progress_cb, cancel)
        threading.Thread(target=installer.run_install, daemon=True).start()
    """

    def __init__(
        self,
        config: ConfigManager,
        log_cb: LogCallback,
        progress_cb: ProgressCallback,
        cancel_event: Optional[Event] = None,
    ) -> None:
        self._cfg = config
        self._log = log_cb
        self._prog = progress_cb
        self._cancel = cancel_event or Event()

    # ------------------------------------------------------------------ #
    # Public entry points                                                 #
    # ------------------------------------------------------------------ #

    def run_install(self) -> None:
        """Full fresh install pipeline."""
        self._log("=== Hearthstone Linux Installer ===")
        steps = [
            self._step_prepare_tooling,
            self._step_check_version,
            self._step_download_game,
            self._step_fetch_unity,
            self._step_build_stubs,
            self._step_assemble,
            self._step_write_config,
        ]
        self._run_steps(steps)
        self._log("\n✓ Installation complete! Log in to continue.")

    def run_update(self) -> None:
        """Update an existing installation to the latest version."""
        self._log("=== Checking for Hearthstone updates ===")
        steps = [
            self._step_prepare_tooling,
            self._step_check_version,
            self._step_download_game,  # keg only fetches changed files
            self._step_assemble,
            self._step_write_config,
        ]
        self._run_steps(steps)
        self._log("\n✓ Update complete!")

    # ------------------------------------------------------------------ #
    # Step runner                                                         #
    # ------------------------------------------------------------------ #

    def _run_steps(self, steps: list) -> None:
        total = len(steps)
        for i, step in enumerate(steps):
            self._check_cancel()
            label = STEPS[i] if i < len(STEPS) else step.__name__
            self._prog(i, total, label)
            self._log(f"\n── Step {i + 1}/{total}: {label} ──")
            step()
        self._prog(total, total, "Done")

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise InstallCancelled("Installation cancelled by user.")

    # ------------------------------------------------------------------ #
    # Step 1 — Prepare tooling                                           #
    # ------------------------------------------------------------------ #

    def _step_prepare_tooling(self) -> None:
        """Set up a Python venv and install keg (the ngdp downloader) into it."""
        venv_dir = KEG_DIR
        ngdp_bin = venv_dir / "bin" / "ngdp"

        if ngdp_bin.is_file():
            self._log(f"keg already installed at {ngdp_bin}")
            return

        self._log(f"Creating Python venv for keg at {venv_dir}…")
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        if venv_dir.is_dir():
            shutil.rmtree(venv_dir)
        self._run([sys.executable, "-m", "venv", str(venv_dir)])

        pip = venv_dir / "bin" / "pip"
        self._log("Installing keg from GitHub…")
        self._run(
            [str(pip), "install", "--quiet", "git+https://github.com/0xf4b1/keg.git"]
        )
        self._log("✓ keg installed successfully.")

    # ------------------------------------------------------------------ #
    # Step 2 — Check game version                                         #
    # ------------------------------------------------------------------ #

    def _step_check_version(self) -> None:
        """Fetch the current online version from Blizzard's CDN."""
        region = self._cfg.settings.region
        host = REGION_NGDP_HOSTS.get(region, REGION_NGDP_HOSTS["us"])
        url = f"http://{host}/{NGDP_PRODUCT}/versions"

        self._log(f"Fetching version info from Blizzard CDN ({region.upper()})…")
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                content = resp.read().decode("utf-8")
        except Exception as exc:
            raise InstallError(f"Failed to fetch version info: {exc}") from exc

        version = self._parse_ngdp_version(content)
        if not version:
            raise InstallError("Could not parse version from CDN response.")

        self._log(f"Online version: {version}")

        # Compare with installed version (if any)
        state = self._cfg.get_install_state()
        installed = state.installed_version
        if installed:
            self._log(f"Installed version: {installed}")
            if installed == version:
                self._log("Already up to date.")
            else:
                self._log(f"Update available: {installed} → {version}")
        else:
            self._log("No existing installation detected.")

        # Stash for later steps
        self._online_version = version

    @staticmethod
    def _parse_ngdp_version(content: str) -> Optional[str]:
        """
        Parse the NGDP versions response.

        Format (pipe-delimited, columns annotated with !TYPE):
            Region!STRING:0|BuildConfig!HEX:16|...|BuildId!DEC:4|VersionsName!String:0|...
            ## seqn = 3663363
            us|4d8a35be...|...|239422|35.0.3.239422.238087|...
            eu|4d8a35be...|...|239422|35.0.3.239422.238087|...

        We prefer VersionsName (full dotted version) over BuildId (bare int).
        We strip the !TYPE suffix from header column names before matching.
        """
        header_cols: list[str] = []
        version_col: int = -1

        for line in content.splitlines():
            stripped = line.strip()
            # Skip blank lines and comment lines (## seqn = ...)
            if not stripped or stripped.startswith("#"):
                continue

            parts = stripped.split("|")

            if not header_cols:
                # First non-comment line is the header.
                # Strip type annotations: "BuildId!DEC:4" -> "BuildId"
                header_cols = [c.split("!")[0] for c in parts]
                # Prefer VersionsName, fall back to BuildId
                for preferred in ("VersionsName", "BuildId"):
                    if preferred in header_cols:
                        version_col = header_cols.index(preferred)
                        break
                continue

            # Data row — return the version from the first data row
            if version_col >= 0 and version_col < len(parts):
                val = parts[version_col].strip()
                if val:
                    return val

        return None

    # ------------------------------------------------------------------ #
    # Step 3 — Download game files                                        #
    # ------------------------------------------------------------------ #

    def _step_download_game(self) -> None:
        """
        Either copy from a local macOS install or download via keg.
        keg outputs to <install_dir>/.ngdp and then extracts into place.
        """
        settings = self._cfg.settings
        macos_src = settings.macos_install_path_or_none
        install = settings.install_path
        region = settings.region

        install.mkdir(parents=True, exist_ok=True)

        if macos_src and macos_src.is_dir():
            self._log(f"Using local macOS install: {macos_src}")
            self._copy_macos_install(macos_src, install)
        else:
            self._log("Downloading game files via keg (this will take a while)…")
            self._run_keg(install, region)

    def _copy_macos_install(self, src: Path, dst: Path) -> None:
        """Mirror a macOS Hearthstone folder into the install directory."""
        self._log(f"Copying {src} → {dst} …")
        # We copy the Contents/Resources/Data subtree which holds game assets
        data_src = src / "Hearthstone.app" / "Contents" / "Resources" / "Data"
        if not data_src.is_dir():
            # Flat layout (older versions)
            data_src = src
        shutil.copytree(
            str(data_src), str(dst / "Bin" / "Hearthstone_Data"), dirs_exist_ok=True
        )
        self._log("Copy complete.")

    def _run_keg(self, install_dir: Path, region: str) -> None:
        """
        Download and install Hearthstone via the ngdp CLI tool.

        ngdp requires initialisation before use. The full sequence is:
            ngdp init
            ngdp remote add <url>
            ngdp --cdn <cdn> fetch <url> --tags OSX --tags <locale> --tags Production
            ngdp install <url> <version> --tags OSX --tags <locale> --tags Production

        ngdp uses CWD as its working directory — must be run from install_dir.
        The .ngdp/ subdirectory is created there by `ngdp init`.
        """
        ngdp_bin = KEG_DIR / "bin" / "ngdp"
        if not ngdp_bin.is_file():
            raise InstallError(
                f"ngdp binary not found at {ngdp_bin}. "
                "Ensure keg was installed correctly in step 1."
            )

        host = REGION_NGDP_HOSTS.get(region, REGION_NGDP_HOSTS["us"])
        url = f"http://{host}/{NGDP_PRODUCT}"

        # CN region uses a different CDN
        if region == "cn":
            cdn = "https://blzdist-hs.necdn.leihuo.netease.com/tpr/hs"
        else:
            cdn = "http://level3.blizzard.com/tpr/hs"

        locale = "enUS"
        ngdp = [str(ngdp_bin)]
        online_version = getattr(self, "_online_version", None)

        # ── Smart skip: if already up to date, do nothing ────────────────
        version_file = install_dir / ".version"
        if online_version and version_file.is_file():
            if version_file.read_text().strip() == online_version:
                self._log(
                    f"Game files already up to date ({online_version}). "
                    "Skipping download."
                )
                return

        # Step 1: initialise the ngdp database (creates .ngdp/ with SQLite db)
        # Safe to run again on an existing install — it's idempotent.
        self._log("Initialising ngdp database…")
        self._run(ngdp + ["init"], cwd=str(install_dir))

        # Step 2: register the remote — ignore "already exists" error
        self._log(f"Adding remote {url}…")
        try:
            self._run(ngdp + ["remote", "add", url], cwd=str(install_dir))
        except InstallError:
            self._log("Remote already registered, continuing…")

        # Step 3: fetch all game files from the CDN
        self._log(f"Fetching game files from CDN ({cdn})…")
        self._run(
            ngdp
            + [
                "--cdn",
                cdn,
                "fetch",
                url,
                "--tags",
                "OSX",
                "--tags",
                locale,
                "--tags",
                "Production",
            ],
            cwd=str(install_dir),
        )

        # Step 4: install (extract) fetched files into the install directory
        version = getattr(self, "_online_version", None)
        if not version:
            raise InstallError("Online version not set — cannot run ngdp install.")

        self._log(f"Installing game files (version {version})…")
        self._run(
            ngdp
            + [
                "install",
                url,
                version,
                "--tags",
                "OSX",
                "--tags",
                locale,
                "--tags",
                "Production",
            ],
            cwd=str(install_dir),
        )

        # Write the version file so future runs can detect the installed version
        (install_dir / ".version").write_text(version)

    # ------------------------------------------------------------------ #
    # Step 4 — Fetch Unity Linux engine                                  #
    # ------------------------------------------------------------------ #

    def _step_fetch_unity(self) -> None:
        """
        Determine which Unity version the game uses, then download the
        Linux standalone player from Unity's CDN if not already present.
        """
        settings = self._cfg.settings
        install_dir = settings.install_path
        unity_dir = settings.unity_path

        unity_ver = self._read_unity_version(install_dir)
        if not unity_ver:
            raise InstallError(
                "Could not determine Unity version from game files. "
                "Ensure the game files were downloaded successfully in step 3."
            )
        self._log(f"Game uses Unity {unity_ver}")

        engine_dst = unity_dir / unity_ver
        linux_player = engine_dst / "LinuxPlayer"

        if linux_player.is_file():
            self._log(f"Unity Linux player already present at {engine_dst}")
        else:
            self._log(f"Fetching Unity {unity_ver} Linux standalone player…")
            download_url = self._resolve_unity_download_url(unity_ver)
            self._download_unity(download_url, engine_dst, unity_ver)

        # Copy Unity engine files into the install
        self._log("Installing Unity engine files…")
        self._install_unity_files(engine_dst, install_dir)

        self._unity_version = unity_ver

    @staticmethod
    def _read_unity_version(install_dir: Path) -> Optional[str]:
        """
        Read the Unity version the game requires.

        craft.sh uses:
            strings "Bin/Hearthstone_Data/level0" | head -n 1

        We replicate that: scan level0 for the first printable ASCII string
        that looks like a Unity version (e.g. "2021.3.16f1").

        Fallbacks:
          - .unity file written by a previous install
          - globalgamemanagers binary scan
        """
        # Fallback 1: .unity file written by a previous run
        unity_file = install_dir / ".unity"
        if unity_file.is_file():
            val = unity_file.read_text().strip()
            if val:
                return val

        # Primary: scan level0 for Unity version string (matches craft.sh)
        # The game is installed as a Mac .app bundle; level0 is inside Resources/Data/
        level0 = (
            install_dir
            / "Hearthstone.app"
            / "Contents"
            / "Resources"
            / "Data"
            / "level0"
        )
        if not level0.is_file():
            # Fallback legacy path
            level0 = install_dir / "Bin" / "Hearthstone_Data" / "level0"
        if level0.is_file():
            try:
                data = level0.read_bytes()
                # Extract printable ASCII strings (like `strings` command)
                # Unity version is the first string: e.g. "2021.3.16f1"
                strings_found = re.findall(rb"[ -~]{4,}", data)
                for s in strings_found:
                    decoded = s.decode("ascii", errors="ignore").strip()
                    if re.match(r"\d{4}\.\d+\.\d+[a-z]\d+", decoded):
                        return decoded
            except OSError:
                pass

        # Fallback 2: scan globalgamemanagers
        ggm = (
            install_dir
            / "Hearthstone.app"
            / "Contents"
            / "Resources"
            / "Data"
            / "globalgamemanagers"
        )
        if not ggm.is_file():
            ggm = install_dir / "Bin" / "Hearthstone_Data" / "globalgamemanagers"
        if ggm.is_file():
            try:
                data = ggm.read_bytes()
                match = re.search(rb"(\d{4}\.\d+\.\d+[a-z]\d+)", data)
                if match:
                    return match.group(1).decode()
            except OSError:
                pass

        return None

    def _resolve_unity_download_url(self, unity_ver: str) -> str:
        """
        Query Unity's GraphQL API to find the download hash for a specific
        version, then construct the CDN URL — exactly as craft.sh does.
        """
        payload = json.dumps(
            {
                "operationName": "GetRelease",
                "variables": {"version": unity_ver, "limit": 300},
                "query": (
                    "query GetRelease($limit: Int, $skip: Int, $version: String!, "
                    "$stream: [UnityReleaseStream!]) {\n"
                    "  getUnityReleases(\n"
                    "    limit: $limit\n    skip: $skip\n    stream: $stream\n"
                    "    version: $version\n    entitlements: [XLTS]\n"
                    "  ) {\n    totalCount\n    edges {\n      node {\n"
                    "        version\n        entitlements\n        releaseDate\n"
                    "        unityHubDeepLink\n        stream\n        __typename\n"
                    "      }\n      __typename\n    }\n    __typename\n  }\n}"
                ),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            UNITY_GRAPHQL_API,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as exc:
            raise InstallError(f"Unity API request failed: {exc}") from exc

        # Extract the unityHubDeepLink, which contains the hash
        # Format: unityhub://<version>/<hash>
        try:
            edges = data["data"]["getUnityReleases"]["edges"]
            for edge in edges:
                deep_link = edge["node"].get("unityHubDeepLink", "")
                m = re.search(rf"unityhub://{re.escape(unity_ver)}/(\w+)", deep_link)
                if m:
                    hash_val = m.group(1)
                    url = (
                        f"https://download.unity3d.com/download_unity/"
                        f"{hash_val}/LinuxEditorInstaller/Unity.tar.xz"
                    )
                    self._log(f"Unity download URL resolved: {url}")
                    return url
        except (KeyError, TypeError) as exc:
            raise InstallError(
                f"Unexpected Unity API response structure: {exc}"
            ) from exc

        raise InstallError(f"Unity version {unity_ver} not found in Unity release API.")

    def _download_unity(self, url: str, dest_dir: Path, unity_ver: str) -> None:
        """Download Unity.tar.xz and extract only the files we need."""
        dest_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as tmp:
            tar_path = Path(tmp) / "Unity.tar.xz"
            self._log(f"Downloading Unity editor ({url}) …")
            self._download_file(url, tar_path)

            self._log("Extracting Unity Linux player files…")
            engine_prefix = UNITY_ENGINE_SUBPATH
            needed = [
                f"{engine_prefix}/LinuxPlayer",
                f"{engine_prefix}/UnityPlayer.so",
                f"{engine_prefix}/Data/MonoBleedingEdge/",
            ]
            with tarfile.open(tar_path, "r:xz") as tf:
                members = [
                    m
                    for m in tf.getmembers()
                    if any(m.name.startswith(n) for n in needed)
                ]
                self._log(f"Extracting {len(members)} members…")
                tf.extractall(path=tmp, members=members)

            # Flatten: move from the long prefix path into dest_dir
            extracted_root = Path(tmp) / engine_prefix
            if extracted_root.is_dir():
                shutil.copytree(str(extracted_root), str(dest_dir), dirs_exist_ok=True)
            else:
                raise InstallError(
                    f"Expected extracted Unity path not found: {extracted_root}"
                )

        self._log(f"Unity engine saved to {dest_dir}")

    def _install_unity_files(self, engine_src: Path, install_dir: Path) -> None:
        """Copy Unity Linux player + Mono into the Hearthstone install tree."""
        bin_dir = install_dir / "Bin"
        bin_dir.mkdir(parents=True, exist_ok=True)

        linux_player_src = engine_src / "LinuxPlayer"
        linux_player_dst = bin_dir / "Hearthstone.x86_64"

        if not linux_player_src.is_file():
            raise InstallError(f"LinuxPlayer not found at {linux_player_src}")

        shutil.copy2(str(linux_player_src), str(linux_player_dst))
        linux_player_dst.chmod(linux_player_dst.stat().st_mode | 0o111)  # +x

        unity_player_src = engine_src / "UnityPlayer.so"
        if unity_player_src.is_file():
            shutil.copy2(str(unity_player_src), str(bin_dir / "UnityPlayer.so"))

        mono_src = engine_src / "Data" / "MonoBleedingEdge"
        # Unity looks for Mono at <data_dir>/MonoBleedingEdge, not at install root
        mono_dst = install_dir / "Bin" / "Hearthstone_Data" / "MonoBleedingEdge"
        if mono_src.is_dir():
            if mono_dst.exists():
                shutil.rmtree(str(mono_dst))
            shutil.copytree(str(mono_src), str(mono_dst))

        self._log("Unity engine files installed.")

    # ------------------------------------------------------------------ #
    # Step 5 — Build C stubs                                             #
    # ------------------------------------------------------------------ #

    def _step_build_stubs(self) -> None:
        """
        Compile the three stub shared libraries from the hearthstone-linux
        tooling repo using the Makefile (or falling back to direct gcc calls).
        """
        install_dir = self._cfg.settings.install_path
        # Bundled stubs shipped with the launcher
        stubs_dir = Path(__file__).parent.parent / "stubs"

        if not stubs_dir.is_dir():
            raise InstallError(
                f"Stubs source directory not found: {stubs_dir}\n"
                "This is a bug — please reinstall the launcher."
            )

        makefile = stubs_dir / "Makefile"
        if makefile.is_file():
            self._log("Building stubs via Makefile…")
            self._run(["make", "-C", str(stubs_dir)])
        else:
            self._log("No Makefile found, compiling stubs directly…")
            self._build_stubs_directly(stubs_dir)

        # Copy compiled stubs into the install directory
        self._log("Copying stubs into install directory…")
        for name, paths in STUB_SOURCES.items():
            src = stubs_dir / paths["built"]  # exact Makefile output name
            dst = install_dir / paths["output"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_file():
                shutil.copy2(str(src), str(dst))
                self._log(f"  Installed {name} stub → {dst.relative_to(install_dir)}")
            else:
                raise InstallError(
                    f"Expected stub binary not found after build: {src}\n"
                    f"Files present: {list(stubs_dir.glob('*.so'))}"
                )

    def _build_stubs_directly(self, stubs_dir: Path) -> None:
        """Fallback: compile each .c stub individually with gcc."""
        c_names = {
            "CoreFoundation": ("CoreFoundation.c", "CoreFoundation.so"),
            "OSXWindowManagement": (
                "OSXWindowManagement.c",
                "libOSXWindowManagement.so",
            ),
            "blz_commerce": (
                "blz_commerce_sdk_plugin.c",
                "libblz_commerce_sdk_plugin.so",
            ),
        }
        for name, (c_file, so_file) in c_names.items():
            src = stubs_dir / c_file
            out = stubs_dir / so_file
            if not src.is_file():
                raise InstallError(f"Stub source not found: {src}")
            self._log(f"  Compiling {c_file}…")
            self._run(
                [
                    "gcc",
                    "-shared",
                    "-fPIC",
                    "-o",
                    str(out),
                    str(src),
                    "-lcryptopp",
                ]
            )

    # ------------------------------------------------------------------ #
    # Step 6 — Assemble install                                          #
    # ------------------------------------------------------------------ #

    def _step_assemble(self) -> None:
        """
        Transform the raw Mac .app bundle into the flat Linux layout that
        the stubs and launcher expect.

        craft.sh transform_installation():
            Hearthstone.app/Contents/Resources/Data/  →  Bin/Hearthstone_Data/
            Hearthstone.app/Contents/MonoBleedingEdge/ → MonoBleedingEdge/
            Bin/Hearthstone_Data/MonoBleedingEdge/    → MonoBleedingEdge/  (if present)

        Expected final layout:
            install_dir/
            ├── Bin/
            │   ├── Hearthstone.x86_64       (Linux binary — from Unity step)
            │   ├── UnityPlayer.so            (from Unity step)
            │   └── Hearthstone_Data/         ← extracted from .app here
            │       ├── level0, globalgamemanagers, ...
            │       ├── Managed/
            │       ├── Plugins/              ← stubs go here
            │       └── ...
            ├── MonoBleedingEdge/             (moved out of Data)
            ├── Data/
            ├── Strings/
            ├── client.config
            └── token
        """
        install_dir = self._cfg.settings.install_path
        app_bundle = install_dir / "Hearthstone.app"
        data_src = app_bundle / "Contents" / "Resources" / "Data"
        data_dst = install_dir / "Bin" / "Hearthstone_Data"

        self._log("Assembling install directory layout…")

        # ── Transform Mac .app → flat Linux layout ──────────────────────
        if data_src.is_dir():
            self._log(f"  Extracting game data from Mac bundle → Bin/Hearthstone_Data/")
            data_dst.mkdir(parents=True, exist_ok=True)
            # Move every item from the Mac Data dir into Bin/Hearthstone_Data/
            for item in data_src.iterdir():
                dst_item = data_dst / item.name
                if dst_item.exists():
                    if dst_item.is_dir():
                        shutil.rmtree(dst_item)
                    else:
                        dst_item.unlink()
                shutil.move(str(item), str(data_dst))
            self._log(f"  Extraction complete → {data_dst}")
        elif data_dst.is_dir():
            self._log("  Bin/Hearthstone_Data already present, skipping extraction.")
        else:
            raise InstallError(
                f"Neither {data_src} nor {data_dst} exists. "
                "Game files may not have been downloaded correctly."
            )

        # ── MonoBleedingEdge stays inside Hearthstone_Data/ ────────────
        # Unity looks for Mono at Bin/Hearthstone_Data/MonoBleedingEdge/x86_64/
        # We do NOT move it to the install root (craft.sh does, but our Unity
        # step installs it directly into Hearthstone_Data/ so it's already right).
        mono_in_data = data_dst / "MonoBleedingEdge"
        mono_at_root = install_dir / "MonoBleedingEdge"

        if mono_at_root.is_dir() and not mono_in_data.is_dir():
            # Migrate from old layout: move from root into Hearthstone_Data/
            self._log("  Migrating MonoBleedingEdge → Bin/Hearthstone_Data/")
            shutil.move(str(mono_at_root), str(mono_in_data))
        elif mono_in_data.is_dir():
            self._log("  MonoBleedingEdge already in Bin/Hearthstone_Data/ ✓")
        else:
            self._log(
                "  WARNING: MonoBleedingEdge not found — game will fail to load mono!"
            )

        # ── Ensure plugin directories exist for stubs ────────────────────
        plugin_dir = data_dst / "Plugins"
        plugin_dir.mkdir(parents=True, exist_ok=True)
        cf_dir = (
            plugin_dir
            / "System"
            / "Library"
            / "Frameworks"
            / "CoreFoundation.framework"
        )
        cf_dir.mkdir(parents=True, exist_ok=True)

        # ── Extract 'unity default resources' before removing .app ─────
        # craft.sh: mv Hearthstone.app/Contents/Resources/'unity default resources'
        #               Bin/Hearthstone_Data/Resources/
        # This file contains built-in Unity shaders (incl. Internal-ErrorShader).
        # Without it the game segfaults immediately on startup.
        udr_src = app_bundle / "Contents" / "Resources" / "unity default resources"
        udr_dst = data_dst / "Resources" / "unity default resources"
        if udr_src.is_file():
            udr_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(udr_src), str(udr_dst))
            self._log(
                "  Moved 'unity default resources' → Bin/Hearthstone_Data/Resources/"
            )
        elif udr_dst.is_file():
            self._log("  'unity default resources' already in place.")
        else:
            self._log(
                "  WARNING: 'unity default resources' not found — game may crash on startup!"
            )

        # ── Clean up the now-empty .app bundle ───────────────────────────
        if app_bundle.is_dir():
            self._log("  Removing Mac .app bundle (no longer needed)…")
            shutil.rmtree(str(app_bundle))

        self._log("Assembly complete.")

    # ------------------------------------------------------------------ #
    # Step 7 — Write client.config                                       #
    # ------------------------------------------------------------------ #

    def _step_write_config(self) -> None:
        """Write client.config, .region, .locale, and ensure Data/DBF/ exists."""
        install_dir = self._cfg.settings.install_path
        settings = self._cfg.settings
        region = settings.region  # e.g. "eu", "us", "asia"

        locale = REGION_LOCALE_MAP.get(region, "enUS")

        # client.config — flat key=value format with region-specific server
        config_path = install_dir / REL_CLIENT_CONFIG
        config_path.write_text(_build_client_config(region), encoding="utf-8")
        self._log(f"Written {config_path} (region={region}, locale={locale})")

        # .region and .locale — read by the game for server/language selection
        (install_dir / ".region").write_text(region, encoding="utf-8")
        self._log(f"Written .region ({region})")
        (install_dir / ".locale").write_text(locale, encoding="utf-8")
        self._log(f"Written .locale ({locale})")

        # Data/DBF/ must exist — game writes its DB files here
        dbf_dir = install_dir / "Data" / "DBF"
        dbf_dir.mkdir(parents=True, exist_ok=True)
        self._log(f"Ensured {dbf_dir} exists")

        # Token placeholder check
        token_path = install_dir / REL_TOKEN
        if not token_path.is_file():
            self._log(
                "No token file present. Use the Login tab to authenticate "
                "before launching the game."
            )

    # ------------------------------------------------------------------ #
    # Subprocess helper                                                   #
    # ------------------------------------------------------------------ #

    def _run(
        self,
        cmd: list[str],
        cwd: Optional[str | Path] = None,
        env: Optional[dict] = None,
    ) -> None:
        """
        Run a subprocess, streaming stdout/stderr line-by-line to the log
        callback.  Raises InstallError on non-zero exit.
        """
        self._log(f"$ {' '.join(str(c) for c in cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self._check_cancel()
            self._log(line.rstrip())
        process.wait()
        if process.returncode != 0:
            raise InstallError(
                f"Command failed (exit {process.returncode}): "
                f"{' '.join(str(c) for c in cmd)}"
            )

    # ------------------------------------------------------------------ #
    # File download helper                                                #
    # ------------------------------------------------------------------ #

    def _download_file(
        self,
        url: str,
        dest: Path,
        chunk_size: int = 1024 * 256,
    ) -> None:
        """
        Download `url` to `dest`, emitting progress updates.
        Uses urllib so there are no extra dependencies.
        """
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    while True:
                        self._check_cancel()
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            self._prog(downloaded, total, f"Downloading {dest.name}")
        except Exception as exc:
            raise InstallError(f"Download failed ({url}): {exc}") from exc
        self._log(f"Downloaded {dest.name} ({_human_bytes(dest.stat().st_size)})")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
