#!/usr/bin/env python3
import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UPSTREAM_BASE = "https://prices.runescape.wiki/api/v1/osrs"
DEFAULT_USER_AGENT = "OSRS-GE-PriceTool/1.2 (+https://github.com/yourname/osrs-ge-pricetool)"
ALLOWED_ENDPOINTS = {"mapping", "latest", "volumes", "5m", "1h"}


class Handler(SimpleHTTPRequestHandler):
    user_agent = DEFAULT_USER_AGENT

    @staticmethod
    def _is_client_disconnect(error):
        return isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

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
        if self.path.startswith("/api/v1/osrs/"):
            self.proxy_api()
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


def main():
    parser = argparse.ArgumentParser(description="Serve OSRS GE tool with API proxy and custom User-Agent.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", default=8080, type=int, help="Port number")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent sent to OSRS Wiki API")
    args = parser.parse_args()

    Handler.user_agent = args.user_agent
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}")
    print(f"Proxying /api/v1/osrs/* to {UPSTREAM_BASE}")
    print(f"Using User-Agent: {Handler.user_agent}")
    server.serve_forever()


if __name__ == "__main__":
    main()
