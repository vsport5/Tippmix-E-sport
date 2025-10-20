import asyncio
import random
import sys
from typing import List, Optional
import httpx

PROXY_LIST_URL = "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
)
TEST_TIPPMIX = "https://api.tippmix.hu/tippmix/search"
WHOAMI = "https://api.myip.com"


async def fetch_proxy_list() -> List[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(PROXY_LIST_URL, timeout=30)
        r.raise_for_status()
        lines = [l.strip() for l in r.text.splitlines() if l.strip()]
        # Add http:// if missing
        out = [l if "://" in l else ("http://" + l) for l in lines]
        return out


async def get_country_via_proxy(proxy: str) -> Optional[str]:
    proxies = {"http://": proxy, "https://": proxy}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, proxies=proxies, timeout=8, verify=True) as client:
            r = await client.get(WHOAMI)
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("cc") or data.get("country")
    except Exception:
        return None


async def test_tippmix_via_proxy(proxy: str) -> bool:
    proxies = {"http://": proxy, "https://": proxy}
    try:
        async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept": "application/json, text/plain, */*"}, proxies=proxies, timeout=10, http2=True, verify=True) as client:
            r = await client.get(TEST_TIPPMIX)
            ct = r.headers.get("content-type", "").lower()
            if r.status_code == 200 and "json" in ct and r.text.strip().startswith("{"):
                return True
            return False
    except Exception:
        return False


async def worker(queue: asyncio.Queue, result: asyncio.Future):
    while not result.done():
        try:
            proxy = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            return
        cc = await get_country_via_proxy(proxy)
        if cc == "HU":
            ok = await test_tippmix_via_proxy(proxy)
            if ok and not result.done():
                result.set_result(proxy)
        queue.task_done()


async def main():
    proxies = await fetch_proxy_list()
    random.shuffle(proxies)
    sample = proxies[:800]
    queue: asyncio.Queue = asyncio.Queue()
    for p in sample:
        queue.put_nowait(p)
    result: asyncio.Future = asyncio.get_event_loop().create_future()
    workers = [asyncio.create_task(worker(queue, result)) for _ in range(60)]
    try:
        await asyncio.wait_for(queue.join(), timeout=300)
    except asyncio.TimeoutError:
        pass
    for w in workers:
        w.cancel()
    if not result.done():
        print("NO_WORKING_HU_PROXY")
        return 2
    print(result.result())
    return 0

if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except KeyboardInterrupt:
        code = 1
    sys.exit(code)
