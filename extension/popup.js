const $ = (id) => document.getElementById(id);
const msg = (t, cls = "") => { $("msg").textContent = t; $("msg").className = cls; };

(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const url = tab && tab.url;
  $("url").textContent = url || "";
  if (!url || !/^https?:/.test(url)) return msg("Open a web page with a video first.", "err");
  if (!(await vgPing())) return msg("VidGrab app isn't running. Start it, then reopen this popup.", "err");
  $("go").disabled = false;
  $("go").onclick = async () => {
    $("go").disabled = true;
    try { await vgDownload(url, $("q").value, $("pl").checked); msg("Download started ✓", "ok"); }
    catch (e) { msg(e.message, "err"); $("go").disabled = false; }
  };
})();
