// The review page's keys: O opens the ad, each decision's letter records it.
// Ignored while typing in the note, and with Cmd or Ctrl held, so browser
// shortcuts such as Cmd+P still work.
document.addEventListener("keydown", function (event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  var tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea") return;
  var key = event.key.toLowerCase();
  if (key === "o") {
    var link = document.getElementById("open-ad");
    if (link) { event.preventDefault(); link.click(); }
    return;
  }
  var button = document.querySelector('#decide button[data-key="' + key + '"]');
  if (button) { event.preventDefault(); button.click(); }
});
