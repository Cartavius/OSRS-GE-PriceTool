# OSRS GE Price + High Alchemy Tool

A lightweight web tool for browsing Old School RuneScape Grand Exchange prices in a sortable/filterable table.

## Data sources

- OSRS Wiki real-time prices API (`latest` endpoint).
- OSRS Wiki item mapping API (`mapping` endpoint) for metadata like High Alchemy value, Low Alchemy value, and item shop value.
- OSRS Wiki volume API (`volumes` endpoint) for 24-hour trade volume.
- API guide reference: <https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>

## Features

- Default sort is High Alch profit from highest to lowest.
- Sortable columns.
- Filter by:
  - search text,
  - members vs F2P,
  - min/max buy price,
  - minimum High Alch profit,
  - minimum trade volume (selected window).
- Column picker dropdown for showing/hiding table columns.
- Trade volume column (24h).
- Item icons from OSRS Wiki mapping data.
- GE buy limit column from item mapping data.
- Selectable trade volume window (`5m`, `1h`, `24h`).
- Pagination with next/previous controls.
- Adjustable items per page (25/50/100/250).
- High Alchemy profit auto-subtracts current nature rune price from GE.
- Client-side API caching in `localStorage` to reduce repeat API calls.

## Running locally

Run the bundled local server so requests go through `/api/v1/osrs/*` with a descriptive `User-Agent`:

```bash
python3 server.py --port 8080 --user-agent "OSRS-GE-PriceTool/1.2 (+https://github.com/<you>/<repo>)"
```

Then open <http://localhost:8080>.

If you prefer to serve static files only, the app will fall back to direct browser requests to `https://prices.runescape.wiki/api/v1/osrs`.

## Notes

- High Alch profit shown here is:
  - `high_alch_value - GE_high_buy_price - nature_rune_GE_price`
- It does **not** subtract fire rune/staff costs or GE tax/transaction overhead.

## Troubleshooting API load failures

If you see `Failed to load API data`, check the browser DevTools Network/Console tabs:

- Verify requests to `/api/v1/osrs/mapping`, `latest`, and `volumes` are being made.
- If requests are blocked, common causes are:
  - browser extensions (especially ad/privacy blockers),
  - firewall or antivirus web filtering,
  - VPN/proxy/DNS filtering.
- If you opened `index.html` directly from disk, run through the local proxy server:

```bash
python3 server.py --port 8080
```

Then open <http://localhost:8080> and hard refresh (`Ctrl+F5`).

## User-Agent policy note

The OSRS Wiki API asks for a descriptive `User-Agent`. Browser `fetch` does not reliably allow overriding `User-Agent`, so this project sets it in `server.py` when proxying API requests.

## Cache behavior

When the app loads, it uses endpoint-specific cache TTLs:

- `mapping`: 24 hours
- `latest`: 60 seconds
- `volumes` (24h): 60 seconds
- `5m`: 60 seconds
- `1h`: 60 seconds

Clicking **Refresh data** forces a fresh API fetch and updates the cache. If the API request fails, the app will fall back to previously cached data (if available).

Item icons are loaded with lazy-loading and standard browser HTTP caching, so they are not repeatedly downloaded on every render.
