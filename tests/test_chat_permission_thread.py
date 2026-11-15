"""Authorize/unauthorize must accept the ``chat_id|thread_id`` form."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_chat_permission(monkeypatch):
    user_data = {}
    sent = []

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    def update_user_ldata(id_, key, value):
        user_data.setdefault(id_, {})
        user_data[id_][key] = value

    async def send_message(message, text, buttons=None):
        sent.append(text)
        return SimpleNamespace(id=1)

    async def noop(*args, **kwargs):
        return None

    stub(
        "bot",
        user_data=user_data,
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub(
        "bot.helper.ext_utils.bot_utils",
        update_user_ldata=update_user_ldata,
        new_task=lambda func: func,
    )
    stub(
        "bot.helper.ext_utils.db_handler",
        database=SimpleNamespace(update_user_data=noop),
    )
    stub("bot.helper.telegram_helper.message_utils", send_message=send_message)

    spec = importlib.util.spec_from_file_location(
        "bot.modules.chat_permission",
        ROOT / "bot" / "modules" / "chat_permission.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.chat_permission", module)
    spec.loader.exec_module(module)
    module.user_data = user_data
    module.sent = sent
    return module


def _message(text):
    return SimpleNamespace(
        text=text,
        reply_to_message=None,
        topic_message=None,
        message_thread_id=None,
        chat=SimpleNamespace(id=1),
    )


async def test_authorize_parses_thread_id(monkeypatch):
    module = _load_chat_permission(monkeypatch)

    await module.authorize(None, _message("/authorize -100123|45"))

    assert module.user_data[-100123]["AUTH"] is True
    assert module.user_data[-100123]["thread_ids"] == [45]
    assert module.sent[-1] == "Authorized"


async def test_unauthorize_parses_thread_id(monkeypatch):
    module = _load_chat_permission(monkeypatch)
    module.user_data[-100123] = {"AUTH": True, "thread_ids": [45, 46]}

    await module.unauthorize(None, _message("/unauthorize -100123|45"))

    assert module.user_data[-100123]["thread_ids"] == [46]
    assert module.user_data[-100123]["AUTH"] is True
    assert module.sent[-1] == "Unauthorized"
