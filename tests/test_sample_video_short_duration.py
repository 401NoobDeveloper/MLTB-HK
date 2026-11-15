"""A short ``-sv`` sample duration must not divide by zero."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load_media_utils(monkeypatch):
    commands = []

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    async def noop(*args, **kwargs):
        return None

    class FakeStdout:
        async def readline(self):
            return b""

        async def read(self, size=-1):
            return b""

        def at_eof(self):
            return True

    class FakeProc:
        returncode = None

        def __init__(self):
            self.stdout = FakeStdout()

        async def communicate(self):
            self.returncode = 0
            return b"", b""

    async def create_subprocess_exec(*cmd, **kwargs):
        commands.append(cmd)
        return FakeProc()

    aioshutil = stub("aioshutil", rmtree=noop)
    aioshutil.rmtree = noop
    stub(
        "bot",
        LOGGER=SimpleNamespace(
            info=lambda *a, **k: None, error=lambda *a, **k: None
        ),
        DOWNLOAD_DIR="/tmp/",
        threads="1",
        cores="0",
    )
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub(
        "bot.helper.ext_utils.bot_utils",
        cmd_exec=noop,
        sync_to_async=noop,
    )
    stub(
        "bot.helper.ext_utils.files_utils",
        get_mime_type=lambda path: "video/mp4",
        is_archive=lambda path: False,
        is_archive_split=lambda path: False,
    )
    stub("bot.helper.ext_utils.status_utils", time_to_seconds=lambda value: 0)
    stub("bot.core")
    stub(
        "bot.core.config_manager",
        BinConfig=SimpleNamespace(
            ARIA2_NAME="blitzfetcher",
            FFMPEG_NAME="mediaforge",
            FFPROBE_NAME="mediaprobe",
            RCLONE_NAME="ghostdrive",
            SEVENZ_NAME="archiver7",
        ),
    )

    spec = importlib.util.spec_from_file_location(
        "bot.helper.ext_utils.media_utils",
        ROOT / "bot" / "helper" / "ext_utils" / "media_utils.py",
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.helper.ext_utils.media_utils", module)
    spec.loader.exec_module(module)

    async def get_media_info(path):
        return 600, None, None

    module.get_media_info = get_media_info
    module.create_subprocess_exec = create_subprocess_exec
    module.commands = commands
    return module


async def test_sample_video_with_short_duration(monkeypatch):
    module = _load_media_utils(monkeypatch)
    listener = SimpleNamespace(is_cancelled=False, subproc=None, subsize=0, size=0)
    ffmpeg = module.FFMpeg(listener)

    result = await ffmpeg.sample_video("downloads/video.mp4", 8, 4)

    assert result == "downloads/SAMPLE.video.mp4"
    assert module.commands, "ffmpeg was never started"
