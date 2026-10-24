// Links marked data-window open in their own browser window, not a tab
// (Alan, 2026-10-24: job ads from the Alerts page, read beside the list).
// Giving window.open a size is what makes browsers open a window. Without
// JavaScript the link still opens, in a new tab.
//
// Placed on the screen this page is on, against its right edge. Window
// positions are global across monitors, so they are taken from this screen's
// origin (availLeft/availTop; Safari lacks them, so this window's own position
// stands in) rather than from 0,0, which is the main monitor.
document.addEventListener("click", function (event) {
  var link = event.target.closest("a[data-window]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  var s = window.screen;
  var left0 = typeof s.availLeft === "number" ? s.availLeft : window.screenX;
  var top0 = typeof s.availTop === "number" ? s.availTop : window.screenY;
  var w = Math.min(1100, s.availWidth - 80);
  var h = s.availHeight - 80;
  var left = left0 + s.availWidth - w - 40;
  var top = top0 + 40;
  window.open(link.href, "_blank",
    "noopener,noreferrer,width=" + w + ",height=" + h + ",left=" + left + ",top=" + top);
});
