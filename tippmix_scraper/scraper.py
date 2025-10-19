from __future__ import annotations

import asyncio
import json
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Iterable, List

import backoff
from loguru import logger
from playwright.async_api import async_playwright, Browser, Page

from .parser import parse_match
from .storage import insert_raw, upsert_match


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
        browser = await p.chromium.launch(headless=headless)
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
async def run_scraper(db_path: str, interval_seconds: int = 20, headless: bool = True) -> None:
    logger.info("Starting Tippmix E-sport scraper...")
    while True:
        total_inserted = 0
        async for page in capture_page(TARGET_URL, headless=headless):
            # listen to API responses
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
