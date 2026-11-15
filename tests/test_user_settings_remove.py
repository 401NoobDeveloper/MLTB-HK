"""Removing a file setting (thumbnail/rclone config/token) must be safe."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(monkeypatch, user_data):
    async def noop(*args, **kwargs):
        return None

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    def update_user_ldata(user_id, key, value):
        user_data.setdefault(user_id, {})[key] = value

    stub(
        "bot",
        user_data=user_data,
        excluded_extensions=[],
        auth_chats={},
        sudo_users=[],
        included_extensions=[],
    )
    stub("bot.core")
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub(
        "bot.core.config_manager",
        Config=SimpleNamespace(FFMPEG_CMDS={}, TORRENT_FILE_TYPES=[]),
    )
    stub(
        "bot.core.telegram_manager",
        TgClient=SimpleNamespace(bot=None, user=None),
    )
    stub(
        "bot.helper.ext_utils.db_handler",
        database=SimpleNamespace(update_user_doc=noop, update_user_data=noop),
    )
    stub("bot.helper.ext_utils.media_utils", create_thumb=noop)
    stub("bot.helper.telegram_helper.button_build", ButtonMaker=SimpleNamespace)
    stub("bot.helper.ext_utils.help_messages", user_settings_text="")
    stub(
        "bot.helper.ext_utils.bot_utils",
        update_user_ldata=update_user_ldata,
        new_task=lambda func: func,
        get_size_bytes=lambda value: 0,
    )
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size} B",
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=noop,
        edit_message=noop,
        send_file=noop,
        delete_message=noop,
    )

    file_types_spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.file_types",
        ROOT / "bot" / "helper" / "ext_utils" / "file_types.py",
    )
    file_types = importlib.util.module_from_spec(file_types_spec)
    monkeypatch.setitem(
        sys.modules, "bot.helper.ext_utils.file_types", file_types
    )
    file_types_spec.loader.exec_module(file_types)

    spec = importlib.util.spec_from_file_location(
        "bot.modules.users_settings",
        ROOT / "bot" / "modules" / "users_settings.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.users_settings", module)
    spec.loader.exec_module(module)
    return module


def _query(data):
    answers = []

    async def answer(*args, **kwargs):
        answers.append((args, kwargs))

    query = SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=1, mention="@user"),
        message=SimpleNamespace(chat=SimpleNamespace(id=1)),
        answer=answer,
    )
    return query, answers


async def test_remove_missing_rclone_config_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    user_data = {1: {}}
    module = _load(monkeypatch, user_data)
    query, answers = _query("userset 1 remove RCLONE_CONFIG")

    await module.edit_user_settings(None, query)

    assert answers and answers[-1][0][0] == "Removed!"
    assert "RCLONE_CONFIG" not in user_data[1]


async def test_remove_existing_token_pickle(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    user_data = {1: {"TOKEN_PICKLE": "tokens/1.pickle"}}
    module = _load(monkeypatch, user_data)
    (tmp_path / "tokens").mkdir()
    token = tmp_path / "tokens" / "1.pickle"
    token.write_bytes(b"token")
    query, answers = _query("userset 1 remove TOKEN_PICKLE")

    await module.edit_user_settings(None, query)

    assert not token.exists()
    assert "TOKEN_PICKLE" not in user_data[1]
    assert answers and answers[-1][0][0] == "Removed!"
