"""End-to-end tests against a local HTTP server. Run: python -m unittest -v"""
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"

from vidgrab import core, web  # noqa: E402

VIDEO = b"\x00\x00\x00\x18ftypmp42" + os.urandom(300_000)


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/":
            body = b'<html><body><video><source src="clip.mp4"></video></body></html>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith(("/clip.mp4", "/slow.mp4")):
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(VIDEO)))
            self.end_headers()
            step = 4096 if self.path.startswith("/slow") else len(VIDEO)
            try:
                for i in range(0, len(VIDEO), step):
                    self.wfile.write(VIDEO[i:i + step])
                    if step < len(VIDEO):
                        time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.send_error(404)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        threading.Thread(target=cls.site.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.site.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.site.shutdown()

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)


class CoreTests(Base):
    def test_clean_title(self):
        self.assertEqual(core.clean_title({"title": "My clip"}), "My clip")
        self.assertEqual(core.clean_title({"title": "None (1)", "url": "http://x/a/holiday.mp4"}), "holiday")
        self.assertEqual(core.clean_title({"title": None, "webpage_url": "https://ex.com/"}),
                         "video from ex.com")

    def test_ytdlp_page_with_video_tag(self):
        p = core.download(self.base + "/", self.out)
        self.assertEqual(p.status, "done", p.error)
        self.assertEqual(len(p.files), 1)
        self.assertIn("clip", os.path.basename(p.files[0]))
        with open(p.files[0], "rb") as f:
            self.assertEqual(f.read(), VIDEO)

    def test_fallback_without_ytdlp(self):
        saved, core.yt_dlp = core.yt_dlp, None
        try:
            p = core.download(self.base + "/", self.out)
        finally:
            core.yt_dlp = saved
        self.assertEqual(p.status, "done", p.error)
        self.assertEqual(os.path.basename(p.files[0]), "clip.mp4")

    def test_find_media_urls(self):
        self.assertEqual(core.find_media_urls(self.base + "/"), [self.base + "/clip.mp4"])

    def test_cancel(self):
        for use_ytdlp in (True, False):
            with self.subTest(ytdlp=use_ytdlp):
                saved = core.yt_dlp
                if not use_ytdlp:
                    core.yt_dlp = None
                ev = threading.Event()
                try:
                    p = core.download(self.base + "/slow.mp4", self.out,
                                      on_progress=lambda p: p.downloaded > 20000 and ev.set(),
                                      cancel=ev)
                finally:
                    core.yt_dlp = saved
                self.assertEqual(p.status, "cancelled")
                self.assertEqual([f for f in os.listdir(self.out) if not f.startswith(".")], [])


class WebTests(Base):
    def setUp(self):
        super().setUp()
        self.port = free_port()
        self.store = web.JobStore(self.out)
        self.srv = ThreadingHTTPServer(("127.0.0.1", self.port), web.make_handler(self.store, self.port))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.ui = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.ui + path, data=data, headers=headers or {})
        if data:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def wait_done(self, jid):
        for _ in range(100):
            job = next(j for j in json.loads(self.req("/api/jobs")[1]) if j["id"] == jid)
            if job["progress"]["status"] not in web.ACTIVE:
                return job
            time.sleep(0.1)
        self.fail("timeout")

    def test_download_flow_and_history(self):
        self.assertEqual(json.loads(self.req("/api/ping")[1])["app"], "vidgrab")
        code, body = self.req("/api/download", {"url": self.base + "/clip.mp4"})
        self.assertEqual(code, 200)
        job = self.wait_done(json.loads(body)["id"])
        self.assertEqual(job["progress"]["status"], "done", job["progress"]["error"])
        name = job["files"][0]["name"]
        code, data = self.req("/files/" + urllib.request.quote(name))
        self.assertEqual((code, data), (200, VIDEO))
        # history persisted and reloadable
        self.assertEqual(len(web.JobStore(self.out).jobs), 1)
        self.assertEqual(json.loads(self.req("/api/remove", {"id": job["id"]})[1])["ok"], True)
        self.assertEqual(json.loads(self.req("/api/jobs")[1]), [])

    def test_cancel_job(self):
        jid = json.loads(self.req("/api/download", {"url": self.base + "/slow.mp4"})[1])["id"]
        time.sleep(0.5)
        self.req("/api/cancel", {"id": jid})
        self.assertEqual(self.wait_done(jid)["progress"]["status"], "cancelled")

    def test_security(self):
        u = {"url": self.base + "/clip.mp4"}
        self.assertEqual(self.req("/api/download", u, {"Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/download", u, {"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("/api/download", {"url": "file:///etc/passwd"})[0], 400)
        self.assertEqual(self.req("/files/..%2F..%2Fetc%2Fpasswd")[0], 404)
        self.assertEqual(self.req("/files/.vidgrab-history.json")[0], 404)
        ok = self.req("/api/download", u, {"Origin": "chrome-extension://abcdef"})[0]
        self.assertEqual(ok, 200)


if __name__ == "__main__":
    unittest.main()
