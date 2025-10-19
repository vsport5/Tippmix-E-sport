from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich import print

from .scraper import run_scraper
from .storage import init_db

app = typer.Typer(add_completion=False)


@app.command()
def scrape(
    db: Path = typer.Option(Path("tippmix.db"), exists=False, dir_okay=False, help="SQLite database path"),
    interval: int = typer.Option(20, min=5, help="Polling interval seconds"),
    headless: bool = typer.Option(True, help="Run browser in headless mode"),
):
    """Run continuous Tippmix E-sport football scraper."""
    asyncio.run(init_db(str(db)))
    try:
        asyncio.run(run_scraper(str(db), interval_seconds=interval, headless=headless))
    except KeyboardInterrupt:
        print("[yellow]Stopped by user[/]")


if __name__ == "__main__":
    app()  # pragma: no cover
