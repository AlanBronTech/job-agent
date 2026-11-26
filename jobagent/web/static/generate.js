// Generate panel (spec 005): a resume with a longer profile stands in for a
// cover letter, so choosing one unticks the letter. Ticking it again is fine:
// the form sends whatever the box says.
document.addEventListener("change", function (event) {
  var radio = event.target;
  if (!radio.matches('input[type=radio][name="resume_kind"]')) return;
  var cover = radio.form && radio.form.querySelector("[data-cover]");
  if (cover && radio.hasAttribute("data-long-profile")) cover.checked = false;
});
