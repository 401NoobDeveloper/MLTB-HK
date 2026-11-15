"""The cancel-all menu must ignore buttons pressed by someone else."""

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


class FakeButtonMaker:
    def data_button(self, *args, **kwargs):
        return None

    def build_menu(self, *args, **kwargs):
        return None


def _load_cancel_task(monkeypatch):
    calls = {"cancelled": [], "answers": [], "messages": [], "edits": []}

    async def get_all_tasks(status, user_id):
        calls["cancelled"].append((status, user_id))
        return []

    async def get_task_by_gid(gid):
        return None

    async def noop(*args, **kwargs):
        return None

    async def send_message(message, text, buttons=None):
        calls["messages"].append((text, buttons))
        return SimpleNamespace(id=1)

    async def edit_message(message, text=None, buttons=None, **kwargs):
        calls["edits"].append((text, buttons))
        return None

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class CustomFilters:
        @staticmethod
        async def sudo(_, update):
            return False

    stub(
        "bot",
        task_dict={},
        task_dict_lock=FakeLock(),
        user_data={},
        multi_tags={},
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
        "bot.core.config_manager", Config=SimpleNamespace(OWNER_ID=1)
    )
    stub(
        "bot.core.telegram_manager",
        TgClient=SimpleNamespace(bot=SimpleNamespace(get_messages=None)),
    )
    stub("bot.helper.ext_utils.bot_utils", new_task=lambda func: func)
    stub(
        "bot.helper.ext_utils.status_utils",
        get_task_by_gid=get_task_by_gid,
        get_all_tasks=get_all_tasks,
        MirrorStatus=SimpleNamespace(
            STATUS_DOWNLOAD="Download",
            STATUS_UPLOAD="Upload",
            STATUS_SEED="Seed",
            STATUS_SPLIT="Split",
            STATUS_CLONE="Clone",
            STATUS_EXTRACT="Extract",
            STATUS_ARCHIVE="Archive",
            STATUS_QUEUEDL="QueueDl",
            STATUS_QUEUEUP="QueueUp",
            STATUS_SAMVID="SamVid",
            STATUS_CONVERT="Convert",
            STATUS_FFMPEG="FFmpeg",
            STATUS_PAUSED="Pause",
        ),
    )
    button_build = stub("bot.helper.telegram_helper.button_build", ButtonMaker=FakeButtonMaker)
    stub(
        "bot.helper.telegram_helper.bot_commands",
        BotCommands=SimpleNamespace(CancelTaskCommand=["cancel", "canceltask"]),
    )
    stub("bot.helper.telegram_helper.filters", CustomFilters=CustomFilters)
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=send_message,
        auto_delete_message=noop,
        delete_message=noop,
        edit_message=edit_message,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.modules.cancel_task", ROOT / "bot" / "modules" / "cancel_task.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.cancel_task", module)
    spec.loader.exec_module(module)
    module.calls = calls
    module.button_build = button_build
    return module


async def test_cancel_all_rejects_other_users_button(monkeypatch):
    module = _load_cancel_task(monkeypatch)
    answers = []

    async def answer(*args, **kwargs):
        answers.append((args, kwargs))

    query = SimpleNamespace(
        data="canall ms All 999",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            reply_to_message=SimpleNamespace(id=1), chat=SimpleNamespace(id=1)
        ),
        answer=answer,
    )

    await module.cancel_all_update(None, query)

    assert module.calls["cancelled"] == []
    assert module.calls["edits"] == []
    assert ("Not Yours!",) == answers[0][0]


async def test_owner_menu_buttons_cannot_be_replayed_by_others(monkeypatch):
    """Buttons built for a sudo user carry no user id; a stranger must not use them."""
    module = _load_cancel_task(monkeypatch)
    answers = []

    async def answer(*args, **kwargs):
        answers.append((args, kwargs))

    query = SimpleNamespace(
        data="canall ms All",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(
            reply_to_message=SimpleNamespace(id=1), chat=SimpleNamespace(id=1)
        ),
        answer=answer,
    )

    await module.cancel_all_update(None, query)
    query.data = "canall All confirm"
    await module.cancel_all_update(None, query)

    assert module.calls["cancelled"] == []
