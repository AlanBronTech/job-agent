// The Jobs page's filters apply as soon as a choice changes. The form is a
// plain GET, so without JavaScript its Show button does the same.
document.addEventListener("change", function (event) {
  var form = event.target.closest("form[data-autosubmit]");
  if (form && event.target.tagName === "SELECT") form.submit();
});
