"""Drive search inside a user's own drive must use that user's index URL."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_search(monkeypatch):
    user_data = {7: {"GDRIVE_ID": "mt:user-drive-id", "INDEX_URL": "https://idx/"}}

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    class GoogleDriveHelper:
        def __init__(self):
            self.use_sa = False
            self.token_path = "token.pickle"
            self.G_DRIVE_DIR_MIME_TYPE = "application/vnd.google-apps.folder"
            self.G_DRIVE_DIR_BASE_DOWNLOAD_URL = (
                "https://drive.google.com/drive/folders/{}"
            )
            self.G_DRIVE_BASE_DOWNLOAD_URL = (
                "https://drive.google.com/uc?id={}&export=download"
            )

    stub(
        "bot",
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        drives_names=[],
        drives_ids=[],
        index_urls=[],
        user_data=user_data,
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.mirror_leech_utils")
    stub("bot.helper.mirror_leech_utils.gdrive_utils")
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size}B",
    )
    stub(
        "bot.helper.mirror_leech_utils.gdrive_utils.helper",
        GoogleDriveHelper=GoogleDriveHelper,
    )

    spec = importlib.util.spec_from_file_location(
        "bot.helper.mirror_leech_utils.gdrive_utils.search",
        ROOT / "bot" / "helper" / "mirror_leech_utils" / "gdrive_utils" / "search.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(
        sys.modules, "bot.helper.mirror_leech_utils.gdrive_utils.search", module
    )
    spec.loader.exec_module(module)
    return module


def test_user_drive_includes_user_index_url(monkeypatch):
    module = _load_search(monkeypatch)
    search = module.GoogleDriveSearch()

    drives = search.get_user_drive("mt:user-drive-id", 7)

    assert drives == [("User Choice", "user-drive-id", "https://idx/")]
