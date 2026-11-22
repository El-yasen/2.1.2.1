# VidGrab

Download videos from web pages: YouTube, Vimeo, X/Twitter, Reddit, TikTok, news sites and
[1000+ other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus any
page that embeds a plain `<video>` tag or links straight to an `.mp4`/`.webm` file.

There are three ways to use it:

| | What it is | Needs Python? |
|---|---|---|
| **App** | Double-click `VidGrab`, and a download page opens in your browser | No |
| **Browser extension** | A button in Chrome/Edge/Brave that sends the current page's video to the app | No (the app must be running) |
| **Command line** | `python -m vidgrab URL` | Yes |

## 1. The app (easiest)

1. Open the repo's **Releases** page and download the zip for your system:
   `VidGrab-windows.zip`, `VidGrab-macos.zip` or `VidGrab-linux.zip`.
   (Before the first release exists, use the **Actions** tab instead: open the latest
   "Test and build apps" run and download the zip from **Artifacts**.)
2. Unzip it and double-click **VidGrab**. A small window opens, and so does your browser at
   http://127.0.0.1:8765. Keep the window open while downloading, and close it to quit.
3. Paste links, choose a quality or click **Choose format…** to pick an exact format, and click **Download**.
   Files are saved in `Downloads/VidGrab` in your home folder.

The download list is kept between runs. Each entry can be cancelled while running, and
retried or removed afterwards.

First run:
- **Windows** may show "Windows protected your PC". Click **More info**, then **Run anyway**.
- **macOS** may say the app can't be checked. Right-click it, choose **Open**, then **Open** again.

These warnings appear because the app isn't code-signed.

**Install ffmpeg** for HD video with sound and mp3 audio. Without it, many sites only give lower
quality video, and audio-only saves the original audio file instead of converting it.
`winget install ffmpeg` (Windows), `brew install ffmpeg` (macOS), `sudo apt install ffmpeg` (Linux).

## 2. Browser extension (Chrome, Edge, Brave)

1. Download `VidGrab-browser-extension.zip` from Releases (or use the `extension/` folder of this repo) and unzip it.
2. Go to `chrome://extensions`, turn on **Developer mode**, click **Load unpacked**, and pick the unzipped folder.
3. With the VidGrab app running:
   - click the VidGrab toolbar button on any video page, choose a quality, and click **Download**, or
   - right-click a page, link or video and choose **Download … with VidGrab**.

## 3. Command line

```bash
pip install -r requirements.txt     # or: pip install .   (adds `vidgrab` and `vidgrab-app` commands)

python -m vidgrab URL                       # best quality into ./downloads
python -m vidgrab URL1 URL2 -o ~/Videos     # several links, custom folder
python -m vidgrab URL -q 720                # best | 1080 | 720 | 480 | audio | any yt-dlp format
python -m vidgrab PLAYLIST_URL -p           # whole playlist
python -m vidgrab URL -s                    # also download subtitles
python -m vidgrab URL -c chrome             # use your browser's login (members/private videos you can watch)
python -m vidgrab URL --info                # title and available formats only
python -m vidgrab PAGE_URL --find           # list raw video links in the page's HTML
python -m vidgrab --web                     # start the web UI (files go to ./downloads)
```

## How it works

1. **yt-dlp** is tried first. It has site-specific extractors and handles HLS/DASH streams.
2. If that fails, a **fallback** downloads direct media links, or scans the page HTML for
   `<video>`, `<source>` and `og:video` tags and downloads the first video it finds.

Sites change often. Keep yt-dlp current with `pip install -U yt-dlp`. For the app, download a
newer release; a new build picks up the latest yt-dlp.

## Building the app yourself

```bash
pip install -r requirements.txt pyinstaller
pyinstaller vidgrab.spec       # result in dist/
```

GitHub Actions (`.github/workflows/build.yml`) runs the tests and builds Windows, macOS and Linux
apps plus the extension zip on every push to `main`. Pushing a tag like `v0.2.0` also publishes
them as a GitHub Release:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

## Development

```bash
python -m unittest -v          # end-to-end tests against a local test server
```

| Path | What |
|---|---|
| `vidgrab/core.py` | download engine (yt-dlp + fallback, progress, cancel) |
| `vidgrab/web.py` | local web UI and JSON API |
| `vidgrab/cli.py` | command line |
| `vidgrab/app.py` | double-click launcher |
| `extension/` | Chrome/Edge/Brave extension (Manifest V3) |

## Safety and limits

- The app only accepts connections from your own computer. Other websites can't start
  downloads through it; only its own page and the VidGrab extension can.
- DRM-protected services (Netflix, Disney+, Spotify and similar) are not supported.
- Only download content you have the right to download, and follow each site's terms of service.
