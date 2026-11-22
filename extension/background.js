importScripts("api.js");

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: "vg-page", title: "Download video on this page with VidGrab", contexts: ["page", "video"] });
  chrome.contextMenus.create({ id: "vg-link", title: "Download linked video with VidGrab", contexts: ["link"] });
});

function notify(title, message) {
  chrome.notifications.create({ type: "basic", iconUrl: "icon128.png", title, message });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let url = info.menuItemId === "vg-link" ? info.linkUrl : tab.url;
  // A right-click on a <video> with a real file URL: download that file directly.
  if (info.mediaType === "video" && info.srcUrl && /^https?:/.test(info.srcUrl)) url = info.srcUrl;
  if (!(await vgPing())) return notify("VidGrab isn't running", "Start the VidGrab app, then try again.");
  try { await vgDownload(url); notify("VidGrab", "Download started"); }
  catch (e) { notify("VidGrab error", e.message); }
});
