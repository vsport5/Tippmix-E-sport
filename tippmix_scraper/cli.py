from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich import print

from .scraper import run_scraper, run_api_poller
from .storage import init_db
from .blocker import next_action
from .mitigator import auto_mitigate

app = typer.Typer(add_completion=False)


@app.command()
def scrape(
    db: Path = typer.Option(Path("tippmix.db"), help="SQLite database path"),
    interval: int = typer.Option(20, min=5, help="Polling interval seconds"),
    headless: bool = typer.Option(True, help="Run browser in headless mode"),
    monitor_network: bool = typer.Option(True, help="Log all network events to DB"),
    mode: str = typer.Option("both", help="Run mode: web|api|both"),
):
    """Run continuous Tippmix E-sport football scraper/poller."""
    async def runner():
        await init_db(str(db))
        tasks = []
        if mode in ("web", "both"):
            tasks.append(
                asyncio.create_task(
                    run_scraper(
                        str(db),
                        interval_seconds=interval,
                        headless=headless,
                        monitor_network=monitor_network,
                    )
                )
            )
        if mode in ("api", "both"):
            tasks.append(
                asyncio.create_task(
                    run_api_poller(str(db), interval_seconds=max(30, interval))
                )
            )
        if not tasks:
            print("[red]Invalid mode, use: web|api|both[/]")
            return
        await asyncio.gather(*tasks)

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        print("[yellow]Stopped by user[/]")


@app.command()
def analyze(db: Path = typer.Option(Path("tippmix.db"), help="SQLite database path")):
    """Analyze recent block events and suggest mitigation."""
    import sqlite3
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("SELECT occurred_at, source, url, status, block_type, evidence FROM block_events ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()
    if not rows:
        print("[green]No block events recorded[/]")
        return
    for ts, src, url, status, bt, ev in rows:
        strat, why = next_action(bt)
        print(f"[bold]{ts}[/] {src} {status} {bt}\n- {url}\n- evidence: {ev}\n- mitigation: {strat} ({why})\n")


@app.command()
def mitigate(
    block_type: str = typer.Argument(..., help="Block type to mitigate (e.g., geo_ip_block)"),
):
    """Attempt automated mitigation for a block type."""
    res = asyncio.run(auto_mitigate(block_type))
    if res:
        print(f"[green]Mitigation applied[/]: active proxy -> {res}")
    else:
        print("[yellow]No mitigation change applied[/]")


if __name__ == "__main__":
    app()  # pragma: no cover
