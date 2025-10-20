from __future__ import annotations

import os
from typing import Optional, Dict


ACTIVE_PROXY_FILE = "/workspace/active_proxy.txt"


def get_proxy_from_env() -> Optional[str]:
    # Prefer HTTPS_PROXY, then HTTP_PROXY, then active proxy file
    val = os.getenv("PROXY_URL") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if val:
        return val
    try:
        if os.path.exists(ACTIVE_PROXY_FILE):
            with open(ACTIVE_PROXY_FILE, "r", encoding="utf-8") as f:
                line = f.read().strip()
                return line or None
    except Exception:
        return None
    return None


def get_playwright_proxy_settings() -> Optional[Dict[str, str]]:
    url = get_proxy_from_env()
    if not url:
        return None
    username = os.getenv("PROXY_USERNAME")
    password = os.getenv("PROXY_PASSWORD")
    settings: Dict[str, str] = {"server": url}
    if username and password:
        settings["username"] = username
        settings["password"] = password
    return settings


def get_httpx_proxy() -> Optional[dict]:
    url = get_proxy_from_env()
    if not url:
        return None
    # httpx expects mapping or str; support both http and https
    return {
        "http://": url,
        "https://": url,
    }
