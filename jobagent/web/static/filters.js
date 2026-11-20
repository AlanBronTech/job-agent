// The Jobs page's toolbar: a dropdown choice applies at once. The search
// runs only on Enter or the Search button, never while typing; reloading the
// page mid-word ate the space just typed (Alan, 2026-11-21). The form is a
// plain GET, so without JavaScript the Search button applies everything.
(function () {
  var form = document.querySelector("form[data-autosubmit]");
  if (!form) return;
  document.documentElement.classList.add("js");
  form.addEventListener("change", function (event) {
    if (event.target.tagName === "SELECT") form.submit();
  });
  var search = form.querySelector("input[type=search]");
  // The box's own clear (x) empties it; show everything again at once.
  if (search) {
    search.addEventListener("search", function () {
      if (search.value === "") form.submit();
    });
  }
  // Back after a search: put the cursor at the end of what was typed.
  if (search && search.value) {
    search.focus();
    search.setSelectionRange(search.value.length, search.value.length);
  }
})();
