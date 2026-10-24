// Links marked data-window open in their own browser window, not a tab
// (Alan, 2026-10-24: job ads from the Alerts page, read beside the list).
// Giving window.open a size is what makes browsers open a window. Without
// JavaScript the link still opens, in a new tab.
document.addEventListener("click", function (event) {
  var link = event.target.closest("a[data-window]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  var w = Math.min(1100, screen.availWidth - 80);
  var h = screen.availHeight - 80;
  window.open(link.href, "_blank", "noopener,noreferrer,width=" + w + ",height=" + h + ",left=40,top=40");
});
