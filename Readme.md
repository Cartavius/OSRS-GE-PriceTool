# OSRS GE Price Tool

Web app for browsing Old School RuneScape Grand Exchange data with filters, sorting, and High Alchemy profit calculations.

## Requirements

- Python 3.10+
- Modern browser

## Quick Start

```bash
python3 server.py --port 8080 --user-agent "OSRS-GE-PriceTool/1.2 (+https://github.com/Cartavius/OSRS-GE-PriceTool)"
```

Open: <http://localhost:8080>

## One-File Run

Use the self-contained launcher:

```bash
python3 osrs_ge_tool.py
```

It serves the app, proxies API requests with the configured `User-Agent`, and opens the browser automatically.

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

## Data Source

- OSRS Wiki Real-time Prices API: <https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices>

## Project Structure

- `Index.html`: UI layout
- `Styles.css`: styles
- `app.js`: client logic and rendering
- `server.py`: local static server + API proxy

## Notes

- `Reset filters` does not clear favorites.
- Profit does not include GE tax or rune setup variations.

## Troubleshooting

- If the UI cannot load data, verify `/api/v1/osrs/*` requests in browser DevTools.
- If running from file directly fails due request restrictions, run through `server.py` and use `http://localhost:8080`.
