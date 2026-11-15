"""Tool version reporting in /stats (p7zip and 7-Zip banner formats)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent

P7ZIP_BANNER = (
    "7-Zip [64] 16.02 : Copyright (c) 1999-2016 Igor Pavlov : 2016-05-21\n"
    "\n"
    "p7zip Version 16.02 (locale=C.UTF-8,Utf16=on,HugeFiles=on,64 bits,2 CPUs x64)\n"
    "\n"
    "Libs:\n"
    "- 7z.so:\n"
)

BANNERS = {
    ("blitzfetcher", "--version"): (
        "aria2 version 1.36.0\nCopyright (C) 2006, 2019 Tatsuhiro Tsujikawa\n"
    ),
    ("python3", "--version"): "Python 3.12.3\n",
    ("ghostdrive", "--version"): "rclone v1.65.2\n- os/version: debian 12.5 (64 bit)\n",
    ("yt-dlp", "--version"): "2024.11.18\n",
    ("mediaforge", "-version"): (
        "ffmpeg version 5.1.6-0+deb12u1 Copyright (c) 2000-2023 the FFmpeg developers\n"
    ),
    # Debian bookworm p7zip 16.02 banner (what the Docker image installs).
    ("archiver7", "i"): P7ZIP_BANNER,
}


def _load_stats(monkeypatch, banners=None):
    banners = dict(BANNERS if banners is None else banners)

    async def cmd_exec(command, shell=False):
        out = banners.get(tuple(command), "")
        return out, "", 0 if out else 127

    async def noop(*args, **kwargs):
        return None

    def stub(name, **attrs):
        module = ModuleType(name)
        module.__path__ = []
        for key, value in attrs.items():
            setattr(module, key, value)
        monkeypatch.setitem(sys.modules, name, module)
        return module

    stub("bot", bot_start_time=0.0)
    stub("bot.helper")
    stub("bot.helper.ext_utils")
    stub("bot.helper.telegram_helper")
    stub(
        "bot.helper.ext_utils.status_utils",
        get_readable_file_size=lambda size: f"{size} B",
        get_readable_time=lambda seconds: f"{seconds}s",
    )
    stub(
        "bot.helper.ext_utils.bot_utils",
        cmd_exec=cmd_exec,
        new_task=lambda func: func,
    )
    stub("bot.helper.telegram_helper.message_utils", send_message=noop)
    stub(
        "bot.core",
    )
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
        "bot.modules.stats", ROOT / "bot" / "modules" / "stats.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.modules.stats", module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_every_tool_reports_a_version(monkeypatch):
    module = _load_stats(monkeypatch)
    specs = dict(module.commands)

    await module.get_packages_version()

    versions = {tool: module.commands[tool] for tool in specs}
    assert versions == {
        "aria2": "1.36.0",
        "python": "3.12.3",
        "rclone": "1.65.2",
        "yt-dlp": "2024.11.18",
        "ffmpeg": "5.1.6-0",
        "7z": "16.02",
    }


@pytest.mark.asyncio
async def test_7zip_standalone_banner_is_parsed(monkeypatch):
    banner = "7-Zip 24.09 (x64) : Copyright (c) 1999-2024 Igor Pavlov : 2024-11-29\n"
    module = _load_stats(monkeypatch, {("archiver7", "i"): banner})
    command, regex = module.commands["7z"]

    assert await module.get_version_async(command, regex) == "24.09"
