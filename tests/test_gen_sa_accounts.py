"""Service-account key download must not overwrite keys or spin forever."""

from __future__ import annotations

import importlib.util
import sys
from base64 import b64encode
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "gen_sa_accounts", ROOT / "gen_sa_accounts.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "gen_sa_accounts", module)
    spec.loader.exec_module(module)
    return module


class FakeBatch:
    def __init__(self, callback, iam):
        self.callback = callback
        self.iam = iam
        self.count = 0

    def add(self, request):
        self.count += 1

    def execute(self):
        self.iam.executed += 1
        if self.iam.always_fail:
            self.callback("id", None, Exception("boom"))
            return
        for index in range(self.count):
            self.callback(f"id{index}", self.iam.key_response(index), None)


class FakeIam:
    def __init__(self, sas, *, max_batches=10, always_fail=False):
        self.sas = sas
        self.batches = []
        self.executed = 0
        self.max_batches = max_batches
        self.always_fail = always_fail

    def new_batch_http_request(self, callback):
        if len(self.batches) >= self.max_batches:
            raise RuntimeError("too many batch requests")
        batch = FakeBatch(callback, self)
        self.batches.append(batch)
        return batch

    def key_response(self, index):
        data = f"key-{self.executed}-{index}".encode()
        return {
            "name": f"projects/p/serviceAccounts/s/keys/k{index}",
            "privateKeyData": b64encode(data).decode(),
        }

    def projects(self):
        return self

    def serviceAccounts(self):
        return self

    def keys(self):
        return self

    def create(self, **kwargs):
        return object()


def _sas(count):
    return [{"uniqueId": str(i)} for i in range(count)]


def test_keys_of_each_project_are_kept(monkeypatch, tmp_path):
    module = _load(monkeypatch)
    iam = FakeIam(_sas(2))
    monkeypatch.setattr(module, "_list_sas", lambda service, project: service.sas)

    module._create_sa_keys(iam, ["project-one", "project-two"], str(tmp_path))

    files = sorted(path.name for path in tmp_path.iterdir())
    assert files == ["0.json", "1.json", "2.json", "3.json"]
    contents = [(tmp_path / name).read_text() for name in files]
    assert len(set(contents)) == 4


def test_key_download_stops_when_project_has_fewer_accounts(monkeypatch, tmp_path):
    module = _load(monkeypatch)
    iam = FakeIam(_sas(2))
    monkeypatch.setattr(module, "_list_sas", lambda service, project: service.sas)

    module._create_sa_keys(iam, ["project-one"], str(tmp_path))

    assert len(iam.batches) == 1
    assert len(list(tmp_path.iterdir())) == 2


def test_key_download_is_bounded_when_batches_keep_failing(monkeypatch, tmp_path):
    module = _load(monkeypatch)
    iam = FakeIam(_sas(2), max_batches=10, always_fail=True)
    monkeypatch.setattr(module, "_list_sas", lambda service, project: service.sas)

    module._create_sa_keys(iam, ["project-one"], str(tmp_path))

    assert len(iam.batches) == 3
    assert list(tmp_path.iterdir()) == []


def test_account_creation_stops_when_nothing_is_created(monkeypatch):
    module = _load(monkeypatch)
    calls = []

    monkeypatch.setattr(module, "_list_sas", lambda service, project: _sas(40))

    def fake_create(service, project, count):
        calls.append(count)
        if len(calls) > 5:
            raise RuntimeError("still retrying")

    monkeypatch.setattr(module, "_create_accounts", fake_create)

    module._create_remaining_accounts(object(), "project-one")

    assert calls == [60]
