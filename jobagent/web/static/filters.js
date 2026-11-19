// The Jobs page's toolbar: a choice applies at once, and the search runs as
// you type, after a short pause. The form is a plain GET, so without
// JavaScript Enter or the Show button does the same.
(function () {
  var form = document.querySelector("form[data-autosubmit]");
  if (!form) return;
  document.documentElement.classList.add("js");
  form.addEventListener("change", function (event) {
    if (event.target.tagName === "SELECT") form.submit();
  });
  var search = form.querySelector("input[type=search]");
  var timer;
  if (search) {
    search.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { form.submit(); }, 500);
    });
    // Back after a search: put the cursor at the end of what was typed.
    if (search.value) {
      search.focus();
      search.setSelectionRange(search.value.length, search.value.length);
    }
  }
})();
