import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _load_task_manager(monkeypatch):
    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class Config:
        QUEUE_ALL = 0
        QUEUE_DOWNLOAD = 0
        QUEUE_UPLOAD = 0

    class Logger:
        def info(self, message):
            pass

        def error(self, message):
            pass

    class Lock:
        pass

    bot = stub(
        "bot",
        queued_dl={},
        queued_up={},
        non_queued_up=set(),
        non_queued_dl=set(),
        queue_dict_lock=Lock(),
        LOGGER=Logger(),
    )
    stub("bot.core")
    stub("bot.core.config_manager", Config=Config)
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.mirror_leech_utils")
    stub("bot.helper.mirror_leech_utils.gdrive_utils")
    stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.search",
        GoogleDriveSearch=object,
    )
    stub(
        "bot.helper.ext_utils.bot_utils",
        sync_to_async=lambda func, *args, **kwargs: func(*args, **kwargs),
        get_telegraph_list=lambda content: None,
    )
    stub("bot.helper.ext_utils.files_utils", get_base_name=lambda name: name)
    stub("bot.helper.ext_utils.links_utils", is_gdrive_id=lambda value: False)

    path = (
        Path(__file__).resolve().parent.parent
        / "bot/helper/ext_utils/task_manager.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.task_manager", path
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "bot.helper.ext_utils"
    monkeypatch.setitem(
        sys.modules, "bot.helper.ext_utils.task_manager", module
    )
    spec.loader.exec_module(module)
    return module, bot


def _listener(mid):
    return SimpleNamespace(
        mid=mid,
        force_run=False,
        force_download=False,
        force_upload=False,
    )


@pytest.fixture
def queue(monkeypatch):
    module, bot = _load_task_manager(monkeypatch)
    module.queue_dict_lock = asyncio.Lock()
    module.queued_dl.clear()
    module.queued_up.clear()
    module.non_queued_dl.clear()
    module.non_queued_up.clear()
    module.Config.QUEUE_ALL = 0
    module.Config.QUEUE_DOWNLOAD = 0
    module.Config.QUEUE_UPLOAD = 0
    return module


@pytest.mark.asyncio
async def test_all_limit_wins_when_state_limit_is_higher(queue):
    queue.Config.QUEUE_ALL = 1
    queue.Config.QUEUE_DOWNLOAD = 2

    first = _listener(1)
    second = _listener(2)

    queued, event = await queue.check_running_tasks(first, "dl")
    assert queued is False
    assert event is None

    queued, event = await queue.check_running_tasks(second, "dl")
    assert queued is True
    assert event is not None
    assert second.mid in queue.queued_dl
    assert second.mid not in queue.non_queued_dl


@pytest.mark.asyncio
async def test_download_queue_releases_one_task(queue):
    queue.Config.QUEUE_DOWNLOAD = 1

    first = _listener(1)
    second = _listener(2)

    first_queued, _ = await queue.check_running_tasks(first, "dl")
    assert first_queued is False

    second_queued, second_event = await queue.check_running_tasks(second, "dl")
    assert second_queued is True
    assert second.mid in queue.queued_dl

    queue.non_queued_dl.discard(first.mid)
    await queue.start_from_queued()

    assert second_event.is_set()
    assert second.mid in queue.non_queued_dl
    assert second.mid not in queue.queued_dl


@pytest.mark.asyncio
async def test_upload_queue_releases_one_task(queue):
    queue.Config.QUEUE_UPLOAD = 1

    first = _listener(1)
    second = _listener(2)

    first_queued, _ = await queue.check_running_tasks(first, "up")
    assert first_queued is False

    second_queued, second_event = await queue.check_running_tasks(second, "up")
    assert second_queued is True
    assert second.mid in queue.queued_up

    queue.non_queued_up.discard(first.mid)
    await queue.start_from_queued()

    assert second_event.is_set()
    assert second.mid in queue.non_queued_up
    assert second.mid not in queue.queued_up


@pytest.mark.asyncio
async def test_force_flags_bypass_limits(queue):
    queue.Config.QUEUE_ALL = 1
    queue.Config.QUEUE_DOWNLOAD = 1

    first = _listener(1)
    forced = _listener(2)
    forced.force_download = True

    await queue.check_running_tasks(first, "dl")
    queued, event = await queue.check_running_tasks(forced, "dl")

    assert queued is False
    assert event is None
    assert forced.mid in queue.non_queued_dl
