const API_BASE = 'https://prices.runescape.wiki/api/v1/osrs';
const USER_AGENT = 'OSRS-GE-PriceTool/1.1';
const NATURE_RUNE_ITEM_ID = 561;

const columnConfig = [
  { key: 'name', label: 'Item', alwaysVisible: true },
  { key: 'high', label: 'Buy (high)' },
  { key: 'low', label: 'Sell (low)' },
  { key: 'spread', label: 'Spread' },
  { key: 'highalch', label: 'High Alch' },
  { key: 'lowalch', label: 'Low Alch' },
  { key: 'value', label: 'Store Value' },
  { key: 'volume', label: 'Trade Volume (24h)' },
  { key: 'alchProfit', label: 'Alch Profit*' },
];

const defaultColumns = new Set(['name', 'high', 'low', 'spread', 'highalch', 'value', 'volume', 'alchProfit']);

const state = {
  items: [],
  filtered: [],
  sortKey: 'alchProfit',
  sortDirection: 'desc',
  latestTimestamp: null,
  natureRunePrice: null,
  visibleColumns: new Set(defaultColumns),
};

const el = {
  search: document.getElementById('searchInput'),
  members: document.getElementById('memberFilter'),
  minPrice: document.getElementById('minPriceInput'),
  maxPrice: document.getElementById('maxPriceInput'),
  minProfit: document.getElementById('minProfitInput'),
  status: document.getElementById('status'),
  count: document.getElementById('count'),
  updated: document.getElementById('updated'),
  natureRunePrice: document.getElementById('natureRunePrice'),
  tbody: document.getElementById('tableBody'),
  refresh: document.getElementById('refreshBtn'),
  reset: document.getElementById('resetBtn'),
  headers: document.querySelectorAll('th[data-key]'),
  columnOptions: document.getElementById('columnOptions'),
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

function normalizeNum(inputValue) {
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

function applyFilters() {
  const query = el.search.value.trim().toLowerCase();
  const membersFilter = el.members.value;
  const minPrice = normalizeNum(el.minPrice.value);
  const maxPrice = normalizeNum(el.maxPrice.value);
  const minProfit = normalizeNum(el.minProfit.value);

  state.filtered = state.items.filter((item) => {
    if (query && !item.name.toLowerCase().includes(query)) return false;

    if (membersFilter === 'members' && !item.members) return false;
    if (membersFilter === 'f2p' && item.members) return false;

    if (minPrice !== null && (item.high ?? -1) < minPrice) return false;
    if (maxPrice !== null && (item.high ?? Number.MAX_SAFE_INTEGER) > maxPrice) return false;
    if (minProfit !== null && (item.alchProfit ?? Number.NEGATIVE_INFINITY) < minProfit) return false;

    return true;
  });

  state.filtered = sortItems(state.filtered);
  renderTable();
}

function renderTable() {
  const rows = state.filtered
    .map((item) => {
      const profitClass = item.alchProfit > 0 ? 'pos' : item.alchProfit < 0 ? 'neg' : '';

      return `
        <tr>
          <td>${item.name}</td>
          <td>${formatCoins(item.high)}</td>
          <td>${formatCoins(item.low)}</td>
          <td>${formatCoins(item.spread)}</td>
          <td>${formatCoins(item.highalch)}</td>
          <td>${formatCoins(item.lowalch)}</td>
          <td>${formatCoins(item.value)}</td>
          <td>${formatVolume(item.volume)}</td>
          <td class="${profitClass}">${formatCoins(item.alchProfit)}</td>
        </tr>
      `;
    })
    .join('');

  el.tbody.innerHTML = rows;
  el.count.textContent = `Visible items: ${fmtNumber.format(state.filtered.length)} / ${fmtNumber.format(state.items.length)}`;
  updateVisibleColumns();
}

async function fetchJson(endpoint) {
  const response = await fetch(`${API_BASE}/${endpoint}`, {
    headers: {
      'User-Agent': USER_AGENT,
    },
  });

  if (!response.ok) {
    throw new Error(`Request failed (${response.status}) for ${endpoint}`);
  }

  return response.json();
}

function mergeData(mapping, latest, volumes) {
  const priceMap = latest.data || {};
  const volumeMap = volumes.data || {};

  const natureRunePriceData = priceMap[NATURE_RUNE_ITEM_ID] || {};
  state.natureRunePrice = natureRunePriceData.high ?? natureRunePriceData.low ?? null;

  return mapping.data
    .map((item) => {
      const price = priceMap[item.id] || {};
      const volume = volumeMap[item.id] || {};
      const high = price.high ?? null;
      const low = price.low ?? null;
      const highalch = item.highalch ?? null;
      const lowalch = item.lowalch ?? null;
      const value = item.value ?? null;
      const dailyVolume = volume.high ?? volume.low ?? null;
      const spread = high !== null && low !== null ? high - low : null;
      const alchProfit =
        high !== null && highalch !== null && state.natureRunePrice !== null
          ? highalch - high - state.natureRunePrice
          : null;

      return {
        id: item.id,
        name: item.name,
        members: Boolean(item.members),
        high,
        low,
        spread,
        highalch,
        lowalch,
        value,
        volume: dailyVolume,
        alchProfit,
      };
    })
    .filter((item) => item.high !== null || item.low !== null);
}

function renderNatureRuneStatus() {
  if (state.natureRunePrice === null) {
    el.natureRunePrice.textContent = 'Nature rune price: unavailable';
    return;
  }

  el.natureRunePrice.textContent = `Nature rune price used: ${formatCoins(state.natureRunePrice)}`;
}

async function loadData() {
  el.status.textContent = 'Loading API data...';
  el.refresh.disabled = true;

  try {
    const [mapping, latest, volumes] = await Promise.all([
      fetchJson('mapping'),
      fetchJson('latest'),
      fetchJson('volumes'),
    ]);

    state.items = mergeData(mapping, latest, volumes);
    state.latestTimestamp = latest.timestamp;

    const updatedAt = state.latestTimestamp ? new Date(state.latestTimestamp * 1000).toLocaleString() : 'Unknown';
    el.status.textContent = 'Data loaded successfully.';
    el.updated.textContent = `Last update: ${updatedAt}`;
    renderNatureRuneStatus();

    applyFilters();
  } catch (error) {
    console.error(error);
    el.status.textContent = 'Failed to load API data. If opened locally, run through a simple HTTP server to avoid CORS issues.';
  } finally {
    el.refresh.disabled = false;
  }
}

function resetFilters() {
  el.search.value = '';
  el.members.value = 'all';
  el.minPrice.value = '';
  el.maxPrice.value = '';
  el.minProfit.value = '';
  state.sortKey = 'alchProfit';
  state.sortDirection = 'desc';
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
  [el.search, el.members, el.minPrice, el.maxPrice, el.minProfit].forEach((input) => {
    input.addEventListener('input', applyFilters);
    input.addEventListener('change', applyFilters);
  });

  el.refresh.addEventListener('click', loadData);
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

      applyFilters();
    });
  });
}

renderColumnOptions();
setupEvents();
loadData();
