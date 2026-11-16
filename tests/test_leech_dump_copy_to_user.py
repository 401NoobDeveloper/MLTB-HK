"""Tests for copying leeched files to the requesting user's PM."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _module(monkeypatch, name, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def uploader_module(monkeypatch):
    bot_pkg = _module(monkeypatch, "bot", intervals={"stopAll": False})
    bot_pkg.__path__ = []

    core_pkg = _module(monkeypatch, "bot.core")
    core_pkg.__path__ = []

    class Config:
        LEECH_DUMP_COPY_TO_USER = False
        MEDIA_GROUP = False
        LEECH_FILENAME_PREFIX = ""
        FILES_LINKS = False

    config_manager = ModuleType("bot.core.config_manager")
    config_manager.Config = Config
    monkeypatch.setitem(sys.modules, "bot.core.config_manager", config_manager)

    class TgClient:
        bot = SimpleNamespace(copy_message=AsyncMock())

    telegram_manager = ModuleType("bot.core.telegram_manager")
    telegram_manager.TgClient = TgClient
    monkeypatch.setitem(sys.modules, "bot.core.telegram_manager", telegram_manager)

    helper_pkg = _module(monkeypatch, "bot.helper")
    helper_pkg.__path__ = []

    ext_utils_pkg = _module(monkeypatch, "bot.helper.ext_utils")
    ext_utils_pkg.__path__ = []

    async def sync_to_async(func, *args, **kwargs):
        return func(*args, **kwargs)

    bot_utils = ModuleType("bot.helper.ext_utils.bot_utils")
    bot_utils.sync_to_async = sync_to_async
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.bot_utils", bot_utils)

    files_utils = ModuleType("bot.helper.ext_utils.files_utils")
    files_utils.is_archive = lambda name: False
    files_utils.get_base_name = lambda name: name
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.files_utils", files_utils)

    async def get_document_type(_):
        return False, False, False

    media_utils = ModuleType("bot.helper.ext_utils.media_utils")
    media_utils.get_media_info = AsyncMock(return_value=(0, "artist", "title"))
    media_utils.get_document_type = get_document_type
    media_utils.get_video_thumbnail = AsyncMock(return_value=None)
    media_utils.get_audio_thumbnail = AsyncMock(return_value=None)
    media_utils.get_multiple_frames_thumbnail = AsyncMock(return_value=None)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.media_utils", media_utils)

    telegram_helper_pkg = _module(monkeypatch, "bot.helper.telegram_helper")
    telegram_helper_pkg.__path__ = []

    message_utils = ModuleType("bot.helper.telegram_helper.message_utils")
    message_utils.delete_message = AsyncMock()
    monkeypatch.setitem(
        sys.modules, "bot.helper.telegram_helper.message_utils", message_utils
    )

    mlu_pkg = _module(monkeypatch, "bot.helper.mirror_leech_utils")
    mlu_pkg.__path__ = [str(ROOT / "bot" / "helper" / "mirror_leech_utils")]

    upload_utils_pkg = _module(
        monkeypatch, "bot.helper.mirror_leech_utils.upload_utils"
    )
    upload_utils_pkg.__path__ = [
        str(ROOT / "bot" / "helper" / "mirror_leech_utils" / "upload_utils")
    ]

    pil = _module(monkeypatch, "PIL")
    pil.Image = SimpleNamespace(open=lambda *args, **kwargs: None)

    _module(monkeypatch, "aioshutil", rmtree=AsyncMock())
    _module(monkeypatch, "natsort", natsorted=lambda values: sorted(values))

    aiofiles = _module(monkeypatch, "aiofiles")
    aiofiles.__path__ = []
    aiofiles_os = ModuleType("aiofiles.os")
    aiofiles_os.remove = AsyncMock()
    aiofiles_os.rename = AsyncMock()
    aiofiles_os.path = SimpleNamespace(
        exists=AsyncMock(return_value=False),
        isfile=AsyncMock(return_value=False),
    )
    monkeypatch.setitem(sys.modules, "aiofiles.os", aiofiles_os)

    pyrogram = _module(monkeypatch, "pyrogram")
    pyrogram.__path__ = []

    errors = ModuleType("pyrogram.errors")

    class RPCError(Exception):
        pass

    class BadRequest(RPCError):
        pass

    class FloodWait(RPCError):
        pass

    class FloodPremiumWait(FloodWait):
        pass

    errors.FloodWait = FloodWait
    errors.RPCError = RPCError
    errors.FloodPremiumWait = FloodPremiumWait
    errors.BadRequest = BadRequest
    monkeypatch.setitem(sys.modules, "pyrogram.errors", errors)

    types = ModuleType("pyrogram.types")
    types.InputMediaVideo = type("InputMediaVideo", (), {})
    types.InputMediaDocument = type("InputMediaDocument", (), {})
    types.InputMediaPhoto = type("InputMediaPhoto", (), {})
    monkeypatch.setitem(sys.modules, "pyrogram.types", types)

    tenacity = _module(monkeypatch, "tenacity")

    def retry(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    tenacity.retry = retry
    tenacity.wait_exponential = lambda *args, **kwargs: None
    tenacity.stop_after_attempt = lambda *args, **kwargs: None
    tenacity.retry_if_exception_type = lambda *args, **kwargs: None
    tenacity.RetryError = type("RetryError", (Exception,), {})

    sys.modules.pop(
        "bot.helper.mirror_leech_utils.upload_utils.telegram_uploader", None
    )
    uploader = importlib.import_module(
        "bot.helper.mirror_leech_utils.upload_utils.telegram_uploader"
    )
    uploader.Config = Config
    uploader.TgClient = TgClient
    return uploader


def _make_uploader(module):
    listener = SimpleNamespace(
        as_doc=True,
        is_cancelled=False,
        thumb="none",
        up_dest=-100123456,
        user_dict={},
        user_id=111222333,
        user_transmission=False,
    )
    return module.TelegramUploader(listener, str(ROOT)), listener


@pytest.mark.asyncio
async def test_copies_to_requesting_user_pm(uploader_module):
    uploader, listener = _make_uploader(uploader_module)
    uploader_module.Config.LEECH_DUMP_COPY_TO_USER = True
    await uploader._user_settings()

    message = SimpleNamespace(chat=SimpleNamespace(id=-100123456), id=7)
    await uploader._copy_to_user_pm(message)

    uploader_module.TgClient.bot.copy_message.assert_awaited_once_with(
        chat_id=listener.user_id,
        from_chat_id=-100123456,
        message_id=7,
        disable_notification=True,
    )


@pytest.mark.asyncio
async def test_does_nothing_when_toggle_is_disabled(uploader_module):
    uploader, _ = _make_uploader(uploader_module)
    await uploader._user_settings()

    message = SimpleNamespace(chat=SimpleNamespace(id=-100123456), id=7)
    await uploader._copy_to_user_pm(message)

    uploader_module.TgClient.bot.copy_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_not_duplicate_when_destination_is_user_pm(uploader_module):
    uploader, listener = _make_uploader(uploader_module)
    uploader_module.Config.LEECH_DUMP_COPY_TO_USER = True
    await uploader._user_settings()

    message = SimpleNamespace(chat=SimpleNamespace(id=listener.user_id), id=7)
    await uploader._copy_to_user_pm(message)

    uploader_module.TgClient.bot.copy_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_does_nothing_without_dump_destination(uploader_module):
    uploader, listener = _make_uploader(uploader_module)
    listener.up_dest = None
    uploader_module.Config.LEECH_DUMP_COPY_TO_USER = True
    await uploader._user_settings()

    message = SimpleNamespace(chat=SimpleNamespace(id=-100123456), id=7)
    await uploader._copy_to_user_pm(message)

    uploader_module.TgClient.bot.copy_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_file_copies_after_successful_send(uploader_module):
    uploader, _ = _make_uploader(uploader_module)
    uploader_module.Config.LEECH_DUMP_COPY_TO_USER = True
    await uploader._user_settings()

    sent = SimpleNamespace(chat=SimpleNamespace(id=-100123456), id=99)
    uploader._sent_msg = SimpleNamespace(
        reply_document=AsyncMock(return_value=sent)
    )
    uploader._up_path = str(ROOT / "dummy.bin")

    await uploader._upload_file(
        "<code>dummy.bin</code>", "dummy.bin", uploader._up_path
    )

    uploader_module.TgClient.bot.copy_message.assert_awaited_once_with(
        chat_id=111222333,
        from_chat_id=-100123456,
        message_id=99,
        disable_notification=True,
    )
