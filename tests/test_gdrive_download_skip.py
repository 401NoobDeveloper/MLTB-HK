"""Resuming a Drive folder download must skip files already on disk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_gd_download(monkeypatch):
    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    async def noop(*args, **kwargs):
        return None

    class GoogleDriveHelper:
        G_DRIVE_DIR_MIME_TYPE = "application/vnd.google-apps.folder"

        def __init__(self):
            self.proc_bytes = 0
            self.total_files = 0
            self.total_folders = 0
            self.file_processed_bytes = 0
            self.status = None
            self.total_time = 0
            self.use_sa = False
            self.alt_auth = False

        def progress(self):
            return None

    stub(
        "bot",
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.mirror_leech_utils")
    stub("bot.helper.mirror_leech_utils.gdrive_utils")
    stub(
        "bot.helper.ext_utils.bot_utils",
        async_to_sync=noop,
        SetInterval=object,
    )
    stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.helper",
        GoogleDriveHelper=GoogleDriveHelper,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.helper.mirror_leech_utils.gdrive_utils.download",
        ROOT
        / "bot"
        / "helper"
        / "mirror_leech_utils"
        / "gdrive_utils"
        / "download.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules, "bot.helper.mirror_leech_utils.gdrive_utils.download", module
    )
    spec.loader.exec_module(module)
    return module


async def test_folder_download_skips_existing_file(monkeypatch, tmp_path):
    module = _load_gd_download(monkeypatch)
    listener = SimpleNamespace(
        name="folder",
        link="",
        user_id=1,
        size=0,
        is_cancelled=False,
        included_extensions=[],
        excluded_extensions=[],
    )
    downloader = module.GoogleDriveDownload(listener, str(tmp_path))
    existing = tmp_path / "folder" / "existing.mkv"
    existing.parent.mkdir()
    existing.write_bytes(b"abc")

    downloader.get_files_by_folder_id = lambda folder_id: [
        {
            "id": "file-id",
            "name": "existing.mkv",
            "mimeType": "video/x-matroska",
            "size": "3",
        }
    ]
    downloads = []
    downloader._download_file = lambda *args, **kwargs: downloads.append(args)

    downloader._download_folder("root-id", str(tmp_path), "folder")

    assert downloads == []
