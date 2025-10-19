from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from dateutil import parser as dateparser

from .models import Match, MatchOdd


ESPORT_SPORT_NAMES = {
    "E-sport", "E-FOCI", "Esport", "Esports", "E-Sport", "E-Football", "E-sport foci"
}


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # assume seconds if small, ms if large
            if value > 10_000_000_000:
                return datetime.fromtimestamp(value / 1000)
            return datetime.fromtimestamp(value)
        except Exception:
            return None
    if isinstance(value, str) and value.strip():
        try:
            return dateparser.parse(value)
        except Exception:
            return None
    return None


def is_esport_football(item: Dict[str, Any]) -> bool:
    sport = (str(item.get("sport")) or str(item.get("sportName")) or "").lower()
    league = (str(item.get("league")) or str(item.get("tournament")) or "").lower()
    name = (str(item.get("name")) or "").lower()
    combined = " ".join([sport, league, name])
    keywords = [
        "e-sport", "esport", "efootball", "e-football", "e foci", "fifa", "e-foot", "virtual football",
    ]
    return any(k in combined for k in keywords)


def parse_odds(raw: Dict[str, Any]) -> List[MatchOdd]:
    results: List[MatchOdd] = []
    markets = raw.get("markets") or raw.get("odds") or []
    for market in markets:
        market_name = str(market.get("name") or market.get("market") or "").strip()
        selections = market.get("selections") or market.get("outcomes") or []
        for sel in selections:
            selection_name = str(sel.get("name") or sel.get("selection") or sel.get("outcome") or "").strip()
            price = sel.get("odds") or sel.get("price") or sel.get("decimal") or sel.get("value")
            try:
                price_f = float(price)
            except Exception:
                continue
            results.append(MatchOdd(market=market_name, selection=selection_name, odds=price_f))
    return results


def parse_match(item: Dict[str, Any]) -> Match | None:
    try:
        home = (item.get("homeTeam") or item.get("home") or item.get("team1") or {}).get("name") if isinstance(item.get("homeTeam"), dict) else item.get("homeTeam") or item.get("home") or item.get("team1")
        away = (item.get("awayTeam") or item.get("away") or item.get("team2") or {}).get("name") if isinstance(item.get("awayTeam"), dict) else item.get("awayTeam") or item.get("away") or item.get("team2")
        if isinstance(home, dict):
            home = home.get("name")
        if isinstance(away, dict):
            away = away.get("name")
        name = str(item.get("name") or "").strip()
        if not home or not away:
            if name and " - " in name:
                parts = name.split(" - ", 1)
                home, away = parts[0].strip(), parts[1].strip()
        if not home or not away:
            return None

        match_id = str(item.get("id") or item.get("matchId") or item.get("eventId") or item.get("fixtureId") or f"{home}-{away}-{item.get('start')}")
        tournament = item.get("tournament") or item.get("league") or item.get("competition")
        start_raw = item.get("start") or item.get("startTime") or item.get("kickoff") or item.get("date")
        start_time = parse_datetime(start_raw)
        is_live = bool(item.get("live") or item.get("inplay") or item.get("isLive"))
        odds = parse_odds(item)
        sport = str(item.get("sport") or item.get("sportName") or "E-sport").strip()

        if not is_esport_football(item):
            return None

        return Match(
            match_id=match_id,
            sport=sport,
            tournament=str(tournament) if tournament else None,
            home_team=str(home),
            away_team=str(away),
            start_time=start_time,
            is_live=is_live,
            odds=odds,
            raw=item,
        )
    except Exception:
        return None
