"""Deploy scripts must only call InstalledAppFlow methods that still exist."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

SCRIPTS = [
    "add_to_team_drive.py",
    "generate_drive_token.py",
    "gen_sa_accounts.py",
]


def _flow_variables(tree):
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "from_client_secrets_file"
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def test_scripts_only_use_existing_flow_methods():
    flow_module = pytest.importorskip("google_auth_oauthlib.flow")
    flow_class = flow_module.InstalledAppFlow

    problems = []
    for script in SCRIPTS:
        tree = ast.parse((ROOT / script).read_text(encoding="utf-8"))
        flow_vars = _flow_variables(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in flow_vars:
                if not hasattr(flow_class, node.func.attr):
                    problems.append(
                        f"{script}: flow.{node.func.attr}() no longer exists"
                    )

    assert problems == []
