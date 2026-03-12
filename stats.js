const els = {
  statsStatus: document.getElementById('statsStatus'),
  dbSize: document.getElementById('dbSize'),
  dbPath: document.getElementById('dbPath'),
  projectedSize: document.getElementById('projectedSize'),
  rawRows: document.getElementById('rawRows'),
  snapshotCount: document.getElementById('snapshotCount'),
  rollupRows: document.getElementById('rollupRows'),
  rollupBreakdown: document.getElementById('rollupBreakdown'),
  rawRetention: document.getElementById('rawRetention'),
  hourlyRetention: document.getElementById('hourlyRetention'),
  dailyRetention: document.getElementById('dailyRetention'),
  pollInterval: document.getElementById('pollInterval'),
  rowsPerSnapshot: document.getElementById('rowsPerSnapshot'),
  bytesPerRow: document.getElementById('bytesPerRow'),
  tableRawRows: document.getElementById('tableRawRows'),
  tableHourlyRows: document.getElementById('tableHourlyRows'),
  tableDailyRows: document.getElementById('tableDailyRows'),
  tableMetaRows: document.getElementById('tableMetaRows'),
};

const fmtNumber = new Intl.NumberFormat();
const fmtDecimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) return '-';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${fmtDecimal.format(size)} ${units[unitIndex]}`;
}

function formatRetention(days) {
  if (!Number.isFinite(days)) return '-';
  return days === 0 ? 'Forever' : `${fmtNumber.format(days)} days`;
}

function formatSeconds(seconds) {
  if (!Number.isFinite(seconds)) return '-';
  if (seconds % 3600 === 0) return `${fmtNumber.format(seconds / 3600)}h`;
  if (seconds % 60 === 0) return `${fmtNumber.format(seconds / 60)}m`;
  return `${fmtNumber.format(seconds)}s`;
}

async function loadStats() {
  els.statsStatus.textContent = 'Loading storage stats...';
  try {
    const response = await fetch('/history/stats');
    if (!response.ok) {
      throw new Error(`Request failed (${response.status})`);
    }

    const stats = await response.json();
    const hourlyRows = Number(stats.hourly_rows) || 0;
    const dailyRows = Number(stats.daily_rows) || 0;

    els.dbSize.textContent = formatBytes(Number(stats.db_size_bytes));
    els.dbPath.textContent = stats.db_path || '-';
    els.projectedSize.textContent = formatBytes(Number(stats.projected_size_bytes_1y));
    els.rawRows.textContent = fmtNumber.format(Number(stats.rows) || 0);
    els.snapshotCount.textContent = `${fmtNumber.format(Number(stats.distinct_snapshots) || 0)} snapshots across ${fmtNumber.format(Number(stats.distinct_items) || 0)} items`;
    els.rollupRows.textContent = fmtNumber.format(hourlyRows + dailyRows);
    els.rollupBreakdown.textContent = `${fmtNumber.format(hourlyRows)} hourly + ${fmtNumber.format(dailyRows)} daily`;

    els.rawRetention.textContent = formatRetention(Number(stats.retention?.raw_days));
    els.hourlyRetention.textContent = formatRetention(Number(stats.retention?.hourly_days));
    els.dailyRetention.textContent = formatRetention(Number(stats.retention?.daily_days));
    els.pollInterval.textContent = formatSeconds(Number(stats.poll_interval_seconds));
    els.rowsPerSnapshot.textContent = fmtDecimal.format(Number(stats.rows_per_snapshot) || 0);
    els.bytesPerRow.textContent = formatBytes(Number(stats.bytes_per_row) || 0);

    els.tableRawRows.textContent = fmtNumber.format(Number(stats.rows) || 0);
    els.tableHourlyRows.textContent = fmtNumber.format(hourlyRows);
    els.tableDailyRows.textContent = fmtNumber.format(dailyRows);
    els.tableMetaRows.textContent = fmtNumber.format(Number(stats.meta_rows) || 0);

    els.statsStatus.textContent = 'Storage stats loaded.';
  } catch (error) {
    console.error(error);
    els.statsStatus.textContent = 'Failed to load storage stats.';
  }
}

loadStats();
