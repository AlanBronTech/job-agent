# Static files for the local UI

`htmx.min.js` is HTMX 2.0.4, vendored so the UI loads nothing from the
network. It is used for two things only: polling a running action's status and
swapping a confirmation panel in place (specs/001-local-ui, research R2).

- Source: https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
- SHA-256: e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447
- Licence: 0BSD (htmx 2.x), https://github.com/bigskysoftware/htmx/blob/master/LICENSE

To upgrade, replace the file, update the version and hash above, and check the
polling fragment still stops once a run has finished.
