from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

import aiosqlite

from .models import Match, MatchOdd


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    sport TEXT NOT NULL,
    tournament TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    start_time TEXT,
    is_live INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS odds (
    match_id TEXT NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (match_id, market, selection),
    FOREIGN KEY (match_id) REFERENCES matches(match_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    payload TEXT NOT NULL,
    received_at TEXT NOT NULL
);
"""


async def init_db(db_path: str) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def upsert_match(db_path: str, match: Match) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO matches(match_id, sport, tournament, home_team, away_team, start_time, is_live, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                sport=excluded.sport,
                tournament=excluded.tournament,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                start_time=excluded.start_time,
                is_live=excluded.is_live,
                updated_at=excluded.updated_at
            """,
            (
                match.match_id,
                match.sport,
                match.tournament,
                match.home_team,
                match.away_team,
                match.start_time.isoformat() if match.start_time else None,
                1 if match.is_live else 0,
                now,
                now,
            ),
        )
        # upsert odds
        for o in match.odds:
            await db.execute(
                """
                INSERT INTO odds(match_id, market, selection, odds, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(match_id, market, selection) DO UPDATE SET
                    odds=excluded.odds,
                    updated_at=excluded.updated_at
                """,
                (match.match_id, o.market, o.selection, o.odds, now),
            )
        await db.commit()


async def insert_raw(db_path: str, match_id: Optional[str], payload: dict) -> None:
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO raw_responses(match_id, payload, received_at) VALUES(?, ?, ?)",
            (match_id, json.dumps(payload, ensure_ascii=False), datetime.utcnow().isoformat()),
        )
        await db.commit()
