"""Replying to a media message must not crash /count or /del."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _stub(monkeypatch, name, **attrs):
    module = ModuleType(name)
    module.__path__ = []
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load(monkeypatch, module_name, extra_stubs):
    sent = []

    async def send_message(message, text, buttons=None):
        sent.append(text)
        return SimpleNamespace(id=1)

    async def noop(*args, **kwargs):
        return None

    async def sync_to_async(func, *args, **kwargs):
        return func(*args, **kwargs)

    _stub(
        monkeypatch,
        "bot",
        LOGGER=SimpleNamespace(info=noop, error=noop),
        user_data={},
    )
    _stub(monkeypatch, "bot.helper")
    _stub(monkeypatch, "bot.helper.ext_utils")
    _stub(monkeypatch, "bot.helper.telegram_helper")
    _stub(monkeypatch, "bot.modules")
    _stub(
        monkeypatch,
        "bot.helper.ext_utils.bot_utils",
        sync_to_async=sync_to_async,
        new_task=lambda func: func,
        get_telegraph_list=noop,
    )
    _stub(
        monkeypatch,
        "bot.helper.ext_utils.links_utils",
        is_gdrive_link=lambda link: "drive.google.com" in link,
    )
    _stub(
        monkeypatch,
        "bot.helper.telegram_helper.message_utils",
        send_message=send_message,
        delete_message=noop,
        auto_delete_message=noop,
        edit_message=noop,
    )
    _stub(
        monkeypatch,
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size}B",
    )
    for name, attrs in extra_stubs.items():
        _stub(monkeypatch, name, **attrs)

    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / "bot" / "modules" / f"{module_name.rsplit('.', 1)[1]}.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    module.sent = sent
    return module


MEDIA_REPLY = SimpleNamespace(text=None, photo=object(), video=None, document=None)


@pytest.mark.parametrize(
    ("module_name", "entry", "extra_stubs", "usage"),
    [
        (
            "bot.modules.gd_delete",
            "delete_file",
            {
                "bot.helper.mirror_leech_utils.gdrive_utils.delete": {
                    "GoogleDriveDelete": SimpleNamespace
                }
            },
            "Send Gdrive link",
        ),
        (
            "bot.modules.gd_count",
            "count_node",
            {
                "bot.helper.mirror_leech_utils.gdrive_utils.count": {
                    "GoogleDriveCount": SimpleNamespace
                }
            },
            "Send Gdrive link",
        ),
    ],
)
async def test_reply_without_text_reports_usage(
    monkeypatch, module_name, entry, extra_stubs, usage
):
    module = _load(monkeypatch, module_name, extra_stubs)
    message = SimpleNamespace(
        text="/count",
        from_user=SimpleNamespace(id=1, username="user", mention="@user"),
        reply_to_message=MEDIA_REPLY,
    )

    await getattr(module, entry)(None, message)

    assert module.sent, "the command must answer instead of raising"
    assert usage in module.sent[-1]


async def test_list_callback_survives_deleted_command_message(monkeypatch):
    module = _load(
        monkeypatch,
        "bot.modules.gd_search",
        {
            "bot.helper.mirror_leech_utils.gdrive_utils.search": {
                "GoogleDriveSearch": SimpleNamespace
            },
            "bot.helper.telegram_helper.button_build": {
                "ButtonMaker": SimpleNamespace
            },
        },
    )
    answers = []

    async def answer(text=None, **kwargs):
        answers.append(text)

    query = SimpleNamespace(
        data="list_types 1 folders True False",
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(reply_to_message=None),
        answer=answer,
    )

    await module.select_type(None, query)

    assert answers and "deleted" in answers[0].lower()
