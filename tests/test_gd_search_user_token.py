"""Listing with a user token must search the user's own configured drive."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_gd_search(monkeypatch):
    user_data = {7: {"GDRIVE_ID": "mt:user-drive-id"}}
    searches = []

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    async def noop(*args, **kwargs):
        return None

    async def sync_to_async(func, *args, **kwargs):
        return func(*args, **kwargs)

    class GoogleDriveSearch:
        def __init__(self, **kwargs):
            pass

        def drive_list(self, key, target_id="", user_id=""):
            searches.append((key, target_id, user_id))
            return [], 0

    stub(
        "bot",
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        user_data=user_data,
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.mirror_leech_utils")
    stub("bot.helper.mirror_leech_utils.gdrive_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub(
        "bot.helper.ext_utils.bot_utils",
        sync_to_async=sync_to_async,
        get_telegraph_list=noop,
        new_task=lambda func: func,
    )
    stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.search",
        GoogleDriveSearch=GoogleDriveSearch,
    )
    stub(
        "bot.helper.telegram_helper.button_build",
        ButtonMaker=SimpleNamespace,
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=noop,
        edit_message=noop,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.modules.gd_search", ROOT / "bot" / "modules" / "gd_search.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.gd_search", module)
    spec.loader.exec_module(module)
    module.searches = searches
    return module


async def test_list_drive_uses_user_configured_drive(monkeypatch):
    module = _load_gd_search(monkeypatch)
    message = SimpleNamespace()

    await module._list_drive("movie", message, "both", True, True, 7)

    assert module.searches == [("movie", "mt:user-drive-id", 7)]
