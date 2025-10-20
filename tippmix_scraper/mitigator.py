from __future__ import annotations

import asyncio
from typing import Optional
from loguru import logger
import httpx

from .config import ACTIVE_PROXY_FILE
from .blocker import choose_mitigation

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)

WHOAMI = "https://api.myip.com"


async def fetch_candidates() -> list[str]:
    async with httpx.AsyncClient() as client:
        res: list[str] = []
        for u in PROXY_SOURCES:
            try:
                r = await client.get(u, timeout=20)
                if r.status_code == 200:
                    for line in r.text.splitlines():
                        s = line.strip()
                        if not s:
                            continue
                        if "://" not in s:
                            s = "http://" + s
                        res.append(s)
            except Exception:
                pass
    return res[:500]


async def is_hu(proxy: str) -> bool:
    proxies = {"http://": proxy, "https://": proxy}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, proxies=proxies, timeout=6) as client:
            r = await client.get(WHOAMI)
            if r.status_code != 200:
                return False
            data = r.json()
            return (data.get("cc") or "").upper() == "HU"
    except Exception:
        return False


async def rotate_proxy() -> Optional[str]:
    cands = await fetch_candidates()
    # naive scan for HU
    for p in cands:
        if await is_hu(p):
            try:
                with open(ACTIVE_PROXY_FILE, "w", encoding="utf-8") as f:
                    f.write(p)
                logger.info("Activated proxy {}", p)
                return p
            except Exception:
                return None
    return None


async def auto_mitigate(block_type: str) -> Optional[str]:
    strat = choose_mitigation(block_type)
    if strat == "rotate_proxy_or_hu_exit":
        return await rotate_proxy()
    # for other strategies we could add implementations (e.g., backoff tuning)
    return None
