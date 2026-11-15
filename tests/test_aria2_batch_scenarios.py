"""Scenario tests for the aria2 batch loop (multi-file batches, filters, errors)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_aria2_batch_flow import (  # noqa: E402
    FakeAria2,
    _listener,
    _load_aria2_batch_module,
)


def _files(root):
    (root / "sub").mkdir(exist_ok=True)
    (root / "a.mkv").write_bytes(b"a")
    (root / "b.jpg").write_bytes(b"b")
    (root / "sub" / "c.mkv").write_bytes(b"c")
    return [
        {"index": 1, "path": str(root / "a.mkv"), "length": 1, "completedLength": 1},
        {"index": 2, "path": str(root / "b.jpg"), "length": 1, "completedLength": 1},
        {
            "index": 3,
            "path": str(root / "sub" / "c.mkv"),
            "length": 1,
            "completedLength": 1,
        },
    ]


@pytest.mark.asyncio
async def test_three_files_two_per_batch(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    listener.files_per_batch = 2
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )
    uploads = []

    async def fake_upload(job):
        uploads.append(job.name)
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    batch._upload_one = fake_upload
    await batch.run()

    assert uploads == ["a.mkv", "b.jpg", "c.mkv"]
    assert fake.change_calls == [
        ("gid1", {"select-file": "1,2"}),
        ("gid2", {"select-file": "3"}),
    ]
    assert errors == []
    assert completed
    args, _ = completed[0]
    assert args[0] is None
    assert len(args[1]) == 3
    assert args[2] == 3
    if os.sep == "/":
        assert not (root / "sub").exists()
        assert not root.exists()


@pytest.mark.asyncio
async def test_file_type_filter_limits_batches(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    listener.files_per_batch = 5
    listener.file_types = ["video"]
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )
    uploads = []

    async def fake_upload(job):
        uploads.append(job.name)
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    batch._upload_one = fake_upload
    await batch.run()

    assert uploads == ["a.mkv", "c.mkv"]
    assert batch.listener.batch_total == 2
    assert fake.change_calls == [("gid1", {"select-file": "1,3"})]
    assert errors == []


@pytest.mark.asyncio
async def test_missing_file_aborts_with_message(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)
    (root / "a.mkv").unlink()
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    listener.files_per_batch = 1
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )

    async def fake_upload(job):
        raise AssertionError("upload must not run for a missing file")

    batch._upload_one = fake_upload
    sys.modules["bot"].task_dict[listener.mid] = object()
    await batch.run()

    assert not completed
    assert errors and "missing" in errors[0]


@pytest.mark.asyncio
async def test_upload_status_keeps_full_gid(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, _, _ = _listener(tmp_path)
    batch = module.Aria2Batch(
        listener,
        "abcdef1234567890",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )

    recorded = {}

    class RecordingStatus:
        def __init__(self, status_listener, obj, gid, status):
            recorded["gid"] = gid
            recorded["status"] = status

    class NoopUploader:
        def __init__(self, upload_listener, path):
            pass

        async def upload(self):
            return None

    batch_module = sys.modules["bot.helper.listeners.batch"]
    batch_module.TelegramStatus = RecordingStatus
    batch_module.TelegramUploader = NoopUploader
    job = batch_module.BatchFileJob(
        listener,
        {"index": 1, "name": "TorrentName/a.mkv", "size": 1},
        str(root / "a.mkv"),
        "TorrentName",
    )

    await batch._upload_one(job)

    assert recorded["gid"] == "abcdef1234567890"
    assert recorded["status"] == "up"


@pytest.mark.asyncio
async def test_batch_does_not_enable_seeding(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, _ = _listener(tmp_path)
    listener.link = "magnet:?xt=urn:btih:" + ("a" * 40)
    listener.seed = False

    tasks = []
    sys.modules["bot"].bot_loop.create_task = (
        lambda coro: tasks.append(coro) or coro
    )

    async def fake_upload(self, job):
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    monkeypatch.setattr(module.Aria2Batch, "_upload_one", fake_upload)

    await module.add_aria2_batch(listener, str(task_dir), [], "2", "10")
    await tasks[0]

    options = fake.add_calls[0][1]
    assert not errors, errors
    assert "seed-ratio" not in options
    assert "seed-time" not in options


class _RenamingAria2(FakeAria2):
    """Re-added torrents report their files under a different root folder."""

    def __init__(self, files, renamed_files):
        super().__init__(files)
        self.renamed_files = renamed_files

    async def jsonrpc(self, method, params):
        gid = await super().jsonrpc(method, params)
        self.downloads[gid] = {
            "gid": gid,
            "status": "paused",
            "files": self.renamed_files,
            "bittorrent": {"info": {"name": "Renamed"}},
        }
        return gid


@pytest.mark.asyncio
async def test_readded_batch_remaps_changed_file_paths(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    files = _files(root)

    renamed_root = task_dir / "Renamed"
    (renamed_root / "sub").mkdir(parents=True)
    (renamed_root / "a.mkv").write_bytes(b"a")
    (renamed_root / "b.jpg").write_bytes(b"b")
    (renamed_root / "sub" / "c.mkv").write_bytes(b"c")
    renamed_files = [
        {
            "index": 1,
            "path": str(renamed_root / "a.mkv"),
            "length": 1,
            "completedLength": 1,
        },
        {
            "index": 2,
            "path": str(renamed_root / "b.jpg"),
            "length": 1,
            "completedLength": 1,
        },
        {
            "index": 3,
            "path": str(renamed_root / "sub" / "c.mkv"),
            "length": 1,
            "completedLength": 1,
        },
    ]
    fake = _RenamingAria2(files, renamed_files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, completed = _listener(tmp_path)
    listener.files_per_batch = 2
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )
    uploads = []

    async def fake_upload(job):
        uploads.append((job.name, job.path))
        job.result = ((None, {f"link-{job.name}": job.name}, 1, 0), {})

    batch._upload_one = fake_upload
    await batch.run()

    assert not errors, errors
    assert [name for name, _ in uploads] == ["a.mkv", "b.jpg", "c.mkv"]
    assert uploads[-1][1] == str(renamed_root / "sub" / "c.mkv")
    assert completed


@pytest.mark.asyncio
async def test_leech_batch_splits_before_upload(monkeypatch, tmp_path):
    task_dir = tmp_path / "123"
    root = task_dir / "TorrentName"
    root.mkdir(parents=True)
    big = root / "a.mkv"
    big.write_bytes(b"0123456789")
    files = [
        {
            "index": 1,
            "path": str(big),
            "length": 10,
            "completedLength": 10,
        }
    ]
    fake = FakeAria2(files)
    module = _load_aria2_batch_module(
        monkeypatch, tmp_path, files, str(task_dir), fake
    )
    listener, _, errors, _ = _listener(tmp_path)
    listener.files_per_batch = 1
    listener.split_size = 4
    batch = module.Aria2Batch(
        listener,
        "gid1",
        files,
        b"torrent-bytes",
        str(task_dir),
        {"dir": str(task_dir), "pause": "true"},
    )

    batch_module = sys.modules["bot.helper.listeners.batch"]
    recorded = {}

    class Status:
        def __init__(self, *args, **kwargs):
            pass

    class Uploader:
        def __init__(self, job, path):
            recorded["job"] = job
            recorded["staging"] = path

        async def upload(self):
            recorded["files"] = sorted(os.listdir(recorded["staging"]))
            await recorded["job"].on_upload_complete(
                None, {"https://example/split": "a.mkv"}, 1, 0
            )

    async def fake_split_file(f_path, split_size, split_listener):
        for index in range(1, 4):
            with open(f"{f_path}.{index:03}", "wb") as part:
                part.write(b"x")
        return True

    batch_module.TelegramStatus = Status
    batch_module.TelegramUploader = Uploader
    batch_module.split_file = fake_split_file
    job = batch_module.BatchFileJob(
        listener,
        {"index": 1, "name": "TorrentName/a.mkv", "size": 10},
        str(big),
        "TorrentName",
    )

    await batch._upload_one(job)

    assert recorded["files"] == ["a.mkv.001", "a.mkv.002", "a.mkv.003"]
    assert job.result is not None
    assert big.exists()
