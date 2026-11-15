"""Tests for direct-download path normalization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.helper.listeners import direct_listener


class _FakeAria2:
    def __init__(self):
        self.calls = []

    async def addUri(self, uris, options, position=0):
        self.calls.append((uris, dict(options)))
        return "gid"

    async def tellStatus(self, gid):
        return {
            "status": "complete",
            "totalLength": "10",
            "completedLength": "10",
        }


class _FakeTorrentManager:
    def __init__(self, aria2):
        self.aria2 = aria2

    async def aria2_remove(self, download):
        return None


@pytest.mark.asyncio
async def test_direct_listener_normalizes_full_file_paths(monkeypatch):
    aria2 = _FakeAria2()
    monkeypatch.setattr(
        direct_listener, "TorrentManager", _FakeTorrentManager(aria2)
    )
    listener = SimpleNamespace(
        is_cancelled=False,
        name="job",
        on_download_complete=AsyncMock(),
        on_download_error=AsyncMock(),
    )
    direct = direct_listener.DirectListener("/downloads/job", listener, {})

    await direct.download(
        [
            {"path": "a.mkv", "filename": "a.mkv", "url": "https://x/a"},
            {
                "path": "Folder/b.mkv",
                "filename": "b.mkv",
                "url": "https://x/b",
            },
            {"path": "Folder", "filename": "c.mkv", "url": "https://x/c"},
            {"path": "", "filename": "d.mkv", "url": "https://x/d"},
        ]
    )

    dirs = [options["dir"] for _, options in aria2.calls]
    outs = [options["out"] for _, options in aria2.calls]
    assert dirs == [
        "/downloads/job",
        "/downloads/job/Folder",
        "/downloads/job/Folder",
        "/downloads/job",
    ]
    assert outs == ["a.mkv", "b.mkv", "c.mkv", "d.mkv"]
    listener.on_download_error.assert_not_awaited()
    listener.on_download_complete.assert_awaited_once()
