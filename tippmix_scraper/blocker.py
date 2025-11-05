from __future__ import annotations

from typing import Optional
from loguru import logger

BLOCK_PRIORITY = [
    "geo_ip_block",
    "html_block",
    "captcha",
    "rate_limit",
]


def choose_mitigation(block_type: str) -> str:
    t = (block_type or "").lower()
    if t == "geo_ip_block":
        return "rotate_proxy_or_hu_exit"
    if t == "captcha":
        return "stealth_and_retry_with_human_mouse"
    if t == "rate_limit":
        return "backoff_and_randomize"
    if t == "html_block":
        return "force_proxy_and_web_context"
    return "generic_retry"


def explain_mitigation(strategy: str) -> str:
    return {
        "rotate_proxy_or_hu_exit": "Switch to HU IP (proxy/VPN); rotate pool if blocked.",
        "stealth_and_retry_with_human_mouse": "Enable stealth; random waits, mouse gestures, navigator spoof.",
        "backoff_and_randomize": "Exponential backoff; jitter; vary headers and cadence.",
        "force_proxy_and_web_context": "Fetch via browser network (Playwright) to reuse session/cookies.",
        "generic_retry": "Retry with jitter and different headers.",
    }.get(strategy, strategy)


def next_action(block_type: str) -> tuple[str, str]:
    s = choose_mitigation(block_type)
    return s, explain_mitigation(s)
