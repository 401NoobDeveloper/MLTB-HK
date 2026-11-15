"""Exercise the aria2 batch loop with a fake aria2 JSON-RPC API."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


class FakeLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeAria2:
    def __init__(self, files):
        self.files = files
        self.downloads = {
            "gid1": {
                "gid": "gid1",
                "status": "active",
                "files": files,
                "bittorrent": {"info": {"name": "TorrentName"}},
            }
        }
        self.change_calls = []
        self.add_calls = []
        self.paused = []
        self.unpaused = []
        self.removed = []
        self.gid = 1

    async def tellStatus(self, gid):
        return self.downloads[gid]

    async def changeOption(self, gid, options):
        self.change_calls.append((gid, options))

    async def unpause(self, gid):
        self.unpaused.append(gid)
        self.downloads[gid]["status"] = "active"

    async def forcePause(self, gid):
        self.paused.append(gid)
        self.downloads[gid]["status"] = "paused"

    async def jsonrpc(self, method, params):
        self.add_calls.append((method, params[2]))
        self.gid += 1
        gid = f"gid{self.gid}"
        self.downloads[gid] = {
            "gid": gid,
            "status": "paused",
            "files": self.files,
            "bittorrent": {"info": {"name": "TorrentName"}},
        }
        return gid

    async def addUri(self, uris, options):
        self.add_calls.append(("addUri", options))
        self.gid += 1
        gid = f"gid{self.gid}"
        self.downloads[gid] = {
            "gid": gid,
            "status": "paused",
            "files": self.files,
            "bittorrent": {"info": {"name": "TorrentName"}},
        }
        return gid

    async def forceRemove(self, gid):
        self.removed.append(gid)

    async def removeDownloadResult(self, gid):
        self.removed.append(gid)


class DummyStatus:
    def __init__(self, listener, gid, queued=False):
        self.listener = listener
        self._gid = gid
        self.queued = queued

    def gid(self):
        return self._gid


class DummyUploader:
    def __init__(self, *args, **kwargs):
        pass

    async def upload(self):
        return None


def _load_aria2_batch_module(monkeypatch, tmp_path, files, save_path, fake):
    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    async def noop(*args, **kwargs):
        return None

    async def check_running_tasks(listener, state="dl"):
        return False, None

    async def start_from_queued():
        return None

    async def sync_to_async(func, *args, **kwargs):
        return func(*args, **kwargs)

    @asynccontextmanager
    async def aio_open(path, mode="r"):
        with open(path, mode) as file_obj:
            class Reader:
                async def read(self):
                    return file_obj.read()

            yield Reader()

    aiofiles = ModuleType("aiofiles")
    aiofiles.open = aio_open
    monkeypatch.setitem(sys.modules, "aiofiles", aiofiles)

    aiofiles_os = ModuleType("aiofiles.os")

    async def aio_makedirs(path, **kwargs):
        os.makedirs(path, exist_ok=kwargs.get("exist_ok", False))

    async def aio_remove(path):
        os.remove(path)

    async def aio_rename(source, destination):
        os.rename(source, destination)

    async def aio_rmdir(path):
        os.rmdir(path)

    async def aio_exists(path):
        return os.path.exists(path)

    aiofiles_os.makedirs = aio_makedirs
    aiofiles_os.remove = aio_remove
    aiofiles_os.rename = aio_rename
    aiofiles_os.rmdir = aio_rmdir
    aiofiles_os.path = SimpleNamespace(exists=aio_exists)
    monkeypatch.setitem(sys.modules, "aiofiles.os", aiofiles_os)

    psutil = ModuleType("psutil")
    psutil.disk_usage = lambda path: SimpleNamespace(free=10**12)
    monkeypatch.setitem(sys.modules, "psutil", psutil)

    tasks = []

    def create_task(coro):
        tasks.append(coro)
        return coro

    bot = stub(
        "bot",
        DOWNLOAD_DIR=str(tmp_path),
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        bot_loop=SimpleNamespace(create_task=create_task),
        intervals={"stopAll": False},
        non_queued_dl=set(),
        non_queued_up=set(),
        queue_dict_lock=FakeLock(),
        task_dict={},
        task_dict_lock=FakeLock(),
    )
    bot.tasks = tasks
    stub("bot.core")
    stub(
        "bot.core.config_manager",
        Config=SimpleNamespace(
            TORRENT_TIMEOUT=0,
            BASE_URL="http://localhost",
            WEB_PINCODE=False,
        ),
    )
    stub(
        "bot.core.torrent_manager",
        TorrentManager=SimpleNamespace(aria2=fake, aria2_remove=_aria2_remove(fake)),
        aria2_name=lambda download: (
            download.get("bittorrent", {}).get("info", {}).get("name")
            or "TorrentName"
        ),
        is_metadata=lambda download: any(
            file_info.get("path", "").startswith("[METADATA]")
            for file_info in download.get("files", [])
        ),
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils", __path__=[])
    stub("bot.helper.listeners", __path__=[])
    stub("bot.helper.mirror_leech_utils", __path__=[])
    stub("bot.helper.mirror_leech_utils.download_utils", __path__=[])
    stub("bot.helper.mirror_leech_utils.gdrive_utils", __path__=[])
    stub("bot.helper.mirror_leech_utils.rclone_utils", __path__=[])
    stub("bot.helper.mirror_leech_utils.status_utils", __path__=[])
    stub("bot.helper.mirror_leech_utils.upload_utils", __path__=[])
    stub("bot.helper.telegram_helper", __path__=[])

    file_types_path = (
        Path(__file__).resolve().parent.parent
        / "bot"
        / "helper"
        / "ext_utils"
        / "file_types.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.file_types", file_types_path
    )
    file_types = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.file_types", file_types)
    spec.loader.exec_module(file_types)

    stub(
        "bot.helper.ext_utils.bot_utils",
        sync_to_async=sync_to_async,
        bt_selection_buttons=lambda gid: None,
    )

    class DummyFFMpeg:
        def __init__(self, listener):
            self.listener = listener

        async def split(self, f_path, file_, parts, split_size):
            return True

    async def unknown_document_type(path):
        return False, False, False

    stub(
        "bot.helper.ext_utils.media_utils",
        FFMpeg=DummyFFMpeg,
        get_document_type=unknown_document_type,
    )
    stub(
        "bot.helper.ext_utils.files_utils",
        clean_download=noop,
        split_file=noop,
    )
    stub("bot.helper.ext_utils.links_utils", is_gdrive_id=lambda value: False)
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size} B",
    )
    stub(
        "bot.helper.ext_utils.task_manager",
        start_from_queued=start_from_queued,
        check_running_tasks=check_running_tasks,
    )
    stub(
        "bot.helper.telegram_helper.message_utils",
        send_message=noop,
        update_status_message=noop,
        send_status_message=noop,
    )

    for name, cls in [
        ("gdrive_status", "GoogleDriveStatus"),
        ("rclone_status", "RcloneStatus"),
        ("telegram_status", "TelegramStatus"),
        ("aria2_status", "Aria2Status"),
        ("queue_status", "QueueStatus"),
    ]:
        stub(
            f"bot.helper.mirror_leech_utils.status_utils.{name}",
            **{cls: DummyStatus},
        )
    for name, cls in [
        ("telegram_uploader", "TelegramUploader"),
    ]:
        stub(
            f"bot.helper.mirror_leech_utils.upload_utils.{name}",
            **{cls: DummyUploader},
        )
    stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.upload",
        GoogleDriveUpload=DummyUploader,
    )
    stub(
        "bot.helper.mirror_leech_utils.rclone_utils.transfer",
        RcloneTransferHelper=DummyUploader,
    )

    base = Path(__file__).resolve().parent.parent / "bot" / "helper" / "listeners"
    for module_name in ["batch", "aria2_batch"]:
        spec = importlib.util.spec_from_file_location(
            f"bot.helper.listeners.{module_name}", base / f"{module_name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "bot.helper.listeners"
        monkeypatch.setitem(sys.modules, f"bot.helper.listeners.{module_name}", module)
        spec.loader.exec_module(module)
        if module_name == "aria2_batch":
            return module


def _aria2_remove(fake):
    async def remove(download):
        gid = download.get("gid", "")
        if download.get("status", "") in ("active", "paused", "waiting"):
            await fake.forceRemove(gid)
        else:
            await fake.removeDownloadResult(gid)

    return remove


def _load_aria2_download_module(monkeypatch):
    download_path = (
        Path(__file__).resolve().parent.parent
        / "bot"
        / "helper"
        / "mirror_leech_utils"
        / "download_utils"
        / "aria2_download.py"
    )
    spec = importlib.util.spec_from_file_location(
        "bot.helper.mirror_leech_utils.download_utils.aria2_download",
        download_path,
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "bot.helper.mirror_leech_utils.download_utils"
    monkeypatch.setitem(
        sys.modules,
        "bot.helper.mirror_leech_utils.download_utils.aria2_download",
        module,
    )
    spec.loader.exec_module(module)
    return module


def _listener(tmp_path):
    task_dir = tmp_path / "123"
    task_dir.mkdir(exist_ok=True)
    errors = []
    completed = []

    async def on_upload_complete(*args, **kwargs):
        completed.append((args, kwargs))

    async def on_download_error(error, button=None):
        errors.append(error)

    async def on_download_start():
        return None

    listener = SimpleNamespace(
        mid=123,
        dir=f"{task_dir}/",
        name="TorrentName",
        size=0,
        is_file=False,
        up_dest="",
        is_leech=True,
        is_cancelled=False,
        seed=False,
        equal_splits=False,
        as_doc=False,
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
        message=SimpleNamespace(chat=SimpleNamespace(id=555)),
        on_upload_complete=on_upload_complete,
        on_download_error=on_download_error,
        on_download_start=on_download_start,
    )
    return listener, task_dir, errors, completed


def _make_files(tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    (root / "a.mkv").write_bytes(b"a")
    (root / "b.jpg").write_bytes(b"b")
    files = [
        {
            "index": 1,
            "path": str(root / "a.mkv"),
            "length": 1,
            "completedLength": 1,
        },
        {
            "index": 2,
            "path": str(root / "b.jpg"),
            "length": 1,
            "completedLength": 1,
        },
    ]
    return task_dir, root, files


@pytest.mark.asyncio
async def test_aria2_batch_selects_each_file_and_uploads(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )
    uploads = []

    async def fake_wait(batch_files):
        return True

    async def fake_upload(job):
        uploads.append(job.name)
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    batch._wait_batch = fake_wait
    batch._upload_one = fake_upload
    await batch.run()

    assert uploads == ["a.mkv", "b.jpg"]
    assert fake.change_calls == [
        ("gid1", {"select-file": "1"}),
        ("gid2", {"select-file": "2"}),
    ]
    assert fake.add_calls[0][0] == "addTorrent"
    assert "select-file" not in fake.add_calls[0][1]
    assert fake.unpaused == ["gid1", "gid2"]
    assert fake.removed == ["gid1", "gid2"]
    assert not (root / "a.mkv").exists()
    assert not (root / "b.jpg").exists()
    assert errors == []
    assert completed


@pytest.mark.asyncio
async def test_aria2_wait_batch_checks_completed_length(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    files[0]["completedLength"] = 0
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )
    polls = []

    async def fake_sleep(seconds):
        polls.append(seconds)
        files[0]["completedLength"] = files[0]["length"]

    monkeypatch.setattr(module, "sleep", fake_sleep)
    assert await batch._wait_batch([batch.pending[0]]) is True
    assert polls


@pytest.mark.asyncio
async def test_add_aria2_batch_adds_paused_and_runs(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    torrent = tmp_path / "input.torrent"
    torrent.write_bytes(b"torrent-bytes")
    listener.link = str(torrent)
    uploads = []

    async def fake_upload(self, job):
        uploads.append(job.name)
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    monkeypatch.setattr(module.Aria2Batch, "_upload_one", fake_upload)
    tasks = []
    sys.modules["bot"].bot_loop.create_task = (
        lambda coro: tasks.append(coro) or coro
    )
    await module.add_aria2_batch(listener, str(task_dir), [], 0, 0)

    assert not errors, errors
    assert fake.add_calls[0][0] == "addTorrent"
    assert fake.add_calls[0][1]["pause"] == "true"
    assert not torrent.exists()
    assert tasks
    await tasks[0]
    assert uploads == ["a.mkv", "b.jpg"]
    assert errors == []
    assert completed


@pytest.mark.asyncio
async def test_magnet_without_s_auto_batch_starts(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    listener.link = "magnet:?xt=urn:btih:" + ("a" * 40)
    uploads = []

    async def fake_upload(self, job):
        uploads.append(job.name)
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    monkeypatch.setattr(module.Aria2Batch, "_upload_one", fake_upload)
    tasks = []
    sys.modules["bot"].bot_loop.create_task = (
        lambda coro: tasks.append(coro) or coro
    )
    await module.add_aria2_batch(listener, str(task_dir), [], 0, 0)

    assert not errors, errors
    assert fake.add_calls[0][0] == "addUri"
    assert "pause" not in fake.add_calls[0][1]
    assert fake.add_calls[0][1]["pause-metadata"] == "true"
    assert tasks
    await tasks[0]
    assert "gid2" in fake.unpaused
    assert uploads == ["a.mkv", "b.jpg"]
    assert completed


@pytest.mark.asyncio
async def test_select_non_batch_torrent_is_added_paused(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    fake = FakeAria2(files)
    _load_aria2_batch_module(monkeypatch, tmp_path, files, str(task_dir), fake)
    download_module = _load_aria2_download_module(monkeypatch)

    listener, _, errors, _ = _listener(tmp_path)
    listener.select = True
    listener.batch_mode = False
    listener.files_per_batch = 0
    torrent = tmp_path / "input.torrent"
    torrent.write_bytes(b"torrent-bytes")
    listener.link = str(torrent)

    await download_module.add_aria2_download(listener, str(task_dir), [], 0, 0)

    assert fake.add_calls[0][0] == "addTorrent"
    assert fake.add_calls[0][1]["pause"] == "true"
    assert fake.paused == []
    assert errors == []


@pytest.mark.asyncio
async def test_magnet_with_s_uses_single_selection(monkeypatch, tmp_path):
    task_dir, root, files = _make_files(tmp_path)
    fake = FakeAria2(files)
    _load_aria2_batch_module(monkeypatch, tmp_path, files, str(task_dir), fake)
    download_module = _load_aria2_download_module(monkeypatch)
    listener, _, errors, _ = _listener(tmp_path)
    listener.select = True
    listener.batch_mode = False
    listener.files_per_batch = 0
    listener.link = "magnet:?xt=urn:btih:" + ("b" * 40)
    tasks = []
    sys.modules["bot"].bot_loop.create_task = (
        lambda coro: tasks.append(coro) or coro
    )

    await download_module.add_aria2_download(listener, str(task_dir), [], 0, 0)

    assert fake.add_calls[0][0] == "addUri"
    assert fake.add_calls[0][1]["pause-metadata"] == "true"
    assert "pause" not in fake.add_calls[0][1]
    assert fake.paused == []
    assert tasks == []
    assert errors == []
