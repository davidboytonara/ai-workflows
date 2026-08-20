#!/usr/bin/env python3
"""CLI client for the bundled Playwright daemon.

Exit codes:
  0  success
  1  daemon/request failure
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17337


def load_json_arg(raw: str) -> Any:
    text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
    return json.loads(text)


def parse_param(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise ValueError(f"Invalid --param {raw!r}. Use key=value")
    key, value = raw.split("=", 1)
    key = key.strip()
    if not key:
        raise ValueError("Parameter key cannot be empty")
    value = value.strip()
    if value == "":
        return key, ""
    try:
        return key, json.loads(value)
    except json.JSONDecodeError:
        return key, value


def endpoint(host: str, port: int, path: str) -> str:
    return f"http://{host}:{port}{path}"


def get_json(url: str) -> dict[str, Any]:
    request = Request(url, method="GET")
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def print_json(payload: dict[str, Any], *, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(payload, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send commands to the Playwright workflow daemon",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  playwright_client.py health\n"
            "  playwright_client.py action navigate --json '{\"url\":\"https://example.com\"}'\n"
            "  playwright_client.py action click --param 'selector=button.submit'\n"
            "  playwright_client.py raw @body.json\n\n"
            "Run subcommand help for more:\n"
            "  playwright_client.py action --help\n"
            "  playwright_client.py raw --help"
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Daemon host. Default: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Daemon port. Default: {DEFAULT_PORT}")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of pretty JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "health",
        help="Check daemon health",
        description="Check daemon health and print returned JSON.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    action_parser = subparsers.add_parser(
        "action",
        help="Send an action with params",
        description=(
            "Send one daemon action.\n"
            "Use --json for an object payload, repeated --param key=value for simple overrides, or both.\n"
            "If the same key appears multiple times, last value wins."
        ),
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  playwright_client.py action navigate --json '{\"url\":\"https://example.com\",\"wait_until\":\"networkidle\"}'\n"
            "  playwright_client.py action click --param 'selector=button:has-text(\"Save\")'\n"
            "  playwright_client.py action screenshot --json '{\"path\":\"debug/home.png\",\"full_page\":true}'\n"
            "  playwright_client.py action list_pages\n\n"
            "Common actions include:\n"
            "  navigate, click, fill, press, hover, inspect, content, screenshot, pdf,\n"
            "  new_page, list_pages, switch_page, wait_for_selector, wait_for_url,\n"
            "  console_network, cookies, clear_storage, close_browser, shutdown"
        ),
    )
    action_parser.add_argument("action_name", help="Daemon action name")
    action_parser.add_argument("--json", dest="json_arg", help="JSON object string or @file with params")
    action_parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Param as key=value. Value may be JSON like true, 2, [1,2], or {\"a\":1}",
    )

    raw_parser = subparsers.add_parser(
        "raw",
        help="Send a full raw JSON body",
        description="Send a full JSON body directly to /command.",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  playwright_client.py raw '{\"action\":\"navigate\",\"params\":{\"url\":\"https://example.com\"}}'\n"
            "  playwright_client.py raw @body.json"
        ),
    )
    raw_parser.add_argument("body", help="Raw JSON string or @file")

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pretty = not args.compact

    try:
        if args.command == "health":
            result = get_json(endpoint(args.host, args.port, "/health"))
            print_json(result, pretty=pretty)
            return 0 if result.get("ok") else 1

        if args.command == "action":
            params: dict[str, Any] = {}
            if args.json_arg:
                loaded = load_json_arg(args.json_arg)
                if not isinstance(loaded, dict):
                    raise ValueError("--json must decode to an object")
                params.update(loaded)
            for raw in args.param:
                key, value = parse_param(raw)
                params[key] = value
            result = post_json(
                endpoint(args.host, args.port, "/command"),
                {"action": args.action_name, "params": params},
            )
            print_json(result, pretty=pretty)
            return 0 if result.get("ok") else 1

        if args.command == "raw":
            payload = load_json_arg(args.body)
            if not isinstance(payload, dict):
                raise ValueError("raw body must decode to an object")
            result = post_json(endpoint(args.host, args.port, "/command"), payload)
            print_json(result, pretty=pretty)
            return 0 if result.get("ok") else 1

        parser.error("Unknown command")
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"ok": False, "error": f"HTTP {exc.code}: {detail}"}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    except URLError as exc:
        print(json.dumps({"ok": False, "error": str(exc.reason)}, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
