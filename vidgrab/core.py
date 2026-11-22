"""Download engine.

Uses yt-dlp (supports 1000+ sites) when available. Falls back to a plain
HTTP downloader that handles direct media links (.mp4, .webm, ...) and
simple pages that embed a <video>/<source> tag.
"""
from __future__ import annotations

import html.parser
import os
import re
import shutil
import threading
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    import yt_dlp  # type: ignore
except ImportError:  # pragma: no cover
    yt_dlp = None

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
MEDIA_EXT = (".mp4", ".webm", ".mkv", ".mov", ".m4v", ".ogv", ".mp3", ".m4a")

# Quality presets -> yt-dlp format selectors
QUALITY = {
    "best": "bv*+ba/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
    "480": "bv*[height<=480]+ba/b[height<=480]/b",
    "audio": "ba/b",
}


@dataclass
class Progress:
    status: str = "queued"  # queued|downloading|processing|done|error|cancelled
    percent: float = 0.0
    downloaded: int = 0
    total: Optional[int] = None
    speed: Optional[float] = None
    eta: Optional[int] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    files: list = field(default_factory=list)


ProgressCB = Callable[[Progress], None]


class Cancelled(Exception):
    pass


_BAD_TITLE = re.compile(r"^\s*(none|na|null|untitled|video)?\s*(\(\d+\))?\s*$", re.I)


def clean_title(info: dict) -> str:
    """Pick a usable title. yt-dlp's generic extractor can return e.g. 'None (1)'."""
    title = info.get("title")
    if title and not _BAD_TITLE.match(str(title)):
        return str(title)
    fmts = info.get("formats") or []
    candidates = [info.get("url")] + [f.get("url") for f in fmts[-1:]]
    for u in candidates:
        if u:
            base = os.path.splitext(os.path.basename(urllib.parse.urlparse(u).path))[0]
            if base and not _BAD_TITLE.match(base):
                return urllib.parse.unquote(base)
    host = urllib.parse.urlparse(info.get("webpage_url") or "").hostname
    return f"video from {host}" if host else "video"


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def info(url: str) -> dict:
    """Return metadata (title, duration, available formats) without downloading."""
    if yt_dlp is None:
        raise RuntimeError("yt-dlp is not installed: pip install yt-dlp")
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        data = ydl.extract_info(url, download=False)
    entries = data.get("entries")
    formats = [
        {
            "id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": f.get("height"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "size": f.get("filesize") or f.get("filesize_approx"),
            "note": f.get("format_note"),
        }
        for f in (data.get("formats") or [])
    ]
    return {
        "title": data.get("title"),
        "uploader": data.get("uploader"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "extractor": data.get("extractor_key"),
        "playlist_count": len(list(entries)) if entries is not None else None,
        "formats": formats,
    }


def download(
    url: str,
    out_dir: str = "downloads",
    quality: str = "best",
    playlist: bool = False,
    subtitles: bool = False,
    cookies_from_browser: Optional[str] = None,
    on_progress: Optional[ProgressCB] = None,
    cancel: Optional[threading.Event] = None,
) -> Progress:
    """Download a video. Tries yt-dlp, then the generic fallback.

    Set the ``cancel`` event from another thread to stop the download.
    """
    os.makedirs(out_dir, exist_ok=True)
    prog = Progress()
    cancel = cancel or threading.Event()
    user_emit = on_progress or (lambda p: None)

    def emit(p):
        if cancel.is_set():
            raise Cancelled()
        user_emit(p)

    def cancelled():
        prog.status = "cancelled"
        prog.error = None
        _remove_partials(out_dir, prog.filename)
        user_emit(prog)
        return prog

    if yt_dlp is not None:
        try:
            return _ytdlp_download(url, out_dir, quality, playlist, subtitles,
                                   cookies_from_browser, prog, emit)
        except Exception as e:  # noqa: BLE001  (yt-dlp may wrap Cancelled)
            if cancel.is_set():
                return cancelled()
            ytdlp_err = _clean_err(e)
    else:
        ytdlp_err = "yt-dlp not installed"

    # Fallback: direct file / <video> tag scraping
    try:
        return _generic_download(url, out_dir, prog, emit)
    except Exception as e:  # noqa: BLE001
        if cancel.is_set():
            return cancelled()
        prog.status = "error"
        prog.error = f"yt-dlp: {ytdlp_err} | fallback: {_clean_err(e)}"
        emit(prog)
        return prog


# --------------------------------------------------------------------- yt-dlp
def _ytdlp_download(url, out_dir, quality, playlist, subtitles, browser, prog, emit):
    fmt = QUALITY.get(quality, quality)  # allow raw yt-dlp format strings
    if not has_ffmpeg() and "+" in fmt:
        # Without ffmpeg we can't merge separate video+audio streams
        fmt = "b" if quality != "audio" else "ba/b"

    def hook(d):
        if d["status"] == "downloading":
            prog.status = "downloading"
            prog.downloaded = d.get("downloaded_bytes") or 0
            prog.total = d.get("total_bytes") or d.get("total_bytes_estimate")
            prog.speed = d.get("speed")
            prog.eta = d.get("eta")
            prog.filename = os.path.basename(d.get("filename") or "")
            if prog.total:
                prog.percent = round(100 * prog.downloaded / prog.total, 1)
            emit(prog)
        elif d["status"] == "finished":
            prog.status = "processing"
            prog.percent = 100.0
            emit(prog)

    def post_hook(d):
        if d["status"] == "finished":
            path = d.get("info_dict", {}).get("filepath")
            if path and path not in prog.files:
                prog.files.append(path)

    opts = {
        "format": fmt,
        "outtmpl": os.path.join(out_dir, "%(title|video).150B [%(id)s].%(ext)s"),
        "noplaylist": not playlist,
        "progress_hooks": [hook],
        "postprocessor_hooks": [post_hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "retries": 5,
        "concurrent_fragment_downloads": 4,
        "http_headers": {"User-Agent": USER_AGENT},
    }
    if quality == "audio" and has_ffmpeg():
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    elif has_ffmpeg():
        opts["merge_output_format"] = "mp4"
    if subtitles:
        opts.update({"writesubtitles": True, "subtitleslangs": ["en.*", "all"]})
    if browser:
        opts["cookiesfrombrowser"] = (browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.add_post_processor(_TitleFixer(), when="pre_process")
        data = ydl.extract_info(url, download=True)
        prog.title = clean_title(data) if data.get("_type") != "playlist" else data.get("title")
        if not prog.files:
            for e in data.get("entries") or [data]:
                if e and e.get("requested_downloads"):
                    prog.files += [r["filepath"] for r in e["requested_downloads"]]
    prog.status = "done"
    prog.percent = 100.0
    emit(prog)
    return prog


if yt_dlp is not None:
    class _TitleFixer(yt_dlp.postprocessor.PostProcessor):
        """Runs before the filename is built, replacing junk titles."""

        def run(self, info):
            info["title"] = clean_title(info)
            return [], info


def _remove_partials(out_dir, filename):
    if not filename:
        return
    stem = os.path.splitext(filename)[0].split(".f")[0]
    for name in os.listdir(out_dir):
        if name.startswith(stem) and (name.endswith(".part") or ".part-Frag" in name
                                      or name.endswith(".ytdl")):
            try:
                os.remove(os.path.join(out_dir, name))
            except OSError:
                pass


# -------------------------------------------------------------------- generic
class _VideoTagParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("video", "source", "audio") and a.get("src"):
            self.urls.append(a["src"])
        elif tag == "meta" and a.get("property") in ("og:video", "og:video:url",
                                                     "og:video:secure_url"):
            if a.get("content"):
                self.urls.append(a["content"])


def _open(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=30)


def find_media_urls(page_url: str) -> list[str]:
    """Scan an HTML page for <video>/<source>/og:video and raw .mp4 links."""
    with _open(page_url) as r:
        ctype = r.headers.get("Content-Type", "")
        if not ctype.startswith("text/html"):
            return [page_url]
        body = r.read(5_000_000).decode("utf-8", "replace")
    p = _VideoTagParser()
    p.feed(body)
    found = p.urls + re.findall(
        r"""https?://[^\s"'<>]+?\.(?:mp4|webm|m4v|mov)(?:\?[^\s"'<>]*)?""", body)
    out, seen = [], set()
    for u in found:
        absu = urllib.parse.urljoin(page_url, u.replace("\\/", "/"))
        if absu.startswith("http") and absu not in seen:
            seen.add(absu)
            out.append(absu)
    return out


def _generic_download(url, out_dir, prog, emit):
    path = urllib.parse.urlparse(url).path.lower()
    candidates = [url] if path.endswith(MEDIA_EXT) else find_media_urls(url)
    if not candidates:
        raise RuntimeError("no video found on page")
    media = candidates[0]

    with _open(media) as r:
        ctype = r.headers.get("Content-Type", "")
        if ctype.startswith("text/"):
            raise RuntimeError(f"not a media file ({ctype})")
        name = _filename_from(r, media)
        dest = _unique(os.path.join(out_dir, name))
        prog.total = int(r.headers.get("Content-Length") or 0) or None
        prog.filename = os.path.basename(dest)
        prog.title = prog.filename
        prog.status = "downloading"
        with open(dest + ".part", "wb") as f:
            while chunk := r.read(256 * 1024):
                f.write(chunk)
                prog.downloaded += len(chunk)
                if prog.total:
                    prog.percent = round(100 * prog.downloaded / prog.total, 1)
                emit(prog)
    os.replace(dest + ".part", dest)
    prog.files.append(dest)
    prog.status = "done"
    prog.percent = 100.0
    emit(prog)
    return prog


def _filename_from(resp, url):
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
    name = urllib.parse.unquote(m.group(1)) if m else \
        os.path.basename(urllib.parse.urlparse(url).path) or "video.mp4"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "video.mp4"
    if "." not in name:
        name += ".mp4"
    return name[:200]


def _unique(path):
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(path):
        path = f"{base} ({i}){ext}"
        i += 1
    return path


def _clean_err(e: Exception) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "").strip()
