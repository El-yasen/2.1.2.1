"""Command-line interface.

    python -m vidgrab URL [URL ...] [-o DIR] [-q best|1080|720|480|audio]
    python -m vidgrab --info URL
    python -m vidgrab --web            # start the browser UI
"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, core


def _bar(p: core.Progress) -> None:
    if p.status != "downloading":
        return
    width = 30
    filled = int(width * p.percent / 100) if p.total else 0
    speed = f"{p.speed / 1e6:5.1f} MB/s" if p.speed else "   ?    "
    eta = f"ETA {p.eta}s" if p.eta is not None else ""
    size = f"{p.downloaded / 1e6:.1f}MB" if p.downloaded >= 1e5 else f"{p.downloaded / 1e3:.0f}KB"
    sys.stderr.write(
        f"\r[{'#' * filled}{'.' * (width - filled)}] {p.percent:5.1f}% {size} {speed} {eta}   ")
    sys.stderr.flush()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vidgrab", description="Download videos from web pages.")
    ap.add_argument("urls", nargs="*", help="page or video URLs")
    ap.add_argument("-o", "--output", default="downloads", help="output folder (default: downloads)")
    ap.add_argument("-q", "--quality", default="best",
                    help="best | 1080 | 720 | 480 | audio | any yt-dlp format string")
    ap.add_argument("-p", "--playlist", action="store_true", help="download the whole playlist")
    ap.add_argument("-s", "--subs", action="store_true", help="also download subtitles")
    ap.add_argument("-c", "--cookies-from-browser", metavar="BROWSER",
                    help="use your browser's login cookies (chrome, firefox, edge, safari...)")
    ap.add_argument("-i", "--info", action="store_true", help="show info/formats, don't download")
    ap.add_argument("-f", "--find", action="store_true",
                    help="list direct media links found in the page HTML")
    ap.add_argument("--web", action="store_true", help="start the web UI")
    ap.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="with --web: don't open a browser tab")
    ap.add_argument("-V", "--version", action="version", version=__version__)
    a = ap.parse_args(argv)

    if a.web:
        from .web import serve
        serve(a.host, a.port, a.output, open_browser=not a.no_browser)
        return 0
    if not a.urls:
        ap.print_help()
        return 2

    rc = 0
    for url in a.urls:
        if a.info:
            print(json.dumps(core.info(url), indent=2, default=str))
            continue
        if a.find:
            for u in core.find_media_urls(url):
                print(u)
            continue
        print(f"→ {url}", file=sys.stderr)
        p = core.download(url, a.output, a.quality, a.playlist, a.subs,
                          a.cookies_from_browser, on_progress=_bar)
        sys.stderr.write("\n")
        if p.status == "done":
            for f in p.files:
                print(f"✓ {f}")
        else:
            print(f"✗ {p.error}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
