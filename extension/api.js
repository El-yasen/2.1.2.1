// Shared helpers for talking to the local VidGrab app.
const VIDGRAB = "http://127.0.0.1:8765";

async function vgPing() {
  try {
    const r = await fetch(VIDGRAB + "/api/ping", { cache: "no-store" });
    return (await r.json()).app === "vidgrab";
  } catch (e) { return false; }
}

async function vgDownload(url, quality = "best", playlist = false) {
  const r = await fetch(VIDGRAB + "/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, quality, playlist }),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error || "request failed");
  return d;
}
