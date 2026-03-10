const API_BASE_CANDIDATES = [
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
  if (value === null || value === undefined) return '—';
  return `${fmtNumber.format(value)} gp`;
}

function formatVolume(value) {
  if (value === null || value === undefined) return '—';
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
    favoriteBtn.textContent = favorite ? '★' : '☆';
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

