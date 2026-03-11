# OSRS GE Price Tool

Web app for browsing Old School RuneScape Grand Exchange data with filters, sorting, and High Alchemy profit calculations.

## Requirements

- Python 3.10+
- Modern browser

## Quick Start

```bash
python3 server.py
```

Open: <http://localhost:8080>

## Configuration

`server.py` loads defaults from `server.config.json` (if present).

- Precedence: `CLI args > server.config.json > built-in defaults`
- Default config path can be overridden with:

```bash
python3 server.py --config my-config.json
```

Example one-off override:

```bash
python3 server.py --port 9090 --no-icon-debug
```

## One-File Run

Use the self-contained launcher:

```bash
python3 osrs_ge_tool.py
```

It serves the app, proxies API requests with the configured `User-Agent`, and opens the browser automatically.

## Docker

Build and run with Docker:

```bash
docker build -t osrs-ge-tool .
docker run --rm -p 8080:8080 -v ${PWD}/.icon-cache:/app/.icon-cache osrs-ge-tool
```

Using Docker Compose:

```bash
docker compose up --build
```

Notes:

- App is available at `http://localhost:8080`.
- Container runs `server.py` with `--host 0.0.0.0`.
- `server.config.json` is mounted read-only into the container and used for defaults.
- `.icon-cache` is mounted so mirrored icons persist between container restarts.

## Features

- Live GE data via OSRS Wiki prices API.
- Sortable, filterable table with pagination.
- High Alch profit calculation:
  - `high_alch - buy_high - nature_rune_price`
- Selectable volume window (`5m`, `1h`, `24h`).
- Favorites list with persistent local storage.
- Column show/hide picker.
- Local API proxy with custom `User-Agent`.
- Client-side caching to reduce repeat API requests.
- Icon cache/mirroring with staged background refresh.
- Rate-limit-aware icon fetching (budgeted window).
- Icon stats endpoint at `/icon/stats`.

## Data Source

- OSRS Wiki Real-time Prices API: <https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>

## Project Structure

- `Index.html`: UI layout
- `Styles.css`: styles
- `app.js`: client logic and rendering
- `server.py`: local static server + API proxy
- `server.config.json`: runtime defaults for local server behavior
- `osrs_ge_tool.py`: single-file launcher with embedded frontend assets

## Notes

- `Reset filters` does not clear favorites.
- Profit does not include GE tax or rune setup variations.

## Troubleshooting

- If the UI cannot load data, verify `/api/v1/osrs/*` requests in browser DevTools.
- If running from file directly fails due request restrictions, run through `server.py` and use `http://localhost:8080`.
- Check icon mirror health and rate-limit usage at `http://localhost:8080/icon/stats`.
