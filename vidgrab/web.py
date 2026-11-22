"""Tiny local web UI (stdlib only). Open http://127.0.0.1:8765 in your browser."""
from __future__ import annotations

import json
import os
import threading
import urllib.parse
import uuid
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import core

JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
SEM = threading.Semaphore(3)  # max parallel downloads

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VidGrab</title><style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1b1f24;--mut:#6b7280;--acc:#2563eb;--bd:#e5e7eb;--err:#dc2626;--ok:#16a34a}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--fg:#e6e8eb;--mut:#9aa1ab;--bd:#2a2f37;--acc:#3b82f6}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:32px 16px}h1{margin:0 0 4px;font-size:24px}p.s{margin:0 0 20px;color:var(--mut)}
form{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px;display:grid;gap:10px}
textarea,select,input,button{font:inherit;color:inherit}
textarea{width:100%;min-height:80px;padding:10px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);resize:vertical}
.row{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
select{padding:8px;border:1px solid var(--bd);border-radius:8px;background:var(--bg)}
button{padding:9px 18px;border:0;border-radius:8px;background:var(--acc);color:#fff;font-weight:600;cursor:pointer;margin-left:auto}
.job{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;margin-top:12px}
.t{font-weight:600;word-break:break-all}.m{color:var(--mut);font-size:13px;word-break:break-all}
.bar{height:6px;background:var(--bd);border-radius:3px;overflow:hidden;margin:8px 0 4px}
.bar>i{display:block;height:100%;background:var(--acc);transition:width .3s}
.done .bar>i{background:var(--ok)}.error .bar>i{background:var(--err)}.e{color:var(--err);font-size:13px}
a{color:var(--acc)}</style></head><body><main>
<h1>VidGrab</h1><p class="s">Paste video or page links (one per line) and download them.</p>
<form id="f"><textarea id="u" placeholder="https://..." required></textarea>
<div class="row"><label>Quality <select id="q">
<option value="best">Best</option><option value="1080">1080p</option><option value="720">720p</option>
<option value="480">480p</option><option value="audio">Audio only (mp3)</option></select></label>
<label><input type="checkbox" id="p"> Whole playlist</label>
<label><input type="checkbox" id="s"> Subtitles</label>
<button>Download</button></div></form><div id="jobs"></div></main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const mb=b=>b?(b/1e6).toFixed(1)+' MB':'';
$('f').onsubmit=async e=>{e.preventDefault();
 const urls=$('u').value.split(/\s+/).filter(Boolean);
 for(const url of urls) await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({url,quality:$('q').value,playlist:$('p').checked,subs:$('s').checked})});
 $('u').value='';poll();};
async function poll(){
 const jobs=await (await fetch('/api/jobs')).json();
 $('jobs').innerHTML=jobs.map(j=>{const p=j.progress;
  const files=(p.files||[]).map(f=>`<div><a href="/files/${encodeURIComponent(f.split(/[\\/]/).pop())}" download>⬇ ${esc(f.split(/[\\/]/).pop())}</a></div>`).join('');
  const sp=p.speed?(p.speed/1e6).toFixed(1)+' MB/s':'';
  return `<div class="job ${p.status}"><div class="t">${esc(p.title||p.filename||j.url)}</div>
  <div class="m">${esc(j.url)}</div><div class="bar"><i style="width:${p.status==='done'?100:p.percent}%"></i></div>
  <div class="m">${p.status} ${p.percent?p.percent+'%':''} ${mb(p.downloaded)} ${sp} ${p.eta!=null&&p.status==='downloading'?'· ETA '+p.eta+'s':''}</div>
  ${p.error?`<div class="e">${esc(p.error)}</div>`:''}${files}</div>`}).join('');
 if(jobs.some(j=>['queued','downloading','processing'].includes(j.progress.status))) setTimeout(poll,800);}
poll();
</script></body></html>"""


def _run(job_id: str, out_dir: str):
    job = JOBS[job_id]

    def cb(p):
        with LOCK:
            job["progress"] = asdict(p)

    with SEM:
        core.download(job["url"], out_dir, job["quality"], job["playlist"], job["subs"],
                      on_progress=cb)


def make_handler(out_dir: str):
    out_abs = os.path.abspath(out_dir)

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if path == "/api/jobs":
                with LOCK:
                    jobs = sorted(JOBS.values(), key=lambda j: j["created"], reverse=True)
                    return self._send(200, json.dumps(jobs, default=str))
            if path.startswith("/files/"):
                name = os.path.basename(urllib.parse.unquote(path[7:]))
                fp = os.path.join(out_abs, name)
                if not name or not os.path.isfile(fp):
                    return self._send(404, '{"error":"not found"}')
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(os.path.getsize(fp)))
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
                self.end_headers()
                with open(fp, "rb") as f:
                    while chunk := f.read(1 << 20):
                        self.wfile.write(chunk)
                return
            self._send(404, '{"error":"not found"}')

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/api/download":
                return self._send(404, '{"error":"not found"}')
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                url = str(body.get("url", "")).strip()
            except (ValueError, json.JSONDecodeError):
                return self._send(400, '{"error":"bad json"}')
            if not url.startswith(("http://", "https://")):
                return self._send(400, '{"error":"url must start with http(s)://"}')
            import time
            jid = uuid.uuid4().hex[:8]
            with LOCK:
                JOBS[jid] = {
                    "id": jid, "url": url, "created": time.time(),
                    "quality": str(body.get("quality") or "best"),
                    "playlist": bool(body.get("playlist")), "subs": bool(body.get("subs")),
                    "progress": asdict(core.Progress()),
                }
            threading.Thread(target=_run, args=(jid, out_dir), daemon=True).start()
            self._send(200, json.dumps({"id": jid}))

    return H


def serve(host="127.0.0.1", port=8765, out_dir="downloads"):
    os.makedirs(out_dir, exist_ok=True)
    srv = ThreadingHTTPServer((host, port), make_handler(out_dir))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
    print(f"VidGrab UI running at {url}  (files -> {os.path.abspath(out_dir)})  Ctrl+C to stop")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
