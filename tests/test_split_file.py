"""Tests for split command failure handling."""

from types import SimpleNamespace

import pytest

from bot.helper.ext_utils import files_utils


class _FakeProc:
    returncode = 1

    async def communicate(self):
        return b"", b"split failed"


@pytest.mark.asyncio
async def test_split_file_returns_false_on_failure(monkeypatch, tmp_path):
    async def fake_exec(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(files_utils, "create_subprocess_exec", fake_exec)
    listener = SimpleNamespace(is_cancelled=False, subproc=None)

    result = await files_utils.split_file(
        str(tmp_path / "file.bin"), 1024, listener
    )

    assert result is False
