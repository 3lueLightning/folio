#!/usr/bin/env python3
"""Serve a folio so that Save writes straight back to the source file.

    python serve_folio.py deck.md

A browser will not let a page overwrite a file you opened by double-clicking
it. Served from localhost the same page can post its changes back, so this
script runs a small local server that accepts them, writes the Markdown source
and rebuilds the HTML. Nothing leaves the machine and nothing is installed.

Stop it with Ctrl+C when you are done. The built .html file stays behind and
keeps working on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_folio import build  # noqa: E402
from folio_model import apply_edits, model_to_markdown, parse_markdown  # noqa: E402

STATE: dict[str, Path] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:  # keep the console readable
        pass

    def _send(self, code: int, body: bytes, mime: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].lstrip("/")
        if path == "__folio/ping":
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path in ("", "index.html", STATE["html"].name):
            self._send(200, STATE["html"].read_bytes(), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0].lstrip("/") != "__folio/save":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            edits = json.loads(self.rfile.read(length) or b"{}")

            source = STATE["source"]
            model = parse_markdown(source.read_text(encoding="utf-8"))
            changed = apply_edits(model, edits)
            source.write_text(model_to_markdown(model), encoding="utf-8")
            build(source, output=STATE["html"], quiet=True)

            print(f"  saved {changed} change(s) -> {source.name}")
            self._send(
                200,
                json.dumps({"ok": True, "changed": changed, "source": source.name}).encode(),
                "application/json",
            )
        except Exception as error:  # noqa: BLE001 - always answer the browser
            print(f"  save failed: {error}")
            self._send(500, json.dumps({"error": str(error)}).encode(), "application/json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Edit a folio with save-to-source.")
    parser.add_argument("source", type=Path, help="the .md source file")
    parser.add_argument("-p", "--port", type=int, default=8777)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.exists():
        print(f"Source not found: {source}", file=sys.stderr)
        return 1

    html, _ = build(source)
    STATE["source"] = source
    STATE["html"] = html

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"\nEditing {source.name} at {url}")
    print("Press E in the page to edit, Ctrl+S to save. Ctrl+C here to stop.\n")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. " + html.name + " is ready to share.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
