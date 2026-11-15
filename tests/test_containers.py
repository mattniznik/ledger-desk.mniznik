"""The container images: Container Apps run the API and the mock ERP (docs/decisions/0009).

What has to hold in any image, checked on the files themselves; the images are built and run
locally by hand, never pushed from here.
"""

import re
from pathlib import Path

import pytest

from ledger_desk.db import url_for

ROOT = Path(__file__).resolve().parents[1]


def test_the_database_address_comes_from_the_environment_when_set(monkeypatch):
    monkeypatch.delenv("LEDGER_DESK_DB_URL", raising=False)
    assert url_for("ledger_desk") == "postgresql://postgres@127.0.0.1:55432/ledger_desk"  # local default unchanged
    monkeypatch.setenv("LEDGER_DESK_DB_URL", "postgresql://app@db.internal:5432")
    assert url_for("ledger_desk") == "postgresql://app@db.internal:5432/ledger_desk"


def test_the_dockerfile_builds_two_targets_on_a_pinned_base_as_a_non_root_user():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.12-slim(@sha256:[0-9a-f]{64})? AS base$", text, re.M)
    assert re.search(r"COPY --from=ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+ /uv /uvx /bin/", text)  # pinned, per uv's Docker guide
    assert re.search(r"^FROM base AS api$", text, re.M) and re.search(r"^FROM base AS erp$", text, re.M)
    assert "uv sync --locked" in text and "--no-install-project" in text
    users = re.findall(r"^USER (\S+)$", text, re.M)
    assert users and "root" not in users
    cmds = re.findall(r"^CMD (.+)$", text, re.M)
    assert len(cmds) == 2 and all('"--host", "0.0.0.0"' in c for c in cmds)  # reachable from outside the container
    for secret in (".env", "ANTHROPIC", "API_KEY="):
        assert secret not in text, secret


def test_secrets_and_local_clutter_never_enter_the_build_context():
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    for entry in (".env", ".env.*", ".venv", "out", "web", "tests", ".pytest_cache"):
        assert entry in ignored, entry


def test_the_servers_can_listen_beyond_localhost(capsys):
    import pytest

    from ledger_desk.cli import main

    for command in ("api-serve", "erp-serve"):
        with pytest.raises(SystemExit):
            main([command, "--help"])
        assert "--host" in capsys.readouterr().out, command


def test_resetting_a_database_uses_the_same_server_as_connecting_to_it(monkeypatch):
    # db-reset dropped and created the database on the default server while the app connected to the one in
    # LEDGER_DESK_DB_URL (found rehearsing CI on Linux, 2026-11-14): "database ledger_desk_e2e does not exist".
    from ledger_desk.db import admin_url

    monkeypatch.setenv("LEDGER_DESK_DB_URL", "postgresql://app@db.internal:5432")
    assert admin_url() == "postgresql://app@db.internal:5432/postgres"
    monkeypatch.delenv("LEDGER_DESK_DB_URL", raising=False)
    assert admin_url() == "postgresql://postgres@127.0.0.1:55432/postgres"


@pytest.mark.parametrize("url, local", [
    ("postgresql://postgres@127.0.0.1:55432", True),
    ("postgresql://postgres@localhost:55433", True),
    ("postgresql://postgres@[::1]:5432", True),
    ("postgresql://app@db.example.org:5432", False),
    ("postgresql://app@ld-ci-pg:5432", False),
])
def test_only_a_database_on_this_machine_counts_as_local(url, local):
    from ledger_desk.db import is_local

    assert is_local(url) is local


def test_resetting_refuses_a_database_that_is_not_on_this_machine(monkeypatch):
    # db-reset drops the database: with LEDGER_DESK_DB_URL pointing at a deployed server it would drop that one
    from ledger_desk.db import reset_database

    monkeypatch.setenv("LEDGER_DESK_DB_URL", "postgresql://app@db.example.org:5432")
    with pytest.raises(RuntimeError, match="this machine"):
        reset_database("ledger_desk")
