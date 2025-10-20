from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from loguru import logger
from seleniumwire import webdriver  # type: ignore
from selenium.webdriver.chrome.options import Options

from .parser import parse_match
from .storage import upsert_match, insert_raw, insert_network_event, insert_block_event
from .config import get_proxy_from_env

TARGET_URL = "https://www.tippmix.hu/mobil/sportfogadas#?sportid=999&countryid=99999988&page=1"


def build_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--lang=hu-HU")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
    )
    proxy_url = get_proxy_from_env()
    seleniumwire_options = {}
    if proxy_url:
        seleniumwire_options = {
            'proxy': {
                'http': proxy_url,
                'https': proxy_url,
                'no_proxy': 'localhost,127.0.0.1'
            }
        }
    driver = webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)
    return driver


def is_json_response(req) -> bool:
    try:
        ct = req.response.headers.get('Content-Type', '')
        return 'json' in ct.lower()
    except Exception:
        return False


def extract_json_body(req) -> Dict[str, Any] | None:
    try:
        body = req.response.body
        return json.loads(body.decode('utf-8', errors='ignore'))
    except Exception:
        return None


def is_block_response(req) -> bool:
    try:
        status = req.response.status_code
        if status in (301, 302, 303, 307, 308):
            loc = req.response.headers.get('Location', '')
            return 'ip-blokk' in (loc or '')
        ct = req.response.headers.get('Content-Type', '')
        return 'text/html' in ct.lower() and status >= 300
    except Exception:
        return False


def process_payload_sync(db_path: str, payload: Dict[str, Any]) -> int:
    inserted = 0
    candidates: List[Dict[str, Any]] = []
    for key in ("events", "matches", "data", "items", "list", "fixtures"):
        val = payload.get(key)
        if isinstance(val, list):
            candidates.extend(v for v in val if isinstance(v, dict))
    if not candidates and isinstance(payload, dict):
        candidates = [payload]
    for item in candidates:
        m = parse_match(item)
        if not m:
            continue
        # sync wrappers
        import asyncio
        asyncio.run(upsert_match(db_path, m))
        asyncio.run(insert_raw(db_path, m.match_id, item))
        inserted += 1
    return inserted


def run_selenium_scraper(db_path: str, duration_seconds: int = 30):
    driver = build_driver()
    try:
        driver.get(TARGET_URL)
        t0 = time.time()
        while time.time() - t0 < duration_seconds:
            # scroll to trigger loads
            driver.execute_script("window.scrollBy(0, 1200);")
            time.sleep(1.5)
            for req in driver.requests:
                if not req.response:
                    continue
                url = req.url
                method = req.method
                status = req.response.status_code
                headers = dict(req.response.headers or {})
                try:
                    import asyncio
                    asyncio.run(insert_network_event(
                        db_path,
                        phase="selenium_response",
                        url=url,
                        method=method,
                        status=status,
                        resource_type=req.response.headers.get('Content-Type',''),
                        headers=headers,
                        body_bytes=len(req.response.body or b''),
                        duration_ms=None,
                        error=None,
                    ))
                except Exception:
                    pass
                if is_block_response(req):
                    try:
                        import asyncio
                        asyncio.run(insert_block_event(
                            db_path,
                            source="web",
                            url=url,
                            status=status,
                            block_type="geo_ip_block" if status in (301,302,303,307,308) else "html_block",
                            evidence=headers.get('Location') or headers.get('Content-Type'),
                            proxy_used=get_proxy_from_env(),
                            user_agent=driver.execute_script("return navigator.userAgent")
                        ))
                    except Exception:
                        pass
                if is_json_response(req):
                    data = extract_json_body(req)
                    if data:
                        process_payload_sync(db_path, data)
            time.sleep(2)
    finally:
        driver.quit()
