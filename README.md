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

## Options
- `--monitor-network/--no-monitor-network`: enable/disable logging all network events to `network_events`.
- `--interval`: scrape cadence in seconds (default: 20).
- `--headless`: run browser headless (default: True).
- `--mode`: run `web`, `api`, or `both` (default: `both`).

## Notes
- Built with Playwright. Some endpoints may be obfuscated or protected. The scraper listens to network responses and heuristically parses structures.
- Adjust `interval` to control scraping cadence.

## Proxy support (required for geofenced API)

The Tippmix API blocks non-HU IPs. Set a Hungarian upstream proxy via environment variables:

```bash
export PROXY_URL="http://user:pass@hu-proxy-host:port"
# or use HTTPS_PROXY/HTTP_PROXY
```

Both the Python components (Playwright and HTTPX) and the Node proxy use `PROXY_URL` automatically.

### Start Node CORS proxy

```bash
cd server
npm i
PORT=5001 node src/index.js
# Test
curl -sS http://localhost:5001/api/events | jq .
curl -sS http://localhost:5001/api/search | jq .
```

### Run only API poller (proxied)

```bash
python3 /workspace/run_api.py
```

### Run both web and API modes

```bash
python -m tippmix_scraper.cli scrape --mode both --interval 20 --headless True
```
