# OSRS GE Price Tool

A lightweight Old School RuneScape Grand Exchange browser with filtering, sorting, favorites, High Alchemy profit calculations, and optional local icon mirroring.

## Features

- Live OSRS Wiki price and mapping data
- Sortable and filterable table
- Favorites stored in browser `localStorage`
- High Alch profit calculation using current nature rune price
- Selectable trade volume windows: `5m`, `1h`, `24h`
- Local API proxy with configurable `User-Agent`
- Optional icon mirroring with cache, rate limiting, and staged background refresh
- Docker and non-Docker deployment paths

## Requirements

- Python `3.10+` for direct local runs
- Docker Desktop / Docker Engine for containerized runs
- Modern browser

## Running Locally

Default local server:

```bash
python3 server.py
```

Open `http://localhost:8080`.

Self-contained single-file launcher:

```bash
python3 osrs_ge_tool.py
```

## Running With Docker

Preferred:

```bash
docker compose up --build
```

Manual image run:

```bash
docker build -t osrs-ge-tool .
docker run --rm -p 8080:8080 -v ${PWD}/.icon-cache:/app/.icon-cache osrs-ge-tool
```

The container exposes the app on `http://localhost:8080` and persists mirrored icons through `./.icon-cache`.

## Configuration

`server.py` loads defaults from `server.config.json` when present.

Precedence:
- `CLI arguments`
- `server.config.json`
- built-in defaults

Use a different config file:

```bash
python3 server.py --config my-config.json
```

Override a configured default for a single run:

```bash
python3 server.py --port 9090 --no-icon-debug
```

Useful runtime endpoint:

- `http://localhost:8080/icon/stats` for icon cache, refresh queue, and rate-limit status

## Deployment Notes

- `server.config.json` is the right place for long-lived behavior like icon mirroring, TTL, and rate-limit settings.
- Docker is the best default for homelab or VM deployment.
- The current Docker setup mounts `server.config.json` read-only and persists icon cache on disk.

## Project Files

- `Index.html`: UI markup
- `Styles.css`: frontend styles
- `app.js`: frontend behavior and rendering
- `server.py`: local HTTP server, API proxy, icon cache/mirroring logic
- `server.config.json`: default runtime settings
- `Dockerfile`: container image definition
- `docker-compose.yml`: local container orchestration
- `osrs_ge_tool.py`: single-file packaged launcher

## Notes

- `Reset filters` does not clear favorites.
- Profit does not include GE tax, staff setup, or other rune-cost variants.
- Data source: OSRS Wiki Real-time Prices API  
  <https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>

## Troubleshooting

- If the UI cannot load data, verify `/api/v1/osrs/*` requests in browser DevTools.
- If icons are missing, check `/icon/stats` and verify the cache/rate-limit settings in `server.config.json`.
- If opening the HTML file directly from disk fails, run through `server.py` or Docker instead.
