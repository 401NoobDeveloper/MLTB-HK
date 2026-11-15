"""A status button whose task is already gone must not raise."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


class FakeLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _load_file_selector(monkeypatch):
    answers = []

    async def get_task_by_gid(gid):
        return None

    async def noop(*args, **kwargs):
        return None

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    stub(
        "bot",
        task_dict={},
        task_dict_lock=FakeLock(),
        user_data={},
        LOGGER=SimpleNamespace(info=noop, error=noop),
    )
    stub("bot.core")
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub("bot.core.config_manager", Config=SimpleNamespace(BASE_URL="", OWNER_ID=1))
    stub("bot.core.torrent_manager", TorrentManager=SimpleNamespace(aria2=None))
    stub(
        "bot.core.telegram_manager",
        TgClient=SimpleNamespace(bot=None, user=None),
    )
    stub(
        "bot.helper.ext_utils.bot_utils",
        bt_selection_buttons=lambda *args, **kwargs: None,
        new_task=lambda func: func,
    )
    stub(
        "bot.helper.ext_utils.status_utils",
        get_task_by_gid=get_task_by_gid,
        MirrorStatus=SimpleNamespace(
            STATUS_DOWNLOAD="Download",
            STATUS_PAUSED="Pause",
            STATUS_QUEUEDL="QueueDl",
        ),
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=noop,
        send_status_message=noop,
        delete_message=noop,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.modules.file_selector", ROOT / "bot" / "modules" / "file_selector.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.file_selector", module)
    spec.loader.exec_module(module)
    module.answers = answers
    return module


async def test_select_callback_with_finished_task_answers_click(monkeypatch):
    module = _load_file_selector(monkeypatch)

    async def answer(*args, **kwargs):
        module.answers.append((args, kwargs))

    query = SimpleNamespace(
        data="sel select 0123456789abcdef",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        answer=answer,
    )

    await module.select_callback(query)

    assert module.answers, "the callback must still answer the click"
    assert "cancel" in str(module.answers[0][0][0]).lower()
