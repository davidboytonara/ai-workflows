#!/usr/bin/env python3
"""Persistent Playwright daemon for browser workflows.

Keeps one Chromium browser context alive behind a small local HTTP API so
multi-step browsing, debugging, and authenticated sessions can reuse state.

Exit codes:
  0  success
  2  usage error
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, cast

_SYNC_PLAYWRIGHT = None
_PLAYWRIGHT_ERROR_TYPES: tuple[type[BaseException], ...] = ()


def load_playwright() -> Any:
    global _SYNC_PLAYWRIGHT, _PLAYWRIGHT_ERROR_TYPES
    if _SYNC_PLAYWRIGHT is None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        _SYNC_PLAYWRIGHT = sync_playwright
        _PLAYWRIGHT_ERROR_TYPES = (PlaywrightError, PlaywrightTimeoutError)
    return _SYNC_PLAYWRIGHT


SERVICE_NAME = "playwright-workflow-daemon"
SCRIPT_DIR = Path(__file__).resolve().parent
ARTIFACT_ROOT = SCRIPT_DIR / "artifacts"
AUTH_ROOT = SCRIPT_DIR / ".auth"
BROWSERS_ROOT = SCRIPT_DIR / ".browsers"
# Resolve Chromium from the workflow-local .browsers dir so the daemon is
# self-contained whether started via playwright_launch.py (which sets this and
# exec's into us) or run directly. setdefault preserves any explicit override.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(BROWSERS_ROOT))
MAX_CONSOLE_MESSAGES = 300
MAX_NETWORK_EVENTS = 500
MAX_POST_DATA_CHARS = 4000


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _limit_list(items: list[dict[str, Any]], max_len: int) -> None:
    if len(items) > max_len:
        del items[: len(items) - max_len]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


class BrowserSession:
    def __init__(self, headless: bool = True, channel: str | None = None) -> None:
        self._playwright = None
        self.headless = headless
        self.channel = channel.strip() if channel else None
        self.browser = None
        self.context = None
        self.pages: dict[int, Any] = {}
        self.next_page_id = 1
        self.active_page_id: int | None = None
        self.console_messages: list[dict[str, Any]] = []
        self.network_events: list[dict[str, Any]] = []
        self.start()

    @staticmethod
    def _profile_name(value: Any) -> str:
        name = str(value or "").strip()
        if name.endswith(".json"):
            name = name[:-5]
        if not name:
            raise ValueError("'name' is required")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        if any(char not in allowed for char in name):
            raise ValueError("Invalid profile name. Use letters, numbers, dot, underscore, or dash")
        return name

    def _auth_file(self, profile_name: str) -> Path:
        AUTH_ROOT.mkdir(parents=True, exist_ok=True)
        candidate = (AUTH_ROOT / f"{profile_name}.json").resolve()
        if os.path.commonpath([str(AUTH_ROOT.resolve()), str(candidate)]) != str(AUTH_ROOT.resolve()):
            raise ValueError("Invalid profile name")
        return candidate

    def _artifact_path(self, value: Any, prefix: str, suffix: str) -> Path:
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        if value:
            raw = Path(str(value)).expanduser()
            path = raw if raw.is_absolute() else (ARTIFACT_ROOT / raw)
        else:
            path = ARTIFACT_ROOT / f"{prefix}-{utc_stamp()}{suffix}"
        path = path.resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _upload_paths(self, value: Any) -> list[str]:
        if value is None:
            raise ValueError("'file' or 'files' is required")
        raw_values = value if isinstance(value, list) else [value]
        paths: list[str] = []
        for raw in raw_values:
            path = Path(str(raw)).expanduser()
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            if not path.exists():
                raise ValueError(f"Upload file not found: {path}")
            paths.append(str(path))
        return paths

    def _attach_page_events(self, page: Any, page_id: int) -> None:
        page.on("console", lambda message: self._on_console(page_id, message))
        page.on("request", lambda request: self._on_request(page_id, request))
        page.on("response", lambda response: self._on_response(page_id, response))
        page.on("close", lambda: self._cleanup_pages())

    def _register_page(self, page: Any, activate: bool = False) -> int:
        self._cleanup_pages()
        for page_id, known_page in self.pages.items():
            if known_page is page:
                if activate:
                    self.active_page_id = page_id
                return page_id

        page_id = self.next_page_id
        self.next_page_id += 1
        self.pages[page_id] = page
        self._attach_page_events(page, page_id)
        if activate or self.active_page_id is None:
            self.active_page_id = page_id
        return page_id

    def _cleanup_pages(self) -> None:
        closed: list[int] = []
        for page_id, page in self.pages.items():
            try:
                is_closed = page.is_closed()
            except Exception:
                is_closed = True
            if is_closed:
                closed.append(page_id)
        for page_id in closed:
            self.pages.pop(page_id, None)
        if self.active_page_id not in self.pages:
            self.active_page_id = max(self.pages) if self.pages else None

    def _page_info(self, page_id: int, page: Any | None = None) -> dict[str, Any]:
        page = page or self.pages.get(page_id)
        if page is None:
            return {"page_id": page_id, "active": False, "closed": True}
        try:
            closed = page.is_closed()
        except Exception:
            closed = True
        try:
            title = page.title() if not closed else ""
        except Exception:
            title = ""
        try:
            url = page.url if not closed else ""
        except Exception:
            url = ""
        return {
            "page_id": page_id,
            "url": url,
            "title": title,
            "active": page_id == self.active_page_id,
            "closed": closed,
        }

    def _list_pages(self) -> list[dict[str, Any]]:
        self._cleanup_pages()
        return [self._page_info(page_id, self.pages[page_id]) for page_id in sorted(self.pages)]

    def _new_page(self, activate: bool = True) -> tuple[int, Any]:
        if self.context is None:
            self.restart()
        assert self.context is not None
        page = self.context.new_page()
        page_id = self._register_page(page, activate=activate)
        return page_id, page

    def _resolve_page(self, page_id: Any | None = None, create: bool = True) -> tuple[int, Any]:
        self._cleanup_pages()

        if page_id is not None:
            try:
                resolved_id = int(page_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("'page_id' must be an integer") from exc
            page = self.pages.get(resolved_id)
            if page is None or page.is_closed():
                raise ValueError(f"Page not found: {resolved_id}")
            return resolved_id, page

        if self.active_page_id is not None:
            page = self.pages.get(self.active_page_id)
            if page is not None and not page.is_closed():
                return self.active_page_id, page

        if self.pages:
            resolved_id = max(self.pages)
            page = self.pages[resolved_id]
            self.active_page_id = resolved_id
            return resolved_id, page

        if not create:
            raise ValueError("No open pages")

        return self._new_page(activate=True)

    def start(self, storage_state: str | None = None) -> None:
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        AUTH_ROOT.mkdir(parents=True, exist_ok=True)

        self._playwright = load_playwright()().start()
        # Google (and other identity providers) refuse to sign in to a browser that
        # advertises itself as automated: "This browser or app may not be secure."
        # Two signals cause it, and BOTH must go -- the user agent is NOT the cause:
        #   1. `--enable-automation`, which Playwright passes by default, and
        #   2. the AutomationControlled blink feature, which sets
        #      `navigator.webdriver === true`.
        # Stripping both makes a manual sign-in in headed mode succeed. Pair it with
        # `--channel chrome` (real branded Chrome) -- bundled Chromium is refused by
        # some providers regardless of these flags.
        launch_kwargs: dict[str, Any] = {
            "headless": self.headless,
            "ignore_default_args": ["--enable-automation"],
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.channel:
            launch_kwargs["channel"] = self.channel

        try:
            self.browser = self._playwright.chromium.launch(**launch_kwargs)
        except Exception as exc:
            if not self.channel or (_PLAYWRIGHT_ERROR_TYPES and not isinstance(exc, _PLAYWRIGHT_ERROR_TYPES)):
                raise
            self.browser = self._playwright.chromium.launch(
                headless=self.headless,
                ignore_default_args=["--enable-automation"],
                args=["--disable-blink-features=AutomationControlled"],
            )

        context_kwargs: dict[str, Any] = {}
        if storage_state and Path(storage_state).is_file():
            context_kwargs["storage_state"] = storage_state

        self.context = self.browser.new_context(**context_kwargs)
        self.context.on("page", lambda page: self._register_page(page, activate=True))
        self.pages = {}
        self.active_page_id = None
        self._new_page(activate=True)

    def close(self) -> None:
        if self.context is not None:
            try:
                self.context.close()
            except Exception:
                pass
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass

        self._playwright = None
        self.browser = None
        self.context = None
        self.pages = {}
        self.active_page_id = None

    def restart(self, storage_state: str | None = None) -> None:
        self.close()
        self.console_messages = []
        self.network_events = []
        self.start(storage_state=storage_state)

    def _on_console(self, page_id: int, message: Any) -> None:
        location = message.location or {}
        entry = {
            "page_id": page_id,
            "type": message.type,
            "text": message.text,
            "location": {
                "url": location.get("url", ""),
                "lineNumber": location.get("lineNumber"),
                "columnNumber": location.get("columnNumber"),
            },
        }
        self.console_messages.append(entry)
        _limit_list(self.console_messages, MAX_CONSOLE_MESSAGES)

    def _on_request(self, page_id: int, request: Any) -> None:
        post_data = None
        if request.method in {"POST", "PUT", "PATCH"} and request.resource_type in {"fetch", "xhr"}:
            try:
                post_data = request.post_data
            except Exception:
                post_data = None

        if post_data is not None and len(post_data) > MAX_POST_DATA_CHARS:
            post_data = post_data[:MAX_POST_DATA_CHARS] + "...[truncated]"

        entry = {
            "page_id": page_id,
            "event": "request",
            "method": request.method,
            "url": request.url,
            "resourceType": request.resource_type,
        }
        if post_data:
            entry["postData"] = post_data
        self.network_events.append(entry)
        _limit_list(self.network_events, MAX_NETWORK_EVENTS)

    def _on_response(self, page_id: int, response: Any) -> None:
        request = response.request
        entry = {
            "page_id": page_id,
            "event": "response",
            "method": request.method,
            "url": request.url,
            "status": response.status,
            "ok": response.ok,
            "resourceType": request.resource_type,
        }
        self.network_events.append(entry)
        _limit_list(self.network_events, MAX_NETWORK_EVENTS)

    def _run(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "current":
            page_id, page = self._resolve_page()
            return {"page": self._page_info(page_id, page)}

        if action == "list_pages":
            return {"pages": self._list_pages(), "active_page_id": self.active_page_id}

        if action == "new_page":
            activate = bool(params.get("activate", True))
            page_id, page = self._new_page(activate=activate)
            response = None
            url = str(params.get("url", "")).strip()
            if url:
                timeout = int(params.get("timeout", 30000))
                wait_until = str(params.get("wait_until", "load"))
                response = page.goto(url, wait_until=wait_until, timeout=timeout)
                wait_for_selector = params.get("wait_for_selector")
                if wait_for_selector:
                    page.wait_for_selector(str(wait_for_selector), timeout=timeout)
            return {
                "page": self._page_info(page_id, page),
                "status": response.status if response else None,
            }

        if action == "switch_page":
            page_id, page = self._resolve_page(params.get("page_id"), create=False)
            self.active_page_id = page_id
            return {"page": self._page_info(page_id, page)}

        if action == "close_page":
            page_id, page = self._resolve_page(params.get("page_id"), create=False)
            page.close()
            self._cleanup_pages()
            return {
                "closed_page_id": page_id,
                "active_page_id": self.active_page_id,
                "pages": self._list_pages(),
            }

        if action == "navigate":
            url = str(params.get("url", "")).strip()
            if not url:
                raise ValueError("'url' is required")

            if bool(params.get("new_page", False)):
                page_id, page = self._new_page(activate=bool(params.get("activate", True)))
            else:
                page_id, page = self._resolve_page(params.get("page_id"))
                if bool(params.get("activate", True)):
                    self.active_page_id = page_id

            wait_until = str(params.get("wait_until", "load"))
            timeout = int(params.get("timeout", 30000))
            wait_for_selector = params.get("wait_for_selector")

            response = page.goto(url, wait_until=wait_until, timeout=timeout)
            if wait_for_selector:
                page.wait_for_selector(str(wait_for_selector), timeout=timeout)

            return {
                "page": self._page_info(page_id, page),
                "status": response.status if response else None,
            }

        if action == "reload":
            page_id, page = self._resolve_page(params.get("page_id"))
            timeout = int(params.get("timeout", 30000))
            wait_until = str(params.get("wait_until", "load"))
            wait_for_selector = params.get("wait_for_selector")
            response = page.reload(wait_until=wait_until, timeout=timeout)
            if wait_for_selector:
                page.wait_for_selector(str(wait_for_selector), timeout=timeout)
            return {
                "page": self._page_info(page_id, page),
                "status": response.status if response else None,
            }

        if action == "back":
            page_id, page = self._resolve_page(params.get("page_id"))
            timeout = int(params.get("timeout", 30000))
            wait_until = str(params.get("wait_until", "load"))
            wait_for_selector = params.get("wait_for_selector")
            response = page.go_back(wait_until=wait_until, timeout=timeout)
            if response is not None and wait_for_selector:
                page.wait_for_selector(str(wait_for_selector), timeout=timeout)
            return {
                "page": self._page_info(page_id, page),
                "status": response.status if response else None,
                "navigated": response is not None,
            }

        if action == "forward":
            page_id, page = self._resolve_page(params.get("page_id"))
            timeout = int(params.get("timeout", 30000))
            wait_until = str(params.get("wait_until", "load"))
            wait_for_selector = params.get("wait_for_selector")
            response = page.go_forward(wait_until=wait_until, timeout=timeout)
            if response is not None and wait_for_selector:
                page.wait_for_selector(str(wait_for_selector), timeout=timeout)
            return {
                "page": self._page_info(page_id, page),
                "status": response.status if response else None,
                "navigated": response is not None,
            }

        if action == "wait_for_url":
            page_id, page = self._resolve_page(params.get("page_id"))
            url = str(params.get("url", "")).strip()
            if not url:
                raise ValueError("'url' is required")
            timeout = int(params.get("timeout", 30000))
            wait_until = str(params.get("wait_until", "load"))
            page.wait_for_url(url, wait_until=wait_until, timeout=timeout)
            return {
                "message": f"URL matched: {url}",
                "page": self._page_info(page_id, page),
            }

        if action == "click":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")

            timeout = int(params.get("timeout", 30000))
            button = str(params.get("button", "left"))
            click_count = int(params.get("click_count", 1))
            locator = page.locator(selector).first

            if bool(params.get("wait_for_navigation", False)):
                wait_until = str(params.get("wait_until", "load"))
                with page.expect_navigation(wait_until=wait_until, timeout=timeout):
                    locator.click(timeout=timeout, button=button, click_count=click_count)
            else:
                locator.click(timeout=timeout, button=button, click_count=click_count)

            return {"message": f"Clicked selector: {selector}", "page": self._page_info(page_id, page)}

        if action == "hover":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")
            timeout = int(params.get("timeout", 30000))
            page.locator(selector).first.hover(timeout=timeout)
            return {"message": f"Hovered selector: {selector}", "page": self._page_info(page_id, page)}

        if action == "press":
            page_id, page = self._resolve_page(params.get("page_id"))
            key = str(params.get("key", "")).strip()
            if not key:
                raise ValueError("'key' is required")
            timeout = int(params.get("timeout", 30000))
            selector = str(params.get("selector", "")).strip()
            if selector:
                page.locator(selector).first.press(key, timeout=timeout)
            else:
                page.keyboard.press(key)
            return {"message": f"Pressed key: {key}", "page": self._page_info(page_id, page)}

        if action == "fill":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")

            mode = str(params.get("mode", "fill"))
            timeout = int(params.get("timeout", 30000))
            locator = page.locator(selector).first

            if mode == "fill":
                locator.fill(str(params.get("value", "")), timeout=timeout)
                return {"message": f"Filled selector: {selector}", "page": self._page_info(page_id, page)}

            if mode == "type":
                locator.type(str(params.get("value", "")), timeout=timeout, delay=int(params.get("delay", 0)))
                return {"message": f"Typed into selector: {selector}", "page": self._page_info(page_id, page)}

            if mode == "select":
                value = params.get("values", params.get("value"))
                if value is None:
                    raise ValueError("'value' or 'values' is required for mode=select")
                if isinstance(value, list):
                    selected = locator.select_option(value=[str(item) for item in value], timeout=timeout)
                else:
                    selected = locator.select_option(value=str(value), timeout=timeout)
                return {"selected": selected, "page": self._page_info(page_id, page)}

            if mode == "check":
                locator.check(timeout=timeout)
                return {"message": f"Checked selector: {selector}", "page": self._page_info(page_id, page)}

            if mode == "uncheck":
                locator.uncheck(timeout=timeout)
                return {"message": f"Unchecked selector: {selector}", "page": self._page_info(page_id, page)}

            raise ValueError("Unsupported mode. Use fill, type, select, check, or uncheck")

        if action == "drag_and_drop":
            page_id, page = self._resolve_page(params.get("page_id"))
            source = str(params.get("source", "")).strip()
            target = str(params.get("target", "")).strip()
            if not source:
                raise ValueError("'source' is required")
            if not target:
                raise ValueError("'target' is required")
            timeout = int(params.get("timeout", 30000))
            drag_kwargs: dict[str, Any] = {"timeout": timeout}
            if params.get("source_position") is not None:
                drag_kwargs["source_position"] = params.get("source_position")
            if params.get("target_position") is not None:
                drag_kwargs["target_position"] = params.get("target_position")
            page.locator(source).first.drag_to(page.locator(target).first, **drag_kwargs)
            return {"message": f"Dragged {source} to {target}", "page": self._page_info(page_id, page)}

        if action == "scroll":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            timeout = int(params.get("timeout", 30000))
            if selector:
                page.locator(selector).first.scroll_into_view_if_needed(timeout=timeout)
            else:
                x = int(params.get("x", 0))
                y = int(params.get("y", 0))
                if str(params.get("mode", "to")) == "by":
                    page.evaluate("(coords) => window.scrollBy(coords.x, coords.y)", {"x": x, "y": y})
                else:
                    page.evaluate("(coords) => window.scrollTo(coords.x, coords.y)", {"x": x, "y": y})
            position = page.evaluate(
                "() => ({x: window.scrollX, y: window.scrollY, width: window.innerWidth, height: window.innerHeight})"
            )
            return {"position": _json_safe(position), "page": self._page_info(page_id, page)}

        if action == "inspect":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")

            timeout = int(params.get("timeout", 30000))
            max_chars = int(params.get("max_chars", 4000))
            locator = page.locator(selector)
            count = locator.count()
            if count < 1:
                raise ValueError(f"No elements matched selector: {selector}")

            first = locator.first
            result: dict[str, Any] = {
                "selector": selector,
                "count": count,
                "page": self._page_info(page_id, page),
            }

            try:
                result["visible"] = first.is_visible()
            except Exception:
                pass
            try:
                result["enabled"] = first.is_enabled()
            except Exception:
                pass
            try:
                result["editable"] = first.is_editable()
            except Exception:
                pass
            try:
                result["checked"] = first.is_checked()
            except Exception:
                pass
            try:
                result["tag_name"] = first.evaluate("(element) => element.tagName.toLowerCase()")
            except Exception:
                pass
            try:
                value = first.input_value(timeout=timeout)
                if value != "":
                    result["value"] = value
            except Exception:
                pass
            try:
                handle = first.element_handle(timeout=timeout)
            except Exception:
                handle = None

            if bool(params.get("include_text", True)):
                try:
                    text = first.inner_text(timeout=timeout)
                    result["text_total_chars"] = len(text)
                    result["text_truncated"] = max_chars > 0 and len(text) > max_chars
                    result["text"] = text[:max_chars] if max_chars > 0 and len(text) > max_chars else text
                except Exception:
                    pass

            if bool(params.get("include_html", False)):
                try:
                    html = first.inner_html(timeout=timeout)
                    result["html_total_chars"] = len(html)
                    result["html_truncated"] = max_chars > 0 and len(html) > max_chars
                    result["html"] = html[:max_chars] if max_chars > 0 and len(html) > max_chars else html
                except Exception:
                    pass

            if bool(params.get("include_attributes", True)) and handle is not None:
                try:
                    result["attributes"] = _json_safe(
                        handle.evaluate(
                            "(element) => Object.fromEntries([...element.attributes].map((attr) => [attr.name, attr.value]))"
                        )
                    )
                except Exception:
                    pass
                try:
                    result["bounding_box"] = _json_safe(handle.bounding_box())
                except Exception:
                    pass

            return result

        if action == "upload":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")
            timeout = int(params.get("timeout", 30000))
            files = self._upload_paths(params.get("files", params.get("file")))
            page.locator(selector).first.set_input_files(files, timeout=timeout)
            return {"files": files, "page": self._page_info(page_id, page)}

        if action == "evaluate":
            page_id, page = self._resolve_page(params.get("page_id"))
            expression = params.get("expression")
            if expression is None:
                raise ValueError("'expression' is required")
            if "arg" in params:
                result = page.evaluate(str(expression), params.get("arg"))
            else:
                result = page.evaluate(str(expression))
            return {"result": _json_safe(result), "page": self._page_info(page_id, page)}

        if action == "content":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = params.get("selector")
            content_mode = str(params.get("mode", "html"))
            timeout = int(params.get("timeout", 30000))
            max_chars = int(params.get("max_chars", 20000))

            if selector:
                locator = page.locator(str(selector)).first
                data = locator.inner_text(timeout=timeout) if content_mode == "text" else locator.inner_html(timeout=timeout)
            else:
                data = page.inner_text("body", timeout=timeout) if content_mode == "text" else page.content()

            total_chars = len(data)
            truncated = False
            if max_chars > 0 and total_chars > max_chars:
                data = data[:max_chars]
                truncated = True

            return {
                "page": self._page_info(page_id, page),
                "mode": content_mode,
                "truncated": truncated,
                "total_chars": total_chars,
                "content": data,
            }

        if action == "set_viewport":
            width = params.get("width")
            height = params.get("height")
            if width is None or height is None:
                raise ValueError("'width' and 'height' are required")
            page_id, page = self._resolve_page(params.get("page_id"))
            viewport = {"width": int(width), "height": int(height)}
            page.set_viewport_size(viewport)
            return {"viewport": viewport, "page": self._page_info(page_id, page)}

        if action == "wait_for_selector":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")
            state = str(params.get("state", "visible"))
            timeout = int(params.get("timeout", 30000))
            page.wait_for_selector(selector, state=state, timeout=timeout)
            return {
                "message": f"Selector reached state '{state}': {selector}",
                "page": self._page_info(page_id, page),
            }

        if action == "wait_for_load_state":
            page_id, page = self._resolve_page(params.get("page_id"))
            state = str(params.get("state", "load"))
            timeout = int(params.get("timeout", 30000))
            page.wait_for_load_state(state=state, timeout=timeout)
            return {
                "message": f"Load state reached: {state}",
                "page": self._page_info(page_id, page),
            }

        if action == "console_network":
            max_entries = int(params.get("max_entries", 50))
            include_network = bool(params.get("include_network", True))
            include_console = bool(params.get("include_console", True))
            result: dict[str, Any] = {}
            if include_console:
                result["console_messages"] = self.console_messages[-max_entries:]
            if include_network:
                result["network_events"] = self.network_events[-max_entries:]
            if bool(params.get("clear", False)):
                self.console_messages.clear()
                self.network_events.clear()
            return result

        if action == "screenshot":
            page_id, page = self._resolve_page(params.get("page_id"))
            output_path = self._artifact_path(params.get("path"), "screenshot", ".png")
            selector = params.get("selector")
            timeout = int(params.get("timeout", 30000))
            if selector:
                page.locator(str(selector)).first.screenshot(path=str(output_path), timeout=timeout)
            else:
                page.screenshot(path=str(output_path), timeout=timeout, full_page=bool(params.get("full_page", True)))
            return {"path": str(output_path), "page": self._page_info(page_id, page)}

        if action == "pdf":
            page_id, page = self._resolve_page(params.get("page_id"))
            output_path = self._artifact_path(params.get("path"), "page", ".pdf")
            page.pdf(
                path=str(output_path),
                format=str(params.get("format", "A4")),
                print_background=bool(params.get("print_background", True)),
            )
            return {"path": str(output_path), "page": self._page_info(page_id, page)}

        if action == "download":
            page_id, page = self._resolve_page(params.get("page_id"))
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("'selector' is required")
            timeout = int(params.get("timeout", 30000))
            with page.expect_download(timeout=timeout) as download_info:
                page.locator(selector).first.click(timeout=timeout)
            download = download_info.value
            raw_path = params.get("path")
            if raw_path:
                output_path = self._artifact_path(raw_path, "download", Path(download.suggested_filename or "download").suffix)
            else:
                suggested = Path(download.suggested_filename or "download")
                output_path = self._artifact_path(None, suggested.stem or "download", suggested.suffix)
            download.save_as(str(output_path))
            return {
                "path": str(output_path),
                "suggested_filename": download.suggested_filename,
                "page": self._page_info(page_id, page),
            }

        if action == "cookies":
            if self.context is None:
                self.restart()
            assert self.context is not None
            mode = str(params.get("mode", "list"))

            if mode == "list":
                urls = params.get("urls")
                if urls is None and bool(params.get("current_page", False)):
                    _page_id, page = self._resolve_page(params.get("page_id"))
                    urls = [page.url] if page.url else None
                elif urls is not None and not isinstance(urls, list):
                    urls = [urls]
                cookies = self.context.cookies([str(url) for url in urls]) if urls else self.context.cookies()
                return {"cookies": cookies, "count": len(cookies)}

            if mode == "clear":
                self.context.clear_cookies()
                return {"message": "Cookies cleared"}

            if mode == "add":
                cookies = params.get("cookies", params.get("cookie"))
                if cookies is None:
                    raise ValueError("'cookie' or 'cookies' is required for mode=add")
                if not isinstance(cookies, list):
                    cookies = [cookies]
                self.context.add_cookies(cookies)
                return {"message": f"Added {len(cookies)} cookies", "count": len(cookies)}

            raise ValueError("Unsupported cookies mode. Use list, clear, or add")

        if action == "clear_storage":
            page_id, page = self._resolve_page(params.get("page_id"))
            page.evaluate(
                "() => { try { window.localStorage.clear(); } catch (error) {} try { window.sessionStorage.clear(); } catch (error) {} return true; }"
            )
            if self.context is not None and bool(params.get("clear_cookies", False)):
                self.context.clear_cookies()
            if bool(params.get("reload", False)):
                page.reload(wait_until=str(params.get("wait_until", "load")), timeout=int(params.get("timeout", 30000)))
            return {
                "message": "Cleared localStorage and sessionStorage",
                "cookies_cleared": bool(params.get("clear_cookies", False)),
                "page": self._page_info(page_id, page),
            }

        if action == "close_browser":
            self.restart()
            return {
                "message": "Browser restarted",
                "pages": self._list_pages(),
                "active_page_id": self.active_page_id,
            }

        if action == "save_auth":
            profile_name = self._profile_name(params.get("name"))
            auth_file = self._auth_file(profile_name)
            assert self.context is not None
            self.context.storage_state(path=str(auth_file))
            return {"message": f"Saved auth state '{profile_name}'", "name": profile_name, "path": str(auth_file)}

        if action == "load_auth":
            profile_name = self._profile_name(params.get("name"))
            auth_file = self._auth_file(profile_name)
            if not auth_file.is_file():
                raise ValueError(f"Auth state '{profile_name}' not found")
            self.restart(storage_state=str(auth_file))
            return {"message": f"Loaded auth state '{profile_name}'", "name": profile_name, "path": str(auth_file)}

        if action == "list_auth":
            AUTH_ROOT.mkdir(parents=True, exist_ok=True)
            profiles = [path.stem for path in sorted(AUTH_ROOT.glob("*.json")) if path.is_file()]
            return {"profiles": profiles, "count": len(profiles)}

        if action == "delete_auth":
            profile_name = self._profile_name(params.get("name"))
            auth_file = self._auth_file(profile_name)
            if not auth_file.is_file():
                raise ValueError(f"Auth state '{profile_name}' not found")
            auth_file.unlink()
            return {"message": f"Deleted auth state '{profile_name}'", "name": profile_name, "path": str(auth_file)}

        raise ValueError(f"Unknown action: {action}")

    def handle(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._run(action, params)
        except Exception as exc:
            if _PLAYWRIGHT_ERROR_TYPES and isinstance(exc, _PLAYWRIGHT_ERROR_TYPES):
                if "Target page, context or browser has been closed" in str(exc):
                    self.restart()
                    return self._run(action, params)
            raise


class Handler(BaseHTTPRequestHandler):
    server_version = "PlaywrightWorkflow/1.0"

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        server = cast(PlaywrightServer, self.server)
        self._send_json(
            200,
            {
                "ok": True,
                "service": SERVICE_NAME,
                "pid": os.getpid(),
                "headless": server.session.headless,
                "channel": server.session.channel,
                "pages": server.session._list_pages(),
                "active_page_id": server.session.active_page_id,
            },
        )

    def do_POST(self) -> None:
        if self.path != "/command":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Invalid Content-Length"})
            return

        try:
            body = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "Invalid JSON body"})
            return

        action = body.get("action")
        params = body.get("params") or {}
        if not action:
            self._send_json(400, {"ok": False, "error": "'action' is required"})
            return

        server = cast(PlaywrightServer, self.server)
        if str(action) == "shutdown":
            self._send_json(200, {"ok": True, "message": "Server shutting down"})
            server.request_stop()
            return

        try:
            with server.command_lock:
                result = server.session.handle(str(action), params)
            self._send_json(200, {"ok": True, **result})
        except Exception as exc:
            self._send_json(200, {"ok": False, "error": str(exc)})

    def log_message(self, _format: str, *args: Any) -> None:
        return


class PlaywrightServer(HTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], *, headless: bool, channel: str | None) -> None:
        super().__init__(server_address, handler_class)
        self.session = BrowserSession(headless=headless, channel=channel)
        self.command_lock = threading.Lock()

    def request_stop(self) -> None:
        # Stop serve_forever() from a separate thread (HTTPServer.shutdown() must
        # not run on the serving thread). Browser/Playwright teardown happens in
        # main() after serve_forever() returns, on the thread that created those
        # objects — calling session.close() here would touch the sync Playwright
        # API from the wrong thread and hang, leaving the port bound.
        threading.Thread(target=self.shutdown, daemon=True).start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the persistent Playwright workflow daemon",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  playwright_daemon.py --port 17337\n"
            "  playwright_daemon.py --port 17337 --headed\n"
            "  playwright_daemon.py --port 17337 --channel chrome\n\n"
            "Usually start through playwright_launch.py so runtime setup happens automatically."
        ),
    )
    parser.add_argument("--port", type=int, default=17337, help="HTTP port. Default: 17337")
    parser.add_argument("--headed", action="store_true", help="Launch browser in headed mode")
    parser.add_argument("--channel", default="", help="Optional browser channel, e.g. chrome or msedge")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    server = PlaywrightServer(
        ("127.0.0.1", args.port),
        Handler,
        headless=not args.headed,
        channel=args.channel or None,
    )

    def _handle_signal(_signum: int, _frame: Any) -> None:
        server.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        server.serve_forever()
    finally:
        # Tear down on the main thread, where the Playwright objects were created,
        # then release the listening socket so the port is freed immediately.
        try:
            server.session.close()
        finally:
            server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(os.sys.argv[1:]))
