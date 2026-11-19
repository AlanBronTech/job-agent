// Batch page: the header checkbox selects or clears every job.
document.addEventListener("change", function (event) {
  if (!event.target.matches("[data-select-all]")) return;
  document.querySelectorAll('input[type=checkbox][name="jd"]').forEach(function (box) {
    box.checked = event.target.checked;
  });
});
