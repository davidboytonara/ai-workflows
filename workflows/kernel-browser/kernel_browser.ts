// Kernel (kernel.sh) cloud-browser CLI — create, drive, inspect, and delete browser sessions for LLM use.
// Exit codes: 0 success, 1 no session / API error, 2 usage error, 3 missing or rejected KERNEL_API_KEY,
//             4 @onkernel/sdk not installed (the error prints the install command).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Same centralized secret file every Python workflow reads. This is TypeScript
// so it cannot import workflows/_shared/agents_config.py; it re-implements the
// identical contract instead. See .env.example.
const AGENTS_HOME = process.env.AGENTS_HOME
  ? path.resolve(process.env.AGENTS_HOME)
  : path.join(os.homedir(), ".agents");
const ENV_FILE = path.join(AGENTS_HOME, ".env");
const STATE_FILE = path.join(__dirname, "state", "last_session.json");

const USAGE = `Usage: tsx kernel_browser.ts <command> [args]

Commands:
  create [--name N] [--stealth] [--headless] [--timeout SECS] [--start-url URL]
         [--profile NAME [--save-profile]] [--width W --height H]
      Create a browser session. Prints session JSON (session_id, cdp_ws_url,
      browser_live_view_url) and remembers it as the last session.
      --timeout: inactivity seconds before auto-delete (default 600 here; API default 60).

  exec [SESSION_ID] (--code JS | --file PATH) [--timeout-sec SECS]
      Run Playwright code inside the session's VM. The code has \`page\`,
      \`context\`, and \`browser\` in scope, supports await, and its \`return\`
      value is printed as JSON. SESSION_ID defaults to the last created session.

  view [SESSION_ID]     Print the live-view URL (non-headless sessions only).
  list                  List active browser sessions as JSON.
  delete [SESSION_ID | --all]   Delete a session (default: last created) or all sessions.
  check                 Validate prerequisites offline (no API call): @onkernel/sdk
                        installed, API key resolved, state dir writable.
                        Exit 0 ok, 3 key missing, 4 SDK missing.
  help                  Show this help.

API key: read from $KERNEL_API_KEY, else from KERNEL_API_KEY= in ${ENV_FILE}.`;

// Strict KEY=VALUE subset, matching workflows/_shared/agents_config.py exactly:
// own-line # comments only, no `export `, no $VAR interpolation, no inline
// trailing comments, matched surrounding quotes stripped. The subset is
// mandatory because the heartbeat systemd unit reads this same file via
// EnvironmentFile=, and systemd understands only this much.
function loadEnvFile(): void {
  if (process.env.KERNEL_API_KEY || !fs.existsSync(ENV_FILE)) return;
  for (const line of fs.readFileSync(ENV_FILE, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const m = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!m || process.env[m[1]] !== undefined) continue;
    process.env[m[1]] = m[2].trim().replace(/^(["'])(.*)\1$/, "$2");
  }
}

type Flags = { [key: string]: string | boolean };

function parseFlags(argv: string[]): { positional: string[]; flags: Flags } {
  const boolFlags = new Set(["stealth", "headless", "save-profile", "all"]);
  const positional: string[] = [];
  const flags: Flags = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) {
      positional.push(a);
      continue;
    }
    const key = a.slice(2);
    if (boolFlags.has(key)) {
      flags[key] = true;
    } else {
      if (i + 1 >= argv.length) throw new UsageError(`--${key} requires a value`);
      flags[key] = argv[++i];
    }
  }
  return { positional, flags };
}

class UsageError extends Error {}

function readState(): { session_id?: string; browser_live_view_url?: string } | null {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return null;
  }
}

function writeState(data: object | null): void {
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  if (data === null) fs.rmSync(STATE_FILE, { force: true });
  else fs.writeFileSync(STATE_FILE, JSON.stringify(data, null, 2) + "\n");
}

function resolveSessionId(positional: string[]): string {
  if (positional[0]) return positional[0];
  const last = readState();
  if (last?.session_id) return last.session_id;
  throw new UsageError("No SESSION_ID given and no last session recorded — run `create` first or pass an id.");
}

function intFlag(flags: Flags, key: string): number | undefined {
  if (flags[key] === undefined) return undefined;
  const n = Number(flags[key]);
  if (!Number.isInteger(n) || n <= 0) throw new UsageError(`--${key} must be a positive integer`);
  return n;
}

function print(obj: unknown): void {
  console.log(JSON.stringify(obj, null, 2));
}

const SDK_INSTALL_CMD = `npm install --prefix ${CASPER_ROOT} tsx @onkernel/sdk`;

async function check(keyFromShell: boolean): Promise<number> {
  let sdkInstalled = true;
  try {
    await import("@onkernel/sdk");
  } catch {
    sdkInstalled = false;
  }
  const keyPresent = Boolean(process.env.KERNEL_API_KEY);
  const stateDir = path.dirname(STATE_FILE);
  let stateDirWritable = true;
  try {
    fs.mkdirSync(stateDir, { recursive: true });
    fs.accessSync(stateDir, fs.constants.W_OK);
  } catch {
    stateDirWritable = false;
  }
  print({
    ok: sdkInstalled && keyPresent && stateDirWritable,
    node: process.version,
    sdk: sdkInstalled ? "installed" : `missing — run: ${SDK_INSTALL_CMD}`,
    api_key: keyPresent
      ? `present (${keyFromShell ? "environment" : ENV_FILE})`
      : `missing — add KERNEL_API_KEY=<key> to ${ENV_FILE} or export it`,
    state_dir: stateDirWritable ? "writable" : `not writable: ${stateDir}`,
  });
  if (!sdkInstalled) return 4;
  if (!keyPresent) return 3;
  return stateDirWritable ? 0 : 1;
}

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2);
  if (!cmd || ["help", "--help", "-h"].includes(cmd)) {
    console.log(USAGE);
    return cmd ? 0 : 2;
  }

  const keyFromShell = Boolean(process.env.KERNEL_API_KEY);
  loadEnvFile();

  if (cmd === "check") return check(keyFromShell);

  if (!process.env.KERNEL_API_KEY) {
    console.error(
      `KERNEL_API_KEY is not set. Add it to ${ENV_FILE} as KERNEL_API_KEY=<key> ` +
        `(create a key in the kernel.sh dashboard) or export it in the environment.`,
    );
    return 3;
  }

  let Kernel: typeof import("@onkernel/sdk").default;
  try {
    ({ default: Kernel } = await import("@onkernel/sdk"));
  } catch {
    console.error(`@onkernel/sdk is not installed. Run: ${SDK_INSTALL_CMD}`);
    return 4;
  }
  const kernel = new Kernel();
  const { positional, flags } = parseFlags(rest);

  switch (cmd) {
    case "create": {
      const params: Record<string, unknown> = {
        timeout_seconds: intFlag(flags, "timeout") ?? 600,
      };
      if (flags["name"]) params.name = flags["name"];
      if (flags["stealth"]) params.stealth = true;
      if (flags["headless"]) params.headless = true;
      if (flags["start-url"]) params.start_url = flags["start-url"];
      if (flags["profile"])
        params.profile = { name: flags["profile"], save_changes: !!flags["save-profile"] };
      const width = intFlag(flags, "width");
      const height = intFlag(flags, "height");
      if (width && height) params.viewport = { width, height };
      const browser = await kernel.browsers.create(params);
      const summary = {
        session_id: browser.session_id,
        cdp_ws_url: browser.cdp_ws_url,
        browser_live_view_url: browser.browser_live_view_url ?? null,
        headless: browser.headless,
        stealth: browser.stealth,
        timeout_seconds: browser.timeout_seconds,
        created_at: browser.created_at,
      };
      writeState(summary);
      print(summary);
      return 0;
    }

    case "exec": {
      const codeFlag = flags["code"] as string | undefined;
      const fileFlag = flags["file"] as string | undefined;
      if (!codeFlag && !fileFlag) throw new UsageError("exec requires --code JS or --file PATH");
      const code = codeFlag ?? fs.readFileSync(fileFlag!, "utf8");
      const id = resolveSessionId(positional);
      const timeout_sec = intFlag(flags, "timeout-sec");
      const res = await kernel.browsers.playwright.execute(id, {
        code,
        ...(timeout_sec ? { timeout_sec } : {}),
      });
      print(res);
      return 0;
    }

    case "view": {
      const id = resolveSessionId(positional);
      const browser = await kernel.browsers.retrieve(id);
      if (!browser.browser_live_view_url) {
        console.error(`Session ${id} has no live-view URL (headless sessions never do).`);
        return 1;
      }
      console.log(browser.browser_live_view_url);
      return 0;
    }

    case "list": {
      const sessions: unknown[] = [];
      for await (const s of kernel.browsers.list()) sessions.push(s);
      print(sessions);
      return sessions.length ? 0 : 1;
    }

    case "delete": {
      const ids: string[] = [];
      if (flags["all"]) {
        for await (const s of kernel.browsers.list()) ids.push((s as { session_id: string }).session_id);
        if (!ids.length) {
          console.error("No active sessions to delete.");
          return 1;
        }
      } else {
        ids.push(resolveSessionId(positional));
      }
      for (const id of ids) {
        await kernel.browsers.deleteByID(id);
        console.log(`deleted ${id}`);
        if (readState()?.session_id === id) writeState(null);
      }
      return 0;
    }

    default:
      throw new UsageError(`Unknown command: ${cmd}`);
  }
}

main().then(
  (code) => process.exit(code),
  (err) => {
    if (err instanceof UsageError) {
      console.error(`${err.message}\n\n${USAGE}`);
      process.exit(2);
    }
    const status = (err as { status?: number }).status;
    console.error(`Kernel API error${status ? ` (HTTP ${status})` : ""}: ${err.message}`);
    process.exit(status === 401 || status === 403 ? 3 : 1);
  },
);
