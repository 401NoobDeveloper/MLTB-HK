"""Batch uploads must go through the upload queue like normal uploads."""

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


def _load_batch(monkeypatch, tmp_path):
    calls = []
    queue = SimpleNamespace(
        queued=False, waited=[], cancel_after_wait=False
    )

    def _stub(name, **attrs):
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

    async def check_running_tasks(listener, state="dl"):
        calls.append(state)
        if state == "up" and queue.queued:
            class _Event:
                async def wait(self):
                    queue.waited.append(True)
                    if queue.cancel_after_wait:
                        listener.is_cancelled = True

            return True, _Event()
        return False, None

    async def start_from_queued():
        calls.append("start_from_queued")

    _stub(
        "psutil",
        disk_usage=lambda path: SimpleNamespace(free=10**12),
    )
    _stub(
        "bot",
        DOWNLOAD_DIR=str(tmp_path),
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        intervals={"stopAll": False},
        non_queued_dl=set(),
        non_queued_up=set(),
        queue_dict_lock=FakeLock(),
        task_dict={},
        task_dict_lock=FakeLock(),
    )
    _stub("bot.helper")
    _stub("bot.helper.ext_utils")
    _stub("bot.helper.listeners")
    _stub("bot.helper.mirror_leech_utils")
    _stub("bot.helper.mirror_leech_utils.gdrive_utils")
    _stub("bot.helper.mirror_leech_utils.rclone_utils")
    _stub("bot.helper.mirror_leech_utils.status_utils")
    _stub("bot.helper.mirror_leech_utils.upload_utils")
    _stub("bot.helper.telegram_helper")
    _stub("bot.helper.ext_utils.bot_utils", sync_to_async=sync_to_async)
    _stub(
        "bot.helper.ext_utils.files_utils",
        clean_download=noop,
        split_file=noop,
    )
    _stub("bot.helper.ext_utils.links_utils", is_gdrive_id=lambda value: False)
    _stub(
        "bot.helper.ext_utils.media_utils",
        FFMpeg=object,
        get_document_type=noop,
    )
    _stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size} B",
    )
    _stub(
        "bot.helper.ext_utils.task_manager",
        check_running_tasks=check_running_tasks,
        start_from_queued=start_from_queued,
    )
    _stub(
        "bot.helper.telegram_helper.message_utils",
        update_status_message=noop,
    )
    for name, cls in [
        ("gdrive_status", "GoogleDriveStatus"),
        ("rclone_status", "RcloneStatus"),
        ("telegram_status", "TelegramStatus"),
        ("queue_status", "QueueStatus"),
    ]:
        _stub(f"bot.helper.mirror_leech_utils.status_utils.{name}", **{cls: object})
    _stub(
        "bot.helper.mirror_leech_utils.upload_utils.telegram_uploader",
        TelegramUploader=object,
    )
    _stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.upload",
        GoogleDriveUpload=object,
    )
    _stub(
        "bot.helper.mirror_leech_utils.rclone_utils.transfer",
        RcloneTransferHelper=object,
    )

    file_types_spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.file_types",
        ROOT / "bot" / "helper" / "ext_utils" / "file_types.py",
    )
    file_types = importlib.util.module_from_spec(file_types_spec)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.file_types", file_types)
    file_types_spec.loader.exec_module(file_types)

    spec = importlib.util.spec_from_file_location(
        "bot.helper.listeners.batch", ROOT / "bot" / "helper" / "listeners" / "batch.py"
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "bot.helper.listeners"
    monkeypatch.setitem(sys.modules, "bot.helper.listeners.batch", module)
    spec.loader.exec_module(module)
    module.calls = calls
    module.queue = queue
    return module


def _listener(tmp_path):
    task_dir = tmp_path / "123"
    task_dir.mkdir(exist_ok=True)

    async def noop(*args, **kwargs):
        return None

    return SimpleNamespace(
        mid=123,
        dir=f"{task_dir}/",
        name="TorrentName",
        size=0,
        is_file=False,
        up_dest="",
        is_leech=True,
        is_cancelled=False,
        files_per_batch=1,
        batch_max_size=0,
        file_types=[],
        included_extensions=[],
        excluded_extensions=[],
        split_size=0,
        batch_current=0,
        batch_total=0,
        multi=1,
        is_rss=False,
        select=False,
        batch_mode=True,
        force_run=False,
        force_download=False,
        force_upload=False,
        message=SimpleNamespace(chat=SimpleNamespace(id=555)),
        on_upload_complete=noop,
        on_download_error=noop,
    ), task_dir


async def test_batch_uploads_use_upload_queue(monkeypatch, tmp_path):
    module = _load_batch(monkeypatch, tmp_path)
    listener, task_dir = _listener(tmp_path)
    files = [
        {"index": 1, "name": "TorrentName/a.mkv", "size": 1},
        {"index": 2, "name": "TorrentName/b.mkv", "size": 1},
    ]
    runner = module.BatchRunner(
        listener,
        {"hash": "gid", "content_path": str(task_dir)},
        files,
        task_root=str(task_dir),
    )

    async def apply_batch(batch):
        return None

    async def wait_batch(batch):
        return True

    uploaded = []

    async def upload_batch(batch):
        uploaded.extend(file_info["name"] for file_info in batch)

    async def remove_torrent():
        return None

    async def finish():
        return None

    runner._apply_batch = apply_batch
    runner._wait_batch = wait_batch
    runner._upload_batch = upload_batch
    runner._remove_torrent = remove_torrent
    runner._finish = finish

    await runner.run()

    assert uploaded == ["TorrentName/a.mkv", "TorrentName/b.mkv"]
    states = [call for call in module.calls if call in ("dl", "up")]
    assert states == ["up", "dl", "up"]


async def test_acquire_upload_slot_waits_for_queue_event(monkeypatch, tmp_path):
    module = _load_batch(monkeypatch, tmp_path)
    listener, task_dir = _listener(tmp_path)
    module.queue.queued = True
    runner = module.BatchRunner(
        listener,
        {"hash": "gid", "content_path": str(task_dir)},
        [],
        task_root=str(task_dir),
    )

    assert await runner._acquire_upload_slot() is True
    assert module.queue.waited == [True]


async def test_acquire_upload_slot_stops_when_cancelled(monkeypatch, tmp_path):
    module = _load_batch(monkeypatch, tmp_path)
    listener, task_dir = _listener(tmp_path)
    module.queue.queued = True
    module.queue.cancel_after_wait = True
    runner = module.BatchRunner(
        listener,
        {"hash": "gid", "content_path": str(task_dir)},
        [],
        task_root=str(task_dir),
    )

    assert await runner._acquire_upload_slot() is False
