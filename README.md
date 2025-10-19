# Tippmix E-sport Foci Scraper

Continuous scraper for Tippmix E-sport football matches from the Tippmix mobile site.

## Quick start

1. Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

2. Run scraper:

```bash
python -m tippmix_scraper.cli scrape --db tippmix.db --interval 30 --headless True
```

The scraper opens the given URL and captures JSON API responses, parses possible E-sport football matches, and upserts them into SQLite. Raw payloads are also stored.

## Notes
- Built with Playwright. Some endpoints may be obfuscated or protected. The scraper listens to network responses and heuristically parses structures.
- Adjust `interval` to control scraping cadence.
