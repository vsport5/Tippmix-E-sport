from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Iterable, List

import backoff
from loguru import logger
from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import stealth_async

from .parser import parse_match
from .storage import insert_raw, upsert_match, insert_network_event, insert_block_event
from .config import get_playwright_proxy_settings, get_httpx_proxy
import httpx


TARGET_URL = (
    "https://www.tippmix.hu/mobil/sportfogadas#?sportid=999&countryid=99999988&page=1"
)

API_GLOBS = [
    re.compile(r"/api/.*", re.I),
    re.compile(r"/sport.*", re.I),
    re.compile(r"/mobile/.*", re.I),
]


@asynccontextmanager
async def launch_browser(headless: bool = True) -> AsyncIterator[Browser]:
    async with async_playwright() as p:
        launch_kwargs = {
            "headless": headless,
            "args": ["--no-sandbox", "--disable-setuid-sandbox"],
        }
        proxy = get_playwright_proxy_settings()
        if proxy:
            launch_kwargs["proxy"] = proxy
        browser = await p.chromium.launch(**launch_kwargs)
        try:
            yield browser
        finally:
            await browser.close()


def is_api_request(url: str) -> bool:
    return any(p.search(url) for p in API_GLOBS)


async def capture_page(url: str, headless: bool = True) -> AsyncIterator[Page]:
    async with launch_browser(headless=headless) as browser:
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            locale="hu-HU",
            extra_http_headers={
                "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
            },
        )
        page = await context.new_page()
        # apply stealth to reduce detection
        try:
            await stealth_async(page)
        except Exception:
            pass
        await page.goto(url)
        # attempt to accept cookie banners if present (best-effort)
        try:
            for text in ("Elfogad", "Rendben", "Elfogadom", "Accept all"):
                btn = page.get_by_role("button", name=text)
                if await btn.count() > 0:
                    await btn.first.click(timeout=2000)
                    break
        except Exception:
            pass
        # save a quick snapshot for debugging
        try:
            await page.screenshot(path="/workspace/screenshot.png", full_page=True)
            html = await page.content()
            with open("/workspace/page.html", "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
        try:
            yield page
        finally:
            await context.close()


async def extract_json_from_response(resp) -> Dict[str, Any] | None:
    try:
        ct = (resp.headers or {}).get("content-type", "")
        if "json" not in ct.lower():
            return None
        body = await resp.body()
        return json.loads(body.decode("utf-8", errors="ignore"))
    except Exception:
        return None


async def process_payload(db_path: str, payload: Dict[str, Any]) -> int:
    inserted = 0
    # try common containers
    candidates: List[Dict[str, Any]] = []
    for key in ("events", "matches", "data", "items", "list", "fixtures"):
        val = payload.get(key)
        if isinstance(val, list):
            candidates.extend(v for v in val if isinstance(v, dict))
    if not candidates and isinstance(payload, dict):
        # maybe payload is a single match dict
        candidates = [payload]

    for item in candidates:
        match = parse_match(item)
        if not match:
            continue
        await upsert_match(db_path, match)
        await insert_raw(db_path, match.match_id, item)
        inserted += 1
    return inserted


@backoff.on_exception(backoff.expo, Exception, max_time=300)
async def run_scraper(
    db_path: str,
    interval_seconds: int = 20,
    headless: bool = True,
    monitor_network: bool = True,
) -> None:
    logger.info("Starting Tippmix E-sport scraper...")
    while True:
        total_inserted = 0
        async for page in capture_page(TARGET_URL, headless=headless):
            # listen to API responses
            if monitor_network:
                page.on(
                    "request",
                    lambda req: asyncio.create_task(_handle_request(db_path, req)),
                )
                page.on(
                    "requestfailed",
                    lambda req: asyncio.create_task(_handle_request_failed(db_path, req)),
                )
                page.on(
                    "requestfinished",
                    lambda req: asyncio.create_task(_handle_request_finished(db_path, req)),
                )
                # capture websocket endpoints as well
                def _on_ws(ws):
                    try:
                        asyncio.create_task(
                            insert_network_event(
                                db_path,
                                phase="websocket_open",
                                url=ws.url,
                                method=None,
                                status=None,
                                resource_type="websocket",
                                headers=None,
                                body_bytes=None,
                                duration_ms=None,
                                error=None,
                            )
                        )
                        ws.on(
                            "close",
                            lambda: asyncio.create_task(
                                insert_network_event(
                                    db_path,
                                    phase="websocket_close",
                                    url=ws.url,
                                    method=None,
                                    status=None,
                                    resource_type="websocket",
                                    headers=None,
                                    body_bytes=None,
                                    duration_ms=None,
                                    error=None,
                                )
                            ),
                        )
                    except Exception as e:
                        logger.debug("Error handling websocket: {}", e)

                page.on("websocket", _on_ws)
            page.on(
                "response",
                lambda resp: asyncio.create_task(_handle_response(db_path, resp)),
            )
            try:
                await page.wait_for_timeout(8000)
                # trigger some scrolling/clicking if needed
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(4000)
            except Exception:
                pass
        logger.info("Cycle complete. Sleeping {}s", interval_seconds)
        await asyncio.sleep(interval_seconds)


async def _handle_response(db_path: str, resp) -> None:
    try:
        url = resp.url
        try:
            status = resp.status
        except Exception:
            status = None
        try:
            req = resp.request
            method = getattr(req, "method", lambda: None)()
            resource_type = getattr(req, "resource_type", lambda: None)()
        except Exception:
            method = None
            resource_type = None
        headers = None
        try:
            headers = await resp.all_headers()
        except Exception:
            headers = None
        await insert_network_event(
            db_path,
            phase="response",
            url=url,
            method=method,
            status=status,
            resource_type=resource_type,
            headers=headers,
            body_bytes=None,
            duration_ms=None,
            error=None,
        )
        # block detection heuristics for web responses
        if status in (301, 302, 303, 307, 308):
            loc = None
            try:
                loc = (await resp.all_headers()).get("location")
            except Exception:
                pass
            if loc and "ip-blokk" in loc:
                await insert_block_event(
                    db_path,
                    source="web",
                    url=url,
                    status=status,
                    block_type="geo_ip_block",
                    evidence=f"redirect:{loc}",
                    proxy_used=None,
                    user_agent=None,
                )
        if not is_api_request(url):
            return
        payload = await extract_json_from_response(resp)
        if not payload:
            return
        count = await process_payload(db_path, payload)
        if count:
            logger.info("Processed {} matches from {}", count, url)
    except Exception as e:
        logger.debug("Error handling response: {}", e)


async def _handle_request(db_path: str, req) -> None:
    try:
        url = req.url
        method = req.method
        resource_type = req.resource_type
        headers = req.headers
        await insert_network_event(
            db_path,
            phase="request",
            url=url,
            method=method,
            status=None,
            resource_type=resource_type,
            headers=headers,
            body_bytes=None,
            duration_ms=None,
            error=None,
        )
    except Exception as e:
        logger.debug("Error handling request: {}", e)


async def _handle_request_failed(db_path: str, req) -> None:
    try:
        url = req.url
        method = req.method
        resource_type = req.resource_type
        headers = req.headers
        err = getattr(req, "failure", lambda: None)() or {}
        err_text = None
        try:
            err_text = err.get("errorText") if isinstance(err, dict) else str(err)
        except Exception:
            err_text = None
        await insert_network_event(
            db_path,
            phase="failed",
            url=url,
            method=method,
            status=None,
            resource_type=resource_type,
            headers=headers,
            body_bytes=None,
            duration_ms=None,
            error=err_text,
        )
    except Exception as e:
        logger.debug("Error handling requestfailed: {}", e)


async def _handle_request_finished(db_path: str, req) -> None:
    try:
        url = req.url
        method = req.method
        resource_type = req.resource_type
        headers = req.headers
        timing_attr = getattr(req, "timing", None)
        timing = None
        try:
            timing = timing_attr() if callable(timing_attr) else timing_attr
        except Exception:
            timing = None
        duration = None
        try:
            if isinstance(timing, dict):
                start = timing.get("startTime")
                end = timing.get("responseEnd") or timing.get("endTime")
                if start is not None and end is not None:
                    duration = float(end) - float(start)
        except Exception:
            duration = None
        size = None
        try:
            resp = await req.response()
            if resp is not None:
                body = await resp.body()
                size = len(body) if body else None
        except Exception:
            size = None
        await insert_network_event(
            db_path,
            phase="finished",
            url=url,
            method=method,
            status=None,
            resource_type=resource_type,
            headers=headers,
            body_bytes=size,
            duration_ms=duration,
            error=None,
        )
    except Exception as e:
        logger.debug("Error handling requestfinished: {}", e)


# --------------------------
# HTTP API polling
# --------------------------

API_BASE = "https://api.tippmix.hu"
API_ENDPOINTS = [
    "/tippmix/search-filter",
    "/event",
    "/tippmix/search",
]


async def poll_api_once(db_path: str, client: httpx.AsyncClient) -> int:
    processed = 0
    for path in API_ENDPOINTS:
        url = API_BASE + path
        try:
            resp = await client.get(url, timeout=20)
            await insert_network_event(
                db_path,
                phase="api_response",
                url=url,
                method="GET",
                status=resp.status_code,
                resource_type="http",
                headers=dict(resp.headers),
                body_bytes=len(resp.content) if resp.content else 0,
                duration_ms=None,
                error=None,
            )
            ctype = (resp.headers.get("content-type") or "").lower()
            # detect redirects to block page or html payloads
            redirected_to = None
            try:
                if getattr(resp, "history", None):
                    for h in resp.history:  # type: ignore[attr-defined]
                        loc = h.headers.get("location") if hasattr(h, 'headers') else None
                        if loc:
                            redirected_to = loc
                            break
            except Exception:
                redirected_to = None
            if "ip-blokk" in (redirected_to or "") or ("text/html" in ctype):
                await insert_block_event(
                    db_path,
                    source="api",
                    url=url,
                    status=resp.status_code,
                    block_type="geo_ip_block" if "ip-blokk" in (redirected_to or "") else "html_block",
                    evidence=f"redirect:{redirected_to}" if redirected_to else f"ctype:{ctype}",
                    proxy_used=str(client._proxies) if hasattr(client, "_proxies") else None,
                    user_agent=client.headers.get("User-Agent"),
                )
            if ctype.find("json") >= 0:
                data = resp.json()
                # Store raw
                await insert_raw(db_path, None, data)
                # Try parse matches
                processed += await process_payload(db_path, data)
        except Exception as e:
            await insert_network_event(
                db_path,
                phase="api_error",
                url=url,
                method="GET",
                status=None,
                resource_type="http",
                headers=None,
                body_bytes=None,
                duration_ms=None,
                error=str(e),
            )
            # try to detect HTML/IP-block via exception or text
            try:
                if hasattr(e, "response") and e.response is not None:
                    r = e.response
                    ct = r.headers.get("content-type", "").lower()
                    if "text/html" in ct:
                        await insert_block_event(
                            db_path,
                            source="api",
                            url=url,
                            status=r.status_code,
                            block_type="html_block",
                            evidence="content-type:text/html",
                            proxy_used=str(client._proxies) if hasattr(client, "_proxies") else None,
                            user_agent=client.headers.get("User-Agent"),
                        )
            except Exception:
                pass
    return processed


@backoff.on_exception(backoff.expo, Exception, max_time=300)
async def run_api_poller(db_path: str, interval_seconds: int = 60) -> None:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
        ),
        "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
        "Origin": "https://www.tippmix.hu",
        "Referer": "https://www.tippmix.hu/",
    }
    proxies = get_httpx_proxy()
    async with httpx.AsyncClient(headers=headers, http2=True, verify=True, proxies=proxies) as client:
        logger.info("Starting Tippmix API poller...")
        while True:
            try:
                count = await poll_api_once(db_path, client)
                if count:
                    logger.info("API poller parsed {} matches", count)
            except Exception as e:
                logger.debug("API poller error: {}", e)
            await asyncio.sleep(interval_seconds)
