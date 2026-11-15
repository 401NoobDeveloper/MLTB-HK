"""The Cancel button of the yt-dlp audio-quality menu must cancel the task."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_ytdlp(monkeypatch):
    edits = []

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    async def noop(*args, **kwargs):
        return None

    async def edit_message(message, text=None, buttons=None, **kwargs):
        edits.append((text, buttons))
        return None

    async def sync_to_async(func, *args, **kwargs):
        return func(*args, **kwargs)

    def new_task(func):
        return func

    yt_dlp = stub(
        "yt_dlp",
        YoutubeDL=object,
        DownloadError=Exception,
    )
    yt_dlp.__path__ = []

    stub(
        "bot",
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        bot_loop=SimpleNamespace(create_task=lambda coro: coro),
        task_dict_lock=SimpleNamespace(),
        DOWNLOAD_DIR="/tmp/",
    )
    stub("bot.core")
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.listeners")
    stub("bot.helper.mirror_leech_utils")
    stub("bot.helper.mirror_leech_utils.download_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub(
        "bot.core.config_manager",
        Config=SimpleNamespace(YT_DLP_OPTIONS={}),
    )
    stub(
        "bot.helper.ext_utils.bot_utils",
        new_task=new_task,
        sync_to_async=sync_to_async,
        arg_parser=noop,
        COMMAND_USAGE={},
    )
    stub("bot.helper.ext_utils.links_utils", is_url=lambda link: False)
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size}B",
        get_readable_time=lambda seconds: f"{seconds}s",
    )
    stub("bot.helper.listeners.task_listener", TaskListener=object)
    stub(
        "bot.helper.mirror_leech_utils.download_utils.yt_dlp_download",
        YoutubeDLHelper=object,
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=noop,
        edit_message=edit_message,
        delete_message=noop,
    )

    button_build_spec = importlib.util.spec_from_file_location(
        "bot.helper.telegram_helper.button_build",
        ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py",
    )
    button_build = importlib.util.module_from_spec(button_build_spec)
    monkeypatch.setitem(
        sys.modules, "bot.helper.telegram_helper.button_build", button_build
    )
    button_build_spec.loader.exec_module(button_build)

    spec = importlib.util.spec_from_file_location(
        "bot.modules.ytdlp", ROOT / "bot" / "modules" / "ytdlp.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.ytdlp", module)
    spec.loader.exec_module(module)
    module.edits = edits
    return module


def _button_data(markup, text):
    for row in markup.inline_keyboard:
        for button in row:
            if button.text == text:
                return button.callback_data
    raise AssertionError(f"No {text!r} button in menu")


async def test_audio_quality_cancel_button_cancels_task(monkeypatch):
    module = _load_ytdlp(monkeypatch)
    listener = SimpleNamespace(
        is_cancelled=False,
        user_id=1,
        size=0,
        name="video",
        message=SimpleNamespace(),
        client=SimpleNamespace(),
    )
    selection = module.YtSelection(listener)

    await selection.audio_quality("ba/b-flac-")
    cancel_data = _button_data(module.edits[-1][1], "Cancel")

    async def answer(*args, **kwargs):
        return None

    query = SimpleNamespace(
        data=cancel_data,
        message=SimpleNamespace(),
        answer=answer,
    )
    await module.select_format(None, query, selection)

    assert selection.listener.is_cancelled is True
    assert selection.event.is_set()
    assert selection.qual is None
