"""config_sample.py is the documented template: it must expose every setting."""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _config_and_sample(monkeypatch):
    bot = ModuleType("bot")
    bot.__path__ = []
    bot.LOGGER = type(
        "Logger",
        (),
        {
            "info": lambda *a, **k: None,
            "error": lambda *a, **k: None,
            "warning": lambda *a, **k: None,
        },
    )()
    monkeypatch.setitem(sys.modules, "bot", bot)
    spec = importlib.util.spec_from_file_location(
        "bot.core.config_manager", ROOT / "bot" / "core" / "config_manager.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bot.core.config_manager", module)
    spec.loader.exec_module(module)
    sample = runpy.run_path(str(ROOT / "config_sample.py"))
    return module.Config, sample


def test_sample_exposes_every_config_key(monkeypatch):
    config, sample = _config_and_sample(monkeypatch)
    keys = [name for name in vars(config) if name.isupper()]

    missing = sorted(key for key in keys if key not in sample)

    assert missing == []


def test_sample_port_defaults_match_config(monkeypatch):
    config, sample = _config_and_sample(monkeypatch)

    for key in ("BASE_URL_PORT", "RCLONE_SERVE_PORT"):
        assert sample[key] == getattr(config, key), key
