# OSRS GE Price Tool

OSRS GE Price Tool is a local web app for browsing Old School RuneScape Grand Exchange data with persistent market history, configurable charting, favorites, presets, and a local proxy for the OSRS Wiki price API.

## What It Does

- Loads item mapping, live prices, and trade volume from the OSRS Wiki real-time price API
- Filters and sorts the item table by price, profit, liquidity, membership status, and favorites
- Stores favorites and saved filter presets in browser `localStorage`
- Calculates High Alch profit and tax-aware flip profit
- Opens item details in an in-page modal instead of navigating away from the table
- Persists price history on the server in SQLite for long-term charting
- Caches item icons locally and keeps them on disk by default

## Current Feature Set

- Live table with:
  - sortable columns
  - favorites
  - saved presets
  - column visibility controls
  - pagination
  - `5m`, `1h`, and `24h` volume views
- Detail modal with:
  - market stats
  - profitability stats
  - persistent history chart
  - range selection: `24h`, `7d`, `30d`, `90d`, `1y`, `All`
  - chart modes: line view and observed OHLC bars
  - volume overlay
  - hover readout
  - brush zoom and reset zoom
- Local server features:
  - `/api/v1/osrs/*` proxy with custom `User-Agent`
  - `/icon` local icon serving and mirroring
  - `/icon/stats` cache/rate-limit diagnostics
  - `/history` raw and aggregated history access
- Docker support for local and homelab deployment

## Requirements

- Python `3.10+` for direct runs
- Docker Engine / Docker Desktop for containerized runs
- Modern browser

## Quick Start

### Local Python Run

```bash
python3 server.py
```

Open:

```text
http://localhost:8080
```

### Docker Run

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8080
```

Stop it:

```bash
docker compose down
```

## Docker Notes

The compose setup persists both icon cache and market history:

- `./.icon-cache`
- `./.price-history`

That means:

- icons stay cached across container rebuilds
- price history continues accumulating over time

For a deployed host or VM, the normal update flow is:

```bash
git pull
docker compose up -d --build
```

## Configuration

`server.py` loads defaults from `server.config.json`.

Precedence:

1. CLI arguments
2. `server.config.json`
3. built-in defaults

Run with a different config:

```bash
python3 server.py --config my-config.json
```

Current default behavior includes:

- icon mirroring enabled
- icon TTL disabled (`0`, treated as never stale)
- persistent market history tracking enabled
- history DB at `.price-history/osrs-ge-history.sqlite3`
- history polling every `300` seconds

## Runtime Endpoints

### Icon Stats

```text
/icon/stats
```

Shows:

- cache directory
- cached icon count
- rate-limit usage
- refresh queue state
- icon fetch counters

### History

Raw snapshot history:

```text
/history?id=<item_id>&limit=<rows>
```

Observed OHLC aggregation:

```text
/history?id=<item_id>&limit=<rows>&aggregate=ohlc&bucket_seconds=<seconds>
```

The OHLC output is derived from the app's stored snapshot history. It is not an official exchange candlestick feed.

## Data Storage

### Browser Storage

Stored in `localStorage`:

- favorites
- saved presets
- short-lived API cache entries

### Server Storage

Stored on disk:

- icon cache in `.icon-cache/`
- price history database in `.price-history/`

## Project Files

- `Index.html`: application markup
- `Styles.css`: application styles
- `app.js`: frontend state, filtering, modal, charting, and history interactions
- `server.py`: local HTTP server, API proxy, icon cache, and persistent history tracker
- `server.config.json`: runtime defaults
- `Dockerfile`: container image definition
- `docker-compose.yml`: local container orchestration
- `osrs_ge_tool.py`: single-file launcher variant

## Operational Notes

- The detail modal does not auto-open on page load; it opens only from an explicit item click.
- If a detail modal is already open during refresh, the selected item's history reloads in place.
- Long ranges may be downsampled in the chart to keep rendering responsive.
- Candle mode is based on observed history buckets produced by this tool, not official historical bars.
- Icon cache is intended to be durable. If you want a full icon refresh, clear `.icon-cache/` manually or change config behavior.

## Troubleshooting

- If the app cannot load market data, inspect browser requests to `/api/v1/osrs/*`.
- If icons are missing, inspect `/icon/stats`.
- If history is not building, check container or server logs for `[history]` lines.
- If Docker is running but the app is unavailable, rebuild:

```bash
docker compose up -d --build
```

## Data Source

OSRS Wiki real-time prices API:

<https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>
