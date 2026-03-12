# OSRS GE Price Tool

OSRS GE Price Tool is a local web application for exploring Old School RuneScape Grand Exchange prices, trade volume, and item profitability with persistent historical storage.

It combines:
- live OSRS Wiki market data
- local icon mirroring
- persistent SQLite history
- long-range charting with rollups
- a Docker-friendly deployment model for always-on use

## Features

- Live item table with:
  - search and filters
  - favorites
  - saved presets
  - sortable columns
  - draggable and resizable columns
  - configurable visible columns
  - pagination
- Profit calculations:
  - High Alch profit
  - GE tax-aware flip profit
- Item detail modal with:
  - market stats
  - profitability stats
  - OSRS Wiki link
  - persistent history chart
  - range selection: `24h`, `7d`, `30d`, `90d`, `1y`, `All`
  - line and observed OHLC views
  - volume overlay
  - hover readout
  - brush zoom
- Persistent market history with:
  - raw snapshots
  - hourly rollups
  - daily rollups
  - retention controls
- Storage diagnostics page:
  - current DB size
  - projected 1-year growth
  - raw/hourly/daily row counts
  - retention settings

## Data Sources

- OSRS Wiki real-time prices API
  - <https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>
- OSRS Wiki item pages via item ID lookup

## Project Structure

- `Index.html` - main application UI
- `Styles.css` - shared styles for the app and stats page
- `app.js` - frontend state, filtering, table behavior, modal behavior, and charting
- `stats.html` - storage stats page
- `stats.js` - storage stats page logic
- `server.py` - local server, API proxy, icon cache, persistent history tracking, rollups
- `server.config.json` - default runtime configuration
- `Dockerfile` - container image definition
- `docker-compose.yml` - local/container deployment
- `osrs_ge_tool.py` - single-file launcher variant

## Requirements

- Python `3.10+` for direct local runs
- Docker Engine / Docker Desktop for containerized runs
- A modern browser

## Running Locally

### Python

```bash
python3 server.py
```

Open:

```text
http://localhost:8080
```

### Docker

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:8080
```

Stop:

```bash
docker compose down
```

## Updating a Deployment

For a VM or other long-running host:

```bash
git pull
docker compose up -d --build
```

## Configuration

`server.py` reads settings with this precedence:

1. CLI arguments
2. `server.config.json`
3. built-in defaults

Use an alternate config file:

```bash
python3 server.py --config my-config.json
```

Current defaults include:

- icon mirroring enabled
- icon cache treated as permanent
- persistent market history enabled
- history polling every `300` seconds
- raw history retention: `180` days
- hourly rollup retention: `730` days
- daily rollup retention: forever

## Storage Model

### Browser storage

Stored in `localStorage`:

- favorites
- saved presets
- column order
- column widths
- short-lived API cache entries

### Server storage

Stored on disk:

- icon cache in `.icon-cache/`
- history database in `.price-history/osrs-ge-history.sqlite3`

### History retention

The server stores:

- raw snapshots for recent analysis
- hourly rollups for medium-term history
- daily rollups for long-term history

The chart automatically selects the right source:

- `24h`, `7d` -> raw history
- `30d`, `90d` -> hourly rollups
- `1y`, `All` -> daily rollups

This keeps recent ranges detailed and long ranges efficient.

## Endpoints

### Main UI

- `/`
- `/Index.html`

### Storage stats page

- `/stats.html`

### API proxy

- `/api/v1/osrs/latest`
- `/api/v1/osrs/volumes`
- `/api/v1/osrs/5m`
- `/api/v1/osrs/1h`
- `/api/v1/osrs/mapping`

### Icon endpoints

- `/icon?name=<icon_name>`
- `/icon/stats`

### History endpoints

Raw or rolled-up price history:

```text
/history?id=<item_id>&limit=<rows>&source=raw|hourly|daily
```

Observed OHLC history:

```text
/history?id=<item_id>&limit=<rows>&aggregate=ohlc&source=raw|hourly|daily&bucket_seconds=<seconds>
```

History storage stats:

```text
/history/stats
```

## Notes

- Observed OHLC values are derived from this tool's stored snapshots. They are not an official candlestick feed from Jagex or the OSRS Wiki.
- The icon cache is intended to be durable. If you want to refresh cached icons, clear `.icon-cache/`.
- The storage stats page reports current and projected history growth using the live database contents.

## Troubleshooting

- If market data is missing, inspect requests to `/api/v1/osrs/*`.
- If icons are missing, inspect `/icon/stats`.
- If history is not updating, check server/container logs for `[history]`.
- If the stats page is missing in Docker, rebuild the image:

```bash
docker compose down
docker compose up -d --build
```
