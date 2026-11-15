"""Regression tests for /select on a task that is still waiting in the queue."""

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


class FakeTask:
    def __init__(self, gid="gidABC", queued=False, name="Torrent", batch_mode=False):
        self._gid = gid
        self.queued = queued
        self.updated = 0
        self.listener = SimpleNamespace(
            user_id=1,
            is_torrent=True,
            select=False,
            mid=5,
            name=name,
            batch_mode=batch_mode,
        )

    async def update(self):
        self.updated += 1

    def gid(self):
        return self._gid

    def name(self):
        return self.listener.name

    async def status(self):
        return "QueueDl"


def _load_file_selector(monkeypatch, task):
    sent = []
    answers = []

    async def send_message(message, text, buttons=None):
        sent.append((text, buttons))
        return SimpleNamespace(id=1, chat=SimpleNamespace(id=1))

    async def send_status_message(*args, **kwargs):
        return None

    async def delete_message(*args, **kwargs):
        return None

    async def get_task_by_gid(gid):
        return task

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
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
    )
    stub("bot.core")
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub(
        "bot.core.config_manager",
        Config=SimpleNamespace(BASE_URL="http://localhost:8080", OWNER_ID=1),
    )
    stub(
        "bot.core.torrent_manager",
        TorrentManager=SimpleNamespace(aria2=SimpleNamespace()),
    )
    stub(
        "bot.core.telegram_manager",
        TgClient=SimpleNamespace(
            bot=SimpleNamespace(get_messages=None), user=None
        ),
    )
    stub(
        "bot.helper.ext_utils.bot_utils",
        bt_selection_buttons=lambda gid: f"buttons:{gid}",
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
        send_message=send_message,
        send_status_message=send_status_message,
        delete_message=delete_message,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.modules.file_selector", ROOT / "bot" / "modules" / "file_selector.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.file_selector", module)
    spec.loader.exec_module(module)
    module.sent = sent
    module.answers = answers
    return module


async def test_select_on_queued_task_shows_selection_buttons(monkeypatch):
    task = FakeTask(queued=True)
    module = _load_file_selector(monkeypatch, task)
    message = SimpleNamespace(
        text="/select gidABC",
        from_user=SimpleNamespace(id=1),
        reply_to_message_id=None,
        chat=SimpleNamespace(id=1),
    )

    await module.select(None, message)

    assert module.sent[-1][1] == "buttons:gidABC"
    assert task.listener.select is True
    assert task.updated == 0


async def test_select_callback_on_queued_task_shows_selection_buttons(monkeypatch):
    task = FakeTask(queued=True)
    module = _load_file_selector(monkeypatch, task)
    module.TgClient.bot.get_messages = _async_message

    async def answer(*args, **kwargs):
        module.answers.append((args, kwargs))

    query = SimpleNamespace(
        data="sel select gidABC",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        answer=answer,
    )

    await module.select_callback(query)

    assert module.sent[-1][1] == "buttons:gidABC"
    assert task.listener.select is True


def _batch_task(monkeypatch):
    task = FakeTask(queued=False, batch_mode=True)
    module = _load_file_selector(monkeypatch, task)
    paused = []

    async def force_pause(gid):
        paused.append(gid)

    async def tell_status(gid):
        return {"status": "active"}

    module.TorrentManager.aria2.forcePause = force_pause
    module.TorrentManager.aria2.tellStatus = tell_status
    module.TgClient.bot.get_messages = _async_message
    return task, module, paused


async def test_select_callback_rejects_batch_task(monkeypatch):
    task, module, paused = _batch_task(monkeypatch)
    answers = []

    async def answer(*args, **kwargs):
        answers.append((args, kwargs))

    query = SimpleNamespace(
        data="sel select gidABC",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        answer=answer,
    )

    await module.select_callback(query)

    assert paused == []
    assert task.listener.select is False
    assert answers and "batch" in str(answers[-1][0][0]).lower()


async def test_select_command_rejects_batch_task(monkeypatch):
    task, module, paused = _batch_task(monkeypatch)
    message = SimpleNamespace(
        text="/select gidABC",
        from_user=SimpleNamespace(id=1),
        reply_to_message_id=None,
        chat=SimpleNamespace(id=1),
    )

    await module.select(None, message)

    assert paused == []
    assert task.listener.select is False
    assert module.sent and "batch" in module.sent[-1][0].lower()


async def _async_message(*args, **kwargs):
    return SimpleNamespace(id=2, chat=SimpleNamespace(id=1))
