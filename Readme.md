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
  - minimum High Alch profit.
- Column picker dropdown for showing/hiding table columns.
- Trade volume column (24h).
- High Alchemy profit auto-subtracts current nature rune price from GE.

## Running locally

Use a local web server (instead of opening `index.html` directly) so browser fetch/CORS rules are handled consistently:

```bash
python3 -m http.server 8080
```

Then open <http://localhost:8080>.

## Notes

- High Alch profit shown here is:
  - `high_alch_value - GE_high_buy_price - nature_rune_GE_price`
- It does **not** subtract fire rune/staff costs or GE tax/transaction overhead.
