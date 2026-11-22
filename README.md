# VidGrab

Download videos from web pages: YouTube, Vimeo, X/Twitter, Reddit, TikTok, news sites and
[1000+ other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus any
page that embeds a plain `<video>` tag or links straight to an `.mp4`/`.webm` file.

You can use it from the command line or from a small web page that runs on your own computer.

## Install

```bash
pip install -r requirements.txt     # installs yt-dlp
# Optional but recommended: ffmpeg (merges HD video+audio, converts to mp3)
#   Windows: winget install ffmpeg   macOS: brew install ffmpeg   Linux: apt install ffmpeg
```

## Web UI

```bash
python -m vidgrab --web
```

Your browser opens at http://127.0.0.1:8765. Paste one or more links, pick a quality and click
**Download**. Progress shows live, and finished files have a download link. Files are saved to `./downloads`.

## Command line

```bash
python -m vidgrab URL                       # best quality into ./downloads
python -m vidgrab URL1 URL2 -o ~/Videos     # several links, custom folder
python -m vidgrab URL -q 720                # best | 1080 | 720 | 480 | audio
python -m vidgrab URL -q audio              # mp3 (needs ffmpeg)
python -m vidgrab PLAYLIST_URL -p           # whole playlist
python -m vidgrab URL -s                    # also download subtitles
python -m vidgrab URL -c chrome             # use your browser's login cookies (members/private videos you can watch)
python -m vidgrab URL --info                # show title and available formats only
python -m vidgrab PAGE_URL --find           # list raw video links found in a page's HTML
```

## How it works

1. **yt-dlp** is tried first. It knows the site-specific extractors and handles HLS/DASH streams.
2. If that fails, a **fallback** downloads direct media links, or scans the page HTML for
   `<video>`, `<source>` and `og:video` tags and downloads the first video it finds.

Keep yt-dlp up to date (`pip install -U yt-dlp`), since sites change often.

## Notes

- DRM-protected streams (Netflix, Disney+, Spotify and similar) are not supported.
- Only download content you have the right to download, and follow each site's terms of service.
- The web UI listens on `127.0.0.1` only. Don't expose it to the internet.
