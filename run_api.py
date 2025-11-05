import asyncio
from pathlib import Path

from tippmix_scraper.storage import init_db
from tippmix_scraper.scraper import run_api_poller

DB_PATH = Path("/workspace/tippmix.db")

async def main():
    await init_db(str(DB_PATH))
    await run_api_poller(str(DB_PATH), interval_seconds=30)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
