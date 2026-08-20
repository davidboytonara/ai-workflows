---
trigger: Any URL to open or read, including one just pasted, plus "using browser", "playwright", "open site", "scrape", "log in to", "debug website"; also when an API is blocked.
---

> **⚠️ Terms-of-Service notice.** This workflow automates a browser against
> third-party services using a session you log into yourself. It is intended solely
> for **your own accounts and your own data**. Automated access may violate those
> services' terms, which can change at any time. Do not use it to access accounts you
> do not own, to scrape or redistribute third-party content, or to circumvent rate
> limits, access controls, or bot-detection measures. Read the full notice in the
> repository README before use. Never commit session state from `.auth/`.

## Trigger

Any URL that must be opened or read — including one the user just pasted — plus `using browser`, `playwright`, `open site`, `scrape`, `log in to`, `debug website`, `automated test`.

Also the fallback the moment a domain workflow's API path is blocked (expired token, missing consent, no display): a browser session often still reaches the page. For a hosted cloud browser instead, prefer `../kernel-browser/kernel-browser.md`.

## Goal

The browsing, debugging, or test task completes through the persistent local Playwright daemon, with requested artifacts saved and any auth decision honored and reported.

## Context

Runs on `~/.agents/.venv` (verified by `playwright_launch.py`). Browser binaries (`.browsers/`), auth profiles (`.auth/`), artifacts (`artifacts/`), and logs (`logs/`) live under `~/.agents/workflows/playwright/`.

Shell variables do **not** persist between tool calls — re-declare in every call:

```bash
PY="$HOME/.agents/.venv/bin/python"
WF="$HOME/.agents/workflows/playwright"
LOG="$WF/logs/daemon.log"
```

**Persistent daemon.** Port `17337`, outlives individual tasks — it holds the live pages and any loaded auth profile, which is how authenticated sessions are reused. One command runs health check → background start → re-check:

```bash
"$PY" "$WF/playwright_launch.py" --ensure --port 17337
```

Exit `0` ready · `1` never healthy (stop, report `$LOG`) · `3` headless daemon running but `--headed` requested.

Headed mode (manual login, visual confirmation) requires a restart, in this order:

```bash
"$PY" "$WF/playwright_client.py" --port 17337 action shutdown || true
"$PY" "$WF/playwright_launch.py" --ensure --headed --port 17337
```

**Interactive sign-in — use real branded Chrome via `--channel chrome`:**

```bash
"$PY" "$WF/playwright_launch.py" --ensure --headed --channel chrome --port 17337
```

This is for a **human-driven headed login**: you type the credentials in the window yourself. Many
providers only support sign-in from a real branded Chrome build and refuse bundled Chromium outright
(e.g. Google answers **"This browser or app may not be secure"**), so the sign-in cannot be completed
at all without it. `--channel chrome` runs the installed Chrome (`/opt/google/chrome/chrome` on
Linux) instead of Playwright's Chromium.

**Do not spoof the user agent** — it is not the cause, and it only breaks feature detection. What a
CDP launch changes is the browser's own automation self-report, and `playwright_daemon.py` normalises
it to a standard interactive-Chrome configuration on every launch
(`ignore_default_args=["--enable-automation"]` + `args=["--disable-blink-features=AutomationControlled"]`,
in the primary launch *and* the channel-fallback path):

1. `--enable-automation`, which Playwright passes by default — it also puts an infobar over the page
   and alters some dialog behaviour, both of which get in a human's way during login;
2. the `AutomationControlled` blink feature, which sets `navigator.webdriver === true`.

Verify before handing the window to the user — both must be true:

```bash
"$PY" "$WF/playwright_client.py" --port 17337 action evaluate \
  --json '{"expression":"JSON.stringify({webdriver: navigator.webdriver, ua: navigator.userAgent})"}'
# want: "webdriver":false  and a UA containing Chrome/<version> with NO "HeadlessChrome"
```

**Auth profiles.** Named files under `.auth/`, loaded into the running browser: `list_auth`, `load_auth --param name=PROFILE`, `save_auth --param name=PROFILE`.

A loaded profile is **not** proof of a live session — cookies expire silently. After `load_auth`, navigate and confirm the page is not a sign-in/account-chooser screen before trusting it. Refreshing a dead session needs headed mode and the user; no amount of retrying fixes it headlessly.

**Driving the browser.** `--param key=value` for simple values, `--json '{...}'` for complex ones. `playwright_client.py action --help` lists the common actions but not their shapes; the non-obvious ones:

| Action | Params |
|---|---|
| `navigate` / `reload` | `{"url":…,"wait_until":"networkidle"}` |
| `content` | `{"mode":"text","max_chars":8000}` |
| `click` / `hover` / `scroll` / `wait_for_selector` | `{"selector":…}` (+ `"state":"visible"`) |
| `fill` / `press` | `{"selector":…,"value":…}` · `key=Enter` |
| `screenshot` / `pdf` | `{"path":"debug/home.png","full_page":true}` |
| `upload` | `{"selector":"input[type=file]","files":[…]}` |
| `drag_and_drop` | `{"source":…,"target":…}` |
| `inspect` | `{"selector":…,"include_html":true}` |
| `new_page` / `switch_page` | `{"url":…}` · `page_id=2` |
| `console_network` | `{"max_entries":100}` |
| `set_viewport` | `{"width":1440,"height":900}` |
| `clear_storage` | `{"clear_cookies":true,"reload":true}` |

Also: `list_pages`, `back`, `wait_for_url`, `wait_for_load_state`, `cookies mode=list`.

LLM needed because selectors, waits, and action choice against arbitrary pages cannot be encoded as fixed rules; the daemon only executes them.

**Recovery.** `close_browser` resets the browser but keeps the daemon; `shutdown` ends the session; `delete_auth` removes a saved profile.

## Constraints

- Clarify before starting: target URL and goal, headed vs headless, artifacts wanted.
- Never save auth or write credentials without explicit user approval; report any auth decision taken.
- The daemon and port are shared across tasks — do not `shutdown`, `close_browser`, or `clear_storage` a session another task may be using; when in doubt, ask.
- Convert a flow into repo Playwright tests only after selectors and waits are stable; preserve existing tests, and ask before running an unknown repo test command.
- Large DOM, logs, or artifacts → delegate analysis to a subagent with artifact paths plus the exact question; keep live browser control in the main agent.

## Verify

```bash
PY="$HOME/.agents/.venv/bin/python"; WF="$HOME/.agents/workflows/playwright"

"$PY" "$WF/playwright_client.py" --port 17337 health        # exit 0
"$PY" "$WF/playwright_client.py" --port 17337 action list_pages
ls -l "$WF/artifacts"                                        # artifacts you reported exist
tail -n 20 "$WF/logs/daemon.log"                             # on failure
```
