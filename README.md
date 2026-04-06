# Pythstone Linux

A native Linux launcher for Hearthstone, built with Python and PyQt6.

Pythstone handles the full install pipeline — downloading game files, fetching the Unity Linux engine, compiling compatibility stubs, and managing your Battle.net login token — all from a clean GUI. No Wine, no Battle.net desktop app required.

> **Note:** This project depends on [keg](https://github.com/0xf4b1/keg) for downloading game files from Blizzard's CDN. The in-game shop is not functional — this is a known limitation with no current workaround.

---

## Screenshots

![Screenshot1](https://github.com/brcly/brcly.github.io/blob/main/screenshots/Screenshot_20260406_101021.png)
![Screenshot2](https://github.com/brcly/brcly.github.io/blob/main/screenshots/Screenshot_20260406_101051.png)
![Screenshot3](https://github.com/brcly/brcly.github.io/blob/main/screenshots/Screenshot_20260406_101109.png)
![Screenshot4](https://github.com/brcly/brcly.github.io/blob/main/screenshots/Screenshot_20260406_101122.png)

---

## Requirements

### System packages

**Arch Linux / CachyOS / Manjaro**
```bash
sudo pacman -S base-devel crypto++ python python-virtualenv git
```

**Debian / Ubuntu**
```bash
sudo apt install build-essential libcrypto++-dev python3 python3-venv git
```

**Fedora**
```bash
sudo dnf install gcc gcc-c++ cryptopp-devel python3 python3-virtualenv git
```

### Python packages

```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `PyQt6` | GUI framework |
| `PyQt6-WebEngine` | Embedded browser for Battle.net login |
| `pycryptodome` | AES token encryption |

---

## Installation

```bash
git clone https://github.com/yourusername/pythstone-linux.git
cd pythstone-linux
pip install -r requirements.txt
python main.py
```

---

## Usage

### 1. Install the game

Go to the **Install** tab, set your install directory and region, then click **Install**. The launcher will:

- Download and set up [keg](https://github.com/0xf4b1/keg) (Blizzard's CDN downloader)
- Download the macOS Hearthstone game files (~11 GB)
- Download the matching Unity Linux standalone player
- Compile the compatibility stubs (`CoreFoundation`, `OSXWindowManagement`, `blz_commerce_sdk_plugin`)
- Assemble everything into the final Linux layout

### 2. Log in

Go to the **Login** tab and sign in with your Battle.net account. The launcher intercepts the authentication token automatically after login and saves it to your install directory.

### 3. Play

Click **▶ Play** on the home screen.

---

## How it works

Hearthstone is built on Unity, which supports Linux natively. The macOS game build uses the OpenGL Core renderer, which works on Linux too. Pythstone:

1. Downloads the **macOS game assets** from Blizzard's CDN (they contain all game data)
2. Pairs them with the **Unity Linux standalone player** binaries
3. Compiles small **C stub libraries** that replace macOS-only system frameworks (`CoreFoundation`, `OSXWindowManagement`) with Linux-compatible no-ops
4. The `CoreFoundation` stub reads an AES-encrypted `token` file to provide Battle.net authentication without the official launcher

This approach is identical to [hearthstone-linux](https://github.com/0xf4b1/hearthstone-linux) by 0xf4b1, which this project is based on. Pythstone reimplements the shell script pipeline as a Python/PyQt6 GUI application.

---

## Project structure

```
pythstone-linux/
├── main.py                  # Entry point
├── app.py                   # Application bootstrap and page wiring
├── requirements.txt
├── stubs/                   # C stub sources (compiled at install time)
│   ├── CoreFoundation.c
│   ├── OSXWindowManagement.c
│   ├── blz_commerce_sdk_plugin.c
│   └── Makefile
├── launcher/
│   ├── config.py            # Settings, paths, install state
│   ├── installer.py         # Full install/update pipeline
│   ├── login.py             # Token extraction and AES encryption
│   └── game.py              # Game process management
└── ui/
    ├── main_window.py       # Top-level window and sidebar navigation
    ├── home_page.py         # Play page with status and game log
    ├── install_page.py      # Install/update wizard with step indicators
    ├── login_page.py        # Embedded Battle.net OAuth browser
    ├── settings_page.py     # Configuration settings
    └── log_widget.py        # Reusable live log output widget
```

---

## Known limitations

- **In-game shop is not functional.** The shop requires `libcommerce_http_client`, a proprietary Blizzard library that is not included in the CDN download and cannot be stubbed.
- **Wayland + NVIDIA** may require a workaround. If the login page crashes, try setting `__NV_DISABLE_EXPLICIT_SYNC=1` in Settings → Wayland.
- This is an unofficial method. Use at your own risk — Blizzard could theoretically detect and action accounts using this approach, though no bans have been reported.

---

## Credits

- [0xf4b1/hearthstone-linux](https://github.com/0xf4b1/hearthstone-linux) — the original shell script implementation that this project is based on
- [0xf4b1/keg](https://github.com/0xf4b1/keg) — the Blizzard CDN downloader used to fetch game files

---
