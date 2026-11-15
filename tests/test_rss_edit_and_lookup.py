"""RSS edit must survive a trailing newline and sudo title lookups must work."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_bot_utils(monkeypatch):
    async def noop(*args, **kwargs):
        return None

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    stub("bot.helper.telegram_helper")
    button_build_spec = importlib.util.spec_from_file_location(
        "bot.helper.telegram_helper.button_build",
        ROOT / "bot" / "helper" / "telegram_helper" / "button_build.py",
    )
    button_build = importlib.util.module_from_spec(button_build_spec)
    monkeypatch.setitem(
        sys.modules, "bot.helper.telegram_helper.button_build", button_build
    )
    button_build_spec.loader.exec_module(button_build)
    stub(
        "bot.helper.ext_utils.telegraph_helper",
        telegraph=SimpleNamespace(create_page=noop, edit_telegraph=noop),
    )
    stub(
        "bot.helper.ext_utils.help_messages",
        YT_HELP_DICT={"main": "", "a": ""},
        GDL_HELP_DICT={"main": "", "a": ""},
        MIRROR_HELP_DICT={"main": "", "a": ""},
        CLONE_HELP_DICT={"main": "", "a": ""},
    )
    spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.bot_utils",
        ROOT / "bot" / "helper" / "ext_utils" / "bot_utils.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.bot_utils", module)
    spec.loader.exec_module(module)
    return module


def _load_rss(monkeypatch):
    sent = []
    db_updates = []
    rss_dict = {
        7: {
            "title1": {
                "link": "https://example.com/feed",
                "last_feed": "",
                "last_title": "",
                "inf": [],
                "exf": [],
                "paused": False,
                "command": "ql",
                "sensitive": False,
                "tag": "@user",
            }
        }
    }

    async def send_message(message, text, buttons=None):
        sent.append(text)
        return SimpleNamespace(id=1)

    async def edit_message(*args, **kwargs):
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

    class FakeScheduler:
        running = False
        state = 0

        def add_job(self, *args, **kwargs):
            return None

        def start(self):
            self.running = True

        def pause(self):
            self.state = 1

        def resume(self):
            self.running = True

    stub(
        "bot",
        scheduler=FakeScheduler(),
        rss_dict=rss_dict,
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None,
            error=lambda *a, **k: None,
            warning=lambda *a, **k: None,
        ),
        user_data={},
        bot_loop=SimpleNamespace(create_task=lambda coro: coro),
        task_dict={},
    )
    stub("bot.core")
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub("bot.modules")
    stub(
        "bot.core.config_manager",
        Config=SimpleNamespace(
            CMD_SUFFIX="", RSS_CHAT="", RSS_DELAY=600, RSS_SIZE_LIMIT=0
        ),
    )
    stub(
        "bot.core.telegram_manager",
        TgClient=SimpleNamespace(bot=SimpleNamespace(get_users=None), user=None),
    )
    _load_bot_utils(monkeypatch)
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size}B",
    )
    stub(
        "bot.helper.ext_utils.db_handler",
        database=SimpleNamespace(
            rss_update=_recorder(db_updates), rss_delete=noop, trunc_table=noop
        ),
    )
    stub(
        "bot.helper.ext_utils.exceptions",
        RssShutdownException=type("RssShutdownException", (Exception,), {}),
    )
    stub("bot.helper.ext_utils.help_messages", RSS_HELP_MESSAGE="help")
    stub(
        "bot.helper.telegram_helper.filters",
        CustomFilters=SimpleNamespace(sudo=noop, authorized=noop),
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=send_message,
        edit_message=edit_message,
        send_rss=noop,
        send_file=noop,
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
        "bot.modules.rss", ROOT / "bot" / "modules" / "rss.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.rss", module)
    spec.loader.exec_module(module)

    async def update_rss_menu(query):
        return None

    module.update_rss_menu = update_rss_menu
    module.sent = sent
    module.db_updates = db_updates
    module.rss_dict = rss_dict
    return module


def _recorder(sink):
    async def record(*args, **kwargs):
        sink.append(args[0] if args else kwargs)

    return record


async def test_rss_edit_ignores_trailing_blank_line(monkeypatch):
    module = _load_rss(monkeypatch)
    message = SimpleNamespace(
        text="title1 -c none\n",
        from_user=SimpleNamespace(id=7, username="user", mention="@user"),
    )

    await module.rss_edit.__wrapped__(None, message, SimpleNamespace())

    assert module.rss_dict[7]["title1"]["command"] is None
    assert module.db_updates == [7]


async def test_get_user_id_finds_title_across_users(monkeypatch):
    module = _load_rss(monkeypatch)

    found, user_id = await module.get_user_id("title1")

    assert (found, user_id) == (True, 7)
    assert await module.get_user_id("missing") == (False, False)


async def test_rss_monitor_posts_to_username_chat(monkeypatch):
    module = _load_rss(monkeypatch)
    module.Config.RSS_CHAT = "@my_channel"
    module.rss_dict[7]["title1"]["command"] = None

    async def no_sleep(*args, **kwargs):
        return None

    module.sleep = no_sleep

    class FakeResponse:
        text = "<rss/>"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url):
            return FakeResponse()

    module.AsyncClient = FakeClient
    entry = {
        "title": "item",
        "links": [{"href": "u0"}, {"href": "u1"}],
        "size": "1024",
    }
    module.feed_parse = lambda html: SimpleNamespace(entries=[entry])

    calls = []

    async def send_rss(text, chat_id, thread_id):
        calls.append((chat_id, thread_id))
        return SimpleNamespace(id=1)

    module.send_rss = send_rss

    await module.rss_monitor()

    assert calls == [("@my_channel", None)]


async def test_rss_list_pages_all_users_by_action(monkeypatch):
    module = _load_rss(monkeypatch)
    for uid in (7, 8):
        module.rss_dict[uid] = {
            f"feed{uid}_{i}": {
                "link": f"https://example.com/{uid}/{i}",
                "last_feed": "",
                "last_title": "",
                "inf": [],
                "exf": [],
                "paused": False,
                "command": None,
                "sensitive": False,
                "tag": f"@{uid}",
            }
            for i in range(1, 7)
        }

    edits = []

    async def edit_message(message, text=None, buttons=None, **kwargs):
        edits.append((text, buttons))

    module.edit_message = edit_message

    async def answer(*args, **kwargs):
        return None

    query = SimpleNamespace(
        from_user=SimpleNamespace(id=1),
        message=SimpleNamespace(text=SimpleNamespace(html="")),
        answer=answer,
    )

    await module.rss_list(query, 5, all_users=True)

    text, markup = edits[-1]
    assert "feed7_6" in text
    assert "feed8_1" in text
    assert "feed7_1" not in text
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert any(data.startswith("rss listall ") for data in callbacks)
    assert not any(data.startswith("rss list ") for data in callbacks)
