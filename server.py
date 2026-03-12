#!/usr/bin/env python3
import argparse
import json
import hashlib
import sqlite3
import threading
import time
from collections import deque
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

UPSTREAM_BASE = "https://prices.runescape.wiki/api/v1/osrs"
ICON_UPSTREAM_BASE = "https://oldschool.runescape.wiki/w/Special:FilePath"
DEFAULT_USER_AGENT = "OSRS-GE-PriceTool/1.2 (+https://github.com/yourname/osrs-ge-pricetool)"
ALLOWED_ENDPOINTS = {"mapping", "latest", "volumes", "5m", "1h"}
DEFAULT_CONFIG_PATH = "server.config.json"
DEFAULT_SETTINGS = {
    "host": "127.0.0.1",
    "port": 8080,
    "user_agent": DEFAULT_USER_AGENT,
    "mirror_icons": True,
    "icon_cache_dir": ".icon-cache",
    "icon_cache_ttl_hours": 0,
    "icon_rate_limit_count": 200,
    "icon_rate_limit_window_seconds": 600,
    "prefetch_icons": False,
    "prefetch_force": False,
    "icon_debug": False,
    "history_tracking": True,
    "history_db_path": ".price-history/osrs-ge-history.sqlite3",
    "history_poll_interval_seconds": 300,
    "history_raw_retention_days": 180,
    "history_hourly_retention_days": 730,
    "history_daily_retention_days": 0,
}


class Handler(SimpleHTTPRequestHandler):
    user_agent = DEFAULT_USER_AGENT
    mirror_icons = False
    icon_cache_dir = Path(".icon-cache")
    icon_cache_ttl_seconds = 7 * 24 * 60 * 60
    icon_debug = False
    icon_rate_limit_count = 200
    icon_rate_limit_window_seconds = 10 * 60
    icon_fetch_timestamps = deque()
    icon_rate_limit_lock = threading.Lock()
    icon_refresh_queue = deque()
    icon_refresh_queued = set()
    icon_refresh_lock = threading.Lock()
    icon_refresh_worker_started = False
    icon_refresh_interval_seconds = 1
    icon_stats_lock = threading.Lock()
    icon_stats = {
        "cache_hit_fresh": 0,
        "cache_hit_stale": 0,
        "cache_miss": 0,
        "served_stale": 0,
        "upstream_fetch_ok": 0,
        "upstream_fetch_failed": 0,
        "rate_limited_no_cache": 0,
        "refresh_queued": 0,
        "refresh_worker_updates": 0,
        "refresh_worker_failures": 0,
    }
    history_tracking = True
    history_db_path = Path(".price-history/osrs-ge-history.sqlite3")
    history_poll_interval_seconds = 300
    history_raw_retention_days = 180
    history_hourly_retention_days = 730
    history_daily_retention_days = 0
    history_db_lock = threading.Lock()
    history_worker_started = False
    index_pages = ["Index.html", "index.html"]

    @staticmethod
    def _is_client_disconnect(error):
        return isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

    @classmethod
    def _log_icon(cls, message):
        if cls.icon_debug:
            print(f"[icon] {message}")

    @classmethod
    def _inc_icon_stat(cls, key, amount=1):
        with cls.icon_stats_lock:
            cls.icon_stats[key] = cls.icon_stats.get(key, 0) + amount

    @classmethod
    def _prune_icon_fetch_timestamps(cls, now):
        while cls.icon_fetch_timestamps and (now - cls.icon_fetch_timestamps[0]) >= cls.icon_rate_limit_window_seconds:
            cls.icon_fetch_timestamps.popleft()

    @classmethod
    def try_acquire_icon_fetch_slot(cls):
        now = time.time()
        with cls.icon_rate_limit_lock:
            cls._prune_icon_fetch_timestamps(now)
            if len(cls.icon_fetch_timestamps) >= cls.icon_rate_limit_count:
                return False
            cls.icon_fetch_timestamps.append(now)
            return True

    @classmethod
    def seconds_until_icon_slot(cls):
        now = time.time()
        with cls.icon_rate_limit_lock:
            cls._prune_icon_fetch_timestamps(now)
            if len(cls.icon_fetch_timestamps) < cls.icon_rate_limit_count:
                return 0.0
            oldest = cls.icon_fetch_timestamps[0]
            return max(0.0, cls.icon_rate_limit_window_seconds - (now - oldest))

    @classmethod
    def queue_icon_refresh(cls, icon_name):
        with cls.icon_refresh_lock:
            if icon_name in cls.icon_refresh_queued:
                return
            cls.icon_refresh_queued.add(icon_name)
            cls.icon_refresh_queue.append(icon_name)
        cls._inc_icon_stat("refresh_queued")

    @classmethod
    def pop_queued_icon(cls):
        with cls.icon_refresh_lock:
            if not cls.icon_refresh_queue:
                return None
            icon_name = cls.icon_refresh_queue.popleft()
            cls.icon_refresh_queued.discard(icon_name)
            return icon_name

    @classmethod
    def ensure_icon_refresh_worker(cls):
        if not cls.mirror_icons:
            return
        with cls.icon_refresh_lock:
            if cls.icon_refresh_worker_started:
                return
            cls.icon_refresh_worker_started = True
        thread = threading.Thread(target=cls.icon_refresh_worker_loop, name="icon-refresh-worker", daemon=True)
        thread.start()
        cls._log_icon("background refresh worker started")

    @classmethod
    def icon_refresh_worker_loop(cls):
        while True:
            icon_name = cls.pop_queued_icon()
            if not icon_name:
                time.sleep(cls.icon_refresh_interval_seconds)
                continue

            cached, is_fresh = cls._load_cached_icon(icon_name)
            if not cached or is_fresh:
                continue

            while not cls.try_acquire_icon_fetch_slot():
                wait = cls.seconds_until_icon_slot()
                cls._log_icon(f"refresh queue waiting for rate-limit slot ({wait:.1f}s)")
                time.sleep(max(1.0, min(30.0, wait or 1.0)))

            try:
                body, content_type = cls.fetch_upstream_icon(icon_name)
                cls._save_cached_icon(icon_name, body, content_type)
                cls._inc_icon_stat("refresh_worker_updates")
                cls._log_icon(f"background refresh updated: {icon_name}")
            except (HTTPError, URLError, OSError) as error:
                cls._inc_icon_stat("refresh_worker_failures")
                cls._log_icon(f"background refresh failed: {icon_name} ({error})")

    @staticmethod
    def _icon_cache_key(icon_name):
        return hashlib.sha256(icon_name.encode("utf-8")).hexdigest()

    @classmethod
    def _icon_cache_paths(cls, icon_name):
        key = cls._icon_cache_key(icon_name)
        return cls.icon_cache_dir / f"{key}.bin", cls.icon_cache_dir / f"{key}.json"

    @classmethod
    def _open_history_db(cls):
        cls.history_db_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(cls.history_db_path, timeout=30, check_same_thread=False)

    @classmethod
    def init_history_db(cls):
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS price_history (
                        item_id INTEGER NOT NULL,
                        ts INTEGER NOT NULL,
                        high INTEGER,
                        low INTEGER,
                        volume_24h INTEGER,
                        PRIMARY KEY (item_id, ts)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_history_item_ts ON price_history (item_id, ts DESC)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS price_history_hourly (
                        item_id INTEGER NOT NULL,
                        bucket_ts INTEGER NOT NULL,
                        open_mid REAL,
                        high_mid REAL,
                        low_mid REAL,
                        close_mid REAL,
                        close_high INTEGER,
                        close_low INTEGER,
                        volume_avg REAL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (item_id, bucket_ts)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_history_hourly_item_ts ON price_history_hourly (item_id, bucket_ts DESC)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS price_history_daily (
                        item_id INTEGER NOT NULL,
                        bucket_ts INTEGER NOT NULL,
                        open_mid REAL,
                        high_mid REAL,
                        low_mid REAL,
                        close_mid REAL,
                        close_high INTEGER,
                        close_low INTEGER,
                        volume_avg REAL,
                        sample_count INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (item_id, bucket_ts)
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_history_daily_item_ts ON price_history_daily (item_id, bucket_ts DESC)"
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS history_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                connection.commit()

    @staticmethod
    def _bucket_start(ts, bucket_seconds):
        return int(ts) - (int(ts) % int(bucket_seconds))

    @staticmethod
    def _retention_cutoff_days(retention_days, now_ts):
        if retention_days is None or retention_days <= 0:
            return None
        return int(now_ts) - (int(retention_days) * 24 * 60 * 60)

    @classmethod
    def _load_meta_int(cls, connection, key):
        row = connection.execute("SELECT value FROM history_meta WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return None

    @classmethod
    def _save_meta_int(cls, connection, key, value):
        connection.execute(
            """
            INSERT INTO history_meta (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(int(value))),
        )

    @classmethod
    def rebuild_rollup_table(cls, connection, target_table, bucket_seconds, meta_key):
        latest_raw_ts_row = connection.execute("SELECT MAX(ts) FROM price_history").fetchone()
        latest_raw_ts = latest_raw_ts_row[0] if latest_raw_ts_row else None
        if latest_raw_ts is None:
            return

        last_rollup_ts = cls._load_meta_int(connection, meta_key)
        start_ts = None if last_rollup_ts is None else cls._bucket_start(last_rollup_ts, bucket_seconds)
        filter_sql = ""
        params = [bucket_seconds, bucket_seconds]
        if start_ts is not None:
            filter_sql = "WHERE ts >= ?"
            params.append(start_ts)

        query = f"""
            WITH bucketed AS (
                SELECT
                    item_id,
                    CAST(ts / ? AS INTEGER) * ? AS bucket_ts,
                    ts,
                    high,
                    low,
                    volume_24h,
                    CASE
                        WHEN high IS NOT NULL AND low IS NOT NULL THEN (high + low) / 2.0
                        WHEN high IS NOT NULL THEN CAST(high AS REAL)
                        WHEN low IS NOT NULL THEN CAST(low AS REAL)
                        ELSE NULL
                    END AS mid_price
                FROM price_history
                {filter_sql}
            ),
            ranked AS (
                SELECT
                    item_id,
                    bucket_ts,
                    ts,
                    high,
                    low,
                    volume_24h,
                    mid_price,
                    ROW_NUMBER() OVER (PARTITION BY item_id, bucket_ts ORDER BY ts ASC) AS rn_open,
                    ROW_NUMBER() OVER (PARTITION BY item_id, bucket_ts ORDER BY ts DESC) AS rn_close
                FROM bucketed
            ),
            aggregated AS (
                SELECT
                    item_id,
                    bucket_ts,
                    MAX(CASE WHEN rn_open = 1 THEN mid_price END) AS open_mid,
                    MAX(mid_price) AS high_mid,
                    MIN(mid_price) AS low_mid,
                    MAX(CASE WHEN rn_close = 1 THEN mid_price END) AS close_mid,
                    MAX(CASE WHEN rn_close = 1 THEN high END) AS close_high,
                    MAX(CASE WHEN rn_close = 1 THEN low END) AS close_low,
                    AVG(volume_24h) AS volume_avg,
                    COUNT(*) AS sample_count
                FROM ranked
                GROUP BY item_id, bucket_ts
            )
            INSERT OR REPLACE INTO {target_table} (
                item_id,
                bucket_ts,
                open_mid,
                high_mid,
                low_mid,
                close_mid,
                close_high,
                close_low,
                volume_avg,
                sample_count
            )
            SELECT
                item_id,
                bucket_ts,
                open_mid,
                high_mid,
                low_mid,
                close_mid,
                close_high,
                close_low,
                volume_avg,
                sample_count
            FROM aggregated
        """
        connection.execute(query, params)
        cls._save_meta_int(connection, meta_key, latest_raw_ts)

    @classmethod
    def prune_history_tables(cls, connection, now_ts):
        retention_specs = [
            ("price_history", "ts", cls.history_raw_retention_days),
            ("price_history_hourly", "bucket_ts", cls.history_hourly_retention_days),
            ("price_history_daily", "bucket_ts", cls.history_daily_retention_days),
        ]
        for table_name, time_column, retention_days in retention_specs:
            cutoff = cls._retention_cutoff_days(retention_days, now_ts)
            if cutoff is None:
                continue
            connection.execute(f"DELETE FROM {table_name} WHERE {time_column} < ?", (cutoff,))

    @classmethod
    def maintain_history_rollups(cls, connection, latest_ts=None):
        effective_now = latest_ts or int(time.time())
        cls.rebuild_rollup_table(connection, "price_history_hourly", 60 * 60, "hourly_last_rollup_ts")
        cls.rebuild_rollup_table(connection, "price_history_daily", 24 * 60 * 60, "daily_last_rollup_ts")
        cls.prune_history_tables(connection, effective_now)

    @classmethod
    def ensure_history_worker(cls):
        if not cls.history_tracking:
            return
        cls.init_history_db()
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                cls.maintain_history_rollups(connection)
                connection.commit()
            if cls.history_worker_started:
                return
            cls.history_worker_started = True
        thread = threading.Thread(target=cls.history_worker_loop, name="history-worker", daemon=True)
        thread.start()
        print("[history] background tracker started")

    @classmethod
    def history_worker_loop(cls):
        while True:
            try:
                cls.capture_market_snapshot()
            except (HTTPError, URLError, OSError, ValueError, sqlite3.DatabaseError) as error:
                print(f"[history] snapshot failed: {error}")
            time.sleep(max(60, cls.history_poll_interval_seconds))

    @classmethod
    def fetch_upstream_json(cls, endpoint, timeout=30):
        request = Request(
            f"{UPSTREAM_BASE}/{endpoint}",
            headers={
                "User-Agent": cls.user_agent,
                "Accept": "application/json",
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def extract_latest_timestamp(payload):
        if isinstance(payload, dict) and isinstance(payload.get("timestamp"), int):
            return payload["timestamp"]

        price_entries = payload.get("data", {}) if isinstance(payload, dict) else {}
        max_timestamp = None
        for entry in price_entries.values():
            if not isinstance(entry, dict):
                continue
            high_time = entry.get("highTime") if isinstance(entry.get("highTime"), int) else None
            low_time = entry.get("lowTime") if isinstance(entry.get("lowTime"), int) else None
            candidate = max(high_time or 0, low_time or 0)
            if candidate > 0 and (max_timestamp is None or candidate > max_timestamp):
                max_timestamp = candidate
        return max_timestamp

    @classmethod
    def capture_market_snapshot(cls):
        latest = cls.fetch_upstream_json("latest")
        volumes = cls.fetch_upstream_json("volumes")
        snapshot_ts = cls.extract_latest_timestamp(latest) or int(time.time())
        latest_data = latest.get("data", {}) if isinstance(latest, dict) else {}
        volume_data = volumes.get("data", {}) if isinstance(volumes, dict) else {}

        rows = []
        for raw_item_id, price in latest_data.items():
            try:
                item_id = int(raw_item_id)
            except (TypeError, ValueError):
                continue
            if not isinstance(price, dict):
                continue
            high = price.get("high") if isinstance(price.get("high"), int) else None
            low = price.get("low") if isinstance(price.get("low"), int) else None
            volume_entry = volume_data.get(raw_item_id, volume_data.get(item_id))
            if isinstance(volume_entry, dict):
                volume_24h = volume_entry.get("high")
                if not isinstance(volume_24h, int):
                    volume_24h = volume_entry.get("low") if isinstance(volume_entry.get("low"), int) else None
            elif isinstance(volume_entry, int):
                volume_24h = volume_entry
            else:
                volume_24h = None
            rows.append((item_id, snapshot_ts, high, low, volume_24h))

        if not rows:
            return

        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                connection.executemany(
                    """
                    INSERT INTO price_history (item_id, ts, high, low, volume_24h)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(item_id, ts) DO UPDATE SET
                        high=excluded.high,
                        low=excluded.low,
                        volume_24h=excluded.volume_24h
                    """,
                    rows,
                )
                cls.maintain_history_rollups(connection, latest_ts=snapshot_ts)
                connection.commit()
        print(f"[history] snapshot stored for {len(rows)} items at {snapshot_ts}")

    @classmethod
    def load_item_history(cls, item_id, limit):
        cls.init_history_db()
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                cursor = connection.execute(
                    """
                    SELECT ts, high, low, volume_24h
                    FROM price_history
                    WHERE item_id = ?
                    ORDER BY ts DESC
                    LIMIT ?
                    """,
                    (item_id, limit),
                )
                rows = cursor.fetchall()
        rows.reverse()
        return [
            {
                "ts": row[0] * 1000,
                "high": row[1],
                "low": row[2],
                "volume": row[3],
            }
            for row in rows
        ]

    @classmethod
    def load_item_rollup_history(cls, item_id, limit, source):
        cls.init_history_db()
        table_name = "price_history_hourly" if source == "hourly" else "price_history_daily"
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                cursor = connection.execute(
                    f"""
                    SELECT bucket_ts, close_high, close_low, volume_avg, sample_count
                    FROM {table_name}
                    WHERE item_id = ?
                    ORDER BY bucket_ts DESC
                    LIMIT ?
                    """,
                    (item_id, limit),
                )
                rows = cursor.fetchall()
        rows.reverse()
        return [
            {
                "ts": row[0] * 1000,
                "high": row[1],
                "low": row[2],
                "volume": round(row[3]) if row[3] is not None else None,
                "sample_count": row[4],
            }
            for row in rows
        ]

    @classmethod
    def load_item_history_ohlc(cls, item_id, limit, bucket_seconds):
        raw_entries = cls.load_item_history(item_id, limit)
        buckets = []
        current_bucket = None

        for entry in raw_entries:
            ts_ms = entry["ts"]
            ts_seconds = ts_ms // 1000
            bucket_start = ts_seconds - (ts_seconds % bucket_seconds)
            mid_price = None
            high = entry.get("high")
            low = entry.get("low")
            if isinstance(high, (int, float)) and isinstance(low, (int, float)):
                mid_price = (high + low) / 2
            elif isinstance(high, (int, float)):
                mid_price = high
            elif isinstance(low, (int, float)):
                mid_price = low

            if current_bucket is None or current_bucket["bucket_start"] != bucket_start:
                if current_bucket is not None:
                    buckets.append(current_bucket)
                current_bucket = {
                    "bucket_start": bucket_start,
                    "open": mid_price,
                    "high": mid_price,
                    "low": mid_price,
                    "close": mid_price,
                    "volume_sum": 0,
                    "volume_count": 0,
                    "sample_count": 0,
                }

            current_bucket["sample_count"] += 1
            if isinstance(entry.get("volume"), (int, float)):
                current_bucket["volume_sum"] += entry["volume"]
                current_bucket["volume_count"] += 1

            if mid_price is None:
                continue

            if current_bucket["open"] is None:
                current_bucket["open"] = mid_price
            current_bucket["close"] = mid_price
            current_bucket["high"] = mid_price if current_bucket["high"] is None else max(current_bucket["high"], mid_price)
            current_bucket["low"] = mid_price if current_bucket["low"] is None else min(current_bucket["low"], mid_price)

        if current_bucket is not None:
            buckets.append(current_bucket)

        return [
            {
                "ts": bucket["bucket_start"] * 1000,
                "open": round(bucket["open"]) if bucket["open"] is not None else None,
                "high": round(bucket["high"]) if bucket["high"] is not None else None,
                "low": round(bucket["low"]) if bucket["low"] is not None else None,
                "close": round(bucket["close"]) if bucket["close"] is not None else None,
                "volume": round(bucket["volume_sum"] / bucket["volume_count"]) if bucket["volume_count"] else None,
                "sample_count": bucket["sample_count"],
            }
            for bucket in buckets
        ]

    @classmethod
    def load_item_rollup_ohlc(cls, item_id, limit, source):
        cls.init_history_db()
        table_name = "price_history_hourly" if source == "hourly" else "price_history_daily"
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                cursor = connection.execute(
                    f"""
                    SELECT bucket_ts, open_mid, high_mid, low_mid, close_mid, volume_avg, sample_count
                    FROM {table_name}
                    WHERE item_id = ?
                    ORDER BY bucket_ts DESC
                    LIMIT ?
                    """,
                    (item_id, limit),
                )
                rows = cursor.fetchall()
        rows.reverse()
        return [
            {
                "ts": row[0] * 1000,
                "open": round(row[1]) if row[1] is not None else None,
                "high": round(row[2]) if row[2] is not None else None,
                "low": round(row[3]) if row[3] is not None else None,
                "close": round(row[4]) if row[4] is not None else None,
                "volume": round(row[5]) if row[5] is not None else None,
                "sample_count": row[6],
            }
            for row in rows
        ]

    @classmethod
    def load_history_stats(cls):
        cls.init_history_db()
        db_size_bytes = cls.history_db_path.stat().st_size if cls.history_db_path.exists() else 0
        with cls.history_db_lock:
            with cls._open_history_db() as connection:
                row = connection.execute(
                    """
                    SELECT
                        COUNT(*) AS rows,
                        COUNT(DISTINCT item_id) AS items,
                        MIN(ts) AS min_ts,
                        MAX(ts) AS max_ts,
                        COUNT(DISTINCT ts) AS snapshots
                    FROM price_history
                    """
                ).fetchone()
                hourly_rows = connection.execute("SELECT COUNT(*) FROM price_history_hourly").fetchone()[0]
                daily_rows = connection.execute("SELECT COUNT(*) FROM price_history_daily").fetchone()[0]
                meta_rows = connection.execute("SELECT COUNT(*) FROM history_meta").fetchone()[0]

        rows = int(row[0] or 0)
        items = int(row[1] or 0)
        min_ts = row[2]
        max_ts = row[3]
        snapshots = int(row[4] or 0)
        span_seconds = max(0, int(max_ts - min_ts)) if min_ts is not None and max_ts is not None else 0
        rows_per_snapshot = (rows / snapshots) if snapshots else 0.0
        bytes_per_row = (db_size_bytes / rows) if rows else 0.0
        snapshots_per_year = (365 * 24 * 60 * 60) / max(60, cls.history_poll_interval_seconds)
        projected_rows = rows_per_snapshot * snapshots_per_year
        projected_size_bytes = projected_rows * bytes_per_row

        return {
            "db_path": str(cls.history_db_path),
            "db_size_bytes": db_size_bytes,
            "rows": rows,
            "distinct_items": items,
            "distinct_snapshots": snapshots,
            "hourly_rows": int(hourly_rows or 0),
            "daily_rows": int(daily_rows or 0),
            "meta_rows": int(meta_rows or 0),
            "min_ts": min_ts,
            "max_ts": max_ts,
            "span_seconds": span_seconds,
            "rows_per_snapshot": rows_per_snapshot,
            "bytes_per_row": bytes_per_row,
            "poll_interval_seconds": cls.history_poll_interval_seconds,
            "retention": {
                "raw_days": cls.history_raw_retention_days,
                "hourly_days": cls.history_hourly_retention_days,
                "daily_days": cls.history_daily_retention_days,
            },
            "projected_rows_1y": projected_rows,
            "projected_size_bytes_1y": projected_size_bytes,
        }

    @classmethod
    def _load_cached_icon(cls, icon_name):
        body_path, meta_path = cls._icon_cache_paths(icon_name)
        if not body_path.exists() or not meta_path.exists():
            return None, False

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            fetched_at = float(meta.get("fetched_at", 0))
            content_type = meta.get("content_type", "image/png")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None, False

        is_fresh = cls.icon_cache_ttl_seconds <= 0 or (time.time() - fetched_at) < cls.icon_cache_ttl_seconds
        return (body, content_type), is_fresh

    @classmethod
    def _save_cached_icon(cls, icon_name, body, content_type):
        body_path, meta_path = cls._icon_cache_paths(icon_name)
        cls.icon_cache_dir.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        meta = {
            "content_type": content_type or "image/png",
            "fetched_at": time.time(),
        }
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    @classmethod
    def fetch_upstream_icon(cls, icon_name):
        icon_url = f"{ICON_UPSTREAM_BASE}/{quote(icon_name, safe='')}"
        request = Request(
            icon_url,
            headers={
                "User-Agent": cls.user_agent,
                "Accept": "image/*",
            },
            method="GET",
        )
        with urlopen(request, timeout=20) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "image/png")
        return body, content_type

    @classmethod
    def prefetch_icons(cls, icon_names, force=False):
        total = len(icon_names)
        fetched = 0
        skipped_fresh = 0
        failed = 0
        print(f"[icon] Prefetch start: {total} icon names")
        for index, icon_name in enumerate(icon_names, start=1):
            cached, is_fresh = cls._load_cached_icon(icon_name)
            if cached and is_fresh and not force:
                skipped_fresh += 1
                continue
            try:
                while not cls.try_acquire_icon_fetch_slot():
                    wait = cls.seconds_until_icon_slot()
                    cls._log_icon(f"prefetch waiting for rate-limit slot ({wait:.1f}s)")
                    time.sleep(max(1.0, min(30.0, wait or 1.0)))
                body, content_type = cls.fetch_upstream_icon(icon_name)
                cls._save_cached_icon(icon_name, body, content_type)
                fetched += 1
            except (HTTPError, URLError, OSError) as error:
                failed += 1
                cls._log_icon(f"prefetch failed [{index}/{total}] name={icon_name!r} error={error}")
            if index % 200 == 0:
                print(f"[icon] Prefetch progress: {index}/{total}")
        print(
            f"[icon] Prefetch done: fetched={fetched}, skipped_fresh={skipped_fresh}, failed={failed}, total={total}"
        )

    def end_headers(self):
        # Baseline hardening headers for both static assets and proxied responses.
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
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/v1/osrs/"):
            self.proxy_api()
            return
        if parsed.path == "/icon/stats":
            self.send_icon_stats()
            return
        if parsed.path == "/history/stats":
            self.send_history_stats()
            return
        if parsed.path == "/history":
            self.send_history(parsed.query)
            return
        if parsed.path == "/icon":
            self.proxy_icon(parsed.query)
            return
        super().do_GET()

    def proxy_api(self):
        endpoint = self.path[len("/api/v1/osrs/") :]
        if not endpoint or "?" in endpoint or endpoint not in ALLOWED_ENDPOINTS:
            self.send_error(400, "Invalid API endpoint")
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
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {"error": "Upstream request failed", "details": str(error)}
            try:
                self.wfile.write(json.dumps(payload).encode("utf-8"))
            except OSError as write_error:
                if not self._is_client_disconnect(write_error):
                    raise
            return

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def proxy_icon(self, query):
        params = parse_qs(query)
        icon_name = params.get("name", [None])[0]
        if not icon_name or len(icon_name) > 200:
            self._log_icon(f"bad request: name={icon_name!r}")
            self.send_error(400, "Invalid icon name")
            return

        # Always serve from local cache first if present, even when stale.
        cached, is_fresh = self._load_cached_icon(icon_name)
        if cached and is_fresh:
            self._inc_icon_stat("cache_hit_fresh")
            self._log_icon(f"cache hit (fresh): {icon_name}")
            body, content_type = cached
            self._send_icon(body, content_type)
            return

        if cached and not is_fresh:
            self._inc_icon_stat("cache_hit_stale")
            self._inc_icon_stat("served_stale")
            self._log_icon(f"cache hit (stale): {icon_name} (serving stale, queueing refresh)")
            body, content_type = cached
            self._send_icon(body, content_type)
            if self.mirror_icons:
                self.queue_icon_refresh(icon_name)
            return
        self._inc_icon_stat("cache_miss")

        if not self.try_acquire_icon_fetch_slot():
            wait = self.seconds_until_icon_slot()
            self._inc_icon_stat("rate_limited_no_cache")
            self._log_icon(f"rate-limited with no cache: {icon_name} (retry after {wait:.1f}s)")
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Retry-After", str(max(1, int(wait))))
            self.end_headers()
            try:
                self.wfile.write(b"Icon temporarily rate-limited")
            except OSError as write_error:
                if not self._is_client_disconnect(write_error):
                    raise
            return

        try:
            body, content_type = self.fetch_upstream_icon(icon_name)
            self._inc_icon_stat("upstream_fetch_ok")
            self._log_icon(f"upstream fetch ok: {icon_name}")
        except (HTTPError, URLError) as error:
            self._inc_icon_stat("upstream_fetch_failed")
            self._log_icon(f"upstream fetch failed: {icon_name} ({error})")
            if cached:
                self._log_icon(f"serving stale cache: {icon_name}")
                body, content_type = cached
                self._send_icon(body, content_type)
                return
            self.send_error(502, "Icon fetch failed")
            return

        if self.mirror_icons:
            try:
                self._save_cached_icon(icon_name, body, content_type)
                self._log_icon(f"cache write: {icon_name}")
            except OSError:
                # Cache writes are best-effort.
                self._log_icon(f"cache write failed: {icon_name}")
                pass

        self._send_icon(body, content_type)

    def _send_icon(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type or "image/png")
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def send_icon_stats(self):
        now = time.time()
        with self.icon_rate_limit_lock:
            self._prune_icon_fetch_timestamps(now)
            budget_used = len(self.icon_fetch_timestamps)
        with self.icon_refresh_lock:
            queue_length = len(self.icon_refresh_queue)
            queued_set_size = len(self.icon_refresh_queued)
        with self.icon_stats_lock:
            counters = dict(self.icon_stats)

        cache_files = 0
        if self.icon_cache_dir.exists():
            cache_files = sum(1 for _ in self.icon_cache_dir.glob("*.json"))

        payload = {
            "mirror_icons": self.mirror_icons,
            "cache_dir": str(self.icon_cache_dir),
            "cache_ttl_seconds": self.icon_cache_ttl_seconds,
            "cached_icon_count": cache_files,
            "rate_limit": {
                "count": self.icon_rate_limit_count,
                "window_seconds": self.icon_rate_limit_window_seconds,
                "used_in_window": budget_used,
                "remaining_in_window": max(0, self.icon_rate_limit_count - budget_used),
                "seconds_until_next_slot": self.seconds_until_icon_slot(),
            },
            "refresh_queue": {
                "queued_items": queue_length,
                "queued_unique_items": queued_set_size,
                "worker_started": self.icon_refresh_worker_started,
            },
            "counters": counters,
            "timestamp": now,
        }

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def send_history(self, query):
        params = parse_qs(query)
        item_id_value = params.get("id", [None])[0]
        limit_value = params.get("limit", [1000])[0]
        aggregate = params.get("aggregate", ["raw"])[0]
        source = params.get("source", ["raw"])[0]
        bucket_seconds_value = params.get("bucket_seconds", [3600])[0]

        try:
            item_id = coerce_int(item_id_value, "id")
            limit = coerce_int(limit_value, "limit")
            bucket_seconds = coerce_int(bucket_seconds_value, "bucket_seconds", minimum=60)
            if aggregate not in {"raw", "ohlc"}:
                raise ValueError(f"Invalid aggregate value: {aggregate!r}")
            if source not in {"raw", "hourly", "daily"}:
                raise ValueError(f"Invalid source value: {source!r}")
        except ValueError as error:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps({"error": str(error)}).encode("utf-8"))
            except OSError as write_error:
                if not self._is_client_disconnect(write_error):
                    raise
            return

        try:
            if aggregate == "ohlc":
                if source == "raw":
                    entries = self.load_item_history_ohlc(item_id, min(limit, 10000), bucket_seconds)
                else:
                    entries = self.load_item_rollup_ohlc(item_id, min(limit, 10000), source)
            else:
                if source == "raw":
                    entries = self.load_item_history(item_id, min(limit, 5000))
                else:
                    entries = self.load_item_rollup_history(item_id, min(limit, 10000), source)
        except sqlite3.DatabaseError as error:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps({"error": "History database unavailable", "details": str(error)}).encode("utf-8"))
            except OSError as write_error:
                if not self._is_client_disconnect(write_error):
                    raise
            return

        body = json.dumps(
            {
                "item_id": item_id,
                "aggregate": aggregate,
                "source": source,
                "bucket_seconds": bucket_seconds if aggregate == "ohlc" else None,
                "entries": entries,
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise

    def send_history_stats(self):
        try:
            payload = self.load_history_stats()
        except sqlite3.DatabaseError as error:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps({"error": "History stats unavailable", "details": str(error)}).encode("utf-8"))
            except OSError as write_error:
                if not self._is_client_disconnect(write_error):
                    raise
            return

        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError as write_error:
            if not self._is_client_disconnect(write_error):
                raise


def fetch_mapping_icon_names(user_agent):
    request = Request(
        f"{UPSTREAM_BASE}/mapping",
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
        method="GET",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    mapping_items = payload if isinstance(payload, list) else payload.get("data", [])
    icon_names = set()
    for item in mapping_items:
        if not isinstance(item, dict):
            continue
        icon_name = item.get("icon")
        if isinstance(icon_name, str) and icon_name:
            icon_names.add(icon_name)
    return sorted(icon_names)


def load_config(path_value):
    path = Path(path_value)
    if not path.exists():
        return {}, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ValueError(f"Failed to parse config file '{path}': {error}") from error
    if not isinstance(payload, dict):
        raise ValueError(f"Config file '{path}' must contain a JSON object at top level")
    return payload, True


def resolve_setting(cli_value, config, key):
    if cli_value is not None:
        return cli_value
    if key in config:
        return config[key]
    return DEFAULT_SETTINGS[key]


def coerce_bool(value, key):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Invalid boolean value for '{key}': {value!r}")


def coerce_int(value, key, minimum=1):
    if isinstance(value, bool):
        raise ValueError(f"Invalid integer value for '{key}': {value!r}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid integer value for '{key}': {value!r}") from error
    if parsed < minimum:
        raise ValueError(f"Value for '{key}' must be >= {minimum}, got {parsed}")
    return parsed


def main():
    parser = argparse.ArgumentParser(description="Serve OSRS GE tool with API proxy and custom User-Agent.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to JSON config file for default behavior")
    parser.add_argument("--host", default=None, help="Host interface to bind")
    parser.add_argument("--port", default=None, type=int, help="Port number")
    parser.add_argument("--user-agent", default=None, help="User-Agent sent to OSRS Wiki API")
    parser.add_argument(
        "--mirror-icons",
        dest="mirror_icons",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable local icon mirroring",
    )
    parser.add_argument("--icon-cache-dir", default=None, help="Directory for mirrored icon cache")
    parser.add_argument("--icon-cache-ttl-hours", default=None, type=int, help="Max icon cache age before refresh (0 = never refresh)")
    parser.add_argument("--icon-rate-limit-count", default=None, type=int, help="Max icon fetches per rate-limit window")
    parser.add_argument("--icon-rate-limit-window-seconds", default=None, type=int, help="Rate-limit window in seconds")
    parser.add_argument(
        "--prefetch-icons",
        dest="prefetch_icons",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable icon prefetch from mapping at startup",
    )
    parser.add_argument(
        "--prefetch-force",
        dest="prefetch_force",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable forced refresh during prefetch",
    )
    parser.add_argument(
        "--icon-debug",
        dest="icon_debug",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable verbose icon cache/fetch logging",
    )
    parser.add_argument(
        "--history-tracking",
        dest="history_tracking",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable background market history tracking",
    )
    parser.add_argument("--history-db-path", default=None, help="SQLite file path for stored market history")
    parser.add_argument(
        "--history-poll-interval-seconds",
        default=None,
        type=int,
        help="Background market snapshot interval in seconds",
    )
    parser.add_argument(
        "--history-raw-retention-days",
        default=None,
        type=int,
        help="Raw snapshot retention in days (0 = keep forever)",
    )
    parser.add_argument(
        "--history-hourly-retention-days",
        default=None,
        type=int,
        help="Hourly rollup retention in days (0 = keep forever)",
    )
    parser.add_argument(
        "--history-daily-retention-days",
        default=None,
        type=int,
        help="Daily rollup retention in days (0 = keep forever)",
    )
    args = parser.parse_args()

    config_data, config_loaded = load_config(args.config)

    resolved_host = resolve_setting(args.host, config_data, "host")
    resolved_port = coerce_int(resolve_setting(args.port, config_data, "port"), "port")
    resolved_user_agent = resolve_setting(args.user_agent, config_data, "user_agent")
    resolved_mirror_icons = coerce_bool(resolve_setting(args.mirror_icons, config_data, "mirror_icons"), "mirror_icons")
    resolved_icon_cache_dir = resolve_setting(args.icon_cache_dir, config_data, "icon_cache_dir")
    resolved_ttl_hours = coerce_int(
        resolve_setting(args.icon_cache_ttl_hours, config_data, "icon_cache_ttl_hours"), "icon_cache_ttl_hours", minimum=0
    )
    resolved_rate_limit_count = coerce_int(
        resolve_setting(args.icon_rate_limit_count, config_data, "icon_rate_limit_count"), "icon_rate_limit_count"
    )
    resolved_rate_limit_window = coerce_int(
        resolve_setting(args.icon_rate_limit_window_seconds, config_data, "icon_rate_limit_window_seconds"),
        "icon_rate_limit_window_seconds",
    )
    resolved_prefetch_icons = coerce_bool(resolve_setting(args.prefetch_icons, config_data, "prefetch_icons"), "prefetch_icons")
    resolved_prefetch_force = coerce_bool(resolve_setting(args.prefetch_force, config_data, "prefetch_force"), "prefetch_force")
    resolved_icon_debug = coerce_bool(resolve_setting(args.icon_debug, config_data, "icon_debug"), "icon_debug")
    resolved_history_tracking = coerce_bool(
        resolve_setting(args.history_tracking, config_data, "history_tracking"), "history_tracking"
    )
    resolved_history_db_path = resolve_setting(args.history_db_path, config_data, "history_db_path")
    resolved_history_poll_interval = coerce_int(
        resolve_setting(args.history_poll_interval_seconds, config_data, "history_poll_interval_seconds"),
        "history_poll_interval_seconds",
        minimum=60,
    )
    resolved_history_raw_retention = coerce_int(
        resolve_setting(args.history_raw_retention_days, config_data, "history_raw_retention_days"),
        "history_raw_retention_days",
        minimum=0,
    )
    resolved_history_hourly_retention = coerce_int(
        resolve_setting(args.history_hourly_retention_days, config_data, "history_hourly_retention_days"),
        "history_hourly_retention_days",
        minimum=0,
    )
    resolved_history_daily_retention = coerce_int(
        resolve_setting(args.history_daily_retention_days, config_data, "history_daily_retention_days"),
        "history_daily_retention_days",
        minimum=0,
    )

    Handler.user_agent = resolved_user_agent
    Handler.mirror_icons = resolved_mirror_icons
    Handler.icon_cache_dir = Path(resolved_icon_cache_dir)
    Handler.icon_cache_ttl_seconds = resolved_ttl_hours * 60 * 60
    Handler.icon_debug = resolved_icon_debug
    Handler.icon_rate_limit_count = resolved_rate_limit_count
    Handler.icon_rate_limit_window_seconds = resolved_rate_limit_window
    Handler.history_tracking = resolved_history_tracking
    Handler.history_db_path = Path(resolved_history_db_path)
    Handler.history_poll_interval_seconds = resolved_history_poll_interval
    Handler.history_raw_retention_days = resolved_history_raw_retention
    Handler.history_hourly_retention_days = resolved_history_hourly_retention
    Handler.history_daily_retention_days = resolved_history_daily_retention
    if resolved_prefetch_icons and not Handler.mirror_icons:
        Handler.mirror_icons = True
        print("[icon] --prefetch-icons requested, enabling --mirror-icons automatically")
    if Handler.mirror_icons:
        Handler.ensure_icon_refresh_worker()
    if Handler.history_tracking:
        Handler.ensure_history_worker()

    if resolved_prefetch_icons:
        try:
            icon_names = fetch_mapping_icon_names(Handler.user_agent)
            Handler.prefetch_icons(icon_names, force=resolved_prefetch_force)
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as error:
            print(f"[icon] Prefetch failed: {error}")

    server = ThreadingHTTPServer((resolved_host, resolved_port), Handler)
    print(f"Serving on http://{resolved_host}:{resolved_port}")
    print(f"Proxying /api/v1/osrs/* to {UPSTREAM_BASE}")
    print(f"Using User-Agent: {Handler.user_agent}")
    print(f"Config file: {args.config} ({'loaded' if config_loaded else 'not found, using built-in defaults'})")
    print(f"Icon route: /icon?name=<icon>")
    print("History route: /history?id=<item_id>&limit=<rows>")
    print(
        f"Icon mirroring: {'enabled' if Handler.mirror_icons else 'disabled'} "
        f"(dir={Handler.icon_cache_dir}, ttl={'never' if resolved_ttl_hours == 0 else f'{resolved_ttl_hours}h'})"
    )
    print(f"Icon rate-limit budget: {Handler.icon_rate_limit_count}/{Handler.icon_rate_limit_window_seconds}s")
    print(
        f"History tracking: {'enabled' if Handler.history_tracking else 'disabled'} "
        f"(db={Handler.history_db_path}, poll={Handler.history_poll_interval_seconds}s, "
        f"retention raw={Handler.history_raw_retention_days}d hourly={Handler.history_hourly_retention_days}d "
        f"daily={'forever' if Handler.history_daily_retention_days == 0 else f'{Handler.history_daily_retention_days}d'})"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
