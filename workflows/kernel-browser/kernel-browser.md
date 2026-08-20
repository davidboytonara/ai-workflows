---
trigger: "kernel", "kernel.sh", "cloud browser", "remote browser", "browse with kernel" — LLM browsing on a hosted browser; for a local browser use playwright instead.
---

## Trigger

`kernel`, `kernel.sh`, `cloud browser`, `remote browser`, `browse with kernel` — LLM-driven browsing on a hosted browser instead of a local Playwright one. For local browsers, prefer the **persistent daemon** in `../playwright/playwright.md`.

## Goal

The browsing task is completed in a Kernel cloud browser session driven by Playwright snippets, and every session created for it is deleted afterwards.

## Context

All Kernel operations go through the bundled CLI `kernel_browser.ts`, run with the shared `tsx` runtime. Session state (last created session) lives in `workflows/kernel-browser/state/`; `create` records the new session as the default for later commands.

```bash
TSX="$HOME/.agents/node_modules/.bin/tsx"
KB="$HOME/.agents/workflows/kernel-browser/kernel_browser.ts"
[ -x "$TSX" ] || npm install --prefix "$HOME/.agents" tsx @onkernel/sdk   # bootstrap tsx itself
"$TSX" "$KB" check   # offline self-check: SDK installed, API key resolved, state dir writable
```

**API key.** Read from `$KERNEL_API_KEY`, falling back to the `KERNEL_API_KEY=` line in `~/.agents/.env` (created there with an empty placeholder; keys come from the kernel.sh dashboard → API Keys).

**Exit codes.** `check` exits `0` when everything is in place — run it first and fix what it names before any other command. `2` is a usage error (re-run `"$TSX" "$KB" help`); `3` means the key is missing or rejected; `4` means `@onkernel/sdk` is not installed (the error prints the install command); `1` carries the API error message — read it before retrying.

**Sessions.** `"$TSX" "$KB" create --name my-task` prints `session_id`, `cdp_ws_url`, and `browser_live_view_url`. Flags: `--stealth` (anti-bot), `--headless` (no live view), `--start-url URL`, `--timeout SECS` (inactivity auto-delete; script default 600), `--profile NAME [--save-profile]` (persist logins across sessions), `--width W --height H`.

**Driving.** For each goal, compose a small Playwright snippet and execute it in the session's VM — `page`, `context`, and `browser` are in scope, `await` works, and the snippet's `return` value comes back as JSON. LLM needed because page-specific Playwright actions over arbitrary, unstructured web pages cannot be encoded as a fixed rule; the script only transports and executes the code.

```bash
"$TSX" "$KB" exec --code "await page.goto('https://example.com'); return await page.title();"
"$TSX" "$KB" exec --file ./snippet.js --timeout-sec 120   # larger snippets from a file; cap max 300s
```

**Observing.** `"$TSX" "$KB" view` prints the live-view URL — share it with the user to watch or take over (e.g. manual login). Live view only exists for non-headless sessions. For CDP-level access from other tools, use the `cdp_ws_url` (e.g. Playwright `connectOverCDP`). `"$TSX" "$KB" list` shows all active sessions; `delete` removes the last session, `delete --all` every active one.

## Constraints

- Never print or echo the API key value. On exit `3`, ask the user to paste their key into `~/.agents/.env` — do not fetch or guess one.
- Get user approval before saving auth state with `--save-profile`.
- Delete sessions explicitly when done — sessions bill while alive. The inactivity auto-delete is a backstop, not the cleanup.

## Verify

```bash
TSX="$HOME/.agents/node_modules/.bin/tsx"
KB="$HOME/.agents/workflows/kernel-browser/kernel_browser.ts"

# Prerequisites OK offline (exit 0; 3 = key missing, 4 = SDK missing)
"$TSX" "$KB" check

# Key accepted by the API (exit 3 = rejected; exit 1 with [] just means no active sessions)
"$TSX" "$KB" list

# During the run: a snippet round-trips through the session VM
"$TSX" "$KB" exec --code "return await page.title();"

# After cleanup: the session no longer appears
"$TSX" "$KB" list
```
