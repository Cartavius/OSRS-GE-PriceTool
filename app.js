const API_BASE_CANDIDATES = [
  '/api/v1/osrs',
  'https://prices.runescape.wiki/api/v1/osrs',
];
const NATURE_RUNE_ITEM_ID = 561;
const CACHE_KEY_PREFIX = 'osrs_ge_cache_v1';
const FAVORITES_KEY = 'osrs_ge_favorites_v1';
const PRESETS_KEY = 'osrs_ge_presets_v1';
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
const GE_TAX_CAP = 5000000;
const CHART_RANGE_MS = {
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
  '90d': 90 * 24 * 60 * 60 * 1000,
  '1y': 365 * 24 * 60 * 60 * 1000,
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
  { key: 'flipProfit', label: 'Flip Profit' },
  { key: 'alchProfit', label: 'Alch Profit*' },
];

const defaultColumns = new Set(['name', 'high', 'low', 'spread', 'highalch', 'value', 'volume', 'buyLimit', 'flipProfit', 'alchProfit']);

const state = {
  items: [],
  filtered: [],
  sortKey: 'alchProfit',
  sortDirection: 'desc',
  latestTimestamp: null,
  natureRunePrice: null,
  iconCacheBust: null,
  volumeWindow: '24h',
  favoritesFilter: 'all',
  favorites: new Set(),
  visibleColumns: new Set(defaultColumns),
  currentPage: 1,
  pageSize: 100,
  applyTax: true,
  taxRate: 2,
  presets: {},
  selectedPreset: '',
  selectedItemId: null,
  snapshots: {},
  ohlcSeries: {},
  historyLoadingItemId: null,
  chartRange: '30d',
  chartMode: 'line',
  chartShowVolume: true,
  chartGeometry: null,
  chartZoomRange: null,
  chartBrush: null,
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
  presetSelect: document.getElementById('presetSelect'),
  savePresetBtn: document.getElementById('savePresetBtn'),
  deletePresetBtn: document.getElementById('deletePresetBtn'),
  applyTax: document.getElementById('applyTaxInput'),
  taxRate: document.getElementById('taxRateInput'),
  detailPanel: document.getElementById('detailPanel'),
  detailTitle: document.getElementById('detailTitle'),
  detailSubtitle: document.getElementById('detailSubtitle'),
  detailIcon: document.getElementById('detailIcon'),
  detailTags: document.getElementById('detailTags'),
  detailMarketStats: document.getElementById('detailMarketStats'),
  detailProfitStats: document.getElementById('detailProfitStats'),
  detailChart: document.getElementById('detailChart'),
  detailChartEmpty: document.getElementById('detailChartEmpty'),
  detailChartReadout: document.getElementById('detailChartReadout'),
  detailChartLegend: document.getElementById('detailChartLegend'),
  detailHistoryStatus: document.getElementById('detailHistoryStatus'),
  closeDetailBtn: document.getElementById('closeDetailBtn'),
  detailBackdrop: document.getElementById('detailBackdrop'),
  detailChartRange: document.getElementById('detailChartRange'),
  detailChartMode: document.getElementById('detailChartMode'),
  detailChartVolume: document.getElementById('detailChartVolume'),
  detailChartResetZoom: document.getElementById('detailChartResetZoom'),
};

const fmtNumber = new Intl.NumberFormat();
const fmtPercent = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function formatCoins(value) {
  if (value === null || value === undefined) return '-';
  return `${fmtNumber.format(Math.round(value))} gp`;
}

function formatVolume(value) {
  if (value === null || value === undefined) return '-';
  return fmtNumber.format(Math.round(value));
}

function formatPercent(value) {
  if (value === null || value === undefined) return '-';
  return `${fmtPercent.format(value)}%`;
}

function formatShortDateTime(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function getDirectIconUrl(iconName, cacheBust = null) {
  if (!iconName) return null;
  const base = `https://oldschool.runescape.wiki/w/Special:FilePath/${encodeURIComponent(iconName)}`;
  return cacheBust ? `${base}?v=${cacheBust}` : base;
}

function getIconUrl(iconName, cacheBust = null) {
  if (!iconName) return null;
  if (window.location.protocol === 'http:' || window.location.protocol === 'https:') {
    const params = new URLSearchParams({ name: iconName });
    if (cacheBust) {
      params.set('v', String(cacheBust));
    }
    return `/icon?${params.toString()}`;
  }
  return getDirectIconUrl(iconName, cacheBust);
}

function formatBuyLimit(value) {
  if (value === null || value === undefined) return '-';
  return fmtNumber.format(value);
}

function getVolumeWindowLabel(windowKey) {
  return VOLUME_WINDOW_LABELS[windowKey] ?? '24h';
}

function normalizeNum(inputValue) {
  if (inputValue === '' || inputValue === null || inputValue === undefined) {
    return null;
  }
  const parsed = Number(inputValue);
  return Number.isFinite(parsed) ? parsed : null;
}

function loadStoredJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function saveStoredJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore storage failures.
  }
}

function loadFavorites() {
  const parsed = loadStoredJson(FAVORITES_KEY, []);
  if (!Array.isArray(parsed)) return new Set();
  return new Set(parsed.map((value) => Number(value)).filter((value) => Number.isInteger(value) && value > 0));
}

function saveFavorites() {
  saveStoredJson(FAVORITES_KEY, [...state.favorites]);
}

function loadPresets() {
  const parsed = loadStoredJson(PRESETS_KEY, {});
  return parsed && typeof parsed === 'object' ? parsed : {};
}

function savePresets() {
  saveStoredJson(PRESETS_KEY, state.presets);
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

function calculateGeTax(price) {
  if (!state.applyTax || price === null || price === undefined || price <= 0) {
    return 0;
  }
  return Math.min(price * (state.taxRate / 100), GE_TAX_CAP);
}

function enrichCalculatedFields(item) {
  const geTax = item.low !== null ? calculateGeTax(item.low) : 0;
  const flipProfit = item.low !== null && item.high !== null ? item.low - geTax - item.high : null;
  const spread = item.high !== null && item.low !== null ? item.high - item.low : null;
  const marginPercent = item.high && flipProfit !== null ? (flipProfit / item.high) * 100 : null;
  return {
    ...item,
    geTax,
    flipProfit,
    spread,
    marginPercent,
  };
}

function updateCalculatedFields() {
  state.items = state.items.map((item) => enrichCalculatedFields(item));
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

function getCurrentFilterState() {
  return {
    search: el.search.value,
    members: el.members.value,
    favorites: el.favorites.value,
    minPrice: el.minPrice.value,
    maxPrice: el.maxPrice.value,
    minProfit: el.minProfit.value,
    volumeWindow: el.volumeWindow.value,
    minVolume: el.minVolume.value,
    pageSize: el.pageSize.value,
    applyTax: el.applyTax.checked,
    taxRate: el.taxRate.value,
    sortKey: state.sortKey,
    sortDirection: state.sortDirection,
    visibleColumns: [...state.visibleColumns],
  };
}

function applyPresetValues(preset) {
  el.search.value = preset.search ?? '';
  el.members.value = preset.members ?? 'all';
  el.favorites.value = preset.favorites ?? 'all';
  el.minPrice.value = preset.minPrice ?? '';
  el.maxPrice.value = preset.maxPrice ?? '';
  el.minProfit.value = preset.minProfit ?? '';
  el.volumeWindow.value = preset.volumeWindow ?? '24h';
  el.minVolume.value = preset.minVolume ?? '';
  el.pageSize.value = preset.pageSize ?? '100';
  el.applyTax.checked = preset.applyTax ?? true;
  el.taxRate.value = preset.taxRate ?? '2';

  state.sortKey = preset.sortKey ?? 'alchProfit';
  state.sortDirection = preset.sortDirection ?? 'desc';
  state.visibleColumns = new Set(Array.isArray(preset.visibleColumns) ? preset.visibleColumns : defaultColumns);
  state.pageSize = normalizeNum(el.pageSize.value) || 100;
  state.volumeWindow = VOLUME_WINDOW_LABELS[el.volumeWindow.value] ? el.volumeWindow.value : '24h';
  state.applyTax = Boolean(el.applyTax.checked);
  state.taxRate = Math.max(0, normalizeNum(el.taxRate.value) ?? 2);
  renderColumnOptions();
  updateVolumeUiLabels();
  updateCalculatedFields();
  applyVolumeWindowToItems();
  applyFilters();
}

function renderPresetOptions() {
  const current = state.selectedPreset;
  el.presetSelect.innerHTML = '<option value="">Custom view</option>';
  Object.keys(state.presets)
    .sort((a, b) => a.localeCompare(b))
    .forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      el.presetSelect.appendChild(option);
    });
  el.presetSelect.value = current in state.presets ? current : '';
  el.deletePresetBtn.disabled = !el.presetSelect.value;
}

function saveCurrentPreset() {
  const name = window.prompt('Preset name');
  if (!name) return;
  state.presets[name] = getCurrentFilterState();
  state.selectedPreset = name;
  savePresets();
  renderPresetOptions();
}

function deleteSelectedPreset() {
  const name = el.presetSelect.value;
  if (!name || !state.presets[name]) return;
  delete state.presets[name];
  state.selectedPreset = '';
  savePresets();
  renderPresetOptions();
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
  state.applyTax = Boolean(el.applyTax.checked);
  state.taxRate = Math.max(0, normalizeNum(el.taxRate.value) ?? 2);

  updateCalculatedFields();
  applyVolumeWindowToItems();

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
  renderSelectedItem();
}

function renderRowCell(tr, text, className = '') {
  const td = document.createElement('td');
  if (className) {
    td.className = className;
  }
  td.textContent = text;
  tr.appendChild(td);
}

function selectItem(itemId) {
  if (state.selectedItemId !== itemId) {
    state.chartZoomRange = null;
  }
  state.selectedItemId = itemId;
  renderTable();
  renderSelectedItem();
  loadSelectedItemHistory(itemId, { forceRefresh: true });
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
    if (state.selectedItemId === item.id) {
      tr.classList.add('is-selected');
    }
    tr.addEventListener('click', () => {
      selectItem(item.id);
    });

    const nameTd = document.createElement('td');
    const itemCell = document.createElement('div');
    itemCell.className = 'item-cell';

    const favoriteBtn = document.createElement('button');
    const favorite = isFavorite(item.id);
    favoriteBtn.type = 'button';
    favoriteBtn.className = `favorite-toggle${favorite ? ' active' : ''}`;
    favoriteBtn.setAttribute('aria-label', favorite ? `Remove ${item.name} from favorites` : `Add ${item.name} to favorites`);
    favoriteBtn.setAttribute('aria-pressed', favorite ? 'true' : 'false');
    favoriteBtn.textContent = favorite ? '*' : '+';
    favoriteBtn.addEventListener('click', (event) => {
      event.stopPropagation();
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
      icon.addEventListener('error', () => {
        const fallbackUrl = getDirectIconUrl(item.icon, state.iconCacheBust);
        if (!fallbackUrl || icon.src === fallbackUrl) return;
        icon.src = fallbackUrl;
      });
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

    renderRowCell(tr, formatCoins(item.high));
    renderRowCell(tr, formatCoins(item.low));
    renderRowCell(tr, formatCoins(item.spread));
    renderRowCell(tr, formatCoins(item.highalch));
    renderRowCell(tr, formatCoins(item.lowalch));
    renderRowCell(tr, formatCoins(item.value));
    renderRowCell(tr, formatVolume(item.volume));
    renderRowCell(tr, formatBuyLimit(item.buyLimit));
    renderRowCell(tr, formatCoins(item.flipProfit), item.flipProfit > 0 ? 'pos' : item.flipProfit < 0 ? 'neg' : '');
    renderRowCell(tr, formatCoins(item.alchProfit), item.alchProfit > 0 ? 'pos' : item.alchProfit < 0 ? 'neg' : '');
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

async function fetchItemHistory(itemId, { forceRefresh = false } = {}) {
  const key = String(itemId);
  if (!forceRefresh && Array.isArray(state.snapshots[key])) {
    return state.snapshots[key];
  }

  const response = await fetch(`/history?id=${encodeURIComponent(itemId)}&limit=5000`);
  if (!response.ok) {
    throw new Error(`History request failed (${response.status})`);
  }

  const payload = await response.json();
  const entries = Array.isArray(payload?.entries) ? payload.entries : [];
  state.snapshots[key] = entries;
  return entries;
}

function getChartBucketSeconds() {
  if (state.chartRange === '24h') return 5 * 60;
  if (state.chartRange === '7d') return 60 * 60;
  if (state.chartRange === '30d') return 6 * 60 * 60;
  if (state.chartRange === '90d') return 12 * 60 * 60;
  return 24 * 60 * 60;
}

async function fetchItemOhlcHistory(itemId, { forceRefresh = false } = {}) {
  const bucketSeconds = getChartBucketSeconds();
  const key = `${itemId}:${bucketSeconds}`;
  if (!forceRefresh && Array.isArray(state.ohlcSeries[key])) {
    return state.ohlcSeries[key];
  }

  const response = await fetch(
    `/history?id=${encodeURIComponent(itemId)}&limit=10000&aggregate=ohlc&bucket_seconds=${bucketSeconds}`
  );
  if (!response.ok) {
    throw new Error(`OHLC history request failed (${response.status})`);
  }

  const payload = await response.json();
  const entries = Array.isArray(payload?.entries) ? payload.entries : [];
  state.ohlcSeries[key] = entries;
  return entries;
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
  saveStoredJson(getCacheKey(endpoint), { cachedAt: Date.now(), payload });
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
      const dailyVolume = typeof volume24h === 'number' ? volume24h : (volume24h?.high ?? volume24h?.low ?? null);
      const shortVolume5m = extractTimedVolume(volume5m);
      const shortVolume1h = extractTimedVolume(volume1h);
      const alchProfit = high !== null && highalch !== null && state.natureRunePrice !== null
        ? highalch - high - state.natureRunePrice
        : null;

      return enrichCalculatedFields({
        id: item.id,
        name: item.name,
        icon: item.icon ?? null,
        iconUrl: getIconUrl(item.icon, state.iconCacheBust),
        members: Boolean(item.members),
        high,
        low,
        highalch,
        lowalch,
        value,
        volume24h: dailyVolume,
        volume5m: shortVolume5m,
        volume1h: shortVolume1h,
        volume: dailyVolume,
        buyLimit,
        alchProfit,
      });
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
  el.natureRunePrice.textContent = `Nature rune price used: ${formatCoins(state.natureRunePrice)} | Tax: ${formatPercent(state.taxRate)}`;
}

function renderDetailStats(container, rows) {
  container.textContent = '';
  rows.forEach(({ label, value, className }) => {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = value;
    if (className) {
      dd.className = className;
    }
    container.appendChild(dt);
    container.appendChild(dd);
  });
}

function filterEntriesByRange(entries) {
  const rangeMs = CHART_RANGE_MS[state.chartRange] ?? null;
  if (!rangeMs || !entries.length) {
    return entries;
  }

  const latestTs = entries[entries.length - 1]?.ts;
  if (typeof latestTs !== 'number') {
    return entries;
  }

  const minTs = latestTs - rangeMs;
  const filtered = entries.filter((entry) => typeof entry.ts === 'number' && entry.ts >= minTs);
  return filtered.length ? filtered : entries.slice(-Math.min(entries.length, 2));
}

function filterEntriesByZoom(entries) {
  if (!state.chartZoomRange || !entries.length) {
    return entries;
  }

  const minTs = Math.min(state.chartZoomRange.startTs, state.chartZoomRange.endTs);
  const maxTs = Math.max(state.chartZoomRange.startTs, state.chartZoomRange.endTs);
  const filtered = entries.filter((entry) => typeof entry.ts === 'number' && entry.ts >= minTs && entry.ts <= maxTs);
  return filtered.length >= 2 ? filtered : entries;
}

function getChartEntries(itemId) {
  const baseEntries = state.chartMode === 'candles'
    ? state.ohlcSeries[`${itemId}:${getChartBucketSeconds()}`] || []
    : state.snapshots[String(itemId)] || [];
  return filterEntriesByZoom(filterEntriesByRange(baseEntries));
}

function appendSvgText(svg, { x, y, text, fill = '#94a3b8', anchor = 'start', size = '10' }) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  node.setAttribute('x', String(x));
  node.setAttribute('y', String(y));
  node.setAttribute('fill', fill);
  node.setAttribute('font-size', size);
  node.setAttribute('text-anchor', anchor);
  node.textContent = text;
  svg.appendChild(node);
  return node;
}

function averageOf(values) {
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getMidPrice(entry) {
  if (typeof entry.close === 'number') return entry.close;
  if (typeof entry.high === 'number' && typeof entry.low === 'number') {
    return (entry.high + entry.low) / 2;
  }
  if (typeof entry.high === 'number') return entry.high;
  if (typeof entry.low === 'number') return entry.low;
  return null;
}

function normalizeChartEntry(entry) {
  const open = typeof entry.open === 'number' ? entry.open : getMidPrice(entry);
  const close = typeof entry.close === 'number' ? entry.close : getMidPrice(entry);
  const high = typeof entry.high === 'number' ? entry.high : close;
  const low = typeof entry.low === 'number' ? entry.low : close;
  return {
    ts: entry.ts,
    high,
    low,
    volume: entry.volume,
    open,
    close,
    candleHigh: typeof entry.high === 'number' ? entry.high : close,
    candleLow: typeof entry.low === 'number' ? entry.low : close,
    sourceCount: entry.sample_count ?? entry.sourceCount ?? 1,
  };
}

function aggregateChartEntries(entries, maxPoints) {
  if (entries.length <= maxPoints) {
    return entries.map(normalizeChartEntry);
  }

  const chunkSize = Math.ceil(entries.length / maxPoints);
  const aggregated = [];
  for (let index = 0; index < entries.length; index += chunkSize) {
    const chunk = entries.slice(index, index + chunkSize);
    const highs = chunk.map((entry) => entry.high).filter((value) => typeof value === 'number');
    const lows = chunk.map((entry) => entry.low).filter((value) => typeof value === 'number');
    const volumes = chunk.map((entry) => entry.volume).filter((value) => typeof value === 'number');
    const mids = chunk.map(getMidPrice).filter((value) => typeof value === 'number');
    aggregated.push({
      ts: chunk[chunk.length - 1].ts,
      high: averageOf(highs),
      low: averageOf(lows),
      volume: averageOf(volumes),
      open: mids[0] ?? null,
      close: mids[mids.length - 1] ?? null,
      candleHigh: mids.length ? Math.max(...mids) : null,
      candleLow: mids.length ? Math.min(...mids) : null,
      sourceCount: chunk.length,
    });
  }
  return aggregated;
}

function getRenderableChartData(itemId) {
  const filteredEntries = getChartEntries(itemId);
  const pointLimit = state.chartMode === 'candles' ? 90 : 180;
  return {
    filteredEntries,
    renderEntries: aggregateChartEntries(filteredEntries, pointLimit),
  };
}

function renderChartLegend() {
  const parts = state.chartMode === 'candles'
    ? [
        '<span><i class="legend-swatch legend-swatch-mid"></i>Observed OHLC bars</span>',
        state.chartShowVolume ? '<span><i class="legend-swatch legend-swatch-volume"></i>24h volume overlay</span>' : '',
      ]
    : [
        '<span><i class="legend-swatch legend-swatch-high"></i>High</span>',
        '<span><i class="legend-swatch legend-swatch-low"></i>Low</span>',
        state.chartShowVolume ? '<span><i class="legend-swatch legend-swatch-volume"></i>24h volume overlay</span>' : '',
      ];
  el.detailChartLegend.innerHTML = parts.filter(Boolean).join('');
}

function updateChartReadout(item, datum) {
  if (!datum) {
    const modeLabel = state.chartMode === 'candles' ? 'Observed OHLC view' : 'High/low line view';
    el.detailChartReadout.textContent = `${modeLabel}. Hover the chart to inspect exact values.`;
    return;
  }

  const segments = [`${formatShortDateTime(datum.ts)}`];
  if (state.chartMode === 'candles') {
    segments.push(`Open ${formatCoins(datum.open)}`);
    segments.push(`High ${formatCoins(datum.candleHigh)}`);
    segments.push(`Low ${formatCoins(datum.candleLow)}`);
    segments.push(`Close ${formatCoins(datum.close)}`);
  } else {
    segments.push(`High ${formatCoins(datum.high)}`);
    segments.push(`Low ${formatCoins(datum.low)}`);
  }
  if (typeof datum.volume === 'number') {
    segments.push(`24h volume ${formatVolume(datum.volume)}`);
  }
  if (datum.sourceCount > 1) {
    segments.push(`${datum.sourceCount} samples`);
  }
  el.detailChartReadout.textContent = segments.join(' | ');
}

function clearChartHover(item) {
  const geometry = state.chartGeometry;
  if (!geometry) return;
  geometry.hoverGroup.setAttribute('display', 'none');
  updateChartReadout(item, null);
}

function drawLineChartSeries(svg, entries, getX, getPriceY, hoverGroup) {
  const lineConfig = [
    { key: 'high', color: '#38bdf8' },
    { key: 'low', color: '#f59e0b' },
  ];
  const hoverDots = {};

  function pointsFor(key) {
    return entries
      .map((entry) => {
        if (typeof entry[key] !== 'number') return null;
        return `${getX(entry.ts)},${getPriceY(entry[key])}`;
      })
      .filter(Boolean)
      .join(' ');
  }

  lineConfig.forEach(({ key, color }) => {
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', pointsFor(key));
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', color);
    line.setAttribute('stroke-width', '3');
    svg.appendChild(line);

    entries.forEach((entry) => {
      if (typeof entry[key] !== 'number') return;
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', String(getX(entry.ts)));
      circle.setAttribute('cy', String(getPriceY(entry[key])));
      circle.setAttribute('r', '2.75');
      circle.setAttribute('fill', color);
      svg.appendChild(circle);
    });

    const hoverDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    hoverDot.setAttribute('r', '4.5');
    hoverDot.setAttribute('fill', color);
    hoverDot.setAttribute('stroke', '#020617');
    hoverDot.setAttribute('stroke-width', '1.5');
    hoverGroup.appendChild(hoverDot);
    hoverDots[key] = hoverDot;
  });

  return hoverDots;
}

function drawCandleChartSeries(svg, entries, getX, getPriceY, hoverGroup) {
  const candleWidth = Math.max(4, Math.min(12, 520 / Math.max(entries.length, 1)));
  const hoverRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  hoverRect.setAttribute('stroke', '#c084fc');
  hoverRect.setAttribute('stroke-width', '2');
  hoverRect.setAttribute('fill', 'rgba(192, 132, 252, 0.18)');
  hoverGroup.appendChild(hoverRect);

  entries.forEach((entry) => {
    if (typeof entry.candleHigh !== 'number' || typeof entry.candleLow !== 'number') return;
    const x = getX(entry.ts);
    const wick = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    wick.setAttribute('x1', String(x));
    wick.setAttribute('x2', String(x));
    wick.setAttribute('y1', String(getPriceY(entry.candleHigh)));
    wick.setAttribute('y2', String(getPriceY(entry.candleLow)));
    wick.setAttribute('stroke', '#c084fc');
    wick.setAttribute('stroke-width', '1.5');
    svg.appendChild(wick);

    const open = typeof entry.open === 'number' ? entry.open : entry.candleLow;
    const close = typeof entry.close === 'number' ? entry.close : entry.candleHigh;
    const top = getPriceY(Math.max(open, close));
    const bottom = getPriceY(Math.min(open, close));
    const body = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    body.setAttribute('x', String(x - candleWidth / 2));
    body.setAttribute('width', String(candleWidth));
    body.setAttribute('y', String(Math.min(top, bottom)));
    body.setAttribute('height', String(Math.max(2, Math.abs(bottom - top))));
    body.setAttribute('fill', close >= open ? 'rgba(74, 222, 128, 0.65)' : 'rgba(248, 113, 113, 0.65)');
    body.setAttribute('stroke', '#c084fc');
    body.setAttribute('stroke-width', '1');
    svg.appendChild(body);
  });

  return { candleWidth, hoverRect };
}

function renderHistoryChart(item) {
  const allEntries = state.chartMode === 'candles'
    ? state.ohlcSeries[`${item.id}:${getChartBucketSeconds()}`] || []
    : state.snapshots[String(item.id)] || [];
  const entryLabel = state.chartMode === 'candles' ? 'bars' : 'snapshots';
  const { filteredEntries, renderEntries } = getRenderableChartData(item.id);
  el.detailChart.textContent = '';
  state.chartGeometry = null;
  renderChartLegend();
  updateChartReadout(item, null);
  el.detailChartResetZoom.disabled = !state.chartZoomRange;

  if (renderEntries.length < 2) {
    el.detailChart.classList.add('hidden');
    el.detailChartEmpty.classList.remove('hidden');
    if (state.historyLoadingItemId === item.id) {
      el.detailHistoryStatus.textContent = 'Loading server history...';
    } else {
      el.detailHistoryStatus.textContent = renderEntries.length === 1 ? `1 stored ${entryLabel.slice(0, -1)} in this range` : `No stored ${entryLabel} yet`;
    }
    return;
  }

  const priceValues = state.chartMode === 'candles'
    ? renderEntries.flatMap((entry) => [entry.candleHigh, entry.candleLow]).filter((value) => typeof value === 'number')
    : renderEntries.flatMap((entry) => [entry.high, entry.low]).filter((value) => typeof value === 'number');

  if (!priceValues.length) {
    el.detailChart.classList.add('hidden');
    el.detailChartEmpty.classList.remove('hidden');
    el.detailHistoryStatus.textContent = `${renderEntries.length} stored ${entryLabel} without price points`;
    return;
  }

  const width = 640;
  const height = 260;
  const paddingLeft = 56;
  const paddingRight = 14;
  const paddingTop = 18;
  const paddingBottom = 34;
  const volumeAreaHeight = state.chartShowVolume && renderEntries.some((entry) => typeof entry.volume === 'number') ? 52 : 0;
  const priceBottom = height - paddingBottom - volumeAreaHeight;
  const minValue = Math.min(...priceValues);
  const maxValue = Math.max(...priceValues);
  const valueRange = Math.max(1, maxValue - minValue);
  const minTs = renderEntries[0].ts;
  const maxTs = renderEntries[renderEntries.length - 1].ts;
  const timeRange = Math.max(1, maxTs - minTs);
  const volumeValues = renderEntries.map((entry) => entry.volume).filter((value) => typeof value === 'number');
  const maxVolume = volumeValues.length ? Math.max(...volumeValues) : 1;

  function getX(ts) {
    return paddingLeft + (((ts - minTs) / timeRange) * (width - paddingLeft - paddingRight));
  }

  function getPriceY(value) {
    return priceBottom - (((value - minValue) / valueRange) * (priceBottom - paddingTop));
  }

  function getVolumeY(value) {
    return height - paddingBottom - ((value / Math.max(1, maxVolume)) * Math.max(16, volumeAreaHeight - 8));
  }

  const yTicks = [maxValue, minValue + valueRange / 2, minValue];
  yTicks.forEach((tickValue) => {
    const y = getPriceY(tickValue);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', String(paddingLeft));
    line.setAttribute('x2', String(width - paddingRight));
    line.setAttribute('y1', String(y));
    line.setAttribute('y2', String(y));
    line.setAttribute('stroke', '#334155');
    line.setAttribute('stroke-width', '1');
    el.detailChart.appendChild(line);
    appendSvgText(el.detailChart, {
      x: paddingLeft - 6,
      y: y + 3,
      text: formatCoins(tickValue).replace(' gp', ''),
      anchor: 'end',
    });
  });

  const xTicks = [minTs, minTs + timeRange / 2, maxTs];
  xTicks.forEach((tickTs) => {
    const x = getX(tickTs);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', String(x));
    line.setAttribute('x2', String(x));
    line.setAttribute('y1', String(paddingTop));
    line.setAttribute('y2', String(height - paddingBottom));
    line.setAttribute('stroke', '#1e293b');
    line.setAttribute('stroke-width', '1');
    el.detailChart.appendChild(line);
  });

  const axis = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  axis.setAttribute(
    'd',
    `M ${paddingLeft} ${paddingTop} V ${height - paddingBottom} H ${width - paddingRight}`
  );
  axis.setAttribute('stroke', '#64748b');
  axis.setAttribute('stroke-width', '1.25');
  axis.setAttribute('fill', 'none');
  el.detailChart.appendChild(axis);

  if (volumeAreaHeight > 0) {
    const volumeBarWidth = Math.max(2, Math.min(10, 520 / Math.max(renderEntries.length, 1)));
    renderEntries.forEach((entry) => {
      if (typeof entry.volume !== 'number') return;
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('x', String(getX(entry.ts) - volumeBarWidth / 2));
      rect.setAttribute('width', String(volumeBarWidth));
      rect.setAttribute('y', String(getVolumeY(entry.volume)));
      rect.setAttribute('height', String((height - paddingBottom) - getVolumeY(entry.volume)));
      rect.setAttribute('fill', 'rgba(34, 197, 94, 0.35)');
      el.detailChart.appendChild(rect);
    });
    [maxVolume, maxVolume / 2, 0].forEach((tickValue) => {
      const y = tickValue === 0 ? height - paddingBottom : getVolumeY(tickValue);
      appendSvgText(el.detailChart, {
        x: width - paddingRight + 2,
        y: y + 3,
        text: formatVolume(tickValue),
        fill: '#22c55e',
      });
    });
  }

  const hoverGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  hoverGroup.setAttribute('display', 'none');
  const hoverLine = document.createElementNS('http://www.w3.org/2000/svg', 'line');
  hoverLine.setAttribute('stroke', '#e2e8f0');
  hoverLine.setAttribute('stroke-dasharray', '4 4');
  hoverLine.setAttribute('stroke-width', '1');
  hoverGroup.appendChild(hoverLine);

  let hoverArtifacts = null;
  if (state.chartMode === 'candles') {
    hoverArtifacts = drawCandleChartSeries(el.detailChart, renderEntries, getX, getPriceY, hoverGroup);
  } else {
    hoverArtifacts = drawLineChartSeries(el.detailChart, renderEntries, getX, getPriceY, hoverGroup);
  }

  const brushRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  brushRect.setAttribute('fill', 'rgba(56, 189, 248, 0.18)');
  brushRect.setAttribute('stroke', '#38bdf8');
  brushRect.setAttribute('stroke-width', '1.25');
  brushRect.setAttribute('display', 'none');
  el.detailChart.appendChild(brushRect);

  el.detailChart.appendChild(hoverGroup);

  appendSvgText(el.detailChart, {
    x: paddingLeft,
    y: height - 8,
    text: formatShortDateTime(minTs),
  });
  appendSvgText(el.detailChart, {
    x: width / 2,
    y: height - 8,
    text: formatShortDateTime(minTs + timeRange / 2),
    anchor: 'middle',
  });
  appendSvgText(el.detailChart, {
    x: width - paddingRight,
    y: height - 8,
    text: formatShortDateTime(maxTs),
    anchor: 'end',
  });

  if (state.chartShowVolume && volumeAreaHeight > 0) {
    appendSvgText(el.detailChart, {
      x: width - paddingRight,
      y: priceBottom + 14,
      text: '24h volume',
      anchor: 'end',
      fill: '#22c55e',
    });
  }

  state.chartGeometry = {
    itemId: item.id,
    data: renderEntries,
    getX,
    getPriceY,
    minTs,
    maxTs,
    width,
    paddingLeft,
    paddingRight,
    hoverGroup,
    hoverLine,
    hoverArtifacts,
    brushRect,
    priceTop: paddingTop,
    priceBottom,
    height,
    paddingBottom,
  };

  el.detailChart.classList.remove('hidden');
  el.detailChartEmpty.classList.add('hidden');
  const compressionNote = renderEntries.length !== filteredEntries.length ? ` | downsampled to ${renderEntries.length}` : '';
  const zoomNote = state.chartZoomRange ? ' | zoomed' : '';
  el.detailHistoryStatus.textContent = `${filteredEntries.length} shown / ${allEntries.length} stored ${entryLabel}${compressionNote}${zoomNote}`;
}

function renderSelectedItem() {
  const item = state.items.find((candidate) => candidate.id === state.selectedItemId);
  if (!item) {
    el.detailPanel.classList.add('hidden');
    document.body.classList.remove('modal-open');
    el.detailChartResetZoom.disabled = true;
    return;
  }

  el.detailPanel.classList.remove('hidden');
  document.body.classList.add('modal-open');
  el.detailChartRange.value = state.chartRange;
  el.detailChartMode.value = state.chartMode;
  el.detailChartVolume.checked = state.chartShowVolume;
  el.detailTitle.textContent = item.name;
  el.detailSubtitle.textContent = item.members ? 'Members item' : 'Free-to-play item';
  if (item.iconUrl) {
    el.detailIcon.src = item.iconUrl;
    el.detailIcon.classList.remove('hidden');
  } else {
    el.detailIcon.classList.add('hidden');
  }

  el.detailTags.textContent = '';
  [item.members ? 'Members' : 'F2P', isFavorite(item.id) ? 'Favorite' : null, state.applyTax ? `GE tax ${formatPercent(state.taxRate)}` : 'GE tax off']
    .filter(Boolean)
    .forEach((label) => {
      const span = document.createElement('span');
      span.className = 'detail-tag';
      span.textContent = label;
      el.detailTags.appendChild(span);
    });

  renderDetailStats(el.detailMarketStats, [
    { label: 'Buy (high)', value: formatCoins(item.high) },
    { label: 'Sell (low)', value: formatCoins(item.low) },
    { label: 'Spread', value: formatCoins(item.spread) },
    { label: 'GE tax', value: formatCoins(item.geTax) },
    { label: `Volume (${getVolumeWindowLabel(state.volumeWindow)})`, value: formatVolume(item.volume) },
    { label: 'Buy limit', value: formatBuyLimit(item.buyLimit) },
  ]);

  renderDetailStats(el.detailProfitStats, [
    { label: 'Flip profit', value: formatCoins(item.flipProfit), className: item.flipProfit > 0 ? 'pos' : item.flipProfit < 0 ? 'neg' : '' },
    { label: 'Margin %', value: formatPercent(item.marginPercent), className: item.marginPercent > 0 ? 'pos' : item.marginPercent < 0 ? 'neg' : '' },
    { label: 'High Alch', value: formatCoins(item.highalch) },
    { label: 'Nature rune', value: formatCoins(state.natureRunePrice) },
    { label: 'Alch profit', value: formatCoins(item.alchProfit), className: item.alchProfit > 0 ? 'pos' : item.alchProfit < 0 ? 'neg' : '' },
    { label: 'Store value', value: formatCoins(item.value) },
  ]);

  renderHistoryChart(item);
}

function handleChartPointerMove(event) {
  const geometry = state.chartGeometry;
  if (!geometry || state.selectedItemId === null || geometry.itemId !== state.selectedItemId) {
    return;
  }

  const bounds = el.detailChart.getBoundingClientRect();
  if (!bounds.width || !bounds.height) {
    return;
  }

  if (state.chartBrush) {
    const currentX = ((event.clientX - bounds.left) / bounds.width) * geometry.width;
    const minX = Math.max(geometry.paddingLeft, Math.min(state.chartBrush.startX, currentX));
    const maxX = Math.min(geometry.width - geometry.paddingRight, Math.max(state.chartBrush.startX, currentX));
    geometry.brushRect.setAttribute('display', 'block');
    geometry.brushRect.setAttribute('x', String(minX));
    geometry.brushRect.setAttribute('y', String(geometry.priceTop));
    geometry.brushRect.setAttribute('width', String(Math.max(1, maxX - minX)));
    geometry.brushRect.setAttribute('height', String((geometry.height - geometry.paddingBottom) - geometry.priceTop));
    return;
  }

  const svgX = ((event.clientX - bounds.left) / bounds.width) * 640;
  let nearest = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  geometry.data.forEach((entry) => {
    const x = geometry.getX(entry.ts);
    const distance = Math.abs(x - svgX);
    if (distance < nearestDistance) {
      nearest = entry;
      nearestDistance = distance;
    }
  });

  if (!nearest) return;

  const x = geometry.getX(nearest.ts);
  geometry.hoverLine.setAttribute('x1', String(x));
  geometry.hoverLine.setAttribute('x2', String(x));
  geometry.hoverLine.setAttribute('y1', String(geometry.priceTop));
  geometry.hoverLine.setAttribute('y2', String(geometry.height - geometry.paddingBottom));
  geometry.hoverGroup.setAttribute('display', 'block');

  if (state.chartMode === 'candles') {
    const { candleWidth, hoverRect } = geometry.hoverArtifacts;
    const top = geometry.getPriceY(nearest.candleHigh ?? nearest.close ?? nearest.open ?? 0);
    const bottom = geometry.getPriceY(nearest.candleLow ?? nearest.close ?? nearest.open ?? 0);
    hoverRect.setAttribute('x', String(x - candleWidth / 2 - 1));
    hoverRect.setAttribute('width', String(candleWidth + 2));
    hoverRect.setAttribute('y', String(Math.min(top, bottom)));
    hoverRect.setAttribute('height', String(Math.max(4, Math.abs(bottom - top))));
  } else {
    const { high, low } = geometry.hoverArtifacts;
    if (typeof nearest.high === 'number') {
      high.setAttribute('cx', String(x));
      high.setAttribute('cy', String(geometry.getPriceY(nearest.high)));
      high.setAttribute('display', 'block');
    } else {
      high.setAttribute('display', 'none');
    }
    if (typeof nearest.low === 'number') {
      low.setAttribute('cx', String(x));
      low.setAttribute('cy', String(geometry.getPriceY(nearest.low)));
      low.setAttribute('display', 'block');
    } else {
      low.setAttribute('display', 'none');
    }
  }

  const currentItem = state.items.find((candidate) => candidate.id === state.selectedItemId);
  if (currentItem) {
    updateChartReadout(currentItem, nearest);
  }
}

function handleChartPointerDown(event) {
  const geometry = state.chartGeometry;
  if (!geometry || state.selectedItemId === null || geometry.itemId !== state.selectedItemId) {
    return;
  }
  event.preventDefault();

  const bounds = el.detailChart.getBoundingClientRect();
  if (!bounds.width || !bounds.height) {
    return;
  }

  const svgX = ((event.clientX - bounds.left) / bounds.width) * geometry.width;
  const clampedX = Math.max(geometry.paddingLeft, Math.min(geometry.width - geometry.paddingRight, svgX));
  state.chartBrush = { startX: clampedX };
  geometry.brushRect.setAttribute('display', 'block');
  geometry.brushRect.setAttribute('x', String(clampedX));
  geometry.brushRect.setAttribute('y', String(geometry.priceTop));
  geometry.brushRect.setAttribute('width', '1');
  geometry.brushRect.setAttribute('height', String((geometry.height - geometry.paddingBottom) - geometry.priceTop));
}

function handleChartPointerUp() {
  const geometry = state.chartGeometry;
  const brush = state.chartBrush;
  state.chartBrush = null;
  if (!geometry || !brush) {
    return;
  }

  const width = Number(geometry.brushRect.getAttribute('width') || '0');
  if (width < 8) {
    geometry.brushRect.setAttribute('display', 'none');
    return;
  }

  const startX = Number(geometry.brushRect.getAttribute('x') || geometry.paddingLeft);
  const endX = startX + width;
  const rangeWidth = geometry.width - geometry.paddingLeft - geometry.paddingRight;
  const startTs = geometry.minTs + (((startX - geometry.paddingLeft) / rangeWidth) * (geometry.maxTs - geometry.minTs));
  const endTs = geometry.minTs + (((endX - geometry.paddingLeft) / rangeWidth) * (geometry.maxTs - geometry.minTs));
  geometry.brushRect.setAttribute('display', 'none');
  state.chartZoomRange = { startTs, endTs };
  renderSelectedItem();
}

function closeDetailPanel() {
  state.selectedItemId = null;
  state.chartGeometry = null;
  state.chartBrush = null;
  state.chartZoomRange = null;
  el.detailPanel.classList.add('hidden');
  document.body.classList.remove('modal-open');
  renderTable();
}

async function loadSelectedItemHistory(itemId, { forceRefresh = false } = {}) {
  if (itemId === null || itemId === undefined) return;
  state.historyLoadingItemId = itemId;
  renderSelectedItem();
  try {
    await Promise.all([
      fetchItemHistory(itemId, { forceRefresh }),
      fetchItemOhlcHistory(itemId, { forceRefresh }),
    ]);
  } catch (error) {
    console.error(error);
    state.snapshots[String(itemId)] = [];
    state.ohlcSeries[`${itemId}:${getChartBucketSeconds()}`] = [];
  } finally {
    state.historyLoadingItemId = null;
    if (state.selectedItemId === itemId) {
      renderSelectedItem();
    }
  }
}

async function refreshSelectedChartData() {
  if (state.selectedItemId === null) return;
  try {
    if (state.chartMode === 'candles') {
      await fetchItemOhlcHistory(state.selectedItemId, { forceRefresh: false });
    } else {
      await fetchItemHistory(state.selectedItemId, { forceRefresh: false });
    }
  } catch (error) {
    console.error(error);
  }
  renderSelectedItem();
}

async function loadData({ forceRefresh = false } = {}) {
  el.status.textContent = forceRefresh ? 'Refreshing API data...' : 'Loading API data...';
  el.refresh.disabled = true;
  if (forceRefresh) {
    state.iconCacheBust = Date.now();
  }

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

    if (state.selectedItemId === null && state.filtered.length > 0) {
      state.selectedItemId = state.filtered[0].id;
      renderTable();
      renderSelectedItem();
      loadSelectedItemHistory(state.selectedItemId, { forceRefresh: true });
    } else if (state.selectedItemId !== null) {
      loadSelectedItemHistory(state.selectedItemId, { forceRefresh: true });
    }
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
  el.pageSize.value = '100';
  el.applyTax.checked = true;
  el.taxRate.value = '2';
  state.sortKey = 'alchProfit';
  state.sortDirection = 'desc';
  state.volumeWindow = '24h';
  state.favoritesFilter = 'all';
  state.visibleColumns = new Set(defaultColumns);
  state.pageSize = 100;
  state.selectedPreset = '';
  renderPresetOptions();
  renderColumnOptions();
  updateVolumeUiLabels();
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
  [el.search, el.members, el.favorites, el.minPrice, el.maxPrice, el.minProfit, el.minVolume, el.applyTax, el.taxRate].forEach((input) => {
    input.addEventListener('input', () => applyFilters());
    input.addEventListener('change', () => applyFilters());
  });

  el.presetSelect.addEventListener('change', () => {
    const name = el.presetSelect.value;
    state.selectedPreset = name;
    renderPresetOptions();
    if (!name || !state.presets[name]) return;
    applyPresetValues(state.presets[name]);
  });

  el.savePresetBtn.addEventListener('click', saveCurrentPreset);
  el.deletePresetBtn.addEventListener('click', deleteSelectedPreset);

  el.volumeWindow.addEventListener('change', () => {
    state.volumeWindow = VOLUME_WINDOW_LABELS[el.volumeWindow.value] ? el.volumeWindow.value : '24h';
    updateVolumeUiLabels();
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
  el.closeDetailBtn.addEventListener('click', closeDetailPanel);
  el.detailBackdrop.addEventListener('click', closeDetailPanel);
  el.detailChartRange.addEventListener('change', () => {
    state.chartRange = el.detailChartRange.value;
    state.chartZoomRange = null;
    refreshSelectedChartData();
  });
  el.detailChartMode.addEventListener('change', () => {
    state.chartMode = el.detailChartMode.value;
    state.chartZoomRange = null;
    refreshSelectedChartData();
  });
  el.detailChartVolume.addEventListener('change', () => {
    state.chartShowVolume = el.detailChartVolume.checked;
    renderSelectedItem();
  });
  el.detailChartResetZoom.addEventListener('click', () => {
    state.chartZoomRange = null;
    renderSelectedItem();
  });
  el.detailChart.addEventListener('mousedown', handleChartPointerDown);
  el.detailChart.addEventListener('mousemove', handleChartPointerMove);
  el.detailChart.addEventListener('mouseleave', () => {
    const item = state.items.find((candidate) => candidate.id === state.selectedItemId);
    if (item) {
      clearChartHover(item);
    }
  });
  document.addEventListener('mouseup', handleChartPointerUp);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.selectedItemId !== null) {
      closeDetailPanel();
    }
  });

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
state.presets = loadPresets();
renderPresetOptions();
renderColumnOptions();
updateVolumeUiLabels();
setupEvents();
loadData();
