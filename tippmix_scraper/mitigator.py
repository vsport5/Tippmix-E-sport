from __future__ import annotations

import asyncio
from typing import Optional
from loguru import logger
import httpx

from .config import ACTIVE_PROXY_FILE
from .blocker import choose_mitigation

PROXY_SOURCES = [
    # Curated lists
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/https.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    # ProxyScrape
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&proxy_format=protocolipport&format=text&timeout=6000&country=hu",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=6000&country=HU&anonymity=Elite",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=https&timeout=6000&country=HU&anonymity=Elite",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=socks5&timeout=8000&country=HU&anonymity=Elite",
    # Proxy-List.download
    "https://www.proxy-list.download/api/v1/get?type=http&country=HU",
    "https://www.proxy-list.download/api/v1/get?type=https&country=HU",
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
                            # Guess protocol from source
                            if "socks5" in u:
                                s = "socks5://" + s
                            elif "socks4" in u:
                                s = "socks4://" + s
                            else:
                                s = "http://" + s
                        res.append(s)
            except Exception:
                pass
    # deduplicate preserving order
    seen = set()
    uniq: list[str] = []
    for p in res:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq[:1200]


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
    batch = 30
    for i in range(0, len(cands), batch):
        sub = cands[i:i+batch]
        checks = await asyncio.gather(*[is_hu(p) for p in sub])
        for p, ok in zip(sub, checks):
            if ok:
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
