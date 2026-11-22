"""Tiny local web UI (stdlib only). Open http://127.0.0.1:8765 in your browser."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import uuid
import webbrowser
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, core

ACTIVE = ("queued", "downloading", "processing")
MAX_PARALLEL = 3
HISTORY_LIMIT = 200


class JobStore:
    """Jobs + their progress, persisted to <out_dir>/.vidgrab-history.json."""

    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.path = os.path.join(out_dir, ".vidgrab-history.json")
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(MAX_PARALLEL)
        self.jobs: dict[str, dict] = {}
        self.cancels: dict[str, threading.Event] = {}
        self._load()

    # ---- persistence
    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                for j in json.load(f):
                    if j["progress"]["status"] in ACTIVE:
                        j["progress"]["status"] = "error"
                        j["progress"]["error"] = "interrupted (app was closed)"
                    self.jobs[j["id"]] = j
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save(self):  # caller holds lock
        jobs = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(jobs[:HISTORY_LIMIT], f)
            os.replace(tmp, self.path)
        except OSError:
            pass

    # ---- operations
    def list(self):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j["created"], reverse=True)
            out = []
            for j in jobs:
                j = dict(j)
                j["files"] = [
                    {"name": os.path.basename(f), "exists": os.path.isfile(f)}
                    for f in j["progress"].get("files") or []
                ]
                out.append(j)
            return out

    def add(self, url, quality="best", playlist=False, subs=False):
        jid = uuid.uuid4().hex[:10]
        ev = threading.Event()
        with self.lock:
            self.jobs[jid] = {
                "id": jid, "url": url, "created": time.time(), "quality": quality,
                "playlist": playlist, "subs": subs, "progress": asdict(core.Progress()),
            }
            self.cancels[jid] = ev
            self._save()
        threading.Thread(target=self._run, args=(jid, ev), daemon=True).start()
        return jid

    def _run(self, jid, ev):
        job = self.jobs[jid]
        last = {"status": None}

        def cb(p):
            with self.lock:
                job["progress"] = asdict(p)
                if p.status != last["status"]:
                    last["status"] = p.status
                    self._save()

        with self.sem:
            if ev.is_set():
                return
            core.download(job["url"], self.out_dir, job["quality"], job["playlist"],
                          job["subs"], on_progress=cb, cancel=ev)
        with self.lock:
            self.cancels.pop(jid, None)
            self._save()

    def cancel(self, jid):
        with self.lock:
            ev = self.cancels.get(jid)
            job = self.jobs.get(jid)
            if not ev or not job:
                return False
            ev.set()
            if job["progress"]["status"] == "queued":  # not started yet
                job["progress"]["status"] = "cancelled"
                self.cancels.pop(jid, None)
                self._save()
            return True

    def remove(self, jid):
        with self.lock:
            job = self.jobs.get(jid)
            if not job or job["progress"]["status"] in ACTIVE:
                return False
            del self.jobs[jid]
            self._save()
            return True

    def clear(self):
        with self.lock:
            for jid in [k for k, j in self.jobs.items() if j["progress"]["status"] not in ACTIVE]:
                del self.jobs[jid]
            self._save()


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VidGrab</title><style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#1b1f24;--mut:#6b7280;--acc:#2563eb;--bd:#e5e7eb;--err:#dc2626;--ok:#16a34a}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#181b21;--fg:#e6e8eb;--mut:#9aa1ab;--bd:#2a2f37;--acc:#3b82f6}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
main{max-width:760px;margin:0 auto;padding:32px 16px}h1{margin:0 0 4px;font-size:24px}p.s{margin:0 0 20px;color:var(--mut)}
h2{font-size:16px;margin:28px 0 0;display:flex;align-items:center}
form,.job,#fmt{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:14px}
form{display:grid;gap:10px}
textarea,select,input,button{font:inherit;color:inherit}
textarea{width:100%;min-height:80px;padding:10px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);resize:vertical}
.row{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
select{padding:8px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);max-width:100%}
button{padding:8px 16px;border:1px solid var(--bd);border-radius:8px;background:var(--bg);cursor:pointer}
button.pri{border:0;background:var(--acc);color:#fff;font-weight:600}
button.sm{padding:3px 10px;font-size:13px}.grow{margin-left:auto}
#fmt{display:none;margin-top:12px;gap:12px}#fmt img{width:120px;border-radius:6px;object-fit:cover}
.job{margin-top:10px}.t{font-weight:600;word-break:break-all}.m{color:var(--mut);font-size:13px;word-break:break-all}
.bar{height:6px;background:var(--bd);border-radius:3px;overflow:hidden;margin:8px 0 4px}
.bar>i{display:block;height:100%;background:var(--acc);transition:width .3s}
.done .bar>i{background:var(--ok)}.error .bar>i,.cancelled .bar>i{background:var(--err)}.e{color:var(--err);font-size:13px}
.acts{display:flex;gap:8px;margin-top:6px;flex-wrap:wrap;align-items:center}
a{color:var(--acc)}.empty{color:var(--mut);margin-top:10px}</style></head><body><main>
<h1>VidGrab</h1><p class="s">Paste video or page links (one per line) and download them.</p>
<form id="f"><textarea id="u" placeholder="https://..." required></textarea>
<div class="row"><label>Quality <select id="q">
<option value="best">Best</option><option value="1080">1080p</option><option value="720">720p</option>
<option value="480">480p</option><option value="audio">Audio only (mp3)</option></select></label>
<label><input type="checkbox" id="p"> Whole playlist</label>
<label><input type="checkbox" id="s"> Subtitles</label>
<span class="grow"></span><button type="button" id="fb">Choose format…</button><button class="pri">Download</button></div>
<div id="fmt" class="row"></div></form>
<h2>Downloads <span class="grow"></span><button class="sm" id="clr">Clear finished</button></h2>
<div id="jobs"></div></main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const mb=b=>!b?'':b<1e6?(b/1e3).toFixed(0)+' KB':(b/1e6).toFixed(1)+' MB';
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});
let polling=false,fmtSel=null;
$('f').onsubmit=async e=>{e.preventDefault();
 const urls=$('u').value.split(/\s+/).filter(Boolean);
 const quality=(fmtSel&&fmtSel.value)||$('q').value;
 for(const url of urls){const r=await post('/api/download',{url,quality,playlist:$('p').checked,subs:$('s').checked});
  if(!r.ok)alert((await r.json()).error);}
 $('u').value='';$('fmt').style.display='none';fmtSel=null;poll();};
$('fb').onclick=async()=>{const url=$('u').value.split(/\s+/).filter(Boolean)[0];
 const box=$('fmt');if(!url){alert('Paste a link first');return;}
 box.style.display='flex';box.innerHTML='<span class="m">Loading formats…</span>';
 const r=await fetch('/api/info?url='+encodeURIComponent(url));const d=await r.json();
 if(!r.ok){box.innerHTML=`<span class="e">${esc(d.error)}</span>`;return;}
 const fs=(d.formats||[]).filter(f=>f.vcodec!=='none'||f.acodec!=='none').reverse();
 const opt=f=>{const vo=f.vcodec!=='none'&&f.acodec==='none',ao=f.vcodec==='none';
  const val=vo&&d.ffmpeg?`${f.id}+ba/${f.id}`:f.id;
  const lab=[ao?'audio':(f.height?f.height+'p':f.note||'video'),f.ext,mb(f.size),vo?(d.ffmpeg?'(+ best audio)':'(no audio!)'):'',f.note&&f.height?f.note:''].filter(Boolean).join(' · ');
  return `<option value="${esc(val)}">${esc(lab)}</option>`};
 box.innerHTML=`${d.thumbnail?`<img src="${esc(d.thumbnail)}" alt="">`:''}<div style="flex:1;min-width:200px">
  <div class="t">${esc(d.title)}</div><div class="m">${esc(d.uploader||'')} ${d.duration?'· '+Math.round(d.duration/60)+' min':''}</div>
  <select id="fs" style="margin-top:8px;width:100%"><option value="">Use quality setting above</option>${fs.map(opt).join('')}</select></div>`;
 fmtSel=$('fs');};
$('clr').onclick=async()=>{await post('/api/clear');poll();};
async function act(a,id){await post('/api/'+a,{id});poll();}
async function poll(){
 let jobs;try{jobs=await (await fetch('/api/jobs')).json();}catch(e){setTimeout(poll,3000);return;}
 $('jobs').innerHTML=jobs.length?jobs.map(j=>{const p=j.progress,act=['queued','downloading','processing'].includes(p.status);
  const files=j.files.map(f=>f.exists?`<a href="/files/${encodeURIComponent(f.name)}" download>⬇ ${esc(f.name)}</a>`:`<span class="m">${esc(f.name)} (moved or deleted)</span>`).join('');
  const sp=p.speed?(p.speed/1e6).toFixed(1)+' MB/s':'';
  return `<div class="job ${p.status}"><div class="t">${esc(p.title||p.filename||j.url)}</div>
  <div class="m">${esc(j.url)} · ${new Date(j.created*1000).toLocaleString()}</div>
  <div class="bar"><i style="width:${p.status==='done'?100:p.percent}%"></i></div>
  <div class="m">${p.status} ${act&&p.percent?p.percent+'%':''} ${act?mb(p.downloaded):''} ${act?sp:''} ${p.eta!=null&&p.status==='downloading'?'· ETA '+p.eta+'s':''}</div>
  ${p.error?`<div class="e">${esc(p.error)}</div>`:''}
  <div class="acts">${files}<span class="grow"></span>${act?`<button class="sm" onclick="act('cancel','${j.id}')">Cancel</button>`:
   `<button class="sm" onclick="$('u').value=${esc(JSON.stringify(j.url))};scrollTo(0,0)">Retry</button><button class="sm" onclick="act('remove','${j.id}')">Remove</button>`}</div></div>`}).join('')
  :'<div class="empty">No downloads yet.</div>';
 if(jobs.some(j=>['queued','downloading','processing'].includes(j.progress.status))){if(!polling){polling=true;setTimeout(()=>{polling=false;poll();},800);}}}
poll();
</script></body></html>"""


def make_handler(store: JobStore, port: int):
    out_abs = os.path.abspath(store.out_dir)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    class H(BaseHTTPRequestHandler):
        server_version = "VidGrab/" + __version__

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            if not isinstance(body, (str, bytes)):
                body = json.dumps(body, default=str)
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            # Blocks DNS-rebinding attacks from websites pretending to be localhost.
            return self.headers.get("Host", "") in allowed_hosts

        def _origin_ok(self):
            # Only our own page, the browser extension, or non-browser tools (no Origin).
            o = self.headers.get("Origin")
            if not o:
                return True
            if o.startswith(("chrome-extension://", "moz-extension://")):
                return True
            return urllib.parse.urlparse(o).netloc in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden host"})
            u = urllib.parse.urlparse(self.path)
            path = u.path
            if path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if path == "/api/ping":
                return self._send(200, {"ok": True, "app": "vidgrab", "version": __version__})
            if path == "/api/jobs":
                return self._send(200, store.list())
            if path == "/api/info":
                url = (urllib.parse.parse_qs(u.query).get("url") or [""])[0].strip()
                if not url.startswith(("http://", "https://")):
                    return self._send(400, {"error": "url must start with http(s)://"})
                try:
                    d = core.info(url)
                    d["ffmpeg"] = core.has_ffmpeg()
                    return self._send(200, d)
                except Exception as e:  # noqa: BLE001
                    return self._send(400, {"error": core._clean_err(e)})
            if path.startswith("/files/"):
                name = os.path.basename(urllib.parse.unquote(path[7:]))
                fp = os.path.join(out_abs, name)
                if not name or name.startswith(".") or not os.path.isfile(fp):
                    return self._send(404, {"error": "not found"})
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
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or not self._origin_ok():
                return self._send(403, {"error": "forbidden origin"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._send(400, {"error": "bad json"})
            path = urllib.parse.urlparse(self.path).path

            if path == "/api/download":
                url = str(body.get("url", "")).strip()
                if not url.startswith(("http://", "https://")):
                    return self._send(400, {"error": "url must start with http(s)://"})
                jid = store.add(url, str(body.get("quality") or "best")[:200],
                                bool(body.get("playlist")), bool(body.get("subs")))
                return self._send(200, {"id": jid})
            if path == "/api/cancel":
                return self._send(200, {"ok": store.cancel(str(body.get("id")))})
            if path == "/api/remove":
                return self._send(200, {"ok": store.remove(str(body.get("id")))})
            if path == "/api/clear":
                store.clear()
                return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})

    return H


def serve(host="127.0.0.1", port=8765, out_dir="downloads", open_browser=True):
    os.makedirs(out_dir, exist_ok=True)
    store = JobStore(out_dir)
    srv = ThreadingHTTPServer((host, port), make_handler(store, port))
    url = f"http://127.0.0.1:{port}"
    print(f"VidGrab UI running at {url}  (files -> {os.path.abspath(out_dir)})  Ctrl+C to stop")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    return srv
