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
from .storage import insert_raw, upsert_match, insert_network_event


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
        browser = await p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        try:
            yield browser
        finally:
            await browser.close()


def is_api_request(url: str) -> bool:
    return any(p.search(url) for p in API_GLOBS)


async def capture_page(url: str, headless: bool = True) -> AsyncIterator[Page]:
    async with launch_browser(headless=headless) as browser:
        context = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ))
        page = await context.new_page()
        # apply stealth to reduce detection
        try:
            await stealth_async(page)
        except Exception:
            pass
        await page.goto(url)
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
