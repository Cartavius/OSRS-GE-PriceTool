#!/usr/bin/env python3
import argparse
import json
import hashlib
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
    "mirror_icons": False,
    "icon_cache_dir": ".icon-cache",
    "icon_cache_ttl_hours": 168,
    "icon_rate_limit_count": 200,
    "icon_rate_limit_window_seconds": 600,
    "prefetch_icons": False,
    "prefetch_force": False,
    "icon_debug": False,
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

        is_fresh = (time.time() - fetched_at) < cls.icon_cache_ttl_seconds
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
    parser.add_argument("--icon-cache-ttl-hours", default=None, type=int, help="Max icon cache age before refresh")
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
    args = parser.parse_args()

    config_data, config_loaded = load_config(args.config)

    resolved_host = resolve_setting(args.host, config_data, "host")
    resolved_port = coerce_int(resolve_setting(args.port, config_data, "port"), "port")
    resolved_user_agent = resolve_setting(args.user_agent, config_data, "user_agent")
    resolved_mirror_icons = coerce_bool(resolve_setting(args.mirror_icons, config_data, "mirror_icons"), "mirror_icons")
    resolved_icon_cache_dir = resolve_setting(args.icon_cache_dir, config_data, "icon_cache_dir")
    resolved_ttl_hours = coerce_int(
        resolve_setting(args.icon_cache_ttl_hours, config_data, "icon_cache_ttl_hours"), "icon_cache_ttl_hours"
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

    Handler.user_agent = resolved_user_agent
    Handler.mirror_icons = resolved_mirror_icons
    Handler.icon_cache_dir = Path(resolved_icon_cache_dir)
    Handler.icon_cache_ttl_seconds = resolved_ttl_hours * 60 * 60
    Handler.icon_debug = resolved_icon_debug
    Handler.icon_rate_limit_count = resolved_rate_limit_count
    Handler.icon_rate_limit_window_seconds = resolved_rate_limit_window
    if resolved_prefetch_icons and not Handler.mirror_icons:
        Handler.mirror_icons = True
        print("[icon] --prefetch-icons requested, enabling --mirror-icons automatically")
    if Handler.mirror_icons:
        Handler.ensure_icon_refresh_worker()

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
    print(
        f"Icon mirroring: {'enabled' if Handler.mirror_icons else 'disabled'} "
        f"(dir={Handler.icon_cache_dir}, ttl={resolved_ttl_hours}h)"
    )
    print(f"Icon rate-limit budget: {Handler.icon_rate_limit_count}/{Handler.icon_rate_limit_window_seconds}s")
    server.serve_forever()


if __name__ == "__main__":
    main()
