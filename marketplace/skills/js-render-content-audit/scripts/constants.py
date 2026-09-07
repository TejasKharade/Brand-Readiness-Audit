#!/usr/bin/env python3
"""
Constants, configurations, and thresholds for js-render-content-audit.
Pure standard library. Zero external dependencies.
"""

import os
import sys

# User-Agent for Pass A simulating fast AI SearchBot crawler
BOT_UA = "Mozilla/5.0 (compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"

# Browser candidate binary names on system PATH
BROWSER_CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium",
    "chromium-browser", "chrome", "msedge", "microsoft-edge"
]

# Platform-specific browser installation search paths
WIN_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
]

MAC_PATHS = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
]

LINUX_PATHS = [
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/snap/bin/chromium"
]

# Headless browser flags for Pass B DOM hydration capture
HEADLESS_FLAGS = [
    "--headless",
    "--disable-gpu",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--blink-settings=imagesEnabled=false",
    "--disable-remote-fonts",
    "--disable-background-networking",
    "--disable-sync",
    "--mute-audio",
    "--dump-dom"
]

# Semantic parity & diagnostic thresholds
LATENCY_BUDGET_MS = 4500
SENTENCE_MIN_CHARS = 25
SENTENCE_MIN_WORDS = 4
PARAGRAPH_MIN_CHARS = 40
PARAGRAPH_MIN_WORDS = 6

PARITY_EMPTY_SHELL_THRESHOLD = 15.0
PARITY_CORE_GAP_THRESHOLD = 60.0
PARITY_PARTIAL_GAP_THRESHOLD = 88.0
