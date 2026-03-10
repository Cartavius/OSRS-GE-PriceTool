#!/usr/bin/env python3
import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

UPSTREAM_BASE = "https://prices.runescape.wiki/api/v1/osrs"
DEFAULT_USER_AGENT = "OSRS-GE-PriceTool/1.2 (+https://github.com/Cartavius/OSRS-GE-PriceTool)"
ALLOWED_ENDPOINTS = {"mapping", "latest", "volumes", "5m", "1h"}

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OSRS GE + High Alch Price Tool</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <main class="container">
    <header>
      <h1>OSRS Grand Exchange + High Alchemy Tool</h1>
      <p>
        Live prices from the OSRS Wiki real-time prices API, combined with item mapping data for
        High Alchemy, Low Alchemy, and shop values.
      </p>
    </header>

    <section class="controls" aria-label="Filters and controls">
      <label>
        Search item
        <input id="searchInput" type="search" placeholder="Rune scimitar, Shark, Nature rune..." />
      </label>

      <label>
        Members
        <select id="memberFilter">
          <option value="all">All items</option>
          <option value="members">Members only</option>
          <option value="f2p">Free-to-play only</option>
        </select>
      </label>

      <label>
        Favorites
        <select id="favoritesFilter">
          <option value="all">All items</option>
          <option value="favorites">Favorites only</option>
        </select>
      </label>

      <label>
        Min buy (high)
        <input id="minPriceInput" type="number" min="0" step="1" placeholder="0" />
      </label>

      <label>
        Max buy (high)
        <input id="maxPriceInput" type="number" min="0" step="1" placeholder="Any" />
      </label>

      <label>
        Min alch profit
        <input id="minProfitInput" type="number" step="1" placeholder="0" />
      </label>

      <label>
        Volume window
        <select id="volumeWindowSelect">
          <option value="5m">5m</option>
          <option value="1h">1h</option>
          <option value="24h" selected>24h</option>
        </select>
      </label>

      <label id="minVolumeLabel">
        Min trade volume (24h)
        <input id="minVolumeInput" type="number" min="0" step="1" placeholder="0" />
      </label>

      <details class="column-picker">
        <summary>Show / hide columns</summary>
        <div id="columnOptions" class="column-options"></div>
      </details>

      <button id="refreshBtn" type="button">Refresh data</button>
      <button id="resetBtn" type="button" class="secondary">Reset filters</button>
    </section>

    <section class="stats" aria-live="polite">
      <span id="status">Loading data...</span>
      <span id="count"></span>
      <span id="updated"></span>
      <span id="natureRunePrice"></span>
    </section>

    <section class="pagination-controls" aria-label="Pagination controls">
      <label>
        Items per page
        <select id="pageSizeSelect">
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100" selected>100</option>
          <option value="250">250</option>
        </select>
      </label>
      <button id="prevPageBtn" type="button" class="secondary">Previous</button>
      <span id="pageInfo">Page 1 / 1</span>
      <button id="nextPageBtn" type="button" class="secondary">Next</button>
    </section>

    <div class="table-wrap">
      <table id="itemsTable">
        <thead>
          <tr>
            <th data-key="name">Item</th>
            <th data-key="high">Buy (high)</th>
            <th data-key="low">Sell (low)</th>
            <th data-key="spread">Spread</th>
            <th data-key="highalch">High Alch</th>
            <th data-key="lowalch">Low Alch</th>
            <th data-key="value">Store Value</th>
            <th data-key="volume" id="volumeHeader">Trade Volume (24h)</th>
            <th data-key="buyLimit">GE Buy Limit</th>
            <th data-key="alchProfit">Alch Profit*</th>
          </tr>
        </thead>
        <tbody id="tableBody"></tbody>
      </table>
    </div>

    <footer>
      <small>
        *Alch Profit = High Alch - Buy (high) - Nature rune price (auto-fetched from GE).
      </small>
    </footer>
  </main>

  <script src="app.js"></script>
</body>
</html>
"""
STYLES_CSS = """:root {
  color-scheme: light dark;
  font-family: Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}

body {
  margin: 0;
  background: #111827;
  color: #e5e7eb;
}

.container {
  max-width: 1300px;
  margin: 0 auto;
  padding: 1rem;
}

header h1 {
  margin: 0;
}

header p {
  color: #cbd5e1;
}

.controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-weight: 600;
}

input,
select,
button {
  border-radius: 0.5rem;
  border: 1px solid #374151;
  background: #1f2937;
  color: #f9fafb;
  padding: 0.55rem 0.65rem;
}

button {
  cursor: pointer;
  font-weight: 700;
  margin-top: auto;
}

button:hover {
  background: #374151;
}

button.secondary {
  background: #0f172a;
}

.column-picker {
  border: 1px solid #374151;
  border-radius: 0.5rem;
  padding: 0.55rem 0.65rem;
  background: #0f172a;
}

.column-picker summary {
  cursor: pointer;
  font-weight: 700;
}

.column-options {
  margin-top: 0.65rem;
  display: grid;
  gap: 0.45rem;
}

.column-options label {
  flex-direction: row;
  align-items: center;
  font-weight: 500;
}

.column-options input[type='checkbox'] {
  width: 1rem;
  height: 1rem;
  margin: 0;
}

.stats {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-bottom: 0.8rem;
  color: #cbd5e1;
}

.pagination-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: 0.75rem;
  margin-bottom: 0.8rem;
}

#pageInfo {
  color: #cbd5e1;
  min-width: 8.5rem;
  text-align: center;
}

.table-wrap {
  overflow: auto;
  border: 1px solid #374151;
  border-radius: 0.75rem;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: 0.6rem;
  border-bottom: 1px solid #374151;
  white-space: nowrap;
  text-align: right;
}

th:first-child,
td:first-child {
  text-align: left;
}

.item-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.favorite-toggle {
  border: 0;
  background: transparent;
  color: #94a3b8;
  padding: 0;
  font-size: 1rem;
  line-height: 1;
  margin: 0;
  cursor: pointer;
}

.favorite-toggle:hover {
  color: #fbbf24;
  background: transparent;
}

.favorite-toggle.active {
  color: #f59e0b;
}

.item-icon,
.item-icon-placeholder {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
}

.item-icon-placeholder {
  display: inline-block;
}

th {
  position: sticky;
  top: 0;
  background: #0b1220;
  cursor: pointer;
  user-select: none;
}

.hidden-column {
  display: none;
}

tbody tr:hover {
  background: #1e293b;
}

.pos { color: #4ade80; }
.neg { color: #f87171; }

footer {
  margin-top: 0.75rem;
  color: #94a3b8;
}
"""
APP_JS = """const API_BASE_CANDIDATES = [
  '/api/v1/osrs',
  'https://prices.runescape.wiki/api/v1/osrs',
];
const NATURE_RUNE_ITEM_ID = 561;
const CACHE_KEY_PREFIX = 'osrs_ge_cache_v1';
const FAVORITES_KEY = 'osrs_ge_favorites_v1';
const CACHE_TTL_MS = {
  mapping: 24 * 60 * 60 * 1000,
  latest: 60 * 1000,
  volumes: 60 * 1000,
  '5m': 60 * 1000,
  '1h': 60 * 1000,
};
const VOLUME_WINDOW_LABELS = {
  '5m': '5m',
  '1h': '1h',
  '24h': '24h',
};

const columnConfig = [
  { key: 'name', label: 'Item', alwaysVisible: true },
  { key: 'high', label: 'Buy (high)' },
  { key: 'low', label: 'Sell (low)' },
  { key: 'spread', label: 'Spread' },
  { key: 'highalch', label: 'High Alch' },
  { key: 'lowalch', label: 'Low Alch' },
  { key: 'value', label: 'Store Value' },
  { key: 'volume', label: 'Trade Volume' },
  { key: 'buyLimit', label: 'GE Buy Limit' },
  { key: 'alchProfit', label: 'Alch Profit*' },
];

const defaultColumns = new Set(['name', 'high', 'low', 'spread', 'highalch', 'value', 'volume', 'buyLimit', 'alchProfit']);

const state = {
  items: [],
  filtered: [],
  sortKey: 'alchProfit',
  sortDirection: 'desc',
  latestTimestamp: null,
  natureRunePrice: null,
  volumeWindow: '24h',
  favoritesFilter: 'all',
  favorites: new Set(),
  visibleColumns: new Set(defaultColumns),
  currentPage: 1,
  pageSize: 100,
};

const el = {
  search: document.getElementById('searchInput'),
  members: document.getElementById('memberFilter'),
  favorites: document.getElementById('favoritesFilter'),
  minPrice: document.getElementById('minPriceInput'),
  maxPrice: document.getElementById('maxPriceInput'),
  minProfit: document.getElementById('minProfitInput'),
  volumeWindow: document.getElementById('volumeWindowSelect'),
  minVolumeLabel: document.getElementById('minVolumeLabel'),
  minVolume: document.getElementById('minVolumeInput'),
  status: document.getElementById('status'),
  count: document.getElementById('count'),
  updated: document.getElementById('updated'),
  natureRunePrice: document.getElementById('natureRunePrice'),
  tbody: document.getElementById('tableBody'),
  refresh: document.getElementById('refreshBtn'),
  reset: document.getElementById('resetBtn'),
  headers: document.querySelectorAll('th[data-key]'),
  volumeHeader: document.getElementById('volumeHeader'),
  columnOptions: document.getElementById('columnOptions'),
  pageSize: document.getElementById('pageSizeSelect'),
  prevPage: document.getElementById('prevPageBtn'),
  nextPage: document.getElementById('nextPageBtn'),
  pageInfo: document.getElementById('pageInfo'),
};

const fmtNumber = new Intl.NumberFormat();

function formatCoins(value) {
  if (value === null || value === undefined) return 'â€”';
  return `${fmtNumber.format(value)} gp`;
}

function formatVolume(value) {
  if (value === null || value === undefined) return 'â€”';
  return fmtNumber.format(value);
}

function getIconUrl(iconName) {
  if (!iconName) return null;
  return `https://oldschool.runescape.wiki/w/Special:FilePath/${encodeURIComponent(iconName)}`;
}

function formatBuyLimit(value) {
  if (value === null || value === undefined) return '-';
  return fmtNumber.format(value);
}

function getVolumeWindowLabel(windowKey) {
  return VOLUME_WINDOW_LABELS[windowKey] ?? '24h';
}

function loadFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();

    const ids = parsed
      .map((value) => Number(value))
      .filter((value) => Number.isInteger(value) && value > 0);

    return new Set(ids);
  } catch {
    return new Set();
  }
}

function saveFavorites() {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify([...state.favorites]));
  } catch {
    // Ignore storage failures.
  }
}

function isFavorite(itemId) {
  return state.favorites.has(itemId);
}

function toggleFavorite(itemId) {
  if (isFavorite(itemId)) {
    state.favorites.delete(itemId);
  } else {
    state.favorites.add(itemId);
  }
  saveFavorites();
}

function extractTimedVolume(entry) {
  if (!entry || typeof entry !== 'object') return null;
  const high = typeof entry.highPriceVolume === 'number' ? entry.highPriceVolume : null;
  const low = typeof entry.lowPriceVolume === 'number' ? entry.lowPriceVolume : null;
  if (high === null && low === null) return null;
  return (high ?? 0) + (low ?? 0);
}

function getVolumeForWindow(item, windowKey) {
  if (windowKey === '5m') return item.volume5m;
  if (windowKey === '1h') return item.volume1h;
  return item.volume24h;
}

function updateVolumeUiLabels() {
  const label = getVolumeWindowLabel(state.volumeWindow);
  if (el.volumeHeader) {
    el.volumeHeader.textContent = `Trade Volume (${label})`;
  }
  if (el.minVolumeLabel) {
    el.minVolumeLabel.childNodes[0].textContent = `Min trade volume (${label})`;
  }
}

function applyVolumeWindowToItems() {
  state.items.forEach((item) => {
    item.volume = getVolumeForWindow(item, state.volumeWindow);
  });
}

function normalizeNum(inputValue) {
  if (inputValue === '' || inputValue === null || inputValue === undefined) {
    return null;
  }
  const parsed = Number(inputValue);
  return Number.isFinite(parsed) ? parsed : null;
}

function sortItems(items) {
  const sorted = [...items];
  const { sortKey, sortDirection } = state;

  sorted.sort((a, b) => {
    const aVal = a[sortKey];
    const bVal = b[sortKey];

    if (sortKey === 'name') {
      return sortDirection === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
    }

    const aNum = aVal ?? Number.NEGATIVE_INFINITY;
    const bNum = bVal ?? Number.NEGATIVE_INFINITY;
    return sortDirection === 'asc' ? aNum - bNum : bNum - aNum;
  });

  return sorted;
}

function updateVisibleColumns() {
  const headers = document.querySelectorAll('th[data-key]');
  headers.forEach((header, index) => {
    const key = header.dataset.key;
    const visible = state.visibleColumns.has(key);
    header.classList.toggle('hidden-column', !visible);

    const rows = el.tbody.querySelectorAll('tr');
    rows.forEach((row) => {
      if (!row.children[index]) return;
      row.children[index].classList.toggle('hidden-column', !visible);
    });
  });
}

function applyFilters({ resetPage = true } = {}) {
  const query = el.search.value.trim().toLowerCase();
  const membersFilter = el.members.value;
  const favoritesFilter = el.favorites.value;
  const minPrice = normalizeNum(el.minPrice.value);
  const maxPrice = normalizeNum(el.maxPrice.value);
  const minProfit = normalizeNum(el.minProfit.value);
  const minVolume = normalizeNum(el.minVolume.value);
  state.favoritesFilter = favoritesFilter === 'favorites' ? 'favorites' : 'all';

  state.filtered = state.items.filter((item) => {
    if (query && !item.name.toLowerCase().includes(query)) return false;

    if (membersFilter === 'members' && !item.members) return false;
    if (membersFilter === 'f2p' && item.members) return false;
    if (state.favoritesFilter === 'favorites' && !isFavorite(item.id)) return false;

    if (minPrice !== null && (item.high ?? -1) < minPrice) return false;
    if (maxPrice !== null && (item.high ?? Number.MAX_SAFE_INTEGER) > maxPrice) return false;
    if (minProfit !== null && (item.alchProfit ?? Number.NEGATIVE_INFINITY) < minProfit) return false;
    if (minVolume !== null && (item.volume ?? Number.NEGATIVE_INFINITY) < minVolume) return false;

    return true;
  });

  state.filtered = sortItems(state.filtered);
  if (resetPage) {
    state.currentPage = 1;
  }
  renderTable();
}

function renderTable() {
  const totalItems = state.filtered.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / state.pageSize));
  state.currentPage = Math.min(Math.max(1, state.currentPage), totalPages);
  const pageStart = (state.currentPage - 1) * state.pageSize;
  const pageItems = state.filtered.slice(pageStart, pageStart + state.pageSize);

  el.tbody.textContent = '';
  for (const item of pageItems) {
    const tr = document.createElement('tr');
    const profitClass = item.alchProfit > 0 ? 'pos' : item.alchProfit < 0 ? 'neg' : '';

    const nameTd = document.createElement('td');
    const itemCell = document.createElement('div');
    itemCell.className = 'item-cell';

    const favoriteBtn = document.createElement('button');
    const favorite = isFavorite(item.id);
    favoriteBtn.type = 'button';
    favoriteBtn.className = `favorite-toggle${favorite ? ' active' : ''}`;
    favoriteBtn.setAttribute('aria-label', favorite ? `Remove ${item.name} from favorites` : `Add ${item.name} to favorites`);
    favoriteBtn.setAttribute('aria-pressed', favorite ? 'true' : 'false');
    favoriteBtn.textContent = favorite ? 'â˜…' : 'â˜†';
    favoriteBtn.addEventListener('click', () => {
      toggleFavorite(item.id);
      applyFilters({ resetPage: false });
    });
    itemCell.appendChild(favoriteBtn);

    if (item.iconUrl) {
      const icon = document.createElement('img');
      icon.className = 'item-icon';
      icon.src = item.iconUrl;
      icon.alt = '';
      icon.loading = 'lazy';
      icon.decoding = 'async';
      icon.width = 24;
      icon.height = 24;
      itemCell.appendChild(icon);
    } else {
      const iconPlaceholder = document.createElement('span');
      iconPlaceholder.className = 'item-icon-placeholder';
      iconPlaceholder.setAttribute('aria-hidden', 'true');
      itemCell.appendChild(iconPlaceholder);
    }

    const nameSpan = document.createElement('span');
    nameSpan.textContent = item.name ?? '';
    itemCell.appendChild(nameSpan);
    nameTd.appendChild(itemCell);
    tr.appendChild(nameTd);

    const highTd = document.createElement('td');
    highTd.textContent = formatCoins(item.high);
    tr.appendChild(highTd);

    const lowTd = document.createElement('td');
    lowTd.textContent = formatCoins(item.low);
    tr.appendChild(lowTd);

    const spreadTd = document.createElement('td');
    spreadTd.textContent = formatCoins(item.spread);
    tr.appendChild(spreadTd);

    const highAlchTd = document.createElement('td');
    highAlchTd.textContent = formatCoins(item.highalch);
    tr.appendChild(highAlchTd);

    const lowAlchTd = document.createElement('td');
    lowAlchTd.textContent = formatCoins(item.lowalch);
    tr.appendChild(lowAlchTd);

    const valueTd = document.createElement('td');
    valueTd.textContent = formatCoins(item.value);
    tr.appendChild(valueTd);

    const volumeTd = document.createElement('td');
    volumeTd.textContent = formatVolume(item.volume);
    tr.appendChild(volumeTd);

    const buyLimitTd = document.createElement('td');
    buyLimitTd.textContent = formatBuyLimit(item.buyLimit);
    tr.appendChild(buyLimitTd);

    const profitTd = document.createElement('td');
    if (profitClass) {
      profitTd.className = profitClass;
    }
    profitTd.textContent = formatCoins(item.alchProfit);
    tr.appendChild(profitTd);

    el.tbody.appendChild(tr);
  }

  el.count.textContent = `Visible items: ${fmtNumber.format(state.filtered.length)} / ${fmtNumber.format(state.items.length)}`;
  el.pageInfo.textContent = `Page ${fmtNumber.format(state.currentPage)} / ${fmtNumber.format(totalPages)}`;
  el.prevPage.disabled = state.currentPage <= 1;
  el.nextPage.disabled = state.currentPage >= totalPages;
  updateVisibleColumns();
}

async function fetchJson(endpoint) {
  let lastError = null;

  for (const base of API_BASE_CANDIDATES) {
    try {
      const response = await fetch(`${base}/${endpoint}`);

      if (!response.ok) {
        throw new Error(`Request failed (${response.status}) for ${base}/${endpoint}`);
      }

      return response.json();
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError ?? new Error(`Request failed for ${endpoint}`);
}

function getCacheKey(endpoint) {
  return `${CACHE_KEY_PREFIX}:${endpoint}`;
}

function getCachedEntry(endpoint) {
  try {
    const raw = localStorage.getItem(getCacheKey(endpoint));
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function setCachedEntry(endpoint, payload) {
  try {
    const entry = {
      cachedAt: Date.now(),
      payload,
    };
    localStorage.setItem(getCacheKey(endpoint), JSON.stringify(entry));
  } catch {
    // Ignore storage failures (private mode/full quota).
  }
}

function isCacheFresh(endpoint, entry) {
  if (!entry || typeof entry.cachedAt !== 'number') return false;
  const ttl = CACHE_TTL_MS[endpoint];
  if (!ttl) return false;
  return Date.now() - entry.cachedAt < ttl;
}

async function fetchJsonCached(endpoint, { forceRefresh = false } = {}) {
  const cachedEntry = getCachedEntry(endpoint);
  if (!forceRefresh && isCacheFresh(endpoint, cachedEntry)) {
    return cachedEntry.payload;
  }

  try {
    const payload = await fetchJson(endpoint);
    setCachedEntry(endpoint, payload);
    return payload;
  } catch (error) {
    if (cachedEntry?.payload) {
      return cachedEntry.payload;
    }
    throw error;
  }
}

function mergeData(mapping, latest, volumes, prices5m, prices1h) {
  const mappingItems = Array.isArray(mapping) ? mapping : mapping?.data ?? [];
  const priceMap = latest.data || {};
  const volume24hMap = volumes.data || {};
  const volume5mMap = prices5m.data || {};
  const volume1hMap = prices1h.data || {};

  const natureRunePriceData = priceMap[NATURE_RUNE_ITEM_ID] || {};
  state.natureRunePrice = natureRunePriceData.high ?? natureRunePriceData.low ?? null;

  return mappingItems
    .map((item) => {
      const price = priceMap[item.id] || {};
      const volume24h = volume24hMap[item.id] || {};
      const volume5m = volume5mMap[item.id] || {};
      const volume1h = volume1hMap[item.id] || {};
      const high = price.high ?? null;
      const low = price.low ?? null;
      const highalch = item.highalch ?? null;
      const lowalch = item.lowalch ?? null;
      const value = item.value ?? null;
      const buyLimit = item.limit ?? null;
      const dailyVolume =
        typeof volume24h === 'number'
          ? volume24h
          : (volume24h?.high ?? volume24h?.low ?? null);
      const shortVolume5m = extractTimedVolume(volume5m);
      const shortVolume1h = extractTimedVolume(volume1h);
      const spread = high !== null && low !== null ? high - low : null;
      const alchProfit =
        high !== null && highalch !== null && state.natureRunePrice !== null
          ? highalch - high - state.natureRunePrice
          : null;

      return {
        id: item.id,
        name: item.name,
        icon: item.icon ?? null,
        iconUrl: getIconUrl(item.icon),
        members: Boolean(item.members),
        high,
        low,
        spread,
        highalch,
        lowalch,
        value,
        volume24h: dailyVolume,
        volume5m: shortVolume5m,
        volume1h: shortVolume1h,
        volume: dailyVolume,
        buyLimit,
        alchProfit,
      };
    })
    .filter((item) => item.high !== null || item.low !== null);
}

function getLatestTimestamp(latest) {
  if (typeof latest?.timestamp === 'number') {
    return latest.timestamp;
  }

  const priceEntries = Object.values(latest?.data || {});
  let maxTimestamp = null;
  for (const entry of priceEntries) {
    const highTime = typeof entry?.highTime === 'number' ? entry.highTime : null;
    const lowTime = typeof entry?.lowTime === 'number' ? entry.lowTime : null;
    const candidate = Math.max(highTime ?? 0, lowTime ?? 0);
    if (candidate > 0 && (maxTimestamp === null || candidate > maxTimestamp)) {
      maxTimestamp = candidate;
    }
  }

  return maxTimestamp;
}

function renderNatureRuneStatus() {
  if (state.natureRunePrice === null) {
    el.natureRunePrice.textContent = 'Nature rune price: unavailable';
    return;
  }

  el.natureRunePrice.textContent = `Nature rune price used: ${formatCoins(state.natureRunePrice)}`;
}

async function loadData({ forceRefresh = false } = {}) {
  el.status.textContent = forceRefresh ? 'Refreshing API data...' : 'Loading API data...';
  el.refresh.disabled = true;

  try {
    const [mapping, latest, volumes, prices5m, prices1h] = await Promise.all([
      fetchJsonCached('mapping', { forceRefresh }),
      fetchJsonCached('latest', { forceRefresh }),
      fetchJsonCached('volumes', { forceRefresh }),
      fetchJsonCached('5m', { forceRefresh }),
      fetchJsonCached('1h', { forceRefresh }),
    ]);

    state.items = mergeData(mapping, latest, volumes, prices5m, prices1h);
    applyVolumeWindowToItems();
    state.latestTimestamp = getLatestTimestamp(latest);

    const updatedAt = state.latestTimestamp ? new Date(state.latestTimestamp * 1000).toLocaleString() : 'Unknown';
    el.status.textContent = 'Data loaded successfully.';
    el.updated.textContent = `Last update: ${updatedAt}`;
    renderNatureRuneStatus();

    applyFilters();
  } catch (error) {
    console.error(error);
    el.status.textContent = 'Failed to load API data. Check DevTools for blocked requests (CORS, ad-blocker, firewall, or proxy).';
  } finally {
    el.refresh.disabled = false;
  }
}

function resetFilters() {
  el.search.value = '';
  el.members.value = 'all';
  el.favorites.value = 'all';
  el.minPrice.value = '';
  el.maxPrice.value = '';
  el.minProfit.value = '';
  el.volumeWindow.value = '24h';
  el.minVolume.value = '';
  state.sortKey = 'alchProfit';
  state.sortDirection = 'desc';
  state.volumeWindow = '24h';
  state.favoritesFilter = 'all';
  updateVolumeUiLabels();
  applyVolumeWindowToItems();
  state.currentPage = 1;
  state.visibleColumns = new Set(defaultColumns);
  renderColumnOptions();
  applyFilters();
}

function renderColumnOptions() {
  el.columnOptions.innerHTML = columnConfig
    .map((column) => {
      const checked = state.visibleColumns.has(column.key) ? 'checked' : '';
      const disabled = column.alwaysVisible ? 'disabled' : '';
      return `
        <label>
          <input type="checkbox" data-column-key="${column.key}" ${checked} ${disabled} />
          <span>${column.label}</span>
        </label>
      `;
    })
    .join('');

  const checkboxes = el.columnOptions.querySelectorAll('input[data-column-key]');
  checkboxes.forEach((checkbox) => {
    checkbox.addEventListener('change', () => {
      const key = checkbox.dataset.columnKey;
      if (!key) return;

      if (checkbox.checked) {
        state.visibleColumns.add(key);
      } else {
        state.visibleColumns.delete(key);
      }

      updateVisibleColumns();
    });
  });
}

function setupEvents() {
  [el.search, el.members, el.favorites, el.minPrice, el.maxPrice, el.minProfit, el.minVolume].forEach((input) => {
    input.addEventListener('input', applyFilters);
    input.addEventListener('change', applyFilters);
  });

  el.volumeWindow.addEventListener('change', () => {
    const nextWindow = el.volumeWindow.value;
    state.volumeWindow = VOLUME_WINDOW_LABELS[nextWindow] ? nextWindow : '24h';
    updateVolumeUiLabels();
    applyVolumeWindowToItems();
    applyFilters();
  });

  el.pageSize.addEventListener('change', () => {
    const nextPageSize = normalizeNum(el.pageSize.value);
    state.pageSize = nextPageSize && nextPageSize > 0 ? nextPageSize : 100;
    state.currentPage = 1;
    renderTable();
  });

  el.prevPage.addEventListener('click', () => {
    if (state.currentPage <= 1) return;
    state.currentPage -= 1;
    renderTable();
  });

  el.nextPage.addEventListener('click', () => {
    state.currentPage += 1;
    renderTable();
  });

  el.refresh.addEventListener('click', () => {
    loadData({ forceRefresh: true });
  });
  el.reset.addEventListener('click', resetFilters);

  el.headers.forEach((header) => {
    header.addEventListener('click', () => {
      const key = header.dataset.key;
      if (!key) return;

      if (state.sortKey === key) {
        state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = key;
        state.sortDirection = key === 'name' ? 'asc' : 'desc';
      }

      applyFilters({ resetPage: false });
    });
  });
}

state.favorites = loadFavorites();
renderColumnOptions();
updateVolumeUiLabels();
setupEvents();
loadData();

"""


class Handler(BaseHTTPRequestHandler):
    user_agent = DEFAULT_USER_AGENT

    @staticmethod
    def _is_client_disconnect(error):
        return isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

    def _send_common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' https://oldschool.runescape.wiki data:; "
            "connect-src 'self' https://prices.runescape.wiki; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'",
        )

    def _send_text(self, status, content_type, text, cache_control="no-store"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def _send_bytes(self, status, content_type, body, cache_control="no-store"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self._send_common_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_text(200, "text/html", INDEX_HTML, cache_control="no-cache")
            return

        if path == "/styles.css":
            self._send_text(200, "text/css", STYLES_CSS)
            return

        if path == "/app.js":
            self._send_text(200, "application/javascript", APP_JS)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self._send_common_headers()
            self.end_headers()
            return

        if path.startswith("/api/v1/osrs/"):
            self.proxy_api(path)
            return

        self._send_text(404, "text/plain", "Not found")

    def proxy_api(self, path):
        endpoint = path[len("/api/v1/osrs/") :]
        if not endpoint or endpoint not in ALLOWED_ENDPOINTS:
            self._send_text(400, "application/json", json.dumps({"error": "Invalid API endpoint"}))
            return

        upstream_url = f"{UPSTREAM_BASE}/{endpoint}"
        request = Request(
            upstream_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=20) as response:
                body = response.read()
                status = response.getcode()
                content_type = response.headers.get("Content-Type", "application/json")
        except HTTPError as error:
            body = error.read() if hasattr(error, "read") else b""
            status = error.code
            content_type = error.headers.get("Content-Type", "application/json") if error.headers else "application/json"
        except URLError as error:
            payload = {"error": "Upstream request failed", "details": str(error)}
            self._send_text(502, "application/json", json.dumps(payload))
            return

        self._send_bytes(status, content_type, body)


def main():
    parser = argparse.ArgumentParser(description="Run OSRS GE tool as a single-file local app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", default=8080, type=int, help="Port number")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent sent to OSRS Wiki API")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open the browser")
    args = parser.parse_args()

    Handler.user_agent = args.user_agent
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"

    print(f"Serving on {url}")
    print(f"Proxying /api/v1/osrs/* to {UPSTREAM_BASE}")
    print(f"Using User-Agent: {Handler.user_agent}")

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    server.serve_forever()


if __name__ == "__main__":
    main()
