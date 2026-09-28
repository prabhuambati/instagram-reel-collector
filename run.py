from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from collector.core import BASE_DIR, DB_PATH, connect, export_credits, import_records, process_video, records, stats, update_status
from collector.model_classifier import analyze_media

WEB_DIR = BASE_DIR / "collector" / "web"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code=200, body=b"", content_type="application/json; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            body = (WEB_DIR / "index.html").read_bytes(); return self._send(200, body, "text/html; charset=utf-8")
        if parsed.path == "/api/stats": return self._send(200, json.dumps(stats()).encode())
        if parsed.path == "/api/reels":
            q = parse_qs(parsed.query); body = json.dumps(records(q.get("q", [""])[0], q.get("status", [""])[0], int(q.get("limit", [1000])[0]))).encode(); return self._send(200, body)
        if parsed.path in {"/export/csv", "/export/json"}:
            fmt = parsed.path.rsplit("/", 1)[-1]
            path = Path(export_credits(fmt))
            return self._send(200, path.read_bytes(), "text/csv; charset=utf-8" if fmt == "csv" else "application/json; charset=utf-8")
        if parsed.path.startswith("/media/"):
            path = (BASE_DIR / "data" / "media" / parsed.path.removeprefix("/media/")).resolve()
            if path.parent != (BASE_DIR / "data" / "media").resolve() or not path.exists(): return self._send(404, b"Not found", "text/plain")
            return self._send(200, path.read_bytes(), mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        return self._send(404, b"Not found", "text/plain")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0")); raw = self.rfile.read(length)
        try:
            if parsed.path == "/api/import":
                payload = json.loads(raw.decode("utf-8")); result = import_records(payload.get("records", payload if isinstance(payload, list) else []), payload.get("source_kind", "") if isinstance(payload, dict) else "", payload.get("source_query", "") if isinstance(payload, dict) else ""); return self._send(200, json.dumps(result).encode())
            if parsed.path == "/api/status":
                payload = json.loads(raw.decode()); update_status(payload["id"], payload["status"]); return self._send(200, b'{"ok":true}')
        except Exception as exc:
            return self._send(400, json.dumps({"error": str(exc)}).encode())
        return self._send(404, b"Not found", "text/plain")


def main():
    parser = argparse.ArgumentParser(description="Local public Instagram reel music collection prototype")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    serve = sub.add_parser("serve"); serve.add_argument("--host", default="127.0.0.1"); serve.add_argument("--port", type=int, default=8765)
    imp = sub.add_parser("import-json"); imp.add_argument("path"); imp.add_argument("--source-kind", default="manual"); imp.add_argument("--source-query", default="")
    exp = sub.add_parser("export"); exp.add_argument("--format", choices=["csv", "json"], required=True); exp.add_argument("--output")
    vid = sub.add_parser("process-video"); vid.add_argument("path"); vid.add_argument("--reel-url", required=True); vid.add_argument("--username", default=""); vid.add_argument("--song-title", default=""); vid.add_argument("--song-artist", default="")
    ana = sub.add_parser("analyze-video"); ana.add_argument("path"); ana.add_argument("--caption", default=""); ana.add_argument("--source-query", default="")
    args = parser.parse_args()
    if args.command == "init": connect().close(); print(f"Initialized {DB_PATH}")
    elif args.command == "serve": connect().close(); print(f"Dashboard: http://{args.host}:{args.port}"); ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
    elif args.command == "import-json": print(import_records(json.loads(Path(args.path).read_text(encoding="utf-8")), args.source_kind, args.source_query))
    elif args.command == "export": print(export_credits(args.format, args.output))
    elif args.command == "analyze-video": print(json.dumps(analyze_media(args.path, args.caption, args.source_query), indent=2))
    elif args.command == "process-video": print(process_video(args.path, args.reel_url, args.username, args.song_title, args.song_artist))

if __name__ == "__main__": main()
