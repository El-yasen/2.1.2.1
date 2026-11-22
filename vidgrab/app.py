"""Double-click entry point: starts the web UI and opens it in the browser.

Used by the packaged app (VidGrab.exe / VidGrab.app) and by `vidgrab-app`.
Files go to ~/Downloads/VidGrab.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
import webbrowser

PORT = 8765


def _already_running() -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/ping")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=1) as r:
            return json.load(r).get("app") == "vidgrab"
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    url = f"http://127.0.0.1:{PORT}"
    if _already_running():
        webbrowser.open(url)
        return 0
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            print(f"Port {PORT} is used by another program. Close it and try again.")
            input("Press Enter to exit...") if sys.stdin and sys.stdin.isatty() else None
            return 1
    out = os.path.join(os.path.expanduser("~"), "Downloads", "VidGrab")
    from vidgrab.web import serve
    print("Keep this window open while downloading. Close it to quit VidGrab.\n")
    serve("127.0.0.1", PORT, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
