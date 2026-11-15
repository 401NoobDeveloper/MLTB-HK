"""Regression tests for the content-type probe used before every mirror."""

from __future__ import annotations

import asyncio
import http.server
import importlib.util
import socketserver
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_MODULE_NAME = "bot.helper.ext_utils.bot_utils"


def _stub(saved, name, **attrs):
    module = types.ModuleType(name)
    module.__path__ = []
    for key, value in attrs.items():
        setattr(module, key, value)
    saved[name] = sys.modules.get(name)
    sys.modules[name] = module
    return module


@pytest.fixture(scope="module")
def bot_utils():
    """Load bot_utils.py without importing the bot package (needs uvloop)."""
    if _MODULE_NAME in sys.modules:
        yield sys.modules[_MODULE_NAME]
        return

    saved: dict[str, object] = {}
    try:
        _stub(saved, "bot", user_data={}, bot_loop=asyncio.new_event_loop())
        _stub(saved, "bot.core")
        _stub(saved, "bot.core.config_manager", Config=types.SimpleNamespace())
        _stub(saved, "bot.helper")
        _stub(saved, "bot.helper.ext_utils")
        _stub(saved, "bot.helper.telegram_helper")
        _stub(saved, "bot.helper.telegram_helper.button_build", ButtonMaker=object)
        _stub(saved, "bot.helper.ext_utils.telegraph_helper", telegraph=object)
        _stub(
            saved,
            "bot.helper.ext_utils.help_messages",
            YT_HELP_DICT={"main": ""},
            GDL_HELP_DICT={"main": ""},
            MIRROR_HELP_DICT={"main": ""},
            CLONE_HELP_DICT={"main": ""},
        )
        spec = importlib.util.spec_from_file_location(
            _MODULE_NAME, ROOT / "bot" / "helper" / "ext_utils" / "bot_utils.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[_MODULE_NAME] = module
        spec.loader.exec_module(module)
    except Exception:
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
        raise

    yield module

    for name, original in saved.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original
    sys.modules.pop(_MODULE_NAME, None)


class _Server:
    def __init__(self, handler):
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/file.bin"

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def _head_only_handler():
    class Handler(http.server.BaseHTTPRequestHandler):
        methods: list[str] = []

        def do_HEAD(self):
            self.methods.append("HEAD")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            self.methods.append("GET")
            self.send_error(500, "the body must never be requested")

        def log_message(self, *args):
            pass

    return Handler


def _no_head_handler():
    payload = b"x" * (2 * 1024 * 1024)

    class Handler(http.server.BaseHTTPRequestHandler):
        methods: list[str] = []

        def do_HEAD(self):
            self.methods.append("HEAD")
            self.send_response(405)
            self.end_headers()

        def do_GET(self):
            self.methods.append("GET")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            try:
                self.wfile.write(payload)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    return Handler


def test_probe_uses_head_and_returns_content_type(bot_utils):
    handler = _head_only_handler()
    with _Server(handler) as url:
        content_type = asyncio.run(bot_utils.get_content_type(url))
    assert content_type == "text/html; charset=utf-8"
    assert handler.methods == ["HEAD"]


def test_probe_falls_back_to_a_streamed_get_when_head_is_rejected(bot_utils):
    handler = _no_head_handler()
    with _Server(handler) as url:
        content_type = asyncio.run(bot_utils.get_content_type(url))
    assert content_type == "application/octet-stream"
    assert handler.methods == ["HEAD", "GET"]
