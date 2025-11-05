from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MatchOdd:
    market: str
    selection: str
    odds: float


@dataclass
class Match:
    match_id: str
    sport: str
    tournament: Optional[str]
    home_team: str
    away_team: str
    start_time: Optional[datetime]
    is_live: bool
    odds: List[MatchOdd]
    raw: Dict[str, Any]
