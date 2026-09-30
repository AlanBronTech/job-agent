# Contract: CLI changes

Every existing command keeps its arguments, messages and exit codes. The
existing `test_cli_*` suites pass unchanged, and that is the parity check for
the move into `services/`.

## New: `jobagent ui`

```text
jobagent ui [--port 8765] [--no-browser]
```

- Starts the server on `127.0.0.1:<port>` in the foreground; there is no `--host`.
- Marks any `running` rows in `ui_runs` as `interrupted`.
- Opens `http://127.0.0.1:<port>/?t=<token>` in the default browser once
  listening, unless `--no-browser` is given.
- Port busy: exit 2 with "Something is already listening on <url> — probably
  another `jobagent ui`."
- Ctrl-C with a run active: prints what is running and asks for a second Ctrl-C.
- Composes with `--budget`: `jobagent --budget ui` routes UI runs to the free tier,
  and every cost display says so.

## New flag: `jobagent generate --supersede`

```text
jobagent generate 12 --resume --cover --supersede
```

- If the application folder already holds documents this run would write,
  it is renamed to `<YYYY-MM>.superseded-<timestamp>_<suffix>` first, and the
  new name is printed.
- If the rename fails, exit 1 with nothing spent and the folder untouched.
- Mutually exclusive with `--overwrite` (exit 2).
- The "Already generated" refusal gains one line: "…or pass --supersede to keep
  them under a dated name."

## Run log

Calls made from the UI carry `source: "ui"`. `jobagent spend` shows `ui` as its
own row under "by source" and counts it as real work.
