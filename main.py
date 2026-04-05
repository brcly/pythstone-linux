#!/usr/bin/env python3
"""
main.py — Hearthstone Linux Launcher
Top-level entry point. Run this file to start the launcher.

    python main.py
"""

import sys
import os

# Ensure the project root is on sys.path so that absolute imports like
# `from launcher.config import ...` and `from ui.home_page import ...`
# resolve correctly regardless of the working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import run

if __name__ == "__main__":
    sys.exit(run(sys.argv))
