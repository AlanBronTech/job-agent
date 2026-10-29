// The review page's keys: O opens the ad, each decision's letter records it.
// Ignored while typing in the note, and with Cmd or Ctrl held, so browser
// shortcuts such as Cmd+P still work. Enter or Escape in the note leaves the
// box without submitting: Enter alone would record the first button,
// "interested", whatever the note said.
document.addEventListener("keydown", function (event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  var tag = (event.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea") {
    if (event.key === "Enter" || event.key === "Escape") {
      event.preventDefault();
      event.target.blur();
    }
    return;
  }
  var key = event.key.toLowerCase();
  if (key === "o") {
    var link = document.getElementById("open-ad");
    if (link) { event.preventDefault(); link.click(); }
    return;
  }
  var button = document.querySelector('#decide button[data-key="' + key + '"]');
  if (button) { event.preventDefault(); button.click(); }
});
