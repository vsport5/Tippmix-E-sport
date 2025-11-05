import asyncio
import sys
from typing import List, Optional
import httpx

CANDIDATE_SOURCES = [
    # ProxyScrape v2/v3 style endpoints (best-effort)
    "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&proxy_format=protocolipport&format=text&timeout=6000&country=hu",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=6000&country=HU&anonymity=Elite",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=https&timeout=6000&country=HU&anonymity=Elite",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=socks4&timeout=8000&country=HU&anonymity=Elite",
    "https://api.proxyscrape.com/?request=getproxies&proxytype=socks5&timeout=8000&country=HU&anonymity=Elite",
]

TEST_URL = "https://api.tippmix.hu/tippmix/search"
UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)


def normalize(lines: str) -> List[str]:
    out: List[str] = []
    for raw in lines.splitlines():
        s = raw.strip()
        if not s:
            continue
        # Some sources include protocol; keep as-is, else assume http
        if "socks5://" in s or "socks4://" in s or s.startswith("http://") or s.startswith("https://"):
            out.append(s)
        else:
            out.append("http://" + s)
    return out


async def fetch_source(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        r = await client.get(url, timeout=15)
        r.raise_for_status()
        return normalize(r.text)
    except Exception:
        return []


async def test_proxy(proxy: str) -> Optional[str]:
    proxies = None
    if proxy.startswith("socks5://") or proxy.startswith("socks4://"):
        proxies = {"http://": proxy, "https://": proxy}
    else:
        proxies = {"http://": proxy, "https://": proxy}
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"},
            http2=True,
            verify=True,
            proxies=proxies,
        ) as client:
            r = await client.get(TEST_URL, timeout=20)
            ctype = r.headers.get("content-type", "").lower()
            if r.status_code == 200 and "json" in ctype and r.text.strip().startswith("{"):
                return proxy
            return None
    except Exception:
        return None


async def main() -> int:
    async with httpx.AsyncClient() as client:
        candidates: List[str] = []
        for src in CANDIDATE_SOURCES:
            lst = await fetch_source(client, src)
            candidates.extend(lst)
        # Deduplicate, keep at most 200
        seen = set()
        uniq = []
        for p in candidates:
            if p not in seen:
                uniq.append(p)
                seen.add(p)
        uniq = uniq[:200]
        if not uniq:
            print("NO_CANDIDATE_PROXIES")
            return 2
        # Test concurrently in batches
        batch = 20
        for i in range(0, len(uniq), batch):
            tasks = [test_proxy(p) for p in uniq[i:i+batch]]
            results = await asyncio.gather(*tasks)
            for res in results:
                if res:
                    print(res)
                    return 0
        print("NO_WORKING_PROXY")
        return 3

if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 1
    sys.exit(code)
